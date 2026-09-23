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
#   tools/search_upstream.sh --compact "<query>"         # omit headings and blank lines
#   tools/search_upstream.sh --cache-dir .research-scratch/upstream-search "<query>"
#   tools/search_upstream.sh --refresh --cache-dir .research-scratch/upstream-search "<query>"
#   tools/search_upstream.sh --retry 3 --retry-delay 5 "<query>"
#   tools/search_upstream.sh "<query>" "owner/repo"     # other repo (e.g. john30/ebusd)
set -euo pipefail

REPO="john30/ebusd-configuration"
QUERY=""
MATCH="title,body"
LIMIT=10
DO_ISSUES=1
DO_PRS=0
COMPACT=0
CACHE_DIR="${UPSTREAM_SEARCH_CACHE_DIR:-}"
RETRIES="${UPSTREAM_SEARCH_RETRIES:-2}"
RETRY_DELAY="${UPSTREAM_SEARCH_RETRY_DELAY:-2}"
REFRESH_CACHE=0
POSITIONAL=()

# Intent: print the supported search-wrapper options before a malformed invocation exits.
# Why: agents need a stable contract when a query, repository, or option value is missing.
usage() {
    echo "usage: $0 [--prs|--all] [--comments] [--compact] [--refresh] [--limit N] [--repo owner/repo] [--cache-dir DIR] [--retry N] [--retry-delay SECONDS] \"<query>\"" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prs) DO_ISSUES=0; DO_PRS=1; shift ;;
        --all) DO_ISSUES=1; DO_PRS=1; shift ;;
        --comments) MATCH="title,body,comments"; shift ;;
        --compact) COMPACT=1; shift ;;
        --refresh) REFRESH_CACHE=1; shift ;;
        --cache-dir)
            if [[ $# -lt 2 || "$2" == -* ]]; then usage; exit 2; fi
            CACHE_DIR="$2"
            shift 2
            ;;
        --retry)
            if [[ $# -lt 2 || "$2" == -* ]]; then usage; exit 2; fi
            RETRIES="$2"
            shift 2
            ;;
        --retry-delay)
            if [[ $# -lt 2 || "$2" == -* ]]; then usage; exit 2; fi
            RETRY_DELAY="$2"
            shift 2
            ;;
        --limit)
            if [[ $# -lt 2 || "$2" == -* ]]; then usage; exit 2; fi
            LIMIT="$2"
            shift 2
            ;;
        --repo)
            if [[ $# -lt 2 || "$2" == -* ]]; then usage; exit 2; fi
            REPO="$2"
            shift 2
            ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done

if [[ ${#POSITIONAL[@]} -eq 1 ]]; then
    QUERY="${POSITIONAL[0]}"
elif [[ ${#POSITIONAL[@]} -eq 2 ]]; then
    QUERY="${POSITIONAL[0]}"
    REPO="${POSITIONAL[1]}"
else
    usage
    exit 2
fi

if [[ ! "$RETRIES" =~ ^[0-9]+$ || ! "$RETRY_DELAY" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "retry values must be non-negative numbers" >&2
    exit 2
fi

# Intent: execute one bounded upstream search with optional cache and rate-limit recovery.
# Why: agents need repeatable evidence without hiding unrelated GitHub failures.
run() {
    local kind="$1"
    local jq_expression
    local cache_file=""
    local cache_key
    local output_file
    local error_file
    local attempt=0

    if [[ "$COMPACT" -eq 0 ]]; then
        echo "── $kind in $REPO (match: $MATCH, limit: $LIMIT) ──"
    fi
    if [[ "$COMPACT" -eq 1 ]]; then
        jq_expression=".[] | \"$kind\\t#\\(.number) [\\(.state)] \\(.title) (\\(.updatedAt))\\n    \\(.url)\""
    else
        jq_expression='.[] | "#\(.number) [\(.state)] \(.title)  (\(.updatedAt))\n    \(.url)"'
    fi

    if [[ -n "$CACHE_DIR" ]]; then
        mkdir -p "$CACHE_DIR"
        cache_key=$(printf '%s' "$REPO|$kind|$QUERY|$MATCH|$LIMIT|$COMPACT" | sha256sum | cut -d' ' -f1)
        cache_file="$CACHE_DIR/${kind}-${cache_key}.txt"
        if [[ "$REFRESH_CACHE" -eq 0 && -f "$cache_file" ]]; then
            cat "$cache_file"
            if [[ "$COMPACT" -eq 0 ]]; then
                echo
            fi
            return 0
        fi
    fi

    output_file=$(mktemp)
    error_file="${output_file}.err"
    while true; do
        if gh search "$kind" --repo "$REPO" "$QUERY" --match "$MATCH" --limit "$LIMIT" \
            --json number,title,state,updatedAt,url --jq "$jq_expression" \
            >"$output_file" 2>"$error_file"; then
            if [[ -n "$cache_file" ]]; then
                mv "$output_file" "$cache_file"
                cat "$cache_file"
            else
                cat "$output_file"
                rm -f "$output_file"
            fi
            rm -f "$error_file"
            if [[ "$COMPACT" -eq 0 ]]; then
                echo
            fi
            return 0
        fi

        if [[ "$attempt" -ge "$RETRIES" ]] || ! grep -Eiq 'rate[ -]?limit|secondary rate|abuse detection|temporarily blocked' "$error_file"; then
            cat "$error_file" >&2
            rm -f "$output_file" "$error_file"
            return 1
        fi
        attempt=$((attempt + 1))
        sleep "$RETRY_DELAY"
    done
}

if [[ "$DO_ISSUES" -eq 1 ]]; then run issues; fi
if [[ "$DO_PRS" -eq 1 ]]; then run prs; fi
