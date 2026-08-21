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

DiscoveryService = DISCOVERY.DiscoveryService
DeviceType = DISCOVERY.DeviceType

GENIASET_LINES = load_find_lines("community/geniaset_bass3_discovery.yaml")


def test_geniaset_bass3_graph() -> None:
    graph = DiscoveryService.build_device_graph(GENIASET_LINES)
    assert graph.nodes["bass"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["bass"].scan_type == "BASS3"
    assert graph.nodes["bass"].has_data is True
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP


def test_geniaset_bass3_dhw_registers_discovered() -> None:
    graph = DiscoveryService.build_device_graph(GENIASET_LINES)
    for key in ("bass.HwcOpMode", "bass.HwcStorageTemp", "bass.HwcTempDesired"):
        assert key in graph.raw_registers, f"missing {key}"
