"""Tests for the GeniaSet BASS3 community fixture."""

from __future__ import annotations

import sys

from tests import _component_loader  # noqa: F401 — loads the shared modules once
from tests.fake_ebusd import load_find_lines

MODELS = sys.modules["vaillant_ebus.backend.models"]
EBUS_MOD = sys.modules["vaillant_ebus.backend.ebus_service"]
DISCOVERY = sys.modules["vaillant_ebus.backend.discovery_service"]
MAPPING = sys.modules["vaillant_ebus.backend.mapping"]
ENTITY = sys.modules["vaillant_ebus.backend.entity_factory"]

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
