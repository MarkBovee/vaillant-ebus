#!/usr/bin/env python3
"""Run the CI checks locally in one command and compare test failures with a known-environment baseline.

    python tools/validate.py            # everything CI runs, then pytest
    python tools/validate.py --quick    # skip pytest
    python tools/validate.py --tests-only -k issue171

On Windows a few tests fail for environment reasons only (CRLF checkout changes fixture digests, the bash-based
search tool tests, one timing test). They are listed in ``tools/known_env_failures.txt`` and ignored there; any other
failure fails the run. On Linux/macOS the baseline is not applied.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = ROOT / "tools" / "known_env_failures.txt"
# Keep in sync with the "Format check" and "Type check" steps of .github/workflows/checks.yml.
FORMAT_TARGETS = ["custom_components"]
MYPY_TARGETS = ["custom_components/vaillant_ebus/backend"]


# Intent: pick the repository virtualenv interpreter for the current OS, falling back to the running Python.
# Why: tools must run the same ruff/pytest versions the project is developed with.
def venv_python() -> str:
    for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


# Intent: read the baseline of environment-only failing test ids (prefix match, comments allowed).
# Why: Windows checkouts fail a handful of tests for reasons unrelated to the change under test.
def load_baseline(path: Path = BASELINE_FILE) -> list[str]:
    if not path.exists():
        return []
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


# Intent: split failing test ids into known-environment and new failures.
# Why: only new failures should fail a local run.
def classify_failures(failures: list[str], baseline: list[str]) -> tuple[list[str], list[str]]:
    known = [item for item in failures if any(item.startswith(prefix) for prefix in baseline)]
    return known, [item for item in failures if item not in known]


# Intent: extract failing node ids from pytest's short summary.
# Why: the baseline comparison needs stable ids, not the raw log.
def parse_failures(output: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"^(?:FAILED|ERROR) (\S+)", output, re.MULTILINE)]


# Intent: run one named step and report pass or fail without aborting the remaining steps.
# Why: a single run should list every problem, not only the first.
def run_step(name: str, command: list[str], results: dict[str, bool]) -> subprocess.CompletedProcess[str]:
    print(f"\n== {name}")
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    output = (completed.stdout + completed.stderr).strip()
    print(output[-2500:] if output else "(no output)")
    results[name] = completed.returncode == 0
    return completed


# Intent: run the YAML syntax check CI applies to every *.yml/*.yaml file in the repository.
# Why: a broken fixture or workflow should fail locally, not in CI.
def check_yaml(python: str, results: dict[str, bool]) -> None:
    code = (
        "import pathlib,yaml,sys\n"
        "bad=[]\n"
        "for pat in ('*.yml','*.yaml'):\n"
        "    for p in pathlib.Path('.').rglob(pat):\n"
        "        if {'.venv','.git'} & set(p.parts): continue\n"
        "        try: yaml.safe_load(p.read_text(encoding='utf-8'))\n"
        "        except Exception as e: bad.append(f'{p}: {str(e)[:80]}')\n"
        "print('\\n'.join(bad)); sys.exit(1 if bad else 0)\n"
    )
    run_step("yaml", [python, "-c", code], results)


# Intent: orchestrate the CI-equivalent checks.
# Why: release candidates need CI parity before a tag is pushed (a failing hassfest once shipped in a tag).
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip pytest")
    parser.add_argument("--tests-only", action="store_true", help="run only pytest")
    parser.add_argument("-k", dest="expression", default="", help="pytest -k expression")
    args = parser.parse_args()
    python = venv_python()
    results: dict[str, bool] = {}

    if not args.tests_only:
        run_step("ruff check", [python, "-m", "ruff", "check", "."], results)
        run_step("ruff format", [python, "-m", "ruff", "format", "--check", *FORMAT_TARGETS], results)
        run_step("mypy --strict", [python, "-m", "mypy", "--strict", "--follow-imports=skip", *MYPY_TARGETS], results)
        run_step("version", [python, "tools/version.py", "check"], results)
        run_step("translations (hassfest rules)", [python, "tools/check_translations.py"], results)
        check_yaml(python, results)
        run_step("compileall", [python, "-m", "compileall", "-q", "-f", "custom_components/vaillant_ebus/"], results)
        run_step("git diff --check", ["git", "diff", "--check", "HEAD"], results)

    if not args.quick:
        command = [python, "-m", "pytest", "-q", "-rf", "tests/"]
        if args.expression:
            command += ["-k", args.expression]
        completed = run_step("pytest", command, results)
        failures = parse_failures(completed.stdout + completed.stderr)
        baseline = load_baseline() if sys.platform == "win32" else []
        known, new = classify_failures(failures, baseline)
        results["pytest"] = not new
        print(f"pytest: {len(failures)} failed, {len(known)} known environment failures, {len(new)} new")
        for item in new:
            print(f"  NEW FAILURE: {item}")

    print("\nSummary")
    for name, ok in results.items():
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
