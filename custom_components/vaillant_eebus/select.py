"""Select platform for Vaillant EEBUS HVAC mode control."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from vaillant.model import Capability

from .const import DOMAIN
from .coordinator import VaillantCoordinator

HVAC_MODES = ["heating", "cooling", "ventilation", "standby", "auto"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[VaillantHvacModeSelect] = []

    for cap in coordinator.capabilities.by_feature_type("HVAC"):
        etype = coordinator.capabilities.get_entity_type(list(cap.entity))
        if etype and "HVAC" in etype or "Room" in etype or "Zone" in etype:
            entities.append(VaillantHvacModeSelect(coordinator, cap, entry))

    async_add_entities(entities)


class VaillantHvacModeSelect(CoordinatorEntity[VaillantCoordinator], SelectEntity):
    """Select entity for HVAC operating mode."""

    def __init__(
        self,
        coordinator: VaillantCoordinator,
        cap: Capability,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._cap = cap
        entity_str = "_".join(str(e) for e in cap.entity)
        self._attr_unique_id = f"{entry.entry_id}_{entity_str}_f{cap.feature}_hvac_mode"
        self._attr_name = "HVAC Mode"
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info
        self._attr_options = HVAC_MODES

    @property
    def current_option(self) -> str | None:
        v = self._cap.value
        return str(v) if v else None

    async def async_select_option(self, option: str) -> None:
        server = {"entity": list(self._cap.entity), "feature": self._cap.feature}
        await self.coordinator.client.write_hvac_mode(server, option)
