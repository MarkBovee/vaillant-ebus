"""Unit tests for EntityFactoryService."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

from tests.fake_ebusd import load_find_lines

BACKEND_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend"
COMPONENT_PATH = BACKEND_PATH.parent

for name in ("vaillant_ebus", "vaillant_ebus.backend"):
    pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    pkg.__path__ = [str(COMPONENT_PATH)] if name == "vaillant_ebus" else [str(BACKEND_PATH)]
    sys.modules[name] = pkg

MODELS_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.backend.models", BACKEND_PATH / "models.py")
assert MODELS_SPEC and MODELS_SPEC.loader
MODELS = importlib.util.module_from_spec(MODELS_SPEC)
sys.modules["vaillant_ebus.backend.models"] = MODELS
MODELS_SPEC.loader.exec_module(MODELS)

MAPPING_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.backend.mapping", BACKEND_PATH / "mapping.py")
assert MAPPING_SPEC and MAPPING_SPEC.loader
MAPPING = importlib.util.module_from_spec(MAPPING_SPEC)
sys.modules["vaillant_ebus.backend.mapping"] = MAPPING
MAPPING_SPEC.loader.exec_module(MAPPING)

EBUS_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.ebus_service", BACKEND_PATH / "ebus_service.py"
)
assert EBUS_SPEC and EBUS_SPEC.loader
EBUS_MOD = importlib.util.module_from_spec(EBUS_SPEC)
sys.modules["vaillant_ebus.backend.ebus_service"] = EBUS_MOD
EBUS_SPEC.loader.exec_module(EBUS_MOD)
EbusService = EBUS_MOD.EbusService

DISCOVERY_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.discovery_service", BACKEND_PATH / "discovery_service.py"
)
assert DISCOVERY_SPEC and DISCOVERY_SPEC.loader
DISCOVERY = importlib.util.module_from_spec(DISCOVERY_SPEC)
sys.modules["vaillant_ebus.backend.discovery_service"] = DISCOVERY
DISCOVERY_SPEC.loader.exec_module(DISCOVERY)
DiscoveryService = DISCOVERY.DiscoveryService

FACTORY_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.entity_factory", BACKEND_PATH / "entity_factory.py"
)
assert FACTORY_SPEC and FACTORY_SPEC.loader
FACTORY = importlib.util.module_from_spec(FACTORY_SPEC)
sys.modules["vaillant_ebus.backend.entity_factory"] = FACTORY
FACTORY_SPEC.loader.exec_module(FACTORY)

from vaillant_ebus.backend.entity_factory import (  # noqa: E402
    EntityFactoryService,
    _determine_enabled_by_default,
    _resolve_device_circuit,
)
from vaillant_ebus.backend.mapping import (  # noqa: E402
    REGISTER_MAP,
    RegisterMeta,
    get_meta,
    is_field_key,
    parent_register_name,
)
from vaillant_ebus.backend.models import DeviceGraph, DeviceNode, DeviceType  # noqa: E402


def _build_graph(overrides: dict | None = None) -> DeviceGraph:
    """Build a minimal test graph with known registers."""
    ov = overrides or {}
    nodes = {
        "hmu": DeviceNode(
            circuit="hmu",
            device_type=DeviceType.HEAT_PUMP,
            registers=["hmu.Status01", "hmu.FlowTemp", "hmu.CurrentConsumedPower"],
            has_data=ov.get("hmu_has_data", True),
        ),
        "ctlv2": DeviceNode(
            circuit="ctlv2",
            device_type=DeviceType.HEATING_CONTROLLER,
            registers=[
                "ctlv2.Date",
                "ctlv2.Hc1FlowTemp",
                "ctlv2.Hc2FlowTemp",
                "ctlv2.DhwFlowTemp",
            ],
            has_data=True,
            zone_circuits=["z1"],
            heating_circuits=["hc1"],
        ),
        "z1": DeviceNode(
            circuit="z1",
            device_type=DeviceType.ZONE,
            registers=["ctlv2.Z1DayTemp", "ctlv2.Z1OpMode"],
            parent="ctlv2",
            has_data=ov.get("z1_has_data", True),
        ),
        "dhw": DeviceNode(
            circuit="dhw",
            device_type=DeviceType.DHW,
            registers=["ctlv2.HwcTempDesired", "ctlv2.HwcOpMode"],
            parent="ctlv2",
            has_data=ov.get("dhw_has_data", True),
        ),
    }
    if ov.get("include_z2"):
        nodes["z2"] = DeviceNode(
            circuit="z2",
            device_type=DeviceType.ZONE,
            registers=["ctlv2.Z2DayTemp", "ctlv2.Z2OpMode"],
            parent="ctlv2",
            has_data=ov.get("z2_has_data", False),
        )
        nodes["ctlv2"].zone_circuits.append("z2")
        nodes["ctlv2"].heating_circuits.append("hc2")
    return DeviceGraph(
        nodes=nodes,
        raw_registers={
            "hmu.Status01": "Standby",
            "hmu.FlowTemp": "35.5",
            "hmu.CurrentConsumedPower": "0",
            "ctlv2.Z1DayTemp": "22.0",
            "ctlv2.Z1OpMode": "day",
            "ctlv2.HwcTempDesired": "45",
            "ctlv2.HwcOpMode": "day",
            "ctlv2.Date": "29.07.2026",
            "ctlv2.Hc1FlowTemp": "35.5",
            "ctlv2.Hc2FlowTemp": "30.5",
            "ctlv2.DhwFlowTemp": "45.0",
        },
        placeholder_registers=set(),
    )


# Intent: keep parent-register parsing semantics explicit for all consumers.
# Why: field keys must resolve to their parent register before any read or
# probe, otherwise parsed fields are polled as if they were registers.
def test_field_key_helpers_preserve_parent_registers() -> None:
    assert is_field_key("ctlv3.Status01.temp") is True
    assert parent_register_name("ctlv3.Status01.temp") == "ctlv3.Status01"
    assert is_field_key("ctlv3.Status01") is False
    assert parent_register_name("ctlv3.Status01") == "ctlv3.Status01"


class TestEntityGeneration:
    """Entity generation from DeviceGraph."""

    # Intent: generating from a graph with known registers yields a non-empty entity list.
    # Why: an empty result would silently remove all Home Assistant entities.
    def test_generate_returns_entities(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        assert result, "Expected non-empty entity list"

    # Intent: the reference graph yields at least seven entities across hmu, z1 and dhw.
    # Why: catches silent under-generation when device routing or dedup drops registers.
    def test_generate_count(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        # 3 hmu + 2 z1 + 2 dhw + 1 REGISTER_MAP fallback (hmu.RunDataCompressorSpeed)
        # hmu.RunDataLowPressure has enabled=False, excluded
        assert len(result) >= 7, f"Expected at least 7 entities, got {len(result)}"

    # Intent: all generated entity keys are unique.
    # Why: duplicate keys collide in the entity registry and unique-id dedup.
    def test_entities_have_unique_keys(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        keys = [e.key for e in result]
        assert len(keys) == len(set(keys)), f"Duplicate keys: {keys}"

    # Intent: every entity key has the form circuit.name.field with exactly two dots.
    # Why: platform code parses keys into circuit, name and field, so a malformed key breaks lookups.
    def test_entities_have_keys(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        for e in result:
            assert e.key.startswith(f"{e.circuit}.{e.name}."), f"Bad key format: {e.key}"
            assert e.key.count(".") == 2, f"Key should have 2 dots: {e.key}"

    # Helianthus B524 register map fixture (community capture via discussion
    # #60): the runtime-defined heating-circuit state registers must generate
    # entities with the documented metadata (units, device classes, counters
    # as diagnostic total-increasing sensors).
    # Intent: B524 runtime-defined heating-circuit registers generate entities
    # with the documented units, device classes and counter metadata.
    # Why: locks the community-captured metadata from discussion #60 so a
    # mapping change cannot silently drop units or state classes.
    def test_helianthus_b524_circuit_register_entities(self) -> None:
        lines = load_find_lines("community/helianthus_b524_circuit_registers.yaml")
        graph = DiscoveryService.build_device_graph(lines)
        svc = EntityFactoryService()
        result = svc.generate(graph)
        by_name = {e.name: e for e in result}
        assert by_name["Hc1FlowTempCalc"].meta.unit == "°C"
        assert by_name["Hc1FlowTempCalc"].meta.device_class == "temperature"
        assert by_name["Hc1MixerPosition"].meta.unit == "%"
        assert by_name["Hc1Humidity"].meta.unit == "%"
        assert by_name["Hc1Humidity"].meta.device_class == "humidity"
        assert by_name["Hc1DewPointTemp"].meta.device_class == "temperature"
        assert by_name["Hc1PumpHours"].meta.unit == "h"
        assert by_name["Hc1PumpHours"].meta.state_class == "total_increasing"
        assert by_name["Hc1PumpHours"].meta.entity_category == "diagnostic"
        assert by_name["Hc1PumpStarts"].meta.state_class == "total_increasing"
        assert by_name["Hc2FlowTempCalc"].meta.unit == "°C"
        assert by_name["Hc2Humidity"].meta.device_class == "humidity"
        assert by_name["Hc2PumpHours"].meta.unit == "h"
        assert by_name["Hc2PumpStarts"].meta.entity_category == "diagnostic"


class TestDeviceCircuitResolution:
    """Device circuit assignment from device graph."""

    # Intent: a zone node with live data assigns its registers to the zone circuit.
    # Why: zone registers must group under z1 instead of the controller to keep device entities correct.
    def test_device_circuit_zone_with_data(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        z1_entities = [e for e in result if e.name == "Z1DayTemp"]
        assert z1_entities, "Expected Z1DayTemp entity"
        assert z1_entities[0].device_circuit == "z1", f"Expected z1, got {z1_entities[0].device_circuit}"

    # Intent: a zone node without live data routes its registers to the parent ctlv2 circuit.
    # Why: avoids exposing an empty ghost zone while keeping the register visible.
    def test_device_circuit_zone_without_data(self) -> None:
        graph = _build_graph({"z1_has_data": False})
        svc = EntityFactoryService()
        result = svc.generate(graph)
        z1_entities = [e for e in result if e.name == "Z1DayTemp"]
        assert z1_entities, "Expected Z1DayTemp entity"
        assert z1_entities[0].device_circuit == "ctlv2", f"Expected ctlv2, got {z1_entities[0].device_circuit}"

    # Intent: exclude an inactive secondary zone instead of folding it into ctlv2.
    # Why: an inactive secondary zone would otherwise create phantom entities for hardware that is not installed.
    def test_inactive_z2_is_suppressed(self) -> None:
        graph = _build_graph({"include_z2": True, "z2_has_data": False})
        svc = EntityFactoryService()
        result = svc.generate(graph)
        z2_entities = [e for e in result if e.name == "Z2DayTemp"]
        assert not z2_entities, "Inactive secondary zones must not create entities"

    # Intent: the DHW logical node's registers are assigned to the dhw circuit.
    # Why: water-heater entities must be grouped under dhw rather than the controller.
    def test_device_circuit_dhw(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        dhw_entities = [e for e in result if e.name == "HwcTempDesired"]
        assert dhw_entities, "Expected HwcTempDesired entity"
        assert dhw_entities[0].device_circuit == "dhw", f"Expected dhw, got {dhw_entities[0].device_circuit}"

    # Intent: heat-pump registers are assigned to the hmu circuit.
    # Why: keeps heat-pump sensors attached to the outdoor unit device.
    def test_device_circuit_hmu(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        hmu_entities = [e for e in result if e.name == "FlowTemp"]
        assert hmu_entities, "Expected FlowTemp entity"
        assert hmu_entities[0].device_circuit == "hmu", f"Expected hmu, got {hmu_entities[0].device_circuit}"

    # Intent: route controller-owned HC and DHW registers to logical devices.
    # Why: HC flow temps belong to the zone and DHW flow temp to the cylinder,
    # so misrouting splits entities across the wrong device.
    def test_controller_owned_registers_route_to_logical_devices(self) -> None:
        graph = _build_graph()
        result = EntityFactoryService().generate(graph)
        circuits = {entity.name: entity.device_circuit for entity in result}
        assert circuits["Hc1FlowTemp"] == "z1"
        assert circuits["DhwFlowTemp"] == "dhw"
        assert circuits["Date"] == "ctlv2"

    # Intent: ensure an inactive HC2 does not leak onto the controller device.
    # Why: an inactive HC2 flow register must not leak onto the controller as a misleading entity.
    def test_inactive_secondary_zone_register_is_suppressed(self) -> None:
        graph = _build_graph({"include_z2": True, "z2_has_data": False})
        result = EntityFactoryService().generate(graph)
        assert all(entity.name != "Hc2FlowTemp" for entity in result)

    # Intent: route an active secondary heating circuit to its matching zone.
    # Why: an installed second heating circuit must expose its flow temp on z2, not ctlv2.
    def test_active_secondary_zone_register_routes_to_zone(self) -> None:
        graph = _build_graph({"include_z2": True, "z2_has_data": True})
        result = EntityFactoryService().generate(graph)
        circuits = {entity.name: entity.device_circuit for entity in result}
        assert circuits["Hc2FlowTemp"] == "z2"

    # Intent: preserve explicit user-selected device routing.
    # Why: user YAML routing must not be overridden by automatic circuit resolution.
    def test_device_circuit_override_wins_over_redistribution(self) -> None:
        graph = _build_graph()
        result = EntityFactoryService().generate(
            graph,
            yaml_overrides={"ctlv2.Hc1FlowTemp": {"device_circuit": "custom"}},
        )
        entity = next(entity for entity in result if entity.name == "Hc1FlowTemp")
        assert entity.device_circuit == "custom"


class TestEnabledByDefault:
    """Entity enabled_by_default determination."""

    # Intent: a REGISTER_MAP register with enabled=True is enabled by default.
    # Why: anchors the happy-path default for mapped registers.
    def test_enabled_by_default_known_register(self) -> None:
        result = _determine_enabled_by_default("hmu.Status01", "Standby", True, RegisterMeta(enabled=True))
        assert result is True

    # Intent: an unknown register with a real value is enabled by default.
    # Why: newly discovered registers with data should be usable without manual enabling.
    def test_enabled_by_default_has_data(self) -> None:
        result = _determine_enabled_by_default("unknown.RegName", "42", True, RegisterMeta(enabled=True))
        assert result is True

    # Intent: an unknown register whose value is None is disabled by default.
    # Why: prevents empty placeholder registers from cluttering the entity list.
    def test_enabled_by_default_unknown_placeholder_is_disabled(self) -> None:
        result = _determine_enabled_by_default("unknown.RegName", None, True, RegisterMeta(enabled=True))
        assert result is False

    # Intent: an unmapped register returning '-' with has_data False is disabled.
    # Why: ebusd placeholder sentinels must not become enabled entities.
    def test_enabled_by_default_placeholder_not_known(self) -> None:
        result = _determine_enabled_by_default("unknown.RegName", "-", False, RegisterMeta(enabled=True))
        assert result is False

    # Intent: a mapped register returning '-' with has_data False is disabled.
    # Why: no-data known registers stay disabled even when mapped.
    def test_enabled_by_default_placeholder_known(self) -> None:
        result = _determine_enabled_by_default("hmu.Status01", "-", False, REGISTER_MAP["hmu.Status01"])
        assert result is False

    # Intent: a REGISTER_MAP entry with enabled=False stays disabled regardless of value.
    # Why: honors explicit opt-out metadata for noisy registers.
    def test_enabled_by_default_meta_disabled(self) -> None:
        result = _determine_enabled_by_default(
            "hmu.RunDataLowPressure", "-", False, REGISTER_MAP["hmu.RunDataLowPressure"]
        )
        assert result is False


class TestMetadataIsolation:
    """Generated entities must not mutate shared register mapping metadata."""

    # Intent: re-generating after a register value changes reclassifies the entity without mutating shared metadata.
    # Why: shared REGISTER_MAP mutation would leak classification between entities and coordinator cycles.
    def test_register_classification_does_not_leak_between_generations(self) -> None:
        graph = DeviceGraph(
            nodes={
                "custom": DeviceNode(
                    circuit="custom",
                    device_type=DeviceType.UNKNOWN,
                    registers=["custom.Value"],
                    has_data=True,
                )
            },
            raw_registers={"custom.Value": "1"},
            placeholder_registers=set(),
        )
        first = EntityFactoryService().generate(graph)[0]
        graph.raw_registers["custom.Value"] = "hello"
        second = EntityFactoryService().generate(graph)[0]

        assert first.meta.entity_type == "binary_sensor"
        assert second.meta.entity_type == "sensor"


class TestYamlOverrides:
    """YAML override handling."""

    # Intent: a YAML entity_type override changes the generated entity type.
    # Why: lets users fix misclassified registers without code changes.
    def test_yaml_override_changes_entity_type(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        yaml = {"hmu.Status01": {"entity_type": "number"}}
        result = svc.generate(graph, yaml_overrides=yaml)
        entity = [e for e in result if e.key == "hmu.Status01.value"][0]
        assert entity.entity_type == "number", f"Expected number, got {entity.entity_type}"

    # Intent: a YAML enabled override enables a register that discovery marked disabled or no-data.
    # Why: a user override must beat the automatic enabled-by-default heuristic.
    def test_yaml_override_force_enabled(self) -> None:
        graph = _build_graph()
        graph.nodes["z1"].has_data = False
        graph.raw_registers["ctlv2.Z1OpMode"] = "-"
        svc = EntityFactoryService()
        yaml = {"ctlv2.Z1OpMode": {"enabled": True}}
        result = svc.generate(graph, yaml_overrides=yaml)
        entity = [e for e in result if e.key == "ctlv2.Z1OpMode.value"][0]
        assert entity.enabled_by_default is True

    # Intent: a YAML device_class override replaces the mapped device class.
    # Why: users need to correct device-class classification for statistics and the UI.
    def test_yaml_override_device_class(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        yaml = {"hmu.FlowTemp": {"device_class": "temperature_new"}}
        result = svc.generate(graph, yaml_overrides=yaml)
        entity = [e for e in result if e.key == "hmu.FlowTemp.value"][0]
        assert entity.meta.device_class == "temperature_new"


class TestRegisterMapFallback:
    """No REGISTER_MAP fallback — entity existence from graph only."""

    # Intent: entities come only from the discovery graph and REGISTER_MAP does not inject a missing register.
    # Why: enforces the graph-is-source-of-truth rule that prevents virtual entities for absent hardware.
    def test_graph_only_no_fallback(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        keys = {e.key for e in result}
        assert "hmu.RunDataCompressorSpeed.value" not in keys, "No fallback — only graph registers exist"

    # Intent: an empty graph produces zero entities.
    # Why: nothing discovered must mean no entities, not a REGISTER_MAP dump.
    def test_empty_graph_no_fallback(self) -> None:
        graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        svc = EntityFactoryService()
        result = svc.generate(graph)
        assert len(result) == 0, "Empty graph → no entities"

    # Intent: a parsed field key such as ctlv3.Status01.temp is ignored rather than exposed.
    # Why: field suffixes are not ebusd registers, so treating them as registers creates bogus entities.
    def test_field_entry_is_not_treated_as_register(self) -> None:
        graph = DeviceGraph(
            nodes={
                "ctlv3": DeviceNode(
                    circuit="ctlv3",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["ctlv3.Status01.temp"],
                    has_data=True,
                )
            },
            raw_registers={"ctlv3.Status01.temp": "21.5"},
            placeholder_registers=set(),
        )

        assert EntityFactoryService().generate(graph) == []

    # Intent: an unmapped composite register such as bai.SetModeOverride is not exposed as a raw sensor.
    # Why: raw semicolon payloads must never surface as sensor values.
    def test_unmapped_composite_register_is_not_exposed_as_raw_sensor(self) -> None:
        graph = DeviceGraph(
            nodes={
                "bai": DeviceNode(
                    circuit="bai",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["bai.SetModeOverride"],
                    has_data=True,
                )
            },
            raw_registers={"bai.SetModeOverride": "0;55.0;45.0;-;-;0;0;0;-;0;0;0"},
            placeholder_registers=set(),
        )

        assert EntityFactoryService().generate(graph) == []

    # Intent: an empty date sentinel does not produce a sensor entity.
    # Why: empty ebusd date placeholders must not appear as sensor values.
    def test_empty_date_value_is_not_exposed_as_sensor(self) -> None:
        graph = DeviceGraph(
            nodes={
                "sc": DeviceNode(
                    circuit="sc",
                    device_type=DeviceType.SOLAR,
                    registers=["sc.Date"],
                    has_data=True,
                )
            },
            raw_registers={"sc.Date": "-.-.-"},
            placeholder_registers=set(),
        )

        assert EntityFactoryService().generate(graph) == []


class TestBackwardCompatibility:
    """EntityDescription structure compatibility."""

    # Intent: generated entities expose the expected EntityDescription attributes with the correct types.
    # Why: platform modules and unique-id logic depend on this field contract.
    def test_entity_description_structure(self) -> None:
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        e = result[0]
        assert hasattr(e, "circuit")
        assert hasattr(e, "name")
        assert hasattr(e, "field")
        assert hasattr(e, "unique_id") and isinstance(e.unique_id, str)
        assert hasattr(e, "key") and isinstance(e.key, str)
        assert hasattr(e, "device_circuit") and isinstance(e.device_circuit, str)
        assert hasattr(e, "entity_type") and isinstance(e.entity_type, str)
        assert hasattr(e, "enabled_by_default")
        assert e.field == "value"


class TestResolveDeviceCircuit:
    """Unit tests for _resolve_device_circuit helper."""

    # Intent: _resolve_device_circuit returns the sub-device circuit when the sub-device has data.
    # Why: pins the helper contract used by entity routing.
    def test_sub_device_with_data_returns_own(self) -> None:
        graph = _build_graph()
        node = graph.nodes["z1"]
        assert _resolve_device_circuit("ctlv2.Z1DayTemp", node, graph) == "z1"

    # Intent: _resolve_device_circuit falls back to the parent circuit when the sub-device has no data.
    # Why: avoids routing no-data registers to a non-existent zone device.
    def test_sub_device_without_data_returns_parent(self) -> None:
        graph = _build_graph({"z1_has_data": False})
        node = graph.nodes["z1"]
        assert _resolve_device_circuit("ctlv2.Z1DayTemp", node, graph) == "ctlv2"

    # Intent: _resolve_device_circuit returns a top-level node's own circuit.
    # Why: top-level devices such as hmu must not be reassigned to a parent.
    def test_top_level_returns_own(self) -> None:
        graph = _build_graph()
        node = graph.nodes["hmu"]
        assert _resolve_device_circuit("hmu.Status01", node, graph) == "hmu"

    # Intent: the solar/hydraulic-scheme register routes to the controller device, not the sc circuit.
    # Why: the hydraulic scheme is controller configuration and must appear on ctlv2.
    def test_sc_hydraulic_scheme_belongs_to_controller(self) -> None:
        graph = _build_graph()
        graph.nodes["sc"] = DeviceNode(
            circuit="sc",
            device_type=DeviceType.UNKNOWN,
            registers=["sc.HydraulicScheme"],
            has_data=True,
        )
        graph.raw_registers["sc.HydraulicScheme"] = "8"

        entities = EntityFactoryService().generate(graph)

        entity = next(e for e in entities if e.key == "sc.HydraulicScheme.value")
        assert entity.device_circuit == "ctlv2"

    # Intent: _resolve_device_circuit returns the node's own circuit when it has no parent.
    # Why: guards against a None parent resolving to an empty circuit.
    def test_no_parent_returns_own(self) -> None:
        graph = _build_graph()
        node = graph.nodes["z1"]
        node.parent = None
        assert _resolve_device_circuit("ctlv2.Z1DayTemp", node, graph) == "z1"


# =============================================================================
# Integration tests with real fixture data
# =============================================================================


class TestGenerateFromFixtureGraphs:
    """Entity generation from real fixture DeviceGraphs."""

    # Intent: a real aroTHERM find output generates a large, well-formed entity set across hmu and ctlv2.
    # Why: end-to-end fixture check that discovery plus the factory produce usable entities offline.
    def test_generate_from_arotherm_graph(self) -> None:
        lines = load_find_lines("arotherm_find.txt")
        graph = DiscoveryService.build_device_graph(lines)
        svc = EntityFactoryService()
        entities = svc.generate(graph)
        assert len(entities) > 50
        assert any(e.circuit == "hmu" for e in entities)
        assert any(e.circuit == "ctlv2" for e in entities)
        for e in entities:
            assert isinstance(e.unique_id, str)
            assert isinstance(e.key, str)
        assert any(e.enabled_by_default for e in entities)

    # Intent: a basv find output generates entities including from the basv circuit.
    # Why: verifies non-ctlv2 controller hardware is handled by the factory.
    def test_generate_from_basv_graph(self) -> None:
        lines = load_find_lines("community/basv_find.txt")
        graph = DiscoveryService.build_device_graph(lines)
        svc = EntityFactoryService()
        entities = svc.generate(graph)
        assert len(entities) > 0
        assert any(e.circuit == "basv" for e in entities), "Expected entities from basv circuit"

    # Intent: preserve active Z2 entities that share the ctlv2 source circuit with Z1.
    # Why: single-source-circuit multi-zone setups must split Z2 registers off the controller without losing them.
    def test_generate_active_z2_entities_from_single_circuit_fixture(self) -> None:
        lines = load_find_lines("community/multizone_single_circuit_find.txt")
        graph = DiscoveryService.build_device_graph(lines)
        entities = EntityFactoryService().generate(graph)
        z2_entities = [entity for entity in entities if entity.name.startswith("Z2")]
        assert {entity.name for entity in z2_entities} == {
            "Z2RoomTemp",
            "Z2DayTemp",
            "Z2OpMode",
            "Z2ActualRoomTempDesired",
        }
        assert {entity.device_circuit for entity in z2_entities} == {"z2"}

    # Intent: a YAML icon override is applied to the generated entity metadata.
    # Why: users can customize entity icons without code changes.
    def test_yaml_override_icon(self) -> None:
        lines = load_find_lines("arotherm_find.txt")
        graph = DiscoveryService.build_device_graph(lines)
        svc = EntityFactoryService()
        yaml = {"hmu.CurrentConsumedPower": {"icon": "mdi:flash"}}
        entities = svc.generate(graph, yaml_overrides=yaml)
        matches = [e for e in entities if e.key == "hmu.CurrentConsumedPower.value"]
        assert matches, "Expected hmu.CurrentConsumedPower entity"
        assert matches[0].meta.icon == "mdi:flash"

    # Intent: a YAML entity_type override on a fixture graph changes the entity type.
    # Why: confirms overrides work against real discovered registers, not only synthetic graphs.
    def test_yaml_override_entity_type(self) -> None:
        lines = load_find_lines("arotherm_find.txt")
        graph = DiscoveryService.build_device_graph(lines)
        svc = EntityFactoryService()
        yaml = {"ctlv2.Z1DayTemp": {"entity_type": "number"}}
        entities = svc.generate(graph, yaml_overrides=yaml)
        matches = [e for e in entities if e.key == "ctlv2.Z1DayTemp.value"]
        assert matches, "Expected ctlv2.Z1DayTemp entity"
        assert matches[0].entity_type == "number"

    # Intent: an empty graph yields no entities.
    # Why: documents that the factory has no REGISTER_MAP fallback path.
    def test_empty_graph_generates_no_entities(self) -> None:
        graph = DeviceGraph(
            nodes={},
            raw_registers={},
            placeholder_registers=set(),
        )
        svc = EntityFactoryService()
        entities = svc.generate(graph)
        assert len(entities) == 0, "No fallbacks — empty graph produces no entities"


class TestMultiFieldParsing:
    """Multi-field register parsing (issue #51)."""

    @staticmethod
    def _status01_graph() -> DeviceGraph:
        return DeviceGraph(
            nodes={
                "hmu": DeviceNode(
                    circuit="hmu",
                    device_type=DeviceType.HEAT_PUMP,
                    registers=["hmu.Status01"],
                    has_data=True,
                ),
            },
            raw_registers={"hmu.Status01": "39.5;40.5;-;-;-;off"},
            placeholder_registers=set(),
        )

    # Intent: hmu.Status01 multi-field values split into the named fields temp, temp_1 and pumpstate.
    # Why: issue #51: a compound status register must expose each parsed field instead of one raw string.
    def test_status01_splits_into_named_fields(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._status01_graph())
        fields = {e.field for e in entities if e.name == "Status01"}
        assert "temp" in fields
        assert "temp_1" in fields
        assert "pumpstate" in fields

    # Intent: the Status01 temp and temp_1 fields carry flow/return friendly names and temperature metadata.
    # Why: issue #51: field metadata must match the parsed position.
    def test_status01_flow_return_temperature_meta(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._status01_graph())
        flow = next(e for e in entities if e.field == "temp")
        ret = next(e for e in entities if e.field == "temp_1")
        assert flow.meta.friendly_name == "Flow Temperature"
        assert flow.meta.device_class == "temperature"
        assert flow.meta.unit == "°C"
        assert ret.meta.friendly_name == "Return Temperature"
        assert ret.meta.unit == "°C"

    # Intent: the Status01 field entities have a distinct key per field.
    # Why: duplicate keys would collide in the entity registry.
    def test_status01_field_keys_are_unique(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._status01_graph())
        status_keys = [e.key for e in entities if e.name == "Status01"]
        assert "hmu.Status01.temp" in status_keys
        assert "hmu.Status01.temp_1" in status_keys
        assert "hmu.Status01.pumpstate" in status_keys
        assert len(status_keys) == len(set(status_keys))

    # Intent: placeholder Status01 fields are either omitted or retained with raw_value '-'.
    # Why: guards that empty compound fields are not given fabricated values.
    def test_status01_placeholder_fields_skipped(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._status01_graph())
        status_fields = {e.field for e in entities if e.name == "Status01"}
        assert "temp_2" not in status_fields or any(
            e.field == "temp_2" and e.raw_value == "-" for e in entities if e.name == "Status01"
        )

    # Intent: the original hmu.Status01.value entity is retained alongside the split fields.
    # Why: issue #51: splitting must not remove the raw register entity.
    def test_status01_original_string_entity_kept(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._status01_graph())
        original = [e for e in entities if e.key == "hmu.Status01.value"]
        assert original, "Original Status01 value entity must be kept"
        assert original[0].meta.friendly_name == "Status"


class TestPowerConsumptionUnit:
    """Power unit consistency (issue #52)."""

    # Intent: PowerConsumptionHmu metadata is power in kW.
    # Why: issue #52: a wrong unit breaks Home Assistant statistics and the energy dashboard.
    def test_power_consumption_hmu_unit_is_kw(self) -> None:
        meta = get_meta("hmu", "PowerConsumptionHmu")
        assert meta.unit == "kW"
        assert meta.device_class == "power"


class TestSourceTempMetadata:
    """Source temp metadata (issue #49)."""

    # Intent: SourceTempInput metadata is temperature in degrees Celsius.
    # Why: issue #49: the brine source temperature must render correctly.
    def test_source_temp_input_metadata(self) -> None:
        meta = get_meta("hmu", "SourceTempInput")
        assert meta.device_class == "temperature"
        assert meta.unit == "°C"

    # Intent: SourceTempOutput metadata is temperature in degrees Celsius.
    # Why: issue #49: companion to the source input temperature.
    def test_source_temp_output_metadata(self) -> None:
        meta = get_meta("hmu", "SourceTempOutput")
        assert meta.device_class == "temperature"
        assert meta.unit == "°C"

    # Intent: hmux0 RunDataReturnTemp metadata is temperature in degrees Celsius.
    # Why: issue #49: return temperature must be a measurement on HMUX hardware.
    def test_run_data_return_temperature_metadata(self) -> None:
        meta = get_meta("hmux0", "RunDataReturnTemp")
        assert meta.device_class == "temperature"
        assert meta.unit == "°C"

    # Intent: the issue #99 hmux0 fixture generates enabled entities with
    # correct metadata for return temp, yield and COP registers.
    # Why: issue #99: aliasing hmux0 to a generic CSV dropped these registers, so this pins them.
    def test_hmux0_yield_and_cop_entities_from_issue_99_fixture(self) -> None:
        graph = DiscoveryService.build_device_graph(load_find_lines("community/hmux0_yield_cop_find.txt"))
        entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

        for register in (
            "RunDataReturnTemp",
            "YieldHc",
            "YieldHcDay",
            "YieldHcMonth",
            "YieldHwc",
            "YieldHwcDay",
            "YieldHwcMonth",
            "CopHc",
            "CopHcMonth",
            "CopHwc",
            "CopHwcMonth",
        ):
            entity = entities.get(f"hmux0.{register}.value")
            assert entity is not None, register
            assert entity.enabled_by_default is True, register

        assert entities["hmux0.RunDataReturnTemp.value"].meta.device_class == "temperature"
        assert entities["hmux0.RunDataReturnTemp.value"].meta.unit == "°C"
        assert entities["hmux0.YieldHc.value"].meta.device_class == "energy"
        assert entities["hmux0.YieldHc.value"].meta.unit == "kWh"
        assert entities["hmux0.YieldHc.value"].meta.state_class == "total_increasing"
        assert entities["hmux0.CopHc.value"].meta.device_class == ""
        assert entities["hmux0.CopHc.value"].meta.state_class == "measurement"


class TestStateClassSemantics:
    """State class renders history as line graph (issue #54)."""

    @staticmethod
    def _cop_graph() -> DeviceGraph:
        return DeviceGraph(
            nodes={
                "hmu": DeviceNode(
                    circuit="hmu",
                    device_type=DeviceType.HEAT_PUMP,
                    registers=["hmu.CopHc", "hmu.CopCooling"],
                    has_data=True,
                ),
            },
            raw_registers={"hmu.CopHc": "4.2", "hmu.CopCooling": "3.8"},
            placeholder_registers=set(),
        )

    # Intent: COP entities get state_class measurement.
    # Why: issue #54: without it Home Assistant renders COP as a step or bar instead of a line graph.
    def test_cop_entities_measurement_state_class(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._cop_graph())
        cop = [e for e in entities if e.name.startswith("Cop")]
        assert cop
        for entity in cop:
            assert entity.meta.state_class == "measurement"

    # Intent: Z1RoomTemp metadata is a temperature measurement.
    # Why: issue #54: room temperature must plot as a measurement line.
    def test_room_temp_measurement_state_class(self) -> None:
        meta = get_meta("ctlv2", "Z1RoomTemp")
        assert meta.state_class == "measurement"
        assert meta.device_class == "temperature"


class TestPrEnergySum:
    """Electrical energy consumption registers (issue #53)."""

    # Intent: ctlv2 PrEnergySumHc metadata is energy in kWh with total_increasing.
    # Why: issue #53: energy totals must feed the energy dashboard as cumulative sensors.
    def test_pr_energy_sum_meta_is_energy(self) -> None:
        meta = get_meta("ctlv2", "PrEnergySumHc")
        assert meta.device_class == "energy"
        assert meta.unit == "kWh"
        assert meta.state_class == "total_increasing"

    # Intent: ctlv3 PrEnergySumHwc gets the same energy metadata through fallback resolution.
    # Why: issue #53: controllers exposing the register under ctlv3 must not lose energy classification.
    def test_ctlv3_fallback_gets_energy_meta(self) -> None:
        meta = get_meta("ctlv3", "PrEnergySumHwc")
        assert meta.device_class == "energy"
        assert meta.unit == "kWh"
        assert meta.state_class == "total_increasing"

    # Intent: the aroTHERM Plus prenergy discovery dump generates enabled PrEnergySum entities with energy metadata.
    # Why: issue #53: guards real fixture coverage for the energy registers.
    def test_prenergy_fixture_entities_have_energy_meta(self) -> None:
        lines = load_find_lines("community/arotherm_plus_prenergy_discovery.yaml")
        graph = DiscoveryService.build_device_graph(lines)
        entities = EntityFactoryService().generate(graph)
        pre = [e for e in entities if "PrEnergySum" in e.name]
        assert pre, "PrEnergySum entities must be generated"
        for entity in pre:
            assert entity.meta.device_class == "energy"
            assert entity.meta.unit == "kWh"
            assert entity.meta.state_class == "total_increasing"
            assert entity.enabled_by_default is True

    # aroTHERM Plus run dumps (#53 follow-up): PrEnergySum* stay no-data even
    # during active runs, but entities must still be generated (and enabled).
    # Intent: cooling and HWC run dumps still generate enabled PrEnergySum entities even when values are no-data.
    # Why: issue #53 follow-up: entities must persist during active runs for energy accounting.
    def test_run_fixtures_keep_prenergy_entities(self) -> None:
        for fixture in (
            "community/arotherm_plus_cooling_run_discovery.yaml",
            "community/arotherm_plus_hwc_run_discovery.yaml",
        ):
            lines = load_find_lines(fixture)
            graph = DiscoveryService.build_device_graph(lines)
            entities = EntityFactoryService().generate(graph)
            pre = [e for e in entities if "PrEnergySum" in e.name]
            assert pre, f"{fixture}: PrEnergySum entities must be generated"
            for entity in pre:
                assert entity.meta.device_class == "energy"
                assert entity.meta.unit == "kWh"
                assert entity.meta.state_class == "total_increasing"
                assert entity.enabled_by_default is True

    # Live yield/energy registers from the run dumps map to energy entities.
    # Intent: live Yield and TotalEnergyUsage registers in the run dumps map to energy/kWh entities.
    # Why: issue #53 follow-up: live consumption must register as energy, not as raw strings.
    def test_run_fixtures_live_energy_registers_are_energy(self) -> None:
        for fixture in (
            "community/arotherm_plus_cooling_run_discovery.yaml",
            "community/arotherm_plus_hwc_run_discovery.yaml",
        ):
            lines = load_find_lines(fixture)
            graph = DiscoveryService.build_device_graph(lines)
            entities = EntityFactoryService().generate(graph)
            by_key = {e.key: e for e in entities}
            for reg in ("hmu.YieldHc", "hmu.YieldHwc", "hmu.TotalEnergyUsage", "hmu.YieldCooling"):
                entity = by_key.get(f"{reg}.value")
                assert entity is not None, f"{fixture}: missing {reg}"
                assert entity.meta.device_class == "energy"
                assert entity.meta.unit == "kWh"

    # ctlv2 cooling fixture (Mark's own system while cooling): the live cooling
    # data registers exposed by ebusd map to proper entities; the cooling-program
    # registers that this hardware does not have must not appear as entities.
    # Intent: the ctlv2 cooling dump exposes live cooling registers and omits unsupported cooling-program registers.
    # Why: prevents entities for hardware features the unit does not implement.
    def test_ctlv2_cooling_fixture_entities(self) -> None:
        lines = load_find_lines("community/arotherm_plus_ctlv2_cooling_discovery.yaml")
        graph = DiscoveryService.build_device_graph(lines)
        entities = EntityFactoryService().generate(graph)
        by_key = {e.key: e for e in entities}
        for reg in (
            "hmu.CopCooling.value",
            "hmu.CopCoolingMonth.value",
            "hmu.YieldCoolDay.value",
            "hmu.YieldCooling.value",
            "hmu.YieldCoolingMonth.value",
            "ctlv2.Z1CoolingTemp.value",
        ):
            assert by_key.get(reg) is not None, f"missing {reg}"
        for reg in (
            "ctlv2.Hc1CoolingEnabled.value",
            "ctlv2.Z1CoolingOpMode.value",
            "ctlv2.Z1CoolingTempDesired.value",
        ):
            assert by_key.get(reg) is None, f"unexpected {reg}"

    # The runtime-defined manual cooling dates (GitHub issue #644) must appear as
    # sensor entities when present in the find output, carrying the mapped
    # friendly name.
    # Intent: the runtime-defined ManualCoolingStartDate and ManualCoolingEndDate
    # registers generate sensor entities with the mapped names.
    # Why: issue #644: the manual cooling dates must be usable from Home Assistant.
    def test_manual_cooling_dates_entities(self) -> None:
        lines = [
            "ctlv2 ManualCoolingStartDate = 14.08.2026",
            "ctlv2 ManualCoolingEndDate = 15.08.2026",
        ]
        graph = DiscoveryService.build_device_graph(lines)
        entities = EntityFactoryService().generate(graph)
        by_key = {e.key: e for e in entities}
        start = by_key.get("ctlv2.ManualCoolingStartDate.value")
        end = by_key.get("ctlv2.ManualCoolingEndDate.value")
        assert start is not None
        assert end is not None
        assert start.entity_type == "sensor"
        assert end.entity_type == "sensor"
        assert start.meta.friendly_name == "Manual Cooling Start Date"
        assert end.meta.friendly_name == "Manual Cooling End Date"


class TestStatEnergyRegisters:
    """Heat-pump statistics energy registers on non-hmu circuits (issue #53)."""

    # Intent: basv3 StatElectricEnergySumCool resolves to energy/kWh/total_increasing metadata.
    # Why: issue #53: non-hmu controllers need the same energy classification.
    def test_basv3_gets_hmu_energy_meta(self) -> None:
        meta = get_meta("basv3", "StatElectricEnergySumCool")
        assert meta.device_class == "energy"
        assert meta.unit == "kWh"
        assert meta.state_class == "total_increasing"

    # Intent: the basv3 fixture generates enabled energy entities for every Stat*EnergySum register.
    # Why: issue #53: locks the controller energy register family.
    def test_basv3_fixture_stat_energy_entities(self) -> None:
        lines = load_find_lines("community/arotherm_plus_basv3_discovery.yaml")
        graph = DiscoveryService.build_device_graph(lines)
        entities = EntityFactoryService().generate(graph)
        by_key = {e.key: e for e in entities}
        for reg in (
            "basv3.StatElectricEnergySum.value",
            "basv3.StatElectricEnergySumCool.value",
            "basv3.StatElectricEnergySumHc.value",
            "basv3.StatElectricEnergySumHwc.value",
            "basv3.StatEnvironmentEnergySum.value",
            "basv3.StatEnvironmentEnergySumCool.value",
            "basv3.StatEnvironmentEnergySumHc.value",
            "basv3.StatEnvironmentEnergySumHwc.value",
        ):
            entity = by_key.get(reg)
            assert entity is not None, f"missing {reg}"
            assert entity.meta.device_class == "energy", reg
            assert entity.meta.unit == "kWh", reg
            assert entity.meta.state_class == "total_increasing", reg
            assert entity.enabled_by_default is True, reg

    # Intent: registers on a no-data orphan circuit such as vwzio are not exposed as standalone entities.
    # Why: prevents an empty disconnected node from creating phantom energy sensors.
    def test_no_data_orphan_circuit_suppressed(self) -> None:
        lines = load_find_lines("community/arotherm_plus_basv3_discovery.yaml")
        graph = DiscoveryService.build_device_graph(lines)
        entities = EntityFactoryService().generate(graph)
        # vwzio carries no live data and has no parent device, so its registers
        # are not exposed as standalone entities (consistent no-data handling).
        by_key = {e.key: e for e in entities}
        assert "vwzio.StatElectricEnergySumCool.value" not in by_key

    # flexoTHERM (brine-water, no active cooling) reports the cooling energy
    # register as "element not found" — it must not appear as an entity.
    # Intent: flexoTHERM, which has no active cooling, does not expose cooling Stat*EnergySum entities.
    # Why: issue #50: element-not-found registers must stay hidden.
    def test_flexotherm_has_no_cooling_energy_entity(self) -> None:
        graph = DiscoveryService.build_device_graph(load_find_lines("community/flexotherm_discovery.yaml"))
        by_key = {e.key: e for e in EntityFactoryService().generate(graph)}
        assert "hmu.StatElectricEnergySumCool.value" not in by_key
        assert "hmu.StatEnvironmentEnergySumCool.value" not in by_key

    # flexoTHERM v1.3.3 dump (issue #50), captured during an active passive
    # (brine) cooling cycle: flow temp ~19 °C at 31 °C outside, releaseCooling=1,
    # but RunDataStatuscode=0 — the compressor never runs, so the compressor-based
    # counters stay at 0 (YieldCoolDay=0.0, HoursCool=0) and cumulative cooling
    # totals return "element not found" and must stay hidden.
    # Intent: the flexoTHERM v1.3.3 passive-cooling dump exposes daily cooling
    # yield and runtime but hides element-not-found cumulative cooling registers.
    # Why: issue #50: distinguishes real passive-cooling data from unavailable cumulative totals.
    def test_flexotherm_133_cooling_daily_yield_entities(self) -> None:
        graph = DiscoveryService.build_device_graph(load_find_lines("community/flexotherm_133_cooling_discovery.yaml"))
        by_key = {e.key: e for e in EntityFactoryService().generate(graph)}
        yield_day = by_key.get("hmu.YieldCoolDay.value")
        assert yield_day is not None, "daily cooling yield must be an entity"
        assert yield_day.meta.device_class == "energy"
        assert yield_day.meta.unit == "kWh"
        runtime = by_key.get("hmu.HoursCool.value")
        assert runtime is not None, "cooling runtime must be an entity"
        assert runtime.meta.device_class == "duration"
        for reg in (
            "hmu.StatElectricEnergySumCool.value",
            "hmu.StatEnvironmentEnergySumCool.value",
            "hmu.YieldCooling.value",
            "hmu.YieldCoolingMonth.value",
            "hmu.CopCooling.value",
            "hmu.CopCoolingMonth.value",
        ):
            assert reg not in by_key, f"element-not-found register must stay hidden: {reg}"

    # flexoTHERM v1.3.3 dump (issue #50): ctlv3/dhw (live Hwc registers) and
    # hmu/dhw (all no-data) both map to the logical "dhw" device name. The
    # later one used to overwrite the live node, hiding the DHW sensors and
    # leaving water_heater without a current temperature.
    # Intent: merging the ctlv3/dhw and hmu/dhw logical nodes keeps the live variant's registers and data.
    # Why: issue #50: the no-data node used to overwrite the live one, hiding DHW sensors.
    def test_flexotherm_dhw_sub_device_merge_keeps_live_registers(self) -> None:
        graph = DiscoveryService.build_device_graph(load_find_lines("community/flexotherm_133_cooling_discovery.yaml"))
        dhw = graph.nodes.get("dhw")
        assert dhw is not None
        assert dhw.has_data, "dhw node must keep the live variant's data"
        assert "ctlv3.HwcStorageTemp" in dhw.registers
        by_key = {e.key: e for e in EntityFactoryService().generate(graph)}
        for reg in (
            "ctlv3.HwcStorageTemp.value",
            "ctlv3.HwcTempDesired.value",
            "ctlv3.HwcOpMode.value",
        ):
            entity = by_key.get(reg)
            assert entity is not None, f"live DHW register must be an entity: {reg}"

    # flexoCOMPACT (air/water aroTHERM with active cooling) reports cooling
    # energy live on both hmu and ctlv2; both get hmu energy metadata (issue #50).
    # Intent: flexoCOMPACT exposes live cooling energy on both hmu and ctlv2 plus SourceTempInput as a temperature.
    # Why: issues #49 and #50: covers air/water active-cooling hardware.
    def test_flexocompact_cooling_energy_entities(self) -> None:
        graph = DiscoveryService.build_device_graph(load_find_lines("community/flexocompact_find.txt"))
        by_key = {e.key: e for e in EntityFactoryService().generate(graph)}
        for reg in (
            "hmu.StatElectricEnergySumCool.value",
            "hmu.StatEnvironmentEnergySumCool.value",
            "ctlv2.StatElectricEnergySumCool.value",
            "ctlv2.StatEnvironmentEnergySumCool.value",
        ):
            entity = by_key.get(reg)
            assert entity is not None, f"missing {reg}"
            assert entity.meta.device_class == "energy", reg
            assert entity.meta.unit == "kWh", reg
            assert entity.meta.state_class == "total_increasing", reg
        # SourceTempInput is returned by find on this air/water unit (issue #49)
        # and must generate a temperature entity from the REGISTER_MAP metadata.
        src = by_key.get("hmu.SourceTempInput.value")
        assert src is not None, "missing hmu.SourceTempInput"
        assert src.meta.device_class == "temperature"
        assert src.meta.unit == "°C"


class TestBuildingCircuitFlowUnit:
    """Building circuit flow unit (issue #55)."""

    # Intent: BuildingCircuitFlow metadata uses litres per hour.
    # Why: issue #55: a wrong flow unit misleads users and breaks unit conversion.
    def test_building_circuit_flow_unit_is_l_per_hour(self) -> None:
        meta = get_meta("hmu", "BuildingCircuitFlow")
        assert meta.unit == "l/h"


class TestCaseInsensitiveRegisterDedup:
    """Registers differing only by case must not create duplicate entities."""

    @staticmethod
    def _case_graph() -> DeviceGraph:
        return DeviceGraph(
            nodes={
                "ctlv2": DeviceNode(
                    circuit="ctlv2",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["ctlv2.HwcSfMode", "ctlv2.HwcSFMode"],
                    has_data=True,
                ),
            },
            raw_registers={"ctlv2.HwcSfMode": "auto", "ctlv2.HwcSFMode": "auto"},
            placeholder_registers=set(),
        )

    # Intent: registers differing only by case collapse into a single entity with one unique id.
    # Why: ebusd-dependent casing would otherwise create duplicate unique ids.
    def test_case_variants_produce_single_entity(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._case_graph())
        uids = [e.unique_id for e in entities]
        assert len(uids) == len(set(uids)), f"duplicate unique IDs: {uids}"
        assert uids.count("ebusd_ctlv2_hwcsfmode") == 1


class TestCompressorRunStatsSplit:
    """CompressorHc/CompressorHwc multi-field split (issue #62)."""

    @staticmethod
    def _compressor_graph() -> DeviceGraph:
        return DeviceGraph(
            nodes={
                "hmu": DeviceNode(
                    circuit="hmu",
                    device_type=DeviceType.HEAT_PUMP,
                    registers=["hmu.CompressorHc", "hmu.CompressorHwc"],
                    has_data=True,
                ),
            },
            raw_registers={
                "hmu.CompressorHc": "187055;4327",
                "hmu.CompressorHwc": "51989;733",
            },
            placeholder_registers=set(),
        )

    # Intent: CompressorHc splits into runtime and cycles entities with min/duration/total_increasing metadata.
    # Why: issue #62: compressor stats must be two typed sensors, not one raw pair.
    def test_compressor_hc_splits_into_runtime_and_cycles(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._compressor_graph())
        keys = [e.key for e in entities if e.name == "CompressorHc"]
        assert "hmu.CompressorHc.runtime" in keys
        assert "hmu.CompressorHc.cycles" in keys
        runtime = next(e for e in entities if e.key == "hmu.CompressorHc.runtime")
        cycles = next(e for e in entities if e.key == "hmu.CompressorHc.cycles")
        assert runtime.raw_value == "187055"
        assert cycles.raw_value == "4327"
        assert runtime.meta.unit == "min"
        assert runtime.meta.device_class == "duration"
        assert runtime.meta.state_class == "total_increasing"

    # Intent: CompressorHwc splits into runtime and cycles with the pair values split correctly.
    # Why: issue #62: DHW compressor stats need the same split as heating.
    def test_compressor_hwc_splits_into_runtime_and_cycles(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._compressor_graph())
        runtime = next(e for e in entities if e.key == "hmu.CompressorHwc.runtime")
        cycles = next(e for e in entities if e.key == "hmu.CompressorHwc.cycles")
        assert runtime.raw_value == "51989"
        assert cycles.raw_value == "733"

    # Intent: the split compressor entities each have a unique id.
    # Why: issue #62: duplicate unique ids would make Home Assistant drop entities.
    def test_compressor_split_unique_ids(self) -> None:
        svc = EntityFactoryService()
        entities = svc.generate(self._compressor_graph())
        uids = [e.unique_id for e in entities]
        assert len(uids) == len(set(uids)), f"duplicate unique IDs: {uids}"
        assert "ebusd_hmu_compressorhc_runtime" in uids
        assert "ebusd_hmu_compressorhc_cycles" in uids
        assert "ebusd_hmu_compressorhwc_runtime" in uids


class TestOutsideTempDeviceClass:
    """OutsideTemp must be a graphable measurement (issue #61)."""

    # Intent: ctlv2 OutsideTemp metadata is temperature with measurement state class.
    # Why: issue #61: outside temperature must graph as a measurement.
    def test_ctlv2_outsidetemp_is_temperature(self) -> None:
        meta = get_meta("ctlv2", "OutsideTemp")
        assert meta.device_class == "temperature"
        assert meta.unit == "°C"
        assert meta.state_class == "measurement"

    # Intent: basv3 OutsideTemp falls back to the temperature metadata.
    # Why: issue #61: non-ctlv2 controllers must not lose outside-temperature classification.
    def test_basv3_outsidetemp_falls_back_to_temperature(self) -> None:
        meta = get_meta("basv3", "OutsideTemp")
        assert meta.device_class == "temperature"
        assert meta.unit == "°C"
        assert meta.state_class == "measurement"

    # Intent: a generated basv3 OutsideTemp entity carries temperature measurement metadata.
    # Why: issue #61: verifies the fallback survives into the generated entity.
    def test_basv3_outsidetemp_entity_has_device_class(self) -> None:
        graph = DeviceGraph(
            nodes={
                "basv3": DeviceNode(
                    circuit="basv3",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["basv3.OutsideTemp"],
                    has_data=True,
                ),
            },
            raw_registers={"basv3.OutsideTemp": "24.6719"},
            placeholder_registers=set(),
        )
        entities = EntityFactoryService().generate(graph)
        entity = next(e for e in entities if e.key == "basv3.OutsideTemp.value")
        assert entity.meta.device_class == "temperature"
        assert entity.meta.state_class == "measurement"

    # Intent: the basv3 discovery fixture generates an OutsideTemp entity with measurement metadata.
    # Why: issue #61: fixture-level regression for outside temperature.
    def test_basv3_fixture_outsidetemp_is_measurement(self) -> None:
        lines = load_find_lines("community/arotherm_plus_basv3_discovery.yaml")
        graph = DiscoveryService.build_device_graph(lines)
        entities = EntityFactoryService().generate(graph)
        matches = [e for e in entities if e.name == "OutsideTemp"]
        assert matches, "basv3 OutsideTemp entity must be generated"
        entity = next(e for e in matches if e.circuit == "basv3")
        assert entity.meta.device_class == "temperature"
        assert entity.meta.unit == "°C"
        assert entity.meta.state_class == "measurement"

    # Intent: the 2-zone fixture generates all four split compressor entities with unique ids.
    # Why: end-to-end coverage of compressor splitting on a multi-zone system.
    def test_2zone_fixture_compressor_split(self) -> None:
        lines = load_find_lines("community/arotherm_plus_2zone_discovery.yaml")
        graph = DiscoveryService.build_device_graph(lines)
        entities = EntityFactoryService().generate(graph)
        keys = {e.key for e in entities}
        assert "hmu.CompressorHc.runtime" in keys
        assert "hmu.CompressorHc.cycles" in keys
        assert "hmu.CompressorHwc.runtime" in keys
        assert "hmu.CompressorHwc.cycles" in keys
        uids = [e.unique_id for e in entities]
        assert len(uids) == len(set(uids)), f"duplicate unique IDs: {uids}"
