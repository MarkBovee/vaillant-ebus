"""Tests for the per-input temperature entities of the VR 70 and VR 71 sensor messages (issue #246)."""

from __future__ import annotations

from custom_components.vaillant_ebus.backend.mapping import split_multi_field
from tests.fake_ebusd import load_find_lines
from tests.test_entity_factory import DiscoveryService, EntityFactoryService

VR70_FIXTURE = "community/flexotherm_vwf1174_issue134_2026-09-15_162647.yaml"
VR71_FIXTURE = "community/arotherm_ecotec_discovery.yaml"
NO_VR7X_FIXTURE = "community/flexotherm_ctlv2_cooling_discovery.yaml"


# Intent: generate entities from a fixture's find lines, keyed by circuit.name.field.
# Why: every assertion looks at which sensor inputs become entities, their raw value and their default state.
def _entities(fixture: str, overrides: dict[str, dict] | None = None) -> dict:
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture))
    return {entity.key: entity for entity in EntityFactoryService().generate(graph, yaml_overrides=overrides)}


# Intent: the VR 70 `SensorData` of discussion #232 gives one temperature per input; unconnected inputs start disabled.
# Why: the buffer sensors S1 and S5 were only visible as one text (`56.00;-;-;-;56.50;25.88;c8 7c 00`).
def test_vr70_sensor_data_splits_into_input_temperatures() -> None:
    entities = _entities(VR70_FIXTURE)

    connected = {f"vr_70.SensorData.s{n}": entities[f"vr_70.SensorData.s{n}"] for n in (1, 5, 6)}
    assert {key: entity.raw_value for key, entity in connected.items()} == {
        "vr_70.SensorData.s1": "56.00",
        "vr_70.SensorData.s5": "56.50",
        "vr_70.SensorData.s6": "25.88",
    }
    assert all(entity.enabled_by_default for entity in connected.values())
    assert connected["vr_70.SensorData.s1"].meta.device_class == "temperature"
    assert connected["vr_70.SensorData.s1"].meta.friendly_name == "Sensor S1 Temperature"
    assert [entities[f"vr_70.SensorData.s{n}"].enabled_by_default for n in (2, 3, 4)] == [False] * 3
    assert "vr_70.SensorData.value" not in entities
    assert sorted(key for key in entities if key.startswith("vr_70.SensorData.")) == [
        f"vr_70.SensorData.s{n}" for n in range(1, 7)
    ]


# Intent: VR 71 `SensorData1/2` split into inputs; the combined text and the status bytes get no entity, and the
# unproven s12/Sx inputs start disabled.
# Why: issue #246 showed four temperatures in one "Mixer Sensors 1-7" entity; s12/Sx read 0.00/8.00 without sensors.
def test_vr71_sensor_data_splits_and_hides_combined_text() -> None:
    entities = _entities(VR71_FIXTURE)

    assert [entities[f"vr_71.SensorData1.s{n}"].raw_value for n in (1, 2, 3)] == ["30.69", "30.19", "29.75"]
    assert all(entities[f"vr_71.SensorData1.s{n}"].enabled_by_default for n in (1, 2, 3))
    assert not any(entities[f"vr_71.SensorData1.s{n}"].enabled_by_default for n in (4, 5, 6, 7))
    assert (entities["vr_71.SensorData2.s12"].raw_value, entities["vr_71.SensorData2.sx"].raw_value) == ("0.00", "8.00")
    assert not entities["vr_71.SensorData2.s12"].enabled_by_default
    assert not entities["vr_71.SensorData2.sx"].enabled_by_default
    assert "vr_71.SensorData1.value" not in entities and "vr_71.SensorData2.value" not in entities

    with_combined = _entities(VR71_FIXTURE, {"vr_71.SensorData1": {"enabled": True}})
    assert with_combined["vr_71.SensorData1.value"].raw_value == "30.69;30.19;29.75;-;-;-;-;40 3d"


# Intent: a bus without a VR 70 or VR 71 gets no sensor input entities, and a short value leaves later inputs empty.
# Why: field entities must come from the discovery graph only, never from the mapping table.
def test_sensor_inputs_absent_without_module_or_value() -> None:
    entities = _entities(NO_VR7X_FIXTURE)

    assert not [key for key in entities if key.startswith(("vr_70.", "vr_71.SensorData"))]
    assert split_multi_field("vr_71.SensorData2", "-;21.5") == {
        "value": "-;21.5",
        "s8": "-",
        "s9": "21.5",
        "s10": None,
        "s11": None,
        "s12": None,
        "sx": None,
    }
