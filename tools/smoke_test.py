#!/usr/bin/env python3
"""Check the release smoke test on the owner's Home Assistant: the two newest discovery dumps and ebusd's grab state.

    python tools/smoke_test.py            # read the two newest dumps over SSH, check them, run `grab result all`
    python tools/smoke_test.py --local A.yaml B.yaml   # check dump files that are already on disk

Run it after the two `vaillant_ebus.export_discovery_dump` calls of docs/release-process.md (`grab_duration: 0`, then
a short positive duration, both through HA-MCP). It does steps 3 to 5 of that procedure, which every release since
1.11 scripted by hand: read both files, require `metadata`, `raw_find_lines`, `before_registers` and `registers`, check
the grab fields of each dump, and confirm `grab result all` does not answer `grab disabled`. Step 6 (fresh HA logs and
repairs) stays with HA-MCP.

Credentials come from the git-ignored `.env` through `tools/ha_snapshot.py`, stay inside this process and are never
printed. Every remote command only reads. Exit code 0 means the smoke test passed; deviations print as `DEVIATION`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SECTIONS = ("metadata", "raw_find_lines", "before_registers", "registers")
DUMP_GLOB = "/config/vaillant_ebus/discovery_dump_*.yaml"
# Asks ebusd on the HA host for the grab result and prints only the line count and whether grab is disabled.
GRAB_SCRIPT = (
    "import socket;s=socket.create_connection(('127.0.0.1',8888),10);s.sendall(b'grab result all\\n');"
    "buf=b''\nwhile not buf.endswith(b'\\n\\n'):\n  c=s.recv(65536)\n  if not c: break\n  buf+=c\n"
    "t=buf.decode('utf-8','replace');print(len(t.splitlines()), 'grab disabled' in t)"
)


# List the problems of one parsed dump; an empty list means it passes.
# The zero-second dump must not have grabbed; the positive one must have captured or continued a grab, and a
# `skipped_active` result is a deviation the release plan records (the service fell back to a register-only dump).
def check_dump(data: Any, name: str) -> tuple[list[str], list[str]]:
    if not isinstance(data, dict):
        return [f"{name}: not a YAML mapping"], []
    failures = [f"{name}: missing section {section}" for section in REQUIRED_SECTIONS if section not in data]
    deviations: list[str] = []
    metadata = data.get("metadata") or {}
    duration = grab_duration(data)
    status = metadata.get("grab_status")
    if duration == 0:
        if status != "not_requested":
            failures.append(f"{name}: zero-second dump has grab_status {status!r}, expected 'not_requested'")
        if metadata.get("grab_captured_duration") not in (0, 0.0):
            failures.append(f"{name}: zero-second dump captured {metadata.get('grab_captured_duration')!r} s")
        return failures, deviations
    if status == "skipped_active":
        deviations.append(f"{name}: grab skipped_active ({metadata.get('grab_error') or 'no reason given'})")
    elif status not in ("continued", "captured"):
        failures.append(f"{name}: positive dump has grab_status {status!r}, expected 'continued' or 'captured'")
    elif not (metadata.get("grab_captured_duration") or 0) > 0:
        failures.append(f"{name}: positive dump captured no time")
    return failures, deviations


# Return the requested grab duration of a parsed dump, 0 when it is missing or the dump is not a mapping.
def grab_duration(data: Any) -> float:
    metadata = data.get("metadata") if isinstance(data, dict) else None
    return float((metadata or {}).get("grab_duration") or 0)


# Check a set of dumps: one must be the zero-second dump and one a positive-duration dump.
# Returns the failures and the deviations of all of them together.
def check_dumps(dumps: dict[str, Any]) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    deviations: list[str] = []
    durations = []
    for name, data in dumps.items():
        dump_failures, dump_deviations = check_dump(data, name)
        failures += dump_failures
        deviations += dump_deviations
        durations.append(grab_duration(data))
    if 0 not in durations:
        failures.append("no zero-second dump among the newest files: call export_discovery_dump with grab_duration 0")
    if not any(duration > 0 for duration in durations):
        failures.append("no positive-duration dump among the newest files: call it again with grab_duration 1")
    return failures, deviations


# Read the newest dumps and the grab state from the HA host over the read-only SSH path.
def read_remote(count: int) -> tuple[dict[str, Any], str]:
    sys.path.insert(0, str(ROOT / "tools"))
    import ha_snapshot  # noqa: PLC0415  (pulls in paramiko only when the remote path is used)

    client = ha_snapshot.connect()
    try:
        paths = ha_snapshot.run_read(client, f"ls -t {DUMP_GLOB}").split()[:count]
        dumps = {path.rsplit("/", 1)[-1]: yaml.safe_load(ha_snapshot.run_read(client, f"cat {path}")) for path in paths}
        grab = ha_snapshot.run_read(client, f'python3 -c "{GRAB_SCRIPT}"')
    finally:
        client.close()
    return dumps, grab


# Turn the remote `grab result all` answer ("<lines> <disabled>") into a failure list.
def check_grab(answer: str) -> list[str]:
    parts = answer.split()
    if len(parts) != 2:
        return [f"grab result all: unexpected answer {answer[:80]!r}"]
    if parts[1] == "True":
        return ["grab result all answers 'grab disabled' after the positive-duration export"]
    return []


# Print the result and return the exit code.
def report(failures: list[str], deviations: list[str], names: list[str]) -> int:
    print("checked:", ", ".join(names) or "nothing")
    for line in deviations:
        print("DEVIATION", line)
    for line in failures:
        print("FAIL", line)
    print("smoke test", "FAILED" if failures else "passed")
    return 1 if failures else 0


# Parse the arguments and run the remote or the local check.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--local", nargs="+", type=Path, help="check these dump files instead of reading the host")
    parser.add_argument("--count", type=int, default=2, help="number of newest dumps to read from the host")
    args = parser.parse_args(argv)
    if args.local:
        dumps = {path.name: yaml.safe_load(path.read_text(encoding="utf-8")) for path in args.local}
        failures, deviations = check_dumps(dumps)
        return report(failures, deviations, list(dumps))
    dumps, grab = read_remote(args.count)
    failures, deviations = check_dumps(dumps)
    failures += check_grab(grab)
    return report(failures, deviations, list(dumps))


if __name__ == "__main__":
    raise SystemExit(main())
