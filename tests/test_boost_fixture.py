"""Tests for the aroTHERM BASV2 boost-mode community fixtures (discussion #31).

MichaelLachmann captured two discovery dumps around a DHW boost toggle: the
first with boost on (11:16:49), the second with boost off (11:18:07). Both
dumps show ``basv HwcSFMode = load`` while the compressor is actively heating
the cylinder toward 68 C. These tests pin that capture so the write-verification
fix (a read-back that does not match the written value must fail) has a
real-bus fixture behind it, and so the boost registers are discoverable with
data.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

from tests.fake_ebusd import load_discovery_dump, load_find_lines

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

DiscoveryService = DISCOVERY.DiscoveryService
EntityFactoryService = ENTITY.EntityFactoryService

BOOST_ON_DUMP = "community/arotherm_basv_boost_on_discovery.yaml"
BOOST_OFF_DUMP = "community/arotherm_basv_boost_off_discovery.yaml"


def _find_value(lines: list[str], circuit: str, name: str) -> str | None:
    """Return the first live value for circuit.name in raw find lines."""
    for line in lines:
        if "=" not in line:
            continue
        lhs, rhs = line.split("=", 1)
        parts = lhs.strip().split(" ", 1)
        if len(parts) != 2 or parts[0] != circuit or parts[1] != name:
            continue
        val = rhs.strip()
        if val and val != "no data stored" and not val.startswith("(ERR"):
            return val
    return None


# Intent: both boost discovery dumps load with raw lines, before registers, and >500 registers.
# Why: fixture integrity is required before boost behavior can be asserted.
def test_boost_fixtures_load() -> None:
    for dump in (BOOST_ON_DUMP, BOOST_OFF_DUMP):
        data = load_discovery_dump(dump)
        assert data.get("raw_find_lines")
        assert data.get("before_registers")
        assert data.get("metadata", {}).get("register_count") > 500


# Intent: both boost dumps report basv HwcSFMode=load with a 46->68 C cylinder charge.
# Why: discussion #31 - HwcSFMode lags the boost toggle during charging.
def test_boost_on_dump_shows_sfmode_load() -> None:
    # The whole point of the capture: even with boost "off" (second dump), the
    # register still reads load while the compressor runs the cylinder up.
    for dump in (BOOST_ON_DUMP, BOOST_OFF_DUMP):
        lines = load_find_lines(dump)
        assert _find_value(lines, "basv", "HwcSFMode") == "load", dump
        assert _find_value(lines, "basv", "HwcStorageTemp") == "46", dump
        assert _find_value(lines, "basv", "HwcTempDesired") == "68", dump


# Intent: the boost-on dump generates basv DHW entities with correct metadata.
# Why: discussion #31 - boost registers must be discoverable and typed.
def test_boost_fixture_entities() -> None:
    lines = load_find_lines(BOOST_ON_DUMP)
    graph = DiscoveryService.build_device_graph(lines)
    entities = EntityFactoryService().generate(graph)
    by_key = {e.key: e for e in entities}

    # The boost-relevant registers must generate entities with live data on
    # the basv circuit (heating controller for this hardware).
    for key in (
        "basv.HwcSFMode.value",
        "basv.HwcOpMode.value",
        "basv.HwcStorageTemp.value",
        "basv.HwcTempDesired.value",
    ):
        entity = by_key.get(key)
        assert entity is not None, f"{key} must be an entity"

    assert by_key["basv.HwcStorageTemp.value"].meta.device_class == "temperature"
    assert by_key["basv.HwcSFMode.value"].meta.friendly_name == "DHW Special Function"
