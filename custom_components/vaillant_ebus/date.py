"""Date platform for holiday periods and manual-cooling windows."""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VaillantCoordinator, get_register_value

DATE_FMT = "%d.%m.%Y"
RESET_VALUES = frozenset(("01.01.2015", "01.01.2019"))

MANUAL_COOLING_ENTITIES = [
    ("Manual Cooling Start Date", "ManualCoolingStartDate", "mdi:snowflake", "controller"),
    ("Manual Cooling End Date", "ManualCoolingEndDate", "mdi:snowflake", "controller"),
]


# Create date entities for date-only controller registers.
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    added_registers: set[str] = set()

    # Intent: add dates only for active discovered zone/controller registers.
    # Why: cache values and static inactive-zone rows must not create date controls.
    # Add each date control once its backing register appears in the discovery graph.
    def ensure_date_entities() -> None:
        entities: list[DateEntity] = []
        if not coordinator.discovery_ready:
            return
        controller = coordinator.heating_circuit
        if controller is not None:
            for zone in coordinator.zone_circuits():
                number = zone[1:]
                label = "Z1" if number == "1" else f"Zone {number}"
                for suffix, title, icon in (
                    ("HolidayStartPeriod", "Holiday Start", "mdi:calendar-start"),
                    ("HolidayEndPeriod", "Holiday End", "mdi:calendar-end"),
                ):
                    register = f"{zone.upper()}{suffix}"
                    if register not in added_registers and coordinator.has_zone_register(controller, zone, suffix):
                        entities.append(
                            EbusdHolidayEntity(coordinator, entry, f"{label} {title}", register, icon, zone)
                        )
                        added_registers.add(register)
            for register, title, icon in (
                ("HwcHolidayStartPeriod", "DHW Holiday Start", "mdi:calendar-start"),
                ("HwcHolidayEndPeriod", "DHW Holiday End", "mdi:calendar-end"),
            ):
                if register not in added_registers and coordinator.has_controller_register(register):
                    entities.append(EbusdHolidayEntity(coordinator, entry, title, register, icon, "dhw"))
                    added_registers.add(register)
        for name, register, icon, zone in MANUAL_COOLING_ENTITIES:
            paired_register = (
                "ManualCoolingEndDate" if register == "ManualCoolingStartDate" else "ManualCoolingStartDate"
            )
            if (
                register not in added_registers
                and coordinator.has_controller_register(register)
                and coordinator.has_controller_register(paired_register)
            ):
                entities.append(EbusdManualCoolingEntity(coordinator, entry, name, register, icon, zone))
                added_registers.add(register)
        if entities:
            async_add_entities(entities)

    ensure_date_entities()
    coordinator.register_post_discovery_callback(ensure_date_entities)


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
        device_circuit = "dhw" if zone == "dhw" else zone
        self._attr_device_info = coordinator.get_device_info(device_circuit)

    # Return a configured holiday date without inventing a time component.
    @property
    def native_value(self) -> date | None:
        circuit = self.coordinator.heating_circuit
        if circuit is None:
            return None
        raw = get_register_value(self.coordinator, circuit, self._register)
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
        self._attr_device_info = coordinator.get_device_info(coordinator.heating_circuit or "dhw")

    # Treat controller reset dates as an unset manual-cooling window.
    @property
    def native_value(self) -> date | None:
        circuit = self.coordinator.heating_circuit
        if circuit is None:
            return None
        raw = get_register_value(self.coordinator, circuit, self._register)
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
