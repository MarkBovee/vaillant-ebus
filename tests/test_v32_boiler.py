"""Tests for the v32 gas-boiler community fixture (GitHub issue #83).

The fixture captures a hybrid system: heat pump (HMU00) plus an ecoTEC plus gas
boiler exposed on the v32 circuit through a VR32 interface board (CSV
08.bai.csv copied as 18.v32.csv). These tests pin the boiler register behavior:
metadata, multi-field splitting, sensor-fault filtering, and the absence of
ventilation-only registers.
"""

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
DeviceType = DISCOVERY.DeviceType

V32_BOILER_LINES = load_find_lines("community/v32_boiler_discovery.yaml")

# Ventilation-only registers from the bai CSV that must never become entities
# on this boiler setup (they return ERR: element not found).
VENTILATION_ONLY_REGISTERS = (
    "BypassPosition",
    "ExhaustAirHumidity",
    "ExhaustAirTemp",
    "MaxAirHumidity",
    "MinAirHumidity",
    "OutsideAirTemp",
    "SupplyAirTemp",
    "VentilationLevelDay",
    "VentilationLevelNight",
    "YieldMonth",
    "YieldToday",
    "YieldTotal",
    "YieldYear",
)


def _graph():
    return DiscoveryService.build_device_graph(V32_BOILER_LINES)


def _v32_entities():
    return [e for e in ENTITY.EntityFactoryService().generate(_graph()) if e.circuit == "v32"]


def test_v32_boiler_graph() -> None:
    graph = _graph()
    node = graph.nodes["v32"]
    assert node.has_data is True
    assert "v32.FlowTemp" in graph.raw_registers
    assert "v32.ReturnTemp" in graph.raw_registers
    assert "v32.WaterPressure" in graph.raw_registers
    # The boiler registers surface as a DHW sub-device of v32.
    assert "v32.HwcHours" in graph.nodes["dhw"].registers


# Category 1 from issue #83: sensors missing device_class/unit.
def test_v32_boiler_temperature_metadata() -> None:
    by_key = {e.key: e for e in _v32_entities()}
    for key in (
        "v32.ReturnTemp.value",
        "v32.StorageTemp.value",
        "v32.StorageTempDesired.value",
        "v32.FlowTempDesired.value",
        "v32.FlowTempMax.value",
        "v32.ReturnTempMax.value",
    ):
        meta = by_key[key].meta
        assert meta.device_class == "temperature", key
        assert meta.unit == "°C", key


def test_v32_boiler_duration_metadata() -> None:
    by_key = {e.key: e for e in _v32_entities()}
    for key, state_class in (
        ("v32.FanHours.value", "total_increasing"),
        ("v32.HcHours.value", "total_increasing"),
        ("v32.HwcHours.value", "total_increasing"),
        ("v32.PumpHours.value", "total_increasing"),
        ("v32.StorageLoadPumpHours.value", "total_increasing"),
        ("v32.HoursTillService.value", ""),
    ):
        meta = by_key[key].meta
        assert meta.device_class == "duration", key
        assert meta.unit == "h", key
        assert meta.state_class == state_class, key


def test_v32_boiler_pump_power_and_pressure() -> None:
    by_key = {e.key: e for e in _v32_entities()}
    pump = by_key["v32.PumpPower.value"]
    assert pump.entity_type == "sensor", "PumpPower must not be a binary_sensor"
    assert pump.meta.device_class == "power"
    assert pump.meta.unit == "W"

    pressure = by_key["v32.WaterPressure.value"]
    assert pressure.meta.device_class == "pressure"
    assert pressure.meta.unit == "bar"


# Category 2 from issue #83: semicolon-separated values must be split.
def test_v32_boiler_multi_field_split() -> None:
    split = MAPPING.split_multi_field
    assert split("v32.ReturnTemp", "55.31;64650;ok")["value"] == "55.31"
    assert split("v32.FlowTemp", "47.06;ok")["value"] == "47.06"
    assert split("v32.StorageTemp", "62.25;ok")["value"] == "62.25"
    assert split("v32.WaterPressure", "1.771;ok")["value"] == "1.771"
    status01 = split("v32.Status01", "43.5;53.5;-;-;62.0;off")
    assert status01 == {
        "value": "43.5;53.5;-;-;62.0;off",
        "temp": "43.5",
        "temp_1": "53.5",
        "temp_2": "-",
        "temp_3": "-",
        "temp_4": "62.0",
        "pumpstate": "off",
    }
    status02 = split("v32.Status02", "auto;60;68.0;70;70.0")
    assert status02 == {
        "value": "auto;60;68.0;70;70.0",
        "hwcmode": "auto",
        "temp0": "60",
        "temp1": "68.0",
        "temp0_1": "70",
        "temp1_1": "70.0",
    }


def test_v32_boiler_status_entities() -> None:
    entities = _v32_entities()
    by_key = {e.key: e for e in entities}
    # Status01 fields reuse the hmu Status01 metadata via the circuit alias.
    # Field entities are keyed without a ".value" suffix.
    assert by_key["v32.Status01.temp"].meta.device_class == "temperature"
    assert by_key["v32.Status01.temp_1"].meta.device_class == "temperature"
    assert by_key["v32.Status01.pumpstate"].entity_type == "binary_sensor"
    # Single-field mappings must not create a duplicate base "value" entity.
    assert sum(1 for e in entities if e.key == "v32.FlowTemp.value") == 1
    assert sum(1 for e in entities if e.key == "v32.ReturnTemp.value") == 1
    assert by_key["v32.FlowTemp.value"].raw_value == "47.06;ok"
    assert by_key["v32.ReturnTemp.value"].raw_value == "55.31;64650;ok"


# Category 3 from issue #83: ventilation-only registers must not appear.
def test_v32_boiler_ventilation_registers_absent() -> None:
    names = {e.name for e in _v32_entities()}
    for name in VENTILATION_ONLY_REGISTERS:
        assert name not in names, f"ventilation-only register {name} must not be an entity"


# Category 4 from issue #83: faulty-sensor values must carry no data.
def test_v32_boiler_faulty_sensor_values_no_data() -> None:
    graph = _graph()
    # Sensor-fault statuses ("circuit"/"cutoff") are parsed as no-data.
    assert "v32.HwcTemp" not in graph.raw_registers
    assert "v32.OutdoorstempSensor" not in graph.raw_registers
    assert DiscoveryService._parse_register("v32 HwcTemp = 116.06;circuit")[2] is None
    assert DiscoveryService._parse_register("v32 OutdoorstempSensor = -60.44;cutoff")[2] is None

    by_key = {e.key: e for e in _v32_entities()}
    # The faulty-sensor entities exist but stay disabled by default.
    assert by_key["v32.HwcTemp.value"].enabled_by_default is False
    assert by_key["v32.OutdoorstempSensor.value"].enabled_by_default is False
    # The maintenance max of the same faulty sensor is diagnostic + disabled.
    maint = by_key["v32.Maintenancedata_HwcTempMax.value"]
    assert maint.enabled_by_default is False
    assert maint.meta.entity_category == "diagnostic"


# The healthy sibling values keep working after the fault filtering.
def test_v32_boiler_valid_values_stay_live() -> None:
    graph = _graph()
    assert graph.raw_registers["v32.ReturnTemp"] == "55.31;64650;ok"
    assert graph.raw_registers["v32.FlowTemp"] == "47.06;ok"
    assert graph.raw_registers["v32.WaterPressure"] == "1.771;ok"
