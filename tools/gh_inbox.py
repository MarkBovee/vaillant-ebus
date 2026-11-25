#!/usr/bin/env python3
"""List GitHub issues, discussions and pull requests with activity the owner has not answered yet.

    python tools/gh_inbox.py                          # report, read-only
    python tools/gh_inbox.py --json                   # same, as JSON for an agent
    python tools/gh_inbox.py --record issue-218 discussion-31   # mark items as seen without a reply

The report compares GitHub with the git-ignored `.gh-inbox-state.json` (the file `tools/gh_reply.py` and the inbox
skill keep). An item is `new` when the state has no entry, `updated` when it changed since the recorded time and the
last comment is not the owner's, and `quiet` otherwise (not printed). Every inbox pass used to rewrite this fetch as a
scratch script; `gh` stays the only network client. `--record` writes the current time stamps of the named items, for
threads that need no reply.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / ".gh-inbox-state.json"
DISCUSSION_QUERY = (
    "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){discussions(first:50,"
    "orderBy:{field:UPDATED_AT,direction:DESC}){nodes{number title updatedAt closed author{login}"
    "comments(last:1){totalCount nodes{author{login} createdAt replies(last:1){nodes{author{login} createdAt}}}}}}}}"
)


@dataclass(frozen=True)
class InboxItem:
    """One issue, pull request or discussion with the facts the comparison needs."""

    key: str
    title: str
    updated_at: str
    comment_count: int
    last_activity_by: str
    last_activity_at: str
    closed: bool


# Run a gh command in the repository and return its stdout.
def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, cwd=ROOT).stdout


# Build an item from one `gh issue list` / `gh pr list` row; the last comment (or the author) is the last activity.
def item_from_issue(row: dict[str, Any], kind: str) -> InboxItem:
    comments = row.get("comments") or []
    last = comments[-1] if comments else None
    author = ((last or row).get("author") or {}).get("login", "")
    return InboxItem(
        key=f"{kind}-{row['number']}",
        title=row.get("title", ""),
        updated_at=row.get("updatedAt", ""),
        comment_count=len(comments),
        last_activity_by=author,
        last_activity_at=(last or {}).get("createdAt", row.get("createdAt", row.get("updatedAt", ""))),
        closed=str(row.get("state", "")).upper() in ("CLOSED", "MERGED"),
    )


# Build an item from one discussion node; a reply inside the newest thread counts as the last activity.
def item_from_discussion(node: dict[str, Any]) -> InboxItem:
    comments = node.get("comments") or {}
    last = (comments.get("nodes") or [None])[-1]
    activity = last
    if last and (last.get("replies") or {}).get("nodes"):
        activity = last["replies"]["nodes"][-1]
    by = ((activity or node).get("author") or {}).get("login", "")
    return InboxItem(
        key=f"discussion-{node['number']}",
        title=node.get("title", ""),
        updated_at=node.get("updatedAt", ""),
        comment_count=int(comments.get("totalCount") or 0),
        last_activity_by=by,
        last_activity_at=(activity or {}).get("createdAt", node.get("updatedAt", "")),
        closed=bool(node.get("closed")),
    )


# Classify an item against its state entry: `new`, `updated` or `quiet`.
# The owner's own last word is never news, and a closed item with no change since the record stays quiet.
def classify(item: InboxItem, state: dict[str, Any], owner: str) -> str:
    entry = state.get(item.key)
    if entry is None:
        return "quiet" if item.closed or item.last_activity_by == owner else "new"
    if item.last_activity_by == owner:
        return "quiet"
    recorded = entry.get("last_activity_at") or entry.get("last_updated_at") or ""
    changed = item.last_activity_at > recorded or item.comment_count > int(entry.get("last_comment_count") or 0)
    return "updated" if changed else "quiet"


# Fetch the open and recently changed items of the repository.
def fetch_items() -> tuple[list[InboxItem], str]:
    repo = json.loads(gh("repo", "view", "--json", "owner,name"))
    owner, name = repo["owner"]["login"], repo["name"]
    fields = "number,title,updatedAt,createdAt,state,author,comments"
    items = [
        item_from_issue(row, "issue")
        for row in json.loads(gh("issue", "list", "--state", "all", "--limit", "60", "--json", fields))
    ]
    items += [item_from_issue(row, "pr") for row in json.loads(gh("pr", "list", "--state", "open", "--json", fields))]
    data = json.loads(
        gh("api", "graphql", "-f", f"query={DISCUSSION_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}")
    )
    items += [item_from_discussion(node) for node in data["data"]["repository"]["discussions"]["nodes"]]
    return items, owner


# Write the current time stamps of the named items into the state file, for threads that need no reply.
def record(items: list[InboxItem], keys: list[str]) -> list[str]:
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    by_key = {item.key: item for item in items}
    missing = [key for key in keys if key not in by_key]
    for key in keys:
        item = by_key.get(key)
        if item is None:
            continue
        entry = state.setdefault(key, {})
        entry.update(
            last_updated_at=item.updated_at,
            last_comment_count=item.comment_count,
            last_activity_at=item.last_activity_at,
            last_activity_by=item.last_activity_by,
            closed=item.closed,
        )
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return missing


# Parse the arguments, fetch, and print or record.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print the new and updated items as JSON")
    parser.add_argument("--record", nargs="+", metavar="KEY", help="mark items (issue-N, pr-N, discussion-N) as seen")
    args = parser.parse_args(argv)
    items, owner = fetch_items()
    if args.record:
        missing = record(items, args.record)
        for key in missing:
            print(f"not found in the fetched items: {key}", file=sys.stderr)
        return 1 if missing else 0
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    news = [(classify(item, state, owner), item) for item in items]
    news = [(status, item) for status, item in news if status != "quiet"]
    if args.json:
        print(json.dumps([{"status": status, **asdict(item)} for status, item in news], indent=1))
        return 0
    for status, item in news:
        print(f"{status:8} {item.key:16} {item.last_activity_at[:16]} {item.last_activity_by:20} {item.title[:60]}")
    print(f"{len(news)} items need attention ({len(items)} fetched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
