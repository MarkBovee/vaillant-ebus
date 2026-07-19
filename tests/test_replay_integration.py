"""Replay integration tests — replay transport through protocol layer."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from tools.replay import SessionReplay


def _eebus_json(obj: dict) -> str:
    """Convert a JSON object to EEBUS array-wrapped format (as string)."""
    def _to_eebus(value):
        if isinstance(value, dict):
            return [{k: _to_eebus(v)} for k, v in value.items()]
        if isinstance(value, list):
            return [_to_eebus(v) for v in value]
        return value
    converted = _to_eebus(obj)
    text = json.dumps(converted, separators=(",", ":"), ensure_ascii=False)
    if text.startswith("[") and text.endswith("]"):
        return text[1:-1]
    return text


def _ship_data_payload(spine_obj: dict) -> str:
    """Wrap a SPINE datagram in SHIP data envelope and return EEBUS JSON text."""
    ship = {
        "data": {
            "header": {"protocolId": "ee1.0"},
            "payload": {"datagram": spine_obj},
        }
    }
    return _eebus_json(ship)


def _make_mini_capture() -> str:
    """Build a synthetic capture with SHIP handshake + discovery + measurement."""
    events = [
        # Phase 1: VR921 responds to our CMI init byte
        {"dir": "rx", "type": "ship_control", "payload": "\x01\x00"},
        # Phase 2: VR921 HELLO ready -> our app is already trusted
        {
            "dir": "rx", "type": "ship_control",
            "payload": _eebus_json({"connectionHello": {"phase": "ready", "waiting": 60000}}),
        },
        # Phase 3: VR921 protocol handshake select
        {
            "dir": "rx", "type": "ship_control",
            "payload": _eebus_json({
                "messageProtocolHandshake": {
                    "handshakeType": "select",
                    "version": {"major": 1, "minor": 0},
                    "formats": {"format": ["JSON-UTF8"]},
                }
            }),
        },
        # Phase 4: VR921 PIN state = none
        {
            "dir": "rx", "type": "ship_control",
            "payload": _eebus_json({"connectionPinState": {"pinState": "none"}}),
        },
        # Phase 5: VR921 accessMethods
        {
            "dir": "rx", "type": "ship_control",
            "payload": _eebus_json({"accessMethods": {"id": "vr921-test"}}),
        },
        # SPINE: discovery reply
        {
            "dir": "rx", "type": "ship_data",
            "payload": _ship_data_payload({
                "header": {
                    "specificationVersion": "1.3.0",
                    "addressSource": {"device": "d:vr921:1"},
                    "addressDestination": {"device": "d:local:1", "entity": [0], "feature": 0},
                    "msgCounter": 10,
                    "msgCounterReference": 5,
                    "cmdClassifier": "reply",
                },
                "payload": {
                    "cmd": [{
                        "nodeManagementDetailedDiscoveryData": {
                            "deviceInformation": {
                                "description": {
                                    "deviceAddress": {"device": "d:vr921:1"},
                                    "deviceType": "HeatPump",
                                    "brandName": "Vaillant",
                                }
                            },
                            "entityInformation": [
                                {"description": {
                                    "entityAddress": {"entity": [3]},
                                    "entityType": "HeatPumpAppliance",
                                }},
                                {"description": {
                                    "entityAddress": {"entity": [6]},
                                    "entityType": "TemperatureSensor",
                                }},
                            ],
                            "featureInformation": [
                                {"description": {
                                    "featureAddress": {"entity": [3], "feature": 11},
                                    "featureType": "Measurement", "role": "server",
                                }},
                                {"description": {
                                    "featureAddress": {"entity": [6], "feature": 11},
                                    "featureType": "Measurement", "role": "server",
                                }},
                            ],
                        }
                    }]
                },
            }),
        },
        # SPINE: measurement description
        {
            "dir": "rx", "type": "ship_data",
            "payload": _ship_data_payload({
                "header": {
                    "specificationVersion": "1.3.0",
                    "addressSource": {"device": "d:vr921:1", "entity": [6], "feature": 11},
                    "addressDestination": {"device": "d:local:1"},
                    "msgCounter": 11,
                    "cmdClassifier": "reply",
                },
                "payload": {
                    "cmd": [{
                        "measurementDescriptionListData": [
                            {"measurementId": 0, "scopeType": "outsideAirTemperature",
                             "unit": "degC", "measurementType": "temperature"}
                        ]
                    }]
                },
            }),
        },
        # SPINE: measurement value notify
        {
            "dir": "rx", "type": "ship_data",
            "payload": _ship_data_payload({
                "header": {
                    "specificationVersion": "1.3.0",
                    "addressSource": {"device": "d:vr921:1", "entity": [6], "feature": 11},
                    "addressDestination": {"device": "d:local:1", "entity": [1], "feature": 1},
                    "msgCounter": 12,
                    "cmdClassifier": "notify",
                },
                "payload": {
                    "cmd": [{
                        "measurementListData": [
                            {"measurementId": 0,
                             "measurementData": {"value": {"number": 205, "scale": -1}}}
                        ]
                    }]
                },
            }),
        },
    ]

    path = tempfile.mktemp(suffix=".jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


@pytest.mark.asyncio
async def test_replay_drives_handshake_and_discovery():
    """VaillantClient connects via SessionReplay, processes discovery + measurement."""
    path = _make_mini_capture()
    try:
        from vaillant.client import VaillantClient

        replay = SessionReplay(path, strict=False)
        client = VaillantClient(
            cert_ski="00" * 20,
            test_transport=replay,
        )
        result = await client.connect_and_subscribe("replay", 0)
        assert result is not None

        caps = client.capabilities.all
        cap_types = {c.feature_type for c in caps}
        assert "Measurement" in cap_types

        temp_caps = client.capabilities.by_scope_type("outsideAirTemperature")
        assert len(temp_caps) >= 1
        cap = temp_caps[0]
        assert cap.value == 20.5
        assert cap.unit == "°C"  # _unit_to_ha converts degC → °C

        # Entity types from discovery
        assert client.capabilities.get_entity_type([6]) == "TemperatureSensor"
        assert client.capabilities.get_entity_type([3]) == "HeatPumpAppliance"
    finally:
        if os.path.exists(path):
            os.unlink(path)


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.mark.asyncio
async def test_replay_drives_live_capture():
    """Full-stack replay of real VR921 capture — regression test."""
    from vaillant.client import VaillantClient

    fixture = os.path.join(FIXTURE_DIR, "capture_subscribe.jsonl")
    if not os.path.exists(fixture):
        pytest.skip("capture_subscribe.jsonl fixture not available")

    replay = SessionReplay(fixture, strict=False)
    client = VaillantClient(
        cert_ski="00" * 20,
        test_transport=replay,
    )
    result = await client.connect_and_subscribe("live", 0)
    assert result is not None

    caps = client.capabilities.all
    cap_types = {c.feature_type for c in caps}
    assert "Measurement" in cap_types

    known_scopes = {"acPowerTotal", "dhwTemperature", "roomAirTemperature", "outsideAirTemperature"}
    found_scopes = set()
    for cap in caps:
        if cap.scope_type in known_scopes:
            found_scopes.add(cap.scope_type)
            assert cap.value is not None, f"{cap.scope_type} has no value"
            assert cap.unit is not None, f"{cap.scope_type} has no unit"

    assert found_scopes == known_scopes, f"Missing scopes: {known_scopes - found_scopes}"
