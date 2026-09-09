"""Climate platform: one thermostat and flow-temperature-range per heating zone."""

from __future__ import annotations

import logging
from collections.abc import Callable
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
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_COOLING_DURATION,
    DEFAULT_COOLING_DURATION,
    DOMAIN,
    EBUSD_TO_HA_HVAC,
    HA_TO_EBUSD_HVAC,
)
from .coordinator import VaillantCoordinator

_LOGGER = logging.getLogger(__name__)

HEATING_STATES = frozenset(
    {
        "heat_compressor_active",
        "heat_prerun",
        "heat_overrun",
        "heat_immersion_heater_active",
    }
)
COOLING_STATES = frozenset(
    {
        "cool_compressor_active",
        "cool_prerun",
        "cool_overrun",
    }
)

DATE_FMT = "%d.%m.%Y"
TIME_FMT = "%H:%M:%S"
HOLIDAY_RESET = "01.01.2015"
HOLIDAY_RESET_VALUES = frozenset(("01.01.2015", "01.01.2019"))

# Measured against live ctlv2 hardware (2026-08-24): quick-veto writes return
# done immediately, but the controller applies them with roughly 30-60 s
# latency before QuickVetoEndDate/EndTime reflect the veto. The confirm
# refresh pulls data once inside that settle window; the optimistic target
# bridges the gap in the UI.
QUICK_VETO_CONFIRM_DELAY = timedelta(seconds=35)

# Registers that gate per-zone features on the zone's owning circuit.
COOLING_REGISTER = "CoolingTemp"
QUICK_VETO_DURATION_REGISTER = "QuickVetoDuration"


# Look up a string value from coordinator ebusd data by register name
def _value(coordinator: VaillantCoordinator, register: str, circuit: str | None = None) -> str | None:
    ckt = circuit or coordinator.heating_circuit
    key = f"{ckt}.{register}.value"
    value = coordinator.data.get("ebusd", {}).get(key)
    return str(value) if value is not None else None


# Parse string value to float, return None on failure
def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# Map ebusd operation mode string to HA HVACMode
def _hvac_mode(value: str | None) -> HVACMode | None:
    ha = EBUSD_TO_HA_HVAC.get((value or "").lower())
    return HVACMode(ha) if ha else None


# Create climate entities: one thermostat and flow-temperature-range per zone
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    created_zones: set[str] = set()

    # Create thermostat + flow-temp-range for every zone not yet added. Runs at
    # setup (falling back to z1 before discovery) and again after each applied
    # discovery graph so zones that appear later still get their entities.
    def _ensure_zone_entities() -> None:
        zone_circuits = coordinator.zone_circuits()
        if not zone_circuits:
            zone_circuits = {"z1": coordinator.heating_circuit}
        missing = [zone for zone in zone_circuits if zone not in created_zones]
        if not missing:
            return
        entities: list[ClimateEntity] = []
        for zone in missing:
            created_zones.add(zone)
            circuit = zone_circuits[zone]
            entities.append(EbusdClimate(coordinator, entry, zone, circuit))
            entities.append(EbusdFlowTempRange(coordinator, entry, zone, circuit))
        async_add_entities(entities)

    _ensure_zone_entities()
    coordinator.register_post_discovery_callback(_ensure_zone_entities)


class EbusdClimate(CoordinatorEntity[VaillantCoordinator], ClimateEntity):
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5
    _attr_max_temp = 30
    _attr_target_temperature_step = 0.5

    # Initialize zone climate entity with zone-scoped registers, identity, and
    # per-zone feature support derived from the discovery graph.
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
        zone: str,
        circuit: str,
    ) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._circuit = circuit
        self._zn = zone.upper()
        self._attr_unique_id = f"{entry.entry_id}_climate_{zone}"
        self._attr_device_info = coordinator.get_device_info(zone)
        self._attr_name = "Home" if zone == "z1" else f"Zone {zone[1:]}"
        self._optimistic_hvac_mode: HVACMode | None = None
        self._quick_veto_until: datetime | None = None
        # Optimistic target temperature shown until device data confirms it or
        # the settle window expires (see QUICK_VETO_CONFIRM_DELAY).
        self._optimistic_target: float | None = None
        self._optimistic_target_until: datetime | None = None
        self._cancel_confirm_refresh: Callable[[], None] | None = None
        # End of the veto that the user explicitly cancelled; while the device
        # still reports exactly this end, BOOST stays suppressed.
        self._boost_suppressed_end: datetime | None = None

    # HVAC modes are computed per zone from the discovery graph: COOL only where
    # the zone's cooling register exists. Computed dynamically so a cache-seeded
    # graph or late discovery self-corrects on the next coordinator update.
    @property
    def hvac_modes(self) -> list[HVACMode]:
        modes = [HVACMode.OFF, HVACMode.HEAT]
        if self.coordinator.has_zone_register(self._circuit, self._zone, COOLING_REGISTER):
            modes.append(HVACMode.COOL)
        modes.append(HVACMode.AUTO)
        return modes

    # Presets are computed per zone: BOOST only where quick-veto duration exists.
    @property
    def preset_modes(self) -> list[str]:
        presets = [PRESET_NONE]
        if self.coordinator.has_zone_register(self._circuit, self._zone, QUICK_VETO_DURATION_REGISTER):
            presets.append(PRESET_BOOST)
        presets.append(PRESET_AWAY)
        return presets

    # Current room temperature from the zone's room temp register
    @property
    def current_temperature(self) -> float | None:
        return _float(_value(self.coordinator, f"{self._zn}RoomTemp", self._circuit))

    # Target temperature: optimistic value after a write, then quick veto temp
    # (boost), actual/target, filtered to valid range, finally day temp.
    @property
    def target_temperature(self) -> float | None:
        now = datetime.now()
        if (
            self._optimistic_target is not None
            and self._optimistic_target_until is not None
            and now < self._optimistic_target_until
        ):
            return self._optimistic_target
        return self._reported_target()

    # Target derived purely from device data (no optimistic override).
    def _reported_target(self) -> float | None:
        if self.preset_mode == PRESET_BOOST:
            qv = _float(_value(self.coordinator, f"{self._zn}QuickVetoTemp", self._circuit))
            if qv is not None and 5 <= qv <= 30:
                return qv
        value = _float(_value(self.coordinator, f"{self._zn}ActualRoomTempDesired", self._circuit))
        if value is not None and 5 <= value <= 30:
            return value
        return _float(_value(self.coordinator, f"{self._zn}DayTemp", self._circuit))

    # Supported features: preset mode, target temp, turn on/off
    @property
    def supported_features(self) -> ClimateEntityFeature:
        return (
            ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    # Current HVAC mode: optimistic value or ebusd zone op mode
    @property
    def hvac_mode(self) -> HVACMode | None:
        if self._optimistic_hvac_mode is not None:
            return self._optimistic_hvac_mode
        return _hvac_mode(_value(self.coordinator, f"{self._zn}OpMode", self._circuit))

    # HVAC action derived from zone status, pump, and heat-pump-global compressor state
    @property
    def hvac_action(self) -> HVACAction | None:
        hc = _float(_value(self.coordinator, f"Hc{self._zone[1:]}Status", self._circuit))
        zone_active = hc is not None and hc > 0
        if hc is None:
            pump = _value(self.coordinator, f"Hc{self._zone[1:]}PumpStatus", self._circuit)
            zone_active = (pump or "").lower() in ("on", "1", "true", "yes", "running")
        comp = (_value(self.coordinator, "RunDataStatuscode", self.coordinator.heat_pump_circuit) or "").lower()
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

    # Current preset: boost (QV active), away (holiday period), or none.
    # Boost comes from either the local optimistic timer or device-side veto
    # end data, so a restart with an active veto still shows BOOST.
    @property
    def preset_mode(self) -> str | None:
        now = datetime.now()
        if self._quick_veto_until and self._quick_veto_until > now:
            return PRESET_BOOST
        if self._device_boost_active(now):
            return PRESET_BOOST
        h_start = _value(self.coordinator, f"{self._zn}HolidayStartPeriod", self._circuit)
        h_end = _value(self.coordinator, f"{self._zn}HolidayEndPeriod", self._circuit)
        if h_start and h_end and h_start not in HOLIDAY_RESET_VALUES and h_end not in HOLIDAY_RESET_VALUES:
            try:
                today = now.date()
                start = datetime.strptime(h_start, DATE_FMT).date()
                end = datetime.strptime(h_end, DATE_FMT).date()
                if start <= today <= end:
                    return PRESET_AWAY
            except ValueError:
                pass
        return PRESET_NONE

    # Device-side quick-veto end as datetime, or None when no future end is
    # reported. Verified live on ctlv2 (2026-08-24): idle zones report the
    # past sentinel date 01.01.2019; an active veto reports today/future.
    def _device_boost_end(self) -> datetime | None:
        end_date = _value(self.coordinator, f"{self._zn}QuickVetoEndDate", self._circuit)
        if not end_date:
            return None
        try:
            day = datetime.strptime(end_date.strip(), DATE_FMT).date()
        except ValueError:
            return None
        now = datetime.now()
        end_time_raw = _value(self.coordinator, f"{self._zn}QuickVetoEndTime", self._circuit)
        try:
            end_time = datetime.strptime(end_time_raw.strip(), TIME_FMT).time() if end_time_raw else None
        except ValueError:
            end_time = None
        if end_time is not None:
            return datetime.combine(day, end_time)
        # Date-only fallback: the veto runs through the end of its final day.
        if day < now.date():
            return None
        return datetime.combine(day, datetime.max.time()).replace(microsecond=0)

    # Whether the controller currently runs a quick veto we have not cancelled.
    def _device_boost_active(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        end = self._device_boost_end()
        if end is None or end <= now:
            return False
        # A user-cancelled veto stays reported by the device until it expires;
        # suppress BOOST while the reported end is unchanged from cancellation.
        return not (self._boost_suppressed_end is not None and end == self._boost_suppressed_end)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    # Set HVAC mode: cancel boost first, then write ebusd op mode
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._optimistic_hvac_mode = hvac_mode
        self.async_write_ha_state()
        if self.preset_mode == PRESET_BOOST:
            await self._cancel_quick_veto()
        if hvac_mode == HVACMode.COOL:
            ok = await self._start_manual_cooling()
        elif hvac_mode == HVACMode.HEAT:
            ok = await self._cancel_manual_cooling()
            if ok:
                ok = await self._write(f"{self._zn}OpMode", "day")
        else:
            ebusd_mode = HA_TO_EBUSD_HVAC.get(hvac_mode.value)
            if ebusd_mode is None:
                self._optimistic_hvac_mode = None
                self.async_write_ha_state()
                return
            try:
                ok = await self._write(f"{self._zn}OpMode", ebusd_mode)
            except Exception as exc:
                _LOGGER.exception("set_hvac_mode failed: %s", exc)
                ok = False
        if not ok:
            self._optimistic_hvac_mode = None
            self.async_write_ha_state()

    # Start manual cooling: write the shared end date (today + the configurable
    # cooling_duration) through the central write path, then set the zone to
    # auto so the controller engages cooling. The controller manages the start
    # date itself, so only the end date is written.
    async def _start_manual_cooling(self) -> bool:
        try:
            days = self.coordinator._entry.options.get(CONF_COOLING_DURATION, DEFAULT_COOLING_DURATION)
            today = datetime.now().date()
            end = today + timedelta(days=days)
            writes = [
                (self.coordinator.heating_circuit, "ManualCoolingEndDate", end.strftime(DATE_FMT)),
                (self._circuit, f"{self._zn}OpMode", "auto"),
            ]
            return await self.coordinator.async_write_registers(writes)
        except Exception as exc:
            _LOGGER.exception("start manual cooling failed: %s", exc)
            return False

    # Cancel manual cooling by clearing the shared end date (reset to the holiday
    # reset sentinel) so the controller stops keeping a cooling period active.
    # The controller manages the start date itself.
    async def _cancel_manual_cooling(self) -> bool:
        try:
            return await self.coordinator.async_write_register(
                self.coordinator.heating_circuit, "ManualCoolingEndDate", HOLIDAY_RESET
            )
        except Exception as exc:
            _LOGGER.exception("cancel manual cooling failed: %s", exc)
            return False

    # Set preset: boost (quick veto), away (holiday), or cancel
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self.preset_modes:
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

    # Set target temperature following mypyllant semantics: boost active →
    # update the veto temperature only; time-controlled (auto) mode → start a
    # quick veto; manual/day modes → write the day temp directly.
    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        if self.preset_mode == PRESET_BOOST:
            ok = await self._write(f"{self._zn}QuickVetoTemp", str(temp))
            if ok:
                self._apply_optimistic_target(float(temp))
                self._schedule_confirm_refresh()
            return
        if self.hvac_mode == HVACMode.AUTO and not self._global_cooling_active():
            await self._start_quick_veto(float(temp))
            return
        ok = await self._write(f"{self._zn}DayTemp", str(temp))
        if ok:
            self._apply_optimistic_target(float(temp))
            self._schedule_confirm_refresh()

    # Whether the heat pump currently reports an active cooling state. Quick
    # vetoes are heating-side; after a restart the optimistic COOL mode is
    # lost while OpMode reads "auto", so this gate prevents a heating veto
    # from firing during manual cooling (worst case falls back to DayTemp).
    def _global_cooling_active(self) -> bool:
        comp = (_value(self.coordinator, "RunDataStatuscode", self.coordinator.heat_pump_circuit) or "").lower()
        return comp in COOLING_STATES

    # Turn on by setting operation mode to auto
    async def async_turn_on(self) -> None:
        await self._write(f"{self._zn}OpMode", "auto")

    # Turn off
    async def async_turn_off(self) -> None:
        await self._write(f"{self._zn}OpMode", "off")

    # Clear optimistic mode/target when ebusd confirms, expire quick veto timer
    def _handle_coordinator_update(self) -> None:
        now = datetime.now()
        if self._quick_veto_until and self._quick_veto_until <= now:
            self._quick_veto_until = None
        if self._optimistic_target is not None:
            if self._optimistic_target_until is not None and now >= self._optimistic_target_until:
                self._optimistic_target = None
            else:
                reported = self._reported_target()
                if reported is not None and abs(reported - self._optimistic_target) < 0.05:
                    self._optimistic_target = None
        if self._optimistic_hvac_mode is not None:
            confirmed = _hvac_mode(_value(self.coordinator, f"{self._zn}OpMode", self._circuit))
            if confirmed == self._optimistic_hvac_mode:
                self._optimistic_hvac_mode = None
        super()._handle_coordinator_update()

    # Show the requested target immediately after a successful write; cleared
    # when device data confirms it or the settle window expires.
    def _apply_optimistic_target(self, temp: float) -> None:
        self._optimistic_target = temp
        self._optimistic_target_until = datetime.now() + QUICK_VETO_CONFIRM_DELAY
        self.async_write_ha_state()

    # Pull fresh data once inside the controller's apply-latency window so
    # QuickVetoEndDate/EndTime confirm (or retire) the optimistic state.
    # One pending refresh is enough; later writes reuse it.
    def _schedule_confirm_refresh(self) -> None:
        if self._cancel_confirm_refresh is not None:
            return

        def _fire(_now: datetime) -> None:
            self._cancel_confirm_refresh = None
            self.hass.async_create_task(self.coordinator.async_request_refresh())

        self._cancel_confirm_refresh = async_call_later(self.coordinator.hass, QUICK_VETO_CONFIRM_DELAY, _fire)

    # Cancel quick veto: hold the current day temperature as the veto setpoint
    # until expiry. Verified against live ctlv2 hardware (2026-08-24): writing
    # QuickVetoDuration 0 does not cancel an active veto and QuickVetoEndDate
    # is read-only ("ERR: element not found"), so overwriting the veto temp
    # with DayTemp is the effective soft-cancel and the veto expires on its own.
    async def _cancel_quick_veto(self) -> None:
        self._quick_veto_until = None
        end = self._device_boost_end()
        if end is not None:
            self._boost_suppressed_end = end
        self.async_write_ha_state()
        day_temp = _float(_value(self.coordinator, f"{self._zn}DayTemp", self._circuit))
        if day_temp is not None:
            ok = await self._write(f"{self._zn}QuickVetoTemp", str(day_temp))
            if ok:
                self._apply_optimistic_target(day_temp)
                self._schedule_confirm_refresh()

    # Start quick veto with specified temp or config-based default for N hours
    async def _start_quick_veto(self, temp_override: float | None = None) -> None:
        if temp_override is not None:
            veto_temp = temp_override
        else:
            temp = _float(_value(self.coordinator, f"{self._zn}RoomTemp", self._circuit))
            options = self.coordinator._entry.options
            veto_temp = options.get("quick_veto_temp")
            if veto_temp is None and temp is not None:
                veto_temp = round(temp, 1)
        if veto_temp is None:
            return
        options = self.coordinator._entry.options
        veto_duration = options.get("quick_veto_duration", 3)
        # A deliberate new veto ends any cancellation suppression.
        self._boost_suppressed_end = None
        ok_temp = await self._write(f"{self._zn}QuickVetoTemp", str(veto_temp))
        ok_duration = await self._write(f"{self._zn}QuickVetoDuration", str(veto_duration))
        if not (ok_temp and ok_duration):
            # Do not claim state the controller never received.
            _LOGGER.warning(
                "Quick veto start incomplete for %s (temp_ok=%s duration_ok=%s)",
                self._zn,
                ok_temp,
                ok_duration,
            )
            return
        self._quick_veto_until = datetime.now() + timedelta(hours=veto_duration)
        # Bridge the controller's apply latency: show the requested setpoint
        # immediately and pull confirming data after the settle window.
        self._apply_optimistic_target(float(veto_temp))
        self._schedule_confirm_refresh()
        self.async_write_ha_state()

    # Start holiday period: set zone holiday start/end periods from today
    async def _start_holiday(self) -> None:
        today = datetime.now().date()
        away_duration = self.coordinator._entry.options.get("away_duration", 7)
        await self._write(f"{self._zn}HolidayStartPeriod", today.strftime(DATE_FMT))
        await self._write(f"{self._zn}HolidayEndPeriod", (today + timedelta(days=away_duration)).strftime(DATE_FMT))
        ht = _float(_value(self.coordinator, f"{self._zn}HolidayTemp", self._circuit))
        if ht is None:
            await self._write(f"{self._zn}HolidayTemp", "15.0")

    # Cancel holiday: reset dates to unset value
    async def _cancel_holiday(self) -> None:
        await self._write(f"{self._zn}HolidayStartPeriod", HOLIDAY_RESET)
        await self._write(f"{self._zn}HolidayEndPeriod", HOLIDAY_RESET)

    # Write register to the zone's owning circuit through the central write path
    async def _write(self, name: str, value: str) -> bool:
        return await self.coordinator.async_write_register(self._circuit, name, value)


class EbusdFlowTempRange(CoordinatorEntity[VaillantCoordinator], ClimateEntity):
    _attr_has_entity_name = True
    _attr_hvac_modes = [HVACMode.AUTO]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5
    _attr_max_temp = 75
    _attr_target_temperature_step = 1

    # Initialize flow temp range entity on the zone's device; zone 1 keeps the
    # legacy unique id so existing single-zone installs are unchanged.
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
        zone: str,
        circuit: str,
    ) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._circuit = circuit
        self._zn = zone.upper()
        self._hc = f"Hc{zone[1:]}"
        if zone == "z1":
            self._attr_unique_id = f"{entry.entry_id}_climate_flow_temp_range"
            self._attr_name = "Flow Temperature Range"
        else:
            self._attr_unique_id = f"{entry.entry_id}_climate_flow_temp_range_{zone}"
            self._attr_name = f"Flow Temperature Range Zone {zone[1:]}"
        self._attr_device_info = coordinator.get_device_info(zone)

    # Supports target temperature range (min/max flow temp)
    @property
    def supported_features(self) -> ClimateEntityFeature:
        return ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

    # Current flow temperature from the zone's circuit flow temp register
    @property
    def current_temperature(self) -> float | None:
        return _float(_value(self.coordinator, f"{self._hc}FlowTemp", self._circuit))

    # Minimum flow temperature target
    @property
    def target_temperature_low(self) -> float | None:
        return _float(_value(self.coordinator, f"{self._hc}MinFlowTempDesired", self._circuit))

    # Maximum flow temperature target
    @property
    def target_temperature_high(self) -> float | None:
        return _float(_value(self.coordinator, f"{self._hc}MaxFlowTempDesired", self._circuit))

    # HVAC action from heat-pump-global compressor status (heating/cooling/idle/off)
    @property
    def hvac_action(self) -> HVACAction | None:
        comp = (_value(self.coordinator, "RunDataStatuscode", self.coordinator.heat_pump_circuit) or "").lower()
        if comp in HEATING_STATES:
            return HVACAction.HEATING
        if comp in COOLING_STATES:
            return HVACAction.COOLING
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if comp:
            return HVACAction.IDLE
        return HVACAction.OFF

    # HVAC mode from the zone's op mode register
    @property
    def hvac_mode(self) -> HVACMode | None:
        return _hvac_mode(_value(self.coordinator, f"{self._zn}OpMode", self._circuit))

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    # Set min/max flow temperature range via the zone's circuit registers
    async def async_set_temperature(self, **kwargs: Any) -> None:
        low = kwargs.get("target_temp_low")
        high = kwargs.get("target_temp_high")
        if low is not None:
            await self._write(f"{self._hc}MinFlowTempDesired", str(int(low)))
        if high is not None:
            await self._write(f"{self._hc}MaxFlowTempDesired", str(int(high)))

    # Write register to the zone's owning circuit through the central write path
    async def _write(self, name: str, value: str) -> bool:
        return await self.coordinator.async_write_register(self._circuit, name, value)
