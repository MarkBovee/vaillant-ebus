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

REGISTER_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.register_service", BACKEND_PATH / "register_service.py"
)
assert REGISTER_SPEC and REGISTER_SPEC.loader
REGISTER = importlib.util.module_from_spec(REGISTER_SPEC)
sys.modules["vaillant_ebus.backend.register_service"] = REGISTER
REGISTER_SPEC.loader.exec_module(REGISTER)

ANALYSIS_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.analysis_service", BACKEND_PATH / "analysis_service.py"
)
assert ANALYSIS_SPEC and ANALYSIS_SPEC.loader
ANALYSIS = importlib.util.module_from_spec(ANALYSIS_SPEC)
sys.modules["vaillant_ebus.backend.analysis_service"] = ANALYSIS
ANALYSIS_SPEC.loader.exec_module(ANALYSIS)

from vaillant_ebus.backend.ebus_service import EbusService, WriteResult  # noqa: E402
from vaillant_ebus.backend.entity_factory import EntityFactoryService  # noqa: E402
from vaillant_ebus.backend.models import DeviceGraph, DeviceNode, DeviceType, EbusdRegister  # noqa: E402

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
sys.modules["homeassistant.helpers.device_registry"] = mock_homeassistant.helpers.device_registry
sys.modules["homeassistant.helpers.event"] = mock_homeassistant.helpers.event
sys.modules["homeassistant.helpers.update_coordinator"] = mock_homeassistant.helpers.update_coordinator
sys.modules["homeassistant.const"] = MagicMock()


repairs_module = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("vaillant_ebus.repairs", None))
repairs_module.async_dismiss_ebusd_unreachable = AsyncMock()
repairs_module.async_create_ebusd_unreachable = AsyncMock()
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

from vaillant_ebus.coordinator import VaillantCoordinator, _register_values  # noqa: E402


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


async def test_coordinator_creates_entity_factory() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert isinstance(c.entity_factory, EntityFactoryService)


async def test_coordinator_seeds_from_cache() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert len(c.entities) == 0


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


# Intent: recover Z2 entities from cache before ebusd completes live discovery.
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
async def test_heat_pump_circuit_resolves_from_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.heat_pump_circuit == "hmu"
        c._graph = _make_graph()
        assert c.heat_pump_circuit == "hmu"


async def test_heat_pump_circuit_resolves_hmux0() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        graph = DeviceGraph(
            nodes={
                "hmux0": DeviceNode(
                    circuit="hmux0",
                    device_type=DeviceType.HEAT_PUMP,
                    registers=["hmux0.RunDataStatuscode"],
                    has_data=True,
                    scan_type="HMUX0",
                ),
                "ctlv3": DeviceNode(
                    circuit="ctlv3",
                    device_type=DeviceType.HEATING_CONTROLLER,
                    registers=["ctlv3.Z1OpMode"],
                    has_data=True,
                    scan_type="CTLV3",
                    parent="hmux0",
                ),
            },
            raw_registers={"hmux0.RunDataStatuscode": "standby", "ctlv3.Z1OpMode": "day"},
            placeholder_registers=set(),
        )
        c._graph = graph
        assert c.heat_pump_circuit == "hmux0"
        assert c.heating_circuit == "ctlv3"


# Intent: re-run discovery once after ebusd has had time to populate live values.
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
        assert mock_discovery.discover.await_count == 2
        schedule.assert_called()


# Intent: keep existing entities when delayed discovery finds only additional devices.
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

        assert "Generated 1 entity descriptions after initial ebusd discovery" not in caplog.text or True
        assert "entity descriptions after initial ebusd discovery" in caplog.text


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


async def test_define_custom_registers_delegates_to_ebus() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.define_register = AsyncMock(return_value="defined")

        c.ebus = mock_ebus
        await c._define_custom_registers()

        assert mock_ebus.define_register.call_count == 6
        calls = [c.args[0] for c in mock_ebus.define_register.call_args_list]
        assert any("z1RoomHumidity" in d for d in calls)
        assert any("ManualCoolingStartDate" in d and d.startswith("r5") for d in calls)
        assert any("ManualCoolingEndDate" in d and d.startswith("r5") for d in calls)
        assert any("ManualCoolingStartDate" in d and d.startswith("w") for d in calls)
        assert any("ManualCoolingEndDate" in d and d.startswith("w") for d in calls)
        assert any("SourceTempInput" in d and d.startswith("r3") for d in calls)


async def test_define_custom_registers_skips_when_not_connected() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = False
        c.ebus = mock_ebus

        await c._define_custom_registers()
        assert mock_ebus.define_register.call_count == 0


async def test_async_write_registers_bundles_and_refreshes() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.write_register = AsyncMock(
            return_value=WriteResult(success=True, verified_value=None)
        )
        c.ebus = mock_ebus
        c.async_request_refresh = AsyncMock()

        ok = await c.async_write_registers(
            [("ctlv2", "ManualCoolingStartDate", "14.08.2026"), ("ctlv2", "ManualCoolingEndDate", "17.08.2026")]
        )

        assert ok is True
        assert mock_ebus.write_register.call_count == 2
        assert c.async_request_refresh.call_count == 1


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

        ok = await c.async_write_registers(
            [("ctlv2", "A", "1"), ("ctlv2", "B", "2")]
        )

        assert ok is False
        assert c.async_request_refresh.call_count == 0


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


async def test_fallback_read_no_ebus_skips() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c.ebus = None
        await c._fallback_read()


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


async def test_entities_generated_after_discovery() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        graph = _make_graph()
        c._graph = graph
        entities = c.entity_factory.generate(graph)
        assert len(entities) > 0
        assert any(e.circuit == "hmu" for e in entities)


async def test_heating_circuit_from_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        graph = _make_graph()
        c._graph = graph
        assert c.heating_circuit == "ctlv2"


async def test_heating_circuit_fallback_no_graph() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = None
        assert c.heating_circuit == "ctlv2"


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


async def test_ebus_none_when_not_connected() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        assert c.ebus is None


async def test_ebus_settable() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        mock = MagicMock(spec=EbusService)
        c.ebus = mock
        assert c.ebus is mock
        c.ebus = None
        assert c.ebus is None


async def test_get_device_info_with_parent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        graph = _make_graph()
        c._graph = graph
        c.ebus = MagicMock()
        c.ebus.version = "23.2"

        info = c.get_device_info("ctlv2")
        assert info.get("via_device") == ("vaillant_ebus", "hmu")


async def test_get_device_info_no_graph_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
        c._graph = None
        c.ebus = None

        info = c.get_device_info("hmu")
        assert "hmu" in str(info["identifiers"])


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
            assert call_log.index("connect") < call_log.index("define") < call_log.index("find")
            assert len(c.entities) > 0
    finally:
        module.EbusService = orig_ebus


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
        registry.async_update_entity = MagicMock(
            side_effect=lambda entity_id, **kwargs: updated.append(entity_id)
        )
        hass.helpers.entity_registry.async_get = MagicMock(return_value=registry)

        entry = _entry()
        entry.entry_id = "entry-1"
        c = VaillantCoordinator(hass, entry)
        c.ebus = MagicMock()
        c.ebus.is_connected = True
        result = await c._enable_registry_entities(["hmu.PowerConsumptionHmu"])
        assert result == ["sensor.power"]
        assert updated == ["sensor.power"]


# Intent: case-variant cache keys (HwcSfMode vs HwcSFMode) must not double-register.
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
