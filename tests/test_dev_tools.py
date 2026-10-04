"""Tests for the developer helper tools under tools/ (validate, translations check, attachment fetch)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


# Intent: import a tools/*.py script as a module without making tools a package.
# Why: the tools are standalone scripts that tests exercise through their pure helper functions.
def load_tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"dev_tool_{name}", ROOT / "tools" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
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

    assert "tests/test_search_upstream.py::" in baseline
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


# Intent: the release gate passes only when hassfest and HACS finished green, fails on red, waits on missing.
# Why: 1.10.5 published a release before hassfest finished; the gate must make that impossible.
def test_release_gate_states_and_timeout() -> None:
    gate = load_tool("release_gate")
    ok = {"status": "completed", "conclusion": "success"}
    red = {"status": "completed", "conclusion": "failure"}
    running = {"status": "in_progress", "conclusion": None}

    assert gate.evaluate([{"name": "validate", **ok}, {"name": "validate-hacs", **ok}])[0] == "pass"
    assert gate.evaluate([{"name": "validate", **red}, {"name": "validate-hacs", **ok}])[0] == "fail"
    assert gate.evaluate([{"name": "validate", **running}, {"name": "validate-hacs", **ok}])[0] == "pending"
    assert gate.evaluate([{"name": "validate", **ok}])[0] == "pending"

    now = [0.0]
    passed, detail = gate.wait_for_gate(
        lambda: [{"name": "validate", **running}],
        timeout=30,
        interval=20,
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        clock=lambda: now[0],
    )
    assert not passed and detail.startswith("timeout")


# Intent: the hardware matrix lists a variant per scanned device and flags one no test references.
# Why: community-only hardware paths must stay visible so a fixture is never silently orphaned.
def test_hardware_matrix_renders_and_flags_untested_variants() -> None:
    tool = load_tool("hardware_matrix")

    rendered = tool.render({"HMUX0 SW0406/HW0504": {"a.yaml": 2}, "VWZIO SW0500/HW0504": {"b.yaml": 0}})

    assert "| HMUX0 SW0406/HW0504 | 1 | 1 | ok |" in rendered
    assert "| VWZIO SW0500/HW0504 | 1 | 0 | NO TEST REFERENCE |" in rendered
    assert "HMUX0 SW0406/HW0504" in tool.build_matrix()


# Intent: the mutation tool finds condition mutants and produces valid, different source for each.
# Why: a tool that silently yields identical or broken mutants would report false confidence.
def test_mutation_tool_generates_distinct_valid_mutants() -> None:
    import ast

    tool = load_tool("mutation_check")
    source = "def f(a, b):\n    if a == b and not a:\n        return a\n    return 0\n"
    tree = ast.parse(source)

    mutants = tool.find_mutants(tree)
    mutated = {tool.apply_mutant(tree, mutant) for mutant in mutants}

    assert {m.kind for m in mutants} == {"compare", "boolop", "not", "return"}
    assert len(mutated) == len(mutants)
    assert all(ast.parse(text) for text in mutated)
    assert ast.unparse(tree) not in mutated
