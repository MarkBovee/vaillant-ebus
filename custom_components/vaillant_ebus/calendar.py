"""eBUS timer programs as Home Assistant calendars; the hot water program can be edited (issue #208)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .backend.timer_program import (
    MAX_SLOTS_PER_DAY,
    SLOT_COUNT_SUFFIXES,
    TimerProgramError,
    TimeSlot,
    build_day_writes,
    ensure_all_slots_visible,
    has_temperature_column,
    parse_slot,
    parse_slot_counts,
)
from .const import DOMAIN
from .coordinator import VaillantCoordinator, get_register_value

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SCHEDULES = {
    "Heating Program": "CcTimer",
    "Zone Program": "Z1Timer",
    "Domestic Hot Water Program": "HwcTimer",
    "Cooling Program": "Z1CoolingTimer",
    "Cooling Program 2": "Z2CoolingTimer",
}
# Programs whose slots may be written. Only the hot water program is proven on two CTLV2 configurations (issue #208).
WRITABLE_PREFIXES = frozenset({"HwcTimer"})
_BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


# Create calendar entities for heating/DHW schedules
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    added_prefixes: set[str] = set()

    # Add each discovered schedule once, including schedules found later.
    # A fixed added flag would lose capabilities arriving during rediscovery.
    def _ensure_calendars() -> None:
        if not coordinator.discovery_ready or coordinator.heating_circuit is None:
            return
        schedules = {
            "Heating Program": ("CcTimer", coordinator.heating_circuit, coordinator.heating_circuit),
            "Domestic Hot Water Program": ("HwcTimer", coordinator.heating_circuit, "dhw"),
        }
        for zone in coordinator.zone_circuits():
            number = zone[1:]
            circuit = coordinator.zone_circuits()[zone]
            schedules.setdefault(
                "Zone Program" if number == "1" else f"Zone {number} Program",
                (f"Z{number}Timer", circuit, zone),
            )
            schedules.setdefault(
                "Cooling Program" if number == "1" else f"Cooling Program {number}",
                (f"Z{number}CoolingTimer", circuit, zone),
            )
        available = [
            (name, prefix, circuit, device_circuit)
            for name, (prefix, circuit, device_circuit) in schedules.items()
            if prefix not in added_prefixes
            and circuit is not None
            and (
                coordinator.has_zone_register(circuit, device_circuit, f"{prefix[2:]}_Monday0")
                if device_circuit.startswith("z")
                else coordinator.has_controller_register(f"{prefix}_Monday0")
            )
        ]
        if not available:
            return
        async_add_entities(
            EbusdCalendar(coordinator, entry, name, prefix, circuit, device_circuit)
            for name, prefix, circuit, device_circuit in available
        )
        added_prefixes.update(prefix for _, prefix, _, _ in available)

    _ensure_calendars()
    coordinator.register_post_discovery_callback(_ensure_calendars)


class EbusdCalendar(CoordinatorEntity[VaillantCoordinator], CalendarEntity):
    """Expose a weekly eBUS timer program; the hot water program also accepts new, changed and deleted slots."""

    _attr_has_entity_name = True

    # Initialize calendar entity with timer prefix
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
        name: str,
        prefix: str,
        circuit: str | None = None,
        device_circuit: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._prefix = prefix
        self._circuit = circuit or coordinator.heating_circuit
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_calendar_{prefix.lower()}"
        self._attr_device_info = coordinator.get_device_info(device_circuit or self._circuit)
        if prefix in WRITABLE_PREFIXES:
            self._attr_supported_features = (
                CalendarEntityFeature.CREATE_EVENT
                | CalendarEntityFeature.UPDATE_EVENT
                | CalendarEntityFeature.DELETE_EVENT
            )

    # The event that is active now, or the next one within the coming eight days.
    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        events = self._events_between(now, now + timedelta(days=8))
        active = [event for event in events if event.start <= now < event.end]
        return active[0] if active else next((event for event in events if event.start >= now), None)

    # Return calendar events in the given date range
    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        return self._events_between(start_date, end_date)

    # Build list of timer events between start and end dates
    def _events_between(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        day = start_date.date()
        while day <= end_date.date():
            weekday = WEEKDAYS[day.weekday()]
            for slot in range(3):
                value = self._value(f"{self._prefix}_{weekday}{slot}")
                event = _parse_slot(day, value, self._attr_name, uid=f"{weekday}:{slot}")
                if event and event.end > start_date and event.start < end_date:
                    events.append(event)
            day += timedelta(days=1)
        return events

    # Add a slot on every weekday the new event covers: its own weekday, or each BYDAY of a weekly rule.
    # The controller only stores weekly slots, so a single event is stored as a weekly slot too (issue #208).
    async def async_create_event(self, **kwargs: Any) -> None:
        slot = _slot_from_times(kwargs["dtstart"], kwargs["dtend"])
        for day in _event_weekdays(kwargs["dtstart"], kwargs.get("rrule")):
            slots, with_temperature = await self._read_day(day)
            await self._write_day(day, [*slots, slot], with_temperature)

    # Remove the slot behind an event; the uid names the weekday and the slot index.
    # Every occurrence of a weekly slot is the same controller slot, so the recurrence range does not matter.
    async def async_delete_event(
        self, uid: str, recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        day, index = _parse_uid(uid)
        slots, with_temperature = await self._read_day(day)
        if index >= len(slots):
            raise HomeAssistantError("This time slot no longer exists; refresh the calendar")
        await self._write_day(day, [slot for position, slot in enumerate(slots) if position != index], with_temperature)

    # Move or resize a slot: remove it from its weekday, then add the new times on the event's weekday(s).
    # The slot keeps its target temperature when it stays on the same layout.
    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        day, index = _parse_uid(uid)
        slots, with_temperature = await self._read_day(day)
        if index >= len(slots):
            raise HomeAssistantError("This time slot no longer exists; refresh the calendar")
        old = slots.pop(index)
        new = _slot_from_times(event["dtstart"], event["dtend"], old.temperature)
        targets = _event_weekdays(event["dtstart"], event.get("rrule"))
        if day not in targets:
            await self._write_day(day, slots, with_temperature)
        for target in targets:
            current, target_temperature = (slots, with_temperature) if target == day else await self._read_day(target)
            await self._write_day(target, [*current, new], target_temperature)

    # Read every slot of a weekday straight from the controller and check that none is hidden.
    # Returns the visible slots in order and whether the layout carries a temperature per slot.
    async def _read_day(self, day: str) -> tuple[list[TimeSlot], bool]:
        raw = [await self._read(f"{self._prefix}_{day}{index}") for index in range(MAX_SLOTS_PER_DAY)]
        slots = [slot for slot in (parse_slot(value) for value in raw) if slot is not None]
        ensure = await self._slot_count(day)
        try:
            ensure_all_slots_visible(day, slots, ensure)
        except TimerProgramError as exc:
            raise HomeAssistantError(str(exc)) from exc
        return slots, any(has_temperature_column(value) for value in raw if value)

    # Write one weekday slot by slot, then read it back and refresh the calendar.
    # A write the controller acknowledges but ignores is caught by comparing the read-back with the request.
    async def _write_day(self, day: str, slots: list[TimeSlot], with_temperature: bool) -> None:
        try:
            writes = build_day_writes(slots, with_temperature, self._default_temperature(slots))
        except TimerProgramError as exc:
            raise HomeAssistantError(str(exc)) from exc
        name = f"{self._prefix}_{day}"
        for value in writes:
            ok = await self.coordinator.async_write_register(
                self._circuit or "", name, value, strict_verify=False, refresh=False, require_discovered=False
            )
            if not ok:
                raise HomeAssistantError(f"ebusd did not accept writing {value!r} to {name}")
        stored, _ = await self._read_day(day)
        if [(slot.start, slot.end) for slot in stored] != [(slot.start, slot.end) for slot in sorted(slots)]:
            raise HomeAssistantError(f"The controller did not store the new time slots for {day}")
        await self.coordinator.async_request_refresh()

    # Read one register past ebusd's cache; an unknown message reads as no value.
    async def _read(self, name: str) -> str | None:
        value = await self.coordinator.async_read_register(self._circuit or "", name, force=True)
        return None if value is None or value.startswith("ERR:") else value

    # Read the controller's slot count for a weekday, or None when this configuration has no count message.
    async def _slot_count(self, day: str) -> int | None:
        for suffix in SLOT_COUNT_SUFFIXES:
            counts = parse_slot_counts(await self._read(f"{self._prefix}_{suffix}"))
            if counts is not None:
                return counts[WEEKDAYS.index(day)]
        return None

    # The temperature for a new slot: one of the day's slots, else the hot water setpoint.
    def _default_temperature(self, slots: list[TimeSlot]) -> float | None:
        known = next((slot.temperature for slot in slots if slot.temperature is not None), None)
        if known is not None:
            return known
        try:
            return float(self._value("HwcTempDesired") or "")
        except ValueError:
            return None

    # Get timer register value from coordinator data or register cache
    def _value(self, name: str) -> str | None:
        c = self._circuit
        if c is None:
            return None
        value = get_register_value(self.coordinator, c, name)
        if value is not None:
            return value
        expected = f"{c}.{name}".casefold()
        register = next(
            (value for key, value in self.coordinator.registers.items() if key.casefold() == expected),
            None,
        )
        return register.value.get("value") if register else None


# Parse a timer slot string into a CalendarEvent.
# With a uid the event is one occurrence of a weekly slot, so editing "all events" maps to the controller slot.
def _parse_slot(day: date, value: str | None, name: str, uid: str | None = None) -> CalendarEvent | None:
    if not value:
        return None
    parts = value.split(";")
    if len(parts) < 2 or parts[0] == "00:00" and parts[1] == "00:00":
        return None
    try:
        start_time = datetime.strptime(parts[0], "%H:%M").time()
        end_time = datetime.strptime(parts[1], "%H:%M").time()
    except ValueError:
        return None
    start = dt_util.as_local(datetime.combine(day, start_time))
    end = dt_util.as_local(datetime.combine(day, end_time))
    if end <= start:
        end += timedelta(days=1)
    description = f"Target temperature: {parts[2]} C" if len(parts) > 2 and parts[2] != "-" else None
    if uid is None:
        return CalendarEvent(start=start, end=end, summary=name, description=description)
    return CalendarEvent(
        start=start,
        end=end,
        summary=name,
        description=description,
        uid=uid,
        rrule="FREQ=WEEKLY",
        recurrence_id=day.isoformat(),
    )


# Turn an event's start and end into a slot of one day.
# The controller has no slot across midnight, so the event must start and end on the same date.
def _slot_from_times(start: Any, end: Any, temperature: float | None = None) -> TimeSlot:
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise HomeAssistantError("A time slot needs a start and end time, not a whole day")
    if dt_util.as_local(end).date() != dt_util.as_local(start).date():
        raise HomeAssistantError("A time slot must start and end on the same day")
    return TimeSlot(
        dt_util.as_local(start).time().replace(second=0, microsecond=0),
        dt_util.as_local(end).time().replace(second=0, microsecond=0),
        temperature,
    )


# List the weekdays an event covers: each BYDAY of a weekly rule, else the weekday of its start.
def _event_weekdays(start: Any, rrule: str | None) -> list[str]:
    days: list[str] = []
    for part in (rrule or "").split(";"):
        key, _, value = part.partition("=")
        if key.strip().upper() == "BYDAY":
            days = [WEEKDAYS[_BYDAY[code.strip()[-2:].upper()]] for code in value.split(",") if code.strip()]
    if days:
        return list(dict.fromkeys(days))
    return [WEEKDAYS[dt_util.as_local(start).weekday() if isinstance(start, datetime) else start.weekday()]]


# Split an event uid (`Monday:1`) into the weekday and the slot index.
def _parse_uid(uid: str) -> tuple[str, int]:
    day, _, index = uid.partition(":")
    if day not in WEEKDAYS or not index.isdigit():
        raise HomeAssistantError(f"Unknown time slot {uid!r}")
    return day, int(index)
