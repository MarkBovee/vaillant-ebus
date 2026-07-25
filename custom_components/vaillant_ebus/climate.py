"""Climate platform for the primary heating zone."""

from __future__ import annotations

import logging
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

_LOGGER = logging.getLogger(__name__)

ZONE = "z1"
CIRCUIT = "ctlv2"
ROOM_TEMPERATURE = f"{CIRCUIT}.Z1RoomTemp.value"
TARGET_TEMPERATURE = f"{CIRCUIT}.Z1ActualRoomTempDesired.value"
OPERATION_MODE = f"{CIRCUIT}.Z1OpMode.value"
DAY_TEMPERATURE = f"{CIRCUIT}.Z1DayTemp.value"
NIGHT_TEMPERATURE = f"{CIRCUIT}.Z1NightTemp.value"
PUMP_STATUS = f"{CIRCUIT}.Hc1PumpStatus.value"
COMPRESSOR_STATUS = "hmu.RunDataStatuscode.value"
SET_MODE = "hmu.SetMode.value"
COOLING_TARGET = f"{CIRCUIT}.Z1CoolingTemp.value"
MIN_COOLING_TEMP = f"{CIRCUIT}.Hc1MinCoolingTempDesired.value"


# Get string value from coordinator data by key
def _value(coordinator: VaillantCoordinator, key: str) -> str | None:
    value = coordinator.data.get("ebusd", {}).get(key)
    return str(value) if value is not None else None


# Safely convert string to float, return None on failure
def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# Check if SetMode indicates cooling is configured (like away mode toggle)
def _is_cooling_enabled(coordinator: VaillantCoordinator) -> bool:
    raw = _value(coordinator, SET_MODE)
    if raw is None:
        return False
    fields = raw.split(";")
    if len(fields) < 10:
        return False
    try:
        return float(fields[1]) > 0 and fields[9] == "1"
    except (TypeError, ValueError):
        return False


# Check if coordinator data indicates cooling is active (prerun, compressor, or configured)
def _is_cooling(coordinator: VaillantCoordinator) -> bool:
    status = _value(coordinator, COMPRESSOR_STATUS)
    if status is not None and "cool" in status.lower():
        return True
    return _is_cooling_enabled(coordinator)


# Map Vaillant operation mode to HA HVACMode
def _hvac_mode(value: str | None, coordinator: VaillantCoordinator | None = None) -> HVACMode | None:
    if coordinator is not None and _is_cooling(coordinator):
        return HVACMode.COOL
    return {
        "off": HVACMode.OFF,
        "auto": HVACMode.AUTO,
        "day": HVACMode.HEAT,
        "night": HVACMode.HEAT,
    }.get((value or "").lower())


# Create the Z1 climate entity
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
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
    _attr_preset_modes = ["day", "night"]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5
    _attr_max_temp = 30
    _attr_target_temperature_step = 0.5

    # Initialize Z1 climate entity
    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_climate_z1"
        self._attr_device_info = coordinator.get_device_info(ZONE)
        self._optimistic_hvac_mode: HVACMode | None = None
        self._last_write_error: str = ""

    @property
    def current_temperature(self) -> float | None:
        # Return current room temperature
        return _float(_value(self.coordinator, ROOM_TEMPERATURE))

    @property
    def target_temperature(self) -> float | None:
        # Return cooling setpoint when in COOL mode
        if self.hvac_mode == HVACMode.COOL:
            return _float(_value(self.coordinator, COOLING_TARGET))
        value = _float(_value(self.coordinator, TARGET_TEMPERATURE))
        if value is not None and 5 <= value <= 30:
            return value
        if self.preset_mode == "night":
            return _float(_value(self.coordinator, NIGHT_TEMPERATURE))
        return _float(_value(self.coordinator, DAY_TEMPERATURE))

    @property
    def target_temperature_step(self) -> float:
        # Return fixed 0.5C step for temperature adjustment
        return 0.5

    @property
    def supported_features(self) -> ClimateEntityFeature:
        # Return PRESET_MODE and TARGET_TEMPERATURE when setpoint known
        features = ClimateEntityFeature.PRESET_MODE
        if self.target_temperature is not None:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

    @property
    def hvac_mode(self) -> HVACMode | None:
        # Return optimistic state first, then fall back to coordinator data
        if self._optimistic_hvac_mode is not None:
            return self._optimistic_hvac_mode
        return _hvac_mode(_value(self.coordinator, OPERATION_MODE), self.coordinator)

    @property
    def hvac_action(self) -> HVACAction | None:
        # Return COOLING, HEATING, or IDLE based on compressor and pump state
        if _is_cooling(self.coordinator):
            return HVACAction.COOLING
        value = (_value(self.coordinator, PUMP_STATUS) or "").lower()
        if value in {"on", "1", "true"}:
            return HVACAction.HEATING
        return HVACAction.IDLE if value else None

    @property
    def preset_mode(self) -> str | None:
        # Return day/night preset from operation mode
        mode = (_value(self.coordinator, OPERATION_MODE) or "").lower()
        return mode if mode in self.preset_modes else None

    @property
    def available(self) -> bool:
        # Entity available when coordinator updates succeed
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        # Expose last write error for debugging
        if self._last_write_error:
            return {"last_write_error": self._last_write_error}
        return None

    # Write temperature setpoint to ebusd (cooling or heating)
    async def async_set_temperature(self, **kwargs: Any) -> None:
        value = kwargs.get(ATTR_TEMPERATURE)
        if value is not None:
            if self.hvac_mode == HVACMode.COOL:
                await self._write("Z1CoolingTemp", str(value))
            else:
                name = "Z1NightTemp" if self.preset_mode == "night" else "Z1DayTemp"
                await self._write(name, str(value))

    # Override coordinator update to preserve optimistic state until confirmed
    def _handle_coordinator_update(self) -> None:
        # Reconcile optimistic state with fresh coordinator data
        if self._optimistic_hvac_mode is not None:
            confirmed = _hvac_mode(_value(self.coordinator, OPERATION_MODE), self.coordinator)
            if confirmed == self._optimistic_hvac_mode:
                self._optimistic_hvac_mode = None
        super()._handle_coordinator_update()

    # Write HVAC mode to ebusd via SetMode (cooling) and Z1OpMode (heating)
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._optimistic_hvac_mode = hvac_mode
        self.async_write_ha_state()
        ok = True
        try:
            if hvac_mode == HVACMode.COOL:
                temp = str(_float(_value(self.coordinator, MIN_COOLING_TEMP)) or 17)
                ok = await self._write_raw("hmu", "SetMode", f"auto;{temp};-;-;1;1;1;0;0;1")
            elif hvac_mode == HVACMode.HEAT:
                ok1 = await self._write_raw("hmu", "SetMode", "auto;0.0;-;-;1;1;1;0;0;0")
                ok2 = await self._write("Z1OpMode", "auto")
                ok = ok1 and ok2
            elif hvac_mode == HVACMode.AUTO:
                ok = await self._write("Z1OpMode", "auto")
            elif hvac_mode == HVACMode.OFF:
                ok = await self._write("Z1OpMode", "off")
        except Exception as exc:
            _LOGGER.exception("set_hvac_mode failed: %s", exc)
            ok = False
        if not ok:
            self._optimistic_hvac_mode = None
            self.async_write_ha_state()

    # Write day/night preset mode to ebusd
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self.preset_modes:
            raise ValueError(f"Unsupported preset: {preset_mode}")
        await self._write("Z1OpMode", preset_mode)

    # Write a CTLV2 register value and trigger refresh
    async def _write(self, name: str, value: str) -> bool:
        return await self._write_raw(CIRCUIT, name, value)

    # Write any circuit register and trigger refresh
    async def _write_raw(self, circuit: str, name: str, value: str) -> bool:
        backend = self.coordinator.ebusd_backend
        if not backend:
            self._last_write_error = "backend is None"
            return False
        result = await backend.async_write(circuit, name, value)
        if result.success:
            self._last_write_error = ""
            await self.coordinator.async_request_refresh()
        else:
            self._last_write_error = result.error_message or "unknown error"
        return result.success
