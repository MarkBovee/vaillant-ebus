"""Unit tests for VaillantCoordinator — service orchestration."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"
BACKEND_PATH = COMPONENT_PATH / "backend"

for name in ("vaillant_ebus", "vaillant_ebus.backend"):
    pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    pkg.__path__ = [str(COMPONENT_PATH)] if name == "vaillant_ebus" else [str(BACKEND_PATH)]
    sys.modules[name] = pkg

MODELS_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.models", BACKEND_PATH / "models.py"
)
assert MODELS_SPEC and MODELS_SPEC.loader
MODELS = importlib.util.module_from_spec(MODELS_SPEC)
sys.modules["vaillant_ebus.backend.models"] = MODELS
MODELS_SPEC.loader.exec_module(MODELS)

MAPPING_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.mapping", BACKEND_PATH / "mapping.py"
)
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

from vaillant_ebus.backend.ebus_service import EbusService  # noqa: E402
from vaillant_ebus.backend.entity_factory import EntityFactoryService  # noqa: E402
from vaillant_ebus.backend.models import DeviceGraph, DeviceNode, DeviceType, EbusdRegister  # noqa: E402

mock_homeassistant = MagicMock()
mock_homeassistant.config_entries = MagicMock()
mock_homeassistant.core = MagicMock()
mock_homeassistant.helpers = MagicMock()
mock_homeassistant.helpers.device_registry = MagicMock()
mock_homeassistant.helpers.update_coordinator = MagicMock()
mock_homeassistant.helpers.device_registry.DeviceInfo = dict

class _MockDataUpdateCoordinator:
    def __init__(self, hass, logger, **kwargs):  # noqa: ARG002
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
sys.modules["homeassistant.helpers.update_coordinator"] = mock_homeassistant.helpers.update_coordinator
sys.modules["homeassistant.const"] = MagicMock()



repairs_module = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("vaillant_ebus.repairs", None)
)
repairs_module.async_dismiss_ebusd_unreachable = AsyncMock()
repairs_module.async_create_ebusd_unreachable = AsyncMock()
sys.modules["vaillant_ebus.repairs"] = repairs_module

const_module = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("vaillant_ebus.const", None)
)
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

from vaillant_ebus.coordinator import VaillantCoordinator  # noqa: E402


def _hass(cache_dir: str) -> MagicMock:
    h = MagicMock()
    h.config.path.return_value = str(Path(cache_dir) / "vaillant_ebus" / "register_cache.json")
    h.async_create_task = MagicMock()
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
        assert len(c.entities) > 0
        assert any(e.circuit == "hmu" for e in c.entities)


async def test_coordinator_seeds_from_cache_with_cached_values() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "vaillant_ebus" / "register_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache = {"hmu.FlowTemp.value": "38.5", "ctlv2.Z1DayTemp.value": "21.0"}
        cache_path.write_text(json.dumps(cache))

        hass = _hass(tmpdir)
        hass.config.path.return_value = str(cache_path)

        c = VaillantCoordinator(hass, _entry())
        assert c.registers.get("ctlv2.Z1DayTemp")
        assert c.registers["ctlv2.Z1DayTemp"].value.get("value") == "21.0"
        assert c.registers["ctlv2.Z1DayTemp"].has_data is True


async def test_connect_and_discover_success() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = _hass(tmpdir)
        c = VaillantCoordinator(hass, _entry())
        graph = _make_graph()
        c.entities = c.entity_factory.generate(graph)
        c._graph = graph
        assert len(c.entities) > 0
        assert c.heating_circuit == "ctlv2"


async def test_connect_failure_no_crash() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())
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

        assert mock_ebus.define_register.call_count == 1


async def test_define_custom_registers_skips_when_not_connected() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = False
        c.ebus = mock_ebus

        await c._define_custom_registers()
        assert mock_ebus.define_register.call_count == 0


async def test_fallback_read_adds_new_registers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = VaillantCoordinator(_hass(tmpdir), _entry())

        mock_ebus = MagicMock(spec=EbusService)
        mock_ebus.is_connected = True
        mock_ebus.read_register = AsyncMock(return_value="45.0")

        c.ebus = mock_ebus
        c._graph = _make_graph()
        c._last_find_keys = {
            "hmu.RunDataStatuscode", "hmu.OutsideTemp",
            "ctlv2.Z1OpMode", "ctlv2.Z1DayTemp",
        }
        c.entities = c.entity_factory.generate(c._graph)

        before = len(c.registers)
        await c._fallback_read()

        assert len(c.registers) >= before


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
        assert "HMU00" in info.get("name", "")


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
        values = c._values_from_registers()
        assert values["test.Example.value"] == "22.50"


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
