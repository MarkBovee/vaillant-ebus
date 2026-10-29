"""Unit tests for the calendar platform.

The calendar exposes eBUS timer programs as read-only recurring events. These
tests pin the timer-slot parser and the entity behavior against a coordinator
whose timer registers may or may not carry data.

Uses the shared homeassistant mock scaffolding from tests._component_loader.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests import test_coordinator as tc  # noqa: F401 — shared test helpers

mock_homeassistant = sys.modules["homeassistant"]
const_module = sys.modules["vaillant_ebus.const"]
CALENDAR = sys.modules["vaillant_ebus.calendar"]

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
# Intent: SCHEDULES maps "Cooling Program" to Z1CoolingTimer and "Cooling Program 2" to Z2CoolingTimer.
# Why: guards the additive per-zone cooling-timer registration that hardware without those registers must tolerate.
def test_cooling_program_in_schedules() -> None:
    assert "Cooling Program" in SCHEDULES
    assert SCHEDULES["Cooling Program"] == "Z1CoolingTimer"
    assert "Cooling Program 2" in SCHEDULES
    assert SCHEDULES["Cooling Program 2"] == "Z2CoolingTimer"


# _parse_slot parses a "HH:MM;HH:MM;temp" slot, ignoring empty/zero slots.
# Intent: _parse_slot builds events with summary and temperature description,
# rolls past-midnight intervals to the next day, and rejects zero/empty/no-data
# slots.
# Why: pins the timer-slot parser against malformed and overnight schedules.
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
# Intent: A calendar built from an empty coordinator exposes its expected
# unique_id/name and returns no events for the queried day.
# Why: proves an absent timer register does not fabricate events or break the entity.
def test_calendar_empty_without_data() -> None:
    cal = EbusdCalendar(_coordinator(), _entry(), "Cooling Program", "Z1CoolingTimer")
    assert cal._attr_unique_id == "entry-1_calendar_z1coolingtimer"
    assert cal._attr_name == "Cooling Program"
    start = datetime(2026, 8, 27, 0, 0)
    end = datetime(2026, 8, 28, 0, 0)
    assert cal._events_between(start, end) == []


# A calendar entity populates events from discovered timer register data.
# 2026-08-27 is a Thursday, so the Thursday0..2 slots apply.
# Intent: Thursday's three discovered timer slots produce exactly the two non-zero events with correct start/end times.
# Why: verifies discovered register data is parsed into calendar events and the zero slot is dropped.
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


HomeAssistantError = sys.modules["homeassistant.exceptions"].HomeAssistantError


class _FakeTimerController:
    """A CTLV2 hot water program that behaves like the controllers tested live for issue #208."""

    # Intent: hold the slots per weekday, the layout (temperature column, readable slots) and the count message name.
    # Why: the two proven layouts differ in exactly these three points.
    def __init__(self, with_temperature: bool = True, readable: int = 3, count_name: str = "Timeframes") -> None:
        self.with_temperature = with_temperature
        self.readable = readable
        self.count_name = count_name
        self.days: dict[str, list[tuple[str, str, str]]] = {day: [] for day in CALENDAR.WEEKDAYS}
        self.writes: list[str] = []

    # Intent: answer slot and count reads like ebusd: the empty marker for a free slot, an error for a slot the
    #         configuration cannot read.
    # Why: the calendar reads each slot past the cache before it rewrites a day.
    async def read(self, circuit: str, name: str, field: str = "", force: bool = False) -> str:
        if name == f"HwcTimer_{self.count_name}":
            return ";".join(str(len(self.days[day])) for day in CALENDAR.WEEKDAYS)
        if not name[-1].isdigit():
            return "ERR: element not found"
        day, index = name[len("HwcTimer_") : -1], int(name[-1])
        if index >= self.readable:
            return "ERR: element not found"
        slots = self.days[day]
        start, end, temperature = slots[index] if index < len(slots) else ("00:00", "00:00", "-")
        return f"{start};{end};{temperature}" if self.with_temperature else f"{start};{end}"

    # Intent: apply a slot write like the controller: slot 0 sets the count, a later slot is ignored unless the count
    #         already includes it, and count 0 clears the day.
    # Why: the owner's live test showed a write of slot 1 acknowledged but ignored before slot 0 carried count 2.
    async def write(self, circuit: str, name: str, value: str, **kwargs: object) -> bool:
        self.writes.append(f"{name}={value}")
        parts = value.split(";")
        index, count, start, end = int(parts[0]), int(parts[1]), parts[2], parts[3]
        temperature = parts[4] if len(parts) > 4 else "-"
        day = name[len("HwcTimer_") :]
        slots = self.days[day]
        if count == 0:
            self.days[day] = []
        elif index == 0:
            self.days[day] = ([(start, end, temperature)] + slots[1:count])[:count]
            self.days[day] += [("00:00", "00:00", "-")] * (count - len(self.days[day]))
        elif index < len(slots):
            slots[index] = (start, end, temperature)
        return True


# Intent: build a writable hot water calendar on top of a fake controller.
# Why: the write path only talks to the coordinator's forced read and write calls.
def _writable_calendar(controller: _FakeTimerController) -> EbusdCalendar:
    coordinator = _coordinator("ctlv2")
    coordinator.data = {"ebusd": {"ctlv2.HwcTempDesired.value": "45"}}
    coordinator.async_read_register = controller.read
    coordinator.async_write_register = controller.write
    coordinator.async_request_refresh = AsyncMock()
    return EbusdCalendar(coordinator, _entry(), "Domestic Hot Water Program", "HwcTimer", "ctlv2", "dhw")


# Intent: a new event with a weekly rule adds a slot on every listed weekday, slot 0 first, with the day's temperature.
# Why: issue #208 - the controller stores weekly slots, and the owner's test showed slot 0 must carry the new count.
async def test_dhw_calendar_creates_a_weekly_slot_on_each_listed_day() -> None:
    controller = _FakeTimerController()
    controller.days["Monday"] = [("13:30", "15:00", "35.0")]
    calendar = _writable_calendar(controller)

    await calendar.async_create_event(
        dtstart=datetime(2026, 11, 2, 16, 0), dtend=datetime(2026, 11, 2, 16, 30), rrule="FREQ=WEEKLY;BYDAY=MO,WE"
    )

    assert controller.days["Monday"] == [("13:30", "15:00", "35.0"), ("16:00", "16:30", "35.0")]
    # A day without slots takes the hot water setpoint as the slot temperature.
    assert controller.days["Wednesday"] == [("16:00", "16:30", "45.0")]
    assert controller.writes[:2] == ["HwcTimer_Monday=0;2;13:30;15:00;35.0", "HwcTimer_Monday=1;2;16:00;16:30;35.0"]


# Intent: deleting the last slot clears the day, and updating a slot moves it within the day.
# Why: issue #208 - count 0 clears a day; an update must not leave the old slot behind.
async def test_dhw_calendar_deletes_and_updates_slots() -> None:
    controller = _FakeTimerController(with_temperature=False, count_name="Timeslots")
    controller.days["Tuesday"] = [("03:00", "03:10", "-"), ("03:20", "03:30", "-")]
    calendar = _writable_calendar(controller)

    await calendar.async_update_event(
        "Tuesday:1", {"dtstart": datetime(2026, 11, 3, 4, 0), "dtend": datetime(2026, 11, 3, 4, 20)}
    )
    assert controller.days["Tuesday"] == [("03:00", "03:10", "-"), ("04:00", "04:20", "-")]

    await calendar.async_delete_event("Tuesday:1")
    await calendar.async_delete_event("Tuesday:0")
    assert controller.days["Tuesday"] == []
    assert controller.writes[-1] == "HwcTimer_Tuesday=0;0;00:00;00:00"


# Intent: a day with more slots than the configuration can read is not rewritten.
# Why: issue #208 - only slot 0 decodes on that config, so a rewrite would silently drop the hidden slot.
async def test_dhw_calendar_refuses_a_day_with_hidden_slots() -> None:
    controller = _FakeTimerController(with_temperature=False, readable=1, count_name="Timeslots")
    controller.days["Tuesday"] = [("03:00", "03:10", "-"), ("03:20", "03:30", "-")]
    calendar = _writable_calendar(controller)

    with pytest.raises(HomeAssistantError, match="Tuesday has 2 time slots"):
        await calendar.async_create_event(dtstart=datetime(2026, 11, 3, 5, 0), dtend=datetime(2026, 11, 3, 5, 30))
    assert controller.writes == []


# Intent: a slot the controller acknowledges but does not store raises, and only the hot water program is writable.
# Why: the owner's first live write was acknowledged and ignored; a silent success would show a slot that is not there.
async def test_dhw_calendar_reports_an_ignored_write_and_other_programs_stay_read_only() -> None:
    controller = _FakeTimerController()

    # Intent: acknowledge every write but store nothing.
    # Why: mirrors a controller that ignores the slot.
    async def _ignore(circuit: str, name: str, value: str, **kwargs: object) -> bool:
        return True

    calendar = _writable_calendar(controller)
    calendar.coordinator.async_write_register = _ignore
    with pytest.raises(HomeAssistantError, match="did not store"):
        await calendar.async_create_event(dtstart=datetime(2026, 11, 2, 6, 0), dtend=datetime(2026, 11, 2, 6, 30))

    heating = EbusdCalendar(_coordinator("ctlv2"), _entry(), "Heating Program", "CcTimer", "ctlv2", "ctlv2")
    assert not getattr(heating, "_attr_supported_features", 0)
    assert calendar._attr_supported_features


# Intent: a slot read that fails (no answer or a bus error) stops the change before anything is written.
# Why: a failed read looked like a free slot, so adding a slot would have rewritten the day and dropped the real one.
@pytest.mark.parametrize("failure", [None, "ERR: read timeout"])
async def test_dhw_calendar_writes_nothing_when_a_slot_cannot_be_read(failure: str | None) -> None:
    controller = _FakeTimerController()
    controller.days["Monday"] = [("13:30", "15:00", "35.0")]
    calendar = _writable_calendar(controller)
    working_read = controller.read

    # Intent: fail the read of slot 0 only.
    # Why: one unreadable slot is enough to make the day look emptier than it is.
    async def _flaky(circuit: str, name: str, field: str = "", force: bool = False) -> str | None:
        return failure if name == "HwcTimer_Monday0" else await working_read(circuit, name, field, force)

    calendar.coordinator.async_read_register = _flaky
    with pytest.raises(HomeAssistantError, match="nothing was changed"):
        await calendar.async_create_event(dtstart=datetime(2026, 11, 2, 16, 0), dtend=datetime(2026, 11, 2, 16, 30))
    assert controller.writes == []


# Intent: a non-weekly or malformed repeat rule, and a day that cannot be fully read without a count message, are
#         refused before anything is written.
# Why: review of 1.13.2 - a daily rule silently wrote one weekday, an unknown BYDAY raised a bare KeyError, and without
#      a count message an undefined slot read could hide a slot that a rewrite would drop.
@pytest.mark.parametrize(
    ("rrule", "count_name", "readable", "message"),
    [
        ("FREQ=DAILY", "Timeframes", 3, "weekly rule"),
        ("FREQ=WEEKLY;BYDAY=XX", "Timeframes", 3, "Unknown weekday"),
        (None, "Missing", 1, "Not every time slot"),
    ],
)
async def test_dhw_calendar_refuses_unsafe_requests(
    rrule: str | None, count_name: str, readable: int, message: str
) -> None:
    controller = _FakeTimerController(count_name=count_name, readable=readable)
    calendar = _writable_calendar(controller)

    with pytest.raises(HomeAssistantError, match=message):
        await calendar.async_create_event(
            dtstart=datetime(2026, 11, 2, 6, 0), dtend=datetime(2026, 11, 2, 6, 30), rrule=rrule
        )
    assert controller.writes == []
