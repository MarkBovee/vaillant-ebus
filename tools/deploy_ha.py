#!/usr/bin/env python3
"""Deploy custom_components/vaillant_ebus to a Home Assistant host over SSH (exec channel; the SSH add-on has no SFTP).

Credentials come from the git-ignored `.env` (HA_HOST, HA_SSH_USER, HA_SSH_PASSWORD); nothing is echoed.
Steps: build a clean zip, back up the remote copy, replace it, optionally restart Home Assistant.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENT = REPO_ROOT / "custom_components" / "vaillant_ebus"
REMOTE_COMPONENT = "/config/custom_components/vaillant_ebus"
REMOTE_BACKUPS = "/config/.deploy_backups"
EXCLUDED_DIRS = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


# Read KEY=VALUE pairs from the repository .env without exporting them to child processes.
# Deployment secrets must stay inside this process and never be printed.
def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# Build the component zip in memory without caches or a directory prefix.
# `__pycache__` from the Windows interpreter must never reach the HA host.
def build_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(COMPONENT.rglob("*")):
            if not path.is_file() or EXCLUDED_DIRS & set(path.parts) or path.suffix in EXCLUDED_SUFFIXES:
                continue
            archive.write(path, path.relative_to(COMPONENT).as_posix())
    return buffer.getvalue()


# Run a command on the HA host and return its exit status and output.
# Every remote step needs the same error handling and must not log credentials.
def run_remote(client, command: str) -> tuple[int, str]:
    _, stdout, stderr = client.exec_command(command, timeout=120)
    output = stdout.read().decode("utf-8", "replace") + stderr.read().decode("utf-8", "replace")
    return stdout.channel.recv_exit_status(), output.strip()


# Parse CLI flags.
# Validation and restart are opt-in/opt-out per the home-assistant skill.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restart", action="store_true", help="restart Home Assistant core after the upload")
    parser.add_argument("--dry-run", action="store_true", help="build the zip and test the SSH login only")
    parser.add_argument("--accept-new-host-key", action="store_true", help="trust an unknown SSH host key")
    return parser.parse_args()


# Orchestrate zip build, remote backup, replacement and optional restart.
# A single entry point keeps the deploy repeatable and the rollback path obvious.
# Write the host key accepted with --accept-new-host-key to the user's known_hosts file.
# AutoAddPolicy trusts the key for this run only; without saving it the next run asks again and fails.
def persist_accepted_host_key(client) -> Path:
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    client.save_host_keys(str(known_hosts))
    return known_hosts


# Deploy the integration to the HA host over SSH: check the target, take a backup, then install the new zip. --dry-run
# stops after the login and directory check.
def main() -> int:
    args = parse_args()
    env = load_env(REPO_ROOT / ".env")
    missing = [key for key in ("HA_HOST", "HA_SSH_USER", "HA_SSH_PASSWORD") if not env.get(key)]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}", file=sys.stderr)
        return 2
    import paramiko

    payload = build_zip()
    print(f"Built zip: {len(payload)} bytes")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(
        paramiko.AutoAddPolicy() if args.accept_new_host_key else paramiko.RejectPolicy()
    )
    client.connect(
        env["HA_HOST"],
        port=int(env.get("HA_SSH_PORT", "22")),
        username=env["HA_SSH_USER"],
        password=env["HA_SSH_PASSWORD"],
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    if args.accept_new_host_key:
        persist_accepted_host_key(client)
    try:
        status, output = run_remote(client, "test -d /config/custom_components && command -v python3 && command -v tar")
        if status != 0:
            print("Remote needs /config/custom_components, python3 and tar", file=sys.stderr)
            return 3
        if args.dry_run:
            print("Dry run: login and target directory OK")
            return 0
        stamp = time.strftime("%Y%m%d-%H%M%S")
        # /config is root-owned on the HA OS SSH add-on; the SSH user needs passwordless sudo for every write.
        status, output = run_remote(client, f"sudo -n mkdir -p {REMOTE_BACKUPS}")
        if status != 0:
            print(f"Cannot create backup dir (sudo needed): {output}", file=sys.stderr)
            return 6
        backup = f"{REMOTE_BACKUPS}/vaillant_ebus-{stamp}.tar.gz"
        status, output = run_remote(
            client,
            f"sudo -n tar -czf {backup} -C /config/custom_components vaillant_ebus && "
            f"sudo -n test -s {backup} && echo ok",
        )
        if status != 0:
            print(f"Backup failed, nothing was changed: {output}", file=sys.stderr)
            return 7
        print(f"Backup verified: {backup}")
        remote_zip = f"/tmp/vaillant_ebus-{stamp}.zip"
        # The HA SSH add-on exposes no SFTP subsystem, so stream the zip over an exec channel instead.
        stdin, stdout, _ = client.exec_command(f"cat > {remote_zip}", timeout=120)
        stdin.write(payload)
        stdin.channel.shutdown_write()
        stdout.channel.recv_exit_status()
        status, output = run_remote(client, f"wc -c < {remote_zip}")
        if status != 0 or output.strip() != str(len(payload)):
            print(f"Upload size mismatch: remote {output!r} vs local {len(payload)}", file=sys.stderr)
            return 5
        extract = (
            f"sudo -n rm -rf {REMOTE_COMPONENT} && sudo -n mkdir -p {REMOTE_COMPONENT} && "
            f'sudo -n python3 -c "import zipfile;'
            f"zipfile.ZipFile('{remote_zip}').extractall('{REMOTE_COMPONENT}')\" && "
            f"rm -f {remote_zip} && grep -m1 '\"version\"' {REMOTE_COMPONENT}/manifest.json"
        )
        status, output = run_remote(client, extract)
        if status != 0:
            print(
                f"Extract failed (restore with: sudo tar -xzf {backup} -C /config/custom_components): {output}",
                file=sys.stderr,
            )
            return 4
        print(f"Deployed: {output}")
        if args.restart:
            status, output = run_remote(client, "sudo -n ha core restart")
            print(f"Restart requested (exit {status}): {output[:200]}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
