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

import pytest

from tests import test_coordinator as tc  # noqa: F401 — installs shared HA mocks
from tests.fake_ebusd import load_find_lines

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
switch_pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("homeassistant.components.switch", None))
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

from vaillant_ebus.switch import HwcAwayModeSwitch, HwcBoostSwitch, _is_holiday_active  # noqa: E402
from vaillant_ebus.water_heater import EbusdWaterHeater  # noqa: E402


def _coordinator(dhw_boost_desired=None, sfmode="load") -> MagicMock:
    c = MagicMock()
    c.heating_circuit = "basv"
    c.dhw_boost_desired = dhw_boost_desired
    c.data = {"ebusd": {"basv.HwcSFMode.value": sfmode, "basv.HwcOpMode.value": "auto"}}
    c.async_write_register = AsyncMock(return_value=True)
    c.async_write_registers = AsyncMock(return_value=True)
    c.async_request_refresh = AsyncMock()
    c.get_device_info = MagicMock(return_value={"identifiers": {("vaillant_ebus", "dhw")}})
    c.last_update_success = True
    return c


def _entry() -> MagicMock:
    e = MagicMock()
    e.entry_id = "entry-1"
    e.options = {}
    e.data = {}
    return e


# Build the coordinator `ebusd` value dict the same way the real coordinator
# does, so the water-heater properties read exactly what a live refresh exposes.
def _ebusd_data_from_graph(graph) -> dict[str, str]:
    data: dict[str, str] = {}
    for rk, raw in graph.raw_registers.items():
        circuit, name = rk.split(".", 1)
        for field, value in tc._register_values(rk, raw).items():
            if value is not None:
                data[f"{circuit}.{name}.{field}"] = value
    return data


# Coordinator stub whose heating circuit is resolved from a real discovery
# graph. Unlike the MagicMock helper above it cannot be told the circuit: the
# DHW entity state depends on the graph resolution being correct.
class _GraphCoordinator:
    def __init__(self, graph, data: dict[str, str]) -> None:
        self._graph = graph
        self.data = {"ebusd": data}
        self.dhw_boost_desired = None
        self.last_update_success = True
        self.async_write_register = AsyncMock(return_value=True)
        self.async_write_registers = AsyncMock(return_value=True)
        self.async_request_refresh = AsyncMock()
        self.async_update_listeners = MagicMock()

    @property
    def heating_circuit(self):
        return self._graph.resolve_circuit_result("ctlv2").circuit

    def get_device_info(self, *_args):
        return {"identifiers": {("vaillant_ebus", "dhw")}}


def _graph_coordinator(fixture: str) -> _GraphCoordinator:
    graph = tc.DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    return _GraphCoordinator(graph, _ebusd_data_from_graph(graph))



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
    c.async_write_register.assert_awaited_once_with("basv", "HwcSFMode", "load", strict_verify=False, refresh=False)
    c.async_update_listeners.assert_called_once()

    c.async_write_register.reset_mock()
    await sw.async_turn_off()
    assert c.dhw_boost_desired is False
    c.async_write_register.assert_awaited_once_with("basv", "HwcSFMode", "auto", strict_verify=False, refresh=False)
    assert c.async_update_listeners.call_count == 2


async def test_boost_switch_keeps_confirmed_state_when_write_fails() -> None:
    c = _coordinator(dhw_boost_desired=False)
    c.async_write_register = AsyncMock(return_value=False)
    sw = HwcBoostSwitch(c, _entry())

    await sw.async_turn_on()

    assert c.dhw_boost_desired is False


async def test_water_heater_keeps_confirmed_boost_state_when_write_fails() -> None:
    c = _coordinator(dhw_boost_desired=False)
    c.async_write_registers = AsyncMock(return_value=False)
    wh = EbusdWaterHeater(c, _entry())

    await wh.async_set_operation_mode("boost")

    assert c.dhw_boost_desired is False


async def test_water_heater_marks_boost_off_before_later_mode_write_fails() -> None:
    c = _coordinator(dhw_boost_desired=True)
    c.async_write_register = AsyncMock(side_effect=(True, False))
    wh = EbusdWaterHeater(c, _entry())

    await wh.async_set_operation_mode("auto")

    assert c.dhw_boost_desired is False
    assert c.async_write_register.await_args_list == [
        (("basv", "HwcSFMode", "auto"), {"strict_verify": False, "refresh": False}),
        (("basv", "HwcOpMode", "auto"), {"strict_verify": False}),
    ]
    c.async_update_listeners.assert_called_once()


async def test_ctlv3_dhw_controls_use_resolved_controller_circuit() -> None:
    c = _coordinator(dhw_boost_desired=False, sfmode="auto")
    c.heating_circuit = "ctlv3"
    c.data["ebusd"] = {
        "ctlv3.HwcOpMode.value": "auto",
        "ctlv3.HwcSFMode.value": "auto",
        "ctlv3.HwcStorageTemp.value": "45",
        "ctlv3.HwcTempDesired.value": "48",
        "ctlv3.HwcHolidayStartPeriod.value": "01.01.2015",
        "ctlv3.HwcHolidayEndPeriod.value": "01.01.2015",
    }
    water_heater = EbusdWaterHeater(c, _entry())

    assert water_heater.current_operation == "auto"
    assert water_heater.current_temperature == 45.0
    assert water_heater.target_temperature == 48.0
    assert water_heater.is_away_mode_on is False

    await water_heater.async_set_operation_mode("boost")
    c.async_write_registers.assert_awaited_once_with(
        [("ctlv3", "HwcSFMode", "load")], strict_verify=False, refresh=False
    )

    c.async_write_registers.reset_mock()
    away = HwcAwayModeSwitch(c, _entry())
    assert away.is_on is False
    await away.async_turn_off()
    c.async_write_registers.assert_awaited_once_with(
        [
            ("ctlv3", "HwcHolidayStartPeriod", "01.01.2015"),
            ("ctlv3", "HwcHolidayEndPeriod", "01.01.2015"),
        ]
    )


# Regression for issue #99: the latest dumps carry a spurious ctlv2 node from
# runtime-defined registers while the real DHW controller is ctlv3. A valid
# ctlv3.HwcOpMode=auto must surface as the water-heater operation mode "auto",
# never "unknown". Before the graph fix this resolved to ctlv2 and stayed None.
@pytest.mark.parametrize(
    "fixture",
    (
        "community/hmux0_issue99_2026-09-10_170850.yaml",
        "community/hmux0_issue99_2026-09-10_173229.yaml",
    ),
)
def test_latest_dump_dhw_entity_state_is_auto_not_unknown(fixture: str) -> None:
    coordinator = _graph_coordinator(fixture)
    assert coordinator.heating_circuit == "ctlv3"

    water_heater = EbusdWaterHeater(coordinator, _entry())

    assert water_heater.current_operation == "auto"
    assert water_heater.current_temperature == 45.0
    assert water_heater.target_temperature == 48.0

    # The dump shows HwcSFMode = auto, so Boost is off.
    assert HwcBoostSwitch(coordinator, _entry()).is_on is False
    # Unset holiday sentinels are an explicit "not away", not unknown.
    assert water_heater.is_away_mode_on is False


# Valid data arriving only after the entity exists must update its state; the
# coordinator populates registers asynchronously, so the entity must not cache
# the initial "unknown".
def test_dhw_entity_operation_updates_when_valid_data_arrives_later() -> None:
    coordinator = _graph_coordinator("community/hmux0_issue99_2026-09-10_173229.yaml")
    water_heater = EbusdWaterHeater(coordinator, _entry())

    coordinator.data["ebusd"].pop("ctlv3.HwcOpMode.value")
    assert water_heater.current_operation is None

    coordinator.data["ebusd"]["ctlv3.HwcOpMode.value"] = "auto"
    assert water_heater.current_operation == "auto"


# A temporary no-data reply must read as unknown, then recover once a real
# value returns. This proves "not available yet" is not conflated with a
# permanent failure state.
def test_dhw_entity_operation_recovers_after_temporary_no_data() -> None:
    coordinator = _graph_coordinator("community/hmux0_issue99_2026-09-10_173229.yaml")
    water_heater = EbusdWaterHeater(coordinator, _entry())

    coordinator.data["ebusd"]["ctlv3.HwcOpMode.value"] = "no data stored"
    assert water_heater.current_operation is None

    coordinator.data["ebusd"]["ctlv3.HwcOpMode.value"] = "auto"
    assert water_heater.current_operation == "auto"


# An enum value the integration does not map must stay unknown instead of
# being coerced to a default.
def test_dhw_entity_operation_unknown_for_invalid_enum() -> None:
    coordinator = _graph_coordinator("community/hmux0_issue99_2026-09-10_173229.yaml")
    coordinator.data["ebusd"]["ctlv3.HwcOpMode.value"] = "bogus"
    water_heater = EbusdWaterHeater(coordinator, _entry())

    assert water_heater.current_operation is None


# DHW writes must target the resolved ctlv3 controller, not the spurious ctlv2
# node the latest dump exposes.
async def test_latest_dump_dhw_writes_target_resolved_controller() -> None:
    coordinator = _graph_coordinator("community/hmux0_issue99_2026-09-10_173229.yaml")
    water_heater = EbusdWaterHeater(coordinator, _entry())

    await water_heater.async_set_operation_mode("boost")
    coordinator.async_write_registers.assert_awaited_once_with(
        [("ctlv3", "HwcSFMode", "load")], strict_verify=False, refresh=False
    )

    coordinator.async_write_registers.reset_mock()
    away = HwcAwayModeSwitch(coordinator, _entry())
    assert away.is_on is False
    await away.async_turn_off()
    coordinator.async_write_registers.assert_awaited_once_with(
        [
            ("ctlv3", "HwcHolidayStartPeriod", "01.01.2015"),
            ("ctlv3", "HwcHolidayEndPeriod", "01.01.2015"),
        ]
    )


# The water heater reports boost once desired, even when HwcSFMode reads "load".
def test_water_heater_current_operation_boost_desired() -> None:
    wh = EbusdWaterHeater(_coordinator(dhw_boost_desired=True, sfmode="load"), _entry())
    assert wh.current_operation == "boost"
    wh2 = EbusdWaterHeater(_coordinator(dhw_boost_desired=False, sfmode="load"), _entry())
    assert wh2.current_operation == "auto"


def test_holiday_reset_values_are_not_active() -> None:
    assert _is_holiday_active("01.01.2015", "01.01.2015") is False
    assert _is_holiday_active("01.01.2019", "01.01.2019") is False


def test_water_heater_properties_and_holiday_handling() -> None:
    c = _coordinator(dhw_boost_desired=None, sfmode="auto")
    c.data["ebusd"].update(
        {
            "basv.HwcStorageTemp.value": "48.5",
            "basv.HwcTempDesired.value": "52",
            "basv.HwcHolidayStartPeriod.value": "01.01.2015",
            "basv.HwcHolidayEndPeriod.value": "01.01.2015",
        }
    )
    wh = EbusdWaterHeater(c, _entry())
    assert wh.current_temperature == 48.5
    assert wh.target_temperature == 52.0
    assert wh.current_operation == "auto"
    assert wh.is_away_mode_on is False
    # Test 01.01.2019 reset sentinel as well
    c.data["ebusd"]["basv.HwcHolidayStartPeriod.value"] = "01.01.2019"
    c.data["ebusd"]["basv.HwcHolidayEndPeriod.value"] = "01.01.2019"
    assert wh.is_away_mode_on is False


# Away state is coherent with the away switch: an unset sentinel is False, a
# bracketing period is True, and only genuinely missing data is unknown.
def test_water_heater_away_state_coherence() -> None:
    c = _coordinator(dhw_boost_desired=None, sfmode="auto")
    c.data["ebusd"]["basv.HwcHolidayStartPeriod.value"] = "01.01.2020"
    c.data["ebusd"]["basv.HwcHolidayEndPeriod.value"] = "01.01.2099"
    wh = EbusdWaterHeater(c, _entry())
    assert wh.is_away_mode_on is True

    c.data["ebusd"].pop("basv.HwcHolidayStartPeriod.value")
    assert wh.is_away_mode_on is None
