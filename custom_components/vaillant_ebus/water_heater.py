"""Water heater platform for domestic hot water."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.water_heater import WaterHeaterEntity, WaterHeaterEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_AWAY_DURATION, DEFAULT_AWAY_DURATION, DOMAIN
from .coordinator import VaillantCoordinator

ZONE = "dhw"

EBUSD_TO_HA_OPMODE = {
    "off": "off",
    "auto": "auto",
    "day": "manual",
}

HA_TO_EBUSD_OPMODE = {v: k for k, v in EBUSD_TO_HA_OPMODE.items()}

OPERATION_MODES = ["off", "auto", "manual", "boost"]

DATE_FMT = "%d.%m.%Y"
HOLIDAY_RESET = "01.01.2015"


# Look up a string value from coordinator ebusd data by register name
def _value(coordinator: VaillantCoordinator, register: str) -> str | None:
    circuit = coordinator.heating_circuit
    key = f"{circuit}.{register}.value"
    value = coordinator.data.get("ebusd", {}).get(key)
    return str(value) if value is not None else None


# Parse string value to float, return None on failure
def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# Create water heater entity from coordinator
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EbusdWaterHeater(coordinator, entry)])


class EbusdWaterHeater(CoordinatorEntity[VaillantCoordinator], WaterHeaterEntity):

    _attr_has_entity_name = True
    _attr_name = "Domestic Hot Water"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 35
    _attr_max_temp = 70
    _attr_target_temperature_step = 1
    _attr_operation_list = OPERATION_MODES

    # Initialize water heater with unique ID and DHW device
    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_water_heater_dhw"
        self._attr_device_info = coordinator.get_device_info(ZONE)

    # Supported features: target temp, operation mode, away mode, on/off
    @property
    def supported_features(self) -> WaterHeaterEntityFeature:
        return (
            WaterHeaterEntityFeature.TARGET_TEMPERATURE
            | WaterHeaterEntityFeature.OPERATION_MODE
            | WaterHeaterEntityFeature.AWAY_MODE
            | WaterHeaterEntityFeature.ON_OFF
        )

    # True when HwcHolidayStartPeriod/EndPeriod bracket today
    @property
    def is_away_mode_on(self) -> bool | None:
        h_start = _value(self.coordinator, "HwcHolidayStartPeriod")
        h_end = _value(self.coordinator, "HwcHolidayEndPeriod")
        if not h_start or not h_end:
            return None
        try:
            now = date.today()
            start = datetime.strptime(h_start, DATE_FMT).date()
            end = datetime.strptime(h_end, DATE_FMT).date()
            return start <= now <= end
        except ValueError:
            return None

    # Current DHW storage temperature from HwcStorageTemp
    @property
    def current_temperature(self) -> float | None:
        return _float(_value(self.coordinator, "HwcStorageTemp"))

    # Target temperature from HwcTempDesired, filtered to valid range
    @property
    def target_temperature(self) -> float | None:
        value = _float(_value(self.coordinator, "HwcTempDesired"))
        return value if value is not None and 30 <= value <= 70 else None

    # Current operation mode: off/auto/manual/boost (boost from HwcSFMode)
    @property
    def current_operation(self) -> str | None:
        sf = (_value(self.coordinator, "HwcSFMode") or "").lower()
        if sf == "load":
            return "boost"
        operation = (_value(self.coordinator, "HwcOpMode") or "").lower()
        return EBUSD_TO_HA_OPMODE.get(operation)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    # Set DHW target temperature via HwcTempDesired
    async def async_set_temperature(self, **kwargs: Any) -> None:
        value = kwargs.get(ATTR_TEMPERATURE)
        if value is not None:
            await self._write("HwcTempDesired", str(value))

    # Switch DHW operation mode: auto/manual/off/boost
    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode not in OPERATION_MODES:
            raise ValueError(f"Unsupported DHW operation: {operation_mode}")
        ebus = self.coordinator.ebus
        if not ebus:
            return
        if operation_mode == "boost":
            await ebus.write_register(self.coordinator.heating_circuit, "HwcSFMode", "load")
        else:
            ebusd_mode = HA_TO_EBUSD_OPMODE.get(operation_mode, operation_mode)
            await ebus.write_register(self.coordinator.heating_circuit, "HwcSFMode", "auto")
            await ebus.write_register(self.coordinator.heating_circuit, "HwcOpMode", ebusd_mode)
        await self.coordinator.async_request_refresh()

    # Turn DHW on by setting operation mode to auto
    async def async_turn_on(self) -> None:
        await self.async_set_operation_mode("auto")

    # Turn DHW off
    async def async_turn_off(self) -> None:
        await self.async_set_operation_mode("off")

    # Enable away mode by setting holiday period from today to end date
    async def async_turn_away_mode_on(self) -> None:
        today = date.today().strftime(DATE_FMT)
        away_duration = self.coordinator._entry.options.get(CONF_AWAY_DURATION, DEFAULT_AWAY_DURATION)
        end = (date.today() + timedelta(days=away_duration)).strftime(DATE_FMT)
        await self._write("HwcHolidayStartPeriod", today)
        await self._write("HwcHolidayEndPeriod", end)

    # Disable away mode by resetting holiday dates to unset
    async def async_turn_away_mode_off(self) -> None:
        await self._write("HwcHolidayStartPeriod", HOLIDAY_RESET)
        await self._write("HwcHolidayEndPeriod", HOLIDAY_RESET)

    # Write value to a DHW register and trigger coordinator refresh
    async def _write(self, name: str, value: str) -> None:
        ebus = self.coordinator.ebus
        if ebus:
            result = await ebus.write_register(self.coordinator.heating_circuit, name, value)
            if result.success:
                await self.coordinator.async_request_refresh()
