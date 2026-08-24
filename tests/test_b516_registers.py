"""Tests for the runtime-defined b516 cooling-energy registers (issue #50)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

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

DISCOVERY_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.discovery_service", BACKEND_PATH / "discovery_service.py"
)
assert DISCOVERY_SPEC and DISCOVERY_SPEC.loader
DISCOVERY = importlib.util.module_from_spec(DISCOVERY_SPEC)
sys.modules["vaillant_ebus.backend.discovery_service"] = DISCOVERY
DISCOVERY_SPEC.loader.exec_module(DISCOVERY)

b516_date_bytes = MAPPING.b516_date_bytes
DiscoveryService = DISCOVERY.DiscoveryService
EntityFactoryService = ENTITY.EntityFactoryService


# The encoding was verified live on 2026-08-24: the HMU accepted payload
# suffix 0835 and returned a plausible August cooling yield.
def test_b516_date_bytes_known_dates() -> None:
    assert b516_date_bytes(datetime(2026, 8, 24)) == "0835"
    assert b516_date_bytes(datetime(2026, 3, 5)) == "6534"
    assert b516_date_bytes(datetime(2026, 12, 31)) == "8f35"
    assert b516_date_bytes(datetime(2025, 1, 1)) == "2132"


def test_b516_date_bytes_month_boundaries() -> None:
    assert b516_date_bytes(datetime(2026, 7, 31)) == "ef34"
    assert b516_date_bytes(datetime(2026, 8, 1)) == "0135"


def test_b516_cooling_register_entities() -> None:
    lines = [
        "hmu CoolEnvYieldTotal = 1206000",
        "hmu CoolEnvYieldDay = 8000",
        "hmu CoolEnvYieldMonth = 139818",
        "hmu CoolElecConsTotal = 153000",
    ]
    graph = DiscoveryService.build_device_graph(lines)
    entities = EntityFactoryService().generate(graph)
    by_key = {e.key: e for e in entities}

    expected_names = {
        "hmu.CoolEnvYieldTotal.value": "Cooling Energy Total",
        "hmu.CoolEnvYieldDay.value": "Cooling Energy Today",
        "hmu.CoolEnvYieldMonth.value": "Cooling Energy Month",
        "hmu.CoolElecConsTotal.value": "Cooling Electricity Total",
    }
    for key, friendly in expected_names.items():
        entity = by_key.get(key)
        assert entity is not None, f"{key} must be an entity"
        assert entity.meta.friendly_name == friendly
        assert entity.entity_type == "sensor"
        assert entity.meta.device_class == "energy"
        assert entity.meta.unit == "Wh"

    assert by_key["hmu.CoolEnvYieldTotal.value"].meta.state_class == "total_increasing"
    assert by_key["hmu.CoolElecConsTotal.value"].meta.state_class == "total_increasing"
    # Daily/monthly yields reset, so they must not be marked total_increasing.
    assert by_key["hmu.CoolEnvYieldDay.value"].meta.state_class != "total_increasing"
