"""Tests for the GeniaSet BASS3 community fixture."""

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

EBUS_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.ebus_service", BACKEND_PATH / "ebus_service.py"
)
assert EBUS_SPEC and EBUS_SPEC.loader
EBUS_MOD = importlib.util.module_from_spec(EBUS_SPEC)
sys.modules["vaillant_ebus.backend.ebus_service"] = EBUS_MOD
EBUS_SPEC.loader.exec_module(EBUS_MOD)

DISCOVERY_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.discovery_service", BACKEND_PATH / "discovery_service.py"
)
assert DISCOVERY_SPEC and DISCOVERY_SPEC.loader
DISCOVERY = importlib.util.module_from_spec(DISCOVERY_SPEC)
sys.modules["vaillant_ebus.backend.discovery_service"] = DISCOVERY
DISCOVERY_SPEC.loader.exec_module(DISCOVERY)

MAPPING_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.mapping", BACKEND_PATH / "mapping.py"
)
assert MAPPING_SPEC and MAPPING_SPEC.loader
MAPPING = importlib.util.module_from_spec(MAPPING_SPEC)
sys.modules["vaillant_ebus.backend.mapping"] = MAPPING
MAPPING_SPEC.loader.exec_module(MAPPING)

ENTITY_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.entity_factory", BACKEND_PATH / "entity_factory.py"
)
assert ENTITY_SPEC and ENTITY_SPEC.loader
ENTITY = importlib.util.module_from_spec(ENTITY_SPEC)
sys.modules["vaillant_ebus.backend.entity_factory"] = ENTITY
ENTITY_SPEC.loader.exec_module(ENTITY)

DiscoveryService = DISCOVERY.DiscoveryService
DeviceType = DISCOVERY.DeviceType

GENIASET_LINES = load_find_lines("community/geniaset_bass3_discovery.yaml")


# Intent: the GeniaSet fixture builds a graph where bass is a data-bearing
# HEATING_CONTROLLER with scan_type BASS3 and hmu is a HEAT_PUMP.
# Why: validates discovery classification for the BASS3 community fixture.
def test_geniaset_bass3_graph() -> None:
    graph = DiscoveryService.build_device_graph(GENIASET_LINES)
    assert graph.nodes["bass"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["bass"].scan_type == "BASS3"
    assert graph.nodes["bass"].has_data is True
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP


# Intent: the bass Hwc operation, storage, and desired registers all appear in the graph's raw_registers.
# Why: ensures the DHW control registers captured on the BASS3 bus are discovered.
def test_geniaset_bass3_dhw_registers_discovered() -> None:
    graph = DiscoveryService.build_device_graph(GENIASET_LINES)
    for key in ("bass.HwcOpMode", "bass.HwcStorageTemp", "bass.HwcTempDesired"):
        assert key in graph.raw_registers, f"missing {key}"


# bass/dhw (live Hwc registers) and hmu/dhw (no data) both map to the logical
# "dhw" device name; the merge must keep the live bass registers as entities
# so water_heater gets a current temperature (GitHub issue #79).
# Intent: after bass/dhw and hmu/dhw merge into one logical dhw device, the live
# bass HwcStorageTemp/HwcTempDesired/HwcOpMode registers still generate entities.
# Why: protects the water_heater current temperature for the GeniaSet system (GitHub issue #79).
def test_geniaset_bass3_dhw_entities_survive_sub_device_merge() -> None:
    graph = DiscoveryService.build_device_graph(GENIASET_LINES)
    dhw = graph.nodes["dhw"]
    assert dhw.has_data is True
    assert "bass.HwcStorageTemp" in dhw.registers

    by_key = {e.key: e for e in ENTITY.EntityFactoryService().generate(graph)}
    for reg in (
        "bass.HwcStorageTemp.value",
        "bass.HwcTempDesired.value",
        "bass.HwcOpMode.value",
    ):
        assert reg in by_key, f"live DHW register must be an entity: {reg}"
