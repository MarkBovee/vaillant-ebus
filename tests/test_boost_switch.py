"""Unit tests for the DHW boost desired-state behavior.

HwcSFMode reports "load" while the cylinder charges even after boost is turned
off, so the boost switch and water heater report the coordinator's desired DHW
boost state once a toggle has happened. These tests pin that behavior.

Reuses the homeassistant mock scaffolding from tests.test_coordinator.
"""

from __future__ import annotations

import enum
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from tests import test_coordinator as tc  # noqa: F401 — installs shared HA mocks

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"

mock_homeassistant = sys.modules["homeassistant"]


class _MockBaseEntity:
    @property
    def unique_id(self) -> str | None:
        return getattr(self, "_attr_unique_id", None)

    @property
    def name(self) -> str | None:
        return getattr(self, "_attr_name", None)

    @property
    def is_on(self):  # pragma: no cover - overridden by real entities
        return None


class _MockCoordinatorEntity(_MockBaseEntity):
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    def async_write_ha_state(self) -> None:
        pass

    def _handle_coordinator_update(self) -> None:
        pass

    async def async_update(self) -> None:
        pass

    def __class_getitem__(cls, item):
        return cls


class _UnitOfTemperature:
    CELSIUS = "°C"


class _WaterHeaterEntityFeature(enum.IntFlag):
    TARGET_TEMPERATURE = 1
    OPERATION_MODE = 2
    AWAY_MODE = 4
    ON_OFF = 8


components_pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("homeassistant.components", None))
switch_pkg = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.components.switch", None)
)
switch_pkg.SwitchEntity = _MockBaseEntity
water_heater_pkg = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.components.water_heater", None)
)
water_heater_pkg.WaterHeaterEntity = _MockBaseEntity
water_heater_pkg.WaterHeaterEntityFeature = _WaterHeaterEntityFeature
sys.modules["homeassistant.components"] = components_pkg
sys.modules["homeassistant.components.switch"] = switch_pkg
sys.modules["homeassistant.components.water_heater"] = water_heater_pkg

ha_const = sys.modules["homeassistant.const"]
ha_const.ATTR_TEMPERATURE = "temperature"
ha_const.UnitOfTemperature = _UnitOfTemperature

entity_platform = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.helpers.entity_platform", None)
)
entity_platform.AddEntitiesCallback = object
sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

mock_homeassistant.helpers.update_coordinator.CoordinatorEntity = _MockCoordinatorEntity
mock_homeassistant.config_entries.ConfigEntry = object
mock_homeassistant.core.HomeAssistant = object

const_module = sys.modules["vaillant_ebus.const"]
const_module.CONF_AWAY_DURATION = "away_duration"
const_module.DEFAULT_AWAY_DURATION = 5
const_module.DOMAIN = "vaillant_ebus"

for _name in ("switch", "water_heater"):
    _spec = importlib.util.spec_from_file_location(f"vaillant_ebus.{_name}", COMPONENT_PATH / f"{_name}.py")
    assert _spec and _spec.loader
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"vaillant_ebus.{_name}"] = _mod
    _spec.loader.exec_module(_mod)

from vaillant_ebus.switch import HwcBoostSwitch  # noqa: E402
from vaillant_ebus.water_heater import EbusdWaterHeater  # noqa: E402


def _coordinator(dhw_boost_desired=None, sfmode="load") -> MagicMock:
    c = MagicMock()
    c.heating_circuit = "basv"
    c.dhw_boost_desired = dhw_boost_desired
    c.data = {"ebusd": {"basv.HwcSFMode.value": sfmode, "basv.HwcOpMode.value": "auto"}}
    c.async_write_register = AsyncMock(return_value=True)
    c.async_write_registers = AsyncMock(return_value=True)
    c.get_device_info = MagicMock(return_value={"identifiers": {("vaillant_ebus", "dhw")}})
    c.last_update_success = True
    return c


def _entry() -> MagicMock:
    e = MagicMock()
    e.entry_id = "entry-1"
    e.options = {}
    e.data = {}
    return e


# Without a prior toggle, the switch falls back to the raw HwcSFMode register.
def test_boost_switch_falls_back_to_raw_register() -> None:
    sw = HwcBoostSwitch(_coordinator(dhw_boost_desired=None, sfmode="load"), _entry())
    assert sw.is_on is True
    sw2 = HwcBoostSwitch(_coordinator(dhw_boost_desired=None, sfmode="auto"), _entry())
    assert sw2.is_on is False


# After a toggle the switch reports the desired state, not the raw register.
def test_boost_switch_reports_desired_state() -> None:
    c = _coordinator(dhw_boost_desired=False, sfmode="load")
    sw = HwcBoostSwitch(c, _entry())
    # HwcSFMode still "load" (charging) but boost was turned off.
    assert sw.is_on is False


# Turning boost on/off writes HwcSFMode without strict verification (read-back
# lags while the cylinder charges) and records the desired state.
async def test_boost_switch_turn_on_and_off() -> None:
    c = _coordinator(dhw_boost_desired=False)
    sw = HwcBoostSwitch(c, _entry())
    await sw.async_turn_on()
    assert c.dhw_boost_desired is True
    c.async_write_register.assert_awaited_once_with("basv", "HwcSFMode", "load", strict_verify=False)

    c.async_write_register.reset_mock()
    await sw.async_turn_off()
    assert c.dhw_boost_desired is False
    c.async_write_register.assert_awaited_once_with("basv", "HwcSFMode", "auto", strict_verify=False)


# The water heater reports boost once desired, even when HwcSFMode reads "load".
def test_water_heater_current_operation_boost_desired() -> None:
    wh = EbusdWaterHeater(_coordinator(dhw_boost_desired=True, sfmode="load"), _entry())
    assert wh.current_operation == "boost"
    wh2 = EbusdWaterHeater(_coordinator(dhw_boost_desired=False, sfmode="load"), _entry())
    assert wh2.current_operation == "auto"
