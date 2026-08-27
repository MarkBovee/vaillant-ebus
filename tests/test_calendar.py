"""Unit tests for the calendar platform.

The calendar exposes eBUS timer programs as read-only recurring events. These
tests pin the timer-slot parser and the entity behavior against a coordinator
whose timer registers may or may not carry data.

Reuses the homeassistant mock scaffolding from tests.test_coordinator.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

from tests import test_coordinator as tc  # noqa: F401 — installs shared HA mocks

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"

mock_homeassistant = sys.modules["homeassistant"]


class CalendarEvent:
    def __init__(self, start, end, summary, description=None) -> None:
        self.start = start
        self.end = end
        self.summary = summary
        self.description = description


class _MockCalendarEntity:
    @property
    def unique_id(self) -> str | None:
        return getattr(self, "_attr_unique_id", None)

    @property
    def name(self) -> str | None:
        return getattr(self, "_attr_name", None)

    @property
    def event(self):
        return None


class _MockCoordinatorEntity(_MockCalendarEntity):
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    def async_write_ha_state(self) -> None:
        pass

    def _handle_coordinator_update(self) -> None:
        pass

    async def async_update(self) -> None:
        pass

    def __class_getitem__(cls, item):
        return cls


def _local(dt: datetime) -> datetime:
    return dt


calendar_pkg = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.components.calendar", None)
)
calendar_pkg.CalendarEntity = _MockCalendarEntity
calendar_pkg.CalendarEvent = CalendarEvent
sys.modules["homeassistant.components.calendar"] = calendar_pkg

ha_util = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("homeassistant.util", None))
ha_util.dt = MagicMock()
ha_util.dt.as_local = _local
ha_util.dt.now = lambda: datetime(2026, 8, 27, 12, 0, 0)
sys.modules["homeassistant.util"] = ha_util
sys.modules["homeassistant.util.dt"] = ha_util.dt

entity_platform = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.helpers.entity_platform", None)
)
entity_platform.AddEntitiesCallback = object
sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

mock_homeassistant.helpers.update_coordinator.CoordinatorEntity = _MockCoordinatorEntity
mock_homeassistant.config_entries.ConfigEntry = object
mock_homeassistant.core.HomeAssistant = object

const_module = sys.modules["vaillant_ebus.const"]
const_module.DOMAIN = "vaillant_ebus"

CALENDAR_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.calendar", COMPONENT_PATH / "calendar.py")
assert CALENDAR_SPEC and CALENDAR_SPEC.loader
CALENDAR = importlib.util.module_from_spec(CALENDAR_SPEC)
sys.modules["vaillant_ebus.calendar"] = CALENDAR
CALENDAR_SPEC.loader.exec_module(CALENDAR)

EbusdCalendar = CALENDAR.EbusdCalendar
_parse_slot = CALENDAR._parse_slot
SCHEDULES = CALENDAR.SCHEDULES


def _entry() -> MagicMock:
    e = MagicMock()
    e.entry_id = "entry-1"
    e.options = {}
    e.data = {}
    return e


def _coordinator(heating_circuit: str = "basv", registers: dict | None = None) -> MagicMock:
    c = MagicMock()
    c.heating_circuit = heating_circuit
    c.data = {"ebusd": {}}
    c.registers = registers or {}
    c.get_device_info = MagicMock(return_value={"identifiers": {("vaillant_ebus", "basv")}})
    return c


# A cooling-timer schedule entry is registered in SCHEDULES.
def test_cooling_program_in_schedules() -> None:
    assert "Cooling Program" in SCHEDULES
    assert SCHEDULES["Cooling Program"] == "Z1CoolingTimer"
    assert "Cooling Program 2" in SCHEDULES
    assert SCHEDULES["Cooling Program 2"] == "Z2CoolingTimer"


# _parse_slot parses a "HH:MM;HH:MM;temp" slot, ignoring empty/zero slots.
def test_parse_slot() -> None:
    day = date(2026, 8, 27)
    ev = _parse_slot(day, "06:00;12:00;21", "Cooling Program")
    assert ev is not None
    assert ev.summary == "Cooling Program"
    assert ev.description == "Target temperature: 21 C"
    assert ev.start == datetime(2026, 8, 27, 6, 0)
    assert ev.end == datetime(2026, 8, 27, 12, 0)

    # An interval that crosses midnight rolls over to the next day.
    ev2 = _parse_slot(day, "22:00;02:00;21", "Cooling Program")
    assert ev2 is not None
    assert ev2.end == datetime(2026, 8, 28, 2, 0)

    assert _parse_slot(day, "00:00;00:00;21", "Cooling Program") is None
    assert _parse_slot(day, None, "Cooling Program") is None
    assert _parse_slot(day, "no data stored", "Cooling Program") is None


# A calendar entity with no timer data yields no events (additive/empty).
def test_calendar_empty_without_data() -> None:
    cal = EbusdCalendar(_coordinator(), _entry(), "Cooling Program", "Z1CoolingTimer")
    assert cal._attr_unique_id == "entry-1_calendar_z1coolingtimer"
    assert cal._attr_name == "Cooling Program"
    start = datetime(2026, 8, 27, 0, 0)
    end = datetime(2026, 8, 28, 0, 0)
    assert cal._events_between(start, end) == []


# A calendar entity populates events from discovered timer register data.
# 2026-08-27 is a Thursday, so the Thursday0..2 slots apply.
def test_calendar_populates_from_register_data() -> None:
    registers = {
        "basv.Z1CoolingTimer_Thursday0": MagicMock(value={"value": "06:00;12:00;21"}),
        "basv.Z1CoolingTimer_Thursday1": MagicMock(value={"value": "18:00;22:00;-"}),
        "basv.Z1CoolingTimer_Thursday2": MagicMock(value={"value": "00:00;00:00;-"}),
    }
    cal = EbusdCalendar(_coordinator(registers=registers), _entry(), "Cooling Program", "Z1CoolingTimer")
    start = datetime(2026, 8, 27, 0, 0)
    end = datetime(2026, 8, 28, 0, 0)
    events = cal._events_between(start, end)
    assert len(events) == 2
    assert events[0].start == datetime(2026, 8, 27, 6, 0)
    assert events[0].end == datetime(2026, 8, 27, 12, 0)
    assert events[1].start == datetime(2026, 8, 27, 18, 0)
    assert events[1].end == datetime(2026, 8, 27, 22, 0)
