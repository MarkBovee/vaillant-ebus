"""Switch platform for Vaillant EBUS."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backend.entity_factory import EntityDescription
from .const import DOMAIN
from .coordinator import VaillantCoordinator

_LOGGER = logging.getLogger(__name__)

SWITCH_ON_VALUES = {"1", "on", "true", "yes"}
FAR_FUTURE = "01.01.2099"
UNSET_DATE = "01.01.2015"


# Create switch entities and away-mode switch
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = []

    for desc in coordinator.entities:
        if desc.entity_type != "switch":
            continue
        uid = f"{entry.entry_id}_{desc.unique_id}"
        entities.append(EbusdSwitch(coordinator, desc, uid, entry))

    entities.append(AwayModeSwitch(coordinator, entry))
    entities.append(HwcBoostSwitch(coordinator, entry))
    entities.append(HwcAwayModeSwitch(coordinator, entry))

    async_add_entities(entities)


class EbusdSwitch(CoordinatorEntity[VaillantCoordinator], SwitchEntity):
    # Initialize switch entity from entity description
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        desc: EntityDescription,
        unique_id: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._desc = desc
        self._attr_unique_id = unique_id
        self._attr_has_entity_name = True
        self._attr_entity_registry_enabled_default = desc.enabled_by_default
        self._attr_device_info = coordinator.get_device_info(desc.device_circuit)
        self._attr_name = desc.meta.friendly_name or desc.name
        if desc.meta.icon:
            self._attr_icon = desc.meta.icon

    @property
    def is_on(self) -> bool | None:
        # Return boolean state from ebusd data
        data = self.coordinator.data.get("ebusd", {})
        raw = data.get(self._desc.key)
        if raw is None:
            return None
        return raw.strip().lower() in SWITCH_ON_VALUES

    # Turn switch on by writing "1" to ebusd
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write("1")

    # Turn switch off by writing "0" to ebusd
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write("0")

    # Write value to ebusd and trigger refresh
    async def _write(self, value: str) -> None:
        if not self.coordinator.ebus:
            return
        result = await self.coordinator.ebus.write_register(
            self._desc.circuit,
            self._desc.name,
            value,
        )
        if result.success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.warning("Write failed for %s: %s", self._desc.key, result.error_message)


# Parse Vaillant date string to date object
def _parse_date(raw: str | None) -> date | None:
    if not raw or raw in ("no data stored", "-", ""):
        return None
    try:
        return datetime.strptime(raw.strip(), "%d.%m.%Y").date()
    except (ValueError, TypeError):
        return None


# Check if today falls within holiday period
def _is_holiday_active(start_raw: str | None, end_raw: str | None) -> bool:
    start = _parse_date(start_raw)
    end = _parse_date(end_raw)
    if start is None or end is None:
        return False
    today = date.today()
    return start <= today <= end


# Return today's date as DD.MM.YYYY string
def _today_str() -> str:
    return date.today().strftime("%d.%m.%Y")


class AwayModeSwitch(CoordinatorEntity[VaillantCoordinator], SwitchEntity):
    # Initialize away mode switch with unique ID
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_away_mode"
        self._attr_has_entity_name = True
        self._attr_name = "Away Mode"
        self._attr_icon = "mdi:exit-run"
        self._attr_device_info = coordinator.get_device_info("z1")

    @property
    def is_on(self) -> bool | None:
        # True when holiday start/end dates contain today
        data = self.coordinator.data.get("ebusd", {})
        start = data.get(f"{self.coordinator.heating_circuit}.Z1HolidayStartPeriod.value")
        end = data.get(f"{self.coordinator.heating_circuit}.Z1HolidayEndPeriod.value")
        if start is None or end is None:
            return None
        return _is_holiday_active(start, end)

    # Set holiday dates from today to far future, enable away mode
    async def async_turn_on(self, **kwargs: Any) -> None:
        ebus = self.coordinator.ebus
        if not ebus:
            return
        today = _today_str()
        data = self.coordinator.data.get("ebusd", {})
        holiday_temp = data.get(f"{self.coordinator.heating_circuit}.Z1HolidayTemp.value", "15")
        writes = [
            (self.coordinator.heating_circuit, "Z1HolidayStartPeriod", today),
            (self.coordinator.heating_circuit, "Z1HolidayEndPeriod", FAR_FUTURE),
            (self.coordinator.heating_circuit, "HwcHolidayStartPeriod", today),
            (self.coordinator.heating_circuit, "HwcHolidayEndPeriod", FAR_FUTURE),
        ]
        for circuit, name, value in writes:
            await ebus.write_register(circuit, name, value)
        if holiday_temp:
            await ebus.write_register(self.coordinator.heating_circuit, "Z1HolidayTemp", holiday_temp)
        await self.coordinator.async_request_refresh()

    # Reset holiday dates to unset, disable away mode
    async def async_turn_off(self, **kwargs: Any) -> None:
        ebus = self.coordinator.ebus
        if not ebus:
            return
        writes = [
            (self.coordinator.heating_circuit, "Z1HolidayStartPeriod", UNSET_DATE),
            (self.coordinator.heating_circuit, "Z1HolidayEndPeriod", UNSET_DATE),
            (self.coordinator.heating_circuit, "HwcHolidayStartPeriod", UNSET_DATE),
            (self.coordinator.heating_circuit, "HwcHolidayEndPeriod", UNSET_DATE),
        ]
        for circuit, name, value in writes:
            await ebus.write_register(circuit, name, value)
        await ebus.write_register(self.coordinator.heating_circuit, "Z1HolidayTemp", "15")
        await self.coordinator.async_request_refresh()


class HwcBoostSwitch(CoordinatorEntity[VaillantCoordinator], SwitchEntity):
    """Toggle DHW boost mode via HwcSFMode register."""

    # Initialize DHW boost switch with unique ID and DHW device
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_hwc_boost"
        self._attr_has_entity_name = True
        self._attr_name = "DHW Boost"
        self._attr_icon = "mdi:water-boiler"
        self._attr_device_info = coordinator.get_device_info("dhw")

    # True when HwcSFMode register equals "load"
    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data.get("ebusd", {})
        raw = data.get(f"{self.coordinator.heating_circuit}.HwcSFMode.value")
        if raw is None:
            return None
        return raw.strip().lower() == "load"

    # Write "load" to HwcSFMode to start DHW boost
    async def async_turn_on(self, **kwargs: Any) -> None:
        ebus = self.coordinator.ebus
        if not ebus:
            return
        await ebus.write_register(self.coordinator.heating_circuit, "HwcSFMode", "load")
        await self.coordinator.async_request_refresh()

    # Write "auto" to HwcSFMode to stop DHW boost
    async def async_turn_off(self, **kwargs: Any) -> None:
        ebus = self.coordinator.ebus
        if not ebus:
            return
        await ebus.write_register(self.coordinator.heating_circuit, "HwcSFMode", "auto")
        await self.coordinator.async_request_refresh()


class HwcAwayModeSwitch(CoordinatorEntity[VaillantCoordinator], SwitchEntity):
    """Toggle DHW holiday mode by setting HwcHolidayStartPeriod/EndPeriod."""

    # Initialize DHW away mode switch with unique ID and DHW device
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_hwc_away_mode"
        self._attr_has_entity_name = True
        self._attr_name = "DHW Away Mode"
        self._attr_icon = "mdi:water-boiler-off"
        self._attr_device_info = coordinator.get_device_info("dhw")

    # True when HwcHolidayStartPeriod/EndPeriod contain today
    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data.get("ebusd", {})
        start = data.get(f"{self.coordinator.heating_circuit}.HwcHolidayStartPeriod.value")
        end = data.get(f"{self.coordinator.heating_circuit}.HwcHolidayEndPeriod.value")
        if start is None or end is None:
            return None
        return _is_holiday_active(start, end)

    # Set DHW holiday from today to far future
    async def async_turn_on(self, **kwargs: Any) -> None:
        ebus = self.coordinator.ebus
        if not ebus:
            return
        today = _today_str()
        await ebus.write_register(self.coordinator.heating_circuit, "HwcHolidayStartPeriod", today)
        await ebus.write_register(self.coordinator.heating_circuit, "HwcHolidayEndPeriod", FAR_FUTURE)
        await self.coordinator.async_request_refresh()

    # Reset DHW holiday dates to unset value
    async def async_turn_off(self, **kwargs: Any) -> None:
        ebus = self.coordinator.ebus
        if not ebus:
            return
        await ebus.write_register(self.coordinator.heating_circuit, "HwcHolidayStartPeriod", UNSET_DATE)
        await ebus.write_register(self.coordinator.heating_circuit, "HwcHolidayEndPeriod", UNSET_DATE)
        await self.coordinator.async_request_refresh()
