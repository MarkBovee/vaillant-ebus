#!/usr/bin/env python3
"""Post a Markdown reply to a GitHub issue or discussion from a file and record it in .gh-inbox-state.json.

    python tools/gh_reply.py issue 171 reply.md
    python tools/gh_reply.py discussion 31 reply.md          # replies to the newest top-level comment
    python tools/gh_reply.py discussion 31 reply.md --reply-to <comment node id>

Posting is an outward-facing action: run it only after the owner has approved the text. ``--dry-run`` prints the plan.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / ".gh-inbox-state.json"
ROOT_COMMENT_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){discussion(number:$number)"
    "{id comments(last:1){nodes{id}}}}}"
)
ADD_COMMENT_MUTATION = (
    "mutation($d:ID!,$r:ID,$b:String!){addDiscussionComment(input:{discussionId:$d,replyToId:$r,body:$b})"
    "{comment{url}}}"
)


# Run a gh command in the repository and return its stdout.
# One place for error handling; gh stays the only network client.
def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, cwd=ROOT).stdout.strip()


# Mark the item as replied in the local inbox state file (git-ignored).
# The inbox skill uses replied_to to avoid answering the same thread twice.
def mark_replied(kind: str, number: int) -> None:
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    key = f"{'issue' if kind == 'issue' else 'discussion'}-{number}"
    entry = state.setdefault(key, {"last_updated_at": "", "last_comment_count": 0})
    entry["replied_to"] = True
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


# Post a discussion reply under the thread root and return the comment URL.
# GitHub rejects replies whose parent is already inside a thread, so the root comment id is required.
def reply_discussion(number: int, body: str, reply_to: str | None) -> str:
    info = json.loads(gh("repo", "view", "--json", "owner,name"))
    root = json.loads(
        gh(
            "api",
            "graphql",
            "-f",
            f"query={ROOT_COMMENT_QUERY}",
            "-f",
            f"owner={info['owner']['login']}",
            "-f",
            f"name={info['name']}",
            "-F",
            f"number={number}",
        )
    )["data"]["repository"]["discussion"]
    parent = reply_to or (root["comments"]["nodes"][0]["id"] if root["comments"]["nodes"] else None)
    arguments = ["api", "graphql", "-f", f"query={ADD_COMMENT_MUTATION}", "-f", f"d={root['id']}", "-f", f"b={body}"]
    if parent:
        arguments += ["-f", f"r={parent}"]
    return json.loads(gh(*arguments))["data"]["addDiscussionComment"]["comment"]["url"]


# Parse arguments and post the reply.
# Keeps reply posting repeatable and auditable.
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("issue", "discussion"))
    parser.add_argument("number", type=int)
    parser.add_argument("body_file", type=Path)
    parser.add_argument("--reply-to", help="discussion comment node id (thread root)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    body = args.body_file.read_text(encoding="utf-8")
    if args.dry_run:
        print(f"Would post {len(body)} characters to {args.kind} #{args.number}")
        return 0
    if args.kind == "issue":
        url = gh("issue", "comment", str(args.number), "--body-file", str(args.body_file))
    else:
        url = reply_discussion(args.number, body, args.reply_to)
    mark_replied(args.kind, args.number)
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
