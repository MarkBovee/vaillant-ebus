"""Unit tests for EntityFactoryService."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

BACKEND_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend"
COMPONENT_PATH = BACKEND_PATH.parent

for name in ("vaillant_ebus", "vaillant_ebus.backend"):
    pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    pkg.__path__ = [str(COMPONENT_PATH)] if name == "vaillant_ebus" else [str(BACKEND_PATH)]
    sys.modules[name] = pkg

MODELS_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.models", BACKEND_PATH / "models.py"
)
assert MODELS_SPEC and MODELS_SPEC.loader
MODELS = importlib.util.module_from_spec(MODELS_SPEC)
sys.modules["vaillant_ebus.backend.models"] = MODELS
MODELS_SPEC.loader.exec_module(MODELS)

MAPPING_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.mapping", BACKEND_PATH / "mapping.py"
)
assert MAPPING_SPEC and MAPPING_SPEC.loader
MAPPING = importlib.util.module_from_spec(MAPPING_SPEC)
sys.modules["vaillant_ebus.backend.mapping"] = MAPPING
MAPPING_SPEC.loader.exec_module(MAPPING)

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
from vaillant_ebus.backend.mapping import REGISTER_MAP, RegisterMeta  # noqa: E402
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
            registers=[],
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
        },
        placeholder_registers=set(),
    )


class TestEntityGeneration:
    """Entity generation from DeviceGraph."""

    def test_generate_returns_entities(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        assert result, "Expected non-empty entity list"

    def test_generate_count(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        # 3 hmu + 2 z1 + 2 dhw + 1 REGISTER_MAP fallback (hmu.RunDataCompressorSpeed)
        # hmu.RunDataLowPressure has enabled=False, excluded
        assert len(result) >= 7, f"Expected at least 7 entities, got {len(result)}"

    def test_entities_have_unique_keys(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        keys = [e.key for e in result]
        assert len(keys) == len(set(keys)), f"Duplicate keys: {keys}"

    def test_entities_have_keys(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        for e in result:
            assert e.key.startswith(f"{e.circuit}.{e.name}."), f"Bad key format: {e.key}"
            assert e.key.count(".") == 2, f"Key should have 2 dots: {e.key}"


class TestDeviceCircuitResolution:
    """Device circuit assignment from device graph."""

    def test_device_circuit_zone_with_data(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        z1_entities = [e for e in result if e.name == "Z1DayTemp"]
        assert z1_entities, "Expected Z1DayTemp entity"
        assert z1_entities[0].device_circuit == "z1", f"Expected z1, got {z1_entities[0].device_circuit}"

    def test_device_circuit_zone_without_data(self):
        graph = _build_graph({"z1_has_data": False})
        svc = EntityFactoryService()
        result = svc.generate(graph)
        z1_entities = [e for e in result if e.name == "Z1DayTemp"]
        assert z1_entities, "Expected Z1DayTemp entity"
        assert z1_entities[0].device_circuit == "ctlv2", f"Expected ctlv2, got {z1_entities[0].device_circuit}"

    def test_device_circuit_z2_without_data(self):
        graph = _build_graph({"include_z2": True, "z2_has_data": False})
        svc = EntityFactoryService()
        result = svc.generate(graph)
        z2_entities = [e for e in result if e.name == "Z2DayTemp"]
        assert z2_entities, "Expected Z2DayTemp entity"
        assert z2_entities[0].device_circuit == "ctlv2", f"Expected ctlv2, got {z2_entities[0].device_circuit}"

    def test_device_circuit_dhw(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        dhw_entities = [e for e in result if e.name == "HwcTempDesired"]
        assert dhw_entities, "Expected HwcTempDesired entity"
        assert dhw_entities[0].device_circuit == "dhw", f"Expected dhw, got {dhw_entities[0].device_circuit}"

    def test_device_circuit_hmu(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        hmu_entities = [e for e in result if e.name == "FlowTemp"]
        assert hmu_entities, "Expected FlowTemp entity"
        assert hmu_entities[0].device_circuit == "hmu", f"Expected hmu, got {hmu_entities[0].device_circuit}"


class TestEnabledByDefault:
    """Entity enabled_by_default determination."""

    def test_enabled_by_default_known_register(self):
        result = _determine_enabled_by_default(
            "hmu.Status01", "Standby", True, RegisterMeta(enabled=True)
        )
        assert result is True

    def test_enabled_by_default_has_data(self):
        result = _determine_enabled_by_default(
            "unknown.RegName", "42", True, RegisterMeta(enabled=True)
        )
        assert result is True

    def test_enabled_by_default_placeholder_not_known(self):
        result = _determine_enabled_by_default(
            "unknown.RegName", "-", False, RegisterMeta(enabled=True)
        )
        assert result is False

    def test_enabled_by_default_placeholder_known(self):
        result = _determine_enabled_by_default(
            "hmu.Status01", "-", False, REGISTER_MAP["hmu.Status01"]
        )
        assert result is True

    def test_enabled_by_default_meta_disabled(self):
        result = _determine_enabled_by_default(
            "hmu.RunDataLowPressure", "-", False, REGISTER_MAP["hmu.RunDataLowPressure"]
        )
        assert result is False


class TestYamlOverrides:
    """YAML override handling."""

    def test_yaml_override_changes_entity_type(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        yaml = {"hmu.Status01": {"entity_type": "number"}}
        result = svc.generate(graph, yaml_overrides=yaml)
        entity = [e for e in result if e.key == "hmu.Status01.value"][0]
        assert entity.entity_type == "number", f"Expected number, got {entity.entity_type}"

    def test_yaml_override_force_enabled(self):
        graph = _build_graph()
        graph.nodes["z1"].has_data = False
        graph.raw_registers["ctlv2.Z1OpMode"] = "-"
        svc = EntityFactoryService()
        yaml = {"ctlv2.Z1OpMode": {"enabled": True}}
        result = svc.generate(graph, yaml_overrides=yaml)
        entity = [e for e in result if e.key == "ctlv2.Z1OpMode.value"][0]
        assert entity.enabled_by_default is True

    def test_yaml_override_device_class(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        yaml = {"hmu.FlowTemp": {"device_class": "temperature_new"}}
        result = svc.generate(graph, yaml_overrides=yaml)
        entity = [e for e in result if e.key == "hmu.FlowTemp.value"][0]
        assert entity.meta.device_class == "temperature_new"


class TestRegisterMapFallback:
    """REGISTER_MAP fallback entities."""

    def test_registermap_fallback_generates_entity(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        keys = {e.key for e in result}
        assert "hmu.RunDataCompressorSpeed.value" in keys, "Expected fallback entity"

    def test_registermap_fallback_disabled_entry(self):
        graph = _build_graph()
        svc = EntityFactoryService()
        result = svc.generate(graph)
        keys = {e.key for e in result}
        assert "hmu.RunDataLowPressure.value" not in keys, "Disabled entry should be excluded"


class TestBackwardCompatibility:
    """EntityDescription structure compatibility."""

    def test_entity_description_structure(self):
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

    def test_sub_device_with_data_returns_own(self):
        graph = _build_graph()
        node = graph.nodes["z1"]
        assert _resolve_device_circuit("ctlv2.Z1DayTemp", node, graph) == "z1"

    def test_sub_device_without_data_returns_parent(self):
        graph = _build_graph({"z1_has_data": False})
        node = graph.nodes["z1"]
        assert _resolve_device_circuit("ctlv2.Z1DayTemp", node, graph) == "ctlv2"

    def test_top_level_returns_own(self):
        graph = _build_graph()
        node = graph.nodes["hmu"]
        assert _resolve_device_circuit("hmu.Status01", node, graph) == "hmu"

    def test_no_parent_returns_own(self):
        graph = _build_graph()
        node = graph.nodes["z1"]
        node.parent = None
        assert _resolve_device_circuit("ctlv2.Z1DayTemp", node, graph) == "z1"


class TestLegacyWrapper:
    """Legacy generate_entity_descriptions raises NotImplementedError."""

    def test_legacy_wrapper_raises(self):
        from vaillant_ebus.backend.entity_factory import generate_entity_descriptions
        try:
            generate_entity_descriptions([])
            assert False, "Should have raised NotImplementedError"
        except NotImplementedError:
            pass
