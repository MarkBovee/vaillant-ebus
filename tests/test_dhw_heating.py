"""Tests for the DHW heating binary sensor of heat pumps (issue #191).

The heat pump status code says whether the compressor charges the hot water cylinder. A gas boiler has no such
register, so the sensor exists only where the discovery graph lists the heat pump status.
"""

from __future__ import annotations

import sys
import tempfile
from unittest.mock import MagicMock

import pytest

from tests import test_coordinator as tc  # noqa: F401 — shared test helpers
from tests.fake_ebusd import load_find_lines
from tests.test_climate import _coordinator, _entry, _graph_two_zone

MODELS = sys.modules["vaillant_ebus.backend.models"]
DISCOVERY = sys.modules["vaillant_ebus.backend.discovery_service"]

from vaillant_ebus import binary_sensor as binary_sensor_platform  # noqa: E402
from vaillant_ebus.binary_sensor import EbusdDhwHeatingSensor  # noqa: E402

derive_dhw_heating = MODELS.derive_dhw_heating


# Intent: the hot water modes (compressor, immersion heater, pump pre- and overrun) are on; every other status is off.
# Why: the sensor shares the heat pump's operating-state logic; a blocked or switched-off hot water heater is not on.
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("hwc_compressor_active", True),
        ("hwc_immersion_heater_active", True),
        ("HWC_Compressor_Active", True),
        ("standby", False),
        ("heat_compressor_active", False),
        ("dhw_pump_prerun", True),
        ("dhw_pump_postrun", True),
        ("dhw_compressor_blocked", False),
        ("dhw_immersion_heater_off", False),
        ("defrost", False),
    ],
)
def test_derive_dhw_heating_maps_status_strings(status: str, expected: bool) -> None:
    assert derive_dhw_heating({"hmu.RunDataStatuscode.value": status}, "hmu") is expected


# Intent: a missing, sentinel or redacted status and a missing circuit stay unknown, never off.
# Why: unavailable data is not "not heating"; ebusd answers no data stored while the compressor is idle.
@pytest.mark.parametrize("raw", [None, "no data stored", "-", ""])
def test_derive_dhw_heating_is_unknown_without_a_usable_status(raw: str | None) -> None:
    values = {} if raw is None else {"hmu.RunDataStatuscode.value": raw}
    assert derive_dhw_heating(values, "hmu") is None
    assert derive_dhw_heating({"hmu.RunDataStatuscode.value": "hwc_compressor_active"}, None) is None


# Intent: the translated status labels the coordinator stores give the same answer as the raw ebusd strings.
# Why: the coordinator rewrites RunDataStatuscode through COMPRESSOR_STATUS_LABELS before it fills the data, so the live
# sensor sees "Active (DHW)", not hwc_compressor_active; feeding only raw strings missed that (audit of 1.12.1).
@pytest.mark.parametrize("raw", sorted(MODELS.COMPRESSOR_STATUS_LABELS))
def test_derive_dhw_heating_reads_the_label_the_coordinator_stores(raw: str) -> None:
    label = MODELS.COMPRESSOR_STATUS_LABELS[raw]

    assert derive_dhw_heating({"hmu.RunDataStatuscode.value": label}, "hmu") is derive_dhw_heating(
        {"hmu.RunDataStatuscode.value": raw}, "hmu"
    )
    assert derive_dhw_heating({"hmu.RunDataStatuscode.value": "Active (DHW)"}, "hmu") is True
    assert derive_dhw_heating({"hmu.RunDataStatuscode.value": "Shutdown (Heating)"}, "hmu") is False


# Intent: units that keep RunDataStatuscode at 0 during hot water demand report it through other fields.
# Why: HMU00/CTLV3 units show the 3-way valve position in Status01.pumpstate (hwc) or the Status00/Status07 bits, so
# a status of 0 alone must neither read "off" while charging nor be trusted when it is the only signal.
@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"hmu.RunDataStatuscode.value": "0", "hmu.Status01.pumpstate": "hwc"}, True),
        ({"hmu.RunDataStatuscode.value": "0", "hmu.Status00.compressorstate": "hot_water"}, True),
        ({"hmu.RunDataStatuscode.value": "0", "hmu.Status01.pumpstate": "off"}, False),
        ({"hmu.RunDataStatuscode.value": "0"}, None),
    ],
)
def test_derive_dhw_heating_uses_the_other_hot_water_signals(values: dict[str, str], expected: bool | None) -> None:
    assert derive_dhw_heating(values, "hmu") is expected


# Intent: the lookup follows the discovered heat pump circuit and ignores the status of another circuit.
# Why: discovered-circuit resolution is mandatory; a hard-coded hmu would read the wrong register on other variants.
def test_derive_dhw_heating_reads_the_given_heat_pump_circuit_only() -> None:
    values = {"hmux0.RunDataStatuscode.value": "hwc_compressor_active", "hmu.RunDataStatuscode.value": "standby"}

    assert derive_dhw_heating(values, "hmux0") is True
    assert derive_dhw_heating(values, "hmu") is False


# Intent: a flexoTHERM capture taken while the cylinder charged yields "on"; a gas boiler capture has no status.
# Why: fixture-driven proof on real captures (positive case) and a dump without any heat pump status (absent case).
def test_dhw_heating_follows_the_community_captures() -> None:
    charging = DISCOVERY.DiscoveryService.build_device_graph(
        load_find_lines("community/arotherm_basv_boost_off_discovery.yaml")
    )
    data = {
        f"{rk.split('.', 1)[0]}.{rk.split('.', 1)[1]}.{field}": value
        for rk, raw in charging.raw_registers.items()
        for field, value in tc._register_values(rk, raw).items()
        if value is not None
    }
    assert derive_dhw_heating(data, "hmu") is True

    gas_boiler = DISCOVERY.DiscoveryService.build_device_graph(
        load_find_lines("community/eloblock_ve28_discovery.yaml")
    )
    assert not any(key.endswith(".RunDataStatuscode") for key in gas_boiler.raw_registers)
    assert derive_dhw_heating({}, gas_boiler.heat_pump_result().circuit) is None


# Intent: the sensor reads the heat pump status of the coordinator data and tracks the coordinator update.
# Why: the entity is derived, so it needs a stable name, unique id, DHW device and a state that follows the data.
def test_dhw_heating_sensor_reports_the_compressor_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_two_zone(), {"ebusd": {"hmu.RunDataStatuscode.value": "standby"}})
        coordinator.last_update_success = True
        sensor = EbusdDhwHeatingSensor(coordinator, _entry())

        assert sensor._attr_name == "DHW Heating"
        assert sensor._attr_unique_id == "entry-1_dhw_heating"
        assert sensor.is_on is False
        coordinator.data["ebusd"]["hmu.RunDataStatuscode.value"] = "hwc_compressor_active"
        assert sensor.is_on is True
        coordinator.data["ebusd"]["hmu.RunDataStatuscode.value"] = "no data stored"
        assert sensor.is_on is None
        assert sensor.available is True


# Intent: setup adds the sensor on a bus with a heat pump status and adds nothing without one.
# Why: a derived entity without a backing register is a ghost; gas boilers must not get a "DHW Heating" sensor.
@pytest.mark.parametrize(("has_status", "expected"), [(True, 1), (False, 0)])
async def test_setup_adds_the_dhw_heating_sensor_only_with_a_heat_pump_status(has_status: bool, expected: int) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = _graph_two_zone()
        if not has_status:
            graph.raw_registers.pop("hmu.RunDataStatuscode")
        coordinator = _coordinator(tmpdir, graph, {"ebusd": {}})
        coordinator._graph.nodes = coordinator._graph.nodes or {"x": MagicMock()}
        hass = MagicMock()
        hass.data = {"vaillant_ebus": {"entry-1": coordinator}}
        added: list = []
        await binary_sensor_platform.async_setup_entry(hass, _entry(), lambda entities: added.extend(entities))

        assert sum(isinstance(entity, EbusdDhwHeatingSensor) for entity in added) == expected
