"""Regression coverage for the latest community captures from issues #99/#103."""

from __future__ import annotations

from tests.fake_ebusd import load_find_lines
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
