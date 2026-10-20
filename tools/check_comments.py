#!/usr/bin/env python3
"""List functions that a diff adds or changes and that lack the required comment block above them.

    python tools/check_comments.py                # compares origin/main...HEAD
    python tools/check_comments.py v1.12.0        # compares v1.12.0...HEAD

The project rule (AGENTS.md) is that every test has an `# Intent:` and a `# Why:` comment, and that every function in
code (`custom_components/`, `tools/`) has a normal comment above it. `tools/validate.py` does not check it, so run this
before a review. Only Python files are looked at; the exit code is 1 when something is missing.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


# Turn the text of `git diff -U0` into the added line numbers per file.
# A function counts as touched when its `def` line is inside an added or changed hunk.
def parse_added_lines(diff_text: str) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    current = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            result.setdefault(current, set())
            continue
        match = HUNK.match(line)
        if match and current:
            start, count = int(match.group(1)), int(match.group(2) or 1)
            result[current].update(range(start, start + count))
    return result


# Return the comment block directly above a function, above its decorators.
# The rule is about the lines a reader sees before the function, and decorators sit between them.
def comment_block(lines: list[str], node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    first = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
    index = first - 2
    block: list[str] = []
    while index >= 0 and lines[index].lstrip().startswith("#"):
        block.append(lines[index])
        index -= 1
    return "\n".join(reversed(block))


# Tests keep the strict `# Intent:` and `# Why:` pair; all other code only needs a normal comment (see AGENTS.md).
def is_test_path(name: str) -> bool:
    return name.startswith("tests/")


# Find the functions on the given lines that lack the required comment block. With `strict` (tests) the block must hold
# `Intent:` and `Why:`; without it (code) any comment text above the function is enough. This is the pure core of the
# check, so a test can feed it source text without git.
def find_missing(source: str, touched_lines: set[int], strict: bool = True) -> list[tuple[int, str, str]]:
    lines = source.splitlines()
    missing: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.lineno not in touched_lines:
            continue
        block = comment_block(lines, node)
        has_intent, has_why = "Intent:" in block, "Why:" in block
        has_comment = any(line.lstrip("# \t") for line in block.splitlines())
        if not ((has_intent and has_why) if strict else has_comment):
            have = "/".join(name for name, present in (("Intent", has_intent), ("Why", has_why)) if present)
            missing.append((node.lineno, node.name, have or "none"))
    return sorted(missing)


# Read the added lines of every changed Python file between a base ref and HEAD.
# Only new or changed functions are checked, so old code does not drown the result.
def changed_lines(base: str, root: Path = ROOT) -> dict[str, set[int]]:
    diff = subprocess.check_output(
        ["git", "diff", "-U0", f"{base}...HEAD", "--", "*.py"], cwd=root, text=True, encoding="utf-8"
    )
    return parse_added_lines(diff)


# Print the functions without the required comment and return a shell exit code. A missing comment is a blocking review
# finding in this repository, never a style nit; tests need the strict Intent/Why pair, other code any comment.
def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    base = args[0] if args else "origin/main"
    findings: list[str] = []
    for name, touched in changed_lines(base).items():
        path = ROOT / name
        if path.suffix != ".py" or not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for lineno, function, have in find_missing(source, touched, strict=is_test_path(name)):
            findings.append(f"{name}:{lineno} {function} (has: {have})")
    print(f"{len(findings)} functions without the required comment (tests: Intent and Why, code: any comment)")
    for finding in findings:
        print(f"  {finding}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
