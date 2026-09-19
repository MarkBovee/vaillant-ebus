"""Tests for the datetime platform write contract.

The holiday datetime entities are hand-built (not generated from the discovery
graph), so nothing else pins that they address the resolved controller circuit
with the right register and date serialization. These tests do exactly that,
using a real discovery graph so the circuit resolution is exercised too.

Reuses the homeassistant mock scaffolding from tests.test_coordinator.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests import test_coordinator as tc  # noqa: F401 — installs shared HA mocks
from tests.fake_ebusd import load_find_lines

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"

mock_homeassistant = sys.modules["homeassistant"]

_TZ = timezone(timedelta(hours=2))


class _MockBaseEntity:
    def async_write_ha_state(self) -> None:
        pass

    def _handle_coordinator_update(self) -> None:
        pass

    async def async_update(self) -> None:
        pass

    def __class_getitem__(cls, item):
        return cls


class _MockCoordinatorEntity(_MockBaseEntity):
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator


datetime_pkg = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.components.datetime", None)
)
datetime_pkg.DateTimeEntity = _MockBaseEntity
sys.modules["homeassistant.components.datetime"] = datetime_pkg
mock_homeassistant.helpers.update_coordinator.CoordinatorEntity = _MockCoordinatorEntity

ha_util = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("homeassistant.util", None))
ha_util.dt = MagicMock()
ha_util.dt.DEFAULT_TIME_ZONE = _TZ
sys.modules["homeassistant.util"] = ha_util
mock_homeassistant.util = ha_util

entity_platform = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.helpers.entity_platform", None)
)
entity_platform.AddEntitiesCallback = object
sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

DATETIME_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.datetime", COMPONENT_PATH / "datetime.py")
assert DATETIME_SPEC and DATETIME_SPEC.loader
DATETIME = importlib.util.module_from_spec(DATETIME_SPEC)
sys.modules["vaillant_ebus.datetime"] = DATETIME
DATETIME_SPEC.loader.exec_module(DATETIME)

EbusdHolidayEntity = DATETIME.EbusdHolidayEntity
EbusdManualCoolingEntity = DATETIME.EbusdManualCoolingEntity


def _ebusd_data_from_graph(graph) -> dict[str, str]:
    data: dict[str, str] = {}
    for rk, raw in graph.raw_registers.items():
        circuit, name = rk.split(".", 1)
        for field, value in tc._register_values(rk, raw).items():
            if value is not None:
                data[f"{circuit}.{name}.{field}"] = value
    return data


# Coordinator stub whose heating circuit is resolved from a real discovery
# graph, mirroring how the live coordinator resolves ctlv2 to the controller.
class _GraphCoordinator:
    def __init__(self, graph, data: dict[str, str]) -> None:
        self._graph = graph
        self.data = {"ebusd": data}
        self.ebus = object()
        self.async_write_register = AsyncMock(return_value=True)
        self.async_update_listeners = MagicMock()

    @property
    def heating_circuit(self):
        return self._graph.resolve_circuit_result("ctlv2").circuit

    def get_device_info(self, *_args):
        return {"identifiers": {("vaillant_ebus", "dhw")}}


def _graph_coordinator(fixture: str = "community/hmux0_issue99_2026-09-10_173229.yaml") -> _GraphCoordinator:
    graph = tc.DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    return _GraphCoordinator(graph, _ebusd_data_from_graph(graph))


def _dhw_holiday_entity(coordinator) -> object:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    return EbusdHolidayEntity(
        coordinator, entry, "DHW Holiday Start", "HwcHolidayStartPeriod", "mdi:calendar-start", "dhw"
    )


# Build a manual-cooling entity with the same resolved-controller test harness as holiday entities.
def _manual_cooling_entity(coordinator) -> object:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    return EbusdManualCoolingEntity(
        coordinator, entry, "Manual Cooling Start Date", "ManualCoolingStartDate", "mdi:snowflake", "ctlv2"
    )


# Date-only entities must declare their supported component for HA's datetime service schema.
# Intent: writable holiday and manual-cooling entities expose dates, never times.
# Why: without these attributes HA rejects datetime.set_value before the ebusd write path runs.
def test_writable_datetime_entities_are_date_only() -> None:
    assert EbusdHolidayEntity._attr_has_date is True
    assert EbusdHolidayEntity._attr_has_time is False
    assert EbusdManualCoolingEntity._attr_has_date is True
    assert EbusdManualCoolingEntity._attr_has_time is False


# The reporter's HMUX0/CTLV3 bus carries a stray runtime ctlv2 probe node, but
# HwcHolidayStartPeriod is owned by ctlv3. The entity must resolve to ctlv3.
# Intent: the DHW holiday entity reads and writes the resolved ctlv3 controller, not the stray ctlv2 node.
# Why: guards the issue #99 controller-resolution fix on the hand-built datetime entities.
def test_holiday_entity_targets_resolved_controller_circuit() -> None:
    coordinator = _graph_coordinator()
    assert coordinator.heating_circuit == "ctlv3"
    entity = _dhw_holiday_entity(coordinator)
    assert entity.native_value is None  # 01.01.2015 is the unset sentinel


# A real controller holiday date must surface as a timezone-aware datetime.
# Intent: a valid ctlv3.HwcHolidayStartPeriod value decodes to a datetime at local midnight.
# Why: pins the read contract so a future change cannot quietly return unknown for a set date.
def test_holiday_entity_decodes_configured_date() -> None:
    coordinator = _graph_coordinator()
    coordinator.data["ebusd"]["ctlv3.HwcHolidayStartPeriod.value"] = "24.09.2026"
    entity = _dhw_holiday_entity(coordinator)
    assert entity.native_value == datetime(2026, 9, 24, tzinfo=_TZ)


# The write contract: resolved circuit + register + DD.MM.YYYY serialization.
# Intent: async_set_value writes ctlv3.HwcHolidayStartPeriod with a zero-padded DD.MM.YYYY date.
# Why: the DateTimeEntity write path is untested; a wrong circuit, register, or format is the issue #99 failure mode.
async def test_holiday_entity_write_contract() -> None:
    coordinator = _graph_coordinator()
    entity = _dhw_holiday_entity(coordinator)

    await entity.async_set_value(datetime(2026, 9, 24))

    coordinator.async_write_register.assert_awaited_once_with("ctlv3", "HwcHolidayStartPeriod", "24.09.2026")


# Single-digit days must be zero-padded so ebusd's date parser accepts them.
# Intent: 4 September serializes as 04.09.2026.
# Why: a non-padded day would be rejected by the HDA date decoder.
async def test_holiday_entity_write_zero_pads_day() -> None:
    coordinator = _graph_coordinator()
    entity = _dhw_holiday_entity(coordinator)

    await entity.async_set_value(datetime(2026, 9, 4))

    coordinator.async_write_register.assert_awaited_once_with("ctlv3", "HwcHolidayStartPeriod", "04.09.2026")


# Controller reset dates do not describe an armed manual-cooling period.
# Intent: manual cooling treats both known reset sentinels as unavailable.
# Why: the controller emits either sentinel after clearing a cooling window, not a real 2015/2019 schedule.
@pytest.mark.parametrize("value", ("01.01.2015", "01.01.2019"))
def test_manual_cooling_reset_dates_are_unset(value: str) -> None:
    coordinator = _graph_coordinator()
    coordinator.data["ebusd"]["ctlv3.ManualCoolingStartDate.value"] = value

    assert _manual_cooling_entity(coordinator).native_value is None


# A configured cooling date must remain a local midnight datetime after sentinel filtering.
# Intent: manual cooling preserves valid controller dates.
# Why: filtering reset dates must not turn a real cooling schedule into an unavailable entity.
def test_manual_cooling_decodes_configured_date() -> None:
    coordinator = _graph_coordinator()
    coordinator.data["ebusd"]["ctlv3.ManualCoolingStartDate.value"] = "24.09.2026"

    assert _manual_cooling_entity(coordinator).native_value == datetime(2026, 9, 24, tzinfo=_TZ)
