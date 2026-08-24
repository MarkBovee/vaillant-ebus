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


def ssh(cmd: str, passwd: str, user: str, host: str) -> str:
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
            f"{user}@{host}",
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


def list_dumps(passwd: str, user: str, host: str) -> list[tuple[str, str]]:
    """Return sorted [(timestamp, path), ...] from HA."""
    out = ssh("ls -1 /config/vaillant_ebus/discovery_dump_*.yaml 2>/dev/null", passwd, user, host)
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


def fetch_dump(path: str, passwd: str, user: str, host: str) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        local = f.name
    data = ssh(f"cat {path}", passwd, user, host)
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

    # Read connection settings from .env
    env: dict[str, str] = {}
    with open(args.env) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key] = value
    passwd = env.get("HA_SSH_PASSWORD")
    user = env.get("HA_SSH_USER")
    host = env.get("HA_HOST")
    missing = [
        name
        for name, val in (("HA_SSH_PASSWORD", passwd), ("HA_SSH_USER", user), ("HA_HOST", host))
        if not val
    ]
    if missing:
        print(f"Missing {', '.join(missing)} in {args.env}", file=sys.stderr)
        sys.exit(1)

    dumps = list_dumps(passwd, user, host)
    if len(dumps) < 2:
        print(f"Need at least 2 dumps, found {len(dumps)}", file=sys.stderr)
        sys.exit(1)

    before_ts, before_path = dumps[-2]
    after_ts, after_path = dumps[-1]
    print(f"Before: {before_ts}  ({before_path})", file=sys.stderr)
    print(f"After:  {after_ts}  ({after_path})", file=sys.stderr)
    print(file=sys.stderr)

    b = fetch_dump(before_path, passwd, user, host)
    a = fetch_dump(after_path, passwd, user, host)

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
