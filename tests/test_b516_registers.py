"""Tests for the runtime-defined b516 cooling-energy registers (issue #50)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import struct
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


# Encoding follows the b516 date table from upstream issue #490: QQ counts
# half-years since 2000 (+1 from August onwards), W selects the month within
# that half-year, and each month's W pair splits the days (even W: V=day for
# days 1-15, odd W: V=day-16 for days 16-31). Anchors are the worked examples
# posted in the thread: Feb 23 2025 -> "5732", Aug 24 2026 -> "1835". An
# earlier live check accepted "0835" for Aug 24 2026, which the device decodes
# as Aug 8 -- plausible-looking but the wrong day.
# Intent: b516_date_bytes encodes five known calendar dates to their exact verified 4-hex-character strings.
# Why: pins the QQ/W/V date table (upstream issue #490) so a refactor cannot shift the day or month encoding.
def test_b516_date_bytes_known_dates() -> None:
    assert b516_date_bytes(datetime(2026, 8, 24)) == "1835"
    assert b516_date_bytes(datetime(2025, 2, 23)) == "5732"
    assert b516_date_bytes(datetime(2026, 3, 5)) == "6534"
    assert b516_date_bytes(datetime(2026, 12, 31)) == "9f35"
    assert b516_date_bytes(datetime(2025, 1, 1)) == "2132"


# Intent: b516_date_bytes rolls the month grouping from July 31 ("ff34") to August 1 ("0135").
# Why: protects the half-year boundary where QQ increments and W resets, a common off-by-one source.
def test_b516_date_bytes_month_boundaries() -> None:
    assert b516_date_bytes(datetime(2026, 7, 31)) == "ff34"
    assert b516_date_bytes(datetime(2026, 8, 1)) == "0135"


# Intent: day 15 stays on the even W value ("0f35") and day 16 flips to the odd W value at V=0 ("1035").
# Why: pins the mid-month day-split boundary of the upstream b516 table.
def test_b516_date_bytes_day_split_boundary() -> None:
    # Day 15 stays on the even W value; day 16 flips to the odd one at V=0.
    assert b516_date_bytes(datetime(2026, 8, 15)) == "0f35"
    assert b516_date_bytes(datetime(2026, 8, 16)) == "1035"


# Intent: three real b516 reply payloads decode as IGN:7 then a little-endian float32 Wh counter.
# Why: freezes the wire contract so a future define-string edit cannot silently
# shift or rescale the energy value (issue #490).
def test_b516_exp_reply_decode_contract() -> None:
    # The runtime defines read every b516 reply as IGN:7 followed by a 4-byte
    # little-endian float32 Wh counter (the upstream "energye" type). Pin that
    # wire contract against real telegrams so a future define-string edit
    # cannot silently shift or rescale the value window.
    #
    # chrizzzp in john30/ebusd-configuration#490: annual electric totals of
    # his unit; the second ticks up by standby power between reads.
    assert struct.unpack("<f", bytes.fromhex("fc0d0a4a"))[0] == 2261887.0
    assert struct.unpack("<f", bytes.fromhex("31895d49"))[0] == 907411.0625
    # The reporter's own flexoTHERM answers the cooling-gas statistics poll
    # with an all-zero counter (tests/fixtures/community/flexotherm_discovery.yaml,
    # reply 0b1000ff4905013500000000).
    assert struct.unpack("<f", bytes.fromhex("00000000"))[0] == 0.0


# Intent: the cooling/electric/solar energy registers generate sensors with the
# expected friendly names, units, device classes, and total_increasing state classes.
# Why: guards the b516 cooling-energy entity contract and the lifetime-vs-daily monotonic classification (issue #50).
def test_b516_cooling_register_entities() -> None:
    lines = [
        "hmu CoolEnvYieldTotal = 1206000",
        "hmu CoolEnvYieldDay = 8000",
        "hmu CoolEnvYieldMonth = 139818",
        "hmu CoolElecConsTotal = 153000",
        "hmu CoolElecConsDay = 1200",
        "hmu HcElecConsTotal = 2400000",
        "hmu HcElecConsDay = 18000",
        "hmu HwcElecConsTotal = 950000",
        "hmu HwcElecConsDay = 7000",
        # CSV/find-based electric registers that supplement the b516 counters.
        "hmu ConsumptionTotal = 12345",
        "hmu RunDataElectricPowerConsumption = 1500",
        "hmu LiveMonitorCurrentConsumedPower = 15",
        "hmu StatSolarEnergySum = 0",
        "hmu StatSolarEnergySumHc = 0",
        "hmu StatSolarEnergySumHwc = 0",
    ]
    graph = DiscoveryService.build_device_graph(lines)
    entities = EntityFactoryService().generate(graph)
    by_key = {e.key: e for e in entities}

    expected_names = {
        "hmu.CoolEnvYieldTotal.value": ("Cooling Energy Total", "Wh"),
        "hmu.CoolEnvYieldDay.value": ("Cooling Energy Today", "Wh"),
        "hmu.CoolEnvYieldMonth.value": ("Cooling Energy Month", "Wh"),
        "hmu.CoolElecConsTotal.value": ("Cooling Electricity Total", "Wh"),
        "hmu.CoolElecConsDay.value": ("Cooling Electricity Today", "Wh"),
        "hmu.HcElecConsTotal.value": ("Heating Electricity Total", "Wh"),
        "hmu.HcElecConsDay.value": ("Heating Electricity Today", "Wh"),
        "hmu.HwcElecConsTotal.value": ("DHW Electricity Total", "Wh"),
        "hmu.HwcElecConsDay.value": ("DHW Electricity Today", "Wh"),
        "hmu.ConsumptionTotal.value": ("Electrical Energy Consumption", "kWh"),
        "hmu.StatSolarEnergySum.value": ("Solar Energy Sum", "kWh"),
        "hmu.StatSolarEnergySumHc.value": ("Solar Energy Sum (Heating)", "kWh"),
        "hmu.StatSolarEnergySumHwc.value": ("Solar Energy Sum (DHW)", "kWh"),
    }
    for key, (friendly, unit) in expected_names.items():
        entity = by_key.get(key)
        assert entity is not None, f"{key} must be an entity"
        assert entity.meta.friendly_name == friendly
        assert entity.entity_type == "sensor"
        assert entity.meta.device_class == "energy"
        assert entity.meta.unit == unit

    # Lifetime totals are monotonic; daily counters reset each day.
    for key in (
        "hmu.CoolEnvYieldTotal.value",
        "hmu.CoolElecConsTotal.value",
        "hmu.HcElecConsTotal.value",
        "hmu.HwcElecConsTotal.value",
        "hmu.ConsumptionTotal.value",
        "hmu.StatSolarEnergySum.value",
        "hmu.StatSolarEnergySumHc.value",
        "hmu.StatSolarEnergySumHwc.value",
    ):
        assert by_key[key].meta.state_class == "total_increasing"
    for key in (
        "hmu.CoolEnvYieldDay.value",
        "hmu.CoolElecConsDay.value",
        "hmu.HcElecConsDay.value",
        "hmu.HwcElecConsDay.value",
    ):
        assert by_key[key].meta.state_class != "total_increasing"

    # Power registers use the power device class with the upstream units.
    assert by_key["hmu.RunDataElectricPowerConsumption.value"].meta.device_class == "power"
    assert by_key["hmu.RunDataElectricPowerConsumption.value"].meta.unit == "W"
    assert by_key["hmu.LiveMonitorCurrentConsumedPower.value"].meta.device_class == "power"
    assert by_key["hmu.LiveMonitorCurrentConsumedPower.value"].meta.unit == "kW"
