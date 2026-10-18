#!/usr/bin/env python3
"""Print which hardware variants the test suite covers, and only through which fixtures.

Everything except the owner's HMU00/CTLV2 system rests on community captures. This tool
makes that visible: it reads the ``scanned:`` lines of every fixture under
``tests/fixtures/community`` (``ID=<device>;SW=..;HW=..``), counts how many test files
reference each fixture, and prints a Markdown table per hardware variant.

    python tools/hardware_matrix.py            # Markdown to stdout (CI step summary)
    python tools/hardware_matrix.py --fail-on-untested   # exit 1 if a variant has no test reference
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "community"
TESTS = ROOT / "tests"
SCAN_RE = re.compile(r"scanned:\s*MF=[^;]*;ID=([A-Za-z0-9]+);SW=(\w+);HW=(\w+)")
# Devices that only relay or gateway data; they are not a heat-pump or controller variant.
IGNORED_IDS = frozenset({"NETX2", "NETX3"})


def fixture_variants(path: Path) -> set[str]:
    """Return ``{"HMUX0 SW0406/HW0504", ...}`` for every scanned device in one fixture."""
    text = path.read_text(errors="replace")
    return {f"{dev} SW{sw}/HW{hw}" for dev, sw, hw in SCAN_RE.findall(text) if dev not in IGNORED_IDS}


def test_references(fixture_name: str) -> int:
    """Count test files that name the fixture (by file name, with or without extension)."""
    stem = Path(fixture_name).stem
    return sum(1 for test in TESTS.glob("test_*.py") if stem in test.read_text(errors="replace"))


def build_matrix() -> dict[str, dict[str, int]]:
    """Map variant -> {fixture file name: number of referencing test files}."""
    matrix: dict[str, dict[str, int]] = defaultdict(dict)
    for path in sorted(FIXTURES.glob("*.yaml")):
        for variant in fixture_variants(path):
            matrix[variant][path.name] = test_references(path.name)
    return dict(matrix)


def render(matrix: dict[str, dict[str, int]]) -> str:
    lines = [
        "## Hardware coverage (community fixtures)",
        "",
        "| Variant | Fixtures | Referenced by tests | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    for variant in sorted(matrix):
        fixtures = matrix[variant]
        referenced = sum(1 for count in fixtures.values() if count)
        status = "ok" if referenced else "NO TEST REFERENCE"
        lines.append(f"| {variant} | {len(fixtures)} | {referenced} | {status} |")
    lines += ["", "Variants with a single fixture rest on one capture; treat changes there with care.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fail-on-untested", action="store_true")
    args = parser.parse_args(argv)
    matrix = build_matrix()
    print(render(matrix))
    if args.fail_on_untested and any(not any(f.values()) for f in matrix.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
