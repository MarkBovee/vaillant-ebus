"""Unit tests for the closing hardening batch: command validation, ordered
dump persistence, cache failure logging, stop-on-failure write sequences, and
multi-entry service dispatch."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import inspect
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests import test_coordinator as tc  # noqa: F401 — installs shared HA mocks

COMPONENT_PATH = Path(tc.COMPONENT_PATH)
BACKEND_PATH = COMPONENT_PATH / "backend"

EBUS = sys.modules["vaillant_ebus.backend.ebus_service"]
from vaillant_ebus.backend.ebus_service import EbusService, WriteResult  # noqa: E402
from vaillant_ebus.coordinator import VaillantCoordinator  # noqa: E402

# --- bootstrap extras the integration __init__ needs on top of tc's stubs ---


class _HomeAssistantError(Exception):
    pass


_ha_exceptions = MagicMock()
_ha_exceptions.HomeAssistantError = _HomeAssistantError
tc.sys.modules.setdefault("homeassistant.exceptions", _ha_exceptions)

_ha_components = MagicMock()
tc.sys.modules["homeassistant.components"] = _ha_components
tc.sys.modules["homeassistant.components.persistent_notification"] = MagicMock()

_const = tc.sys.modules["vaillant_ebus.const"]
if not hasattr(_const, "PLATFORMS"):
    _const.PLATFORMS = ("climate", "sensor", "select", "switch", "binary_sensor", "number", "button")
if not hasattr(_const, "SENSITIVE_FIELDS"):
    _const.SENSITIVE_FIELDS = frozenset()
if not hasattr(_const, "INTEGRATION_VERSION"):
    _const.INTEGRATION_VERSION = "1.7.0"

# __init__.py imports voluptuous at module scope and builds the entry
# selector with vol.Optional; CI does not install it, so stub the parts
# used at import time (Schema/Required are only reached at runtime).
_vol = MagicMock()
tc.sys.modules.setdefault("voluptuous", _vol)

DUMP_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.dump_service", COMPONENT_PATH / "dump_service.py")
assert DUMP_SPEC and DUMP_SPEC.loader
DUMP = importlib.util.module_from_spec(DUMP_SPEC)
sys.modules["vaillant_ebus.dump_service"] = DUMP
DUMP_SPEC.loader.exec_module(DUMP)

INIT_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.__init__", COMPONENT_PATH / "__init__.py")
assert INIT_SPEC and INIT_SPEC.loader
INIT = importlib.util.module_from_spec(INIT_SPEC)
sys.modules["vaillant_ebus.integration_init"] = INIT
INIT_SPEC.loader.exec_module(INIT)

HomeAssistantError = INIT.HomeAssistantError


def _call(data: dict) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _coordinator(tmpdir: str) -> VaillantCoordinator:
    return VaillantCoordinator(tc._hass(tmpdir), tc._entry())


# --- backend boundary validation ---


# Intent: identifiers are validated before interpolation; empty values and
# CR/LF injection never reach the protocol layer.
async def test_read_register_rejects_invalid_identifiers() -> None:
    svc = EbusService(host="127.0.0.1", port=8888)
    svc.send_command = AsyncMock()  # must never be reached by invalid input
    bad_calls = [
        ("", "OutsideTemp", ""),
        ("hmu\n", "OutsideTemp", ""),
        ("hmu", "OutsideTemp\r", ""),
        ("hmu", "OutsideTemp", "value\nx"),
    ]
    for circuit, name, field in bad_calls:
        with pytest.raises(ValueError):
            await svc.read_register(circuit, name, field)
    assert svc.send_command.await_count == 0
    # Valid identifiers pass validation and reach the transport.
    svc.send_command.assert_not_awaited()
    svc.send_command.return_value = EBUS.SendResult(data="21.5")
    assert await svc.read_register("hmu", "OutsideTemp") == "21.5"
    assert svc.send_command.await_count == 1


async def test_write_register_rejects_invalid_identifiers() -> None:
    svc = EbusService(host="127.0.0.1", port=8888)
    svc.send_command = AsyncMock()
    with pytest.raises(ValueError):
        await svc.write_register("hmu", "", "1")
    with pytest.raises(ValueError):
        await svc.write_register("hmu", "X\nY", "1")
    assert svc.send_command.await_count == 0


async def test_define_register_rejects_invalid_definitions() -> None:
    svc = EbusService(host="127.0.0.1", port=8888)
    with pytest.raises(ValueError):
        await svc.define_register("")
    with pytest.raises(ValueError):
        await svc.define_register('r5,hmu,X,1,B5,"a\nb"')


# Intent: values keep their ebusd syntax — spaces and semicolons pass through.
async def test_write_register_preserves_values_with_spaces_and_semicolons() -> None:
    svc = EbusService(host="127.0.0.1", port=8888)
    svc.send_command = AsyncMock(
        side_effect=[
            EBUS.SendResult(data="done"),
            EBUS.SendResult(data="a b;c"),
        ]
    )
    result = await svc.write_register("hmu", "HwcTempDesired", "a b;c")
    assert result.success is True
    first_cmd = svc.send_command.await_args_list[0].args[0]
    assert first_cmd == "write -c hmu HwcTempDesired a b;c"


# --- central write path: stop at the first failure, refresh only on success ---


async def test_write_registers_stop_on_first_failure_without_refresh() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = _coordinator(tmpdir)
        c.ebus = MagicMock()
        c.ebus.is_connected = True
        c.ebus.write_register = AsyncMock(
            side_effect=[
                WriteResult(success=True, verified_value="1"),
                WriteResult(success=False, error_message="boom"),
                WriteResult(success=True, verified_value="3"),
            ]
        )
        c.async_request_refresh = AsyncMock()
        ok = await c.async_write_registers([("hmu", "RegA", "1"), ("hmu", "RegB", "2"), ("hmu", "RegC", "3")])
        assert ok is False
        assert c.ebus.write_register.await_count == 2  # stopped after RegB failed
        c.async_request_refresh.assert_not_awaited()


async def test_write_registers_refresh_once_after_full_success() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = _coordinator(tmpdir)
        c.ebus = MagicMock()
        c.ebus.is_connected = True
        c.ebus.write_register = AsyncMock(return_value=WriteResult(success=True, verified_value="ok"))
        c.async_request_refresh = AsyncMock()
        ok = await c.async_write_registers([("hmu", "RegA", "1"), ("hmu", "RegB", "2")])
        assert ok is True
        assert c.ebus.write_register.await_count == 2
        c.async_request_refresh.assert_awaited_once()


# --- persistence failure visibility ---


# Intent: a corrupt cache falls back to an empty dict but logs why; a missing
# file stays silent because first run without a cache is normal.
async def test_load_cache_logs_corrupt_but_not_missing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = _coordinator(tmpdir)
        cache_file = Path(c.hass.config.path.return_value)
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("{not json", encoding="utf-8")
        with caplog.at_level("WARNING"):
            assert await c._async_load_cache() == {}
        assert "register cache" in caplog.text

    with tempfile.TemporaryDirectory() as tmpdir:
        c2 = _coordinator(tmpdir)
        caplog.clear()
        with caplog.at_level("WARNING"):
            assert await c2._async_load_cache() == {}
        assert "register cache" not in caplog.text


# Intent: save failures log path and reason — never the cached values.
async def test_save_cache_failure_logs_without_values(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = _coordinator(tmpdir)

        async def _explode(func, *args):  # noqa: ARG001
            raise OSError("disk full")

        c.hass.async_add_executor_job = _explode
        with caplog.at_level("WARNING"):
            await c._async_save_cache({"HwcTempDesired": "TOPSECRETVALUE"})
        assert "Failed to save register cache" in caplog.text
        assert str(Path(tmpdir)) in caplog.text or "register_cache" in caplog.text
        assert "TOPSECRETVALUE" not in caplog.text


# --- ordered dump persistence ---


# Intent: the dump directory is created before the YAML write lands.
async def test_persist_dump_creates_directory_before_write(tmp_path: Path) -> None:
    order: list[str] = []

    async def _executor(func, *args):
        order.append(func.__name__)
        return func(*args)

    hass = MagicMock()
    hass.async_add_executor_job = _executor
    target = tmp_path / "nested" / "discovery_dump.yaml"
    await DUMP._persist_dump(hass, str(target), {"metadata": {"dump_version": 3}})
    assert order == ["_mkdir", "_write_yaml"]
    assert target.exists()


async def test_export_dump_reports_disconnected_ebusd(tmp_path: Path) -> None:
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    coordinator = MagicMock()
    coordinator.ebus = None

    with pytest.raises(HomeAssistantError, match="ebusd is not connected"):
        await DUMP.async_export_discovery_dump(hass, coordinator)


# Intent: dump map probes skip logical aliases with ambiguous graph ownership.
async def test_dump_registers_skip_ambiguous_alias() -> None:
    ebus = MagicMock()
    ebus.find_registers = AsyncMock(return_value=[])
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {"ctlv2.Z1DayTemp": MagicMock(enabled=True, writable=False)}
    try:
        registers, _, _ = await DUMP._dump_registers(ebus, circuit_aliases={"ctlv2": None})
    finally:
        DUMP.REGISTER_MAP = original_map

    assert registers == []
    ebus.read_register.assert_not_called()


def test_dump_redacts_sensitive_register_names() -> None:
    DUMP.SENSITIVE_FIELDS = {"serial"}
    assert DUMP._redact("secret-value", "SerialNumber") == "<redacted>"
    assert DUMP._redact("normal-value", "Status") == "normal-value"


# --- multi-entry service dispatch ---


def _two_entry_hass() -> tuple[MagicMock, MagicMock, MagicMock]:
    hass = MagicMock()
    coord_a, coord_b = MagicMock(), MagicMock()
    coord_a.async_request_refresh = AsyncMock()
    coord_b.async_request_refresh = AsyncMock()
    hass.data = {"vaillant_ebus": {"entry-a": coord_a, "entry-b": coord_b}}
    return hass, coord_a, coord_b


# Intent: services stay deterministic with multiple entries — explicit entry_id
# wins, single entries auto-select, ambiguity and unknown ids fail loudly.
async def test_service_dispatch_single_entry_auto_selected() -> None:
    hass = MagicMock()
    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    hass.data = {"vaillant_ebus": {"entry-a": coord}}
    await INIT._svc_refresh(hass, _call({}))
    coord.async_request_refresh.assert_awaited_once()


async def test_service_dispatch_explicit_entry_id_wins() -> None:
    hass, coord_a, coord_b = _two_entry_hass()
    await INIT._svc_refresh(hass, _call({"entry_id": "entry-b"}))
    coord_b.async_request_refresh.assert_awaited_once()
    coord_a.async_request_refresh.assert_not_awaited()


async def test_service_dispatch_requires_selector_when_ambiguous() -> None:
    hass, coord_a, _coord_b = _two_entry_hass()
    with pytest.raises(HomeAssistantError):
        await INIT._svc_refresh(hass, _call({}))
    with pytest.raises(HomeAssistantError):
        await INIT._svc_refresh(hass, _call({"entry_id": "missing"}))


async def test_service_dispatch_fails_without_loaded_entries() -> None:
    hass = MagicMock()
    hass.data = {"vaillant_ebus": {}}
    with pytest.raises(HomeAssistantError):
        await INIT._svc_refresh(hass, _call({}))


async def test_read_parameter_routes_to_selected_coordinator() -> None:
    hass, coord_a, coord_b = _two_entry_hass()
    for coord in (coord_a, coord_b):
        coord.ebus = MagicMock()
        coord.ebus.read_register = AsyncMock(return_value="21.5")
    await INIT._svc_read_parameter(hass, _call({"circuit": "hmu", "name": "OutsideTemp", "entry_id": "entry-a"}))
    coord_a.ebus.read_register.assert_awaited_once_with("hmu", "OutsideTemp", "")
    coord_b.ebus.read_register.assert_not_awaited()


# Intent: integration-scope setup registers every service once with schemas
# that accept the optional entry selector.
async def test_async_setup_registers_all_services_with_entry_selector() -> None:
    hass = MagicMock()
    registered: dict[str, object] = {}

    def _register(domain, name, handler, schema=None):  # noqa: ARG001
        registered[name] = schema

    hass.services.async_register.side_effect = _register
    assert await INIT.async_setup(hass, {}) is True
    expected = {
        "read_parameter",
        "write_parameter",
        "refresh",
        "rediscover",
        "analyze_registers",
        "export_discovery_dump",
        "set_mode_override",
        "clear_mode_override",
    }
    assert set(registered) == expected


async def test_registered_service_handlers_are_async_callbacks() -> None:
    hass = MagicMock()
    registered: dict[str, object] = {}

    def _register(domain, name, handler, schema=None):  # noqa: ARG001
        registered[name] = handler

    hass.services.async_register.side_effect = _register
    await INIT.async_setup(hass, {})

    assert all(inspect.iscoroutinefunction(handler) for handler in registered.values())
