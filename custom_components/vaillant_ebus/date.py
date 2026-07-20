"""Date platform for the heating-zone holiday period."""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VaillantCoordinator

ZONE = "z1"
CIRCUIT = "ctlv2"
HOLIDAY_DATES = {
    "Holiday Start": "Z1HolidayStartPeriod",
    "Holiday End": "Z1HolidayEndPeriod",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        EbusdDate(coordinator, entry, name, register)
        for name, register in HOLIDAY_DATES.items()
    )


class EbusdDate(CoordinatorEntity[VaillantCoordinator], DateEntity):
    """Read and write a Vaillant date register in DD.MM.YYYY format."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
        name: str,
        register: str,
    ) -> None:
        super().__init__(coordinator)
        self._register = register
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_date_{register.lower()}"
        self._attr_device_info = coordinator.get_device_info(ZONE)

    @property
    def native_value(self) -> date | None:
        raw = self.coordinator.data.get("ebusd", {}).get(f"{CIRCUIT}.{self._register}.value")
        try:
            return datetime.strptime(str(raw), "%d.%m.%Y").date()
        except (TypeError, ValueError):
            return None

    async def async_set_value(self, value: date) -> None:
        backend = self.coordinator.ebusd_backend
        if backend:
            result = await backend.async_write(CIRCUIT, self._register, value.strftime("%d.%m.%Y"))
            if result.success:
                await self.coordinator.async_request_refresh()
