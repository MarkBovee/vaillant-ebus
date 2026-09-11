#!/usr/bin/env python3
"""Keep the release version identical across the places that carry it.

The version lives in three places:

- ``pyproject.toml`` (PEP 440: ``1.8.0rc2``)
- ``custom_components/vaillant_ebus/manifest.json`` (display: ``1.8.0-rc2``)
- the top ``## <version>`` heading in ``CHANGELOG.md``

Usage::

    python tools/version.py check
    python tools/version.py bump 1.8.0
    python tools/version.py bump 1.8.0-rc3

``check`` exits non-zero when the three do not agree. It is enforced by
``tests/test_version_consistency.py`` so CI fails on drift. ``bump`` updates
``pyproject.toml`` and ``manifest.json``; add the matching CHANGELOG heading
yourself because release notes are human-written.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
MANIFEST = ROOT / "custom_components" / "vaillant_ebus" / "manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"


def canonical(version: str) -> str:
    """Normalize ``1.8.0-rc2`` / ``1.8.0rc2`` / ``1.8.0`` for comparison."""
    return re.sub(r"[^0-9a-z]", "", version.strip().lower())


def read_pyproject() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    if match is None:
        raise SystemExit("version not found in pyproject.toml")
    return match.group(1)


def read_manifest() -> str:
    return str(json.loads(MANIFEST.read_text())["version"])


def read_changelog_headings() -> list[str]:
    return re.findall(r"^##\s+(\S+)", CHANGELOG.read_text(), re.MULTILINE)


def check() -> int:
    pyproject, manifest, headings = read_pyproject(), read_manifest(), read_changelog_headings()
    problems: list[str] = []
    if canonical(pyproject) != canonical(manifest):
        problems.append(f"pyproject.toml ({pyproject}) != manifest.json ({manifest})")
    if not any(canonical(heading) == canonical(manifest) for heading in headings):
        problems.append(f"CHANGELOG.md has no '## {manifest}' heading")
    if problems:
        for problem in problems:
            print(f"VERSION MISMATCH: {problem}", file=sys.stderr)
        return 1
    print(f"version in sync: {manifest}")
    return 0


def bump(new: str) -> int:
    pyproject_text = PYPROJECT.read_text()
    pyproject_new = re.sub(
        r'(^version\s*=\s*")([^"]+)(")',
        lambda m: f"{m.group(1)}{new}{m.group(3)}",
        pyproject_text,
        count=1,
        flags=re.MULTILINE,
    )
    if pyproject_new == pyproject_text:
        print("version not found in pyproject.toml", file=sys.stderr)
        return 1
    PYPROJECT.write_text(pyproject_new)

    manifest_text = MANIFEST.read_text()
    manifest_new = re.sub(
        r'("version"\s*:\s*")([^"]+)(")',
        lambda m: f"{m.group(1)}{new}{m.group(3)}",
        manifest_text,
        count=1,
    )
    if manifest_new == manifest_text:
        print('version not found in manifest.json', file=sys.stderr)
        return 1
    MANIFEST.write_text(manifest_new)
    print(f"bumped to {new}; add the matching '## {new}' heading to CHANGELOG.md")
    return check()


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("check", "bump"):
        print(__doc__, file=sys.stderr)
        return 2
    if argv[1] == "check":
        return check()
    if len(argv) < 3:
        print("usage: python tools/version.py bump X.Y.Z", file=sys.stderr)
        return 2
    return bump(argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
