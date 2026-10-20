#!/usr/bin/env python3
"""Check the Home Assistant translation rules that hassfest enforces and local tests used to miss.

    python tools/check_translations.py

Rules checked for ``strings.json`` and every ``translations/*.json``:

- the file is valid JSON;
- an entry under ``issues`` has a ``title`` and either a ``description`` (not fixable) or a ``fix_flow`` (fixable),
  never both (hassfest: "two or more values in the same group of exclusion 'fixable'").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "vaillant_ebus"


# Return the translation files hassfest validates for this integration.
# strings.json and every language file follow the same schema.
def translation_files(component: Path = COMPONENT) -> list[Path]:
    files = [component / "strings.json", *sorted((component / "translations").glob("*.json"))]
    return [path for path in files if path.exists()]


# Validate the `issues` section of one parsed translation file.
# A fixable repair must carry its text in fix_flow; a top-level description makes hassfest fail.
def issue_problems(data: dict[str, object]) -> list[str]:
    problems: list[str] = []
    issues = data.get("issues", {})
    if not isinstance(issues, dict):
        return ["issues must be an object"]
    for key, issue in issues.items():
        if not isinstance(issue, dict):
            problems.append(f"issues.{key} must be an object")
            continue
        if "title" not in issue:
            problems.append(f"issues.{key} has no title")
        if "description" in issue and "fix_flow" in issue:
            problems.append(f"issues.{key} has both description and fix_flow (fixable exclusion group)")
        if "description" not in issue and "fix_flow" not in issue:
            problems.append(f"issues.{key} needs a description or a fix_flow")
    return problems


# Check every translation file and print the problems found.
# One command gives CI parity for the translation rules.
def main() -> int:
    failed = False
    for path in translation_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            print(f"{path.name}: invalid JSON: {error}")
            failed = True
            continue
        for problem in issue_problems(data):
            print(f"{path.name}: {problem}")
            failed = True
    print("translations: FAILED" if failed else "translations: ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
