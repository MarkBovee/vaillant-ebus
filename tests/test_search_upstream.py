"""Tests for the bounded upstream-search wrapper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools/search_upstream.sh"


def _fake_gh(tmp_path: Path) -> tuple[dict[str, str], Path]:
    log = tmp_path / "gh-args.log"
    executable = tmp_path / "gh"
    executable.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{log}'\n"
        "kind=$2\n"
        'jq_expression=""\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = --jq ]; then jq_expression="$2"; shift 2; else shift; fi\n'
        "done\n"
        'if [ "$kind" = issues ]; then\n'
        '  json=\'[{"number":1,"title":"Issue result","state":"open","updatedAt":"2026-09-17T00:00:00Z","url":"https://example.test/issues/1"}]\'\n'
        "else\n"
        '  json=\'[{"number":2,"title":"PR result","state":"merged","updatedAt":"2026-09-17T00:00:00Z","url":"https://example.test/pull/2"}]\'\n'
        "fi\n"
        'printf \'%s\\n\' "$json" | jq -r "$jq_expression"\n'
    )
    executable.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    return env, log


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, check=True)


# Intent: default output keeps the existing human-readable headings and spacing.
# Why: existing manual callers must not change behavior when compact mode is absent.
def test_default_output_remains_human_readable(tmp_path: Path) -> None:
    env, _ = _fake_gh(tmp_path)
    result = _run(["--all", "query"], env)

    assert result.stdout == (
        "── issues in john30/ebusd-configuration (match: title,body, limit: 10) ──\n"
        "#1 [open] Issue result  (2026-09-17T00:00:00Z)\n"
        "    https://example.test/issues/1\n"
        "\n"
        "── prs in john30/ebusd-configuration (match: title,body, limit: 10) ──\n"
        "#2 [merged] PR result  (2026-09-17T00:00:00Z)\n"
        "    https://example.test/pull/2\n"
        "\n"
    )


# Intent: compact output removes decoration while retaining a stable issue/PR marker.
# Why: agents can consume smaller output without losing result type or source URLs.
def test_compact_output_preserves_result_type(tmp_path: Path) -> None:
    env, log = _fake_gh(tmp_path)
    result = _run(["--all", "--compact", "--comments", "--limit", "2", "--repo", "owner/repo", "query"], env)

    assert result.stdout == (
        "issues\t#1 [open] Issue result (2026-09-17T00:00:00Z)\n"
        "    https://example.test/issues/1\n"
        "prs\t#2 [merged] PR result (2026-09-17T00:00:00Z)\n"
        "    https://example.test/pull/2\n"
    )
    calls = log.read_text()
    assert "search issues --repo owner/repo query --match title,body,comments --limit 2" in calls
    assert "search prs --repo owner/repo query --match title,body,comments --limit 2" in calls


# Intent: the wrapper remains syntactically valid as a Bash script.
# Why: a compact branch must not break the bounded upstream research entry point.
def test_search_wrapper_passes_bash_syntax_check() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


# Intent: the documented positional repository form reaches both search calls.
# Why: preserve the existing documented wrapper interface while adding compact output.
def test_positional_repository_is_preserved(tmp_path: Path) -> None:
    env, log = _fake_gh(tmp_path)
    _run(["query with spaces", "owner/repo"], env)

    calls = log.read_text()
    assert "search issues --repo owner/repo query with spaces" in calls
    assert "search issues --repo john30/ebusd-configuration" not in calls


# Intent: options without values fail before invoking gh, including when another option follows.
# Why: malformed wrapper calls should produce stable usage errors instead of leaking invalid arguments to gh.
def test_missing_option_values_fail_cleanly() -> None:
    for args in (("--limit", "--compact", "query"), ("--repo", "--compact", "query")):
        result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)
        assert result.returncode == 2
        assert "usage:" in result.stderr
