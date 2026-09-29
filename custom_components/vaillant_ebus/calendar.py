"""Read-only eBUS schedules as Home Assistant calendars."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

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


# Create calendar entities for heating/DHW schedules
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    added_prefixes: set[str] = set()

    # Intent: add each discovered schedule once, including schedules found later.
    # Why: a fixed added flag would lose capabilities arriving during rediscovery.
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
    """Expose a recurring eBUS timer program without allowing timer writes."""

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

    @property
    def event(self) -> CalendarEvent | None:
        # Return current or next upcoming scheduled event
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
                event = _parse_slot(day, value, self._attr_name)
                if event and event.end > start_date and event.start < end_date:
                    events.append(event)
            day += timedelta(days=1)
        return events

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


# Parse a timer slot string into a CalendarEvent
def _parse_slot(day: date, value: str | None, name: str) -> CalendarEvent | None:
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
    return CalendarEvent(start=start, end=end, summary=name, description=description)
