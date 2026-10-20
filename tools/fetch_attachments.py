#!/usr/bin/env python3
"""Download the attachments of a GitHub issue or discussion into a scratch directory, never over a tracked file.

    python tools/fetch_attachments.py 175 --out <scratchpad>/issue175
    python tools/fetch_attachments.py 31 --discussion --out <scratchpad>/disc31

Each file is compared (ignoring line endings) with the community fixtures, so an attachment that is already in the
repository is reported instead of being added twice. Uses the authenticated ``gh`` CLI to list the attachment URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "community"
ATTACHMENT_PATTERN = re.compile(r"https://github\.com/user-attachments/files/\d+/[A-Za-z0-9_.%-]+")
DISCUSSION_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){discussion(number:$number)"
    "{body comments(first:100){nodes{body replies(first:50){nodes{body}}}}}}}"
)


# Find GitHub attachment URLs in free text, keeping order and dropping duplicates.
# Issue bodies and comments link the dumps as Markdown or plain URLs.
def extract_attachment_urls(text: str) -> list[str]:
    return list(dict.fromkeys(ATTACHMENT_PATTERN.findall(text)))


# Hash file content with line endings normalized.
# A CRLF checkout of a fixture must still match the LF attachment.
def normalized_digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


# Map fixture digests to their names for duplicate detection.
# Avoid adding a second copy of a capture that is already a fixture.
def fixture_digests(directory: Path = FIXTURES) -> dict[str, str]:
    return {normalized_digest(path.read_bytes()): path.name for path in directory.glob("*") if path.is_file()}


# Return True when the target directory is inside the repository's tracked fixture tree.
# Downloading over a tracked fixture silently modifies it (this happened once in 1.10.5).
def inside_fixtures(target: Path) -> bool:
    try:
        target.resolve().relative_to(FIXTURES.resolve())
    except ValueError:
        return False
    return True


# Run a gh command in the repository and return its stdout decoded as UTF-8.
# text=True alone decodes with the Windows ANSI code page (cp1252), which crashed on emoji and umlauts in comments.
def run_gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8", check=True, cwd=ROOT
    ).stdout


# Collect the text of an issue or discussion including comments and replies.
# Attachments are usually posted in comments, not in the body.
def collect_text(number: int, discussion: bool) -> str:
    if not discussion:
        return run_gh("issue", "view", str(number), "--json", "body,comments")
    info = json.loads(run_gh("repo", "view", "--json", "owner,name"))
    return run_gh(
        "api",
        "graphql",
        "-f",
        f"query={DISCUSSION_QUERY}",
        "-f",
        f"owner={info['owner']['login']}",
        "-f",
        f"name={info['name']}",
        "-F",
        f"number={number}",
    )


# Download every attachment to the output directory and report duplicates of existing fixtures.
# Gives analysis a scratch copy and a reuse hint without touching the repository.
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("number", type=int, help="issue or discussion number")
    parser.add_argument("--discussion", action="store_true", help="the number is a discussion")
    parser.add_argument("--out", required=True, type=Path, help="scratch directory (not under tests/fixtures)")
    args = parser.parse_args()
    if inside_fixtures(args.out):
        print(
            "Refusing to download into tests/fixtures; use a scratch directory and copy deliberately.", file=sys.stderr
        )
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    urls = extract_attachment_urls(collect_text(args.number, args.discussion).replace("\\/", "/"))
    existing = fixture_digests()
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        data = urllib.request.urlopen(url, timeout=60).read()  # noqa: S310 - fixed https github.com host
        target = args.out / name
        target.write_bytes(data)
        duplicate = existing.get(normalized_digest(data))
        print(f"{name}  {len(data)} bytes" + (f"  DUPLICATE of fixture {duplicate}" if duplicate else ""))
    if not urls:
        print("No attachments found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
