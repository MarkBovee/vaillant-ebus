#!/usr/bin/env python3
"""Compare two discovery dumps from HA and show only changed/new registers."""

import argparse
import os
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml"], check=True)
    import yaml


def ssh(cmd: str, passwd: str) -> str:
    r = subprocess.run(
        [
            "sshpass",
            "-p",
            passwd,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "markbovee@192.168.1.135",
            cmd,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        print(f"SSH error: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


def list_dumps(passwd: str) -> list[tuple[str, str]]:
    """Return sorted [(timestamp, path), ...] from HA."""
    out = ssh("ls -1 /config/vaillant_ebus/discovery_dump_*.yaml 2>/dev/null", passwd)
    if not out:
        print("No dumps found on HA", file=sys.stderr)
        sys.exit(1)
    result = []
    for line in out.split("\n"):
        line = line.strip()
        if not line:
            continue
        ts = line.split("_")[-1].replace(".yaml", "")
        result.append((ts, line))
    return sorted(result, key=lambda x: x[0])


def fetch_dump(path: str, passwd: str) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        local = f.name
    data = ssh(f"cat {path}", passwd)
    with open(local, "w") as f:
        f.write(data)
    with open(local) as f:
        result = yaml.safe_load(f)
    os.unlink(local)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare HA discovery dumps")
    parser.add_argument("--env", default="/mnt/work/Projects/Personal/vaillant-ebus/.env")
    args = parser.parse_args()

    # Read password
    passwd = None
    with open(args.env) as f:
        for line in f:
            if line.startswith("HA_SSH_PASSWORD="):
                passwd = line.strip().split("=", 1)[1]
                break
            if line.startswith("SSH_PASSWORD="):
                passwd = line.strip().split("=", 1)[1]
                break
    if not passwd:
        print("SSH_PASSWORD not found in .env", file=sys.stderr)
        sys.exit(1)

    dumps = list_dumps(passwd)
    if len(dumps) < 2:
        print(f"Need at least 2 dumps, found {len(dumps)}", file=sys.stderr)
        sys.exit(1)

    before_ts, before_path = dumps[-2]
    after_ts, after_path = dumps[-1]
    print(f"Before: {before_ts}  ({before_path})", file=sys.stderr)
    print(f"After:  {after_ts}  ({after_path})", file=sys.stderr)
    print(file=sys.stderr)

    b = fetch_dump(before_path, passwd)
    a = fetch_dump(after_path, passwd)

    bm = {}
    for r in b["registers"]:
        bm[r["circuit"] + "." + r["name"]] = r

    changes = 0
    for r in a["registers"]:
        k = r["circuit"] + "." + r["name"]
        old = bm.get(k)
        if old is None:
            print(f"NEW: {k} = {r.get('value')}")
            changes += 1
        elif old.get("value") != r.get("value"):
            print(f"CHG: {k}: {old.get('value')} -> {r.get('value')}")
            changes += 1

    if changes == 0:
        print("No differences found.")
    else:
        print(f"\n{changes} register(s) changed.")


if __name__ == "__main__":
    main()
