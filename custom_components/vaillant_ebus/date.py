"""Date platform for holiday periods and manual-cooling windows."""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VaillantCoordinator

DATE_FMT = "%d.%m.%Y"
RESET_VALUES = frozenset(("01.01.2015", "01.01.2019"))

HOLIDAY_ENTITIES = [
    ("Z1 Holiday Start", "Z1HolidayStartPeriod", "mdi:calendar-start", "z1"),
    ("Z1 Holiday End", "Z1HolidayEndPeriod", "mdi:calendar-end", "z1"),
    ("DHW Holiday Start", "HwcHolidayStartPeriod", "mdi:calendar-start", "dhw"),
    ("DHW Holiday End", "HwcHolidayEndPeriod", "mdi:calendar-end", "dhw"),
]

MANUAL_COOLING_ENTITIES = [
    ("Manual Cooling Start Date", "ManualCoolingStartDate", "mdi:snowflake", "ctlv2"),
    ("Manual Cooling End Date", "ManualCoolingEndDate", "mdi:snowflake", "ctlv2"),
]


# Create date entities for date-only controller registers.
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[DateEntity] = []
    for name, register, icon, zone in HOLIDAY_ENTITIES:
        entities.append(EbusdHolidayEntity(coordinator, entry, name, register, icon, zone))
    for name, register, icon, zone in MANUAL_COOLING_ENTITIES:
        entities.append(EbusdManualCoolingEntity(coordinator, entry, name, register, icon, zone))
    async_add_entities(entities)


class EbusdHolidayEntity(CoordinatorEntity[VaillantCoordinator], DateEntity):
    _attr_has_entity_name = True

    # Initialize a date-only holiday entity with its register and logical device.
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

    # Return a configured holiday date without inventing a time component.
    @property
    def native_value(self) -> date | None:
        circuit = self.coordinator.heating_circuit
        if circuit is None:
            return None
        raw = self.coordinator.data.get("ebusd", {}).get(f"{circuit}.{self._register}.value")
        if not raw or str(raw) in RESET_VALUES:
            return None
        try:
            return datetime.strptime(str(raw), DATE_FMT).date()
        except TypeError, ValueError:
            return None

    # Write a holiday date through the central path on the resolved controller circuit.
    async def async_set_value(self, value: date) -> None:
        circuit = self.coordinator.heating_circuit
        if self.coordinator.ebus and circuit is not None:
            await self.coordinator.async_write_register(circuit, self._register, value.strftime(DATE_FMT))


class EbusdManualCoolingEntity(CoordinatorEntity[VaillantCoordinator], DateEntity):
    """Manual cooling start/end date (myVaillant 'cool until [date]')."""

    _attr_has_entity_name = True

    # Initialize a date-only manual-cooling entity with its register and logical device.
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

    # Treat controller reset dates as an unset manual-cooling window.
    @property
    def native_value(self) -> date | None:
        circuit = self.coordinator.heating_circuit
        if circuit is None:
            return None
        raw = self.coordinator.data.get("ebusd", {}).get(f"{circuit}.{self._register}.value")
        if (
            not raw
            or str(raw) in RESET_VALUES
            or str(raw) in ("-", "")
            or str(raw).startswith(("ERR:", "no data stored"))
        ):
            return None
        try:
            return datetime.strptime(str(raw), DATE_FMT).date()
        except TypeError, ValueError:
            return None

    # Write the selected manual-cooling date through the resolved controller circuit.
    async def async_set_value(self, value: date) -> None:
        circuit = self.coordinator.heating_circuit
        if self.coordinator.ebus and circuit is not None:
            await self.coordinator.async_write_register(circuit, self._register, value.strftime(DATE_FMT))
