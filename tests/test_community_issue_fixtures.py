"""Regression coverage for the latest community captures from issues #99/#103."""

from __future__ import annotations

import pytest

from tests.fake_ebusd import load_discovery_dump, load_find_lines
from tests.test_entity_factory import DiscoveryService, EntityFactoryService


# Intent: the eloblock VE28 fixture exposes observed bai registers with metadata.
# Why: community boiler captures must produce typed, correctly-labeled entities.
def test_eloblock_ve28_exposes_observed_bai_registers() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/eloblock_ve28_discovery.yaml"))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert graph.nodes["bai"].device_type.name == "HEATING_CONTROLLER"
    for register in ("FlowTemp", "FlowTempDesired", "StorageTemp", "StorageTempDesired", "WaterPressure"):
        assert f"bai.{register}.value" in entities

    assert entities["bai.FlowTemp.value"].meta.device_class == "temperature"
    assert entities["bai.FlowTemp.value"].meta.unit == "°C"
    assert entities["bai.WaterPressure.value"].meta.device_class == "pressure"
    assert entities["bai.WaterPressure.value"].meta.unit == "bar"
    assert entities["bai.Status01.temp"].meta.device_class == "temperature"
    assert entities["bai.Status01.temp_1"].meta.device_class == "temperature"
    assert entities["bai.Gasvalve.value"].enabled_by_default is False
    assert entities["bai.FanSpeed.value"].enabled_by_default is False
    assert entities["bai.Flame.value"].enabled_by_default is False


# Intent: the latest issue #99 HMUX0 values keep entity metadata and raw values.
# Why: issue #99 - HMUX0 telemetry entities must stay available and typed.
def test_hmux0_latest_issue99_values_keep_entity_metadata() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/hmux0_issue99_latest_find.txt"))
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
        assert f"hmux0.{register}.value" in entities

    assert entities["hmux0.RunDataReturnTemp.value"].raw_value == "28.2184"
    assert entities["hmux0.RunDataReturnTemp.value"].meta.device_class == "temperature"
    assert entities["hmux0.YieldHc.value"].meta.device_class == "energy"
    assert entities["hmux0.Status01.temp"].meta.device_class == "temperature"


# Intent: issue #99 dumps keep ctlv3 DHW values and reject invalid HMUX0 return temperature.
# Why: issue #99 - spurious hmux0 readings must not overwrite valid controller data.
@pytest.mark.parametrize(
    ("fixture", "invalid_return_temperature"),
    (
        ("community/hmux0_issue99_2026-09-10_170850.yaml", "1082.88"),
        ("community/hmux0_issue99_2026-09-10_173229.yaml", "-423.75"),
    ),
)
def test_latest_issue99_dumps_keep_ctlv3_dhw_and_reject_invalid_hmux0_temperature(
    fixture: str, invalid_return_temperature: str
) -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert graph.nodes["hmux0"].device_type.name == "HEAT_PUMP"
    assert graph.nodes["ctlv3"].device_type.name == "HEATING_CONTROLLER"
    assert graph.raw_registers["ctlv3.HwcOpMode"] == "auto"
    assert graph.raw_registers["ctlv3.HwcSFMode"] == "auto"
    assert graph.raw_registers["ctlv3.HwcStorageTemp"] == "45"
    assert graph.raw_registers["ctlv3.HwcTempDesired"] == "48"
    assert graph.raw_registers["ctlv3.HwcHolidayStartPeriod"] == "01.01.2015"
    assert graph.raw_registers["ctlv3.HwcHolidayEndPeriod"] == "01.01.2015"
    assert "hmux0.RunDataReturnTemp" not in graph.raw_registers
    assert "hmux0.RunDataReturnTemp" in graph.placeholder_registers
    assert entities["hmux0.RunDataReturnTemp.value"].raw_value == ""
    assert entities["hmux0.RunDataReturnTemp.value"].raw_value != invalid_return_temperature

    for register in ("YieldHc", "YieldHwc", "CopHc", "CopHwc"):
        assert graph.raw_registers[f"hmux0.{register}"]


# Intent: Pro7 quiet-mode captures load but expose no NoiseReduction/DeicingActive entities.
# Why: absent quiet registers must not be fabricated from captures.
@pytest.mark.parametrize(
    "fixture",
    (
        "community/arotherm_pro7_quiet_off_idle_discovery.yaml",
        "community/arotherm_pro7_quiet_off_heating_discovery.yaml",
        "community/arotherm_pro7_quiet_on_heating_discovery.yaml",
    ),
)
def test_arotherm_pro7_quiet_captures_load_without_quiet_registers(fixture: str) -> None:
    dump = load_discovery_dump(fixture)
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture))
    names = {f"{node.circuit}.{register}" for node in graph.nodes.values() for register in node.registers}

    assert dump["raw_find_lines"]
    assert any("scan.08" in line for line in dump["raw_find_lines"])
    assert graph.nodes["hmu"].device_type.name == "HEAT_PUMP"
    assert not any("NoiseReduction" in name or "DeicingActive" in name for name in names)


# Intent: the HMUX0 DHW holiday capture keeps ctlv3 values and treats invalid HMUX0 telemetry as placeholder.
# Why: issues #99/#103 - controller values and sentinel handling must survive the capture.
def test_hmux0_dhw_holiday_capture_keeps_controller_values_and_sentinels_unavailable() -> None:
    dump = load_discovery_dump("community/arotherm_hmux0_dhw_holiday_discovery.yaml")
    graph = DiscoveryService.build_device_graph(load_find_lines("community/arotherm_hmux0_dhw_holiday_discovery.yaml"))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert dump["raw_find_lines"]
    assert graph.nodes["hmux0"].device_type.name == "HEAT_PUMP"
    assert graph.nodes["ctlv3"].device_type.name == "HEATING_CONTROLLER"

    # DHW and controller values are on ctlv3
    assert graph.raw_registers["ctlv3.HwcStorageTemp"] == "42"
    assert graph.raw_registers["ctlv3.HwcTempDesired"] == "50"
    assert graph.raw_registers["ctlv3.HwcOpMode"] == "auto"
    assert graph.raw_registers["ctlv3.HwcSFMode"] == "auto"
    assert graph.raw_registers["ctlv3.HwcHolidayStartPeriod"] == "01.01.2015"
    assert graph.raw_registers["ctlv3.HwcHolidayEndPeriod"] == "01.01.2015"
    assert graph.raw_registers["ctlv3.PrEnergySumHwc"] == "327"

    assert "ctlv3.HwcStorageTemp.value" in entities
    assert entities["ctlv3.HwcStorageTemp.value"].meta.device_class == "temperature"
    assert entities["ctlv3.HwcStorageTemp.value"].meta.unit == "°C"
    assert "ctlv3.HwcTempDesired.value" in entities
    assert "ctlv3.HwcOpMode.value" in entities
    assert "ctlv3.PrEnergySumHwc.value" in entities

    # HMUX0 heat pump telemetry
    assert "hmux0.CopHc.value" in entities
    assert "hmux0.CopHwc.value" in entities
    assert "hmux0.BuildingCircuitFlow.value" in entities

    # Invalid position registers in discovery must have no data and be classified as placeholder
    assert "hmux0.ConsumptionTotal" in graph.placeholder_registers
    assert "hmux0.ConsumptionTotal" not in graph.raw_registers


# Intent: future Z1 holiday dates survive discovery as ctlv3 values.
# Why: holiday scheduling must not be lost or defaulted to a sentinel.
def test_hmux0_holiday_capture_keeps_future_zone_holiday_values() -> None:
    """Controller holiday dates must survive discovery as ctlv3 values."""
    dump = load_discovery_dump("community/arotherm_hmux0_dhw_holiday_discovery.yaml")
    graph = DiscoveryService.build_device_graph(load_find_lines("community/arotherm_hmux0_dhw_holiday_discovery.yaml"))

    assert dump["metadata"]["dump_version"] == 3
    assert graph.raw_registers["ctlv3.Z1HolidayStartPeriod"] == "26.09.2026"
    assert graph.raw_registers["ctlv3.Z1HolidayEndPeriod"] == "09.10.2027"


# Intent: ecoTEC VRT380 captures expose bai entities and a controller graph.
# Why: boiler hardware must be discoverable with its observed register set.
@pytest.mark.parametrize(
    "fixture",
    (
        "community/ecotec_vrt380_15700_discovery.yaml",
        "community/ecotec_vrt380_ctlv2_discovery.yaml",
    ),
)
def test_ecotec_vrt380_captures_expose_bai_and_controller_graph(fixture: str) -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert graph.nodes["bai"].device_type.name == "HEATING_CONTROLLER"
    assert "bai.FlowTemp.value" in entities
    assert "bai.StorageTemp.value" in entities
