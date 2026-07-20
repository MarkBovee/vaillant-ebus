"""Climate platform for the primary heating zone."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VaillantCoordinator

ZONE = "z1"
CIRCUIT = "ctlv2"
ROOM_TEMPERATURE = f"{CIRCUIT}.Z1RoomTemp.value"
TARGET_TEMPERATURE = f"{CIRCUIT}.Z1ActualRoomTempDesired.value"
OPERATION_MODE = f"{CIRCUIT}.Z1OpMode.value"
DAY_TEMPERATURE = f"{CIRCUIT}.Z1DayTemp.value"
NIGHT_TEMPERATURE = f"{CIRCUIT}.Z1NightTemp.value"
PUMP_STATUS = f"{CIRCUIT}.Hc1PumpStatus.value"


def _value(coordinator: VaillantCoordinator, key: str) -> str | None:
    value = coordinator.data.get("ebusd", {}).get(key)
    return str(value) if value is not None else None


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _hvac_mode(value: str | None) -> HVACMode | None:
    return {
        "off": HVACMode.OFF,
        "auto": HVACMode.AUTO,
        "day": HVACMode.HEAT,
        "night": HVACMode.HEAT,
    }.get((value or "").lower())


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EbusdClimate(coordinator, entry)])


class EbusdClimate(CoordinatorEntity[VaillantCoordinator], ClimateEntity):
    """Aggregated climate control for primary zone Z1."""

    _attr_has_entity_name = True
    _attr_name = "Home"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    _attr_preset_modes = ["day", "night"]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5
    _attr_max_temp = 30
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_climate_z1"
        self._attr_device_info = coordinator.get_device_info(ZONE)

    @property
    def current_temperature(self) -> float | None:
        return _float(_value(self.coordinator, ROOM_TEMPERATURE))

    @property
    def target_temperature(self) -> float | None:
        value = _float(_value(self.coordinator, TARGET_TEMPERATURE))
        if value is not None and 5 <= value <= 30:
            return value
        if self.preset_mode == "night":
            return _float(_value(self.coordinator, NIGHT_TEMPERATURE))
        return _float(_value(self.coordinator, DAY_TEMPERATURE))

    @property
    def target_temperature_step(self) -> float:
        return 0.5

    @property
    def supported_features(self) -> ClimateEntityFeature:
        features = ClimateEntityFeature.PRESET_MODE
        if self.target_temperature is not None:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

    @property
    def hvac_mode(self) -> HVACMode | None:
        return _hvac_mode(_value(self.coordinator, OPERATION_MODE))

    @property
    def hvac_action(self) -> HVACAction | None:
        value = (_value(self.coordinator, PUMP_STATUS) or "").lower()
        if value in {"on", "1", "true"}:
            return HVACAction.HEATING
        return HVACAction.IDLE if value else None

    @property
    def preset_mode(self) -> str | None:
        mode = (_value(self.coordinator, OPERATION_MODE) or "").lower()
        return mode if mode in self.preset_modes else None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_set_temperature(self, **kwargs: Any) -> None:
        value = kwargs.get(ATTR_TEMPERATURE)
        if value is not None:
            name = "Z1NightTemp" if self.preset_mode == "night" else "Z1DayTemp"
            await self._write(name, str(value))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        values = {
            HVACMode.OFF: "off",
            HVACMode.HEAT: "day",
            HVACMode.AUTO: "auto",
        }
        await self._write("Z1OpMode", values[hvac_mode])

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self.preset_modes:
            raise ValueError(f"Unsupported preset: {preset_mode}")
        await self._write("Z1OpMode", preset_mode)

    async def _write(self, name: str, value: str) -> None:
        backend = self.coordinator.ebusd_backend
        if backend:
            result = await backend.        async_write(CIRCUIT, name, value)
            if result.success:
                await self.coordinator.async_request_refresh()
