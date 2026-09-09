"""Regression coverage for the latest community captures from issues #99/#103."""

from __future__ import annotations

import pytest

from tests.fake_ebusd import load_discovery_dump, load_find_lines
from tests.test_entity_factory import DiscoveryService, EntityFactoryService


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


def test_hmux0_dhw_holiday_capture_keeps_controller_values_and_sentinels_unavailable() -> None:
    dump = load_discovery_dump("community/arotherm_hmux0_dhw_holiday_discovery.yaml")
    graph = DiscoveryService.build_device_graph(load_find_lines("community/arotherm_hmux0_dhw_holiday_discovery.yaml"))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert dump["raw_find_lines"]
    assert graph.raw_registers["ctlv3.HwcHolidayStartPeriod"] == "01.01.2015"
    assert graph.raw_registers["ctlv3.HwcHolidayEndPeriod"] == "01.01.2015"
    assert graph.raw_registers["ctlv3.PrEnergySumHwc"] == "327"
    assert "ctlv3.PrEnergySumHwc.value" in entities


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
