"""Number platform for Vaillant EEBUS writable setpoints."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from vaillant.model import Capability

from .const import DOMAIN
from .coordinator import VaillantCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[VaillantSetpointNumber] = []

    for cap in coordinator.capabilities.by_feature_type("SetpointServer"):
        etype = coordinator.capabilities.get_entity_type(list(cap.entity))
        if etype and "DHW" in etype:
            entities.append(VaillantSetpointNumber(coordinator, cap, entry))

    async_add_entities(entities)


class VaillantSetpointNumber(CoordinatorEntity[VaillantCoordinator], NumberEntity):
    """Number entity for a temperature setpoint."""

    def __init__(
        self,
        coordinator: VaillantCoordinator,
        cap: Capability,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._cap = cap
        entity_str = "_".join(str(e) for e in cap.entity)
        self._attr_unique_id = f"{entry.entry_id}_{entity_str}_f{cap.feature}_setpoint"
        self._attr_name = "DHW Target Temperature"
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info
        self._attr_native_min_value = 35.0
        self._attr_native_max_value = 65.0
        self._attr_native_step = 1.0
        self._attr_native_unit_of_measurement = "°C"

    @property
    def native_value(self) -> float | None:
        v = self._cap.value
        if isinstance(v, (int, float)):
            return float(v)
        return None

    async def async_set_native_value(self, value: float) -> None:
        server = {"entity": list(self._cap.entity), "feature": self._cap.feature}
        await self.coordinator.client.write_setpoint(server, value)
