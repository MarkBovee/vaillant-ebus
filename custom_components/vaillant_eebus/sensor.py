"""Sensor platform for Vaillant EEBUS."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VaillantCoordinator

SCOPE_TYPE_MAP: dict[str, dict[str, str]] = {
    "acCurrent": {
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "acEnergyConsumed": {
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "acEnergyProduced": {
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "acFrequency": {
        "device_class": SensorDeviceClass.FREQUENCY,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "acPower": {
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "outsideAirTemperature": {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dhwTemperature": {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "roomAirTemperature": {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "acPowerTotal": {
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "acVoltage": {
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "compressorFrequency": {
        "device_class": SensorDeviceClass.FREQUENCY,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "waterPressure": {
        "device_class": SensorDeviceClass.PRESSURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
}

SCOPE_TYPE_NAMES: dict[str, str] = {
    "acCurrent": "AC Current",
    "acEnergyConsumed": "AC Energy Consumed",
    "acEnergyProduced": "AC Energy Produced",
    "acFrequency": "AC Frequency",
    "acPower": "AC Power",
    "outsideAirTemperature": "Outside Temperature",
    "dhwTemperature": "DHW Temperature",
    "roomAirTemperature": "Room Temperature",
    "acPowerTotal": "Compressor Power",
    "acVoltage": "AC Voltage",
    "compressorFrequency": "Compressor Frequency",
    "waterPressure": "Water Pressure",
}


def _guess_metadata(scope_type: str, unit: str) -> dict[str, str]:
    """Guess HA metadata from scope type."""
    s = (scope_type or "").lower()
    if "current" in s:
        return {"device_class": SensorDeviceClass.CURRENT, "state_class": SensorStateClass.MEASUREMENT}
    if "voltage" in s:
        return {"device_class": SensorDeviceClass.VOLTAGE, "state_class": SensorStateClass.MEASUREMENT}
    if "temperature" in s:
        return {"device_class": SensorDeviceClass.TEMPERATURE, "state_class": SensorStateClass.MEASUREMENT}
    if "power" in s:
        return {"device_class": SensorDeviceClass.POWER, "state_class": SensorStateClass.MEASUREMENT}
    if "energy" in s:
        return {"device_class": SensorDeviceClass.ENERGY, "state_class": SensorStateClass.TOTAL_INCREASING}
    if "frequency" in s:
        return {"device_class": SensorDeviceClass.FREQUENCY, "state_class": SensorStateClass.MEASUREMENT}
    if "pressure" in s:
        return {"device_class": SensorDeviceClass.PRESSURE, "state_class": SensorStateClass.MEASUREMENT}
    return {"device_class": "", "state_class": SensorStateClass.MEASUREMENT}


def _friendly_name(scope_type: str) -> str:
    """Return friendly name for scope type."""
    if name := SCOPE_TYPE_NAMES.get(scope_type):
        return name
    return scope_type or "Measurement"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[VaillantSensor] = []

    for object_id, data in coordinator.data.items():
        entities.append(VaillantSensor(coordinator, object_id, data, entry))

    async_add_entities(entities)


class VaillantSensor(CoordinatorEntity[VaillantCoordinator], SensorEntity):
    """Sensor representing a Vaillant measurement."""

    def __init__(
        self,
        coordinator: VaillantCoordinator,
        object_id: str,
        data: dict[str, Any],
        entry: ConfigEntry,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._object_id = object_id
        self._scope_type = data.get("scopeType", "unknown")
        self._attr_unique_id = f"{entry.entry_id}_{object_id}"
        self._attr_name = _friendly_name(self._scope_type)
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info

        metadata = _guess_metadata(self._scope_type, str(data.get("unit", "")))
        self._attr_device_class = metadata["device_class"]
        self._attr_state_class = metadata["state_class"]
        self._attr_native_unit_of_measurement = data.get("unit")

    @property
    def native_value(self) -> float | int | None:
        """Return the sensor value."""
        data = self.coordinator.data.get(self._object_id)
        if data is None:
            return None
        return data.get("value")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.client.connected
