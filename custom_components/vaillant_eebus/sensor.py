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
    seen: set[str] = set()

    for object_id, data in coordinator.data.items():
        scope = data.get("scopeType", "unknown")
        if scope not in seen:
            entities.append(VaillantSensor(coordinator, scope, data, entry))
            seen.add(scope)

    for scope, meta in coordinator.measurement_scopes.items():
        if scope not in seen:
            entities.append(VaillantSensor(coordinator, scope, meta, entry))
            seen.add(scope)

    async_add_entities(entities)


class VaillantSensor(CoordinatorEntity[VaillantCoordinator], SensorEntity):
    """Sensor representing a Vaillant measurement."""

    def __init__(
        self,
        coordinator: VaillantCoordinator,
        scope_type: str,
        data: dict[str, Any],
        entry: ConfigEntry,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._scope_type = scope_type
        self._attr_unique_id = f"{entry.entry_id}_{scope_type}"
        self._attr_name = _friendly_name(scope_type)
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info

        metadata = _guess_metadata(scope_type, str(data.get("unit", "")))
        self._attr_device_class = metadata["device_class"]
        self._attr_state_class = metadata["state_class"]
        self._attr_native_unit_of_measurement = data.get("unit")

    @property
    def native_value(self) -> float | int | None:
        """Return the sensor value."""
        for _object_id, entry_data in self.coordinator.data.items():
            if entry_data.get("scopeType") == self._scope_type:
                return entry_data.get("value")
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.client.connected
