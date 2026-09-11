"""Unit tests for the climate platform — per-zone thermostat and flow range.

Reuses the homeassistant mock scaffolding from tests.test_coordinator so both
files share one set of sys.modules entries (importing a test module does not
re-collect it under pytest).
"""

from __future__ import annotations

import enum
import importlib.machinery
import importlib.util
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from tests import test_coordinator as tc  # noqa: F401 — installs shared HA mocks

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"

mock_homeassistant = sys.modules["homeassistant"]


class HVACMode(enum.StrEnum):
    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    AUTO = "auto"


class HVACAction(enum.StrEnum):
    OFF = "off"
    HEATING = "heating"
    COOLING = "cooling"
    IDLE = "idle"


class ClimateEntityFeature(enum.IntFlag):
    TARGET_TEMPERATURE = 1
    TARGET_TEMPERATURE_RANGE = 2
    PRESET_MODE = 4
    TURN_ON = 8
    TURN_OFF = 16


class _MockClimateEntity:
    @property
    def unique_id(self) -> str | None:
        return getattr(self, "_attr_unique_id", None)

    @property
    def hvac_modes(self) -> list:
        return getattr(self, "_attr_hvac_modes", [])

    @property
    def preset_modes(self) -> list:
        return getattr(self, "_attr_preset_modes", [])


class _MockCoordinatorEntity(_MockClimateEntity):
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


components_pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("homeassistant.components", None))
climate_pkg = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.components.climate", None)
)
climate_const = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.components.climate.const", None)
)
climate_pkg.ClimateEntity = _MockClimateEntity
climate_pkg.ClimateEntityFeature = ClimateEntityFeature
climate_const.PRESET_AWAY = "away"
climate_const.PRESET_BOOST = "boost"
climate_const.PRESET_NONE = "none"
climate_const.HVACAction = HVACAction
climate_const.HVACMode = HVACMode
sys.modules["homeassistant.components"] = components_pkg
sys.modules["homeassistant.components.climate"] = climate_pkg
sys.modules["homeassistant.components.climate.const"] = climate_const

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
const_module.CONF_COOLING_DURATION = "cooling_duration"
const_module.DEFAULT_COOLING_DURATION = 3
const_module.EBUSD_TO_HA_HVAC = {
    "off": "off",
    "auto": "auto",
    "day": "heat",
    "night": "cool",
    "heat": "heat",
    "cool": "cool",
}
const_module.HA_TO_EBUSD_HVAC = {"off": "off", "auto": "auto", "heat": "day"}

CLIMATE_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.climate", COMPONENT_PATH / "climate.py")
assert CLIMATE_SPEC and CLIMATE_SPEC.loader
CLIMATE = importlib.util.module_from_spec(CLIMATE_SPEC)
sys.modules["vaillant_ebus.climate"] = CLIMATE
CLIMATE_SPEC.loader.exec_module(CLIMATE)

from vaillant_ebus.backend.models import DeviceGraph, DeviceNode, DeviceType  # noqa: E402
from vaillant_ebus.climate import EbusdClimate, EbusdFlowTempRange  # noqa: E402
from vaillant_ebus.coordinator import VaillantCoordinator  # noqa: E402


def _entry(entry_id: str = "entry-1", options: dict | None = None) -> MagicMock:
    e = MagicMock()
    e.entry_id = entry_id
    e.options = options or {}
    e.data = {}
    return e


def _coordinator(
    tmpdir: str, graph: DeviceGraph | None, data: dict | None = None, options: dict | None = None
) -> VaillantCoordinator:
    c = VaillantCoordinator(tc._hass(tmpdir), _entry(options=options))
    c._graph = graph
    if graph is not None:
        # Mirrors _apply_discovery_graph: the find set marks discovery complete.
        c._last_find_keys = set(graph.raw_registers)
    c.ebus = MagicMock()
    c.ebus.version = "23.2"
    c.data = data or {"ebusd": {}}
    return c


# Two-zone graph on ctlv2 (mirrors the #75 multizone fixture). With full
# parity, the Z2 cooling/quick-veto registers are present as placeholders.
def _graph_two_zone(full_parity: bool = True) -> DeviceGraph:
    raw_registers = {
        "hmu.RunDataStatuscode": "standby",
        "ctlv2.Z1RoomTemp": "21.5",
        "ctlv2.Z1DayTemp": "22.0",
        "ctlv2.Z1OpMode": "day",
        "ctlv2.Z1ActualRoomTempDesired": "22.0",
        "ctlv2.Z2RoomTemp": "20.5",
        "ctlv2.Z2DayTemp": "21.0",
        "ctlv2.Z2OpMode": "auto",
        "ctlv2.Z2ActualRoomTempDesired": "21.0",
        "ctlv2.Hc1FlowTemp": "35.0",
        "ctlv2.Hc2FlowTemp": "30.0",
    }
    placeholders: set[str] = set()
    if full_parity:
        placeholders.update(
            {
                "ctlv2.Z1CoolingTemp",
                "ctlv2.Z1QuickVetoDuration",
                "ctlv2.Z2CoolingTemp",
                "ctlv2.Z2QuickVetoDuration",
            }
        )
    nodes = {
        "hmu": DeviceNode(
            circuit="hmu",
            device_type=DeviceType.HEAT_PUMP,
            registers=["hmu.RunDataStatuscode"],
            has_data=True,
            scan_type="HMU00",
        ),
        "ctlv2": DeviceNode(
            circuit="ctlv2",
            device_type=DeviceType.HEATING_CONTROLLER,
            registers=[],
            has_data=True,
            zone_circuits=["z1", "z2"],
            parent="hmu",
            scan_type="CTLV2",
        ),
        "z1": DeviceNode(
            circuit="z1",
            device_type=DeviceType.ZONE,
            registers=["ctlv2.Z1RoomTemp"],
            has_data=True,
            parent="ctlv2",
        ),
        "z2": DeviceNode(
            circuit="z2",
            device_type=DeviceType.ZONE,
            registers=["ctlv2.Z2RoomTemp"],
            has_data=True,
            parent="ctlv2",
        ),
    }
    return DeviceGraph(nodes=nodes, raw_registers=raw_registers, placeholder_registers=placeholders)


# Single-zone graph: only z1 carries live data; z2 registers are placeholders.
def _graph_single_zone() -> DeviceGraph:
    graph = _graph_two_zone(full_parity=True)
    graph.nodes["z2"].has_data = False
    for name in ("Z2RoomTemp", "Z2DayTemp", "Z2OpMode", "Z2ActualRoomTempDesired"):
        graph.raw_registers.pop(f"ctlv2.{name}")
        graph.placeholder_registers.add(f"ctlv2.{name}")
    return graph


# Ghost-zone graph: every Z2 register exists but is unused — mapping "none" and
# no live core data — so z2 must NOT get a climate entity.
# Ghost zone: mapping "none", room temp sentinel, and only static set-point
# defaults on DayTemp/OpMode — exactly what ebusd reports on an unused zone.
# These defaults must NOT count as live data (regression: they used to make
# _zone_is_valid accept the ghost zone).
def _graph_ghost_zone() -> DeviceGraph:
    graph = _graph_single_zone()
    graph.raw_registers["ctlv2.Z2RoomZoneMapping"] = "none"
    graph.raw_registers["ctlv2.Z2RoomTemp"] = "empty"
    graph.raw_registers["ctlv2.Z2DayTemp"] = "21.0"
    graph.raw_registers["ctlv2.Z2OpMode"] = "auto"
    graph.nodes["z2"].has_data = True
    return graph


# Real-but-idle graph: z2 has a real thermostat mapping but no live data yet,
# so the climate entity exists but reports unavailable values.
def _graph_idle_zone() -> DeviceGraph:
    graph = _graph_single_zone()
    graph.raw_registers["ctlv2.Z2RoomZoneMapping"] = "VR91_1"
    return graph


def _setup_data() -> dict:
    return {
        "ebusd": {
            "ctlv2.Z1RoomTemp.value": "21.5",
            "ctlv2.Z2RoomTemp.value": "20.5",
            "ctlv2.Hc2FlowTemp.value": "30.0",
        }
    }


# Intent: A two-zone discovery graph yields one thermostat and one flow-range
# entity per zone, each bound to its own device.
# Why: Pins per-zone entity creation and unique_id/device identity so a graph
# with z1 and z2 never collapses to one shared climate.
async def test_async_setup_entry_creates_per_zone_entities() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_two_zone(), _setup_data())
        hass = MagicMock()
        hass.data = {"vaillant_ebus": {"entry-1": coordinator}}
        added: list = []
        await CLIMATE.async_setup_entry(hass, _entry(), lambda entities: added.extend(entities))

        climates = [e for e in added if isinstance(e, EbusdClimate)]
        ranges = [e for e in added if isinstance(e, EbusdFlowTempRange)]
        assert len(climates) == 2
        assert len(ranges) == 2
        z1 = next(e for e in climates if e._attr_unique_id.endswith("_climate_z1"))
        z2 = next(e for e in climates if e._attr_unique_id.endswith("_climate_z2"))
        assert z1._attr_unique_id == "entry-1_climate_z1"
        assert z2._attr_unique_id == "entry-1_climate_z2"
        assert z1._attr_device_info["identifiers"] == {("vaillant_ebus", "z1")}
        assert z2._attr_device_info["identifiers"] == {("vaillant_ebus", "z2")}
        assert {r._attr_unique_id for r in ranges} == {
            "entry-1_climate_flow_temp_range",
            "entry-1_climate_flow_temp_range_z2",
        }


# Intent: a zone-2 thermostat reads its own Z2 registers, not Z1's.
# Why: prevents a per-zone entity from surfacing zone 1's room temperature when both zones share one controller circuit.
async def test_zone2_reads_own_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_two_zone(), _setup_data())
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        z1 = EbusdClimate(coordinator, _entry(), "z1", "ctlv2")
        assert z2.current_temperature == 20.5
        assert z1.current_temperature == 21.5


# Intent: target-temperature writes follow mode semantics — time-controlled
# (auto) zones start a quick veto; manual/day zones write day temp directly.
# Why: guards the mypyllant-aligned quick-veto path so an auto-mode target
# change never overwrites the permanent day setpoint.
async def test_zone2_set_temperature_auto_starts_quick_veto() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(
            tmpdir,
            _graph_two_zone(),
            data={"ebusd": {"ctlv2.Z2OpMode.value": "auto"}},
        )
        coordinator.async_write_register = AsyncMock(return_value=True)
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        await z2.async_set_temperature(temperature=22.0)
        calls = [(c.args[0], c.args[1], c.args[2]) for c in coordinator.async_write_register.call_args_list]
        assert ("ctlv2", "Z2QuickVetoTemp", "22.0") in calls
        assert ("ctlv2", "Z2QuickVetoDuration", "3") in calls
        assert ("ctlv2", "Z2DayTemp", "22.0") not in calls


# Intent: In manual/day mode a target-temperature change writes the zone's DayTemp directly and starts no quick veto.
# Why: pins the mode-dependent write path so day mode keeps a permanent setpoint while auto mode uses quick veto.
async def test_zone1_set_temperature_day_writes_day_temp() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(
            tmpdir,
            _graph_two_zone(),
            data={"ebusd": {"ctlv2.Z1OpMode.value": "day"}},
        )
        coordinator.async_write_register = AsyncMock(return_value=True)
        z1 = EbusdClimate(coordinator, _entry(), "z1", "ctlv2")
        await z1.async_set_temperature(temperature=22.0)
        calls = [(c.args[0], c.args[1], c.args[2]) for c in coordinator.async_write_register.call_args_list]
        assert ("ctlv2", "Z1DayTemp", "22.0") in calls
        assert ("ctlv2", "Z1QuickVetoTemp", "22.0") not in calls


# Intent: an active device-side veto (survives restarts) reports BOOST and
# routes temperature changes to a temp-only quick-veto update.
# Why: ensures a veto already active on the device is recognised after a restart
# and a temp update reuses it without a new duration.
async def test_device_side_veto_reports_boost_and_updates_temp_only() -> None:
    from datetime import datetime, timedelta

    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(
            tmpdir,
            _graph_two_zone(),
            data={
                "ebusd": {
                    "ctlv2.Z2OpMode.value": "auto",
                    "ctlv2.Z2QuickVetoEndDate.value": tomorrow,
                    "ctlv2.Z2QuickVetoEndTime.value": "23:59:00",
                    "ctlv2.Z2QuickVetoTemp.value": "21.0",
                }
            },
        )
        coordinator.async_write_register = AsyncMock(return_value=True)
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        assert z2.preset_mode == "boost"
        await z2.async_set_temperature(temperature=24.0)
        writes = [(c.args[0], c.args[1]) for c in coordinator.async_write_register.call_args_list]
        assert ("ctlv2", "Z2QuickVetoTemp") in writes
        assert ("ctlv2", "Z2QuickVetoDuration") not in writes


# Intent: the idle sentinel end date (01.01.2019) must never read as BOOST;
# a temperature change then starts a fresh veto like any auto-mode zone.
# Why: prevents the idle veto sentinel date from being misread as an active
# boost, which would hide the target and block a fresh veto.
async def test_past_sentinel_end_date_reports_no_boost() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(
            tmpdir,
            _graph_two_zone(),
            data={
                "ebusd": {
                    "ctlv2.Z2OpMode.value": "auto",
                    "ctlv2.Z2QuickVetoEndDate.value": "01.01.2019",
                    "ctlv2.Z2QuickVetoTemp.value": "21.0",
                }
            },
        )
        coordinator.async_write_register = AsyncMock(return_value=True)
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        assert z2.preset_mode == "none"
        await z2.async_set_temperature(temperature=22.0)
        calls = [(c.args[0], c.args[1], c.args[2]) for c in coordinator.async_write_register.call_args_list]
        assert ("ctlv2", "Z2QuickVetoTemp", "22.0") in calls
        assert ("ctlv2", "Z2QuickVetoDuration", "3") in calls


# Intent: A holiday period starting tomorrow reads preset "none", while a period bracketing today reads "away".
# Why: guards the date-window logic so scheduling a future absence does not immediately flip the zone into away mode.
def test_future_holiday_period_is_not_away_and_active_period_is_away() -> None:
    from datetime import date, timedelta

    today = date.today()
    future = {
        "ctlv2.Z1OpMode.value": "auto",
        "ctlv2.Z1HolidayStartPeriod.value": (today + timedelta(days=1)).strftime("%d.%m.%Y"),
        "ctlv2.Z1HolidayEndPeriod.value": (today + timedelta(days=7)).strftime("%d.%m.%Y"),
    }
    active = {
        "ctlv2.Z1OpMode.value": "auto",
        "ctlv2.Z1HolidayStartPeriod.value": (today - timedelta(days=1)).strftime("%d.%m.%Y"),
        "ctlv2.Z1HolidayEndPeriod.value": (today + timedelta(days=1)).strftime("%d.%m.%Y"),
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        future_zone = EbusdClimate(
            _coordinator(tmpdir, _graph_two_zone(), {"ebusd": future}), _entry(), "z1", "ctlv2"
        )
        active_zone = EbusdClimate(
            _coordinator(tmpdir, _graph_two_zone(), {"ebusd": active}), _entry(), "z1", "ctlv2"
        )

        assert future_zone.preset_mode == "none"
        assert active_zone.preset_mode == "away"


# Intent: boost on a zone with quick-veto support writes the zone's veto registers.
# Why: pins that the configured quick_veto_temp and duration reach the zone's own QuickVeto registers.
async def test_zone2_boost_writes_quick_veto() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(
            tmpdir,
            _graph_two_zone(),
            data={"ebusd": {"ctlv2.Z2RoomTemp.value": "20.5"}},
            options={"quick_veto_temp": 23.0},
        )
        coordinator.async_write_register = AsyncMock(return_value=True)
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        await z2.async_set_preset_mode("boost")
        calls = [(c.args[0], c.args[1], c.args[2]) for c in coordinator.async_write_register.call_args_list]
        assert ("ctlv2", "Z2QuickVetoTemp", "23.0") in calls
        assert ("ctlv2", "Z2QuickVetoDuration", "3") in calls


# Intent: COOL and BOOST are hidden for zones without the supporting registers.
# Why: prevents exposing cooling or boost controls the hardware cannot back with registers.
async def test_cool_and_boost_omitted_without_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_two_zone(full_parity=False))
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        z1 = EbusdClimate(coordinator, _entry(), "z1", "ctlv2")
        assert HVACMode.COOL not in z2.hvac_modes
        assert "boost" not in z2.preset_modes
        assert HVACMode.COOL not in z1.hvac_modes
        assert "boost" not in z1.preset_modes


# Intent: a zone with full parity offers COOL, HEAT, AUTO and all presets.
# Why: pins the exact mode and preset lists for a zone whose cooling and veto registers are discovered.
async def test_cool_and_boost_offered_with_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_two_zone(full_parity=True))
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        assert z2.hvac_modes == [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
        assert z2.preset_modes == ["none", "boost", "away"]


# Intent: single-zone systems keep exactly the legacy z1 entities and ids.
# Why: protects backwards-compatible entity ids and the "Home" name for existing single-zone installs.
async def test_single_zone_setup_keeps_z1_identity() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_single_zone(), _setup_data())
        hass = MagicMock()
        hass.data = {"vaillant_ebus": {"entry-1": coordinator}}
        added: list = []
        await CLIMATE.async_setup_entry(hass, _entry(), lambda entities: added.extend(entities))

        assert len(added) == 2
        assert added[0]._attr_unique_id == "entry-1_climate_z1"
        assert added[1]._attr_unique_id == "entry-1_climate_flow_temp_range"
        assert added[0]._attr_name == "Home"


# Intent: ghost zones (mapping "none", no live core data) get no climate entity.
# Why: stops an unused zone's static defaults from creating a phantom thermostat entity.
async def test_ghost_zone_gets_no_climate_entity() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_ghost_zone(), _setup_data())
        hass = MagicMock()
        hass.data = {"vaillant_ebus": {"entry-1": coordinator}}
        added: list = []
        await CLIMATE.async_setup_entry(hass, _entry(), lambda entities: added.extend(entities))

        assert len(added) == 2
        assert {e._attr_unique_id for e in added} == {
            "entry-1_climate_z1",
            "entry-1_climate_flow_temp_range",
        }


# Intent: with no discovery graph yet, setup falls back to z1 with full
# features (COOL/BOOST assumed present), preserving pre-per-zone behavior.
# Why: prevents a cold start before discovery from stripping COOL/BOOST off the legacy z1 entity.
async def test_setup_with_empty_graph_keeps_z1_full_features() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, None, _setup_data())
        hass = MagicMock()
        hass.data = {"vaillant_ebus": {"entry-1": coordinator}}
        added: list = []
        await CLIMATE.async_setup_entry(hass, _entry(), lambda entities: added.extend(entities))

        assert len(added) == 2
        z1 = added[0]
        assert z1._attr_unique_id == "entry-1_climate_z1"
        assert HVACMode.COOL in z1.hvac_modes
        assert "boost" in z1.preset_modes


# Intent: zones discovered after setup still get their climate entities via the
# post-discovery callback, so a fresh install does not require an entry reload.
# Why: ensures late-discovered zones are added live, without an integration reload.
async def test_post_discovery_adds_missing_zone_entities() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, None, _setup_data())
        hass = MagicMock()
        hass.data = {"vaillant_ebus": {"entry-1": coordinator}}
        added: list = []
        await CLIMATE.async_setup_entry(hass, _entry(), lambda entities: added.extend(entities))
        assert len(added) == 2

        graph = _graph_two_zone()
        coordinator._graph = graph
        coordinator._last_find_keys = set(graph.raw_registers)
        for callback in coordinator._post_discovery_callbacks:
            callback()

        assert len(added) == 4
        assert {e._attr_unique_id for e in added} == {
            "entry-1_climate_z1",
            "entry-1_climate_flow_temp_range",
            "entry-1_climate_z2",
            "entry-1_climate_flow_temp_range_z2",
        }


# Intent: a real but idle zone still gets a climate entity; reads are unavailable.
# Why: distinguishes a wired-but-idle zone (entity exists, values unknown) from a ghost zone (no entity).
async def test_real_idle_zone_gets_climate_entity() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_idle_zone(), {"ebusd": {"ctlv2.Z1RoomTemp.value": "21.5"}})
        hass = MagicMock()
        hass.data = {"vaillant_ebus": {"entry-1": coordinator}}
        added: list = []
        await CLIMATE.async_setup_entry(hass, _entry(), lambda entities: added.extend(entities))

        assert len(added) == 4
        z2 = next(e for e in added if e._attr_unique_id == "entry-1_climate_z2")
        assert z2.current_temperature is None
        assert z2.hvac_mode is None


# Intent: the per-zone flow range reads and writes the zone's HcN registers.
# Why: prevents the zone-2 flow range from reading or writing zone-1 HC registers.
async def test_flow_temp_range_zone2_reads_and_writes_hc2() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_two_zone(), _setup_data())
        coordinator.async_write_register = AsyncMock(return_value=True)
        r2 = EbusdFlowTempRange(coordinator, _entry(), "z2", "ctlv2")
        assert r2.current_temperature == 30.0
        assert r2._attr_unique_id == "entry-1_climate_flow_temp_range_z2"
        await r2.async_set_temperature(target_temp_low=25, target_temp_high=45)
        calls = [(c.args[0], c.args[1], c.args[2]) for c in coordinator.async_write_register.call_args_list]
        assert ("ctlv2", "Hc2MinFlowTempDesired", "25") in calls
        assert ("ctlv2", "Hc2MaxFlowTempDesired", "45") in calls


# Intent: hvac_action stays heat-pump-global while zone status gates it.
# Why: keeps hvac_action driven by the shared compressor status while the zone's
# Hc status decides whether it reports heating.
async def test_hvac_action_uses_shared_compressor_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(
            tmpdir,
            _graph_two_zone(),
            data={
                "ebusd": {
                    "hmu.RunDataStatuscode.value": "heat_compressor_active",
                    "ctlv2.Hc2Status.value": "1",
                    "ctlv2.Z2OpMode.value": "day",
                }
            },
        )
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        assert z2.hvac_action == HVACAction.HEATING


# Intent: manual cooling keeps the shared date register and writes the zone op mode.
# Why: pins manual cooling to the shared ManualCoolingEndDate plus the zone's own OpMode write.
async def test_zone2_manual_cooling_uses_shared_date() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_two_zone())
        coordinator.async_write_registers = AsyncMock(return_value=True)
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        await z2.async_set_hvac_mode(HVACMode.COOL)
        writes = coordinator.async_write_registers.await_args.args[0]
        expected_end = (datetime.now().date() + timedelta(days=3)).strftime("%d.%m.%Y")
        assert ("ctlv2", "ManualCoolingEndDate", expected_end) in writes
        assert ("ctlv2", "Z2OpMode", "auto") in writes


# Intent: The climate entity is available whenever the coordinator's last refresh succeeded.
# Why: decouples entity availability from per-register data so a zone with no live values still reports a state.
async def test_available_tracks_coordinator() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = _coordinator(tmpdir, _graph_two_zone())
        z2 = EbusdClimate(coordinator, _entry(), "z2", "ctlv2")
        assert z2.available is True
