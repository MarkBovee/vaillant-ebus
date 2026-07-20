"""Select platform for Vaillant EEBUS."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VaillantCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []

    for desc in coordinator.entities:
        if desc.entity_type != "select":
            continue
        uid = f"{entry.entry_id}_{desc.unique_id}"
        entities.append(EbusdSelect(coordinator, desc, uid, entry))

    async_add_entities(entities)


class EbusdSelect(CoordinatorEntity[VaillantCoordinator], SelectEntity):
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        desc: Any,
        unique_id: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._desc = desc
        self._attr_unique_id = unique_id
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.get_device_info(desc.device_circuit)
        self._attr_name = desc.meta.friendly_name or desc.name
        self._attr_options = desc.meta.options or []
        if desc.meta.icon:
            self._attr_icon = desc.meta.icon

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data.get("ebusd", {})
        raw = data.get(self._desc.key)
        return str(raw) if raw is not None else None

    async def async_select_option(self, option: str) -> None:
        if self.coordinator.ebusd_backend:
            result = await self.coordinator.ebusd_backend.async_write(
                self._desc.circuit,
                self._desc.name,
                option,
            )
            if result.success:
                await self.coordinator.async_request_refresh()
