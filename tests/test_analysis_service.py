"""Unit tests for AnalysisService (background device/entity discovery)."""

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

for mod_name, mod_file in (
    ("vaillant_ebus.backend.models", "models.py"),
    ("vaillant_ebus.backend.mapping", "mapping.py"),
    ("vaillant_ebus.backend.ebus_service", "ebus_service.py"),
    ("vaillant_ebus.backend.discovery_service", "discovery_service.py"),
    ("vaillant_ebus.backend.entity_factory", "entity_factory.py"),
    ("vaillant_ebus.backend.analysis_service", "analysis_service.py"),
):
    spec = importlib.util.spec_from_file_location(mod_name, BACKEND_PATH / mod_file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)

from vaillant_ebus.backend.analysis_service import AnalysisService  # noqa: E402
from vaillant_ebus.backend.discovery_service import DiscoveryService  # noqa: E402
from vaillant_ebus.backend.entity_factory import EntityDescription  # noqa: E402
from vaillant_ebus.backend.mapping import REGISTER_MAP  # noqa: E402
from vaillant_ebus.backend.models import DeviceGraph  # noqa: E402


def _graph(registers: dict[str, str]) -> DeviceGraph:
    """Build a device graph from raw register lines."""
    lines = [f"{key.replace('.', ' ')} = {value}" for key, value in registers.items()]
    return DiscoveryService.build_device_graph(lines)


def _entities(graph: DeviceGraph) -> list[EntityDescription]:
    from vaillant_ebus.backend.entity_factory import EntityFactoryService

    return EntityFactoryService().generate(graph)


class TestAnalysisService:
    def test_empty_live_registers_returns_empty(self) -> None:
        service = AnalysisService()
        result = service.analyze({}, _graph({}), [])
        assert result.new_devices == []
        assert result.new_entities == []
        assert result.registers_to_enable == []
        assert result.suggestions == []

    def test_no_change_produces_no_new_entities(self) -> None:
        graph = _graph({"hmu.Status01": "50.0;40.0;-;-;-;off"})
        entities = _entities(graph)
        service = AnalysisService()
        result = service.analyze({"hmu.Status01": "50.0;40.0;-;-;-;off"}, graph, entities)
        assert result.new_entities == []

    def test_new_register_detected_as_entity(self) -> None:
        graph = _graph({"hmu.CopHc": "4.2"})
        entities = _entities(graph)
        service = AnalysisService()
        result = service.analyze({"hmu.CopHc": "4.2", "hmu.CopHwc": "2.6"}, graph, entities)
        keys = {entity.key for entity in result.new_entities}
        assert "hmu.CopHwc.value" in keys

    def test_new_device_detected(self) -> None:
        graph = _graph({"hmu.CopHc": "4.2"})
        entities = _entities(graph)
        service = AnalysisService()
        # A new circuit (e.g. an EcoTEC boiler) with live registers.
        result = service.analyze(
            {"hmu.CopHc": "4.2", "vr_71.Mc1Operation": "standby"}, graph, entities
        )
        assert "vr_71" in result.new_devices

    def test_disabled_by_default_register_is_enable_candidate(self) -> None:
        # PowerConsumptionHmu is enabled=False in the mapping.
        disabled = next(k for k in REGISTER_MAP if not REGISTER_MAP[k].enabled)
        graph = _graph({"hmu.CopHc": "4.2"})
        entities = _entities(graph)
        service = AnalysisService()
        result = service.analyze({"hmu.CopHc": "4.2", disabled: "0.4"}, graph, entities)
        assert disabled in result.registers_to_enable

    def test_unknown_circuit_suggested(self) -> None:
        graph = _graph({"hmu.CopHc": "4.2"})
        entities = _entities(graph)
        service = AnalysisService()
        result = service.analyze({"hmu.CopHc": "4.2", "vr_71.Mc1Operation": "standby"}, graph, entities)
        assert any("vr_71" in s for s in result.suggestions)
