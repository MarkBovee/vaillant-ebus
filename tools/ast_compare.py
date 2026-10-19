#!/usr/bin/env python3
"""Prove that a change only touches comments: compare the syntax trees of the working tree with a git ref.

    python tools/ast_compare.py                              # changed .py files against HEAD
    python tools/ast_compare.py --ref origin/main            # against another ref
    python tools/ast_compare.py --rename old_name=new_name   # a rename the change is allowed to make

Comments and blank lines never appear in a syntax tree, so equal dumps mean no code changed. The exit code is 1 when
any file differs.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# Intent: report whether two Python sources have the same syntax tree.
# Why: this is the proof that a comment-only or formatting-only change did not alter behaviour.
def trees_equal(old_source: str, new_source: str, renames: dict[str, str] | None = None) -> bool:
    for old_name, new_name in (renames or {}).items():
        old_source = old_source.replace(old_name, new_name)
    return ast.dump(ast.parse(old_source)) == ast.dump(ast.parse(new_source))


# Intent: list the Python files that differ between the working tree and a ref.
# Why: only changed files need the comparison, and deleted files have nothing to parse.
def changed_python_files(ref: str, root: Path = ROOT) -> list[str]:
    out = subprocess.check_output(["git", "diff", "--name-only", ref, "--", "*.py"], cwd=root, text=True)
    return [name for name in out.splitlines() if name.strip() and (root / name).exists()]


# Intent: compare every changed Python file with the same file at the ref and print the verdicts.
# Why: one run answers whether a whole change set is comment-only.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--rename", action="append", default=[], metavar="OLD=NEW")
    args = parser.parse_args(argv)
    renames = dict(item.split("=", 1) for item in args.rename)
    differing = 0
    files = changed_python_files(args.ref)
    for name in files:
        try:
            old = subprocess.check_output(["git", "show", f"{args.ref}:{name}"], cwd=ROOT).decode("utf-8")
        except subprocess.CalledProcessError:
            print(f"NEW FILE    {name}")
            differing += 1
            continue
        same = trees_equal(old, (ROOT / name).read_text(encoding="utf-8"), renames)
        print(("AST equal   " if same else "AST DIFFERS ") + name)
        differing += 0 if same else 1
    print(f"{len(files)} files checked, {differing} differ")
    return 1 if differing else 0


if __name__ == "__main__":
    raise SystemExit(main())
