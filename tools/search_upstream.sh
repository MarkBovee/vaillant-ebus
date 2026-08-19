#!/usr/bin/env bash
# Search john30/ebusd-configuration issues and PRs for register knowledge.
# The shipped CSVs in that repo lag behind the bus and the CDN (#632); the
# field layouts, define strings, and find outputs people share in the
# conversations are the real source. This wraps `gh search` for that repo.
#
# Usage:
#   tools/search_upstream.sh "<query>"                  # issues (default)
#   tools/search_upstream.sh --prs "<query>"            # pull requests
#   tools/search_upstream.sh --comments "<query>"       # match in comments too
#   tools/search_upstream.sh --all "<query>"            # issues + PRs
#   tools/search_upstream.sh --limit 20 "<query>"
#   tools/search_upstream.sh "<query>" "owner/repo"     # other repo (e.g. john30/ebusd)
set -euo pipefail

REPO="john30/ebusd-configuration"
QUERY=""
MATCH="title,body"
LIMIT=10
DO_ISSUES=1
DO_PRS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prs) DO_ISSUES=0; DO_PRS=1; shift ;;
        --all) DO_ISSUES=1; DO_PRS=1; shift ;;
        --comments) MATCH="title,body,comments"; shift ;;
        --limit) LIMIT="$2"; shift 2 ;;
        --repo) REPO="$2"; shift 2 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) QUERY="$1"; shift ;;
    esac
done

if [[ -z "$QUERY" ]]; then
    echo "usage: $0 [--prs|--all] [--comments] [--limit N] [--repo owner/repo] \"<query>\"" >&2
    exit 2
fi

run() {
    local kind="$1"
    echo "── $kind in $REPO (match: $MATCH, limit: $LIMIT) ──"
    gh search "$kind" --repo "$REPO" "$QUERY" --match "$MATCH" --limit "$LIMIT" \
        --json number,title,state,updatedAt,url \
        --jq '.[] | "#\(.number) [\(.state)] \(.title)  (\(.updatedAt))\n    \(.url)"'
    echo
}

if [[ "$DO_ISSUES" -eq 1 ]]; then run issues; fi
if [[ "$DO_PRS" -eq 1 ]]; then run prs; fi