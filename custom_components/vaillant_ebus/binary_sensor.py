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
from .const import DOMAIN
from .coordinator import VaillantCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []

    for desc in coordinator.entities:
        if desc.entity_type != "binary_sensor":
            continue
        uid = f"{entry.entry_id}_{desc.unique_id}"
        entities.append(EbusdBinarySensor(coordinator, desc, uid, entry))

    entities.extend(
        [
            EbusdConnectionSensor(coordinator, entry),
            EbusdFaultSensor(coordinator, entry),
        ]
    )
    async_add_entities(entities)


BINARY_TRUE_VALUES = {"on", "1", "true", "yes", "running", "day"}


class EbusdBinarySensor(CoordinatorEntity[VaillantCoordinator], BinarySensorEntity):
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
        data = self.coordinator.data.get("ebusd", {})
        raw = data.get(self._desc.key)
        if raw is None:
            return None
        return raw.strip().lower() in BINARY_TRUE_VALUES

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class EbusdConnectionSensor(CoordinatorEntity[VaillantCoordinator], BinarySensorEntity):
    """Report local ebusd connectivity instead of cloud availability."""

    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_ebusd_online"
        self._attr_device_info = coordinator.get_device_info("hmu")

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class EbusdFaultSensor(CoordinatorEntity[VaillantCoordinator], BinarySensorEntity):
    """Aggregate current HMU and controller eBUS fault registers."""

    _attr_has_entity_name = True
    _attr_name = "Trouble Codes"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_fault_active"
        self._attr_device_info = coordinator.get_device_info("hmu")

    @property
    def is_on(self) -> bool:
        values = (
            self.coordinator.data.get("ebusd", {}).get("hmu.Currenterror.value"),
            self.coordinator.data.get("ebusd", {}).get("ctlv2.Currenterror.value"),
        )
        return any(
            value and any(part.strip() not in {"", "-"} for part in str(value).split(";"))
            for value in values
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
