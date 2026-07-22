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
from .coordinator import VaillantCoordinator

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SCHEDULES = {
    "Heating Program": "CcTimer",
    "Zone Program": "Z1Timer",
    "Domestic Hot Water Program": "HwcTimer",
}


# Create calendar entities for heating/DHW schedules
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        EbusdCalendar(coordinator, entry, name, prefix)
        for name, prefix in SCHEDULES.items()
    )


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
    ) -> None:
        super().__init__(coordinator)
        self._prefix = prefix
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_calendar_{prefix.lower()}"
        self._attr_device_info = coordinator.get_device_info("ctlv2")

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
        key = f"ctlv2.{name}.value"
        value = self.coordinator.data.get("ebusd", {}).get(key)
        if value is not None:
            return str(value)
        register = self.coordinator.registers.get(f"ctlv2.{name}")
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
