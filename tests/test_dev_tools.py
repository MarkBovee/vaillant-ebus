"""Tests for the developer helper tools under tools/ (validate, translations check, attachment fetch)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


# Intent: import a tools/*.py script as a module without making tools a package.
# Why: the tools are standalone scripts that tests exercise through their pure helper functions.
def load_tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"dev_tool_{name}", ROOT / "tools" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Intent: a fixable repair with both a description and a fix_flow is flagged, as hassfest does.
# Why: v1.10.5 shipped such a translation and only CI hassfest caught it.
def test_translation_check_flags_description_with_fix_flow() -> None:
    tool = load_tool("check_translations")
    data = {"issues": {"x": {"title": "t", "description": "d", "fix_flow": {"step": {}}}}}

    problems = tool.issue_problems(data)

    assert len(problems) == 1 and "fixable" in problems[0]


# Intent: a fix_flow-only issue and a description-only issue are both accepted; a bare title is not.
# Why: either form is valid for hassfest, but one of them is required.
def test_translation_check_accepts_either_form_and_requires_one() -> None:
    tool = load_tool("check_translations")

    assert (
        tool.issue_problems({"issues": {"a": {"title": "t", "fix_flow": {}}, "b": {"title": "t", "description": "d"}}})
        == []
    )
    assert tool.issue_problems({"issues": {"c": {"title": "t"}}}) != []


# Intent: the shipped translation files satisfy the rules.
# Why: CI should fail before hassfest does.
def test_shipped_translations_pass_the_hassfest_rules() -> None:
    tool = load_tool("check_translations")

    for path in tool.translation_files():
        assert tool.issue_problems(json.loads(path.read_text(encoding="utf-8"))) == [], path.name


# Intent: the baseline matcher separates known environment failures from new ones by prefix.
# Why: only new failures should fail a local validation run on Windows.
def test_validate_classifies_known_and_new_failures() -> None:
    tool = load_tool("validate")
    baseline = ["tests/test_search_upstream.py::", "tests/test_x.py::test_known"]
    failures = ["tests/test_search_upstream.py::test_a", "tests/test_x.py::test_known[1]", "tests/test_y.py::test_new"]

    known, new = tool.classify_failures(failures, baseline)

    assert known == failures[:2]
    assert new == ["tests/test_y.py::test_new"]


# Intent: failing node ids are read from pytest's short summary.
# Why: the baseline comparison needs ids, not the raw log.
def test_validate_parses_pytest_failures() -> None:
    tool = load_tool("validate")
    output = "FAILED tests/a.py::test_one - boom\nERROR tests/b.py::test_two\n1 failed"

    assert tool.parse_failures(output) == ["tests/a.py::test_one", "tests/b.py::test_two"]


# Intent: the baseline file lists reasons and prefixes only, with comments and blanks ignored.
# Why: the file is documentation as well as data.
def test_validate_baseline_file_is_loadable() -> None:
    tool = load_tool("validate")

    baseline = tool.load_baseline()

    assert isinstance(baseline, list)
    assert all(not item.startswith("#") for item in baseline)


# Intent: attachment URLs are found in text, de-duplicated, and CRLF-insensitive digests match.
# Why: downloads must not duplicate fixtures that only differ by line endings.
def test_fetch_attachments_helpers() -> None:
    tool = load_tool("fetch_attachments")
    text = "[a](https://github.com/user-attachments/files/123/dump_1.yaml) https://github.com/user-attachments/files/123/dump_1.yaml"

    assert tool.extract_attachment_urls(text) == ["https://github.com/user-attachments/files/123/dump_1.yaml"]
    assert tool.normalized_digest(b"a\r\nb\r\n") == tool.normalized_digest(b"a\nb\n")
    assert tool.inside_fixtures(tool.FIXTURES / "x.yaml") is True
    assert tool.inside_fixtures(ROOT / "docs") is False


# Intent: an accepted SSH host key is written to the user's known_hosts so the next deploy verifies it.
# Why: AutoAddPolicy alone keeps the key in memory only, so each run asked for trust again (deploy of 1.11.1).
def test_deploy_persists_accepted_host_key_to_known_hosts(tmp_path: Path, monkeypatch) -> None:
    tool = load_tool("deploy_ha")
    monkeypatch.setattr(tool.Path, "home", classmethod(lambda cls: tmp_path))
    saved: list[str] = []

    class FakeClient:
        def save_host_keys(self, path: str) -> None:
            saved.append(path)

    written = tool.persist_accepted_host_key(FakeClient())

    assert written == tmp_path / ".ssh" / "known_hosts"
    assert saved == [str(tmp_path / ".ssh" / "known_hosts")]
    assert written.parent.is_dir()
