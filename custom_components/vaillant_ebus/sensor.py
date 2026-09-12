"""Sensor platform for Vaillant eBUS."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backend.entity_factory import EntityDescription
from .backend.models import derive_operating_state
from .const import DOMAIN
from .coordinator import VaillantCoordinator


# Create sensor entities from coordinator entity descriptions
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _build(descriptions: list[EntityDescription]) -> list[SensorEntity]:
        entities: list[SensorEntity] = []
        seen: set[str] = set()
        for desc in descriptions:
            if desc.entity_type not in ("sensor", ""):
                continue
            uid = f"{entry.entry_id}_{desc.unique_id}"
            if uid not in seen:
                entities.append(EbusdSensor(coordinator, desc, uid, entry))
                seen.add(uid)
        return entities

    async_add_entities(_build(coordinator.entities))
    coordinator.register_entity_adder("sensor", lambda descriptions: async_add_entities(_build(descriptions)))

    # The Energy Manager State is derived, not a register read. Create it for a
    # discovered heat pump only, so boiler-only buses never grow a phantom
    # entity. It reports `unavailable` until a status field carries data.
    heat_pump_circuit = coordinator.heat_pump_circuit
    if heat_pump_circuit is not None:
        async_add_entities([EbusdEnergyManagerState(coordinator, entry, heat_pump_circuit)])


class EbusdEnergyManagerState(CoordinatorEntity[VaillantCoordinator], SensorEntity):
    """Derived operating state: Heating / DHW / Cooling / Standby / Defrost."""

    _attr_has_entity_name = True
    _attr_name = "Energy Manager State"
    _attr_icon = "mdi:heat-pump-outline"

    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
        heat_pump_circuit: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_energy_manager_state"
        self._attr_device_info = coordinator.get_device_info(heat_pump_circuit)
        self._fallback_circuit = heat_pump_circuit

    def _state(self) -> str | None:
        # Re-resolve the heat-pump circuit so late discovery or a circuit rename
        # keeps the state sensor on the device that actually reports the status.
        circuit = self.coordinator.heat_pump_circuit or self._fallback_circuit
        data = (self.coordinator.data or {}).get("ebusd", {})
        return derive_operating_state(data, circuit)

    @property
    def native_value(self) -> str | None:
        return self._state()

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._state() is not None


class EbusdSensor(CoordinatorEntity[VaillantCoordinator], SensorEntity, RestoreEntity):
    # Initialize sensor entity from entity description
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
        if desc.meta.device_class:
            self._attr_device_class = desc.meta.device_class
        if desc.meta.state_class:
            self._attr_state_class = desc.meta.state_class
        if desc.meta.unit:
            self._attr_native_unit_of_measurement = desc.meta.unit
        if desc.meta.icon:
            self._attr_icon = desc.meta.icon
        if desc.meta.entity_category:
            cat = desc.meta.entity_category
            self._attr_entity_category = EntityCategory(cat) if cat != "config" else None

    # Restore last known state from HA registry on startup
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable", ""):
            self._cached_value = last.state

    @property
    def native_value(self) -> float | str | None:
        data = self.coordinator.data.get("ebusd", {})
        raw = data.get(self._desc.key)
        if raw is None or raw in ("-", "empty", "") or (raw and "no data stored" in raw):
            return getattr(self, "_cached_value", None)
        # Numeric registers become floats; unitless text registers (status
        # codes) keep their raw string so the UI still shows something useful.
        val: float | str | None
        try:
            val = float(raw)
        except ValueError, TypeError:
            if getattr(self, "_attr_native_unit_of_measurement", None):
                val = None
            else:
                val = str(raw) if raw else None
        if val is not None:
            self._cached_value = val
        return val

    @property
    def available(self) -> bool:
        # Entity available when coordinator updates succeed
        return self.coordinator.last_update_success
