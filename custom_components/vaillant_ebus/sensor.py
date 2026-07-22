"""Sensor platform for Vaillant eBUS."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backend.entity_factory import EntityDescription
from .const import DOMAIN
from .coordinator import VaillantCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    seen: set[str] = set()

    for desc in coordinator.entities:
        if desc.entity_type not in ("sensor", ""):
            continue
        uid = f"{entry.entry_id}_{desc.unique_id}"
        if uid not in seen:
            entities.append(EbusdSensor(coordinator, desc, uid, entry))
            seen.add(uid)

    async_add_entities(entities)


class EbusdSensor(CoordinatorEntity[VaillantCoordinator], SensorEntity):
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
        if desc.meta.device_class:
            self._attr_device_class = desc.meta.device_class
        if desc.meta.state_class:
            self._attr_state_class = desc.meta.state_class
        if desc.meta.unit:
            self._attr_native_unit_of_measurement = desc.meta.unit
        if desc.meta.icon:
            self._attr_icon = desc.meta.icon
        if desc.meta.entity_category:
            self._attr_entity_category = EntityCategory(desc.meta.entity_category)

    @property
    def native_value(self) -> float | str | None:
        data = self.coordinator.data.get("ebusd", {})
        raw = data.get(self._desc.key)
        if raw is None or raw in ("-", "no data stored", "empty"):
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return str(raw)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
