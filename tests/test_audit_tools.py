"""Tests for the evidence tools: comment check, comment-only proof, HA snapshot helpers and the behaviour harness."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_dev_tools import load_tool

DIFF = """\
diff --git a/pkg/a.py b/pkg/a.py
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -3,0 +4,2 @@ def old():
+def added():
+    return 1
@@ -10 +12 @@ def other():
-    return 0
+    return 2
diff --git a/pkg/b.py b/pkg/b.py
--- a/pkg/b.py
+++ b/pkg/b.py
@@ -1 +1 @@
-x = 1
+x = 2
"""

SOURCE = """\
# Intent: has both comments.
# Why: the check should accept it.
def good() -> None:
    pass


# Intent: only the first comment.
def half() -> None:
    pass


def bare() -> None:
    pass


# Intent: the comment sits above the decorator.
# Why: decorators are part of the function.
@staticmethod
def decorated() -> None:
    pass


async def asynchronous() -> None:
    pass
"""


# Intent: the diff parser turns hunks into the added line numbers per file.
# Why: the comment check only looks at functions that start inside an added or changed hunk.
def test_parse_added_lines_reads_hunks_per_file() -> None:
    tool = load_tool("check_comments")

    added = tool.parse_added_lines(DIFF)

    assert added == {"pkg/a.py": {4, 5, 12}, "pkg/b.py": {1}}


# Intent: only functions without both an Intent and a Why comment are reported, decorators and async included.
# Why: a missing comment is a blocking review finding, so the check must see every function shape.
def test_find_missing_reports_functions_without_both_comments() -> None:
    tool = load_tool("check_comments")
    every_line = set(range(1, 40))

    missing = tool.find_missing(SOURCE, every_line)

    assert [(name, have) for _, name, have in missing] == [
        ("half", "Intent"),
        ("bare", "none"),
        ("asynchronous", "none"),
    ]


# Intent: a function outside the touched lines is not reported even when it has no comment.
# Why: the check covers a change, not the whole repository history.
def test_find_missing_ignores_untouched_functions() -> None:
    tool = load_tool("check_comments")

    assert tool.find_missing(SOURCE, {3}) == []


# Intent: in code mode any comment text above a function is enough, while a bare function or an empty `#` is reported.
# Why: AGENTS.md asks for a normal comment in code and keeps the Intent/Why pair for tests only.
def test_find_missing_accepts_any_comment_for_code() -> None:
    tool = load_tool("check_comments")
    code = """\
# plain comment
def a() -> None:
    pass


#
def b() -> None:
    pass


def c() -> None:
    pass
"""
    every_line = set(range(1, 13))

    missing = tool.find_missing(code, every_line, strict=False)

    assert [(name, have) for _, name, have in missing] == [("b", "none"), ("c", "none")]
    assert [name for _, name, _ in tool.find_missing(code, every_line)] == ["a", "b", "c"]


# Intent: the command holds files under tests/ to the Intent/Why pair and every other file to a normal comment.
# Why: the wiring in main() is what makes the two rules differ, so a plain comment must fail in tests only.
def test_main_applies_the_strict_rule_to_tests_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = load_tool("check_comments")
    names = ("tests/test_x.py", "custom_components/code.py")
    for name in names:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("# plain comment\ndef f() -> None:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "changed_lines", lambda base: {name: {2} for name in names})

    assert tool.main([]) == 1
    output = capsys.readouterr().out
    assert "tests/test_x.py:2 f" in output
    assert "custom_components" not in output


# Intent: a comment-only edit has the same syntax tree, a code edit does not, and an allowed rename is applied.
# Why: this is the proof the release used to show that the 30 comment fixes changed no behaviour.
def test_trees_equal_ignores_comments_and_honours_renames() -> None:
    tool = load_tool("ast_compare")
    old = "def f():\n    return 1\n"

    assert tool.trees_equal(old, "# Intent: x\n# Why: y\ndef f():\n    return 1  # note\n")
    assert not tool.trees_equal(old, "def f():\n    return 2\n")
    assert tool.trees_equal(
        "def testmerge():\n    pass\n", "def test_merge():\n    pass\n", {"testmerge": "test_merge"}
    )


# Intent: line endings do not change a hash, content does.
# Why: a Windows checkout deploys CRLF files while git stores LF; that must not look like a different release.
def test_normalized_sha256_folds_line_endings() -> None:
    tool = load_tool("ha_snapshot")

    assert tool.normalized_sha256(b"a\r\nb\r\n") == tool.normalized_sha256(b"a\nb\n")
    assert tool.normalized_sha256(b"a\nb\n") != tool.normalized_sha256(b"a\nc\n")


# Intent: the three difference lists separate host-only files, git-only files and changed content.
# Why: they are the whole answer to "does the host run this release".
def test_diff_hashes_splits_the_three_cases() -> None:
    tool = load_tool("ha_snapshot")

    result = tool.diff_hashes({"a": "1", "b": "2", "c": "3"}, {"b": "2", "c": "9", "d": "4"})

    assert result == (["a"], ["d"], ["c"])


# Intent: the git side hashes the component files of a ref under the same keys as the host listing.
# Why: a key mismatch (a prefix, a path separator) would report every file as different.
def test_git_hashes_keys_match_the_component_listing() -> None:
    tool = load_tool("ha_snapshot")

    hashes = tool.git_hashes("HEAD")

    assert "manifest.json" in hashes and "backend/mapping.py" in hashes
    assert not any(key.startswith("custom_components") for key in hashes)


# Intent: run a remote one-liner against fake files and return what it prints.
# Why: the one-liners are strings sent over SSH; this proves they parse and filter as intended without a host.
def _run_remote_script(script: str, files: dict[str, Any]) -> Any:
    def fake_open(path: str, mode: str = "r") -> Any:
        return io.StringIO(json.dumps(files[path]))

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        exec(script, {"open": fake_open})  # noqa: S102  (fixed project constant, fake files)
    return json.loads(captured.getvalue())


# Intent: the registry one-liner keeps only this integration's rows and their devices.
# Why: the snapshot must hold no other integration's data, and it must find the devices by identifier too.
def test_registry_script_keeps_only_this_integration() -> None:
    tool = load_tool("ha_snapshot")
    files = {
        "/config/.storage/core.entity_registry": {
            "data": {
                "entities": [
                    {"entity_id": "sensor.a", "platform": "vaillant_ebus", "device_id": "d1"},
                    {"entity_id": "sensor.b", "platform": "other", "device_id": "d2"},
                ]
            }
        },
        "/config/.storage/core.device_registry": {
            "data": {
                "devices": [
                    {"id": "d1", "identifiers": [["vaillant_ebus", "hmu"]]},
                    {"id": "d2", "identifiers": [["other", "x"]]},
                    {"id": "d3", "identifiers": [["vaillant_ebus", "sc"]]},
                ]
            }
        },
    }

    result = _run_remote_script(tool.REGISTRY_SCRIPT, files)

    assert [row["entity_id"] for row in result["entities"]] == ["sensor.a"]
    assert [device["id"] for device in result["devices"]] == ["d1", "d3"]


# Intent: the hash one-liner is valid Python.
# Why: a syntax slip would only show on the host, after credentials were used.
def test_hash_script_compiles() -> None:
    tool = load_tool("ha_snapshot")

    compile(tool.HASH_SCRIPT, "<remote>", "exec")


@dataclasses.dataclass
class _Sample:
    name: str
    tags: set[str]


# Intent: sets serialise in a stable sorted order, dataclasses become dicts and unknown objects become text.
# Why: two dumps are compared byte for byte, so the same decision must always serialise the same way.
def test_plain_is_stable_for_sets_and_dataclasses() -> None:
    tool = load_tool("differential")

    assert tool.plain(_Sample("x", {"b", "a"})) == {"name": "x", "tags": ["a", "b"]}
    assert tool.plain({1: (2, 3)}) == {"1": [2, 3]}
    assert isinstance(tool.plain(object()), str)


# Intent: the frozen clock makes `datetime.now()` constant in the patched module and leaves other datetime use intact.
# Why: dumps made on different days must not differ in their date-bearing `define` strings.
def test_freeze_clock_fixes_now_inside_the_module() -> None:
    import datetime
    import types

    tool = load_tool("differential")
    module = types.SimpleNamespace(datetime=datetime.datetime)

    tool.freeze_clock(module)

    assert module.datetime.now() == datetime.datetime(2026, 1, 15, 12, 0, 0)
    assert module.datetime.min == datetime.datetime.min
    assert isinstance(module.datetime.now(), datetime.datetime)


# Intent: identical dumps give no differences; changed values, missing keys and reordered lists are each reported.
# Why: the comparison is the proof that a refactor or merge kept every recorded decision.
def test_diff_dumps_reports_each_kind_of_difference() -> None:
    tool = load_tool("differential")
    left = {"fixtures": {"a": {"reads": [1, 2], "value": 1}}, "register_map": {"k": "x"}}

    assert tool.diff_dumps(left, json.loads(json.dumps(left)))[0] == []

    right = {"fixtures": {"a": {"reads": [2, 1], "value": 2, "extra": True}}, "register_map": {}}
    lines, counts = tool.diff_dumps(left, right)

    assert any("different order" in line for line in lines)
    assert any("1 vs 2" in line for line in lines)
    assert any("only in the second" in line for line in lines)
    assert any("only in the first" in line for line in lines)
    assert counts["fixtures"] == 3 and counts["register_map"] == 1
