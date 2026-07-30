"""Datetime platform for quick veto end and holiday periods."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import VaillantCoordinator

DATE_FMT = "%d.%m.%Y"
TIME_FMT = "%H:%M:%S"
HOLIDAY_RESET = "01.01.2015"

DEFAULT_TIME = "00:00:00"

HOLIDAY_ENTITIES = [
    ("Z1 Holiday Start", "Z1HolidayStartPeriod", "mdi:calendar-start", "z1"),
    ("Z1 Holiday End", "Z1HolidayEndPeriod", "mdi:calendar-end", "z1"),
    ("DHW Holiday Start", "HwcHolidayStartPeriod", "mdi:calendar-start", "dhw"),
    ("DHW Holiday End", "HwcHolidayEndPeriod", "mdi:calendar-end", "dhw"),
]


# Create datetime entities for quick veto end and holiday periods
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[DateTimeEntity] = [EbusdQuickVetoEndEntity(coordinator, entry)]
    for name, register, icon, zone in HOLIDAY_ENTITIES:
        entities.append(EbusdHolidayEntity(coordinator, entry, name, register, icon, zone))
    async_add_entities(entities)


class EbusdQuickVetoEndEntity(CoordinatorEntity[VaillantCoordinator], DateTimeEntity):
    _attr_has_entity_name = True
    _attr_name = "Quick Veto End"
    _attr_icon = "mdi:calendar-clock"

    # Initialize quick veto end entity, disabled by default
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_quick_veto_end"
        self._attr_entity_registry_enabled_default = False
        self._attr_device_info = coordinator.get_device_info("z1")

    # Return quick veto end date/time as local datetime
    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data.get("ebusd", {})
        c = self.coordinator.heating_circuit
        end_date = data.get(f"{c}.Z1QuickVetoEndDate.value")
        end_time = data.get(f"{c}.Z1QuickVetoEndTime.value")
        if not end_date or not end_time or end_date == HOLIDAY_RESET:
            return None
        try:
            naive = datetime.strptime(f"{end_date} {end_time}", f"{DATE_FMT} {TIME_FMT}")
            return naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        except ValueError, TypeError:
            return None


class EbusdHolidayEntity(CoordinatorEntity[VaillantCoordinator], DateTimeEntity):
    _attr_has_entity_name = True

    # Initialize holiday date entity with register and zone mapping
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
        name: str,
        register: str,
        icon: str,
        zone: str,
    ) -> None:
        super().__init__(coordinator)
        self._register = register
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{register.lower()}"
        self._attr_device_info = coordinator.get_device_info(zone)

    # Return holiday start/end date as datetime (time set to midnight)
    @property
    def native_value(self) -> datetime | None:
        raw = self.coordinator.data.get("ebusd", {}).get(f"{self.coordinator.heating_circuit}.{self._register}.value")
        if not raw or str(raw) == HOLIDAY_RESET:
            return None
        try:
            naive = datetime.strptime(f"{raw} {DEFAULT_TIME}", f"{DATE_FMT} {TIME_FMT}")
            return naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        except ValueError, TypeError:
            return None

    # Write holiday date to ebusd register and trigger refresh
    async def async_set_value(self, value: datetime) -> None:
        ebus = self.coordinator.ebus
        if ebus:
            date_str = value.strftime(DATE_FMT)
            result = await ebus.write_register(self.coordinator.heating_circuit, self._register, date_str)
            if result.success:
                await self.coordinator.async_request_refresh()
