#!/usr/bin/env python3
"""Refuse a release unless hassfest and HACS validation passed on the tagged commit.

Used by the ``release`` job in ``.github/workflows/ci.yml``. Those two checks run in
separate workflows, so a tag pushed early could publish a release whose hassfest run
later failed (1.10.5). The gate polls the check runs of the exact commit and fails the
job unless every required check finished with ``success``::

    python tools/release_gate.py <owner/repo> <sha> [--timeout 900]

Needs ``gh`` and ``GH_TOKEN`` in the environment (provided by GitHub Actions).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence

REQUIRED_CHECKS: tuple[str, ...] = ("validate", "validate-hacs")


def evaluate(check_runs: Sequence[Mapping[str, object]], required: Sequence[str] = REQUIRED_CHECKS) -> tuple[str, str]:
    """Return ``(state, detail)`` where state is ``pass``, ``fail`` or ``pending``."""
    by_name: dict[str, Mapping[str, object]] = {}
    for run in check_runs:
        by_name[str(run.get("name"))] = run
    pending: list[str] = []
    for name in required:
        run = by_name.get(name)
        if run is None or run.get("status") != "completed":
            pending.append(name)
            continue
        if run.get("conclusion") != "success":
            return "fail", f"{name} concluded {run.get('conclusion')}"
    if pending:
        return "pending", "waiting for " + ", ".join(pending)
    return "pass", "all required checks succeeded"


def _fetch_check_runs(repo: str, sha: str) -> list[dict[str, object]]:
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/commits/{sha}/check-runs", "--paginate", "--jq", ".check_runs[]"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def wait_for_gate(
    fetch: Callable[[], Sequence[Mapping[str, object]]],
    timeout: float,
    interval: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[bool, str]:
    deadline = clock() + timeout
    while True:
        state, detail = evaluate(fetch())
        if state == "pass":
            return True, detail
        if state == "fail":
            return False, detail
        if clock() >= deadline:
            return False, f"timeout: {detail}"
        sleep(interval)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("sha")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv)
    ok, detail = wait_for_gate(lambda: _fetch_check_runs(args.repo, args.sha), args.timeout)
    print(("RELEASE GATE OK: " if ok else "RELEASE GATE FAILED: ") + detail, file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
