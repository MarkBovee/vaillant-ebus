"""Unit tests for VaillantCoordinator — service orchestration."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.fake_ebusd import FakeEbusdServer, load_find_lines

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"
BACKEND_PATH = COMPONENT_PATH / "backend"

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
    def __init__(self, hass, logger, **kwargs) -> None:  # noqa: ARG002
        self.hass = hass
        self.name = kwargs.get("name", "")
        self.update_interval = kwargs.get("update_interval")
        self.last_update_success = True
        self.listeners: list = []

    def async_update_listeners(self) -> None:
        pass

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
    "DEFAULT_EBUSD_POLL_INTERVAL": 60,
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
    h.config.path.return_value = str(Path(cache_dir) / "vaillant_ebus" / "register_cache.json")
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


# Intent: boiler (bai) and solar (sc) circuits get descriptive device names.
# Why: guards against raw circuit codes leaking into the Home Assistant UI.
async def test_device_names_for_bai_and_sc_are_descriptive() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.get_device_info("bai")["name"] == "Vaillant boiler controller"
        assert c.get_device_info("sc")["name"] == "Vaillant solar controller"


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


# Intent: recover Z2 entities from cache before ebusd completes live discovery.
# Why: prevents a second heating zone from disappearing from the UI after a restart.
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
            "Z2DayTemp",
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


# Intent: heat-pump circuit resolves from the graph; defaults to hmu without a heat pump node.
# Why: protects heat-pump register resolution before and after discovery.
async def test_heat_pump_circuit_resolves_from_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.heat_pump_circuit == "hmu"
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
        assert len(hmux0) == 22
        assert all(",hmu," not in definition for definition in hmux0)
        assert any(",hmux0,RunDataReturnTemp," in definition for definition in hmux0)
        assert any(",hmux0,YieldHc," in definition for definition in hmux0)
        assert any(",hmux0,CopHwcMonth," in definition for definition in hmux0)
        assert any(",hmux0,HcElecConsDay," in definition for definition in hmux0)
        assert any(",hmux0,HwcElecConsTotal," in definition for definition in hmux0)
        # Confirmed 0303/0504 telemetry (upstream #249 / #522).
        assert any(",hmux0,Status00," in definition for definition in definitions)
        assert any(",hmux0,RunDataElPowerConsumption," in definition for definition in definitions)


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
        assert c.heat_pump_circuit == "hmu"


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
        assert ",08,B509,f203," in heating
        assert ",08,B509,f303," in hwc
        assert heating.endswith("value,,onoff,,,")
        assert hwc.endswith("value,,onoff,,,")
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
        assert len(hmux0_defs) == 22
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
        assert len(hmux0_definitions) == 22
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
        assert len([definition for definition in definitions if ",hmux0," in definition]) == 22
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
        assert len([definition for definition in definitions if ",hmux0," in definition]) == 22
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


# Intent: a transport reconnect clears runtime definitions and re-defines them on the next pass.
# Why: prevents using definitions tied to a dropped ebusd session and resets the energy poll.
async def test_transport_reconnect_invalidates_runtime_definitions() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._cache_seeded = c._ebusd_connected = True
        c.ebus = MagicMock(spec=EbusService)
        c.ebus.is_connected = True
        c.ebus.define_register = AsyncMock(return_value="done")
        await c._define_custom_registers()
        c.ebus.find_registers = AsyncMock(side_effect=ConnectionError())
        c.ebus._reconnect = AsyncMock(return_value=True)
        await c._async_update_data()
        assert not c._runtime_definitions
        assert c._last_energy_poll == datetime.min
        c.ebus.define_register.reset_mock()
        await c._define_custom_registers()
        assert c.ebus.define_register.await_count == 32


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


# Intent: the full confirmed runtime definition set is emitted to ebusd.
# Why: covers issues #49/#50/#60 registers so they are not silently dropped.
async def test_define_custom_registers_delegates_to_ebus() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.define_register = AsyncMock(return_value="defined")

        c.ebus = mock_ebus
        await c._define_custom_registers()

        assert mock_ebus.define_register.call_count == 32
        calls = [c.args[0] for c in mock_ebus.define_register.call_args_list]
        assert any("z1RoomHumidity" in d for d in calls)
        assert any("ManualCoolingStartDate" in d and d.startswith("r5") for d in calls)
        assert any("ManualCoolingEndDate" in d and d.startswith("r5") for d in calls)
        assert any("ManualCoolingStartDate" in d and d.startswith("w") for d in calls)
        assert any("ManualCoolingEndDate" in d and d.startswith("w") for d in calls)
        # b516 cooling-energy registers (issue #50), including the date-coded
        # day/month variants.
        assert any("CoolEnvYieldTotal" in d and "1000ffff02050000" in d for d in calls)
        assert any("CoolElecConsTotal" in d and "1000ffff03050000" in d for d in calls)
        assert any(",B516,1001ffff0205" in d for d in calls)
        assert any(",B516,1002ffff0205" in d for d in calls)
        # Daily electric for cooling (issue #50 follow-up) plus the lifetime and
        # daily electric counters for heating (Z=3) and DHW (Z=4) on the same
        # b516 statistics API.
        assert any("CoolElecConsDay" in d and ",B516,1001ffff0305" in d for d in calls)
        assert any("HcElecConsTotal" in d and "1000ffff03030000" in d for d in calls)
        assert any("HcElecConsDay" in d and ",B516,1001ffff0303" in d for d in calls)
        assert any("HwcElecConsTotal" in d and "1000ffff03040000" in d for d in calls)
        assert any("HwcElecConsDay" in d and ",B516,1001ffff0304" in d for d in calls)
        # SourceTempInput runtime define (issue #49), layout verified upstream
        # in john30/ebusd-configuration PR #565 on brine units.
        assert any("SourceTempInput" in d and ",B51A,05ff3222,value,,IGN:3,,,,value,,D2C" in d for d in calls)
        # B524 heating-circuit state registers (Helianthus B524 register map,
        # discussion #60): GG=0x02 messages with the documented RR and wire
        # types (EXP for f32, ULG for u32).
        assert any("Hc1FlowTempCalc" in d and ",B524,020002002000" in d for d in calls)
        assert any("Hc1MixerPosition" in d and ",B524,020002002100" in d for d in calls)
        assert any("Hc1Humidity" in d and ",B524,020002002200" in d and "EXP" in d for d in calls)
        assert any("Hc1DewPointTemp" in d and ",B524,020002002300" in d for d in calls)
        assert any("Hc1PumpHours" in d and ",B524,020002002400" in d and "ULG" in d for d in calls)
        assert any("Hc1PumpStarts" in d and ",B524,020002002500" in d and "ULG" in d for d in calls)
        assert any("Hc2FlowTempCalc" in d and ",B524,020002012000" in d for d in calls)
        assert any("Hc2MixerPosition" in d and ",B524,020002012100" in d for d in calls)
        assert any("Hc2Humidity" in d and ",B524,020002012200" in d and "EXP" in d for d in calls)
        assert any("Hc2DewPointTemp" in d and ",B524,020002012300" in d for d in calls)
        assert any("Hc2PumpHours" in d and ",B524,020002012400" in d and "ULG" in d for d in calls)
        assert any("Hc2PumpStarts" in d and ",B524,020002012500" in d and "ULG" in d for d in calls)


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
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value=None))
        c.ebus = mock_ebus
        c.async_request_refresh = AsyncMock()

        assert await c.async_write_register("ctlv2", "Z1DayTemp", "21") is True
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
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="21")
        c.ebus = mock_ebus

        assert await c.async_read_register("hmu", "OutsideTemp") == "21"
        mock_ebus.read_register.assert_awaited_once_with("hmux0", "OutsideTemp", "")


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
        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value=None))
        c.ebus = mock_ebus

        assert await c.async_write_register("hmu", "SetMode", "auto") is False
        mock_ebus.write_register.assert_not_awaited()


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

        mock_ebus.read_register.assert_any_await("hmu", "YieldHc")
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

        mock_ebus.read_register.assert_any_await("basv3", "PrEnergySumHc")
        mock_ebus.read_register.assert_any_await("basv3", "StatElectricEnergySum")
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

        mock_ebus.read_register.assert_any_await("ctlv3", "PrEnergySumHwc")
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


# Intent: with no graph at all the heating circuit falls back to the legacy ctlv2 default.
# Why: preserves pre-discovery behavior when _graph is None.
async def test_heating_circuit_fallback_no_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = None
        assert c.heating_circuit == "ctlv2"


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
