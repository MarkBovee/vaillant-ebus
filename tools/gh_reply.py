#!/usr/bin/env python3
"""Post a Markdown reply to a GitHub issue or discussion from a file and record it in .gh-inbox-state.json.

    python tools/gh_reply.py issue 171 reply.md
    python tools/gh_reply.py discussion 31 reply.md          # replies to the newest top-level comment
    python tools/gh_reply.py discussion 31 reply.md --reply-to <comment node id>
    python tools/gh_reply.py issue 205 reply.md --label "status: waiting for user verification"
    python tools/gh_reply.py --batch replies.txt [--dry-run]   # one "issue|discussion <n> <file> [label]" per line

Posting is an outward-facing action: run it only after the owner has approved the text. ``--dry-run`` prints the plan.
A batch checks every line and every file before it posts anything, posts in order, and stops at the first failure so
the output says exactly which replies went out. A label applies to issues only (discussions have no labels here).
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Reply:
    """One approved reply: where it goes, the file with its text and an optional issue label."""

    kind: str
    number: int
    body_file: Path
    label: str | None = None


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


# Read a batch file: one reply per line as `issue|discussion <number> <file> [label]`; blank lines and # comments skip.
# Relative files resolve against the batch file's folder. Every problem is collected, so nothing posts on a bad batch.
def parse_batch(path: Path) -> tuple[list[Reply], list[str]]:
    replies: list[Reply] = []
    problems: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = shlex.split(line)
        if len(parts) not in (3, 4) or parts[0] not in ("issue", "discussion") or not parts[1].isdigit():
            problems.append(f"line {line_number}: expected 'issue|discussion <number> <file> [label]'")
            continue
        body_file = Path(parts[2]) if Path(parts[2]).is_absolute() else path.parent / parts[2]
        replies.append(Reply(parts[0], int(parts[1]), body_file, parts[3] if len(parts) == 4 else None))
    return replies, problems


# List what is wrong with a set of replies before anything posts: missing or empty files, labels on discussions.
def check_replies(replies: list[Reply]) -> list[str]:
    problems = []
    for reply in replies:
        target = f"{reply.kind} #{reply.number}"
        if not reply.body_file.is_file():
            problems.append(f"{target}: file {reply.body_file} not found")
        elif not reply.body_file.read_text(encoding="utf-8").strip():
            problems.append(f"{target}: file {reply.body_file} is empty")
        if reply.label and reply.kind != "issue":
            problems.append(f"{target}: labels apply to issues only")
    return problems


# Post one reply, add its label and mark the item in the inbox state; returns the comment URL.
def post(reply: Reply, reply_to: str | None = None) -> str:
    if reply.kind == "issue":
        url = gh("issue", "comment", str(reply.number), "--body-file", str(reply.body_file))
        if reply.label:
            gh("issue", "edit", str(reply.number), "--add-label", reply.label)
    else:
        url = reply_discussion(reply.number, reply.body_file.read_text(encoding="utf-8"), reply_to)
    mark_replied(reply.kind, reply.number)
    return url


# Parse arguments and post one reply or a batch.
# Keeps reply posting repeatable and auditable.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", nargs="?", choices=("issue", "discussion"))
    parser.add_argument("number", nargs="?", type=int)
    parser.add_argument("body_file", nargs="?", type=Path)
    parser.add_argument("--reply-to", help="discussion comment node id (thread root)")
    parser.add_argument("--label", help="label to add to the issue after posting")
    parser.add_argument("--batch", type=Path, help="file with one reply per line")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.batch:
        replies, problems = parse_batch(args.batch)
    elif args.kind and args.number is not None and args.body_file:
        replies, problems = [Reply(args.kind, args.number, args.body_file, args.label)], []
    else:
        parser.error("give either kind, number and file, or --batch")
    problems += check_replies(replies)
    if problems:
        for problem in problems:
            print(f"refused: {problem}", file=sys.stderr)
        return 2
    for reply in replies:
        if args.dry_run:
            size = len(reply.body_file.read_text(encoding="utf-8"))
            label = f" and add label {reply.label!r}" if reply.label else ""
            print(f"Would post {size} characters to {reply.kind} #{reply.number}{label}")
            continue
        try:
            print(post(reply, args.reply_to))
        except subprocess.CalledProcessError as error:
            print(f"failed at {reply.kind} #{reply.number}: {error.stderr.strip()[:300]}", file=sys.stderr)
            print("the replies listed above this line were posted; fix the problem and post the rest", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
