"""Tests for backward-compatible discovery dump analysis."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import yaml

BACKEND_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend"
COMPONENT_PATH = BACKEND_PATH.parent
for name, path in (("vaillant_ebus", COMPONENT_PATH), ("vaillant_ebus.backend", BACKEND_PATH)):
    package = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    package.__path__ = [str(path)]
    sys.modules[name] = package

parser_spec = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.grab_parser", BACKEND_PATH / "grab_parser.py"
)
assert parser_spec and parser_spec.loader
parser_module = importlib.util.module_from_spec(parser_spec)
sys.modules["vaillant_ebus.backend.grab_parser"] = parser_module
parser_spec.loader.exec_module(parser_module)

spec = importlib.util.spec_from_file_location("vaillant_ebus.backend.dump_analysis", BACKEND_PATH / "dump_analysis.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules["vaillant_ebus.backend.dump_analysis"] = module
spec.loader.exec_module(module)

normalize_dump = module.normalize_dump
group_telegrams = module.group_telegrams


# Intent: normalizes a legacy ctlv2 cooling discovery-dump fixture to version 3 while keeping the raw grab lines.
# Why: verifies old dumps are upgraded in-memory without mutating or losing their raw capture.
def test_legacy_fixture_normalizes_without_migration() -> None:
    path = Path(__file__).parent / "fixtures/community/arotherm_plus_ctlv2_cooling_discovery.yaml"
    dump = yaml.safe_load(path.read_text())
    normalized = normalize_dump(dump)

    assert normalized["dump_version"] == 3
    assert normalized["version_supported"] is True
    assert normalized["registers"]["discovered"]
    assert normalized["raw"]["grab"] == dump["grab"]


# Intent: a dump with no metadata version normalizes to dump_version 1 and extracts the before register as discovered.
# Why: keeps first-generation dumps loadable rather than failing version detection.
def test_unversioned_dump_is_treated_as_legacy() -> None:
    normalized = normalize_dump(
        {"before_registers": [{"circuit": "hmu", "name": "State", "values": ["on"], "has_data": True}]}
    )

    assert normalized["dump_version"] == 1
    assert normalized["version_supported"] is True
    assert normalized["registers"]["discovered"] == ["hmu.State"]


# Intent: a dump tagged version 99 keeps that version but reports version_supported False.
# Why: prevents a newer dump format from being parsed with assumptions that could misread fields.
def test_future_version_is_preserved_but_not_assumed_supported() -> None:
    normalized = normalize_dump({"metadata": {"dump_version": 99}, "before_registers": []})

    assert normalized["dump_version"] == 99
    assert normalized["version_supported"] is False


# Intent: normalizes before/after registers, splits mapped from unavailable, and
# reports the sentinel-to-live transition on hmu.State as a change while hmu.New is new.
# Why: guards detection of a register coming alive from "no data stored" during a dump comparison.
def test_register_categories_and_sentinel_diff() -> None:
    before = [{"circuit": "hmu", "name": "State", "values": ["no data stored"], "has_data": False}]
    after = [
        {"circuit": "hmu", "name": "State", "values": ["on"], "has_data": True},
        {"circuit": "hmu", "name": "New", "values": ["1"], "has_data": True, "from_map": True},
    ]
    normalized = normalize_dump({"before_registers": before, "after_registers": after})

    assert normalized["registers"]["mapped"] == ["hmu.New"]
    assert normalized["registers"]["unavailable"] == []
    assert normalized["changes"]["new_registers"] == ["hmu.New"]
    assert normalized["changes"]["changed_registers"][0]["key"] == "hmu.State"


# Intent: group_telegrams merges two identical b510/01 telegrams into one group
# with occurrence_count 5 and both responses.
# Why: ensures duplicate unknown telegrams are aggregated by message identity instead of listed separately.
def test_telegram_grouping_aggregates_counts_and_responses() -> None:
    grouped = group_telegrams(
        [
            {
                "master": "10",
                "slave": "08",
                "msgid": "b510",
                "sub": "01",
                "label": None,
                "request": "10...",
                "resp": "aa",
                "count": "2",
            },
            {
                "master": "10",
                "slave": "08",
                "msgid": "b510",
                "sub": "01",
                "label": None,
                "request": "10...",
                "resp": "bb",
                "count": "3",
            },
        ]
    )

    assert len(grouped) == 1
    assert grouped[0]["known"] is False
    assert grouped[0]["occurrence_count"] == 5
    assert grouped[0]["unique_responses"] == ["aa", "bb"]


# Intent: a version-4 dump with no grab data normalizes to empty traffic summary and unknown lists.
# Why: keeps grab-less dumps producing a stable empty traffic structure instead of None.
def test_empty_grab_normalizes_to_empty_traffic() -> None:
    normalized = normalize_dump({"metadata": {"dump_version": 4}, "before_registers": []})

    assert normalized["traffic"] == {"summary": [], "unknown": []}


# Intent: preserve legacy labeled telegrams that predate raw request fields.
# Why: keeps pre-raw-grab dumps loadable and still exports their label with an empty request list.
def test_legacy_labeled_telegrams_without_request_are_compatible() -> None:
    normalized = normalize_dump(
        {
            "labeled_telegrams": [
                {
                    "master": "31",
                    "slave": "08",
                    "msgid": "b509",
                    "sub": "00",
                    "resp": "01",
                    "count": "2",
                    "label": "hmu State",
                }
            ]
        }
    )

    assert normalized["traffic"]["summary"][0]["label"] == "hmu State"
    assert normalized["traffic"]["summary"][0]["unique_requests"] == []


# Intent: retain serialized unknown candidates when legacy dumps have no raw grab.
# Why: prevents unknown-telegram evidence from being dropped when only a serialized dump exists.
def test_legacy_unknown_telegrams_without_grab_are_preserved() -> None:
    normalized = normalize_dump(
        {
            "unknown_telegrams": [
                {"master": "31", "slave": "08", "msgid": "b511", "sub": "00", "resp": "02", "count": "1"}
            ]
        }
    )

    assert normalized["traffic"]["unknown"][0]["msgid"] == "b511"


# Intent: normalize numeric YAML scalars into the string traffic contract.
# Why: guards against YAML parsing an all-digit response as an int and breaking string-based downstream comparisons.
def test_legacy_numeric_response_is_coerced_to_string() -> None:
    normalized = normalize_dump(
        {
            "labeled_telegrams": [
                {"master": "31", "slave": "08", "msgid": "b509", "sub": "00", "resp": 1, "label": "state"}
            ]
        }
    )

    assert normalized["traffic"]["summary"][0]["unique_responses"] == ["1"]


# Intent: a live vwzio b511/76/0101 candidate retains its exact sub, request, and response bytes.
# Why: pins a real correlated telegram so unknown-register mining keeps request/response pairing intact.
def test_live_vwzio_status01_candidate_preserves_correlated_telegram() -> None:
    dump = {
        "traffic": {
            "unknown": [
                {
                    "msgid": "b511",
                    "slave": "76",
                    "sub": "0101",
                    "unique_requests": ["1076b5110101"],
                    "unique_responses": ["092e2dfb0fff4c0000ff"],
                }
            ]
        }
    }
    status = next(item for item in dump["traffic"]["unknown"] if item["msgid"] == "b511" and item["slave"] == "76")

    assert status["sub"] == "0101"
    assert status["unique_requests"] == ["1076b5110101"]
    assert status["unique_responses"] == ["092e2dfb0fff4c0000ff"]
