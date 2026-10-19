#!/usr/bin/env python3
"""Read-only snapshots of the owner's Home Assistant host, for tests and evidence.

    python tools/ha_snapshot.py registry [--out DIR]   # entity and device registry rows of vaillant_ebus
    python tools/ha_snapshot.py dump [--out DIR]       # newest discovery dump from /config/vaillant_ebus
    python tools/ha_snapshot.py compare [REF]          # integration files on the host against a git ref

Why it exists: registry code passed its unit tests but failed on Home Assistant 2026.10 because the fakes did not match
the live shape. The registry rows show the real shape; the comparison shows whether the host runs a given release.

Credentials come from the git-ignored `.env` through `tools/deploy_ha.py`, stay inside this process and are never
printed. Every remote command only reads. The output goes to `.research-scratch/ha-snapshot` by default (git-ignored).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_PREFIX = "custom_components/vaillant_ebus/"
DEFAULT_OUT = ROOT / ".research-scratch" / "ha-snapshot"

# Remote one-liner: this integration's entity rows, and the devices they belong to or that carry its identifiers.
REGISTRY_SCRIPT = (
    "import json;"
    'e=json.load(open("/config/.storage/core.entity_registry"))["data"]["entities"];'
    'd=json.load(open("/config/.storage/core.device_registry"))["data"]["devices"];'
    'ours=[x for x in e if x.get("platform")=="vaillant_ebus"];'
    'ids={x.get("device_id") for x in ours};'
    'dev=[x for x in d if x.get("id") in ids or any(i[0]=="vaillant_ebus" for i in x.get("identifiers",[]))];'
    'print(json.dumps({"entities":ours,"devices":dev}))'
)

# Remote one-liner: sha256 of every integration file with CRLF folded to LF, keyed by the path below the component.
HASH_SCRIPT = (
    'import hashlib,json,os;root="/config/custom_components/vaillant_ebus";out={};'
    '[out.__setitem__(os.path.relpath(os.path.join(d,f),root).replace(os.sep,"/"),'
    'hashlib.sha256(open(os.path.join(d,f),"rb").read().replace(b"\\r\\n",b"\\n")).hexdigest())'
    ' for d,_,fs in os.walk(root) if "__pycache__" not in d for f in fs if not f.endswith((".pyc",".pyo"))];'
    "print(json.dumps(out))"
)


# Intent: hash file content with line endings folded to LF.
# Why: a Windows checkout deploys CRLF files while git stores LF, and the comparison must not report that as a change.
def normalized_sha256(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


# Intent: split two path-to-hash maps into files only on the host, only in git, and with different content.
# Why: those three lists are the whole answer to "does the host run this release".
def diff_hashes(remote: dict[str, str], local: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    only_remote = sorted(set(remote) - set(local))
    only_local = sorted(set(local) - set(remote))
    different = sorted(name for name in set(remote) & set(local) if remote[name] != local[name])
    return only_remote, only_local, different


# Intent: hash every integration file of a git ref, keyed like the host listing.
# Why: the host hashes are compared with the content of the commit or tag that should be deployed.
def git_hashes(ref: str, root: Path = ROOT) -> dict[str, str]:
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", ref, COMPONENT_PREFIX], cwd=root, text=True
    ).splitlines()
    return {
        name[len(COMPONENT_PREFIX) :]: normalized_sha256(
            subprocess.check_output(["git", "show", f"{ref}:{name}"], cwd=root)
        )
        for name in names
        if name.strip()
    }


# Intent: open one SSH session to the Home Assistant host with the credentials of the repository `.env`.
# Why: the deploy tool already owns the credential handling, so this tool never reads or prints them itself.
def connect() -> Any:
    sys.path.insert(0, str(ROOT / "tools"))
    import deploy_ha  # noqa: PLC0415  (imports paramiko lazily, only when a snapshot is requested)
    import paramiko  # noqa: PLC0415

    env = deploy_ha.load_env(ROOT / ".env")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        env["HA_HOST"],
        port=int(env.get("HA_SSH_PORT", "22")),
        username=env["HA_SSH_USER"],
        password=env["HA_SSH_PASSWORD"],
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    return client


# Intent: run one read-only command on the host, with sudo first and plain as the fallback.
# Why: the SSH add-on user may or may not need sudo for /config/.storage and /config/vaillant_ebus.
def run_read(client: Any, command: str) -> str:
    sys.path.insert(0, str(ROOT / "tools"))
    import deploy_ha  # noqa: PLC0415

    status, output = deploy_ha.run_remote(client, f"sudo -n {command}")
    if status != 0:
        status, output = deploy_ha.run_remote(client, command)
    if status != 0:
        raise RuntimeError(f"remote read failed (exit {status}): {output[:200]}")
    return output


# Intent: save the integration's registry rows and devices as JSON.
# Why: the rows show the real stored shape (aliases, disabled_by, labels) that unit-test fakes must copy.
def snapshot_registry(out_dir: Path) -> Path:
    client = connect()
    try:
        data = json.loads(run_read(client, f"python3 -c '{REGISTRY_SCRIPT}'"))
    finally:
        client.close()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "registry_ours.json"
    target.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"saved {len(data['entities'])} entity rows and {len(data['devices'])} devices to {target}")
    return target


# Intent: save the newest discovery dump of the host.
# Why: the dump holds every register value, which is the evidence for what the entity factory should decide.
def snapshot_dump(out_dir: Path) -> Path:
    client = connect()
    try:
        newest = run_read(client, "ls -t /config/vaillant_ebus/discovery_dump_*.yaml").splitlines()[0].strip()
        content = run_read(client, f"cat {newest}")
    finally:
        client.close()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "owner_dump_latest.yaml"
    target.write_text(content + "\n", encoding="utf-8")
    print(f"saved {newest.rsplit('/', 1)[-1]} ({len(content)} bytes) to {target}")
    return target


# Intent: compare the integration files on the host with a git ref and print the three difference lists.
# Why: it answers whether the host runs exactly the release, before and after a deploy.
def compare_deployed(ref: str) -> int:
    client = connect()
    try:
        remote = json.loads(run_read(client, f"python3 -c '{HASH_SCRIPT}'"))
    finally:
        client.close()
    only_remote, only_local, different = diff_hashes(remote, git_hashes(ref))
    print(f"{ref}: {len(git_hashes(ref))} files in git, {len(remote)} on the host")
    print("only on the host:", only_remote)
    print("only in git:", only_local)
    print("different content:", different)
    return 1 if (only_remote or only_local or different) else 0


# Intent: dispatch the three subcommands.
# Why: one entry point keeps the credential handling and the output folder in one place.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("registry", "dump"):
        sub.add_parser(name).add_argument("--out", type=Path, default=DEFAULT_OUT)
    sub.add_parser("compare").add_argument("ref", nargs="?", default="origin/main")
    args = parser.parse_args(argv)
    if args.command == "registry":
        snapshot_registry(args.out)
        return 0
    if args.command == "dump":
        snapshot_dump(args.out)
        return 0
    return compare_deployed(args.ref)


if __name__ == "__main__":
    raise SystemExit(main())
