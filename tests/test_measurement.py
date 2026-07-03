from __future__ import annotations

import json
from pathlib import Path

from vaillant.measurement import parse_measurement_description, parse_measurement_list


def test_parse_measurement_description_list() -> None:
    cmd = {
        "measurementDescriptionListData": [
            {
                "measurementId": 9,
                "scopeType": "acPowerTotal",
                "unit": "W",
                "measurementType": "power",
            },
            {
                "measurementId": 0,
                "scopeType": "dhwTemperature",
                "unit": "degC",
                "measurementType": "temperature",
            },
        ]
    }

    desc_map = parse_measurement_description(cmd)

    assert desc_map[9]["scopeType"] == "acPowerTotal"
    assert desc_map[9]["unit"] == "W"
    assert desc_map[0]["measurementType"] == "temperature"


def test_parse_measurement_list_with_scaled_numbers() -> None:
    desc_map = {
        9: {"scopeType": "acPowerTotal", "unit": "W", "measurementType": "power"},
        0: {"scopeType": "dhwTemperature", "unit": "degC", "measurementType": "temperature"},
    }
    cmd = {
        "measurementListData": [
            {"measurementId": 9, "measurementData": {"value": {"number": 363, "scale": 0}}},
            {"measurementId": 0, "measurementData": {"value": {"number": 410, "scale": -1}}},
        ]
    }

    updates = parse_measurement_list(cmd, desc_map, source_address={"entity": [3, 1], "feature": 11})

    assert len(updates) == 2
    assert updates[0]["scopeType"] == "acPowerTotal"
    assert updates[0]["value"] == 363.0
    assert updates[1]["scopeType"] == "dhwTemperature"
    assert updates[1]["value"] == 41.0


def test_measurement_fixture_snapshot_contains_expected_live_scopes() -> None:
    fixture = Path("tests/fixtures/measurements.jsonl")
    rows = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]
    scopes = {row["scopeType"] for row in rows}

    assert "acPowerTotal" in scopes
    assert "dhwTemperature" in scopes
    assert "roomAirTemperature" in scopes
    assert "outsideAirTemperature" in scopes
