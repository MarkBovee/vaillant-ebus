"""Unit tests for VaillantCoordinator — service orchestration."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import json
import struct
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.fake_ebusd import FakeEbusdServer, load_discovery_dump, load_find_lines

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"
BACKEND_PATH = COMPONENT_PATH / "backend"
HC_STATE_REGISTER_NAMES = (
    "Hc1FlowTempCalc",
    "Hc1MixerPosition",
    "Hc1Humidity",
    "Hc1DewPointTemp",
    "Hc1PumpHours",
    "Hc1PumpStarts",
    "Hc2FlowTempCalc",
    "Hc2MixerPosition",
    "Hc2Humidity",
    "Hc2DewPointTemp",
    "Hc2PumpHours",
    "Hc2PumpStarts",
)
for name in ("vaillant_ebus", "vaillant_ebus.backend"):
    pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    pkg.__path__ = [str(COMPONENT_PATH)] if name == "vaillant_ebus" else [str(BACKEND_PATH)]
    sys.modules[name] = pkg

MODELS_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.backend.models", BACKEND_PATH / "models.py")
assert MODELS_SPEC and MODELS_SPEC.loader
MODELS = importlib.util.module_from_spec(MODELS_SPEC)
sys.modules["vaillant_ebus.backend.models"] = MODELS
MODELS_SPEC.loader.exec_module(MODELS)

MAPPING_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.backend.mapping", BACKEND_PATH / "mapping.py")
assert MAPPING_SPEC and MAPPING_SPEC.loader
MAPPING = importlib.util.module_from_spec(MAPPING_SPEC)
sys.modules["vaillant_ebus.backend.mapping"] = MAPPING
MAPPING_SPEC.loader.exec_module(MAPPING)

EBUS_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.ebus_service", BACKEND_PATH / "ebus_service.py"
)
assert EBUS_SPEC and EBUS_SPEC.loader
EBUS = importlib.util.module_from_spec(EBUS_SPEC)
sys.modules["vaillant_ebus.backend.ebus_service"] = EBUS
EBUS_SPEC.loader.exec_module(EBUS)

FACTORY_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.entity_factory", BACKEND_PATH / "entity_factory.py"
)
assert FACTORY_SPEC and FACTORY_SPEC.loader
FACTORY = importlib.util.module_from_spec(FACTORY_SPEC)
sys.modules["vaillant_ebus.backend.entity_factory"] = FACTORY
FACTORY_SPEC.loader.exec_module(FACTORY)

DISCOVERY_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.discovery_service", BACKEND_PATH / "discovery_service.py"
)
assert DISCOVERY_SPEC and DISCOVERY_SPEC.loader
DISCOVERY = importlib.util.module_from_spec(DISCOVERY_SPEC)
sys.modules["vaillant_ebus.backend.discovery_service"] = DISCOVERY
DISCOVERY_SPEC.loader.exec_module(DISCOVERY)

ANALYSIS_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.analysis_service", BACKEND_PATH / "analysis_service.py"
)
assert ANALYSIS_SPEC and ANALYSIS_SPEC.loader
ANALYSIS = importlib.util.module_from_spec(ANALYSIS_SPEC)
sys.modules["vaillant_ebus.backend.analysis_service"] = ANALYSIS
ANALYSIS_SPEC.loader.exec_module(ANALYSIS)

from vaillant_ebus.backend.ebus_service import EbusService, WriteResult  # noqa: E402
from vaillant_ebus.backend.entity_factory import EntityFactoryService  # noqa: E402
from vaillant_ebus.backend.models import (  # noqa: E402
    DeviceGraph,
    DeviceNode,
    DeviceType,
    EbusdRegister,
    ResolutionStatus,
)

mock_homeassistant = MagicMock()
mock_homeassistant.config_entries = MagicMock()
mock_homeassistant.core = MagicMock()
mock_homeassistant.helpers = MagicMock()
mock_homeassistant.helpers.device_registry = MagicMock()
mock_homeassistant.helpers.event = MagicMock()
mock_homeassistant.helpers.update_coordinator = MagicMock()
mock_homeassistant.helpers.device_registry.DeviceInfo = dict


class _MockDataUpdateCoordinator:
    # Intent: initialize the published snapshot used by CoordinatorEntity lookups.
    # Why: tests for pushed updates must observe the same data contract as Home Assistant.
    def __init__(self, hass, logger, **kwargs) -> None:  # noqa: ARG002
        self.hass = hass
        self.name = kwargs.get("name", "")
        self.update_interval = kwargs.get("update_interval")
        self.data = None
        self.last_update_success = True
        self.listeners: list = []

    def async_update_listeners(self) -> None:
        pass

    # Intent: publish pushed data before notifying coordinator listeners.
    # Why: delayed discovery tests must observe cleared values in the same order as Home Assistant.
    def async_set_updated_data(self, data: dict[str, object]) -> None:
        self.data = data
        self.async_update_listeners()

    def __class_getitem__(cls, item):
        return cls

    def __call__(self, *args, **kwargs):
        return self


mock_homeassistant.helpers.update_coordinator.DataUpdateCoordinator = _MockDataUpdateCoordinator

sys.modules["homeassistant"] = mock_homeassistant
sys.modules["homeassistant.config_entries"] = mock_homeassistant.config_entries
sys.modules["homeassistant.core"] = mock_homeassistant.core
sys.modules["homeassistant.helpers"] = mock_homeassistant.helpers
mock_homeassistant.helpers.entity_registry = MagicMock()
mock_homeassistant.helpers.entity_registry.RegistryEntryDisabler = MagicMock(INTEGRATION="integration")
sys.modules["homeassistant.helpers.device_registry"] = mock_homeassistant.helpers.device_registry
sys.modules["homeassistant.helpers.entity_registry"] = mock_homeassistant.helpers.entity_registry
sys.modules["homeassistant.helpers.event"] = mock_homeassistant.helpers.event
sys.modules["homeassistant.helpers.update_coordinator"] = mock_homeassistant.helpers.update_coordinator
sys.modules["homeassistant.const"] = MagicMock()


repairs_module = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("vaillant_ebus.repairs", None))
repairs_module.async_dismiss_ebusd_unreachable = AsyncMock()
repairs_module.async_create_ebusd_unreachable = AsyncMock()
repairs_module.async_dismiss_detection_incomplete = AsyncMock()
sys.modules["vaillant_ebus.repairs"] = repairs_module

const_module = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("vaillant_ebus.const", None))
for attr, value in {
    "CONF_EBUSD_HOST": "ebusd_host",
    "CONF_EBUSD_PORT": "ebusd_port",
    "CONF_SCAN_INTERVAL": "scan_interval",
    "CONF_ENERGY_DIVISOR": "energy_counter_divisor",
    "DEFAULT_EBUSD_POLL_INTERVAL": 60,
    "DEFAULT_ENERGY_DIVISOR": 1.0,
    "DOMAIN": "vaillant_ebus",
}.items():
    setattr(const_module, attr, value)
sys.modules["vaillant_ebus.const"] = const_module

COORDINATOR_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.coordinator", COMPONENT_PATH / "coordinator.py"
)
assert COORDINATOR_SPEC and COORDINATOR_SPEC.loader
COORDINATOR = importlib.util.module_from_spec(COORDINATOR_SPEC)
sys.modules["vaillant_ebus.coordinator"] = COORDINATOR
COORDINATOR_SPEC.loader.exec_module(COORDINATOR)

from vaillant_ebus.coordinator import VaillantCoordinator, _register_values, _usable_register_value  # noqa: E402


def _hass(cache_dir: str) -> MagicMock:
    h = MagicMock()

    def _path(*parts: str) -> str:
        return str(Path(cache_dir) / "vaillant_ebus" / parts[-1])

    h.config.path.side_effect = _path
    h.async_create_task = MagicMock()

    async def _executor(func, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)

    h.async_add_executor_job = _executor
    return h


def _entry(host: str = "127.0.0.1", port: int = 8888, scan: int = 60) -> MagicMock:
    e = MagicMock()
    e.data = {
        "ebusd_host": host,
        "ebusd_port": port,
        "scan_interval": scan,
    }
    return e


def _make_graph(raw: dict[str, str] | None = None) -> DeviceGraph:
    nodes = {
        "hmu": DeviceNode(
            circuit="hmu",
            device_type=DeviceType.HEAT_PUMP,
            registers=["hmu.RunDataStatuscode", "hmu.OutsideTemp"],
            has_data=True,
            scan_type="HMU00",
            scan_sw="0514",
            scan_hw="1104",
        ),
        "ctlv2": DeviceNode(
            circuit="ctlv2",
            device_type=DeviceType.HEATING_CONTROLLER,
            registers=["ctlv2.Z1OpMode", "ctlv2.Z1DayTemp"],
            has_data=True,
            scan_type="CTLV2",
            scan_sw="0717",
            scan_hw="1504",
            parent="hmu",
        ),
    }
    raw_registers = raw or {
        "hmu.RunDataStatuscode": "standby",
        "hmu.OutsideTemp": "18.5",
        "ctlv2.Z1OpMode": "auto",
        "ctlv2.Z1DayTemp": "20.0",
    }
    return DeviceGraph(
        nodes=nodes,
        raw_registers=raw_registers,
        placeholder_registers=set(),
    )


# Intent: the coordinator builds an EntityFactoryService during construction.
# Why: entity generation depends on that factory existing; losing it breaks discovery-to-entities.
async def test_coordinator_creates_entity_factory() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert isinstance(c.entity_factory, EntityFactoryService)


# Intent: owner-dependent circuit properties remain unresolved before discovery.
# Why: startup must never target ctlv2 or hmu merely because no graph exists yet.
def test_circuit_properties_have_no_physical_defaults_before_discovery() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())

        assert coordinator.heating_circuit is None
        assert coordinator.heat_pump_circuit is None


# Intent: an optional config/vaillant_ebus/entities.yaml metadata override file
# is loaded into the yaml_overrides mapping used by entity generation.
# Why: the docs advertise the file, but the coordinator never read it, so
# overrides for names/icons/units/device_circuit were silently ignored (issue
# surfaced in discussion #31).
async def test_load_yaml_overrides_reads_entities_file(tmp_path: Path) -> None:
    override_dir = tmp_path / "vaillant_ebus"
    override_dir.mkdir()
    (override_dir / "entities.yaml").write_text(
        'hmu.CurrentConsumedPower:\n  friendly_name: "Power Right Now"\n  unit: "W"\n  entity_category: "diagnostic"\n',
        encoding="utf-8",
    )
    c = VaillantCoordinator(_hass(str(tmp_path)), _entry())
    overrides = await c._async_load_yaml_overrides()
    assert overrides == {
        "hmu.CurrentConsumedPower": {
            "friendly_name": "Power Right Now",
            "unit": "W",
            "entity_category": "diagnostic",
        }
    }


# Intent: a missing entities.yaml is not an error — an empty override mapping.
# Why: the file is optional; discovery and entity generation must always proceed.
async def test_load_yaml_overrides_missing_file_is_empty(tmp_path: Path) -> None:
    c = VaillantCoordinator(_hass(str(tmp_path)), _entry())
    assert await c._async_load_yaml_overrides() == {}


# Intent: the global Options Flow divisor works without an entities.yaml file.
# Why: the YAML file is optional; the setting must not silently become a no-op
# for users who configure the scale only through Home Assistant settings.
async def test_global_energy_divisor_applies_without_yaml_file(tmp_path: Path) -> None:
    entry = _entry()
    entry.options = {"energy_counter_divisor": 0.001}
    c = VaillantCoordinator(_hass(str(tmp_path)), entry)
    overrides = await c._async_load_yaml_overrides()
    assert overrides["hmu.HcElecConsDay"]["divisor"] == 0.001


# Intent: malformed YAML in entities.yaml yields an empty mapping, not a crash.
# Why: a user typo must not take down discovery; a warning is enough.
async def test_load_yaml_overrides_invalid_yaml_is_empty(tmp_path: Path) -> None:
    override_dir = tmp_path / "vaillant_ebus"
    override_dir.mkdir()
    (override_dir / "entities.yaml").write_text("hmu: [unclosed\n", encoding="utf-8")
    c = VaillantCoordinator(_hass(str(tmp_path)), _entry())
    assert await c._async_load_yaml_overrides() == {}


# Intent: the global Options Flow divisor still applies when entities.yaml is
# malformed and therefore cannot provide per-register overrides.
# Why: invalid optional YAML must not suppress a separately configured global
# setting or break discovery (issue #141).
async def test_global_energy_divisor_applies_with_invalid_yaml(tmp_path: Path) -> None:
    override_dir = tmp_path / "vaillant_ebus"
    override_dir.mkdir()
    (override_dir / "entities.yaml").write_text("hmu: [unclosed\n", encoding="utf-8")
    entry = _entry()
    entry.options = {"energy_counter_divisor": 0.001}
    c = VaillantCoordinator(_hass(str(tmp_path)), entry)
    overrides = await c._async_load_yaml_overrides()
    assert overrides["hmu.HcElecConsDay"]["divisor"] == 0.001


# Intent: the global Options Flow energy-counter divisor is applied to the
# Wh-declared b516 energy counters in the generated overrides.
# Why: local ebusd scaling of energy counters varies per install (issue #141);
# the divisor corrects it without a blanket unit change, and per-register
# entities.yaml divisor values win over the global setting.
async def test_global_energy_divisor_applied_unless_overridden(tmp_path: Path) -> None:
    override_dir = tmp_path / "vaillant_ebus"
    override_dir.mkdir()
    # User sets an explicit divisor for one register; the other is defaulted.
    (override_dir / "entities.yaml").write_text(
        "hmu.HcElecConsDay:\n  divisor: 2\n",
        encoding="utf-8",
    )
    entry = _entry()
    entry.options = {"energy_counter_divisor": 1000.0}
    c = VaillantCoordinator(_hass(str(tmp_path)), entry)
    overrides = await c._async_load_yaml_overrides()
    # Explicit per-register divisor wins over the global setting.
    assert overrides["hmu.HcElecConsDay"]["divisor"] == 2
    # Global divisor applied to the other energy counters.
    assert overrides["hmu.HcElecConsTotal"]["divisor"] == 1000
    assert overrides["hmu.CoolEnvYieldDay"]["divisor"] == 1000


# Intent: boiler (bai) and solar (sc) circuits get descriptive device names.
# Why: guards against raw circuit codes leaking into the Home Assistant UI.
async def test_device_names_for_bai_and_sc_are_descriptive() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.get_device_info("bai")["name"] == "Vaillant boiler controller"
        assert c.get_device_info("sc")["name"] == "Vaillant solar controller"


# Intent: the VWZ hydraulic station gets a descriptive English device name
# instead of the raw scan code, on an English Home Assistant.
# Why: device registry names are not translatable, so the default must read
# well; upstream calls the module a "Hydraulikstation".
async def test_device_names_for_vwz_are_descriptive() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.get_device_info("vwz")["name"] == "Vaillant Hydraulic Station"
        assert c.get_device_info("vwzio")["name"] == "Vaillant Hydraulic Station"


# Intent: a fresh coordinator starts with zero generated entities.
# Why: prevents entity creation during init before discovery or cache seeding runs.
async def test_coordinator_seeds_from_cache() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert len(c.entities) == 0


# Intent: cache seeding restores register values and their has_data flag.
# Why: protects offline restarts where cached values must survive before live ebusd data.
async def test_coordinator_seeds_from_cache_with_cached_values() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "vaillant_ebus" / "register_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache = {"hmu.FlowTemp.value": "38.5", "ctlv2.Z1DayTemp.value": "21.0"}
        cache_path.write_text(json.dumps(cache))

        hass = _hass(tmpdir)
        hass.config.path.return_value = str(cache_path)

        c = VaillantCoordinator(hass, _entry())
        await c._async_seed_entities_from_cache()
        assert c.registers.get("ctlv2.Z1DayTemp")
        assert c.registers["ctlv2.Z1DayTemp"].value.get("value") == "21.0"
        assert c.registers["ctlv2.Z1DayTemp"].has_data is True


# Intent: sentinel cache values (unknown/unavailable) are skipped while real values are kept.
# Why: stops stale no-data entries from being revived as normal sensors.
async def test_coordinator_does_not_seed_no_data_cache_values() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "vaillant_ebus" / "register_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "hmu.FlowTemp.value": "unknown",
                    "hmu.ReturnTemp.value": "unavailable",
                    "hmu.Status01.value": "22.0;22.0;-;-;-;off",
                }
            )
        )

        hass = _hass(tmpdir)
        hass.config.path.return_value = str(cache_path)
        coordinator = VaillantCoordinator(hass, _entry())
        await coordinator._async_seed_entities_from_cache()

        assert "hmu.FlowTemp" not in coordinator.registers
        assert "hmu.ReturnTemp" not in coordinator.registers
        assert "hmu.Status01" in coordinator.registers


# Intent: recover read-only Z2 entities from cache before ebusd completes discovery.
# Why: writable cached controls must wait for an authoritative owner graph.
async def test_coordinator_cache_seed_creates_active_z2_entities() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "vaillant_ebus" / "register_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "ctlv2.Z1RoomTemp.value": "21.5",
                    "ctlv2.Z1DayTemp.value": "22.0",
                    "ctlv2.Z1OpMode.value": "day",
                    "ctlv2.Z2RoomTemp.value": "20.5",
                    "ctlv2.Z2DayTemp.value": "21.0",
                    "ctlv2.Z2OpMode.value": "auto",
                    "ctlv2.Z2ActualRoomTempDesired.value": "21.0",
                }
            )
        )

        hass = _hass(tmpdir)
        hass.config.path.return_value = str(cache_path)
        coordinator = VaillantCoordinator(hass, _entry())
        await coordinator._async_seed_entities_from_cache()

        z2_entities = [entity for entity in coordinator.entities if entity.name.startswith("Z2")]
        assert {entity.name for entity in z2_entities} == {
            "Z2RoomTemp",
            "Z2OpMode",
            "Z2ActualRoomTempDesired",
        }
        assert {entity.device_circuit for entity in z2_entities} == {"z2"}


# Intent: generating entities from a two-node graph yields entities and resolves ctlv2 as heating circuit.
# Why: smoke test tying graph-to-entity generation to controller circuit resolution.
async def test_connect_and_discover_success() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        c = VaillantCoordinator(hass, _entry())
        graph = _make_graph()
        c.entities = c.entity_factory.generate(graph)
        c._graph = graph
        assert len(c.entities) > 0
        assert c.heating_circuit == "ctlv2"


# Intent: heat-pump circuit remains unresolved before discovery and resolves after a graph.
# Why: startup must not target hmu without discovered ownership.
async def test_heat_pump_circuit_resolves_from_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.heat_pump_circuit is None
        c._graph = _make_graph()
        assert c.heat_pump_circuit == "hmu"


# Intent: an HMUX0/CTLV3 installation resolves logical hmu/ctlv2 aliases to the discovered circuits.
# Why: protects HMUX0 heat pumps (issue #99 class hardware) from being driven via the hmu alias.
async def test_heat_pump_circuit_resolves_hmux0() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        graph = DeviceGraph(
            nodes={
                "hmux0": DeviceNode(
                    circuit="hmux0",
                    device_type=DeviceType.HEAT_PUMP,
                    registers=["hmux0.RunDataStatuscode", "hmux0.RunDataReturnTemp", "hmux0.YieldHc", "hmux0.CopHc"],
                    has_data=True,
                    scan_type="HMUX0",
                    scan_sw="0303",
                    scan_hw="0504",
                ),
                "ctlv3": DeviceNode(
                    circuit="ctlv3",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["ctlv3.Z1OpMode", "ctlv3.HwcStorageTemp", "ctlv3.HwcTempDesired", "ctlv3.HwcOpMode"],
                    has_data=True,
                    scan_type="CTLV3",
                    scan_sw="0808",
                    scan_hw="8004",
                    parent="hmux0",
                ),
            },
            raw_registers={
                "hmux0.RunDataStatuscode": "standby",
                "hmux0.RunDataReturnTemp": "28.2184",
                "hmux0.YieldHc": "4662",
                "hmux0.CopHc": "3.5",
                "ctlv3.Z1OpMode": "day",
                "ctlv3.HwcStorageTemp": "42.0",
                "ctlv3.HwcTempDesired": "50",
                "ctlv3.HwcOpMode": "auto",
            },
            placeholder_registers=set(),
        )
        c._graph = graph
        assert c.heat_pump_circuit == "hmux0"
        assert c.heating_circuit == "ctlv3"
        assert c.resolve_register_circuit("hmu") == "hmux0"
        assert c.resolve_register_circuit("ctlv2") == "ctlv3"


# Intent: expose ambiguous graph ownership without selecting a node by insertion order.
# Why: a deterministic AMBIGUOUS status stops callers from silently driving the wrong heat pump.
def test_graph_resolution_reports_ambiguous_heat_pump_owner() -> None:
    graph = DeviceGraph(
        nodes={
            "hmux0": DeviceNode("hmux0", DeviceType.HEAT_PUMP, scan_type="HMUX0"),
            "hmu1": DeviceNode("hmu1", DeviceType.HEAT_PUMP, scan_type="HMU00"),
            "hmu2": DeviceNode("hmu2", DeviceType.HEAT_PUMP, scan_type="HMU00"),
        },
        raw_registers={},
        placeholder_registers=set(),
    )

    resolution = graph.resolve_circuit_result("hmu")

    assert resolution.status == ResolutionStatus.AMBIGUOUS
    assert resolution.node is None
    assert resolution.circuit == "hmu"


# Intent: legacy resolve_circuit returns the input string while resolve_circuit_result reports MISSING.
# Why: preserves the backward-compatible string API while ownership-aware callers get an honest status.
def test_legacy_resolve_circuit_keeps_string_contract_without_ownership_authority() -> None:
    graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())

    assert graph.resolve_circuit("hmu") == "hmu"
    assert graph.resolve_circuit_result("hmu").status == ResolutionStatus.MISSING


# Intent: HMUX0 runtime definitions are emitted against the discovered hmux0 circuit, not hmu.
# Why: regression for issue #99 where HMUX0 hardware must not receive hmu alias definitions.
async def test_hmux0_runtime_definitions_use_discovered_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = AsyncMock()
        c.ebus.is_connected = True
        c._graph = DeviceGraph(
            nodes={
                "hmux0": DeviceNode(
                    circuit="hmux0",
                    device_type=DeviceType.HEAT_PUMP,
                    registers=[],
                    has_data=True,
                    scan_type="HMUX0",
                    scan_sw="0303",
                    scan_hw="0504",
                )
            },
            raw_registers={},
            placeholder_registers=set(),
        )
        c.ebus.define_register = AsyncMock(return_value="done")

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        hmux0 = [definition for definition in definitions if ",hmux0," in definition]
        assert len(hmux0) == 24
        assert all(",hmu," not in definition for definition in hmux0)
        assert any(",hmux0,RunDataReturnTemp," in definition for definition in hmux0)
        assert any(",hmux0,YieldHc," in definition for definition in hmux0)
        assert any(",hmux0,CopHwcMonth," in definition for definition in hmux0)
        assert any(",hmux0,HcElecConsDay," in definition for definition in hmux0)
        assert any(",hmux0,HwcElecConsTotal," in definition for definition in hmux0)
        # Confirmed 0303/0504 telemetry (upstream #249 / #522).
        assert any(",hmux0,Status00," in definition for definition in definitions)
        assert any(",hmux0,RunDataElPowerConsumption," in definition for definition in definitions)


# Intent: the discussion #32 HMUX0 SW0302/HW0504 fixture receives only the safe B509 telemetry definitions.
# Why: the target variant must gain its byte-correlated B509 values without
#      inheriting SW0303-only B511/B51A layouts.
async def test_issue32_hmux0_runtime_definitions_use_discovered_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml", after=True)
        )
        hmux0 = graph.nodes["hmux0"]
        assert hmux0.scan_type == "HMUX0"
        assert hmux0.scan_sw == "0302"
        assert hmux0.scan_hw == "0504"

        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c._graph = _make_graph()
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = graph

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        assert any(",hmux0,RunDataElPowerConsumption," in definition for definition in definitions)
        assert any(",hmux0,RunDataCompressorSpeed," in definition for definition in definitions)
        assert any(",hmux0,RunDataBuildingCPumpPower," in definition for definition in definitions)
        assert any(",B509,055402005b0d," in definition for definition in definitions)
        assert any(",B509,055402000d0a," in definition for definition in definitions)
        assert any(",B509,05540200c509," in definition for definition in definitions)
        assert not any(",hmu," in definition for definition in definitions)
        assert not any(",Status00," in definition for definition in definitions)


# Intent: issue #161 gateway frames are decoded passively on their exact discovered owners.
# Why: the HW0504 B511 counters are state-correlated, while active polling is not verified or required.
async def test_issue161_hmux0_sw0407_runtime_definitions_are_passive_and_scan_gated() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = "community/hmux0_issue161_2026-09-28_154109_discovery.yaml"
        find_lines = load_find_lines(fixture, after=True)
        find_lines.extend(
            [
                "scan.50 = MF=Vaillant;ID=CTLV2;SW=0514;HW=1104",
                "scan.50 = MF=Vaillant;ID=CTLV2;SW=0515;HW=1104",
                "scan.51 = MF=Vaillant;ID=CTLV2;SW=;HW=",
            ]
        )
        graph = DISCOVERY.DiscoveryService.build_device_graph(find_lines)
        heat_pump = graph.heat_pump_result().node
        assert heat_pump is not None
        assert (heat_pump.scan_type, heat_pump.scan_sw, heat_pump.scan_hw) == ("HMUX0", "0407", "0504")

        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator._graph = graph

        await coordinator._define_custom_registers()

        definitions = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        expected = {
            ("hmux0", "RunDataStatuscode", "f1", "08", "B509", "055402008813"),
            ("hmux0", "RunDataCompressorSpeed", "f1", "08", "B509", "055402000d0a"),
            ("hmux0", "RunDataElPowerConsumption", "f1", "08", "B509", "055402005b0d"),
            ("hmux0", "RunDataBuildingCPumpPower", "f1", "08", "B509", "05540200c509"),
            ("hmux0", "KmKreisVerflTemp", "f1", "08", "B51A", "05ff3546"),
            ("hmux0", "UnterkuehlungSoll", "f1", "08", "B51A", "05ff354a"),
            ("hmux0", "UnterkuehlungIst", "f1", "08", "B51A", "05ff354b"),
            ("hmux0", "EEVAuslassTemp", "f1", "08", "B51A", "05ff3702"),
            ("hmux0", "KmKreisKompEinlTemp", "f1", "08", "B51A", "05ff3704"),
            ("hmux0", "KmKreisKompAuslTemp", "f1", "08", "B51A", "05ff3705"),
            ("hmux0", "KmKreisHochdruck", "f1", "08", "B51A", "05ff370b"),
            ("vwzio", "PowerConsumptionVwz", "f1", "76", "B516", "14"),
            ("vwzio", "RunStatsImmersionHeaterHwc", "f1", "76", "B511", "021802"),
        }
        actual = set()
        for definition in definitions:
            fields = definition.split(",")
            if len(fields) > 7 and fields[0] == "u":
                actual.add((fields[1], fields[2], fields[4], fields[5], fields[6], fields[7]))
        assert expected <= actual
        assert not any(",B511,021801," in definition for definition in definitions)
        stats_definition = next(
            definition for definition in definitions if ",RunStatsImmersionHeaterHwc," in definition
        )
        assert stats_definition.startswith(
            "u,vwzio,RunStatsImmersionHeaterHwc,RunStatsImmersionHeaterHwc,f1,76,B511,021802,"
        )
        assert "ign,,IGN:1,,,,runtime,,ULG,,min,,cycles,,ULG" in stats_definition
        assert not any(
            fields[0] == "r" and fields[1] == "hmux0" and fields[2] in {entry[1] for entry in expected}
            for fields in (definition.split(",") for definition in definitions)
        )
        for name in (
            "KmKreisVerflTemp",
            "UnterkuehlungSoll",
            "UnterkuehlungIst",
            "EEVAuslassTemp",
            "KmKreisKompEinlTemp",
            "KmKreisKompAuslTemp",
            "KmKreisHochdruck",
        ):
            assert MAPPING.REGISTER_MAP[f"hmux0.{name}"].fallback_read is False
        assert MAPPING.REGISTER_MAP["vwzio.PowerConsumptionVwz"].fallback_read is False
        assert MAPPING.REGISTER_MAP["vwzio.RunStatsImmersionHeaterHwc"].fallback_read is False
        assert not any(definition.startswith("r,vwzio,Status01,") for definition in definitions)
        coordinator._last_find_keys = set()
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        await coordinator._fallback_read(include_placeholders=True)
        assert not any(call.args == ("vwzio", "Status01") for call in coordinator.ebus.read_register.await_args_list)
        assert ("vwzio", "RunStatsImmersionHeaterHwc") not in [
            call.args[:2] for call in coordinator.ebus.read_register.await_args_list
        ]

        nonmatching_lines = [
            line.replace("VWZIO;0500;0504", "VWZIO;0902;5103") if line.strip().startswith("scan.76 ") else line
            for line in load_find_lines(fixture, after=True)
        ]
        nonmatching_graph = DISCOVERY.DiscoveryService.build_device_graph(nonmatching_lines)
        assert "vwzio" not in nonmatching_graph.nodes
        other = VaillantCoordinator(_hass(tmpdir), _entry())
        other.ebus = MagicMock(spec=EbusService)
        other.ebus.is_connected = True
        other.ebus.define_register = AsyncMock(return_value="done")
        other.ebus.read_register = AsyncMock(return_value=None)
        other._graph = nonmatching_graph
        await other._define_custom_registers()
        other_definitions = [call.args[0] for call in other.ebus.define_register.await_args_list]
        assert not any(",PowerConsumptionVwz," in definition for definition in other_definitions)
        assert not any(",RunStatsImmersionHeaterHwc," in definition for definition in other_definitions)
        other._last_find_keys = set(nonmatching_graph.raw_registers) | set(nonmatching_graph.placeholder_registers)
        await other._fallback_read(include_placeholders=True, include_energy=True)
        assert ("vwzio", "RunStatsImmersionHeaterHwc") not in [
            call.args[:2] for call in other.ebus.read_register.await_args_list
        ]


# Intent: a rejected passive HWC counter definition never falls back to an active read or fabricated entity.
# Why: this HW0504 layout is supported only by observed gateway traffic, and no-data must remain unavailable.
async def test_issue161_vwzio_hwc_stats_failed_definition_stays_passive() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = "community/hmux0_issue161_2026-09-28_154109_discovery.yaml"
        graph = DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="ERR: unsupported")
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._graph = graph

        await coordinator._define_custom_registers()
        assert any(
            call.args[0].startswith("u,vwzio,RunStatsImmersionHeaterHwc,")
            for call in coordinator.ebus.define_register.await_args_list
        )
        coordinator._last_find_keys = set(graph.raw_registers) | set(graph.placeholder_registers)
        await coordinator._fallback_read(include_placeholders=True, include_energy=True)

        assert ("vwzio", "RunStatsImmersionHeaterHwc") not in [
            call.args[:2] for call in coordinator.ebus.read_register.await_args_list
        ]
        assert "vwzio.RunStatsImmersionHeaterHwc" not in graph.raw_registers
        entity_keys = {entity.key for entity in EntityFactoryService().generate(graph)}
        assert not any(key.startswith("vwzio.RunStatsImmersionHeaterHwc") for key in entity_keys)


# Intent: a VWZIO SW0500/HW0504 scan at 0x77 cannot authorize slave-0x76 definitions or reads.
# Why: another scanned VWZ-family station may occupy 0x76, so circuit role alone is not address ownership.
async def test_issue161_vwzio_definition_and_fallback_require_scan_address_76(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "scan.76 = MF=Vaillant;ID=VWZ00;SW=0522;HW=5103",
                "scan.77 = MF=Vaillant;ID=VWZIO;SW=0500;HW=0504",
                "vwz Status01 = no data stored",
                "vwzio Status01 = no data stored",
                "vwzio RunStatsImmersionHeaterHwc = no data stored",
            ]
        )
        assert graph.nodes["vwz"].scan_address.casefold() == "scan.76"
        assert graph.nodes["vwzio"].scan_address.casefold() == "scan.77"
        assert MAPPING.vwzio_sw0500_circuit(graph) is None

        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._graph = graph

        await coordinator._define_custom_registers()
        definitions = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        assert not any(definition.startswith("u,vwzio,RunStatsImmersionHeaterHwc,") for definition in definitions)
        assert not any(definition.startswith("r,vwzio,Status01,") for definition in definitions)
        assert any(definition.startswith("r,vwz,Status01,") for definition in definitions)

        monkeypatch.setitem(
            COORDINATOR.REGISTER_MAP,
            "vwzio.RunStatsImmersionHeaterHwc",
            MAPPING.RegisterMeta(fallback_read=True),
        )
        coordinator._last_find_keys = set(graph.raw_registers)
        await coordinator._fallback_read(include_placeholders=True)
        read_calls = [call.args[:2] for call in coordinator.ebus.read_register.await_args_list]
        assert ("vwzio", "Status01") not in read_calls
        assert ("vwzio", "RunStatsImmersionHeaterHwc") not in read_calls
        assert ("vwz", "Status01") in read_calls


# Intent: stale station scan identity cannot survive a later graph with no station node or ambiguous scans.
# Why: a cached prior 0x76 address is not current authority for definitions against the live bus.
def test_merge_device_graphs_replaces_current_vwzio_scan_authority() -> None:
    previous = DISCOVERY.DiscoveryService.build_device_graph(
        [
            "scan.76 = MF=Vaillant;ID=VWZIO;SW=0500;HW=0504",
            "vwzio Status01 = no data stored",
        ]
    )
    assert MAPPING.vwzio_sw0500_circuit(previous) == "vwzio"

    missing = DISCOVERY.DiscoveryService.build_device_graph(
        ["scan.15 = MF=Vaillant;ID=CTLV2;SW=0514;HW=1104", "ctlv2 Z1OpMode = auto"]
    )
    merged_missing = COORDINATOR._merge_device_graphs(previous, missing)
    assert "vwzio" in merged_missing.nodes
    assert [(scan.address, scan.scan_type) for scan in merged_missing.scan_identities] == [("scan.15", "CTLV2")]
    assert MAPPING.vwzio_sw0500_circuit(merged_missing) is None

    conflict = DISCOVERY.DiscoveryService.build_device_graph(
        [
            "scan.76 = MF=Vaillant;ID=VWZIO;SW=0500;HW=0504",
            "scan.77 = MF=Vaillant;ID=VWZIO;SW=0500;HW=0504",
            "vwzio Status01 = no data stored",
        ]
    )
    merged_conflict = COORDINATOR._merge_device_graphs(previous, conflict)
    assert MAPPING.vwzio_sw0500_circuit(merged_conflict) is None


# Intent: the evidence-backed HW5103 Status01 path remains active only on its discovered 0x76 owner.
# Why: address gating must reject wrong slaves without disabling the verified station layout.
async def test_vwzio_status01_fallback_allows_hw5103_owner_at_address76() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
                "scan.50 = MF=Vaillant;ID=CTLV2;SW=0514;HW=1104",
                "scan.50 = MF=Vaillant;ID=CTLV2;SW=0515;HW=1104",
                "scan.51 = MF=Vaillant;ID=CTLV2;SW=;HW=",
                "vwzio Status01 = no data stored",
            ]
        )
        assert graph.nodes["vwzio"].scan_address.casefold() == "scan.76"

        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._graph = graph

        await coordinator._define_custom_registers()
        definitions = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        assert any(definition.startswith("r,vwzio,Status01,") for definition in definitions)

        coordinator._last_find_keys = set(graph.raw_registers) | set(graph.placeholder_registers)
        await coordinator._fallback_read(include_placeholders=True)
        assert ("vwzio", "Status01") in [call.args[:2] for call in coordinator.ebus.read_register.await_args_list]


# Intent: partial identity at the target address blocks station definitions and coordinator fallback reads.
# Why: a complete row cannot authorize slave 0x76 when another recognized row contradicts its identity.
async def test_partial_conflicting_scan_at_address76_blocks_status_definition_and_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
                "scan.76 = MF=Vaillant;ID=VWZ00;SW=;HW",
                "vwzio Status01 = no data stored",
            ]
        )
        assert MAPPING.vwz_station_scan_76_circuit(graph) is None

        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._graph = graph

        await coordinator._define_custom_registers()
        definitions = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        assert not any(definition.startswith("r,vwzio,Status01,") for definition in definitions)

        coordinator._last_find_keys = set(graph.raw_registers) | set(graph.placeholder_registers)
        await coordinator._fallback_read(include_placeholders=True)
        assert ("vwzio", "Status01") not in [call.args[:2] for call in coordinator.ebus.read_register.await_args_list]


# Intent: a ready coordinator applies each usable live scan snapshot before any active fallback read.
# Why: cached graph ownership must not survive a newly observed partial conflict at the fixed station address.
async def test_ready_coordinator_refreshes_scan_snapshot_before_status_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.last_find_usable = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator.ebus.find_registers = AsyncMock(
            return_value=[
                "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
                "scan.76 = MF=Vaillant;ID=VWZ00;SW=;HW",
            ]
        )
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._cache_seeded = coordinator._ebusd_connected = True
        coordinator._last_energy_poll = datetime.min
        coordinator._last_placeholder_poll = datetime.min
        coordinator._graph = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
                "vwzio Status01 = no data stored",
            ]
        )

        await coordinator._async_update_data()

        assert MAPPING.vwz_station_scan_76_circuit(coordinator._graph) is None
        assert not any(
            call.args[0].startswith("r,vwzio,Status01,") for call in coordinator.ebus.define_register.await_args_list
        )
        assert ("vwzio", "Status01") not in [call.args[:2] for call in coordinator.ebus.read_register.await_args_list]


# Intent: preserve current ownership and avoid fallback reads when the live find is unusable.
# Why: malformed/error-only responses cannot replace the last usable scan snapshot or authorize polling.
async def test_ready_coordinator_unusable_live_find_keeps_scan_snapshot_and_skips_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.last_find_usable = False
        coordinator.ebus.find_registers = AsyncMock(return_value=["ERR: response unavailable"])
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._cache_seeded = coordinator._ebusd_connected = True
        coordinator._last_energy_poll = datetime.min
        coordinator._graph = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
                "vwzio Status01 = no data stored",
            ]
        )
        previous_scan_snapshot = coordinator._graph.scan_identities

        await coordinator._async_update_data()

        assert coordinator._graph.scan_identities == previous_scan_snapshot
        assert MAPPING.vwz_station_scan_76_circuit(coordinator._graph) == "vwzio"
        coordinator.ebus.define_register.assert_not_awaited()
        coordinator.ebus.read_register.assert_not_awaited()


# Intent: skip active fallbacks when the follow-up find after new definitions is unusable.
# Why: runtime definitions must not turn an error-only response into stale-graph polling authority.
async def test_unusable_post_definition_find_skips_fallback_and_keeps_usable_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._cache_seeded = coordinator._ebusd_connected = True
        coordinator._last_energy_poll = datetime.min
        coordinator._last_placeholder_poll = datetime.min
        coordinator._graph = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
                "vwzio Status01 = no data stored",
            ]
        )
        current_lines = [
            "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
            "vwzio Status01 = no data stored",
        ]
        responses = iter(((current_lines, True), (["ERR: response unavailable"], False)))

        # Intent: expose the validity result associated with each sequential fake find response.
        # Why: the poll must distinguish its usable pre-definition snapshot from a failed follow-up.
        async def _find_registers() -> list[str]:
            lines, usable = next(responses)
            coordinator.ebus.last_find_usable = usable
            return lines

        coordinator.ebus.find_registers = AsyncMock(side_effect=_find_registers)

        await coordinator._async_update_data()

        assert MAPPING.vwz_station_scan_76_circuit(coordinator._graph) == "vwzio"
        assert coordinator.ebus.find_registers.await_count == 2
        assert coordinator.ebus.define_register.await_count > 0
        coordinator.ebus.read_register.assert_not_awaited()


# Intent: merge post-definition scan evidence before initial entity fallback handling.
# Why: a node-empty usable follow-up must revoke stale station ownership; an unusable one must never poll it.
async def test_initial_setup_post_definition_find_refreshes_scan_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    for followup_usable in (True, False):
        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
            initial_graph = DISCOVERY.DiscoveryService.build_device_graph(
                [
                    "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
                    "vwzio Status01 = no data stored",
                ]
            )
            post_definition_graph = (
                DISCOVERY.DiscoveryService.build_device_graph(["scan.76 = MF=Vaillant;ID=VWZ00;SW=;HW"])
                if followup_usable
                else MODELS.DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
            )
            ebus = MagicMock(spec=EbusService)
            ebus.is_connected = True
            ebus.version = "ebusd 26.1"
            ebus.last_find_usable = True
            ebus.connect = AsyncMock()
            ebus.disconnect = AsyncMock()
            ebus.define_register = AsyncMock(return_value="done")
            ebus.read_register = AsyncMock(return_value=None)
            graphs = iter((initial_graph, post_definition_graph))
            validities = iter((True, followup_usable))
            discovery = MagicMock()

            # Intent: pair each fake graph with the transport's current find-validity state.
            # Why: setup behavior differs for a usable partial scan and an unusable follow-up response.
            async def _discover() -> MODELS.DeviceGraph:
                ebus.last_find_usable = next(validities)
                return next(graphs)

            discovery.discover = AsyncMock(side_effect=_discover)
            monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
            monkeypatch.setattr(COORDINATOR, "DiscoveryService", MagicMock(return_value=discovery))
            monkeypatch.setattr(COORDINATOR.repairs, "async_dismiss_ebusd_unreachable", AsyncMock())
            monkeypatch.setattr(COORDINATOR.repairs, "async_dismiss_detection_incomplete", AsyncMock())
            coordinator._schedule_delayed_rediscovery = MagicMock()
            coordinator._schedule_analysis = MagicMock()
            applied_graphs: list[MODELS.DeviceGraph] = []

            # Intent: exercise the initial graph's actual fallback decision without unrelated HA entity setup.
            # Why: this test isolates whether post-definition scan evidence reaches the active-read gate.
            async def _apply_graph(graph: MODELS.DeviceGraph, source: str) -> None:
                assert source == "initial"
                coordinator._graph = graph
                applied_graphs.append(graph)
                await coordinator._fallback_read(include_placeholders=True)

            coordinator._apply_discovery_graph = AsyncMock(side_effect=_apply_graph)

            await coordinator._ebusd_connect_and_discover()

            definitions = [call.args[0] for call in ebus.define_register.await_args_list]
            assert any(definition.startswith("r,vwzio,Status01,") for definition in definitions)
            assert applied_graphs
            if followup_usable:
                assert MAPPING.vwz_station_scan_76_circuit(applied_graphs[-1]) is None
            else:
                assert MAPPING.vwz_station_scan_76_circuit(applied_graphs[-1]) == "vwzio"
            assert ("vwzio", "Status01") not in [call.args[:2] for call in ebus.read_register.await_args_list]


# Intent: define SW0407 layouts from their unique scan despite ambiguous heat-pump role resolution.
# Why: a second heat pump must not suppress target registers or redirect definitions to the wrong circuit.
async def test_issue161_sw0407_passive_definitions_survive_other_heat_pump_node() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        lines = load_find_lines("community/hmux0_issue161_2026-09-28_154109_discovery.yaml", after=True)
        lines.extend(
            [
                "scan.09 = Vaillant;HMU00;0308;0403",
                "hmu FlowTemp = 30.0",
            ]
        )
        graph = DISCOVERY.DiscoveryService.build_device_graph(lines)
        assert graph.heat_pump_result().status == ResolutionStatus.AMBIGUOUS
        assert MAPPING.hmux0_sw0407_circuit(graph) == "hmux0"
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator._graph = graph

        await coordinator._define_custom_registers()

        definitions = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        assert any(definition.startswith("u,hmux0,RunDataStatuscode,") for definition in definitions)
        assert not any(definition.startswith("u,hmu,") for definition in definitions)
        for name in MAPPING.HMUX0_SW0407_ENVYIELD_REGISTERS:
            assert any(definition.startswith(f"r,hmux0,{name},") for definition in definitions)


# Intent: issue #32's SW0302 map retains its existing active B509 path and gains no SW0407-only passive layouts.
# Why: passive telemetry support is gated to the firmware captured in issue #161.
async def test_issue161_passive_hmux0_definitions_do_not_generalize_to_sw0302() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml", after=True)
        )
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator._graph = graph

        await coordinator._define_custom_registers()

        definitions = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        assert graph.nodes["hmux0"].scan_sw == "0302"
        assert any(",B509,055402005b0d," in definition for definition in definitions)
        assert not any(definition.startswith("u,hmux0,") for definition in definitions)
        for name in MAPPING.HMUX0_SW0407_ENVYIELD_REGISTERS:
            assert not any(f",{name}," in definition for definition in definitions)
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._last_find_keys = set(graph.raw_registers) | set(graph.placeholder_registers)
        await coordinator._fallback_read(include_placeholders=True, include_energy=True)
        assert any(
            call.args == ("hmux0", "RunDataElPowerConsumption")
            for call in coordinator.ebus.read_register.await_args_list
        )
        for name in MAPPING.HMUX0_SW0407_ENVYIELD_REGISTERS:
            assert ("hmux0", name) not in [call.args for call in coordinator.ebus.read_register.await_args_list]
        for register in ("HcElecConsDay", "HwcElecConsDay"):
            assert ("hmux0", register) in [call.args for call in coordinator.ebus.read_register.await_args_list]

        sw0303_graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/hmux0_issue99_2026-09-10_173229.yaml", after=True)
        )
        sw0303 = VaillantCoordinator(_hass(tmpdir), _entry())
        sw0303.ebus = MagicMock(spec=EbusService)
        sw0303.ebus.is_connected = True
        sw0303.ebus.define_register = AsyncMock(return_value="done")
        sw0303.ebus.read_register = AsyncMock(return_value=None)
        sw0303._graph = sw0303_graph
        await sw0303._define_custom_registers()
        assert sw0303_graph.nodes["hmux0"].scan_sw == "0303"
        assert any(",B509,055402005b0d," in call.args[0] for call in sw0303.ebus.define_register.await_args_list)
        for name in MAPPING.HMUX0_SW0407_ENVYIELD_REGISTERS:
            assert not any(f",{name}," in call.args[0] for call in sw0303.ebus.define_register.await_args_list)
        sw0303._last_find_keys = set(sw0303_graph.raw_registers) | set(sw0303_graph.placeholder_registers)
        await sw0303._fallback_read(include_energy=True)
        for name in MAPPING.HMUX0_SW0407_ENVYIELD_REGISTERS:
            assert ("hmux0", name) not in [call.args for call in sw0303.ebus.read_register.await_args_list]
        for register in ("HcElecConsDay", "HwcElecConsDay"):
            assert ("hmux0", register) in [call.args for call in sw0303.ebus.read_register.await_args_list]


# Intent: SW0407 map probes for unsupported B51A names and passive definitions never become active fallback reads.
# Why: the complete issue #161 dump records these B51A probes as unavailable, while only B516 reads stay active.
async def test_issue161_hmux0_sw0407_fallback_skips_unverified_b51a_and_passive_u() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = "community/hmux0_issue161_2026-09-28_154109_discovery.yaml"
        graph = DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._graph = graph

        await coordinator._define_custom_registers()
        definitions = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        yield_definitions = [
            definition
            for definition in definitions
            if any(f",{name}," in definition for name in MAPPING.HMUX0_SW0407_ENVYIELD_REGISTERS)
        ]
        assert len(yield_definitions) == len(MAPPING.HMUX0_SW0407_ENVYIELD_REGISTERS)
        assert all(definition.startswith("r,hmux0,") for definition in yield_definitions)
        coordinator._last_find_keys = set()
        await coordinator._fallback_read(include_placeholders=True, include_energy=True)

        read_calls = coordinator.ebus.read_register.await_args_list
        passive_names = {
            "RunDataStatuscode",
            "RunDataCompressorSpeed",
            "RunDataElPowerConsumption",
            "RunDataBuildingCPumpPower",
            "KmKreisVerflTemp",
            "UnterkuehlungSoll",
            "UnterkuehlungIst",
            "EEVAuslassTemp",
            "KmKreisKompEinlTemp",
            "KmKreisKompAuslTemp",
            "KmKreisHochdruck",
            "PowerConsumptionVwz",
            "RunStatsImmersionHeaterHwc",
        }
        blocked_b51a_names = {
            "BuildingCircuitFlow",
            "CopCooling",
            "CopCoolingMonth",
            "CopHc",
            "CopHcMonth",
            "CopHwc",
            "CopHwcMonth",
            "CurrentCompressorUtil",
            "CurrentConsumedPower",
            "CurrentYieldPower",
            "FlowTemp",
            "FlowTemperature",
            "HoursCool",
            "LiveMonitorCurrentConsumedPower",
            "SourceTempInput",
            "SourceTempOutput",
            "TotalEnergyUsage",
            "YieldCoolDay",
            "YieldCooling",
            "YieldCoolingMonth",
            "YieldHc",
            "YieldHcDay",
            "YieldHcMonth",
            "YieldHwc",
            "YieldHwcDay",
            "YieldHwcMonth",
        }
        blocked_hmux0_names = passive_names | blocked_b51a_names | {"Status00", "Status01", "Status07"}
        blocked_reads = [
            call.args
            for call in read_calls
            if call.args[0].casefold() == "hmux0" and call.args[1] in blocked_hmux0_names
        ]
        assert not blocked_reads, blocked_reads
        for register in ("HcElecConsDay", "HwcElecConsDay"):
            assert ("hmux0", register) in [call.args for call in read_calls]
        for register in MAPPING.HMUX0_SW0407_ENVYIELD_REGISTERS:
            assert ("hmux0", register) in [call.args for call in read_calls]


# Intent: failed passive definitions cannot make the integration actively probe their telegrams as a fallback.
# Why: safety depends on the exact firmware gate, not on ebusd accepting each optional definition.
async def test_issue161_failed_passive_definitions_still_skip_active_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/hmux0_issue161_2026-09-28_154109_discovery.yaml", after=True)
        )
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="ERR: unsupported")
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._graph = graph

        await coordinator._define_custom_registers()
        assert not coordinator._runtime_definitions
        coordinator._last_find_keys = set()
        await coordinator._fallback_read(include_placeholders=True, include_energy=True)

        calls = [call.args for call in coordinator.ebus.read_register.await_args_list]
        for name in MAPPING.HMUX0_SW0407_ENVYIELD_REGISTERS:
            assert ("hmux0", name) not in calls
        for name in (
            "RunDataStatuscode",
            "RunDataCompressorSpeed",
            "RunDataElPowerConsumption",
            "RunDataBuildingCPumpPower",
            "KmKreisVerflTemp",
            "UnterkuehlungSoll",
            "UnterkuehlungIst",
            "EEVAuslassTemp",
            "KmKreisKompEinlTemp",
            "KmKreisKompAuslTemp",
            "KmKreisHochdruck",
            "Status00",
            "Status01",
            "Status07",
        ):
            assert ("hmux0", name) not in calls
        for name in ("HcElecConsDay", "HwcElecConsDay"):
            assert ("hmux0", name) in calls


# Intent: the SW0407-only fallback exclusion does not suppress any mapped register on SW0302 or SW0303.
# Why: the new guard is hardware-specific and must preserve legacy fallback behavior on supported variants.
async def test_issue161_fallback_exclusions_do_not_apply_to_sw0302_or_sw0303() -> None:
    names = {
        "Status00",
        "Status01",
        "Status07",
        "BuildingCircuitFlow",
        "CopCooling",
        "CopCoolingMonth",
        "CopHc",
        "CopHcMonth",
        "CopHwc",
        "CopHwcMonth",
        "CurrentCompressorUtil",
        "CurrentConsumedPower",
        "CurrentYieldPower",
        "FlowTemp",
        "FlowTemperature",
        "HoursCool",
        "LiveMonitorCurrentConsumedPower",
        "SourceTempInput",
        "SourceTempOutput",
        "TotalEnergyUsage",
        "YieldCoolDay",
        "YieldCooling",
        "YieldCoolingMonth",
        "YieldHc",
        "YieldHcDay",
        "YieldHcMonth",
        "YieldHwc",
        "YieldHwcDay",
        "YieldHwcMonth",
    }
    test_map = {f"hmux0.{name}": MAPPING.RegisterMeta(enabled=True, fallback_read=True) for name in names}
    original_map = COORDINATOR.REGISTER_MAP
    COORDINATOR.REGISTER_MAP = test_map
    try:
        for fixture, expected_sw in (
            ("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml", "0302"),
            ("community/hmux0_issue99_2026-09-10_173229.yaml", "0303"),
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                graph = DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
                assert graph.nodes["hmux0"].scan_sw == expected_sw
                graph.raw_registers = {}
                graph.placeholder_registers = {f"hmux0.{name}" for name in names}
                coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
                coordinator.ebus = MagicMock(spec=EbusService)
                coordinator.ebus.is_connected = True
                coordinator.ebus.read_register = AsyncMock(return_value=None)
                coordinator._graph = graph

                await coordinator._fallback_read(include_placeholders=True)

                actual = {call.args for call in coordinator.ebus.read_register.await_args_list}
                assert actual == {("hmux0", name) for name in names}
    finally:
        COORDINATOR.REGISTER_MAP = original_map


# Intent: a usable incomplete HMUX0 scan blocks fallback reads despite retained SW0303 metadata.
# Why: the current scan snapshot, not a stale node identity, decides whether the firmware blocklist applies.
async def test_issue161_incomplete_hmux0_scan_blocks_stale_sw0303_fallback() -> None:
    original_map = COORDINATOR.REGISTER_MAP
    COORDINATOR.REGISTER_MAP = {"hmux0.FlowTemp": MAPPING.RegisterMeta(enabled=True, fallback_read=True)}
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            graph = DISCOVERY.DiscoveryService.build_device_graph(
                load_find_lines("community/hmux0_issue99_2026-09-10_173229.yaml", after=True)
            )
            graph.raw_registers.pop("hmux0.FlowTemp", None)
            graph.placeholder_registers.discard("hmux0.FlowTemp")
            coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
            coordinator.ebus = MagicMock(spec=EbusService)
            coordinator.ebus.is_connected = True
            coordinator.ebus.read_register = AsyncMock(return_value=None)
            coordinator._ebusd_connected = True
            coordinator._graph = graph
            coordinator._last_find_keys = set()

            assert graph.nodes["hmux0"].scan_sw == "0303"
            await coordinator._fallback_read()
            assert ("hmux0", "FlowTemp") in [call.args for call in coordinator.ebus.read_register.await_args_list]

            coordinator.ebus.read_register.reset_mock()
            await coordinator._refresh_graph_from_usable_find(["scan.08 = Vaillant;HMUX0;0303"])

            assert coordinator._graph is not None
            assert coordinator._graph.nodes["hmux0"].scan_sw == "0303"
            assert any(
                not row.complete and row.scan_type.casefold() == "hmux0" for row in coordinator._graph.scan_identities
            )
            assert MAPPING.hmux0_sw0407_circuit(coordinator._graph) is None
            assert MAPPING.hmux0_uncertain_scan_circuits(coordinator._graph) == frozenset({"hmux0"})

            await coordinator._fallback_read()

            assert ("hmux0", "FlowTemp") not in [call.args for call in coordinator.ebus.read_register.await_args_list]
    finally:
        COORDINATOR.REGISTER_MAP = original_map


# Intent: the complete #32 capture decodes the three B509 EXP responses at their documented offsets.
# Why: definition-string tests alone cannot detect a shifted field or wrong datatype in a real telegram.
def test_issue32_b509_exp_responses_decode_at_expected_offsets() -> None:
    dump = load_discovery_dump("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml")
    rows = {item["request"]: item for item in dump["unknown_telegrams"]}

    expected = {
        "f108b509055402005b0d": 9.0,
        "f108b509055402000d0a": 0.0,
        "f108b50905540200c509": 0.0,
    }
    for request, value in expected.items():
        response = rows[request]["resp"]
        assert response is not None
        assert struct.unpack("<f", bytes.fromhex(response[-8:]))[0] == value


# Intent: failed B509 fallback reads use the discovered hmux0 owner and clear stale values.
# Why: a new logical hmu mapping must not poll an alias or resurrect an old cached power value.
async def test_issue32_b509_fallback_reads_resolved_hmux0_and_clears_stale_values() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml", after=True)
        )
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.read_register = AsyncMock(return_value=None)
        c._graph = graph
        c._last_find_keys = set(graph.raw_registers) | set(graph.placeholder_registers)
        for name in ("RunDataElPowerConsumption", "RunDataCompressorSpeed", "RunDataBuildingCPumpPower"):
            c.registers[f"hmux0.{name}"] = EbusdRegister(
                circuit="hmux0",
                name=name,
                fields=["value"],
                value={"value": "123"},
                has_data=True,
            )

        await c._fallback_read()

        calls = c.ebus.read_register.await_args_list
        for name in ("RunDataElPowerConsumption", "RunDataCompressorSpeed", "RunDataBuildingCPumpPower"):
            assert any(call.args == ("hmux0", name) for call in calls)
            assert c.registers[f"hmux0.{name}"].has_data is False
            assert c.registers[f"hmux0.{name}"].value["value"] is None
        assert not any(call.args[0] == "hmu" for call in calls)


# Intent: the bespoke HMUX0 Status00 definition uses complete 6-column fields.
# Why: a mangled Status00 field list is silently accepted by ebusd but decodes
# the wrong bytes, which is worse than the register being absent. The previous
# definition had short field rows that shifted every later field.
async def test_hmux0_status00_definition_has_complete_fields() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(
            ["scan.08 = Vaillant;HMUX0;0303;0504", "ctlv3 HwcOpMode = auto"]
        )

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        definition = next(item for item in definitions if ",B511,00," in item)
        tokens = definition.split(",B511,00,", 1)[1].split(",")
        assert len(tokens) == 8 * 6
        assert tokens[0] == "supplytemp"
        assert tokens[6] == "waterpressure"
        assert tokens[42] == "compressorpower"
        assert tokens[47] == "HMUX0 Status00"


# Intent: keep legacy runtime definition templates on their discovered owner.
# Why: keeps legacy ctlv2/hmu templates from being defined on renamed circuits.
async def test_runtime_definitions_resolve_logical_circuits() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = AsyncMock()
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = DeviceGraph(
            nodes={
                "hmux0": DeviceNode("hmux0", DeviceType.HEAT_PUMP, has_data=True),
                "ctlv3": DeviceNode(
                    "ctlv3",
                    DeviceType.HEATING_CONTROLLER,
                    registers=["ctlv3.Z1OpMode"],
                    has_data=True,
                ),
            },
            raw_registers={},
            placeholder_registers=set(),
        )

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        assert all(",ctlv2," not in definition for definition in definitions)
        assert all(",hmu," not in definition for definition in definitions)


# Intent: runtime controller definitions resolve ctlv4 exactly like the historical ctlv2 alias.
# Why: controller numbering must not change runtime ownership behavior.
async def test_runtime_definitions_resolve_ctlv4_owner() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = AsyncMock()
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = DeviceGraph(
            nodes={
                "ctlv4": DeviceNode(
                    "ctlv4",
                    DeviceType.HEATING_CONTROLLER,
                    registers=["ctlv4.Z1OpMode"],
                    has_data=True,
                )
            },
            raw_registers={"ctlv4.Z1OpMode": "auto"},
            placeholder_registers=set(),
        )

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        assert any(",ctlv4," in definition for definition in definitions)
        assert all(",ctlv2," not in definition for definition in definitions)


# Intent: never define an alias register when graph ownership is ambiguous.
# Why: refusing to guess avoids writing registers to the wrong controller.
async def test_runtime_definitions_skip_ambiguous_logical_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = AsyncMock()
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = DeviceGraph(
            nodes={
                "ctlv3": DeviceNode("ctlv3", DeviceType.HEATING_CONTROLLER, has_data=True),
                "basv3": DeviceNode("basv3", DeviceType.HEATING_CONTROLLER, has_data=True),
            },
            raw_registers={},
            placeholder_registers=set(),
        )

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        assert all(",ctlv2," not in definition for definition in definitions)


# Intent: an empty graph produces no ctlv2/hmu/bai runtime definitions.
# Why: protects ebusd from receiving alias definitions that have no hardware owner.
async def test_runtime_definitions_skip_missing_logical_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = AsyncMock()
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        assert all(",ctlv2," not in definition for definition in definitions)
        assert all(",hmu," not in definition for definition in definitions)
        assert all(",bai," not in definition for definition in definitions)


# Intent: a controller re-homed under a new circuit still resolves the legacy ctlv2 alias to it.
# Why: protects alias resolution when a controller is discovered with a different scan type.
async def test_legacy_register_aliases_resolve_to_discovered_circuits() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = _make_graph()
        assert c.resolve_register_circuit("ctlv2") == "ctlv2"
        assert c.resolve_register_circuit("hmu") == "hmu"

        controller = c._graph.nodes.pop("ctlv2")
        controller.circuit = "ctlv3"
        controller.registers = ["ctlv3.Z1OpMode"]
        controller.scan_type = "CTLV3"
        c._graph.nodes["ctlv3"] = controller
        assert c.resolve_register_circuit("ctlv2") == "ctlv3"


# Intent: prove logical register aliases resolve from graph identity when multiple device families coexist.
# Why: prevents a legacy alias binding to the wrong family when pump and controller variants share the bus.
async def test_graph_resolution_prefers_discovered_roles_in_mixed_installation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={
                "hmux0": DeviceNode("hmux0", DeviceType.HEAT_PUMP, has_data=True),
                "hmu": DeviceNode("hmu", DeviceType.HEAT_PUMP, has_data=True),
                "bai": DeviceNode("bai", DeviceType.HEATING_CONTROLLER, has_data=True),
                "ctlv3": DeviceNode(
                    "ctlv3",
                    DeviceType.HEATING_CONTROLLER,
                    registers=["ctlv3.Z1OpMode", "ctlv3.HwcOpMode"],
                    has_data=True,
                ),
            },
            raw_registers={},
            placeholder_registers=set(),
        )

        assert c.resolve_register_circuit("hmu") == "hmu"
        assert c.resolve_register_circuit("ctlv2") == "ctlv3"
        assert c.heating_circuit == "ctlv3"
        assert c.heat_pump_circuit is None


# Intent: re-run discovery once after ebusd has had time to populate live values.
# Why: protects the delayed re-discovery that lets late-arriving live registers get entities.
async def test_connect_schedules_one_delayed_rediscovery() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        coordinator = VaillantCoordinator(hass, _entry())
        graph = _make_graph()

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.version = "26.1"
        mock_ebus.connect = AsyncMock()
        mock_ebus.define_register = AsyncMock(return_value="done")
        mock_ebus.read_register = AsyncMock(return_value=None)

        mock_discovery = MagicMock()
        mock_discovery.discover = AsyncMock(return_value=graph)
        schedule = MagicMock(return_value=MagicMock())

        module = sys.modules["vaillant_ebus.coordinator"]
        original_ebus = module.EbusService
        original_discovery = module.DiscoveryService
        original_schedule = module.async_call_later
        module.EbusService = MagicMock(return_value=mock_ebus)
        module.DiscoveryService = MagicMock(return_value=mock_discovery)
        module.async_call_later = schedule
        try:
            await coordinator._ebusd_connect_and_discover()
        finally:
            module.EbusService = original_ebus
            module.DiscoveryService = original_discovery
            module.async_call_later = original_schedule

        schedule.assert_called()
        calls = schedule.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] is hass
        assert calls[0].args[1] == timedelta(minutes=5)
        assert calls[1].args[0] is hass
        assert calls[1].args[1] == timedelta(minutes=15)
        delayed_callback = calls[0].args[2]
        await delayed_callback(datetime.now())
        assert mock_discovery.discover.await_count == 3
        schedule.assert_called()


# Intent: a successful initial connection clears a previous ebusd-unreachable repair.
# Why: recovery through config-entry setup is as valid as recovery through reconnect.
async def test_successful_initial_connect_dismisses_ebusd_unreachable_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        coordinator = VaillantCoordinator(hass, _entry())
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.version = "26.1"
        ebus.connect = AsyncMock()
        discovery = MagicMock()
        discovery.discover = AsyncMock(return_value=_make_graph())
        dismiss = AsyncMock()

        monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
        monkeypatch.setattr(COORDINATOR, "DiscoveryService", MagicMock(return_value=discovery))
        monkeypatch.setattr(COORDINATOR.repairs, "async_dismiss_ebusd_unreachable", dismiss)
        coordinator._define_custom_registers = AsyncMock()
        coordinator._apply_discovery_graph = AsyncMock()
        coordinator._schedule_delayed_rediscovery = MagicMock()
        coordinator._schedule_analysis = MagicMock()

        await coordinator._ebusd_connect_and_discover()

        dismiss.assert_awaited_once_with(hass)


# Intent: coordinator polls remain gated until initial discovery has applied its graph.
# Why: concurrent refreshes must not treat an incomplete find as successful recovery.
async def test_initial_poll_waits_for_discovery_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        coordinator = VaillantCoordinator(hass, _entry())
        coordinator._cache_seeded = True
        coordinator._started = True
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.version = "26.1"
        ebus.connect = AsyncMock()
        ebus.find_registers = AsyncMock(return_value=[])
        discovery = MagicMock()

        # Intent: attempt a coordinator update while setup is waiting for discovery.
        # Why: the update must not issue find commands before the graph is applied.
        async def discover() -> DeviceGraph:
            await coordinator._async_update_data()
            ebus.find_registers.assert_not_awaited()
            return _make_graph()

        discovery.discover = AsyncMock(side_effect=discover)
        monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
        monkeypatch.setattr(COORDINATOR, "DiscoveryService", MagicMock(return_value=discovery))
        coordinator._define_custom_registers = AsyncMock()
        coordinator._apply_discovery_graph = AsyncMock()
        coordinator._schedule_delayed_rediscovery = MagicMock()
        coordinator._schedule_analysis = MagicMock()

        await coordinator._ebusd_connect_and_discover()

        assert coordinator._ebusd_connected is True
        assert discovery.discover.await_count == 1


# Intent: the first usable poll builds a graph after an empty initial find.
# Why: services must become ready only after discovered owners appear in the graph.
async def test_first_usable_find_applies_graph_after_empty_discovery() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = True
        coordinator._ebusd_connected = True
        coordinator._ebusd_repair_pending = True
        coordinator._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.last_find_usable = True
        ebus.define_register = AsyncMock(return_value="done")
        ebus.find_registers = AsyncMock(
            return_value=[
                "scan.15 = Vaillant;CTLV2;0514;1104",
                "ctlv2 Z1OpMode = auto",
                "ctlv2 Z1DayTemp = 20",
            ]
        )
        ebus.read_register = AsyncMock(return_value=None)
        coordinator.ebus = ebus
        repairs_module.async_dismiss_ebusd_unreachable.reset_mock()

        await coordinator._async_update_data()

        assert coordinator.discovery_ready is True
        assert coordinator._graph is not None
        controller = coordinator._graph.heating_controller_result().node
        assert controller is not None
        assert controller.scan_type == "CTLV2"
        assert coordinator._ebusd_repair_pending is False
        repairs_module.async_dismiss_ebusd_unreachable.assert_awaited_once_with(coordinator.hass)


# Intent: later poll fallback failure keeps the recovery repair active after graph application.
# Why: repair clearance must wait for all fallback reads in the recovery poll to finish.
async def test_recovery_poll_fallback_failure_does_not_clear_repair() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = True
        coordinator._ebusd_connected = True
        coordinator._ebusd_repair_pending = True
        coordinator._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        coordinator._define_custom_registers = AsyncMock()
        graph = DISCOVERY.DiscoveryService.build_device_graph(["ctlv2 Z1OpMode = auto"])
        coordinator._apply_discovery_graph = AsyncMock(
            side_effect=lambda discovered, source: setattr(coordinator, "_graph", graph)
        )
        coordinator._fallback_read = AsyncMock(side_effect=ConnectionError("fallback transport failed"))
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.last_find_usable = True
        ebus.find_registers = AsyncMock(return_value=["ctlv2 Z1OpMode = auto"])
        ebus._reconnect = AsyncMock(return_value=False)
        coordinator.ebus = ebus
        repairs_module.async_dismiss_ebusd_unreachable.reset_mock()
        repairs_module.async_create_ebusd_unreachable.reset_mock()

        await coordinator._async_update_data()

        assert coordinator._ebusd_repair_pending is True
        repairs_module.async_dismiss_ebusd_unreachable.assert_not_awaited()
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(coordinator.hass)


# Intent: a transport error in the post-definition find returns setup to retry state.
# Why: runtime definitions can make the second discovery the first failing operation.
async def test_post_definition_discovery_failure_retries_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = True
        repairs_module.async_create_ebusd_unreachable.reset_mock()
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.version = "26.1"
        ebus.connect = AsyncMock()
        ebus.disconnect = AsyncMock()
        discovery = MagicMock()
        discovery.discover = AsyncMock(side_effect=[_make_graph(), ConnectionError("connection closed")])
        repairs_module.async_create_ebusd_unreachable.reset_mock()

        # Intent: force the optional post-definition discovery to hit a transport failure.
        # Why: setup must retry when runtime register definitions lose their follow-up find.
        async def define_runtime_registers() -> None:
            coordinator._runtime_definitions["test"] = "runtime definition"

        monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
        monkeypatch.setattr(COORDINATOR, "DiscoveryService", MagicMock(return_value=discovery))
        monkeypatch.setattr(coordinator, "_define_custom_registers", define_runtime_registers)
        coordinator._apply_discovery_graph = AsyncMock()

        await coordinator._ebusd_connect_and_discover()

        assert discovery.discover.await_count == 2
        assert coordinator._ebusd_connected is False
        assert coordinator._started is False
        assert coordinator._ebusd_repair_pending is True
        ebus.disconnect.assert_awaited_once_with()
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(coordinator.hass)

        scheduled: list = []
        coordinator.hass.async_create_task = MagicMock(side_effect=scheduled.append)
        retry_setup = AsyncMock()
        coordinator._ebusd_connect_and_discover = retry_setup
        await coordinator._async_update_data()
        assert coordinator._started is True
        assert len(scheduled) == 1
        await scheduled[0]
        retry_setup.assert_awaited_once_with()


# Intent: an empty post-definition find cannot clear a pending recovery repair.
# Why: the pre-definition graph does not prove the follow-up discovery completed.
async def test_empty_post_definition_find_keeps_repair_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = True
        coordinator._ebusd_repair_pending = True
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.version = "26.1"
        ebus.connect = AsyncMock()
        ebus.disconnect = AsyncMock()
        discovery = MagicMock()
        discovery.discover = AsyncMock(
            side_effect=[_make_graph(), DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())]
        )
        repairs_module.async_create_ebusd_unreachable.reset_mock()
        repairs_module.async_dismiss_ebusd_unreachable.reset_mock()

        # Intent: runtime definitions trigger a second find with no usable graph rows.
        # Why: recovery must not clear its repair from the earlier pre-definition snapshot.
        async def define_runtime_registers() -> None:
            coordinator._runtime_definitions["test"] = "runtime definition"

        monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
        monkeypatch.setattr(COORDINATOR, "DiscoveryService", MagicMock(return_value=discovery))
        monkeypatch.setattr(coordinator, "_define_custom_registers", define_runtime_registers)
        coordinator._apply_discovery_graph = AsyncMock()

        await coordinator._ebusd_connect_and_discover()

        assert discovery.discover.await_count == 2
        assert coordinator._ebusd_connected is False
        assert coordinator._started is False
        assert coordinator._ebusd_repair_pending is True
        coordinator._apply_discovery_graph.assert_not_awaited()
        repairs_module.async_dismiss_ebusd_unreachable.assert_not_awaited()
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(coordinator.hass)

        scheduled: list = []
        coordinator.hass.async_create_task = MagicMock(side_effect=scheduled.append)
        retry_setup = AsyncMock()
        coordinator._ebusd_connect_and_discover = retry_setup
        await coordinator._async_update_data()
        assert coordinator._started is True
        assert len(scheduled) == 1
        await scheduled[0]
        retry_setup.assert_awaited_once_with()


# Intent: an unexpected initial graph-application failure restores the setup retry state.
# Why: a background task error must not leave the entry permanently disconnected.
async def test_initial_graph_application_failure_retries_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = True
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.version = "26.1"
        ebus.connect = AsyncMock()
        ebus.disconnect = AsyncMock()
        discovery = MagicMock()
        discovery.discover = AsyncMock(return_value=_make_graph())
        repairs_module.async_create_ebusd_unreachable.reset_mock()
        monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
        monkeypatch.setattr(COORDINATOR, "DiscoveryService", MagicMock(return_value=discovery))
        coordinator._define_custom_registers = AsyncMock()
        coordinator._apply_discovery_graph = AsyncMock(side_effect=RuntimeError("graph apply failed"))

        await coordinator._ebusd_connect_and_discover()

        assert coordinator._ebusd_connected is False
        assert coordinator._started is False
        assert coordinator._ebusd_repair_pending is True
        ebus.disconnect.assert_awaited_once_with()
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(coordinator.hass)

        scheduled: list = []
        coordinator.hass.async_create_task = MagicMock(side_effect=scheduled.append)
        retry_setup = AsyncMock()
        coordinator._ebusd_connect_and_discover = retry_setup
        await coordinator._async_update_data()
        assert coordinator._started is True
        assert len(scheduled) == 1
        await scheduled[0]
        retry_setup.assert_awaited_once_with()


# Intent: a transport error in the first discovery leaves setup retryable.
# Why: an unusable initial find must not apply an empty graph or strand the entry.
async def test_initial_discovery_failure_retries_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = True
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.version = "26.1"
        ebus.connect = AsyncMock()
        ebus.disconnect = AsyncMock()
        discovery = MagicMock()
        discovery.discover = AsyncMock(side_effect=ConnectionError("find returned no usable lines"))
        repairs_module.async_create_ebusd_unreachable.reset_mock()
        monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
        monkeypatch.setattr(COORDINATOR, "DiscoveryService", MagicMock(return_value=discovery))
        coordinator._apply_discovery_graph = AsyncMock()

        await coordinator._ebusd_connect_and_discover()

        assert coordinator._ebusd_connected is False
        assert coordinator._started is False
        assert coordinator._ebusd_repair_pending is True
        coordinator._apply_discovery_graph.assert_not_awaited()
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(coordinator.hass)

        scheduled: list = []
        coordinator.hass.async_create_task = MagicMock(side_effect=scheduled.append)
        retry_setup = AsyncMock()
        coordinator._ebusd_connect_and_discover = retry_setup
        await coordinator._async_update_data()
        assert coordinator._started is True
        assert len(scheduled) == 1
        await scheduled[0]
        retry_setup.assert_awaited_once_with()


# Intent: an empty successful discovery does not clear a repair while recovering.
# Why: a live TCP socket without an authoritative graph is not proven recovery.
async def test_empty_initial_graph_keeps_unreachable_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = True
        repairs_module.async_create_ebusd_unreachable.reset_mock()
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.version = "26.1"
        ebus.connect = AsyncMock()
        ebus.disconnect = AsyncMock()
        discovery = MagicMock()
        discovery.discover = AsyncMock(
            return_value=DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        )
        dismiss = repairs_module.async_dismiss_ebusd_unreachable
        dismiss.reset_mock()
        monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
        monkeypatch.setattr(COORDINATOR, "DiscoveryService", MagicMock(return_value=discovery))
        coordinator._apply_discovery_graph = AsyncMock()

        await coordinator._ebusd_connect_and_discover()

        assert coordinator._ebusd_connected is False
        assert coordinator._started is False
        assert coordinator._ebusd_repair_pending is True
        coordinator._apply_discovery_graph.assert_not_awaited()
        dismiss.assert_not_awaited()
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(coordinator.hass)
        ebus.disconnect.assert_awaited_once_with()

        scheduled: list = []
        coordinator.hass.async_create_task = MagicMock(side_effect=scheduled.append)
        retry_setup = AsyncMock()
        coordinator._ebusd_connect_and_discover = retry_setup
        await coordinator._async_update_data()
        assert coordinator._started is True
        assert len(scheduled) == 1
        await scheduled[0]
        retry_setup.assert_awaited_once_with()


# Intent: keep existing entities when delayed discovery finds only additional devices.
# Why: delayed discovery must be additive and never drop initially discovered circuits.
async def test_delayed_rediscovery_only_adds_entities_and_devices() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        initial_graph = _make_graph()
        delayed_graph = DeviceGraph(
            nodes={
                "v32": DeviceNode(
                    circuit="v32",
                    device_type=DeviceType.VENTILATION,
                    registers=["v32.SupplyAirTemp"],
                    has_data=True,
                ),
            },
            raw_registers={"v32.SupplyAirTemp": "20.75"},
            placeholder_registers=set(),
        )
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value=None)
        mock_discovery = MagicMock()
        mock_discovery.discover = AsyncMock(return_value=delayed_graph)

        coordinator.ebus = mock_ebus
        coordinator.discovery = mock_discovery
        await coordinator._apply_discovery_graph(initial_graph, "initial")
        await coordinator._async_delayed_rediscover(datetime.now())

        entity_names = {entity.name for entity in coordinator.entities}
        assert {"Z1OpMode", "Z1DayTemp", "SupplyAirTemp"} <= entity_names
        assert {"ctlv2", "v32"} <= set(coordinator._graph.nodes)


# Intent: a transport failure during delayed find restores the setup retry path.
# Why: the one-shot delayed callback must not strand the coordinator on a dead socket.
async def test_delayed_discovery_transport_failure_retries_setup() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._ebusd_connected = True
        coordinator._started = True
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        coordinator.ebus = ebus

        # Intent: model EOF during delayed discovery and let the service close its socket.
        # Why: failed find must become a transport loss before recovery state is evaluated.
        async def fail_discovery() -> DeviceGraph:
            ebus.is_connected = False
            raise ConnectionError("find returned no usable lines")

        coordinator.discovery = MagicMock()
        coordinator.discovery.discover = AsyncMock(side_effect=fail_discovery)
        repairs_module.async_create_ebusd_unreachable.reset_mock()

        await coordinator._async_delayed_rediscover(datetime.now())

        assert coordinator._ebusd_connected is False
        assert coordinator._started is False
        assert coordinator._ebusd_repair_pending is True
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(coordinator.hass)


# Intent: a completed but empty delayed find gets one bounded discovery retry.
# Why: an empty response must not consume the only chance to add delayed devices.
async def test_delayed_discovery_retries_once_after_empty_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        existing_graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        refreshed_graph = DeviceGraph(
            nodes={"v32": DeviceNode("v32", DeviceType.VENTILATION, registers=["v32.SupplyAirTemp"], has_data=True)},
            raw_registers={"v32.SupplyAirTemp": "20.75"},
            placeholder_registers=set(),
        )
        coordinator._graph = existing_graph
        coordinator._ebusd_connected = True
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.discovery = MagicMock()
        coordinator.discovery.discover = AsyncMock(
            side_effect=[DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set()), refreshed_graph]
        )
        coordinator._apply_discovery_graph = AsyncMock()
        schedule = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(COORDINATOR, "async_call_later", schedule)

        await coordinator._async_delayed_rediscover(datetime.now())

        assert coordinator._graph is existing_graph
        assert coordinator._delayed_rediscovery_retry_count == 1
        assert coordinator._delayed_rediscovery_scheduled is True
        retry = schedule.call_args.args[2]
        await retry(datetime.now())
        coordinator._apply_discovery_graph.assert_awaited_once_with(refreshed_graph, "delayed")
        assert coordinator._delayed_rediscovery_retry_count == 0


# Intent: delayed graph-application errors receive one bounded retry.
# Why: a one-shot callback failure must not permanently discard new discovery data.
async def test_delayed_graph_application_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._graph = _make_graph()
        coordinator._ebusd_connected = True
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        graph = DeviceGraph(
            nodes={"v32": DeviceNode("v32", DeviceType.VENTILATION, registers=["v32.SupplyAirTemp"], has_data=True)},
            raw_registers={"v32.SupplyAirTemp": "20.75"},
            placeholder_registers=set(),
        )
        coordinator.discovery = MagicMock()
        coordinator.discovery.discover = AsyncMock(return_value=graph)
        coordinator._apply_discovery_graph = AsyncMock(side_effect=[RuntimeError("temporary apply failure"), None])
        schedule = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(COORDINATOR, "async_call_later", schedule)

        await coordinator._async_delayed_rediscover(datetime.now())

        assert coordinator._delayed_rediscovery_retry_count == 1
        retry = schedule.call_args.args[2]
        await retry(datetime.now())
        assert coordinator._apply_discovery_graph.await_count == 2
        assert coordinator._delayed_rediscovery_retry_count == 0


# Intent: entities introduced by a delayed discovery are pushed to registered platform adders.
# Why: new devices found later must surface in Home Assistant without a reload.
async def test_delayed_rediscovery_adds_new_platform_entities() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        additions = MagicMock()
        coordinator.register_entity_adder("sensor", additions)
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value=None)
        coordinator.ebus = mock_ebus
        await coordinator._apply_discovery_graph(_make_graph(), "initial")
        additions.reset_mock()

        await coordinator._apply_discovery_graph(
            DeviceGraph(
                nodes={
                    "v32": DeviceNode(
                        circuit="v32",
                        device_type=DeviceType.VENTILATION,
                        registers=["v32.SupplyAirTemp"],
                        has_data=True,
                    )
                },
                raw_registers={"v32.SupplyAirTemp": "20.75"},
                placeholder_registers=set(),
            ),
            "delayed",
        )

        additions.assert_called_once()
        assert additions.call_args.args[0][0].key == "v32.SupplyAirTemp.value"


# Intent: re-applying discovery pushes only genuinely new entities once, with or without a pre-seeded graph.
# Why: prevents duplicate entity creation when initial discovery is replayed after cache seeding.
@pytest.mark.parametrize("seed_cache", [False, True])
async def test_initial_discovery_pushes_new_entities_once(seed_cache, caplog) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        initial = DISCOVERY.DiscoveryService.build_device_graph(["hmu OutsideTemp = 18.5"])
        if seed_cache:
            c._graph = initial
            c.entities = c.entity_factory.generate(initial)
        else:
            await c._apply_discovery_graph(initial, "initial")
        adder = MagicMock()
        c.register_entity_adder("sensor", adder)
        fresh = DISCOVERY.DiscoveryService.build_device_graph(["hmu OutsideTemp = 18.5", "hmu FlowTemp = 35"])
        with caplog.at_level("INFO", logger="vaillant_ebus.coordinator"):
            await c._apply_discovery_graph(fresh, "initial")
            await c._apply_discovery_graph(initial, "initial")
            await c._apply_discovery_graph(fresh, "initial")
        adder.assert_called_once()
        assert [e.key for e in adder.call_args.args[0]] == ["hmu.FlowTemp.value"]
        assert "0 new entities" in caplog.text


# Intent: a register that only exists in the cache (stale from an earlier
# session or CSV) is pruned from self.registers on the first real discovery,
# while an enabled REGISTER_MAP register that find does not list is preserved.
# Why: ghost devices such as a hmux0-owned ZZTest survived on cached leftovers
# even though the real bus never exposes them.
async def test_initial_discovery_prunes_stale_cache_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.registers["hmux0.ZZTest"] = EbusdRegister(
            circuit="hmux0", name="ZZTest", fields=["value"], value={"value": "-0.06"}, has_data=True
        )
        c.registers["hmu.SourceTempInput"] = EbusdRegister(
            circuit="hmu", name="SourceTempInput", fields=["value"], value={"value": "3.2"}, has_data=True
        )
        graph = DISCOVERY.DiscoveryService.build_device_graph(["hmu OutsideTemp = 18.5"])
        await c._apply_discovery_graph(graph, "initial")
        assert "hmux0.ZZTest" not in c.registers
        assert "hmu.SourceTempInput" in c.registers


# Intent: B524 state metadata does not preserve cache-only values without safe fallback reads.
# Why: invalid-position reads must not leave stale entities while real ebusd find values remain supported.
@pytest.mark.parametrize(
    ("raw_registers", "expected_supported"),
    [({}, False), ({"ctlv2.Hc1FlowTempCalc": "40.1"}, True)],
)
async def test_initial_discovery_keeps_b524_cache_only_when_live(
    raw_registers: dict[str, str], expected_supported: bool
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        register_key = "ctlv2.Hc1FlowTempCalc"
        c.registers[register_key] = EbusdRegister(
            circuit="ctlv2", name="Hc1FlowTempCalc", fields=["value"], value={"value": "40.1"}, has_data=True
        )
        graph = DeviceGraph(
            nodes={
                "ctlv2": DeviceNode(
                    circuit="ctlv2",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=[register_key] if raw_registers else [],
                    has_data=bool(raw_registers),
                    scan_type="CTLV2",
                )
            },
            raw_registers=raw_registers,
            placeholder_registers=set(),
        )

        await c._apply_discovery_graph(graph, "initial")

        assert (register_key in c.registers) is expected_supported


# Intent: initial discovery removes cached entities only for a proven replacement owner.
# Why: an ambiguous or missing role must preserve 1.9.x entities rather than create not-found IDs.
async def test_initial_discovery_prunes_stale_cache_entities_for_old_aliases() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        stale_graph = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "ctlv2 Hc1PumpHours = 24384",
                "hmu HcElecConsDay = 300.48",
                "bai StatFuelSum = 134.274",
            ]
        )
        c._graph = stale_graph
        c.entities = c.entity_factory.generate(stale_graph)
        c.registers["ctlv2.Hc1PumpHours"] = EbusdRegister(
            circuit="ctlv2", name="Hc1PumpHours", fields=["value"], value={"value": "24384"}, has_data=True
        )
        c.registers["hmu.HcElecConsDay"] = EbusdRegister(
            circuit="hmu", name="HcElecConsDay", fields=["value"], value={"value": "300.48"}, has_data=True
        )
        c.registers["bai.StatFuelSum"] = EbusdRegister(
            circuit="bai", name="StatFuelSum", fields=["value"], value={"value": "134.274"}, has_data=True
        )
        fresh_graph = DeviceGraph(
            nodes={
                "bai": DeviceNode(
                    circuit="bai",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["bai.StatFuelSum"],
                    has_data=False,
                    scan_type="BAI00",
                ),
                "bass": DeviceNode(
                    circuit="bass",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["bass.Hc1PumpHours"],
                    has_data=True,
                    scan_type="BASS3",
                ),
            },
            raw_registers={},
            placeholder_registers={"bass.Hc1PumpHours", "bai.StatFuelSum"},
        )

        await c._apply_discovery_graph(fresh_graph, "initial")

        assert "ctlv2.Hc1PumpHours" not in c.registers
        assert "hmu.HcElecConsDay" in c.registers
        assert "bai.StatFuelSum" not in c.registers
        assert not any(entity.circuit == "ctlv2" and entity.name == "Hc1PumpHours" for entity in c.entities)
        assert any(entity.circuit == "hmu" and entity.name == "HcElecConsDay" for entity in c.entities)
        bai_entities = [entity for entity in c.entities if entity.circuit == "bai" and entity.name == "StatFuelSum"]
        assert bai_entities
        assert all(entity.raw_value != "134.274" for entity in bai_entities)


# Intent: a 1.9.x cache-backed mapped entity survives discovery when its logical controller remains present.
# Why: an upgrade must preserve existing entity IDs even when one find response omits a readable register.
async def test_initial_discovery_preserves_legacy_cache_entity_for_current_controller() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        cached_key = "ctlv2.Z1RoomTemp"
        cached_graph = DeviceGraph(
            nodes={
                "ctlv2": DeviceNode(
                    "ctlv2", DeviceType.HEATING_CONTROLLER, registers=[cached_key], has_data=True, scan_type="CTLV2"
                )
            },
            raw_registers={cached_key: "21.5"},
            placeholder_registers=set(),
        )
        c.registers[cached_key] = EbusdRegister(
            "ctlv2", "Z1RoomTemp", ["value"], value={"value": "21.5"}, has_data=True
        )
        c.entities = c.entity_factory.generate(cached_graph)
        current_graph = DeviceGraph(
            nodes={
                "ctlv2": DeviceNode(
                    "ctlv2",
                    DeviceType.HEATING_CONTROLLER,
                    registers=["ctlv2.Z1OpMode"],
                    has_data=True,
                    scan_type="CTLV2",
                )
            },
            raw_registers={"ctlv2.Z1OpMode": "auto"},
            placeholder_registers=set(),
        )

        await c._apply_discovery_graph(current_graph, "initial")

        assert cached_key in c.registers
        assert any(entity.key == "ctlv2.Z1RoomTemp.value" for entity in c.entities)


# Intent: a user-enabled placeholder keeps its registry choice after stale cache
# data is cleared and remains available as an unavailable entity.
# Why: cache cleanup must not turn temporary no-data into an integration disable
# for an entity the user explicitly enabled (issue #152).
async def test_placeholder_cache_cleanup_preserves_user_enabled_registry_entry() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        entry = _entry()
        entry.entry_id = "entry-1"
        c = VaillantCoordinator(hass, entry)
        desc = COORDINATOR.EntityDescription(
            circuit="bai",
            name="StatFuelSum",
            field="value",
            meta=MAPPING.RegisterMeta(friendly_name="Fuel Energy"),
            register=EbusdRegister(circuit="bai", name="StatFuelSum", fields=["value"]),
            raw_value="134.274",
            enabled_by_default=True,
        )
        c.entities = [desc]
        registry = MagicMock()
        registry.entities = {
            "sensor.fuel": MagicMock(
                unique_id=desc.unique_id,
                config_entry_id="entry-1",
                disabled_by=None,
            )
        }
        registry.async_update_entity = MagicMock()
        from homeassistant.helpers import entity_registry

        entity_registry.async_get = MagicMock(return_value=registry)
        graph = DeviceGraph(
            nodes={
                "bai": DeviceNode(
                    circuit="bai",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["bai.StatFuelSum"],
                    has_data=False,
                    scan_type="BAI00",
                )
            },
            raw_registers={},
            placeholder_registers={"bai.StatFuelSum"},
        )

        await c._apply_discovery_graph(graph, "initial")
        c.disable_no_data_entities()

        assert desc.raw_value == ""
        assert desc.enabled_by_default is False
        registry.async_update_entity.assert_not_called()


# Intent: stale alias entities already present in the registry become
# integration-disabled when discovery proves that their source circuit vanished.
# Why: cache seeding can register an alias before discovery finishes; disabling
# the registry entry removes it from active HA entities without deleting user data.
async def test_initial_discovery_disables_stale_alias_registry_entity() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        entry = _entry()
        entry.entry_id = "entry-1"
        c = VaillantCoordinator(hass, entry)
        stale_graph = DISCOVERY.DiscoveryService.build_device_graph(["ctlv2 Hc1PumpHours = 24384"])
        desc = next(entity for entity in c.entity_factory.generate(stale_graph) if entity.name == "Hc1PumpHours")
        c.entities = [desc]
        c.registers["ctlv2.Hc1PumpHours"] = EbusdRegister(
            circuit="ctlv2", name="Hc1PumpHours", fields=["value"], value={"value": "24384"}, has_data=True
        )
        registry = MagicMock()
        registry.entities = {
            "sensor.stale_pump_hours": MagicMock(
                unique_id=desc.unique_id,
                config_entry_id="entry-1",
                disabled_by=None,
            )
        }
        registry.async_update_entity = MagicMock()
        from homeassistant.helpers import entity_registry

        entity_registry.async_get = MagicMock(return_value=registry)
        fresh_graph = DeviceGraph(
            nodes={
                "bass": DeviceNode(
                    circuit="bass",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["bass.Hc1PumpHours"],
                    has_data=False,
                    scan_type="BASS3",
                )
            },
            raw_registers={},
            placeholder_registers={"bass.Hc1PumpHours"},
        )

        await c._apply_discovery_graph(fresh_graph, "initial")

        registry.async_update_entity.assert_called_once_with("sensor.stale_pump_hours", disabled_by="integration")


# Intent: initial BASV3 error placeholders disable cached B524 entities from prior versions.
# Why: cached sensors skipped by current entity generation must not remain registered as enabled.
async def test_initial_discovery_disables_cached_b524_error_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        entry = _entry()
        entry.entry_id = "entry-basv3"
        coordinator = VaillantCoordinator(hass, entry)
        cache_key = "basv3.Hc1FlowTempCalc.value"
        coordinator._async_load_cache = AsyncMock(return_value={cache_key: "35.5"})
        await coordinator._async_seed_entities_from_cache()
        cached_entity = next(entity for entity in coordinator.entities if entity.name == "Hc1FlowTempCalc")
        registry = MagicMock()
        entity_id = "sensor.cached_hc1_flow_temp_calc"
        registry.entities = {
            entity_id: MagicMock(
                unique_id=cached_entity.unique_id,
                config_entry_id=entry.entry_id,
                disabled_by=None,
            )
        }
        registry.async_update_entity = MagicMock()
        from homeassistant.helpers import entity_registry

        entity_registry.async_get = MagicMock(return_value=registry)
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/basv3_issue31_2026-09-17_203723_discovery.yaml", after=True)
        )

        await coordinator._apply_discovery_graph(graph, "initial")

        assert "basv3.Hc1FlowTempCalc" not in coordinator.registers
        assert not any(entity.name == "Hc1FlowTempCalc" for entity in coordinator.entities)
        registry.async_update_entity.assert_called_once_with(entity_id, disabled_by="integration")


# Intent: the DHW storage-temp register's explicit empty/NaN sentinel
# ("(empty ...7fffffff)") must survive the coordinator pipeline into the data
# dict so the tank-presence sensor can report "off" (no tank). A generic
# no-data sentinel must NOT be conflated with that explicit marker.
# Why: regression for #135 - without this, the coordinator collapsed every
# sentinel to None and the sensor could only ever report unknown, never off.
async def test_hwc_storage_temp_empty_sentinel_reaches_data() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c.ebus.read_register = AsyncMock(return_value=None)
        c._cache_seeded = c._ebusd_connected = True
        empty = "(empty for 3115b52406020001000500 / 0800010500ffffff7f)"
        c.ebus.find_registers = AsyncMock(
            return_value=[
                "ctlv2 OutsideTemp = 18.5",
                f"ctlv2 HwcStorageTemp = {empty}",
            ]
        )
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(
            ["ctlv2 OutsideTemp = 18.5", f"ctlv2 HwcStorageTemp = {empty}"]
        )

        values = await c._async_update_data()

        # The explicit empty-NaN marker is preserved (not None), so the
        # tank-presence sensor can turn it into a confirmed "off".
        assert values["ebusd"]["ctlv2.HwcStorageTemp.value"] == empty
        assert c.registers["ctlv2.HwcStorageTemp"].value["value"] == empty


# Intent: a register the discovery graph does not configure is never revived
# from the cache during a fallback read, even when the cache still holds a
# stale value from an earlier session.
# Why: issue #99 - the cache backfill used to resurrect any register whose read
# returned None, freezing the sensor on a stale value although the register is
# absent from the discovered graph.
async def test_fallback_read_does_not_refill_absent_register_from_cache() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value=None)
        c.ebus = mock_ebus
        c._graph = _make_graph()
        c._last_find_keys = set(c._graph.raw_registers)
        c.registers["ctlv2.HwcStorageTemp"] = EbusdRegister(
            circuit="ctlv2", name="HwcStorageTemp", fields=["value"], value={"value": None}, has_data=False
        )
        await c._async_save_cache({"ctlv2.HwcStorageTemp.value": "45.2"})
        await c._fallback_read()
        assert c.registers["ctlv2.HwcStorageTemp"].value["value"] is None


# Intent: a discovered no-data placeholder never receives an old cached value
# during its retry read.
# Why: issue #152's F34 dump contains fuel/energy registers that return ERR or
# no data while the cache still contains values from an earlier topology.
async def test_fallback_read_does_not_refill_placeholder_from_cache() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value=None)
        c.ebus = mock_ebus
        c._graph = DeviceGraph(
            nodes={
                "hmu": DeviceNode(
                    circuit="hmu",
                    device_type=DeviceType.HEAT_PUMP,
                    registers=["hmu.YieldHc"],
                    has_data=False,
                )
            },
            raw_registers={},
            placeholder_registers={"hmu.YieldHc"},
        )
        await c._async_save_cache({"hmu.YieldHc.value": "123.4"})

        await c._fallback_read(include_placeholders=True)

        mock_ebus.read_register.assert_any_await("hmu", "YieldHc", raise_transport_errors=True)
        assert "hmu.YieldHc" not in c.registers


# Intent: a mapped cache-only register on a real discovered owner remains a
# fallback-read candidate instead of being mistaken for a find result.
# Why: optional registers such as SourceTempInput may be absent from find at
# startup but must still be re-read on hardware that owns the circuit.
async def test_fallback_read_keeps_cache_only_mapped_owner_candidate() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="9.25")
        c.ebus = mock_ebus
        c._graph = _make_graph()
        c.registers["hmu.SourceTempInput"] = EbusdRegister(
            circuit="hmu", name="SourceTempInput", fields=["value"], value={"value": "8.0"}, has_data=True
        )
        c._refresh_find_keys()

        await c._fallback_read()

        mock_ebus.read_register.assert_any_await("hmu", "SourceTempInput", raise_transport_errors=True)
        assert c.registers["hmu.SourceTempInput"].value["value"] == "9.25"


# Intent: a failed read of a cache-only mapped register clears the old cache
# value and never promotes it into the discovery graph.
# Why: a failed SourceTempInput read must not turn a stale cache value into a
# new raw register that remains visible on later polls.
async def test_fallback_read_clears_failed_cache_only_owner_candidate() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value=None)
        c.ebus = mock_ebus
        c._graph = _make_graph()
        c.registers["hmu.SourceTempInput"] = EbusdRegister(
            circuit="hmu", name="SourceTempInput", fields=["value"], value={"value": "8.0"}, has_data=True
        )
        c._refresh_find_keys()

        await c._fallback_read()

        assert c.registers["hmu.SourceTempInput"].value["value"] is None
        assert c.registers["hmu.SourceTempInput"].has_data is False
        assert "hmu.SourceTempInput" not in c._graph.raw_registers


# Intent: energy registers read from ebusd cache between polls and force a read only after the interval.
# Why: protects runtime energy refresh (issue #50 family) without requiring an integration reload.
async def test_runtime_energy_refreshes_without_reload(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c.ebus.read_register = AsyncMock(return_value=None)
        names = ("CoolElecConsDay", "HcElecConsDay", "HwcElecConsDay", "CoolEnvYieldMonth")
        lines = [f"hmu {name} = 100" for name in names]
        c.ebus.find_registers = AsyncMock(return_value=lines)
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(lines)
        monkeypatch.setattr(
            COORDINATOR, "REGISTER_MAP", {f"hmu.{name}": MAPPING.REGISTER_MAP[f"hmu.{name}"] for name in names}
        )
        await c._define_custom_registers()
        c.ebus.read_register = AsyncMock(return_value="200")
        values = await c._async_update_data()
        for name in names:
            assert values["ebusd"][f"hmu.{name}.value"] == "200"
        c.ebus.read_register.reset_mock()
        # A normal poll inside the energy interval uses ebusd's updated cache.
        c.ebus.find_registers.return_value = [f"hmu {name} = 200" for name in names]
        await c._async_update_data()
        c.ebus.read_register.assert_not_awaited()
        c._last_energy_poll = datetime.min
        c.ebus.read_register.return_value = "300"
        values = await c._async_update_data()
        assert values["ebusd"]["hmu.CoolElecConsDay.value"] == "300"


# Intent: the Status07 noise-reduction definition is emitted only for HM5103 hardware.
# Why: hardware gating stops an unsupported Status07 layout being sent to other HMU firmware.
async def test_status07_definition_is_gated_to_hm5103() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = _make_graph()
        c._graph.nodes["hmu"].scan_type = "HMU00"
        c._graph.nodes["hmu"].scan_hw = "5103"

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        status07 = next(definition for definition in definitions if ",Status07," in definition)
        assert ",B511,07," in status07
        assert "display_b5_noisereduction" in status07


# Intent: the BAI boiler switch definitions are emitted on the B509 write message.
# Why: issue #111 - HeatingSwitch/HwcSwitch are read-only in the generic BAI
# config, so the integration must redefine them writable for control to work.
async def test_bai_switch_definitions_use_b509_write_message() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(["bai FlowTemp = 28.69"])

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        heating = next(item for item in definitions if ",bai,HeatingSwitch," in item)
        hwc = next(item for item in definitions if ",bai,HwcSwitch," in item)
        # The write message uses the upstream `0e` write-prefix byte (read is
        # `0d`), so the wire write targets the boiler's writable register rather
        # than the read-only CSV element.
        assert ",08,B509,0ef203," in heating
        assert ",08,B509,0ef303," in hwc
        # `onoff` is not in the runtime define's template scope, so the field
        # must use an explicit UCH onoff encoding or element lookup fails.
        assert heating.endswith("value,,UCH,0=off;1=on,,")
        assert hwc.endswith("value,,UCH,0=off;1=on,,")
        # The switch definitions must not leak onto a heat-pump alias.
        assert all(",hmu," not in item for item in definitions)


# Intent: the VWZIO/VWZ Status01 definition targets address 0x76 with explicit types.
# Why: upstream PR #598 - the hcmode_inc template aliases do not resolve in a
# runtime define, so the Hydraulikstation telemetry needs concrete types.
async def test_vwz_status01_definition_uses_explicit_types_on_0x76() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(
            ["scan.76 = Vaillant;VWZ00;0522;5103", "vwz EnableTestHwcTemp = no data stored"]
        )

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        status01 = next(item for item in definitions if ",vwz,Status01," in item)
        assert status01.startswith("r,vwz,Status01,")
        assert ",31,76,B511,01," in status01
        tokens = status01.split(",B511,01,", 1)[1].split(",")
        assert len(tokens) == 36
        assert tokens[0] == "temp"
        assert tokens[2] == "D1C"
        assert tokens[14] == "D2B"
        assert tokens[30] == "pumpstate"
        assert tokens[32] == "UCH"


# Intent: unproven HMUX0-specific definitions stay disabled for a plain HMU graph.
# Why: avoids enabling unverified registers (Status00, RunDataElPowerConsumption) on uncaptured hardware.
async def test_hmux0_unproven_definitions_are_not_enabled() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = _make_graph()

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        assert not any(",Status00," in definition for definition in definitions)
        assert not any(",RunDataElPowerConsumption," in definition for definition in definitions)


# Intent: the Status07 definition is skipped for HMU hardware other than HM5103.
# Why: protects other HMU variants from an incompatible Status07 message layout.
async def test_status07_definition_skips_other_hmu_hardware() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = _make_graph()

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        assert not any(",Status07," in definition for definition in definitions)


# End-to-end: issue #99 find output → DeviceGraph scan metadata → runtime
# hardware detection. The HMUX0 yield/COP definitions must activate from the
# discovered scan identity (HMUX0;0303;0504) without any circuit-name hack.
# Intent: the issue #99 community fixture drives HMUX0 yield/COP definitions from scan identity.
# Why: regression for #99: definitions follow scan metadata without any circuit-name hack.
async def test_hmux0_runtime_definitions_use_issue99_fixture_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/arotherm_hmux0_dhw_holiday_discovery.yaml")
        )
        hmux0 = graph.nodes.get("hmux0")
        assert hmux0 is not None
        assert hmux0.device_type == DeviceType.HEAT_PUMP
        assert hmux0.scan_type == "HMUX0"
        assert hmux0.scan_sw == "0303"
        assert hmux0.scan_hw == "0504"
        ctlv3 = graph.nodes["ctlv3"]
        assert ctlv3.device_type == DeviceType.HEATING_CONTROLLER
        assert ctlv3.scan_type == "CTLV3"
        assert ctlv3.scan_sw == "0808"
        assert ctlv3.scan_hw == "8004"

        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = graph

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        hmux0_defs = [definition for definition in definitions if ",hmux0," in definition]
        assert len(hmux0_defs) == 24
        assert all(",hmu," not in definition for definition in hmux0_defs)
        assert any(",hmux0,RunDataReturnTemp," in definition for definition in hmux0_defs)
        assert any(",hmux0,YieldHc," in definition for definition in hmux0_defs)
        assert any(",hmux0,CopHwcMonth," in definition for definition in hmux0_defs)
        # Upstream #249 / #522: the 0303/0504 variant keeps the compressor
        # status block and the electrical-power decode.
        assert any(",hmux0,Status00," in definition for definition in hmux0_defs)
        assert any(",hmux0,RunDataElPowerConsumption," in definition for definition in hmux0_defs)


# A future HMUX0 firmware (pro7 capture: SW0406/HW0504) must not receive the
# SW0303-gated yield/COP definitions or the incompatible HMU-only layouts.
# The shared b516 energy family remains available.
# Intent: a future HMUX0 firmware keeps the shared b516 energy family but not the SW0303-gated yield/COP definitions.
# Why: protects firmware-scoped gating so incompatible layouts are not sent to newer hardware.
async def test_hmux0_other_firmware_gets_scan_metadata_without_yield_definitions() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/arotherm_pro7_quiet_off_idle_discovery.yaml")
        )
        hmu = graph.nodes.get("hmu")
        assert hmu is not None
        assert hmu.device_type == DeviceType.HEAT_PUMP
        assert hmu.scan_type == ""

        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = graph

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        # SW0303-gated telemetry stays off for this future firmware.
        assert not any(",RunDataReturnTemp," in definition for definition in definitions)
        assert not any(",YieldHc," in definition for definition in definitions)
        assert not any(",CopHc," in definition for definition in definitions)
        # The shared b516 energy statistics family is firmware-independent and
        # must survive on the identified heat pump.
        assert any(",hmux0,HcElecConsTotal," in definition for definition in definitions)
        assert not any(",Status00," in definition for definition in definitions)
        assert not any(",RunDataElPowerConsumption," in definition for definition in definitions)


# Intent: on a BAS-family heating controller the zone-1 day setpoint is read at
# sub-address 0x22, not the 0x07 slot the shipped 15.700-lineage CSV polls.
# Regression for #129: the 0x07 read returned "ERR: invalid position" on a
# Saunier-Duval BASS3 (scan Vaillant;BASS3;0708;4304) while the setpoint lives
# at 0x22 (upstream issue #646 live read, #522 "0700 -> 2200", ctlv0/ctlv3
# fixtures). The runtime define must replace the CSV read with the 0x22 address
# only on BAS-family controllers; ctlv2/ctlv3 (where 0x07 works) must not be
# overridden.
# Why: pins the hardware-gated 0x22 read override so BASS3/BASV3 setpoints
# become readable without touching the (unmergeable) upstream CSV, while leaving
# ctlv2/ctlv3 behavior unchanged.
async def test_bass3_defines_z1daytemp_read_at_0x22() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/geniaset_bass3_discovery.yaml")
        )
        controller = graph.heating_controller_result().node
        assert controller is not None
        assert controller.scan_type == "BASS3"

        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = graph

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        z1day = [definition for definition in definitions if ",Z1DayTemp," in definition]
        # The BAS-family read and write overrides use the 0x22 sub-address.
        assert len(z1day) == 2
        assert any(definition.startswith("r5,") and ",020003002200," in definition for definition in z1day)
        assert any(definition.startswith("wi,") and ",020103002200," in definition for definition in z1day)
        assert not any(",020003000700," in definition for definition in definitions)
        assert not any(",020103000700," in definition for definition in definitions)


# Intent: the issue #129 BASS3 capture enables the evidence-gated Zone 2 setpoint path.
# Why: upstream #522 documents the BAS-family Z1..Z3 0x07 to 0x22 move, while the capture proves Zone 2 ownership.
async def test_issue129_bass3_defines_zone2_daytemp_at_0x22() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/saunier_duval_f34_issue129_discovery.yaml")
        )
        controller = graph.heating_controller_result().node
        assert controller is not None
        assert controller.scan_type == "BASS3"
        assert "bass.Z2OpMode" in graph.raw_registers

        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = graph

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        z2day = [definition for definition in definitions if ",Z2DayTemp," in definition]
        assert len(z2day) == 2
        assert any(definition.startswith("r5,") and ",020003012200," in definition for definition in z2day)
        assert any(definition.startswith("wi,") and ",020103012200," in definition for definition in z2day)


# Intent: a discovered but unavailable Zone 2 day setpoint creates no entity.
# Why: a static mode value without live zone evidence must not fabricate a normal temperature control.
def test_issue129_zone2_daytemp_absent_value_stays_unavailable() -> None:
    graph = DISCOVERY.DiscoveryService.build_device_graph(
        ["scan.15 = Vaillant;BASS3;0708;4304", "bass Z2OpMode = day", "bass Z2DayTemp = no data stored"]
    )
    entities = FACTORY.EntityFactoryService().generate(graph)
    z2_entities = [entity for entity in entities if entity.circuit == "bass" and entity.name == "Z2DayTemp"]
    assert not z2_entities
    assert "bass.Z2DayTemp" in graph.placeholder_registers


# Intent: BASV3 uses the same 0x22 day-setpoint read and write positions as BASS3.
# Why: covers the shared BAS-family gate with a second community-supported scan type.
async def test_basv3_defines_z1daytemp_read_and_write_at_0x22() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/arotherm_plus_basv3_discovery.yaml")
        )
        controller = graph.heating_controller_result().node
        assert controller is not None
        assert controller.scan_type == "BASV3"

        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = graph

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        z1day = [definition for definition in definitions if ",Z1DayTemp," in definition]
        assert len(z1day) == 2
        assert any(definition.startswith("r5,") and ",020003002200," in definition for definition in z1day)
        assert any(definition.startswith("wi,") and ",020103002200," in definition for definition in z1day)
        assert not any(",020003000700," in definition for definition in definitions)
        assert not any(",020103000700," in definition for definition in definitions)

        assert not any(",Z2DayTemp," in definition for definition in definitions)


# Intent: a ctlv3/ctlv2 controller keeps the shipped day-setpoint definition; the
# BAS-family 0x22 override must not be emitted when it would needlessly replace a
# working 0x07 read.
# Why: guarantees the gating does not regress ctlv2/ctlv3 zone readback.
async def test_ctlv3_does_not_override_z1daytemp_read() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/hmux0_issue99_2026-09-10_173229.yaml")
        )
        controller = graph.heating_controller_result().node
        assert controller is not None
        assert controller.scan_type == "CTLV3"

        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = graph

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        # No 0x22 read or write override on a non-BAS controller.
        assert not any(",Z1DayTemp," in definition for definition in definitions)


# Intent: HMUX0 scan bootstrap defines exactly the confirmed hmux0 register set.
# Why: guards the scan-bootstrap path from emitting generic hmu alias definitions.
async def test_hmux0_scan_bootstrap_defines_only_confirmed_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(
            ["scan.08 = Vaillant;HMUX0;0303;0504", "ctlv3 HwcOpMode = auto"]
        )

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        hmux0_definitions = [definition for definition in definitions if ",hmux0," in definition]
        assert len(hmux0_definitions) == 24
        assert all(definition.split(",", 3)[1] != "hmu" for definition in definitions)


# Intent: after HMUX0 registers are defined, discovery re-runs and merges the newly found live values.
# Why: protects the discover-before/after define flow and heat-pump circuit resolution.
async def test_hmux0_scan_bootstrap_rediscovers_defined_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        initial_lines = ["scan.08 = Vaillant;HMUX0;0303;0504", "ctlv3 HwcOpMode = auto"]
        defined_lines = [
            *initial_lines,
            "hmux0 RunDataReturnTemp = 28.2184",
            "hmux0 YieldHc = 4662",
            "hmux0 CopHc = 3.5",
        ]
        first_graph = DISCOVERY.DiscoveryService.build_device_graph(initial_lines)
        final_graph = DISCOVERY.DiscoveryService.build_device_graph(defined_lines)
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.version = "26.1"
        mock_ebus.connect = AsyncMock()
        mock_ebus.define_register = AsyncMock(return_value="done")
        mock_ebus.read_register = AsyncMock(return_value=None)
        discovery = MagicMock()
        discovery.discover = AsyncMock(side_effect=(first_graph, final_graph))
        module = sys.modules["vaillant_ebus.coordinator"]
        original_ebus = module.EbusService
        original_discovery = module.DiscoveryService
        module.EbusService = MagicMock(return_value=mock_ebus)
        module.DiscoveryService = MagicMock(return_value=discovery)
        try:
            await c._ebusd_connect_and_discover()
        finally:
            module.EbusService = original_ebus
            module.DiscoveryService = original_discovery

        assert discovery.discover.await_count == 2
        definitions = [call.args[0] for call in mock_ebus.define_register.await_args_list]
        assert len([definition for definition in definitions if ",hmux0," in definition]) == 24
        assert all(definition.split(",", 3)[1] != "hmu" for definition in definitions)
        assert c.heat_pump_circuit == "hmux0"
        assert c.heating_circuit == "ctlv3"
        assert c._graph is not None
        assert c._graph.raw_registers["hmux0.RunDataReturnTemp"] == "28.2184"


# Intent: a stale hmu alias find line does not divert generic definitions away from hmux0.
# Why: regression for issue #99 ensuring discovered scan identity wins over stale alias records.
async def test_hmux0_scan_bootstrap_ignores_generic_hmu_alias_definitions() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "scan.08 = Vaillant;HMUX0;0303;0504",
                "hmu YieldTotal =  (ERR: invalid position)",
                "ctlv3 HwcOpMode = auto",
            ]
        )

        await c._define_custom_registers()

        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        assert len([definition for definition in definitions if ",hmux0," in definition]) == 24
        assert all(definition.split(",", 3)[1] != "hmu" for definition in definitions)


# Intent: _usable_register_value rejects implausible HMUX0 return temperatures.
# Why: stops absurd decode results from becoming sensor state.
@pytest.mark.parametrize("raw", ("1082.88", "-423.75"))
def test_usable_value_rejects_invalid_hmux0_return_temperature(raw: str) -> None:
    assert _usable_register_value("hmux0.RunDataReturnTemp", raw) is None


# Intent: plausible HMUX0 return temperatures pass validation unchanged.
# Why: ensures the range guard does not reject valid readings.
@pytest.mark.parametrize("raw", ("28.0172", "28.2184"))
def test_usable_value_keeps_valid_hmux0_return_temperature(raw: str) -> None:
    assert _usable_register_value("hmux0.RunDataReturnTemp", raw) == raw


# Intent: an invalid polled HMUX0 return temperature clears the previously stored value.
# Why: protects the rejection path so a bad decode replaces a stale good value with unavailable.
async def test_hmux0_return_temperature_clears_after_invalid_poll() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(["hmux0 RunDataReturnTemp = 28.2184"])
        c.registers["hmux0.RunDataReturnTemp"] = EbusdRegister(
            circuit="hmux0",
            name="RunDataReturnTemp",
            fields=["value"],
            value={"value": "28.2184"},
            has_data=True,
        )
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.find_registers = AsyncMock(return_value=["hmux0 RunDataReturnTemp = -423.75"])
        c.ebus.read_register = AsyncMock(return_value=None)
        c._last_energy_poll = datetime.now()

        values = await c._async_update_data()

        assert c.registers["hmux0.RunDataReturnTemp"].value["value"] is None
        assert "hmux0.RunDataReturnTemp.value" not in values["ebusd"]


# Intent: an invalid polled value is not overwritten by the cached prior value.
# Why: prevents cache fallback from resurrecting a rejected reading.
async def test_hmux0_return_temperature_invalid_poll_does_not_restore_cache() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(["hmux0 RunDataReturnTemp = 28.2184"])
        c.registers["hmux0.RunDataReturnTemp"] = EbusdRegister(
            circuit="hmux0",
            name="RunDataReturnTemp",
            fields=["value"],
            value={"value": "28.2184"},
            has_data=True,
        )
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.find_registers = AsyncMock(return_value=["hmux0 RunDataReturnTemp = 1082.88"])
        c.ebus.read_register = AsyncMock(return_value=None)
        c._async_load_cache = AsyncMock(return_value={"hmux0.RunDataReturnTemp.value": "28.2184"})
        c._last_energy_poll = datetime.now()

        values = await c._async_update_data()

        assert c.registers["hmux0.RunDataReturnTemp"].value["value"] is None
        assert "hmux0.RunDataReturnTemp.value" not in values["ebusd"]


# Intent: date-coded b516 definitions refresh at the day rollover and failed definitions retry until success.
# Why: protects long-running sessions from keeping stale date-coded registers.
async def test_runtime_definitions_roll_over_and_retry_failures(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c._graph = _make_graph()
        c.ebus.define_register = AsyncMock(return_value="done")
        clock = MagicMock()
        clock.now.return_value = datetime(2026, 8, 31, 23, 59)
        monkeypatch.setattr(COORDINATOR, "datetime", clock)
        await c._define_custom_registers()
        c.ebus.define_register.reset_mock()
        await c._define_custom_registers()
        c.ebus.define_register.assert_not_awaited()
        clock.now.return_value = datetime(2026, 9, 1)
        c.ebus.define_register.return_value = "ERR: temporarily unavailable"
        await c._define_custom_registers()
        assert c.ebus.define_register.await_count == 5
        c.ebus.define_register.reset_mock()
        c.ebus.define_register.return_value = "done"
        await c._define_custom_registers()
        definitions = [call.args[0] for call in c.ebus.define_register.await_args_list]
        assert len(definitions) == 5
        date_bytes = MAPPING.b516_date_bytes(clock.now.return_value)
        assert all(f"{date_bytes},value" in definition for definition in definitions)


# Intent: a register added by fallback read is published to platform adders exactly once.
# Why: prevents duplicate entities when a fallback-added register later appears in discovery.
async def test_fallback_new_register_publishes_entity_once(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(["hmu OutsideTemp = 18.5"])
        c.entities = c.entity_factory.generate(c._graph)
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.read_register = AsyncMock(return_value="200")
        key = "hmu.CoolElecConsDay"
        monkeypatch.setattr(COORDINATOR, "REGISTER_MAP", {key: MAPPING.REGISTER_MAP[key]})
        adder = MagicMock()
        c.register_entity_adder("sensor", adder)
        await c._fallback_read()
        await c._apply_discovery_graph(c._graph, "initial")
        adder.assert_called_once()
        assert [e.key for e in adder.call_args.args[0]] == [f"{key}.value"]


# Intent: live discovery updates the case-variant register key in place without adding a second entity.
# Why: prevents duplicate HwcSfMode/HwcSFMode entities caused by ebusd case differences.
async def test_live_discovery_updates_cached_case_variant_without_duplicate() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._async_load_cache = AsyncMock(return_value={"ctlv2.HwcSfMode.value": "auto"})
        await c._async_seed_entities_from_cache()
        description = next(e for e in c.entities if e.name == "HwcSfMode")
        adder = MagicMock()
        c.register_entity_adder(description.entity_type, adder)
        graph = DISCOVERY.DiscoveryService.build_device_graph(["ctlv2 HwcSFMode = load"])
        await c._apply_discovery_graph(graph, "initial")
        adder.assert_not_called()
        assert description.key == "ctlv2.HwcSFMode.value"
        assert len({e.unique_id for e in c.entities}) == len(c.entities)
        values = await c._async_values_from_registers()
        assert values[description.key] == "load"


# Intent: a cached energy register recovers once ebusd reports live values after a no-data discovery.
# Why: protects cached energy entities from staying permanently unavailable after idle discovery.
async def test_cached_energy_recovers_after_no_data_discovery(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        key = "hmu.CoolElecConsDay"
        c._async_load_cache = AsyncMock(return_value={f"{key}.value": "100"})
        await c._async_seed_entities_from_cache()
        c._cache_seeded = c._ebusd_connected = True
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c.ebus.read_register = AsyncMock(return_value=None)
        monkeypatch.setattr(COORDINATOR, "REGISTER_MAP", {key: MAPPING.REGISTER_MAP[key]})
        await c._define_custom_registers()
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            ["hmu OutsideTemp = 18.5", "hmu CoolElecConsDay = no data stored"]
        )
        await c._apply_discovery_graph(graph, "initial")
        c.ebus.find_registers = AsyncMock(return_value=["hmu CoolElecConsDay = 100"])
        c.ebus.read_register.return_value = "200"
        values = await c._async_update_data()
        assert values["ebusd"][f"{key}.value"] == "200"
        assert key in c._graph.raw_registers


# Intent: a register that previously reported a value is cleared when a later
# find returns no data, so the entity cannot freeze on a stale reading.
# Why: issue #99 - without clearing, _async_values_from_registers keeps emitting
# the old value and the sensor shows a frozen state even though ebusd no longer
# exposes data for the register.
async def test_register_cleared_when_find_returns_no_data() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c.ebus.read_register = AsyncMock(return_value=None)
        # First poll: register carries a value.
        c.ebus.find_registers = AsyncMock(return_value=["hmu OutsideTemp = 18.5"])
        values = await c._async_update_data()
        assert values["ebusd"]["hmu.OutsideTemp.value"] == "18.5"
        # Second poll: ebusd no longer returns data for the register.
        c.ebus.find_registers = AsyncMock(return_value=["hmu OutsideTemp = no data stored"])
        values = await c._async_update_data()
        assert "hmu.OutsideTemp.value" not in values["ebusd"]


# Intent: a duplicate stale "no data stored" line in the same find batch must
# not wipe a readable value for the same register, in either line order.
# Why: ebusd's `find -a` lists some writable registers twice (a readable
# definition and a stale one), which made the issue #99 clearing flip the DHW
# entities to unknown on every poll.
async def test_duplicate_no_data_line_does_not_clear_readable_value() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c.ebus.read_register = AsyncMock(return_value=None)
        c.ebus.find_registers = AsyncMock(return_value=["ctlv2 HwcOpMode = day", "ctlv2 HwcOpMode = no data stored"])
        values = await c._async_update_data()
        assert values["ebusd"]["ctlv2.HwcOpMode.value"] == "day"
        c.ebus.find_registers = AsyncMock(return_value=["ctlv2 HwcOpMode = no data stored", "ctlv2 HwcOpMode = day"])
        values = await c._async_update_data()
        assert values["ebusd"]["ctlv2.HwcOpMode.value"] == "day"


# Intent: a no-data find line clears every field of a multi-field register, not
# just the synthetic `value`, so the per-field sensors cannot freeze.
# Why: issue #99/#102 - a whole-register "Status01 = no data stored" line left
# the named fields (temp, pumpstate, ...) emitting their last decoded values.
async def test_multi_field_no_data_clears_all_fields() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        repairs_module.async_create_ebusd_unreachable.reset_mock()
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.last_find_usable = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c.ebus.read_register = AsyncMock(return_value=None)
        c.ebus.find_registers = AsyncMock(return_value=["hmu Status01 = 40;35;12;48;50;1"])
        values = await c._async_update_data()
        assert "hmu.Status01.temp" in values["ebusd"]
        assert "hmu.Status01.pumpstate" in values["ebusd"]
        c.ebus.find_registers = AsyncMock(return_value=["hmu Status01 = no data stored"])
        c.ebus.last_find_usable = True
        values = await c._async_update_data()
        assert "hmu.Status01.temp" not in values["ebusd"]
        assert "hmu.Status01.pumpstate" not in values["ebusd"]
        assert c.ebus.is_connected is True
        repairs_module.async_create_ebusd_unreachable.assert_not_awaited()


# Intent: a completed error-only find keeps recovery pending and skips fallback reads.
# Why: register-shaped ERR rows cannot authorize a graph update or clear a repair.
async def test_poll_error_only_find_keeps_repair_pending() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = coordinator._ebusd_connected = True
        coordinator._ebusd_repair_pending = True
        coordinator._graph = _make_graph()
        coordinator._last_energy_poll = datetime.now()
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.last_find_usable = False
        ebus.find_registers = AsyncMock(return_value=["ctlv2 Hc1FlowTempCalc = (ERR: invalid position)"])
        ebus.read_register = AsyncMock(return_value="20")
        coordinator.ebus = ebus
        repairs_module.async_dismiss_ebusd_unreachable.reset_mock()

        await coordinator._async_update_data()

        assert coordinator._ebusd_repair_pending is True
        repairs_module.async_dismiss_ebusd_unreachable.assert_not_awaited()
        ebus.read_register.assert_not_awaited()


# Intent: clear prior readings when an error-only find reports the register unavailable.
# Why: retaining a value from an earlier poll would present stale data as current after an explicit bus error.
async def test_poll_error_only_find_clears_previous_value_without_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        graph = _make_graph({"hmu.FlowTemp": "28"})
        coordinator._graph = graph
        coordinator._cache_seeded = coordinator._ebusd_connected = True
        coordinator._ebusd_repair_pending = True
        coordinator._last_energy_poll = datetime.now()
        coordinator.registers["hmu.FlowTemp"] = EbusdRegister(
            circuit="hmu",
            name="FlowTemp",
            fields=["value"],
            value={"value": "28"},
            has_data=True,
        )
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.last_find_usable = False
        ebus.find_registers = AsyncMock(return_value=["hmu FlowTemp = ERR: invalid position"])
        ebus.read_register = AsyncMock(return_value="28")
        coordinator.ebus = ebus

        await coordinator._async_update_data()

        assert coordinator._graph is graph
        assert coordinator.registers["hmu.FlowTemp"].value == {"value": None}
        assert coordinator.registers["hmu.FlowTemp"].has_data is False
        assert graph.error_registers == {"hmu.FlowTemp"}
        assert coordinator._ebusd_repair_pending is True
        ebus.read_register.assert_not_awaited()


# Intent: replace stale raw data with a delayed-discovery placeholder/error row.
# Why: merging graph metadata must not resurrect an older value after discovery reports it unavailable.
def test_merge_delayed_error_placeholder_replaces_existing_raw_value() -> None:
    key = "ctlv3.HwcOpMode"
    existing = DeviceGraph(nodes={}, raw_registers={key: "auto"}, placeholder_registers=set())
    discovered = DeviceGraph(
        nodes={},
        raw_registers={},
        placeholder_registers={key},
        error_registers={key},
    )

    merged = COORDINATOR._merge_device_graphs(existing, discovered)

    assert key not in merged.raw_registers
    assert key in merged.placeholder_registers
    assert merged.error_registers == {key}


# Intent: preserve activity when a partial delayed find omits an older live register.
# Why: omitted rows stay in the merged raw graph and must continue to justify their device.
def test_merge_delayed_partial_find_recomputes_node_data_from_merged_raw() -> None:
    existing = DISCOVERY.DiscoveryService.build_device_graph(
        [
            "scan.15 = Vaillant;CTLV3;0808;8004",
            "ctlv3 Z1OpMode = auto",
            "ctlv3 Z1RoomTemp = 20.5",
        ]
    )
    discovered = DISCOVERY.DiscoveryService.build_device_graph(
        [
            "scan.15 = Vaillant;CTLV3;0808;8004",
            "ctlv3 Z1OpMode = no data stored",
        ]
    )

    merged = COORDINATOR._merge_device_graphs(existing, discovered)

    assert merged.raw_registers["ctlv3.Z1RoomTemp"] == "20.5"
    assert merged.nodes["z1"].has_data is True


# Intent: delayed discovery clears the live register value when a placeholder supersedes raw data.
# Why: listeners must not publish the old value between rediscovery and the next regular poll.
async def test_apply_delayed_error_placeholder_clears_live_register_value() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        existing = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "scan.15 = Vaillant;CTLV3;0808;8004",
                "ctlv3 Z1OpMode = auto",
                "ctlv3 HwcOpMode = auto",
            ]
        )
        discovered = DISCOVERY.DiscoveryService.build_device_graph(
            [
                "scan.15 = Vaillant;CTLV3;0808;8004",
                "ctlv3 Z1OpMode = auto",
                "ctlv3 HwcOpMode = (ERR: invalid position)",
            ]
        )
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._graph = existing
        coordinator.registers["ctlv3.HwcOpMode"] = EbusdRegister(
            circuit="ctlv3",
            name="HwcOpMode",
            fields=["value"],
            value={"value": "auto"},
            has_data=True,
        )
        coordinator.ebus = MagicMock()
        coordinator.ebus.is_connected = False
        coordinator.data = {"ebusd": {"ctlv3.HwcOpMode.value": "auto"}}
        listener_snapshots: list[dict] = []
        coordinator.async_update_listeners = MagicMock(side_effect=lambda: listener_snapshots.append(coordinator.data))

        await coordinator._apply_discovery_graph(discovered, "delayed")

        assert coordinator._graph.raw_registers.get("ctlv3.HwcOpMode") is None
        assert "ctlv3.HwcOpMode" in coordinator._graph.placeholder_registers
        assert coordinator._graph.error_registers == {"ctlv3.HwcOpMode"}
        assert coordinator.registers["ctlv3.HwcOpMode"].value == {"value": None}
        assert coordinator.registers["ctlv3.HwcOpMode"].has_data is False
        assert coordinator._graph.nodes["dhw"].has_data is False
        assert "ctlv3.HwcOpMode.value" not in coordinator.data["ebusd"]
        assert listener_snapshots == [coordinator.data]
        assert "ctlv3.HwcOpMode.value" not in await coordinator._async_load_cache()


# Intent: block fallback polling when an unusable find leaves an older graph cached.
# Why: stale discovery metadata must not authorize active map probes after parser rejection.
async def test_fallback_read_skips_probes_after_unusable_find_with_retained_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        graph = _make_graph()
        coordinator._graph = graph
        coordinator._last_find_keys = {"hmu.Status"}
        coordinator.registers = {"hmu.Status": MagicMock(value={"value": "Standby"})}
        original_registers = dict(coordinator.registers)
        ebus = MagicMock()
        ebus.is_connected = True
        ebus.last_find_usable = False
        ebus.read_register = AsyncMock(return_value="20")
        coordinator.ebus = ebus

        await coordinator._fallback_read(include_placeholders=True, include_energy=True)

        ebus.read_register.assert_not_awaited()
        assert coordinator._graph is graph
        assert coordinator._last_find_keys == {"hmu.Status"}
        assert coordinator.registers == original_registers


# Intent: keep error placeholders visible while skipping their active fallback reads.
# Why: a mixed valid/error find proves the graph exists, but an ERR row still does not authorize polling.
async def test_poll_skips_error_placeholder_until_a_later_find_recovers_it(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        error_lines = [
            "scan.15 = Vaillant;CTLV2;0514;1104",
            "ctlv2 Z1OpMode = auto",
            "ctlv2 HwcOpMode = (ERR: invalid position)",
            "ctlv2 Hc1FlowTempCalc = no data stored",
        ]
        recovered_lines = [
            line.replace("HwcOpMode = (ERR: invalid position)", "HwcOpMode = no data stored") for line in error_lines
        ]
        graph = DISCOVERY.DiscoveryService.build_device_graph(error_lines)
        monkeypatch.setattr(
            COORDINATOR,
            "REGISTER_MAP",
            {
                "ctlv2.HwcOpMode": MAPPING.RegisterMeta(enabled=True, fallback_read=True),
                "ctlv2.Hc1FlowTempCalc": MAPPING.RegisterMeta(enabled=True, fallback_read=True),
            },
        )
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._graph = graph
        coordinator._cache_seeded = coordinator._ebusd_connected = True
        coordinator._last_energy_poll = datetime.now()
        coordinator._last_placeholder_poll = datetime.now() - timedelta(days=1)
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.last_find_usable = True
        coordinator.ebus.find_registers = AsyncMock(side_effect=[error_lines, recovered_lines])
        coordinator.ebus.read_register = AsyncMock(return_value=None)

        await coordinator._async_update_data()

        assert "ctlv2.HwcOpMode" in coordinator._graph.placeholder_registers
        assert coordinator._graph.error_registers == {"ctlv2.HwcOpMode"}
        assert [call.args[:2] for call in coordinator.ebus.read_register.await_args_list] == [
            ("ctlv2", "Hc1FlowTempCalc")
        ]

        coordinator._runtime_definitions["error_energy"] = "r,ctlv2,HwcOpMode,HwcOpMode,31,1,B516,14"
        coordinator.ebus.read_register.reset_mock()
        await coordinator._fallback_read(include_placeholders=True, include_energy=True)
        assert [call.args[:2] for call in coordinator.ebus.read_register.await_args_list] == [
            ("ctlv2", "Hc1FlowTempCalc")
        ]

        coordinator.ebus.read_register.reset_mock()
        coordinator._last_placeholder_poll = datetime.now() - timedelta(days=1)
        await coordinator._async_update_data()

        assert coordinator._graph.error_registers == set()
        assert {call.args[:2] for call in coordinator.ebus.read_register.await_args_list} == {
            ("ctlv2", "HwcOpMode"),
            ("ctlv2", "Hc1FlowTempCalc"),
        }


# Intent: mixed valid and field-shaped find rows update only standalone bus registers.
# Why: field suffixes are parsed values, never independent cache entries or fallback targets.
async def test_poll_ignores_field_shaped_find_rows() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        lines = [
            "scan.15 = Vaillant;CTLV2;0514;1104",
            "ctlv2 Z1OpMode = auto",
            "ctlv2 Status01.temp = 21.0",
        ]
        coordinator._graph = DISCOVERY.DiscoveryService.build_device_graph(lines)
        coordinator._cache_seeded = coordinator._ebusd_connected = True
        coordinator._last_energy_poll = datetime.now()
        coordinator._last_placeholder_poll = datetime.now()
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.last_find_usable = True
        coordinator.ebus.find_registers = AsyncMock(return_value=lines)
        coordinator.ebus.read_register = AsyncMock(return_value=None)

        await coordinator._async_update_data()

        assert "ctlv2.Z1OpMode" in coordinator.registers
        assert "ctlv2.Status01.temp" not in coordinator.registers
        assert not any(
            call.args == ("ctlv2", "Status01.temp") for call in coordinator.ebus.read_register.await_args_list
        )


# Intent: a syntactically usable scan-only response cannot clear repair without an owner graph.
# Why: a successful poll is not authoritative until it identifies at least one device node.
async def test_poll_without_graph_nodes_keeps_repair_pending() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = coordinator._ebusd_connected = True
        coordinator._ebusd_repair_pending = True
        coordinator._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        coordinator._define_custom_registers = AsyncMock()
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.last_find_usable = True
        ebus.find_registers = AsyncMock(return_value=["scan.15 = Vaillant;CTLV2;0514;1104"])
        ebus.read_register = AsyncMock(return_value=None)
        coordinator.ebus = ebus
        repairs_module.async_dismiss_ebusd_unreachable.reset_mock()

        await coordinator._async_update_data()

        assert coordinator.discovery_ready is False
        assert coordinator._ebusd_repair_pending is True
        repairs_module.async_dismiss_ebusd_unreachable.assert_not_awaited()


# Intent: a transport reconnect requires fresh discovery before services use the cached graph.
# Why: circuit ownership may change with the new ebusd session.
async def test_transport_reconnect_requires_fresh_discovery() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        c._graph = _make_graph()
        repairs_module.async_dismiss_ebusd_unreachable.reset_mock()
        repairs_module.async_create_ebusd_unreachable.reset_mock()
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c.ebus.read_register = AsyncMock(return_value=None)
        c.ebus.disconnect = AsyncMock()
        await c._define_custom_registers()
        c.ebus.find_registers = AsyncMock(side_effect=ConnectionError())
        c.ebus._reconnect = AsyncMock(return_value=True)
        old_ebus = c.ebus
        await c._async_update_data()
        assert not c._runtime_definitions
        assert c._last_energy_poll == datetime.min
        assert old_ebus.disconnect.await_count == 1
        assert c.ebus is None
        assert c.discovery is None
        assert c._ebusd_connected is False
        assert c._ebusd_repair_pending is True
        repairs_module.async_dismiss_ebusd_unreachable.assert_not_awaited()
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(c.hass)

        assert await c.async_read_register("ctlv2", "Z1DayTemp") is None
        assert await c.async_write_register("ctlv2", "Z1DayTemp", "21") is False
        old_ebus.read_register.assert_not_awaited()
        old_ebus.write_register.assert_not_awaited()

        scheduled: list = []
        c.hass.async_create_task = MagicMock(side_effect=scheduled.append)
        setup = AsyncMock()
        c._ebusd_connect_and_discover = setup
        await c._async_update_data()
        assert c._started is True
        assert len(scheduled) == 1
        await scheduled[0]
        setup.assert_awaited_once_with()


# Intent: a failed transport reconnect returns the coordinator to its initial retry path.
# Why: a stale disconnected EbusService must not block future connection attempts.
@pytest.mark.parametrize("reconnect_error", [False, True])
async def test_failed_transport_reconnect_retries_setup(reconnect_error: bool) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        c._started = True
        repairs_module.async_create_ebusd_unreachable.reset_mock()
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        c.ebus.read_register = AsyncMock(return_value=None)
        c.ebus.find_registers = AsyncMock(side_effect=ConnectionError("disconnected"))
        reconnect = ConnectionError("reconnect failed") if reconnect_error else False
        c.ebus._reconnect = AsyncMock(side_effect=reconnect) if reconnect_error else AsyncMock(return_value=reconnect)

        await c._async_update_data()

        assert c._ebusd_connected is False
        assert c._started is False
        assert c._ebusd_repair_pending is True
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(c.hass)

        scheduled: list = []
        c.hass.async_create_task = MagicMock(side_effect=scheduled.append)
        reconnect_setup = AsyncMock()
        c._ebusd_connect_and_discover = reconnect_setup
        await c._async_update_data()
        assert c._started is True
        assert len(scheduled) == 1
        await scheduled[0]
        reconnect_setup.assert_awaited_once_with()


# Intent: applying a discovery graph logs the generated entity/platform breakdown.
# Why: provides observable diagnostics for discovery and entity generation.
async def test_apply_discovery_logs_entity_platform_breakdown(caplog) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        graph = _make_graph()
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value=None)
        coordinator.ebus = mock_ebus
        coordinator.discovery = MagicMock()

        with caplog.at_level("INFO", logger="vaillant_ebus.coordinator"):
            await coordinator._apply_discovery_graph(graph, "initial")

        assert "entity descriptions after initial ebusd discovery" in caplog.text


# Intent: a failed connect leaves the coordinator unstarted and keeps its entity list intact.
# Why: protects startup resilience when ebusd is unreachable.
async def test_connect_failure_no_crash() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._started = True
        entities_before = len(c.entities)

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.connect = AsyncMock(side_effect=ConnectionError("refused"))

        module = sys.modules["vaillant_ebus.coordinator"]
        orig_ebus = module.EbusService
        module.EbusService = MagicMock(return_value=mock_ebus)
        try:
            await c._ebusd_connect_and_discover()
        finally:
            module.EbusService = orig_ebus
        assert len(c.entities) >= entities_before
        assert c._started is False


# Intent: a discovery parse failure preserves existing entities and leaves the graph unset.
# Why: protects against losing entities when discovery fails after a successful connect.
async def test_discovery_failure_preserves_cached_entities() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        entities_before = len(c.entities)

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.version = "23.2"
        mock_ebus.connect = AsyncMock()
        mock_ebus.define_register = AsyncMock(return_value="defined")

        mock_discovery = MagicMock()
        mock_discovery.discover = AsyncMock(side_effect=RuntimeError("parse error"))

        module = sys.modules["vaillant_ebus.coordinator"]
        orig_ebus = module.EbusService
        module.EbusService = MagicMock(return_value=mock_ebus)
        orig_disc = module.DiscoveryService
        module.DiscoveryService = MagicMock(return_value=mock_discovery)
        try:
            await c._ebusd_connect_and_discover()
        finally:
            module.EbusService = orig_ebus
            module.DiscoveryService = orig_disc

        assert len(c.entities) >= entities_before
        assert c._graph is None


# Intent: runtime definitions wait until discovery identifies a physical owner.
# Why: a live TCP connection alone must not define registers on a guessed circuit.
async def test_define_custom_registers_delegates_to_ebus() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.define_register = AsyncMock(return_value="defined")

        c.ebus = mock_ebus
        await c._define_custom_registers()

        assert mock_ebus.define_register.call_count == 0


# Intent: BAS controllers do not receive unsupported Hc1/Hc2 B524 poll definitions.
# Why: community BASS3 and BASV3 captures show invalid-position replies for every r5 sub-address.
@pytest.mark.parametrize(
    ("fixture", "scan_type"),
    [
        ("community/geniaset_bass3_discovery.yaml", "BASS3"),
        ("community/basv3_issue31_2026-09-17_203723_discovery.yaml", "BASV3"),
    ],
)
async def test_bas_controllers_skip_unverified_hc_state_definitions(fixture: str, scan_type: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
        controller = graph.heating_controller_result().node
        assert controller is not None
        assert controller.scan_type == scan_type

        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator._graph = graph

        await coordinator._define_custom_registers()

        definitions = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        assert not any(any(f",{name}," in definition for name in HC_STATE_REGISTER_NAMES) for definition in definitions)
        assert any(
            f",{controller.circuit},Z1DayTemp," in definition and ",020003002200," in definition
            for definition in definitions
        )
        assert any(
            f",{controller.circuit},Z1DayTemp," in definition and ",020103002200," in definition
            for definition in definitions
        )


# Intent: no controller receives unverified Hc1/Hc2 B524 active reads.
# Why: captures and owner ebusd logs show invalid-position replies across the observed scan families.
@pytest.mark.parametrize(
    ("fixture", "scan_type"),
    [
        ("community/arotherm_ecotec_discovery.yaml", "CTLV2"),
        ("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml", "CTLV3"),
    ],
)
async def test_controllers_skip_unverified_hc_state_definitions(fixture: str, scan_type: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
        controller = graph.heating_controller_result().node
        assert controller is not None
        assert controller.scan_type == scan_type

        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator._graph = graph

        await coordinator._define_custom_registers()

        definitions = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        assert not any(any(f",{name}," in definition for name in HC_STATE_REGISTER_NAMES) for definition in definitions)


# Intent: the #32 room-temperature select writes through its discovered CTLV3 circuit.
# Why: the logical entity must not send its state change to a ctlv2 alias.
async def test_issue32_room_temperature_select_write_uses_ctlv3() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml", after=True)
        )
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._graph = graph
        coordinator._ebusd_connected = True
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value="thermostat"))
        coordinator.async_request_refresh = AsyncMock()

        assert await coordinator.async_write_register("ctlv3", "Hc1RoomTempSwitchOn", "thermostat")
        coordinator.ebus.write_register.assert_awaited_once_with(
            "ctlv3", "Hc1RoomTempSwitchOn", "thermostat", strict_verify=True
        )


# Intent: discovery removes a cached sensor description when its CTLV3 replacement is a select.
# Why: otherwise the sensor can be forwarded from cache after its registry entry is retired.
@pytest.mark.parametrize("source", ["initial", "delayed"])
async def test_issue32_select_retires_cached_sensor_description(source: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        entry = _entry()
        entry.entry_id = "entry-1"
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml", after=True)
        )
        select = next(
            entity for entity in EntityFactoryService().generate(graph) if entity.name == "Hc1RoomTempSwitchOn"
        )
        cached_sensor = COORDINATOR.EntityDescription(
            circuit=select.circuit,
            name=select.name,
            field=select.field,
            meta=MAPPING.RegisterMeta(friendly_name="Room Temp Threshold (HC1)", unit="°C", entity_type="sensor"),
            register=select.register,
            raw_value=select.raw_value,
        )
        registry_entry = MagicMock(
            platform="vaillant_ebus",
            unique_id=f"{entry.entry_id}_{cached_sensor.unique_id}",
            entity_id="sensor.room_temp_threshold_hc1",
        )
        registry = MagicMock()
        registry.entities.get_entries_for_config_entry_id.return_value = [registry_entry]
        monkeypatch.setattr(COORDINATOR.entity_registry, "async_get", MagicMock(return_value=registry))

        coordinator = VaillantCoordinator(hass, entry)
        coordinator.entities = [cached_sensor]
        coordinator._graph = graph if source == "delayed" else None

        await coordinator._apply_discovery_graph(graph, source)

        replacements = [entity for entity in coordinator.entities if entity.name == "Hc1RoomTempSwitchOn"]
        assert len(replacements) == 1, [
            (entity.circuit, entity.entity_type, entity.unique_id, entity.meta.unit) for entity in replacements
        ]
        assert replacements[0].entity_type == "select"
        registry.async_remove.assert_called_once_with("sensor.room_temp_threshold_hc1")


# Intent: a no-data CTLV2 startup restores its existing threshold sensor registry entry.
# Why: CTLV2 keeps the supported sensor and may only be temporarily unavailable after restart.
async def test_ctlv2_threshold_sensor_reenabled_when_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        entry = _entry()
        entry.entry_id = "entry-ctlv2"
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/flexotherm_ctlv2_cooling_discovery.yaml", after=True)
        )
        graph.raw_registers.pop("ctlv2.Hc1RoomTempSwitchOn", None)
        graph.placeholder_registers.add("ctlv2.Hc1RoomTempSwitchOn")
        sensor = next(
            entity for entity in EntityFactoryService().generate(graph) if entity.name == "Hc1RoomTempSwitchOn"
        )
        registry_entry = MagicMock(
            platform="vaillant_ebus",
            unique_id=f"{entry.entry_id}_{sensor.unique_id}",
            entity_id="sensor.room_temp_threshold_hc1",
            disabled_by="integration",
        )
        registry = MagicMock()
        registry.entities.get_entries_for_config_entry_id.return_value = [registry_entry]
        monkeypatch.setattr(COORDINATOR.entity_registry, "async_get", MagicMock(return_value=registry))
        coordinator = VaillantCoordinator(hass, entry)

        assert graph.heating_controller_result().node.scan_type == "CTLV2"
        assert sensor.raw_value == ""
        assert sensor.enabled_by_default is True

        await coordinator._apply_discovery_graph(graph, "initial")

        registry.async_update_entity.assert_called_once_with(registry_entry.entity_id, disabled_by=None)
        retained = next(entity for entity in coordinator.entities if entity.name == "Hc1RoomTempSwitchOn")
        assert retained.entity_type == "sensor"
        assert retained.enabled_by_default is True


# Intent: runtime definitions are not sent while ebusd is disconnected.
# Why: avoids issuing protocol calls without a live connection.
async def test_define_custom_registers_skips_when_not_connected() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = False
        c.ebus = mock_ebus

        await c._define_custom_registers()
        assert mock_ebus.define_register.call_count == 0


# Intent: writing several registers triggers exactly one refresh after all writes succeed.
# Why: avoids per-register refresh storms and confirms write bundling.
async def test_async_write_registers_bundles_and_refreshes() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = _make_graph(
            {
                "hmu.RunDataStatuscode": "standby",
                "hmu.OutsideTemp": "18.5",
                "ctlv2.Z1OpMode": "auto",
                "ctlv2.Z1DayTemp": "20.0",
                "ctlv2.ManualCoolingStartDate": "14.08.2026",
                "ctlv2.ManualCoolingEndDate": "17.08.2026",
            }
        )
        c._ebusd_connected = True

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value=None))
        c.ebus = mock_ebus
        c.async_request_refresh = AsyncMock()

        ok = await c.async_write_registers(
            [("ctlv2", "ManualCoolingStartDate", "14.08.2026"), ("ctlv2", "ManualCoolingEndDate", "17.08.2026")]
        )

        assert ok is True
        assert mock_ebus.write_register.call_count == 2
        assert c.async_request_refresh.call_count == 1


# Intent: route logical write aliases through discovered circuit identity.
# Why: protects writes on ctlv3 installations from hitting the legacy ctlv2 alias.
async def test_async_write_register_resolves_discovered_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={"ctlv3": DeviceNode("ctlv3", DeviceType.HEATING_CONTROLLER, has_data=True)},
            raw_registers={},
            placeholder_registers=set(),
        )
        c._ebusd_connected = True
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value=None))
        c.ebus = mock_ebus
        c.async_request_refresh = AsyncMock()

        assert await c.async_write_register("ctlv2", "Z1DayTemp", "21", require_discovered=False) is True
        mock_ebus.write_register.assert_awaited_once_with("ctlv3", "Z1DayTemp", "21", strict_verify=True)


# Intent: a logical read alias resolves to the discovered circuit with an empty field.
# Why: protects reads on HMUX0 hardware from polling the hmu alias.
async def test_async_read_register_resolves_discovered_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={"hmux0": DeviceNode("hmux0", DeviceType.HEAT_PUMP, has_data=True)},
            raw_registers={},
            placeholder_registers=set(),
        )
        c._ebusd_connected = True
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="21")
        c.ebus = mock_ebus

        assert await c.async_read_register("hmu", "OutsideTemp") == "21"
        mock_ebus.read_register.assert_awaited_once_with("hmux0", "OutsideTemp", "")


# Intent: lifecycle teardown blocks user reads before they reach ebusd.
# Why: an unload can overlap a service call while the transport is still connected.
@pytest.mark.parametrize("lifecycle_flag", ["_stopped", "_unload_requested"])
async def test_async_read_register_is_lifecycle_gated(lifecycle_flag: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={"hmux0": DeviceNode("hmux0", DeviceType.HEAT_PUMP, has_data=True)},
            raw_registers={},
            placeholder_registers=set(),
        )
        c._ebusd_connected = True
        setattr(c, lifecycle_flag, True)
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="21")
        c.ebus = mock_ebus

        assert await c.async_read_register("hmu", "OutsideTemp") is None
        mock_ebus.read_register.assert_not_awaited()


# Intent: lifecycle teardown stops polling before cache or transport work starts.
# Why: a pending coordinator refresh must not repopulate entities during unload.
async def test_async_update_data_is_lifecycle_gated() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._unload_requested = True
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.find_registers = AsyncMock(return_value=[])

        assert await c._async_update_data() == {"ebusd": {}}
        c.ebus.find_registers.assert_not_awaited()
        assert c._cache_seeded is False


# Intent: an unload detected after find returns no values and does not save the cache.
# Why: lifecycle exits must not persist or publish state from an in-flight poll.
async def test_poll_after_unload_during_find_skips_cache_write() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        c._graph = _make_graph({"hmu.OutsideTemp": "20"})
        c._last_energy_poll = datetime.now()
        c._async_save_cache = AsyncMock()
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True

        # Intent: request teardown before the in-flight find result returns.
        # Why: the resulting poll exit must not call the cache-persisting values helper.
        async def _find_then_unload() -> list[str]:
            c._unload_requested = True
            return ["hmu OutsideTemp = 21"]

        c.ebus.find_registers = AsyncMock(side_effect=_find_then_unload)

        result = await c._async_update_data()

        assert result == {"ebusd": {}}
        c._async_save_cache.assert_not_awaited()


# Intent: a failed platform unload restores all coordinator scheduling gates.
# Why: HA keeps the entry loaded and must be able to retry discovery and analysis.
async def test_cancel_unload_request_restores_coordinator_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._started = True
        c._unload_requested = False
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.request_shutdown = MagicMock()
        c.ebus.clear_shutdown_request = MagicMock()
        c._pending_ebus = MagicMock(spec=EbusService)
        c._pending_ebus.clear_shutdown_request = MagicMock()
        c._schedule_delayed_rediscovery = MagicMock()
        c._schedule_analysis = MagicMock()

        c.request_unload()

        assert c._unload_requested is True
        assert c._started is False
        c.ebus.request_shutdown.assert_called_once_with()
        c._pending_ebus.request_shutdown.assert_called_once_with()

        c.cancel_unload_request()

        assert c._unload_requested is False
        assert c._started is False
        c.ebus.clear_shutdown_request.assert_called_once_with()
        c._pending_ebus.clear_shutdown_request.assert_called_once_with()
        c._schedule_delayed_rediscovery.assert_called_once_with()
        c._schedule_analysis.assert_called_once_with()


# Intent: an in-flight setup remains single-flight after a failed unload is cancelled.
# Why: the retry poll must not start a second transport while discovery is still running.
async def test_cancel_unload_request_does_not_duplicate_inflight_discovery() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = True
        c._async_values_from_registers = AsyncMock(return_value={})
        setup_started = asyncio.Event()
        allow_setup_to_finish = asyncio.Event()
        setup_calls = 0

        # Intent: hold the first setup call open while unload is cancelled.
        # Why: a second poll must wait for this task instead of starting another connection.
        async def _blocked_setup() -> None:
            nonlocal setup_calls
            setup_calls += 1
            setup_started.set()
            await allow_setup_to_finish.wait()

        c._ebusd_connect_and_discover = _blocked_setup
        c.hass.async_create_task = asyncio.create_task

        await c._async_update_data()
        await setup_started.wait()
        first_setup_task = c._setup_task
        assert first_setup_task is not None

        c.request_unload()
        c.cancel_unload_request()
        await c._async_update_data()
        assert setup_calls == 1

        allow_setup_to_finish.set()
        await first_setup_task
        await c._async_update_data()
        assert c._setup_task is not None
        await c._setup_task
        assert setup_calls == 2


# Intent: a cancelled setup task leaves the disconnected coordinator eligible to retry.
# Why: cancellation is not a completed connection attempt and must not strand polling.
async def test_cancelled_setup_task_retries_on_next_poll() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = True
        c._async_values_from_registers = AsyncMock(return_value={})
        setup_started = asyncio.Event()

        # Intent: hold setup open until the test cancels it.
        # Why: exercise the coordinator's cancelled-task recovery branch.
        async def _blocked_setup() -> None:
            setup_started.set()
            await asyncio.Event().wait()

        c._ebusd_connect_and_discover = _blocked_setup
        c.hass.async_create_task = asyncio.create_task
        await c._async_update_data()
        await setup_started.wait()
        first_setup_task = c._setup_task
        assert first_setup_task is not None
        first_setup_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_setup_task

        retry = AsyncMock()
        c._ebusd_connect_and_discover = retry
        scheduled: list[asyncio.Task] = []
        c.hass.async_create_task = lambda coro: scheduled.append(asyncio.create_task(coro)) or scheduled[-1]

        await c._async_update_data()

        assert c._started is True
        assert len(scheduled) == 1
        await scheduled[0]
        retry.assert_awaited_once_with()


# Intent: cancellation after transport promotion closes and clears the active setup client.
# Why: discovery cancellation must not leak a socket before the coordinator retries setup.
async def test_cancelled_setup_task_disconnects_promoted_ebusd_client(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        ebus = MagicMock(spec=EbusService)
        ebus.is_connected = True
        ebus.version = "26.1"
        ebus.connect = AsyncMock()
        ebus.disconnect = AsyncMock()
        ebus.request_shutdown = MagicMock()
        discover_started = asyncio.Event()

        # Intent: keep discovery suspended after setup promotes the connected client.
        # Why: cancellation at this point must clean self.ebus, not only _pending_ebus.
        async def _blocked_discovery() -> DeviceGraph:
            discover_started.set()
            await asyncio.Event().wait()

        discovery = MagicMock()
        discovery.discover = AsyncMock(side_effect=_blocked_discovery)
        monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
        monkeypatch.setattr(COORDINATOR, "DiscoveryService", MagicMock(return_value=discovery))
        c._setup_task = asyncio.create_task(c._async_run_setup_task())
        await discover_started.wait()
        assert c.ebus is ebus
        assert c._pending_ebus is None

        setup_task = c._setup_task
        setup_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await setup_task

        ebus.request_shutdown.assert_called_once_with()
        ebus.disconnect.assert_awaited_once_with()
        assert c.ebus is None
        assert c.discovery is None
        assert c._ebusd_connected is False
        assert c._started is False


# Intent: successful unload waits for a pending connection attempt and closes its client.
# Why: stopping only the promoted client can leave setup running after platform teardown.
async def test_async_stop_cancels_pending_setup_and_disconnects_client(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        connect_started = asyncio.Event()
        ebus = MagicMock(spec=EbusService)
        ebus.connect = AsyncMock()
        ebus.disconnect = AsyncMock()
        ebus.request_shutdown = MagicMock()

        # Intent: hold connect open until async_stop cancels setup.
        # Why: teardown must not return with an active pending transport task.
        async def _blocked_connect() -> None:
            connect_started.set()
            await asyncio.Event().wait()

        ebus.connect.side_effect = _blocked_connect
        monkeypatch.setattr(COORDINATOR, "EbusService", MagicMock(return_value=ebus))
        c._setup_task = asyncio.create_task(c._async_run_setup_task())
        await connect_started.wait()
        setup_task = c._setup_task

        await c.async_stop()
        stopped_setup = setup_task.done()
        if not stopped_setup:
            setup_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await setup_task

        assert stopped_setup
        ebus.request_shutdown.assert_called_once_with()
        ebus.disconnect.assert_awaited_once_with()
        assert c._pending_ebus is None
        assert c.ebus is None
        assert c._setup_task is None


# Intent: cache seeding leaves coordinator state untouched when unload starts during cache I/O.
# Why: an in-flight refresh must not repopulate cached registers or entities during platform teardown.
async def test_cache_seeding_stops_when_unload_starts_during_cache_load() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        # Intent: request teardown before returning cache contents.
        # Why: seeding must discard the awaited values before mutating coordinator state.
        async def _load_cache_then_unload() -> dict[str, str]:
            c._unload_requested = True
            return {"hmu.OutsideTemp.value": "21"}

        c._async_load_cache = AsyncMock(side_effect=_load_cache_then_unload)
        c._async_load_yaml_overrides = AsyncMock()

        await c._async_seed_entities_from_cache()

        assert c.registers == {}
        assert c._graph is None
        assert c.entities == []
        c._async_load_yaml_overrides.assert_not_awaited()


# Intent: cache seeding discards YAML overrides returned after unload starts.
# Why: no entity descriptions should be installed after teardown has begun.
async def test_cache_seeding_stops_when_unload_starts_during_yaml_load() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._async_load_cache = AsyncMock(return_value={"hmu.OutsideTemp.value": "21"})

        # Intent: request teardown while YAML overrides are loading.
        # Why: the cache graph and generated entities must remain uncommitted.
        async def _load_yaml_then_unload() -> dict:
            c._unload_requested = True
            return {}

        c._async_load_yaml_overrides = AsyncMock(side_effect=_load_yaml_then_unload)

        await c._async_seed_entities_from_cache()

        assert c.registers == {}
        assert c._graph is None
        assert c.entities == []


# Intent: fallback reads discard values returned after unload starts.
# Why: late transport replies must not repopulate registers or the discovery graph.
async def test_fallback_read_discards_result_when_unload_starts_during_read() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        c.ebus = mock_ebus
        c._graph = DeviceGraph(
            nodes={"hmu": DeviceNode("hmu", DeviceType.HEAT_PUMP, has_data=True)},
            raw_registers={},
            placeholder_registers=set(),
        )
        c._last_find_keys = set()
        c._fallback_candidate = MagicMock(return_value="hmu")
        c._async_load_yaml_overrides = AsyncMock(return_value={})

        # Intent: request teardown before returning a successful fallback value.
        # Why: the coordinator must discard this late reply without mutating state.
        async def _read_then_request_unload(*args, **kwargs) -> str:
            c._unload_requested = True
            return "42"

        mock_ebus.read_register = AsyncMock(side_effect=_read_then_request_unload)
        c.ebus = mock_ebus
        original_map = COORDINATOR.REGISTER_MAP
        COORDINATOR.REGISTER_MAP = {"hmu.UnseenFallback": MAPPING.RegisterMeta(enabled=True, fallback_read=True)}
        try:
            await c._fallback_read()
        finally:
            COORDINATOR.REGISTER_MAP = original_map

        assert c.registers == {}
        assert c._graph.raw_registers == {}
        mock_ebus.read_register.assert_awaited_once_with("hmu", "UnseenFallback", raise_transport_errors=True)


# Intent: cache data is ignored when unload starts during a fallback cache read.
# Why: an awaited cache load must not restore stale values into coordinator state during teardown.
async def test_fallback_read_stops_when_unload_starts_during_cache_load() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="no data stored")
        c.ebus = mock_ebus
        register = EbusdRegister(
            circuit="hmu", name="CachedFallback", fields=["value"], value={"value": "old"}, has_data=True
        )
        c.registers["hmu.CachedFallback"] = register
        c._graph = DeviceGraph(
            nodes={"hmu": DeviceNode("hmu", DeviceType.HEAT_PUMP, registers=["hmu.CachedFallback"], has_data=True)},
            raw_registers={"hmu.CachedFallback": "no data stored"},
            placeholder_registers=set(),
        )
        c._fallback_candidate = MagicMock(return_value="hmu")
        c._last_find_keys = set()

        # Intent: request teardown while the fallback cache read is suspended.
        # Why: the cache result must not overwrite the live coordinator register.
        async def _load_cache_then_unload() -> dict[str, str]:
            c._unload_requested = True
            return {"hmu.CachedFallback.value": "cached"}

        c._async_load_cache = AsyncMock(side_effect=_load_cache_then_unload)
        original_map = COORDINATOR.REGISTER_MAP
        COORDINATOR.REGISTER_MAP = {"hmu.CachedFallback": MAPPING.RegisterMeta(enabled=True, fallback_read=True)}
        try:
            await c._fallback_read()
        finally:
            COORDINATOR.REGISTER_MAP = original_map

        assert register.value == {"value": "old"}
        assert register.has_data is True
        c._async_load_cache.assert_awaited_once_with()


# Intent: discard cache output when unload starts while the cache executor is pending.
# Why: late cache writes can overwrite a newer coordinator's cache after reload.
async def test_save_cache_does_not_commit_after_unload_starts(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        cache_path = Path(c._cache_path)
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text('{"old":"value"}', encoding="utf-8")
        write_started = asyncio.Event()
        allow_write_to_finish = asyncio.Event()

        # Intent: delay the executor's cache writer until unload has been requested.
        # Why: the final cache path must retain the previous owner's content.
        async def _delayed_executor(func, *args):
            if func.__name__ in {"_write_cache_temp", "_write"}:
                write_started.set()
                await allow_write_to_finish.wait()
            return func(*args)

        c.hass.async_add_executor_job = _delayed_executor
        save_task = asyncio.create_task(c._async_save_cache({"new": "value"}))
        await write_started.wait()
        c._unload_requested = True
        allow_write_to_finish.set()
        await save_task

        assert cache_path.read_text(encoding="utf-8") == '{"old":"value"}'
        assert list(cache_path.parent.glob(".register_cache_*.tmp")) == []


# Intent: remove a staged cache if its executor continues after repeated task cancellation.
# Why: cancellation cleanup must not depend on awaiting the same worker a second time.
async def test_save_cache_repeated_cancellation_removes_staged_file(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        cache_path = Path(c._cache_path)
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text('{"old":"value"}', encoding="utf-8")
        write_started = asyncio.Event()
        allow_write_to_finish = asyncio.Event()
        write_finished = asyncio.Event()

        # Intent: keep the staged cache writer alive through repeated cancellation.
        # Why: its completion callback must remove the path without resuming the caller.
        async def _delayed_executor(func, *args):
            result = func(*args)
            if func.__name__ == "_write_cache_temp":
                write_started.set()
                await allow_write_to_finish.wait()
                write_finished.set()
            return result

        c.hass.async_add_executor_job = _delayed_executor
        save_task = asyncio.create_task(c._async_save_cache({"new": "value"}))
        await write_started.wait()
        save_task.cancel()
        save_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await save_task
        allow_write_to_finish.set()
        await write_finished.wait()
        await asyncio.sleep(0)

        assert cache_path.read_text(encoding="utf-8") == '{"old":"value"}'
        assert list(cache_path.parent.glob(".register_cache_*.tmp")) == []


# Intent: register services wait until the initial discovery graph is authoritative.
# Why: cache-seeded circuit aliases must not send bus reads or writes during setup.
async def test_register_services_do_not_use_cached_graph_during_setup() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = _make_graph()
        c._ebusd_connected = False
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="21")
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value="21"))
        c.ebus = mock_ebus

        assert await c.async_read_register("ctlv2", "Z1DayTemp") is None
        assert await c.async_write_register("ctlv2", "Z1DayTemp", "21", refresh=False) is False

        c._ebusd_connected = True
        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        assert await c.async_read_register("ctlv2", "Z1DayTemp") is None
        assert await c.async_write_register("ctlv2", "Z1DayTemp", "21", refresh=False) is False
        mock_ebus.read_register.assert_not_awaited()
        mock_ebus.write_register.assert_not_awaited()


# Intent: reads return None and skip the transport when the owner is missing or ambiguous.
# Why: prevents reading from an arbitrary circuit when the graph cannot identify one owner.
async def test_async_read_register_rejects_missing_or_ambiguous_owner() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="21")
        c.ebus = mock_ebus

        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        c._ebusd_connected = True
        assert await c.async_read_register("hmu", "OutsideTemp") is None

        c._graph = DeviceGraph(
            nodes={
                "hmux0": DeviceNode("hmux0", DeviceType.HEAT_PUMP),
                "hmu1": DeviceNode("hmu1", DeviceType.HEAT_PUMP),
            },
            raw_registers={},
            placeholder_registers=set(),
        )
        assert await c.async_read_register("hmu", "OutsideTemp") is None
        mock_ebus.read_register.assert_not_awaited()


# Intent: refuse writes when graph ownership cannot identify one controller.
# Why: avoids writing to the wrong controller in mixed installations.
async def test_async_write_register_rejects_ambiguous_discovered_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={
                "ctlv3": DeviceNode("ctlv3", DeviceType.HEATING_CONTROLLER, has_data=True),
                "basv3": DeviceNode("basv3", DeviceType.HEATING_CONTROLLER, has_data=True),
            },
            raw_registers={},
            placeholder_registers=set(),
        )
        c._ebusd_connected = True
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value=None))
        c.ebus = mock_ebus

        assert await c.async_write_register("ctlv2", "Z1DayTemp", "21") is False
        mock_ebus.write_register.assert_not_awaited()


# Intent: writes return False and skip the transport when no owning circuit is discovered.
# Why: prevents writing an alias register that has no discovered hardware owner.
async def test_async_write_register_rejects_missing_discovered_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        c._ebusd_connected = True
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value=None))
        c.ebus = mock_ebus

        assert await c.async_write_register("hmu", "SetMode", "auto") is False
        mock_ebus.write_register.assert_not_awaited()


# Intent: async_write_registers records each attempt in the write log with the
# resolved circuit and the verification result.
# Why: the discovery dump's `writes` section needs to show what the integration
# actually wrote (register, value, resolved circuit, success/error) so write-vs-app
# analysis works without manual ebusctl.
async def test_async_write_registers_records_write_log() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(["ctlv3 Z1DayTemp = 22.0"])
        c._ebusd_connected = True
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(
            side_effect=[
                WriteResult(success=True, verified_value="22.0"),
                WriteResult(success=False, error_message="ERR: element not found"),
            ]
        )
        c.ebus = mock_ebus

        assert await c.async_write_register("ctlv2", "Z1DayTemp", "22.0", refresh=False) is True
        assert await c.async_write_register("ctlv2", "Z1DayTemp", "23.0", refresh=False) is False

        log = c._write_log
        assert [entry["success"] for entry in log] == [True, False]
        assert log[0]["circuit"] == "ctlv2"
        assert log[0]["resolved_circuit"] == "ctlv3"
        assert log[0]["value"] == "22.0"
        assert log[1]["error"] == "ERR: element not found"


# Intent: the write log is a bounded ring buffer, so an unbounded write session
# cannot grow the dump payload without limit.
# Why: keeps the discovery dump small even after heavy write activity.
async def test_write_log_is_bounded() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        for i in range(COORDINATOR.WRITE_LOG_SIZE + 10):
            c._record_write("ctlv2", "Z1DayTemp", str(i), "ctlv2", True)
        assert len(c._write_log) == COORDINATOR.WRITE_LOG_SIZE
        assert c._write_log[0]["value"] == "10"


# Issue #109: on a BAI + CTLV0 boiler bus the BAI burner interface also owns a
# DHW setpoint, which previously made controller resolution AMBIGUOUS and let
# the bare runtime ctlv2 probe alias become the write target.
# Intent: a logical ctlv2 write on the real ecoTEC graph dispatches to ctlv0.
# Why: issue #109 - HA writes must land on the discovered controller, not ctlv2.
async def test_ecotec_boiler_write_targets_discovered_ctl0_not_bare_probe() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/ecotec_vrt380_15700_discovery.yaml")
        )
        c._ebusd_connected = True
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value=None))
        c.ebus = mock_ebus
        c.async_request_refresh = AsyncMock()

        assert c.heating_circuit == "ctlv0"
        assert await c.async_write_register("ctlv2", "Z1DayTemp", "21") is True
        assert mock_ebus.write_register.await_args.args[0] == "ctlv0"


# Intent: an unresolved empty graph makes heating_circuit and heat_pump_circuit return None.
# Why: enforces the no-fallback rule so climate routing never silently targets ctlv2 or hmu.
async def test_register_circuit_properties_do_not_fallback_with_unresolved_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())

        assert c.heating_circuit is None
        assert c.heat_pump_circuit is None


# Intent: route BAI logical writes only when a unique BAI controller is discovered.
# Why: protects boiler SetModeOverride writes from using a hardcoded bai alias.
async def test_async_set_mode_override_resolves_unique_bai_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={"bai0": DeviceNode("bai0", DeviceType.HEATING_CONTROLLER, has_data=True)},
            raw_registers={},
            placeholder_registers=set(),
        )
        c._ebusd_connected = True
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value=None))
        c.ebus = mock_ebus
        c.async_request_refresh = AsyncMock()

        assert await c.async_set_mode_override(55, 45, keep_alive=False) is True
        assert mock_ebus.write_register.await_args.args[0] == "bai0"


# Intent: a failed write in a batch stops the sequence and does not request a refresh.
# Why: prevents partial writes from triggering a misleading refresh.
async def test_async_write_registers_stops_on_failure_no_refresh() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = _make_graph()
        c._ebusd_connected = True

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(
            side_effect=[
                WriteResult(success=True, verified_value=None),
                WriteResult(success=False, error_message="boom"),
            ]
        )
        c.ebus = mock_ebus
        c.async_request_refresh = MagicMock()

        ok = await c.async_write_registers([("ctlv2", "A", "1"), ("ctlv2", "B", "2")])

        assert ok is False
        assert c.async_request_refresh.call_count == 0


# Intent: fallback-read registers are merged into graph raw registers and node register lists.
# Why: protects entity generation that depends on graph membership after fallback reads.
async def test_fallback_read_adds_new_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="45.0")

        c.ebus = mock_ebus
        c._graph = _make_graph()
        c._last_find_keys = {
            "hmu.RunDataStatuscode",
            "hmu.OutsideTemp",
            "ctlv2.Z1OpMode",
            "ctlv2.Z1DayTemp",
        }
        c.entities = c.entity_factory.generate(c._graph)

        before = len(c.registers)
        await c._fallback_read()

        assert len(c.registers) >= before
        for key, register in c.registers.items():
            if register.has_data and register.circuit in c._graph.nodes:
                assert key in c._graph.raw_registers
                assert key in c._graph.nodes[register.circuit].registers


# Intent: fallback read is a no-op when ebus is None.
# Why: protects pre-connect and retry paths from an AttributeError.
async def test_fallback_read_no_ebus_skips() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = None
        await c._fallback_read()


# Intent: set mode override writes the BAI payload, stores it, and schedules a keep-alive that clear cancels.
# Why: protects the boiler override payload format and its keep-alive lifecycle.
async def test_set_mode_override_writes_payload_and_schedules_keep_alive() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={"bai": DeviceNode("bai", DeviceType.HEATING_CONTROLLER, has_data=True)},
            raw_registers={},
            placeholder_registers=set(),
        )
        c._ebusd_connected = True
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value="done"))
        c.ebus = mock_ebus

        c.async_request_refresh = AsyncMock()
        c._cancel_set_mode_override = MagicMock()

        assert await c.async_set_mode_override(55, 45) is True
        mock_ebus.write_register.assert_awaited_once_with(
            "bai", "SetModeOverride", "0;55;45;-;-;0;0;0;-;0;0;0", strict_verify=False
        )
        assert c._set_mode_override_payload == "0;55;45;-;-;0;0;0;-;0;0;0"
        assert c._cancel_set_mode_override is not None

        c.async_clear_mode_override()
        assert c._set_mode_override_payload is None


# Intent: known placeholder registers are explicitly polled and become available when the read succeeds.
# Why: protects placeholders absent from find output from never receiving data.
async def test_fallback_read_polls_known_placeholders() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="25")
        c.ebus = mock_ebus
        c._graph = DeviceGraph(
            nodes=_make_graph().nodes,
            raw_registers=_make_graph().raw_registers,
            placeholder_registers={"hmu.YieldHc"},
        )
        c._last_find_keys = set(c._graph.raw_registers) | {"hmu.YieldHc"}

        await c._fallback_read(include_placeholders=True)

        mock_ebus.read_register.assert_any_await("hmu", "YieldHc", raise_transport_errors=True)
        assert c.registers["hmu.YieldHc"].has_data is True


# aroTHERM Plus exposes energy registers under basv3/ctlv3 while REGISTER_MAP
# stores them under ctlv2/hmu; the fallback read must read the discovered
# circuit (mirrors get_meta's aliasing). Regression for #53/#76/#77.
# Intent: placeholder energy registers are read from the discovered basv3 circuit instead of the legacy ctlv2 alias.
# Why: regression for #53/#76/#77 where aroTHERM Plus registers must be polled on basv3.
async def test_fallback_read_aliases_discovered_placeholder_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="42")
        c.ebus = mock_ebus
        basv3_node = DeviceNode(
            circuit="basv3",
            device_type=DeviceType.HEATING_CONTROLLER,
            registers=[],
            has_data=True,
            scan_type="BASV3",
        )
        c._graph = DeviceGraph(
            nodes={"basv3": basv3_node},
            raw_registers={},
            placeholder_registers={
                "basv3.PrEnergySumHc",
                "basv3.StatElectricEnergySum",
            },
        )
        c._last_find_keys = set()

        await c._fallback_read(include_placeholders=True)

        mock_ebus.read_register.assert_any_await("basv3", "PrEnergySumHc", raise_transport_errors=True)
        mock_ebus.read_register.assert_any_await("basv3", "StatElectricEnergySum", raise_transport_errors=True)
        assert c.registers["basv3.PrEnergySumHc"].has_data is True
        assert c.registers["basv3.StatElectricEnergySum"].has_data is True
        assert "basv3.PrEnergySumHc" in c._graph.raw_registers
        assert "basv3.PrEnergySumHc" in basv3_node.registers


# Intent: REGISTER_MAP fallback reads use the discovered circuit rather than the map key circuit.
# Why: protects CTLV3 hardware whose map key still says ctlv2.
async def test_fallback_read_map_reads_discovered_circuit() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="42")
        c.ebus = mock_ebus
        ctlv3_node = DeviceNode(
            circuit="ctlv3",
            device_type=DeviceType.HEATING_CONTROLLER,
            registers=[],
            has_data=True,
            scan_type="CTLV3",
        )
        c._graph = DeviceGraph(
            nodes={"ctlv3": ctlv3_node},
            raw_registers={},
            placeholder_registers={"ctlv3.PrEnergySumHwc"},
        )
        c._last_find_keys = set()

        await c._fallback_read()

        mock_ebus.read_register.assert_any_await("ctlv3", "PrEnergySumHwc", raise_transport_errors=True)
        calls = {args[0] for args, _ in mock_ebus.read_register.call_args_list}
        assert ("ctlv2", "PrEnergySumHwc") not in calls
        assert c.registers["ctlv3.PrEnergySumHwc"].has_data is True


# Intent: use graph-resolved ownership instead of falling back to a legacy circuit.
# Why: prevents duplicate register names across ctlv3/basv3 from being polled through a legacy alias.
async def test_fallback_read_uses_graph_owner_for_duplicate_register_names() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="42")
        c.ebus = mock_ebus
        c._graph = DeviceGraph(
            nodes={
                "ctlv3": DeviceNode("ctlv3", DeviceType.HEATING_CONTROLLER, has_data=True),
                "basv3": DeviceNode("basv3", DeviceType.HEATING_CONTROLLER, has_data=True),
            },
            raw_registers={"ctlv3.PrEnergySumHwc": "-", "basv3.PrEnergySumHwc": "-"},
            placeholder_registers=set(),
        )
        c._last_find_keys = set()

        await c._fallback_read()

        calls = {(args[0], args[1]) for args, _ in mock_ebus.read_register.call_args_list}
        assert ("ctlv2", "PrEnergySumHwc") not in calls
        assert ("ctlv3", "PrEnergySumHwc") not in calls


# Intent: do not poll a legacy alias when discovered owners are ambiguous.
# Why: prevents a legacy alias read when two discovered controllers could own the register.
async def test_fallback_read_skips_ambiguous_discovered_owners() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="42")
        c.ebus = mock_ebus
        c._graph = DeviceGraph(
            nodes={
                "ctlv3": DeviceNode("ctlv3", DeviceType.HEATING_CONTROLLER, has_data=True),
                "basv3": DeviceNode("basv3", DeviceType.HEATING_CONTROLLER, has_data=True),
            },
            raw_registers={"ctlv3.PrEnergySumHwc": "-", "basv3.PrEnergySumHwc": "-"},
            placeholder_registers=set(),
        )

        await c._fallback_read()

        calls = {(args[0], args[1]) for args, _ in mock_ebus.read_register.call_args_list}
        assert ("ctlv2", "PrEnergySumHwc") not in calls


# Intent: fallback read skips map registers whose logical owner is absent from the graph.
# Why: prevents reading alias registers that have no discovered hardware.
async def test_fallback_read_skips_missing_logical_owner() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="42")
        c.ebus = mock_ebus
        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())

        await c._fallback_read()

        calls = {(args[0], args[1]) for args, _ in mock_ebus.read_register.call_args_list}
        assert ("hmu", "OutsideTemp") not in calls


# Intent: fallback transport failures escape to the coordinator retry handler.
# Why: EOF/timeouts are not ordinary unsupported-register or no-data results.
async def test_fallback_read_propagates_transport_failure() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(side_effect=ConnectionError("connection closed"))
        c.ebus = mock_ebus
        c._graph = DeviceGraph(
            nodes={"hmu": DeviceNode("hmu", DeviceType.HEAT_PUMP, has_data=True)},
            raw_registers={},
            placeholder_registers=set(),
        )
        c._last_find_keys = set()
        original_map = COORDINATOR.REGISTER_MAP
        COORDINATOR.REGISTER_MAP = {"hmu.YieldHc": MAPPING.RegisterMeta(enabled=True)}
        try:
            with pytest.raises(ConnectionError, match="connection closed"):
                await c._fallback_read()
        finally:
            COORDINATOR.REGISTER_MAP = original_map

        mock_ebus.read_register.assert_awaited_once_with("hmu", "YieldHc", raise_transport_errors=True)


# Intent: initial graph application retains the repair when a fallback probe loses TCP.
# Why: a mapped read failure after successful find is still a transport failure, not missing register data.
async def test_initial_fallback_transport_failure_keeps_repair_active() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True

        # Intent: model a transport failure that closes the live ebusd session.
        # Why: initial discovery must not dismiss the repair based on an earlier successful find.
        async def fail_read(circuit: str, name: str, raise_transport_errors: bool = False) -> None:
            c.ebus.is_connected = False
            raise ConnectionError(f"read failed for {circuit}.{name}")

        c.ebus.read_register = AsyncMock(side_effect=fail_read)
        repairs_module.async_create_ebusd_unreachable.reset_mock()
        repairs_module.async_dismiss_ebusd_unreachable.reset_mock()
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/arotherm_ecotec_discovery.yaml", after=True)
        )

        await c._apply_discovery_graph(graph, "initial")

        assert c._ebusd_connected is False
        assert c._started is False
        assert c._ebusd_repair_pending is True
        repairs_module.async_create_ebusd_unreachable.assert_awaited_once_with(c.hass)
        repairs_module.async_dismiss_ebusd_unreachable.assert_not_awaited()


# Intent: initial graph application preserves a live value when the same find batch has a stale no-data row.
# Why: the live value must win over its duplicate placeholder during cache pruning and entity seeding.
async def test_initial_discovery_preserves_live_value_with_duplicate_no_data() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator._cache_seeded = True
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            ["hmu OutsideTemp = 20.75", "hmu OutsideTemp = no data stored"]
        )

        await coordinator._apply_discovery_graph(graph, "initial")

        register = coordinator.registers.get("hmu.OutsideTemp")
        entity = next(entity for entity in coordinator.entities if entity.name == "OutsideTemp")
        assert "hmu.OutsideTemp" in graph.raw_registers
        assert "hmu.OutsideTemp" in graph.placeholder_registers
        assert register is not None
        assert register.value["value"] == "20.75"
        assert entity.raw_value == "20.75"
        coordinator.ebus.read_register.reset_mock()
        await coordinator._fallback_read(include_placeholders=True)
        read_names = {call.args[1] for call in coordinator.ebus.read_register.await_args_list}
        assert "OutsideTemp" not in read_names


# Intent: fallback paths never actively read the unverified Hc1/Hc2 B524 state registers.
# Why: map-driven and placeholder reads otherwise recreate the invalid-position poll churn.
async def test_fallback_read_skips_unverified_b524_hc_state_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = DISCOVERY.DiscoveryService.build_device_graph(
            load_find_lines("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml", after=True)
        )
        controller = graph.heating_controller_result().node
        assert controller is not None
        assert controller.scan_type == "CTLV3"
        assert any(key.endswith(tuple(HC_STATE_REGISTER_NAMES)) for key in graph.placeholder_registers)

        coordinator = VaillantCoordinator(_hass(tmpdir), _entry())
        coordinator.ebus = MagicMock(spec=EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.read_register = AsyncMock(return_value="ERR: invalid position")
        coordinator._graph = graph
        coordinator._last_find_keys = set()

        await coordinator._fallback_read(include_placeholders=True)

        calls = {(args[0], args[1]) for args, _ in coordinator.ebus.read_register.call_args_list}
        assert not any(name in HC_STATE_REGISTER_NAMES for _, name in calls)


# Intent: a singleton node of the wrong device role does not satisfy a heat-pump register read.
# Why: protects against misattributing heat-pump registers when only a controller is discovered.
async def test_fallback_read_rejects_singleton_wrong_role_candidate() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="42")
        c.ebus = mock_ebus
        c._graph = DeviceGraph(
            nodes={"ctlv3": DeviceNode("ctlv3", DeviceType.HEATING_CONTROLLER, has_data=True)},
            raw_registers={"ctlv3.RunDataStatuscode": "-"},
            placeholder_registers=set(),
        )

        await c._fallback_read()

        assert ("ctlv3", "RunDataStatuscode") not in {
            (args[0], args[1]) for args, _ in mock_ebus.read_register.call_args_list
        }


# Intent: keep parsed multi-field names out of coordinator register polling.
# Why: field suffixes are parsed sub-fields, not independent ebusd registers.
async def test_fallback_read_skips_field_mapping_keys() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="42")
        c.ebus = mock_ebus
        c._graph = DeviceGraph(
            nodes={"hmu": DeviceNode("hmu", DeviceType.HEAT_PUMP, has_data=True)},
            raw_registers={},
            placeholder_registers=set(),
        )
        c._last_find_keys = set()

        original_map = COORDINATOR.REGISTER_MAP
        COORDINATOR.REGISTER_MAP = {
            "hmu.Status01": MAPPING.REGISTER_MAP["hmu.Status01"],
            "hmu.Status01.temp": MAPPING.RegisterMeta(enabled=True),
        }
        try:
            await c._fallback_read()
        finally:
            COORDINATOR.REGISTER_MAP = original_map

        calls = {(args[0], args[1]) for args, _ in mock_ebus.read_register.call_args_list}
        assert ("hmu", "Status01.temp") not in calls


# The Yield day/month variants from #77 must be mapped so they get entities
# and placeholder retries.
# Intent: yield day/month register variants are present in REGISTER_MAP with energy metadata.
# Why: regression for #77 so these yield variants get entities and placeholder retries.
def test_fallback_read_yield_day_month_variants_mapped() -> None:
    from vaillant_ebus.backend.mapping import REGISTER_MAP

    for key in ("hmu.YieldHcMonth", "hmu.YieldHwcDay", "hmu.YieldHwcMonth"):
        assert key in REGISTER_MAP
        meta = REGISTER_MAP[key]
        assert meta.enabled is True
        assert meta.device_class == "energy"
        assert meta.unit == "kWh"


# Intent: device info for hmu uses the graph scan type to produce a descriptive name.
# Why: protects user-facing device naming derived from discovery.
async def test_get_device_info_uses_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        graph = _make_graph()
        c._graph = graph
        c.ebus = MagicMock()
        c.ebus.version = "23.2"

        info = c.get_device_info("hmu")
        assert info.get("name") == "Vaillant aroTHERM heat pump"


# Intent: prefer configured names without changing stable circuit identifiers.
# Why: prevents relabeling a circuit from changing its device registry identity.
async def test_get_device_info_prefers_circuit_names() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = _make_graph()
        c.ebus = MagicMock()
        c.ebus.version = "23.2"

        for circuit in ("ctlv0", "ctlv2", "ctlv9"):
            info = c.get_device_info(circuit)
            assert info.get("name") == "Vaillant sensoCOMFORT Control"
            assert info["identifiers"] == {("vaillant_ebus", circuit)}
        assert c.get_device_info("z1").get("name") == "Zone 1"
        assert c.get_device_info("hmu")["identifiers"] == {("vaillant_ebus", "hmu")}


# Intent: expose unclassified devices using their ebusd scan metadata.
# Why: unknown scan devices still get usable HA device entries instead of being dropped.
async def test_get_device_info_for_unknown_scan_type() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        graph = _make_graph()
        graph.nodes["xyz"] = DeviceNode(
            circuit="xyz",
            device_type=DeviceType.UNKNOWN,
            scan_type="XYZ01",
            scan_sw="1234",
            scan_hw="5678",
        )
        c._graph = graph
        c.ebus = MagicMock()
        c.ebus.version = "23.2"

        info = c.get_device_info("xyz")
        assert info["name"] == "Vaillant XYZ01"
        assert info["sw_version"] == "1234"
        assert info["hw_version"] == "5678"
        assert info["identifiers"] == {("vaillant_ebus", "xyz")}


# Intent: the entity factory generates entities from a discovered graph, including an hmu entity.
# Why: smoke test that discovery yields entities.
async def test_entities_generated_after_discovery() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        graph = _make_graph()
        c._graph = graph
        entities = c.entity_factory.generate(graph)
        assert len(entities) > 0
        assert any(e.circuit == "hmu" for e in entities)


# Intent: the heating circuit resolves to ctlv2 from the two-node graph.
# Why: protects controller circuit resolution used by climate entities.
async def test_heating_circuit_from_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        graph = _make_graph()
        c._graph = graph
        assert c.heating_circuit == "ctlv2"


# Intent: the heating circuit prefers the controller owning control registers over one with only flow/storage registers.
# Why: protects climate routing when both bai and ctlvN controllers are discovered.
async def test_heating_circuit_prefers_controller_with_control_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        graph = _make_graph()
        graph.nodes = {
            "bai": DeviceNode(
                circuit="bai",
                device_type=DeviceType.HEATING_CONTROLLER,
                registers=["bai.FlowTemp", "bai.StorageTemp"],
                has_data=True,
            ),
            "ctlv0": DeviceNode(
                circuit="ctlv0",
                device_type=DeviceType.HEATING_CONTROLLER,
                registers=["ctlv0.HwcTempDesired", "ctlv0.HwcOpMode"],
                has_data=True,
            ),
        }
        c._graph = graph
        assert c.heating_circuit == "ctlv0"


# Intent: with no graph at all the heating circuit remains unresolved.
# Why: pre-discovery routing must not fall back to the legacy ctlv2 default.
async def test_heating_circuit_fallback_no_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = None
        assert c.heating_circuit is None


# Intent: values-from-registers strips extra semicolon fields and exposes the primary value under .value.
# Why: protects sensor values from carrying multi-field tails.
async def test_values_from_registers_includes_suffix_stripped() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        c.registers["test.Example"] = EbusdRegister(
            circuit="test",
            name="Example",
            fields=["value"],
            value={"value": "22.50;ok"},
            has_data=True,
        )
        values = await c._async_values_from_registers()
        assert values["test.Example.value"] == "22.50"


# Intent: _register_values splits Status01 into value, temp, temp_1 and pumpstate fields.
# Why: protects multi-field Status01 sensor decoding.
async def test_register_values_splits_status01() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.registers["hmu.Status01"] = EbusdRegister(
            circuit="hmu",
            name="Status01",
            fields=["value"],
            value=_register_values("hmu.Status01", "39.5;40.5;-;-;-;off"),
            has_data=True,
        )
        values = await c._async_values_from_registers()
        assert values["hmu.Status01.value"] == "39.5;40.5;-;-;-;off"
        assert values["hmu.Status01.temp"] == "39.5"
        assert values["hmu.Status01.temp_1"] == "40.5"
        assert values["hmu.Status01.pumpstate"] == "off"


# Intent: the ebus property is None before any connection is set.
# Why: basic lifecycle guard for the not-yet-connected coordinator.
async def test_ebus_none_when_not_connected() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.ebus is None


# Intent: the ebus property can be assigned and cleared.
# Why: supports the dependency-injection lifecycle the coordinator relies on.
async def test_ebus_settable() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock = MagicMock(spec=EbusService)
        c.ebus = mock
        assert c.ebus is mock
        c.ebus = None
        assert c.ebus is None


# Intent: child device info resolves via_device_id from the device registry for a parented circuit.
# Why: protects HA device hierarchy linking child circuits to their parent device.
async def test_get_device_info_with_parent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        graph = _make_graph()
        c._graph = graph
        c.ebus = MagicMock()
        c.ebus.version = "23.2"

        device_registry = sys.modules["homeassistant.helpers.device_registry"]
        device_registry.async_get_device_id_by_identifier = MagicMock(return_value="parent-device-id")
        info = c.get_device_info("ctlv2")
        assert info.get("via_device_id") == "parent-device-id"
        assert "via_device" not in info


# Intent: get_device_info still returns hmu identifiers without a graph or ebus.
# Why: protects device registry creation during startup before discovery.
async def test_get_device_info_no_graph_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = None
        c.ebus = None

        info = c.get_device_info("hmu")
        assert "hmu" in str(info["identifiers"])


# Intent: a registry lookup failure omits via_device_id instead of raising.
# Why: protects device info generation when the parent device is not yet registered.
async def test_get_device_info_omits_parent_when_registry_lookup_fails() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = _make_graph()
        c.ebus = MagicMock()
        c.ebus.version = "23.2"
        device_registry = sys.modules["homeassistant.helpers.device_registry"]
        device_registry.async_get_device_id_by_identifier = MagicMock(side_effect=ValueError)

        info = c.get_device_info("ctlv2")

        assert "via_device_id" not in info


# Intent: setup calls connect, then find, then define, and produces entities.
# Why: protects the ordering needed for definitions to attach to discovered scan metadata.
async def test_orchestration_order() -> None:
    call_log: list[str] = []

    class LoggingEbus(MagicMock):
        pass

    mock_ebus = LoggingEbus(spec=EbusService)
    mock_ebus.is_connected = True
    mock_ebus.version = "23.2"

    async def connect() -> None:
        call_log.append("connect")

    mock_ebus.connect = connect

    async def define_register(defn) -> str:
        call_log.append("define")
        return "done"

    mock_ebus.define_register = define_register

    async def find_registers():
        call_log.append("find")
        return ["hmu Status01 = standby"]

    mock_ebus.find_registers = find_registers

    async def read_register(circuit, name) -> None:
        return None

    mock_ebus.read_register = read_register

    module = sys.modules["vaillant_ebus.coordinator"]
    orig_ebus = module.EbusService
    module.EbusService = MagicMock(return_value=mock_ebus)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            c = VaillantCoordinator(_hass(tmpdir), _entry())
            await c._ebusd_connect_and_discover()

            assert "connect" in call_log
            assert "define" in call_log
            assert "find" in call_log
            assert call_log.index("connect") < call_log.index("find") < call_log.index("define")
            assert len(c.entities) > 0
    finally:
        module.EbusService = orig_ebus


# Intent: a connect failure leaves _ebusd_connected False and cached entities intact.
# Why: protects the repair-issue startup path when ebusd is unreachable.
async def test_connect_failure_repair_issue() -> None:
    mock_ebus = MagicMock(spec=EbusService)
    mock_ebus.connect = AsyncMock(side_effect=ConnectionError("refused"))

    module = sys.modules["vaillant_ebus.coordinator"]
    orig_ebus = module.EbusService
    module.EbusService = MagicMock(return_value=mock_ebus)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            c = VaillantCoordinator(_hass(tmpdir), _entry())
            entities_before = len(c.entities)
            await c._ebusd_connect_and_discover()
            assert c._ebusd_connected is False
            assert len(c.entities) >= entities_before
    finally:
        module.EbusService = orig_ebus


# Intent: a full connect/discover against a fake ebusd regenerates entities via the factory and stores the graph.
# Why: fixture-driven end-to-end discovery path.
async def test_entities_regenerated_with_fresh_graph() -> None:
    async with FakeEbusdServer("arotherm_find.txt") as _:
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.version = "23.2"
        mock_ebus.connect = AsyncMock()

        async def dfn(d) -> str:
            return "defined"

        mock_ebus.define_register = dfn

        find_lines = load_find_lines("arotherm_find.txt")

        async def find_regs():
            return find_lines

        mock_ebus.find_registers = find_regs

        async def read_reg(circuit, name) -> None:
            return None

        mock_ebus.read_register = read_reg

        mock_factory = MagicMock()
        mock_factory.generate = MagicMock(return_value=[MagicMock() for _ in range(5)])

        module = sys.modules["vaillant_ebus.coordinator"]
        orig_ebus = module.EbusService
        module.EbusService = MagicMock(return_value=mock_ebus)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                c = VaillantCoordinator(_hass(tmpdir), _entry())
                c.entity_factory = mock_factory
                await c._ebusd_connect_and_discover()

                mock_factory.generate.assert_called()
                assert len(c.entities) == 5
                assert c._graph is not None
        finally:
            module.EbusService = orig_ebus


# Intent: auto-enable integration-disabled entities but respect user choice.
# Why: protects user-disabled and other-entry entities from being re-enabled.
async def test_enable_registry_entities_respects_user_choice() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)

        class _Entry:
            disabled_by = "integration"

            def __init__(self, uid: str, config_entry_id: str, disabled_by: str | None = "integration") -> None:
                self.unique_id = uid
                self.config_entry_id = config_entry_id
                self.disabled_by = disabled_by

        updated: list[str] = []
        registry = MagicMock()
        registry.entities = {
            "sensor.power": _Entry("ebusd_hmu_powerconsumptionhmu", "entry-1", "integration"),
            "sensor.user_disabled": _Entry("ebusd_hmu_currentconsumedpower", "entry-1", "user"),
            "sensor.enabled": _Entry("ebusd_hmu_currentyieldpower", "entry-1", None),
            "sensor.other_entry": _Entry("ebusd_hmu_powerconsumptionhmu", "entry-2", "integration"),
        }
        registry.async_update_entity = MagicMock(side_effect=lambda entity_id, **kwargs: updated.append(entity_id))
        from homeassistant.helpers import entity_registry

        entity_registry.async_get = MagicMock(return_value=registry)

        entry = _entry()
        entry.entry_id = "entry-1"
        c = VaillantCoordinator(hass, entry)
        c.ebus = MagicMock()
        c.ebus.is_connected = True
        result = await c._enable_registry_entities(["hmu.PowerConsumptionHmu"])
        assert result == ["sensor.power"]
        assert updated == ["sensor.power"]


# Intent: multi-field registers must auto-enable their per-field entities too;
# those unique ids carry a _{field} suffix matching EntityDescription.unique_id.
# Why: protects multi-field registers from only enabling the base entity.
async def test_enable_registry_entities_expands_multi_field_uids() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)

        class _Entry:
            def __init__(self, uid: str, config_entry_id: str, disabled_by: str | None = "integration") -> None:
                self.unique_id = uid
                self.config_entry_id = config_entry_id
                self.disabled_by = disabled_by

        updated: list[str] = []
        registry = MagicMock()
        registry.entities = {
            "sensor.base": _Entry("ebusd_hmu_compressorhc", "entry-1", "integration"),
            "sensor.runtime": _Entry("ebusd_hmu_compressorhc_runtime", "entry-1", "integration"),
            "sensor.cycles": _Entry("ebusd_hmu_compressorhc_cycles", "entry-1", "integration"),
        }
        registry.async_update_entity = MagicMock(side_effect=lambda entity_id, **kwargs: updated.append(entity_id))
        from homeassistant.helpers import entity_registry

        entity_registry.async_get = MagicMock(return_value=registry)

        entry = _entry()
        entry.entry_id = "entry-1"
        c = VaillantCoordinator(hass, entry)
        c.ebus = MagicMock()
        c.ebus.is_connected = True
        result = await c._enable_registry_entities(["hmu.CompressorHc"])
        assert sorted(result) == ["sensor.base", "sensor.cycles", "sensor.runtime"]


# Intent: the no-data disable pass must not undo an entity the user enabled
# manually (issue #152). A registry entry with disabled_by is None for a
# non-default (enabled_by_default=False) description can only be enabled
# because the user switched it on, so it must survive a temporary no-data
# registration. Default-enabled and user-disabled entries keep their behavior.
# Why: a periodic no-data pass used to re-disable optional entities (e.g.
# SourceTempInput, cooling/DHW counters) the user had explicitly enabled,
# flipping them back to disabled on the next rediscovery.
async def test_disable_no_data_preserves_user_enabled_optional_entities() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)

        class _Description:
            def __init__(self, uid: str, enabled_by_default: bool, raw_value: str | None = None) -> None:
                self.unique_id = uid
                self.enabled_by_default = enabled_by_default
                self.raw_value = raw_value

        class _Entry:
            def __init__(self, uid: str, config_entry_id: str, disabled_by: str | None) -> None:
                self.unique_id = uid
                self.config_entry_id = config_entry_id
                self.disabled_by = disabled_by

        updated: list[str] = []
        registry = MagicMock()
        registry.entities = {
            # Non-default description, enabled by the user -> must survive.
            "sensor.user_enabled_optional": _Entry("ebusd_hmu_sourcetempinput", "entry-1", None),
            # Default-enabled description with no data -> integration disables it.
            "sensor.default_no_data": _Entry("ebusd_hmu_outside_temp", "entry-1", None),
            # User disabled -> never touched.
            "sensor.user_disabled": _Entry("ebusd_ctl_v2_z1roomhumidity", "entry-1", "user"),
            # Another config entry -> never touched.
            "sensor.other_entry": _Entry("ebusd_hmu_sourcetempinput", "entry-2", None),
        }
        registry.async_update_entity = MagicMock(side_effect=lambda entity_id, **kwargs: updated.append(entity_id))
        from homeassistant.helpers import entity_registry

        entity_registry.async_get = MagicMock(return_value=registry)

        entry = _entry()
        entry.entry_id = "entry-1"
        c = VaillantCoordinator(hass, entry)
        c._disable_no_data_registry_entities(
            [
                _Description("ebusd_hmu_sourcetempinput", enabled_by_default=False),
                _Description("ebusd_hmu_outside_temp", enabled_by_default=True),
            ]
        )
        # Only the default-enabled no-data entity is disabled.
        assert updated == ["sensor.default_no_data"]


# Intent: the shared find-line parser must keep no-data sentinels out of the
# polled register set — including unknown/unavailable/bare-empty values that
# the old hand-rolled poll filter let through.
# Why: prevents sentinel values from surfacing as normal sensors in both discovery and polling.
async def test_poll_and_discovery_filter_sentinel_find_values() -> None:
    lines = [
        "ctlv2 Z1DayTemp = 21.5",
        "ctlv2 SomeStatus = unknown",
        "hmu CurrentYieldPower = unavailable",
        "hmu FlowTemp = -",
        "hmu CopCooling = no data stored",
        "basv HcStorageTemp =  (empty for f115b5240602000000a000)",
    ]
    mock_ebus = MagicMock(spec=EbusService)
    mock_ebus.is_connected = True
    mock_ebus.version = "23.2"
    mock_ebus.connect = AsyncMock()

    async def dfn(d) -> str:
        return "defined"

    mock_ebus.define_register = dfn

    async def find_regs():
        return lines

    mock_ebus.find_registers = find_regs

    async def read_reg(circuit, name) -> None:
        return None

    mock_ebus.read_register = read_reg

    module = sys.modules["vaillant_ebus.coordinator"]
    orig_ebus = module.EbusService
    module.EbusService = MagicMock(return_value=mock_ebus)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            c = VaillantCoordinator(_hass(tmpdir), _entry())
            c.entity_factory = MagicMock()
            c.entity_factory.generate.return_value = []
            await c._ebusd_connect_and_discover()
            # Discovery side: only live values reach the register set.
            assert "ctlv2.Z1DayTemp" in c.registers
            for absent in (
                "ctlv2.SomeStatus",
                "hmu.CurrentYieldPower",
                "hmu.FlowTemp",
                "hmu.CopCooling",
                "basv.HcStorageTemp",
            ):
                assert absent not in c.registers, f"{absent} leaked via discovery"

            # Poll side: same filter applies through the shared parser.
            await c._async_update_data()
            for absent in (
                "ctlv2.SomeStatus",
                "hmu.CurrentYieldPower",
                "hmu.FlowTemp",
                "hmu.CopCooling",
                "basv.HcStorageTemp",
            ):
                assert absent not in c.registers, f"{absent} leaked via poll"
    finally:
        module.EbusService = orig_ebus


# Intent: case-variant cache keys (HwcSfMode vs HwcSFMode) must not double-register.
# Why: keeps entity unique_ids unique so Home Assistant does not reject duplicate registrations.
async def test_coordinator_seed_dedups_case_variants() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "vaillant_ebus" / "register_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache = {
            "ctlv2.HwcSfMode.value": "auto",
            "ctlv2.HwcSFMode.value": "auto",
            "ctlv2.HwcStorageTemp.value": "40.5",
        }
        cache_path.write_text(json.dumps(cache))

        hass = _hass(tmpdir)
        hass.config.path.return_value = str(cache_path)
        coordinator = VaillantCoordinator(hass, _entry())
        await coordinator._async_seed_entities_from_cache()

        sfmode = [e for e in coordinator.entities if "sfmode" in e.unique_id]
        assert len(sfmode) == 1, f"expected one HwcSfMode entity, got {len(sfmode)}"
        uids = [e.unique_id for e in coordinator.entities]
        assert len(uids) == len(set(uids))


# Intent: active zones are derived from the discovery graph, mapping each zone
# to the circuit hosting its registers for per-zone climate entities.
# Why: protects per-zone climate entity creation from the discovery graph.
async def test_zone_circuits_two_zone_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={
                "ctlv2": DeviceNode(
                    circuit="ctlv2",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=[],
                    has_data=True,
                    zone_circuits=["z1", "z2"],
                ),
                "z1": DeviceNode(
                    circuit="z1",
                    device_type=DeviceType.ZONE,
                    registers=["ctlv2.Z1RoomTemp", "ctlv2.Z1DayTemp"],
                    has_data=True,
                    parent="ctlv2",
                ),
                "z2": DeviceNode(
                    circuit="z2",
                    device_type=DeviceType.ZONE,
                    registers=["ctlv2.Z2RoomTemp", "ctlv2.Z2DayTemp"],
                    has_data=True,
                    parent="ctlv2",
                ),
            },
            raw_registers={
                "ctlv2.Z1RoomTemp": "21.5",
                "ctlv2.Z2RoomTemp": "20.5",
            },
            placeholder_registers=set(),
        )
        assert c.zone_circuits() == {"z1": "ctlv2", "z2": "ctlv2"}


# Intent: zones whose registers were found but carry no data are not active,
# so a single-zone system keeps exactly one climate entity.
# Why: prevents an inactive second zone from adding a climate entity.
async def test_zone_circuits_skips_no_data_zone() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={
                "ctlv2": DeviceNode(
                    circuit="ctlv2",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=[],
                    has_data=True,
                    zone_circuits=["z1", "z2"],
                ),
                "z1": DeviceNode(
                    circuit="z1",
                    device_type=DeviceType.ZONE,
                    registers=["ctlv2.Z1RoomTemp"],
                    has_data=True,
                ),
                "z2": DeviceNode(
                    circuit="z2",
                    device_type=DeviceType.ZONE,
                    registers=["ctlv2.Z2RoomTemp"],
                    has_data=False,
                ),
            },
            raw_registers={"ctlv2.Z1RoomTemp": "21.5"},
            placeholder_registers={"ctlv2.Z2RoomTemp"},
        )
        assert c.zone_circuits() == {"z1": "ctlv2"}


# Intent: an empty graph yields no zones; the climate platform falls back to z1.
# Why: protects default single-zone behavior before discovery.
async def test_zone_circuits_empty_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.zone_circuits() == {}


# Intent: feature gating treats live values and no-data placeholders alike.
# Why: ensures entities are created for known-but-idle zone features.
async def test_has_zone_register_checks_raw_and_placeholder() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={},
            raw_registers={"ctlv2.Z2CoolingTemp": "26"},
            placeholder_registers={"ctlv2.Z2QuickVetoDuration"},
        )
        c._last_find_keys = {"ctlv2.Z2CoolingTemp"}
        assert c.has_zone_register("ctlv2", "z2", "CoolingTemp") is True
        assert c.has_zone_register("ctlv2", "z2", "QuickVetoDuration") is True
        assert c.has_zone_register("ctlv2", "z2", "RoomTemp") is False
        assert c.has_zone_register("ctlv2", "z1", "CoolingTemp") is False


# Intent: before discovery populates the find set, absence is not proof of
# hardware absence, so the register is assumed present (pre-per-zone behavior).
# Why: prevents pre-discovery gating from hiding entities until absence is proven.
async def test_has_zone_register_assumes_present_until_discovery() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.has_zone_register("ctlv2", "z1", "CoolingTemp") is True
        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        assert c.has_zone_register("ctlv2", "z1", "CoolingTemp") is True
        c._last_find_keys = {"ctlv2.Z1RoomTemp"}
        assert c.has_zone_register("ctlv2", "z1", "CoolingTemp") is False


# Intent: write paths can distinguish unknown startup capability from an absent discovered register.
# Why: safety-critical writes must wait for discovery instead of treating pre-discovery UI optimism as support.
async def test_zone_register_discovery_status_distinguishes_unknown_and_absent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.zone_register_discovery_status("ctlv2", "z1", "QuickVetoDuration") is None
        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        assert c.zone_register_discovery_status("ctlv2", "z1", "QuickVetoDuration") is None
        c._last_find_keys = {"ctlv2.Z1RoomTemp"}
        assert c.zone_register_discovery_status("ctlv2", "z1", "QuickVetoDuration") is False


# Intent: an all-placeholder find response still proves supported register presence.
# Why: no data stored means idle-but-supported hardware, not an incomplete discovery or absent feature.
async def test_zone_register_discovery_status_accepts_placeholder_only_find() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(nodes={}, raw_registers={}, placeholder_registers={"ctlv2.Z1QuickVetoDuration"})
        c._refresh_find_keys()

        assert c.zone_register_discovery_status("ctlv2", "z1", "QuickVetoDuration") is True


# Intent: platforms can add entities once a discovery graph has been applied.
# Why: protects the platform re-add hook used to add entities after discovery.
async def test_post_discovery_callbacks_fire_on_apply() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        fired: list[str] = []
        c.register_post_discovery_callback(lambda: fired.append("initial"))
        c.register_post_discovery_callback(lambda: fired.append("delayed"))

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value=None)
        c.ebus = mock_ebus
        await c._apply_discovery_graph(_make_graph(), "initial")
        await c._apply_discovery_graph(
            DeviceGraph(
                nodes={
                    "v32": DeviceNode(
                        circuit="v32",
                        device_type=DeviceType.VENTILATION,
                        registers=["v32.SupplyAirTemp"],
                        has_data=True,
                    )
                },
                raw_registers={"v32.SupplyAirTemp": "20.75"},
                placeholder_registers=set(),
            ),
            "delayed",
        )
        assert fired == ["initial", "delayed", "initial", "delayed"]


# Intent: a ghost zone (mapping "none", no live core registers) must not get a
# climate entity, even though ebusd reports its registers as real values.
# Why: prevents a phantom climate entity for a zone that is not physically present.
async def test_zone_circuits_skips_ghost_zone() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={
                "ctlv2": DeviceNode(
                    circuit="ctlv2",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=[],
                    has_data=True,
                    zone_circuits=["z1", "z2"],
                ),
                "z1": DeviceNode(
                    circuit="z1",
                    device_type=DeviceType.ZONE,
                    registers=["ctlv2.Z1RoomTemp"],
                    has_data=True,
                ),
                "z2": DeviceNode(
                    circuit="z2",
                    device_type=DeviceType.ZONE,
                    registers=["ctlv2.Z2RoomZoneMapping", "ctlv2.Z2RoomTemp"],
                    has_data=True,
                ),
            },
            raw_registers={
                "ctlv2.Z1RoomTemp": "21.5",
                "ctlv2.Z2RoomZoneMapping": "none",
            },
            placeholder_registers={"ctlv2.Z2RoomTemp", "ctlv2.Z2DayTemp", "ctlv2.Z2OpMode"},
        )
        assert c.zone_circuits() == {"z1": "ctlv2"}


# Intent: a real but idle zone (real mapping, no live data yet) still gets a
# climate entity; it simply reports unavailable values while inactive.
# Why: protects a legitimate idle zone from being dropped while it reports unavailable.
async def test_zone_circuits_keeps_real_idle_zone() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DeviceGraph(
            nodes={
                "ctlv2": DeviceNode(
                    circuit="ctlv2",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=[],
                    has_data=True,
                    zone_circuits=["z1", "z2"],
                ),
                "z1": DeviceNode(
                    circuit="z1",
                    device_type=DeviceType.ZONE,
                    registers=["ctlv2.Z1RoomTemp"],
                    has_data=True,
                ),
                "z2": DeviceNode(
                    circuit="z2",
                    device_type=DeviceType.ZONE,
                    registers=["ctlv2.Z2RoomZoneMapping", "ctlv2.Z2RoomTemp"],
                    has_data=False,
                ),
            },
            raw_registers={
                "ctlv2.Z1RoomTemp": "21.5",
                "ctlv2.Z2RoomZoneMapping": "VR91_1",
            },
            placeholder_registers={"ctlv2.Z2RoomTemp", "ctlv2.Z2DayTemp", "ctlv2.Z2OpMode"},
        )
        assert c.zone_circuits() == {"z1": "ctlv2", "z2": "ctlv2"}


# Intent: the logical DHW device is named after the hardware that owns it.
# Why: a heat pump has a hot-water cylinder, not a boiler; a boiler-only bus
# keeps the historical name so existing installs stay stable.
async def test_dhw_device_name_is_hardware_aware() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        c._graph = DISCOVERY.DiscoveryService.build_device_graph(
            ["scan.08 = Vaillant;HMU00;0522;5103", "hmu FlowTemp = 30", "ctlv2 HwcOpMode = auto"]
        )
        assert c._dhw_device_name() == "Domestic Hot Water"

        c._graph = DISCOVERY.DiscoveryService.build_device_graph(
            ["scan.08 = Vaillant;BAI00;0107;7503", "bai FlowTemp = 30", "ctlv2 HwcOpMode = auto"]
        )
        assert c._dhw_device_name() == "Boiler (DHW)"

        c._graph = None
        assert c._dhw_device_name() == "Boiler (DHW)"


# Intent: has_discovered_circuit reflects the current graph and a cleared graph.
# Why: HA device removal must only be allowed for circuits no longer discovered.
async def test_has_discovered_circuit_matches_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = DISCOVERY.DiscoveryService.build_device_graph(["ctlv2 HwcOpMode = auto"])

        assert c.has_discovered_circuit("ctlv2")
        assert not c.has_discovered_circuit("bai")

        c._graph = None
        assert not c.has_discovered_circuit("ctlv2")
