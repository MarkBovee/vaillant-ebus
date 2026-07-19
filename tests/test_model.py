from __future__ import annotations

from vaillant.model import CapabilityRegistry, UnknownFeatureRegistry


def test_capability_register_and_get() -> None:
    reg = CapabilityRegistry()
    reg.register_feature("d:remote:1", [3, 1], 11, "Measurement", "server")

    cap = reg.get([3, 1], 11)
    assert cap is not None
    assert cap.feature_type == "Measurement"
    assert cap.role == "server"
    assert cap.entity == (3, 1)
    assert cap.feature == 11


def test_capability_register_entity_type() -> None:
    reg = CapabilityRegistry()
    reg.register_entity_type([4], "DHWCircuit")
    assert reg.get_entity_type([4]) == "DHWCircuit"
    assert reg.get_entity_type([5]) is None


def test_capability_update_value() -> None:
    reg = CapabilityRegistry()
    reg.register_feature("d:remote:1", [6], 11, "Measurement", "server")
    reg.update_value([6], 11, 20.5, scope_type="outsideAirTemperature", unit="°C")

    cap = reg.get([6], 11)
    assert cap is not None
    assert cap.value == 20.5
    assert cap.scope_type == "outsideAirTemperature"
    assert cap.unit == "°C"
    assert cap.has_value


def test_capability_update_value_auto_creates() -> None:
    reg = CapabilityRegistry()
    reg.update_value([99], 7, "test", scope_type="unknown")

    cap = reg.get([99], 7)
    assert cap is not None
    assert cap.feature_type == "unknown"
    assert cap.value == "test"


def test_capability_queries() -> None:
    reg = CapabilityRegistry()
    reg.register_feature("d:remote:1", [3, 1], 11, "Measurement", "server")
    reg.register_feature("d:remote:1", [4], 18, "Setpoint", "server")
    reg.register_feature("d:remote:1", [1], 1, "Measurement", "client")

    assert len(reg.by_feature_type("Measurement")) == 2
    assert len(reg.by_feature_type("Setpoint")) == 1
    assert len(reg.servers()) == 2
    assert len(reg.clients()) == 1


def test_capability_subscribe_candidates() -> None:
    reg = CapabilityRegistry()
    reg.register_feature("d:remote:1", [0], 0, "NodeManagement", "server")
    reg.register_feature("d:remote:1", [0], 1, "DeviceClassification", "server")
    reg.register_feature("d:remote:1", [3, 1], 11, "Measurement", "server")
    reg.register_feature("d:remote:1", [4], 18, "Setpoint", "server")

    candidates = reg.subscribe_candidates()
    types = {c.feature_type for c in candidates}
    assert "Measurement" in types
    assert "Setpoint" in types
    assert "NodeManagement" not in types
    assert "DeviceClassification" not in types


def test_capability_load_measurement_descriptions() -> None:
    reg = CapabilityRegistry()
    reg.register_feature("d:remote:1", [6], 11, "Measurement", "server")
    reg.load_measurement_descriptions(
        [6], 11,
        {9: {"scopeType": "outsideAirTemperature", "unit": "degC", "measurementType": "temperature"}},
    )

    cap = reg.get([6], 11)
    assert cap is not None
    assert cap.scope_type == "outsideAirTemperature"
    assert "measurementListData" in cap.supported_commands


def test_capability_load_electrical_connection_descriptions() -> None:
    reg = CapabilityRegistry()
    reg.register_feature("d:remote:1", [3], 11, "ElectricalConnection", "server")
    reg.load_electrical_connection_descriptions(
        [3], 11,
        {1: {"scopeType": "acCurrent", "unit": "A", "measurementType": "current"}},
    )

    cap = reg.get([3], 11)
    assert cap is not None
    assert cap.scope_type == "acCurrent"
    assert "electricalConnectionParameterListData" in cap.supported_commands


def test_capability_with_without_value() -> None:
    reg = CapabilityRegistry()
    reg.register_feature("d:remote:1", [6], 11, "Measurement", "server")
    reg.register_feature("d:remote:1", [3, 1], 11, "Measurement", "server")
    reg.update_value([6], 11, 20.5)

    assert len(reg.with_value()) == 1
    assert len(reg.without_value()) == 1


def test_capability_measurement_scopes() -> None:
    reg = CapabilityRegistry()
    reg.register_feature("d:remote:1", [6], 11, "Measurement", "server")
    reg.load_measurement_descriptions(
        [6], 11,
        {0: {"scopeType": "outsideAirTemperature", "unit": "degC"}},
    )
    reg.register_feature("d:remote:1", [4], 11, "Measurement", "server")
    reg.load_measurement_descriptions(
        [4], 11,
        {1: {"scopeType": "dhwTemperature", "unit": "degC"}},
    )

    scopes = reg.measurement_scopes
    assert "outsideAirTemperature" in scopes
    assert "dhwTemperature" in scopes
    assert scopes["outsideAirTemperature"]["unit"] == "degC"


def test_capability_clear() -> None:
    reg = CapabilityRegistry()
    reg.register_feature("d:remote:1", [6], 11, "Measurement", "server")
    reg.clear()
    assert len(reg.all) == 0


def test_capability_from_discovery() -> None:
    reg = CapabilityRegistry()
    discovery = {
        "entityInformation": [
            {"description": {"entityAddress": {"entity": [3]}, "entityType": "HeatPumpAppliance"}},
        ],
        "featureInformation": [
            {
                "description": {
                    "featureAddress": {"entity": [3], "feature": 11},
                    "featureType": "Measurement",
                    "role": "server",
                }
            },
        ],
    }
    reg.register_from_discovery("d:remote:1", discovery)
    assert reg.get_entity_type([3]) == "HeatPumpAppliance"
    cap = reg.get([3], 11)
    assert cap is not None
    assert cap.feature_type == "Measurement"
    assert cap.role == "server"


# --- UnknownFeatureRegistry ---

def test_unknown_record_command() -> None:
    reg = UnknownFeatureRegistry(capacity=10)
    reg.record_command("unknownCmd", {"cmdClassifier": "notify", "msgCounter": 42}, {"some": "data"})

    assert reg.last_unknown == "unknownCmd"
    assert reg.total_discarded == 1
    assert len(reg.unknown_commands) == 1
    assert reg.unknown_commands[0]["cmd_name"] == "unknownCmd"


def test_unknown_capacity() -> None:
    reg = UnknownFeatureRegistry(capacity=3)
    for i in range(5):
        reg.record_command(f"cmd{i}", {}, {})
    assert len(reg.unknown_commands) == 3
    assert reg.total_discarded == 5
    assert reg.unknown_commands[0]["cmd_name"] == "cmd2"


def test_unknown_record_feature_type() -> None:
    reg = UnknownFeatureRegistry()
    reg.record_feature_type("SomeStrangeFeature")
    reg.record_feature_type("SomeStrangeFeature")
    assert reg.unknown_feature_types == {"SomeStrangeFeature": 2}


def test_unknown_clear() -> None:
    reg = UnknownFeatureRegistry()
    reg.record_command("x", {}, {})
    reg.record_feature_type("y")
    reg.clear()
    assert reg.total_discarded == 0
    assert len(reg.unknown_commands) == 0
    assert reg.unknown_feature_types == {}
