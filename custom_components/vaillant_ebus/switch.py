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

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Turn switch on by writing "1" to ebusd
        await self._write("1")

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Turn switch off by writing "0" to ebusd
        await self._write("0")

    # Write value to ebusd and trigger refresh
    async def _write(self, value: str) -> None:
        if not self.coordinator.ebusd_backend:
            return
        result = await self.coordinator.ebusd_backend.async_write(
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
        start = data.get("ctlv2.Z1HolidayStartPeriod.value")
        end = data.get("ctlv2.Z1HolidayEndPeriod.value")
        if start is None or end is None:
            return None
        return _is_holiday_active(start, end)

    # Set holiday dates from today to far future, enable away mode
    async def async_turn_on(self, **kwargs: Any) -> None:
        backend = self.coordinator.ebusd_backend
        if not backend:
            return
        today = _today_str()
        data = self.coordinator.data.get("ebusd", {})
        holiday_temp = data.get("ctlv2.Z1HolidayTemp.value", "15")
        writes = [
            ("ctlv2", "Z1HolidayStartPeriod", today),
            ("ctlv2", "Z1HolidayEndPeriod", FAR_FUTURE),
            ("ctlv2", "HwcHolidayStartPeriod", today),
            ("ctlv2", "HwcHolidayEndPeriod", FAR_FUTURE),
        ]
        for circuit, name, value in writes:
            await backend.async_write(circuit, name, value)
        if holiday_temp:
            await backend.async_write("ctlv2", "Z1HolidayTemp", holiday_temp)
        await self.coordinator.async_request_refresh()

    # Reset holiday dates to unset, disable away mode
    async def async_turn_off(self, **kwargs: Any) -> None:
        backend = self.coordinator.ebusd_backend
        if not backend:
            return
        writes = [
            ("ctlv2", "Z1HolidayStartPeriod", UNSET_DATE),
            ("ctlv2", "Z1HolidayEndPeriod", UNSET_DATE),
            ("ctlv2", "HwcHolidayStartPeriod", UNSET_DATE),
            ("ctlv2", "HwcHolidayEndPeriod", UNSET_DATE),
        ]
        for circuit, name, value in writes:
            await backend.async_write(circuit, name, value)
        await backend.async_write("ctlv2", "Z1HolidayTemp", "15")
        await self.coordinator.async_request_refresh()
