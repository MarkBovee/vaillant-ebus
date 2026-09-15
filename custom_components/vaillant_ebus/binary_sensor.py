"""Binary sensor platform for Vaillant EBUS."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backend.entity_factory import EntityDescription
from .backend.models import derive_tank_presence, is_no_data_value
from .const import DOMAIN
from .coordinator import VaillantCoordinator


# Create binary sensor entities plus connection and fault sensors
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _build(descriptions: list[EntityDescription]) -> list[BinarySensorEntity]:
        entities: list[BinarySensorEntity] = []
        seen: set[str] = set()
        for desc in descriptions:
            if desc.entity_type != "binary_sensor":
                continue
            uid = f"{entry.entry_id}_{desc.unique_id}"
            if uid in seen:
                continue
            seen.add(uid)
            entities.append(EbusdBinarySensor(coordinator, desc, uid, entry))
        return entities

    async_add_entities(_build(coordinator.entities))
    # The DHW tank-present sensor is derived from the controller's storage-temp
    # sentinel, not a register read. It reports unknown until the register
    # carries data, and is always created so discovery can populate it late.
    async_add_entities([EbusdTankPresentSensor(coordinator, entry)])
    added_fixed = False

    def _ensure_fixed_entities() -> None:
        nonlocal added_fixed
        if added_fixed or coordinator.heat_pump_circuit is None:
            return
        async_add_entities([EbusdConnectionSensor(coordinator, entry), EbusdFaultSensor(coordinator, entry)])
        added_fixed = True

    _ensure_fixed_entities()
    coordinator.register_post_discovery_callback(_ensure_fixed_entities)
    coordinator.register_entity_adder("binary_sensor", lambda descriptions: async_add_entities(_build(descriptions)))


BINARY_TRUE_VALUES = {"on", "1", "true", "yes", "running", "day"}


class EbusdBinarySensor(CoordinatorEntity[VaillantCoordinator], BinarySensorEntity):
    # Initialize binary sensor from entity description
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

        low_name = (desc.name or "").lower()
        if any(x in low_name for x in ("error", "alarm", "fault", "Currenterror")):
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        elif any(x in low_name for x in ("pump", "compressor", "running", "StatusCirPump")):
            self._attr_device_class = BinarySensorDeviceClass.RUNNING
        elif "heat" in low_name or "hc" in low_name:
            self._attr_device_class = BinarySensorDeviceClass.HEAT
        elif "cool" in low_name:
            self._attr_device_class = BinarySensorDeviceClass.COLD

    @property
    def is_on(self) -> bool | None:
        # Return binary state; ebusd sentinels mean "unknown", not off.
        data = self.coordinator.data.get("ebusd", {})
        raw = data.get(self._desc.key)
        if raw is None or is_no_data_value(str(raw)):
            return None
        return raw.strip().lower() in BINARY_TRUE_VALUES

    @property
    def available(self) -> bool:
        # Entity available when coordinator updates succeed
        return self.coordinator.last_update_success


class EbusdConnectionSensor(CoordinatorEntity[VaillantCoordinator], BinarySensorEntity):
    """Report local ebusd connectivity instead of cloud availability."""

    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    # Initialize connection sensor with unique ID and device info
    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_ebusd_online"
        self._attr_device_info = coordinator.get_device_info(coordinator.heat_pump_circuit)

    @property
    def is_on(self) -> bool:
        # True when coordinator last update succeeded
        return self.coordinator.last_update_success


class EbusdFaultSensor(CoordinatorEntity[VaillantCoordinator], BinarySensorEntity):
    """Aggregate current HMU and controller eBUS fault registers."""

    _attr_has_entity_name = True
    _attr_name = "Trouble Codes"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    # Initialize fault sensor with unique ID and device info
    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_fault_active"
        self._attr_device_info = coordinator.get_device_info(coordinator.heat_pump_circuit)

    # True when either HMU or CTLV2 has active error codes
    @property
    def is_on(self) -> bool:
        c = self.coordinator.heating_circuit
        hp = self.coordinator.heat_pump_circuit
        if c is None or hp is None:
            return False
        values = (
            self.coordinator.data.get("ebusd", {}).get(f"{hp}.Currenterror.value"),
            self.coordinator.data.get("ebusd", {}).get(f"{c}.Currenterror.value"),
        )
        return any(value and any(part.strip() not in {"", "-"} for part in str(value).split(";")) for value in values)

    @property
    def available(self) -> bool:
        # Entity available when coordinator updates succeed
        return self.coordinator.last_update_success


class EbusdTankPresentSensor(CoordinatorEntity[VaillantCoordinator], BinarySensorEntity):
    """Derived DHW storage-tank presence from the controller storage-temperature sentinel.

    On buses without a connected tank the controller's HwcStorageTemp poll
    returns an empty/NaN sentinel; a real tank reports a live temperature. This
    exposes that as a tri-state binary sensor (on = tank present, off = no tank,
    unknown = no data yet), attached to the logical DHW device.
    """

    _attr_has_entity_name = True
    _attr_name = "DHW Tank Present"
    _attr_icon = "mdi:water-boiler"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_dhw_tank_present"
        self._attr_device_info = coordinator.get_device_info("dhw")

    @property
    def is_on(self) -> bool | None:
        circuit = self.coordinator.heating_circuit
        if circuit is None:
            return None
        data = (self.coordinator.data or {}).get("ebusd", {})
        return derive_tank_presence(data, circuit)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.is_on is not None
