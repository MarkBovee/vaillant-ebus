"""Datetime platform for the quick-veto end timestamp."""

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
# Create the quick-veto timestamp entity.
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EbusdQuickVetoEndEntity(coordinator, entry)])


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
        if c is None:
            return None
        end_date = data.get(f"{c}.Z1QuickVetoEndDate.value")
        end_time = data.get(f"{c}.Z1QuickVetoEndTime.value")
        if not end_date or not end_time or end_date in {"01.01.2015", "01.01.2019"}:
            return None
        try:
            naive = datetime.strptime(f"{end_date} {end_time}", f"{DATE_FMT} {TIME_FMT}")
            return naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        except (ValueError, TypeError):
            return None
