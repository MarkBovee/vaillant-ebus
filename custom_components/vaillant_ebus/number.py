"""Number platform for Vaillant EBUS."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backend.entity_factory import EntityDescription
from .const import DOMAIN
from .coordinator import VaillantCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []

    for desc in coordinator.entities:
        if desc.entity_type != "number":
            continue
        uid = f"{entry.entry_id}_{desc.unique_id}"
        entities.append(EbusdNumber(coordinator, desc, uid, entry))

    async_add_entities(entities)


class EbusdNumber(CoordinatorEntity[VaillantCoordinator], NumberEntity):
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
        self._attr_device_info = coordinator.get_device_info(desc.device_circuit)
        self._attr_name = desc.meta.friendly_name or desc.name
        self._attr_native_min_value = desc.meta.min_value or 0
        self._attr_native_max_value = desc.meta.max_value or 100
        self._attr_native_step = desc.meta.step or 1
        if desc.meta.unit:
            self._attr_native_unit_of_measurement = desc.meta.unit
        if desc.meta.icon:
            self._attr_icon = desc.meta.icon

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data.get("ebusd", {})
        raw = data.get(self._desc.key)
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        if value < self._attr_native_min_value or value > self._attr_native_max_value:
            raise ValueError(
                f"Value {value} not in [{self._attr_native_min_value}, {self._attr_native_max_value}]"
            )
        if not self.coordinator.ebusd_backend:
            return
        result = await self.coordinator.ebusd_backend.async_write(
            self._desc.circuit,
            self._desc.name,
            str(value),
        )
        if result.success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.warning("Write failed for %s: %s", self._desc.key, result.error_message)
