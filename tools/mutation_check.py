#!/usr/bin/env python3
"""Measure how well the tests guard one source file by mutating its conditions.

For every comparison, ``and``/``or``, ``not`` and non-constant ``return`` in the target file this
tool applies one change, runs pytest, and reports mutants that no test noticed (survivors).
Survivors mark logic that can change without a failing test, so they show where a test is
missing or too weak. Run it on small pure modules, for example::

    python tools/mutation_check.py custom_components/vaillant_ebus/backend/hardware_profiles.py \\
        tests/test_hardware_profiles.py

Everything after the target is passed to pytest (default: ``tests``). The target file is restored
afterwards, also on Ctrl+C. A hanging mutant counts as caught (timeout). Some survivors are equivalent
mutants (the changed code behaves identically); judge each one by reading the reported line.
"""

from __future__ import annotations

import ast
import copy
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 240
_SWAP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,
    ast.LtE: ast.Gt,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}


@dataclass(frozen=True)
class Mutant:
    kind: str
    line: int
    index: int  # position of the node in ast.walk order
    op_index: int = 0


# Intent: list every mutation site of a module in a stable order.
# Why: the same site list must be reproducible across runs so survivors can be compared.
def find_mutants(tree: ast.AST) -> list[Mutant]:
    mutants: list[Mutant] = []
    for index, node in enumerate(ast.walk(tree)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Compare):
            mutants += [Mutant("compare", line, index, i) for i, op in enumerate(node.ops) if type(op) in _SWAP]
        elif isinstance(node, ast.BoolOp):
            mutants.append(Mutant("boolop", line, index))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            mutants.append(Mutant("not", line, index))
        elif isinstance(node, ast.Return) and node.value is not None and not isinstance(node.value, ast.Constant):
            mutants.append(Mutant("return", line, index))
    return mutants


def _replace_child(tree: ast.AST, old: ast.AST, new: ast.AST) -> None:
    for parent in ast.walk(tree):
        for name, value in ast.iter_fields(parent):
            if value is old:
                setattr(parent, name, new)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if item is old:
                        value[i] = new


# Intent: produce the source text of the module with exactly one mutation applied.
# Why: one change per run attributes a surviving mutant to one specific condition.
def apply_mutant(tree: ast.AST, mutant: Mutant) -> str:
    clone = copy.deepcopy(tree)
    node = list(ast.walk(clone))[mutant.index]
    if mutant.kind == "compare":
        assert isinstance(node, ast.Compare)
        node.ops[mutant.op_index] = _SWAP[type(node.ops[mutant.op_index])]()
    elif mutant.kind == "boolop":
        assert isinstance(node, ast.BoolOp)
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif mutant.kind == "not":
        assert isinstance(node, ast.UnaryOp)
        _replace_child(clone, node, node.operand)
    elif mutant.kind == "return":
        assert isinstance(node, ast.Return)
        node.value = ast.Constant(value=None)
    ast.fix_missing_locations(clone)
    return ast.unparse(clone)


def _tests_pass(pytest_args: list[str]) -> bool:
    command = [sys.executable, "-m", "pytest", "-q", "-x", "--tb=no", "-p", "no:cacheprovider", *pytest_args]
    try:
        return subprocess.run(command, cwd=ROOT, capture_output=True, timeout=TIMEOUT_SECONDS).returncode == 0
    except subprocess.TimeoutExpired:
        return False  # a hanging mutant is noticed by the tests


# Intent: run every mutant against the tests and yield (mutant, survived).
# Why: the caller prints progress; the file is always restored, even when interrupted.
def run(target: Path, pytest_args: list[str]) -> Iterator[tuple[Mutant, bool]]:
    original = target.read_text()
    tree = ast.parse(original)
    try:
        for mutant in find_mutants(tree):
            target.write_text(apply_mutant(tree, mutant))
            yield mutant, _tests_pass(pytest_args)
    finally:
        target.write_text(original)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 2
    target = (ROOT / args[0]).resolve()
    pytest_args = args[1:] or ["tests"]
    survivors: list[Mutant] = []
    total = 0
    for mutant, survived in run(target, pytest_args):
        total += 1
        if survived:
            survivors.append(mutant)
            print(f"SURVIVED {mutant.kind} at line {mutant.line}", flush=True)
    print(f"{total} mutants, {len(survivors)} survived, {total - len(survivors)} caught")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
