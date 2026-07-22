"""Water heater platform for domestic hot water."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import WaterHeaterEntity, WaterHeaterEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VaillantCoordinator

ZONE = "dhw"
CIRCUIT = "ctlv2"
CURRENT_TEMPERATURE = f"{CIRCUIT}.HwcStorageTemp.value"
TARGET_TEMPERATURE = f"{CIRCUIT}.HwcTempDesired.value"
OPERATION_MODE = f"{CIRCUIT}.HwcOpMode.value"
OPERATION_MODES = ["off", "day", "night", "auto"]


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


# Create the DHW water heater entity
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EbusdWaterHeater(coordinator, entry)])


class EbusdWaterHeater(CoordinatorEntity[VaillantCoordinator], WaterHeaterEntity):
    """Aggregated domestic-hot-water control."""

    _attr_has_entity_name = True
    _attr_name = "Domestic Hot Water"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 30
    _attr_max_temp = 70
    _attr_target_temperature_step = 1
    _attr_operation_list = OPERATION_MODES
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

    # Initialize DHW water heater entity
    def __init__(self, coordinator: VaillantCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_water_heater_dhw"
        self._attr_device_info = coordinator.get_device_info(ZONE)

    @property
    def current_temperature(self) -> float | None:
        # Return current DHW storage temperature
        return _float(_value(self.coordinator, CURRENT_TEMPERATURE))

    @property
    def target_temperature(self) -> float | None:
        # Return DHW setpoint if within valid range
        value = _float(_value(self.coordinator, TARGET_TEMPERATURE))
        return value if value is not None and 30 <= value <= 70 else None

    @property
    def current_operation(self) -> str | None:
        # Return DHW operation mode (off/day/night/auto)
        operation = (_value(self.coordinator, OPERATION_MODE) or "").lower()
        return operation if operation in OPERATION_MODES else None

    @property
    def available(self) -> bool:
        # Entity available when coordinator updates succeed
        return self.coordinator.last_update_success

    # Write DHW target temperature to ebusd
    async def async_set_temperature(self, **kwargs: Any) -> None:
        value = kwargs.get(ATTR_TEMPERATURE)
        if value is not None:
            await self._write("HwcTempDesired", str(value))

    # Write DHW operation mode to ebusd
    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode not in OPERATION_MODES:
            raise ValueError(f"Unsupported DHW operation: {operation_mode}")
        await self._write("HwcOpMode", operation_mode)

    # Write a CTLV2 register value and trigger refresh
    async def _write(self, name: str, value: str) -> None:
        backend = self.coordinator.ebusd_backend
        if backend:
            result = await backend.async_write(CIRCUIT, name, value)
            if result.success:
                await self.coordinator.async_request_refresh()
