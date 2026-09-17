"""Tests for compact discovery dump projections."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("dump_projection", ROOT / "tools/dump_projection.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
project_dump = module.project_dump
main = module.main


# Intent: a projection exposes compact metadata and counts without raw duplicate sections.
# Why: agents need a stable index before requesting detailed evidence from a full dump.
def test_summary_projection_is_marked_derived() -> None:
    dump = {
        "metadata": {"dump_version": 4, "timestamp": "x"},
        "before_registers": [{"circuit": "hmu", "name": "State", "values": ["on"], "has_data": True}],
        "grab": ["1008b5110100 / 09410111436809000016 = 3"],
    }

    result = project_dump(dump, "capture.yaml", {"summary"}, [], [])

    assert result["source"] == "capture.yaml"
    assert result["complete_evidence"] is False
    assert result["raw_available"] is True
    assert result["summary"]["register_counts"]["discovered"] == 1
    assert "raw" not in result


# Intent: a projection reports raw evidence when only post-definition find lines exist.
# Why: post-definition data is still evidence even when the before snapshot is absent.
def test_summary_projection_detects_after_raw_evidence() -> None:
    result = project_dump({"raw_find_lines_after": ["after line"]}, "capture.yaml", {"summary"}, [], [])

    assert result["raw_available"] is True


# Intent: register projections apply explicit circuit and name filters without mutating the source dump.
# Why: selected register context should stay small while the complete fixture remains authoritative.
def test_register_projection_filters_without_mutation() -> None:
    dump = {
        "metadata": {"dump_version": 4},
        "before_registers": [
            {"circuit": "ctlv3", "name": "HwcOpMode", "values": ["auto"]},
            {"circuit": "ctlv3", "name": "Z1DayTemp", "values": ["20"]},
            {"circuit": "hmu", "name": "State", "values": ["on"]},
        ],
    }
    original = yaml.safe_dump(dump)

    result = project_dump(dump, "capture.yaml", {"registers"}, ["ctlv3"], ["Hwc"])

    assert [entry["name"] for entry in result["registers"]] == ["HwcOpMode"]
    assert yaml.safe_dump(dump) == original


# Intent: unknown projections preserve all unique request and response evidence and change semantics.
# Why: candidate selection may be compact, but it must not erase state-specific payloads needed for proof.
def test_projection_preserves_unknown_evidence_and_changes() -> None:
    dump = {
        "metadata": {"dump_version": 4},
        "before_registers": [
            {"circuit": "hmu", "name": "State", "values": ["no data stored"]},
            {"circuit": "hmu", "name": "Gone", "values": ["on"]},
        ],
        "after_registers": [{"circuit": "hmu", "name": "State", "values": ["on"]}],
        "grab": [
            "1008b5110100 / aa = 2",
            "1008b5110100 / bb = 3",
        ],
    }

    result = project_dump(dump, "capture.yaml", {"unknown-telegrams", "changes"}, [], [])

    candidate = result["unknown_telegrams"][0]
    assert candidate["unique_responses"] == ["aa", "bb"]
    assert candidate["occurrence_count"] == 5
    assert result["changes"]["changed_registers"][0]["key"] == "hmu.State"
    assert result["changes"]["disappeared_registers"] == ["hmu.Gone"]


# Intent: an explicit CLI section replaces the default summary section.
# Why: agents requesting one projection must not receive an accidental extra context payload.
def test_cli_section_selection_is_exact(tmp_path: Path, monkeypatch, capsys) -> None:
    path = tmp_path / "dump.yaml"
    path.write_text(yaml.safe_dump({"metadata": {"dump_version": 4}, "before_registers": []}))
    monkeypatch.setattr(sys, "argv", ["dump_projection.py", str(path), "--section", "registers"])

    assert main() == 0
    result = yaml.safe_load(capsys.readouterr().out)
    assert result["sections"] == ["registers"]
    assert "summary" not in result
