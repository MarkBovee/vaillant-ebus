"""Climate platform for the primary heating zone."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import (
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_NONE,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EBUSD_TO_HA_HVAC, HA_TO_EBUSD_HVAC
from .coordinator import VaillantCoordinator

_LOGGER = logging.getLogger(__name__)

ZONE = "z1"
CIRCUIT = "ctlv2"
ROOM_TEMPERATURE = f"{CIRCUIT}.Z1RoomTemp.value"
TARGET_TEMPERATURE = f"{CIRCUIT}.Z1ActualRoomTempDesired.value"
OPERATION_MODE = f"{CIRCUIT}.Z1OpMode.value"
DAY_TEMPERATURE = f"{CIRCUIT}.Z1DayTemp.value"
NIGHT_TEMPERATURE = f"{CIRCUIT}.Z1NightTemp.value"
HC_STATUS = f"{CIRCUIT}.Hc1Status.value"
COMPRESSOR_STATUS = "hmu.RunDataStatuscode.value"
QUICK_VETO_TEMP = f"{CIRCUIT}.Z1QuickVetoTemp.value"
HOLIDAY_START = f"{CIRCUIT}.Z1HolidayStartPeriod.value"
HOLIDAY_END = f"{CIRCUIT}.Z1HolidayEndPeriod.value"

HEATING_STATES = frozenset({
    "heat_compressor_active",
    "heat_prerun",
    "heat_overrun",
    "heat_immersion_heater_active",
})
COOLING_STATES = frozenset({
    "cool_compressor_active",
    "cool_prerun",
    "cool_overrun",
})

DATE_FMT = "%d.%m.%Y"
HOLIDAY_RESET = "01.01.2015"


def _value(coordinator: VaillantCoordinator, key: str) -> str | None:
    value = coordinator.data.get("ebusd", {}).get(key)
    return str(value) if value is not None else None


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _hvac_mode(value: str | None) -> HVACMode | None:
    ha = EBUSD_TO_HA_HVAC.get((value or "").lower())
    return HVACMode(ha) if ha else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EbusdClimate(coordinator, entry), EbusdFlowTempRange(coordinator, entry)])


class EbusdClimate(CoordinatorEntity[VaillantCoordinator], ClimateEntity):

    _attr_has_entity_name = True
    _attr_name = "Home"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
    _attr_preset_modes = [PRESET_NONE, PRESET_BOOST, PRESET_AWAY]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5
    _attr_max_temp = 30
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_climate_z1"
        self._attr_device_info = coordinator.get_device_info(ZONE)
        self._optimistic_hvac_mode: HVACMode | None = None
        self._quick_veto_until: datetime | None = None

    @property
    def current_temperature(self) -> float | None:
        return _float(_value(self.coordinator, ROOM_TEMPERATURE))

    @property
    def target_temperature(self) -> float | None:
        if self.preset_mode == PRESET_BOOST:
            qv = _float(_value(self.coordinator, QUICK_VETO_TEMP))
            if qv is not None and 5 <= qv <= 30:
                return qv
        value = _float(_value(self.coordinator, TARGET_TEMPERATURE))
        if value is not None and 5 <= value <= 30:
            return value
        return _float(_value(self.coordinator, DAY_TEMPERATURE))

    @property
    def supported_features(self) -> ClimateEntityFeature:
        return (
            ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        if self._optimistic_hvac_mode is not None:
            return self._optimistic_hvac_mode
        return _hvac_mode(_value(self.coordinator, OPERATION_MODE))

    @property
    def hvac_action(self) -> HVACAction | None:
        hc = _float(_value(self.coordinator, HC_STATUS))
        zone_active = hc is not None and hc > 0
        if hc is None:
            pump = _value(self.coordinator, f"{CIRCUIT}.Hc1PumpStatus.value")
            zone_active = (pump or "").lower() in ("on", "1", "true", "yes", "running")
        comp = (_value(self.coordinator, COMPRESSOR_STATUS) or "").lower()
        global_heat = comp in HEATING_STATES
        global_cool = comp in COOLING_STATES
        if zone_active:
            if global_heat:
                return HVACAction.HEATING
            if global_cool:
                return HVACAction.COOLING
            if global_heat or global_cool:
                return HVACAction.IDLE
        mode = self.hvac_mode
        if mode == HVACMode.OFF:
            return HVACAction.OFF
        if global_heat:
            return HVACAction.HEATING
        if global_cool:
            return HVACAction.COOLING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        if self._quick_veto_until and self._quick_veto_until > datetime.now():
            return PRESET_BOOST
        h_start = _value(self.coordinator, HOLIDAY_START)
        h_end = _value(self.coordinator, HOLIDAY_END)
        if h_start and h_end and h_start != HOLIDAY_RESET:
            try:
                now = datetime.now().date()
                start = datetime.strptime(h_start, DATE_FMT).date()
                end = datetime.strptime(h_end, DATE_FMT).date()
                if start <= now <= end:
                    return PRESET_AWAY
            except ValueError:
                pass
        return PRESET_NONE

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._optimistic_hvac_mode = hvac_mode
        self.async_write_ha_state()
        if self.preset_mode == PRESET_BOOST:
            await self._cancel_quick_veto()
        ebusd_mode = HA_TO_EBUSD_HVAC.get(hvac_mode.value)
        if ebusd_mode is None:
            self._optimistic_hvac_mode = None
            self.async_write_ha_state()
            return
        ok = True
        try:
            ok = await self._write("Z1OpMode", ebusd_mode)
        except Exception as exc:
            _LOGGER.exception("set_hvac_mode failed: %s", exc)
            ok = False
        if not ok:
            self._optimistic_hvac_mode = None
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self._attr_preset_modes:
            raise ValueError(f"Unsupported preset: {preset_mode}")
        current = self.preset_mode
        if current == PRESET_BOOST and preset_mode != PRESET_BOOST:
            await self._cancel_quick_veto()
        if preset_mode == PRESET_BOOST and current != PRESET_BOOST:
            await self._start_quick_veto()
        if preset_mode == PRESET_AWAY and current != PRESET_AWAY:
            await self._start_holiday()
        elif preset_mode != PRESET_AWAY and current == PRESET_AWAY:
            await self._cancel_holiday()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        if self.preset_mode == PRESET_BOOST:
            await self._write("Z1QuickVetoTemp", str(temp))
        else:
            await self._write("Z1DayTemp", str(temp))

    async def async_turn_on(self) -> None:
        await self._write("Z1OpMode", "auto")

    async def async_turn_off(self) -> None:
        await self._write("Z1OpMode", "off")

    def _handle_coordinator_update(self) -> None:
        if self._quick_veto_until and self._quick_veto_until <= datetime.now():
            self._quick_veto_until = None
        if self._optimistic_hvac_mode is not None:
            confirmed = _hvac_mode(_value(self.coordinator, OPERATION_MODE))
            if confirmed == self._optimistic_hvac_mode:
                self._optimistic_hvac_mode = None
        super()._handle_coordinator_update()

    async def _cancel_quick_veto(self) -> None:
        self._quick_veto_until = None
        self.async_write_ha_state()
        day_temp = _float(_value(self.coordinator, DAY_TEMPERATURE))
        if day_temp is not None:
            await self._write("Z1QuickVetoTemp", str(day_temp))
        await self._write("Z1QuickVetoDuration", "0")

    async def _start_quick_veto(self, temp_override: float | None = None) -> None:
        if temp_override is not None:
            veto_temp = temp_override
        else:
            temp = _float(_value(self.coordinator, ROOM_TEMPERATURE))
            options = self.coordinator._entry.options
            veto_temp = options.get("quick_veto_temp")
            if veto_temp is None and temp is not None:
                veto_temp = round(temp, 1)
        if veto_temp is None:
            return
        options = self.coordinator._entry.options
        veto_duration = options.get("quick_veto_duration", 3)
        self._quick_veto_until = datetime.now() + timedelta(hours=veto_duration)
        await self._write("Z1QuickVetoTemp", str(veto_temp))
        await self._write("Z1QuickVetoDuration", str(veto_duration))
        self.async_write_ha_state()

    async def _start_holiday(self) -> None:
        today = datetime.now().date()
        away_duration = self.coordinator._entry.options.get("away_duration", 7)
        await self._write("Z1HolidayStartPeriod", today.strftime(DATE_FMT))
        await self._write("Z1HolidayEndPeriod", (today + timedelta(days=away_duration)).strftime(DATE_FMT))
        ht = _float(_value(self.coordinator, f"{CIRCUIT}.Z1HolidayTemp.value"))
        if ht is None:
            await self._write("Z1HolidayTemp", "15.0")

    async def _cancel_holiday(self) -> None:
        await self._write("Z1HolidayStartPeriod", HOLIDAY_RESET)
        await self._write("Z1HolidayEndPeriod", HOLIDAY_RESET)

    async def _write(self, name: str, value: str) -> bool:
        return await self._write_raw(CIRCUIT, name, value)

    async def _write_raw(self, circuit: str, name: str, value: str) -> bool:
        backend = self.coordinator.ebusd_backend
        if not backend:
            return False
        try:
            result = await backend.async_write(circuit, name, value)
            if result.success:
                await self.coordinator.async_request_refresh()
            return result.success
        except Exception:
            return False


CIRCUIT_HMU = "hmu"
MIN_FLOW_TEMP = f"{CIRCUIT}.Hc1MinFlowTempDesired.value"
MAX_FLOW_TEMP = f"{CIRCUIT}.Hc1MaxFlowTempDesired.value"
CURRENT_FLOW_TEMP = f"{CIRCUIT}.Hc1FlowTemp.value"


class EbusdFlowTempRange(CoordinatorEntity[VaillantCoordinator], ClimateEntity):

    _attr_has_entity_name = True
    _attr_name = "Flow Temperature Range"
    _attr_hvac_modes = [HVACMode.AUTO]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5
    _attr_max_temp = 75
    _attr_target_temperature_step = 1

    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_climate_flow_temp_range"
        self._attr_device_info = coordinator.get_device_info("z1")

    @property
    def supported_features(self) -> ClimateEntityFeature:
        return ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

    @property
    def current_temperature(self) -> float | None:
        return _float(_value(self.coordinator, CURRENT_FLOW_TEMP))

    @property
    def target_temperature_low(self) -> float | None:
        return _float(_value(self.coordinator, MIN_FLOW_TEMP))

    @property
    def target_temperature_high(self) -> float | None:
        return _float(_value(self.coordinator, MAX_FLOW_TEMP))

    @property
    def hvac_action(self) -> HVACAction | None:
        comp = (_value(self.coordinator, COMPRESSOR_STATUS) or "").lower()
        if comp in HEATING_STATES:
            return HVACAction.HEATING
        if comp in COOLING_STATES:
            return HVACAction.COOLING
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if comp:
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def hvac_mode(self) -> HVACMode | None:
        return _hvac_mode(_value(self.coordinator, OPERATION_MODE))

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_set_temperature(self, **kwargs: Any) -> None:
        low = kwargs.get("target_temp_low")
        high = kwargs.get("target_temp_high")
        if low is not None:
            await self._write("Hc1MinFlowTempDesired", str(int(low)))
        if high is not None:
            await self._write("Hc1MaxFlowTempDesired", str(int(high)))

    async def _write(self, name: str, value: str) -> bool:
        backend = self.coordinator.ebusd_backend
        if not backend:
            return False
        try:
            result = await backend.async_write(CIRCUIT, name, value)
            if result.success:
                await self.coordinator.async_request_refresh()
            return result.success
        except Exception:
            return False
