"""Sensor platform for Vaillant EEBUS."""

from __future__ import annotations

import re
from functools import cache
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

from vaillant.model import Capability

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


@cache
def _guess_metadata(scope_type: str) -> dict[str, str]:
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


def _friendly_name(scope_type: str, cap: Capability, coordinator: VaillantCoordinator) -> str:
    parts = []
    etype = coordinator.capabilities.get_entity_type(list(cap.entity))
    if etype:
        parts.append(etype)
    name = SCOPE_TYPE_NAMES.get(scope_type)
    parts.append(name or scope_type or "Measurement")
    return " ".join(parts)


def _entity_key(entity: tuple[int, ...]) -> str:
    return "_".join(str(e) for e in entity)


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unknown"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    seen: set[str] = set()

    for desc in coordinator.client.measurement_descriptions:
        ent = desc.get("entity") or []
        feat = desc.get("feature", 0)
        mid = desc.get("measurementId", 0)
        uid = f"{entry.entry_id}_{_entity_key(tuple(ent))}_f{feat}_id{mid}"
        if uid not in seen:
            entities.append(VaillantMeasurementSensor(coordinator, desc, uid, entry))
            seen.add(uid)

    for cap in coordinator.capabilities.all:
        if cap.feature_type in ("NodeManagement", "DeviceClassification"):
            continue
        if cap.feature_type == "Measurement" or cap.role != "server":
            continue
        uid = f"{entry.entry_id}_{_entity_key(cap.entity)}_f{cap.feature}_{cap.feature_type}"
        if uid not in seen:
            entities.append(VaillantSensor(coordinator, cap, uid, entry))
            seen.add(uid)

    unknown = coordinator.client.unknown
    if unknown and unknown.total_discarded:
        uid = f"{entry.entry_id}_unknown_features"
        entities.append(VaillantUnknownFeaturesSensor(coordinator, uid, entry))

    async_add_entities(entities)


class VaillantSensor(CoordinatorEntity[VaillantCoordinator], SensorEntity):
    """Sensor backed by a single capability (EC, Setpoint, HVAC, SmartEnergy)."""

    def __init__(
        self,
        coordinator: VaillantCoordinator,
        cap: Capability,
        unique_id: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._cap = cap
        self._attr_unique_id = unique_id
        self._attr_name = _friendly_name(cap.feature_type or "", cap, coordinator)
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info

        scope_type = cap.scope_type or cap.feature_type or ""
        metadata = SCOPE_TYPE_MAP.get(scope_type) or _guess_metadata(scope_type)
        self._attr_device_class = metadata["device_class"]
        self._attr_state_class = metadata["state_class"]
        self._attr_native_unit_of_measurement = cap.unit

    @property
    def native_value(self) -> float | int | None:
        return self._cap.value

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.client.connected


class VaillantMeasurementSensor(CoordinatorEntity[VaillantCoordinator], SensorEntity):
    """Sensor backed by a single measurement description ID."""

    def __init__(
        self,
        coordinator: VaillantCoordinator,
        desc: dict[str, Any],
        unique_id: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._desc = desc
        self._attr_unique_id = unique_id
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info

        ent = desc.get("entity", [])
        feat = desc.get("feature", 0)
        mid = desc.get("measurementId", 0)
        self._object_id = _slug(
            f"{desc.get('scopeType') or 'unknown'}_e{'_'.join(str(x) for x in ent)}"
            f"_f{feat}_id{mid}"
        )
        scope_type = desc.get("scopeType") or ""
        metadata = SCOPE_TYPE_MAP.get(scope_type) or _guess_metadata(scope_type)
        self._attr_device_class = metadata["device_class"]
        self._attr_state_class = metadata["state_class"]
        self._attr_native_unit_of_measurement = desc.get("unit")

        etype = coordinator.capabilities.get_entity_type(ent) or ""
        name = SCOPE_TYPE_NAMES.get(scope_type) or scope_type or f"id{mid}"
        self._attr_name = f"{etype} {name}".strip()

    @property
    def native_value(self) -> float | int | None:
        entry = self.coordinator.client.latest_measurements.get(self._object_id)
        if isinstance(entry, dict):
            val = entry.get("value")
            return val if isinstance(val, (int, float)) else None
        return None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.client.connected


class VaillantUnknownFeaturesSensor(CoordinatorEntity[VaillantCoordinator], SensorEntity):
    """Diagnostic sensor showing count of unknown/unhandled EEBUS feature types."""

    def __init__(
        self,
        coordinator: VaillantCoordinator,
        unique_id: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_name = "Unknown Features"
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> int:
        return self.coordinator.client.unknown.total_discarded

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        features = self.coordinator.client.unknown.unknown_feature_types
        last = self.coordinator.client.unknown.last_unknown
        attrs = dict(features)
        if last:
            attrs["last_unknown"] = last
        return attrs
