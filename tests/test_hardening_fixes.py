"""Unit tests for the closing hardening batch: command validation, ordered
dump persistence, cache failure logging, stop-on-failure write sequences, and
multi-entry service dispatch."""

from __future__ import annotations

import asyncio
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
# Why: prevents CR/LF command injection through register identifiers.
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


# Intent: write rejects an empty name and an embedded newline before sending.
# Why: prevents injection through write identifiers.
async def test_write_register_rejects_invalid_identifiers() -> None:
    svc = EbusService(host="127.0.0.1", port=8888)
    svc.send_command = AsyncMock()
    with pytest.raises(ValueError):
        await svc.write_register("hmu", "", "1")
    with pytest.raises(ValueError):
        await svc.write_register("hmu", "X\nY", "1")
    assert svc.send_command.await_count == 0


# Intent: define_register rejects empty definitions and newline-bearing quoted fields.
# Why: prevents malformed or injected define commands reaching ebusd.
async def test_define_register_rejects_invalid_definitions() -> None:
    svc = EbusService(host="127.0.0.1", port=8888)
    with pytest.raises(ValueError):
        await svc.define_register("")
    with pytest.raises(ValueError):
        await svc.define_register('r5,hmu,X,1,B5,"a\nb"')


# Intent: values keep their ebusd syntax — spaces and semicolons pass through.
# Why: protects legitimate multi-part ebusd values from overzealous sanitization.
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


# Intent: reject line breaks in write values before sending a protocol command.
# Why: ebusd commands are newline-delimited and must not allow command injection.
async def test_write_register_rejects_line_breaks_in_value() -> None:
    svc = EbusService(host="127.0.0.1", port=8888)
    svc.send_command = AsyncMock()

    result = await svc.write_register("hmu", "SetMode", "auto\nread -c hmu Status")

    assert result.success is False
    assert "line breaks" in result.error_message
    svc.send_command.assert_not_awaited()


# --- central write path: stop at the first failure, refresh only on success ---


# Intent: a batch write stops at the first failed register and never refreshes.
# Why: protects partial-write handling so a refresh only follows full success.
async def test_write_registers_stop_on_first_failure_without_refresh() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = _coordinator(tmpdir)
        c._graph = tc._make_graph()
        c._ebusd_connected = True
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


# Intent: a fully successful batch write triggers exactly one refresh.
# Why: protects the single refresh-after-write contract.
async def test_write_registers_refresh_once_after_full_success() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = _coordinator(tmpdir)
        c._graph = tc._make_graph()
        c._ebusd_connected = True
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
# Why: keeps failures diagnosable without first-run warning noise.
async def test_load_cache_logs_corrupt_but_not_missing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        c = _coordinator(tmpdir)
        cache_file = Path(c._cache_path)
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
# Why: prevents cached register values from leaking into logs.
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
# Why: protects ordered dump persistence for nested target paths.
async def test_persist_dump_creates_directory_before_write(tmp_path: Path) -> None:
    order: list[str] = []

    async def _executor(func, *args):
        order.append(func.__name__)
        return func(*args)

    hass = MagicMock()
    hass.async_add_executor_job = _executor
    target = tmp_path / "nested" / "discovery_dump.yaml"
    await DUMP._persist_dump(hass, str(target), {"metadata": {"dump_version": 3}})
    assert order == ["_mkdir", "_write_yaml_temp"]
    assert target.exists()


# Intent: exporting a dump with ebus None raises a HomeAssistantError naming the disconnected state.
# Why: gives a clear failure instead of a later attribute error.
async def test_export_dump_reports_disconnected_ebusd(tmp_path: Path) -> None:
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    coordinator = MagicMock()
    coordinator.ebus = None

    with pytest.raises(HomeAssistantError, match="ebusd is not connected"):
        await DUMP.async_export_discovery_dump(hass, coordinator)


# Intent: dump export refuses a live socket until the coordinator applies discovery.
# Why: map-driven probes must not use assumed circuits during initial setup.
async def test_export_dump_waits_for_discovery_graph(tmp_path: Path) -> None:
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator._graph = tc.DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
    coordinator._ebusd_connected = True
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator.ebus.read_register = AsyncMock(return_value="25")

    with pytest.raises(HomeAssistantError, match="discovery is complete"):
        await DUMP.async_export_discovery_dump(hass, coordinator)

    coordinator.ebus.find_registers.assert_not_awaited()
    coordinator.ebus.read_register.assert_not_awaited()


# Intent: dump export refuses to start while platform teardown is requested.
# Why: diagnostic map probes are active ebusd reads and must obey coordinator lifecycle gates.
async def test_export_dump_is_lifecycle_gated(tmp_path: Path) -> None:
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    coordinator._unload_requested = True
    coordinator.ebus.find_registers = AsyncMock(return_value=[])

    with pytest.raises(HomeAssistantError, match="integration is unloading"):
        await DUMP.async_export_discovery_dump(hass, coordinator)

    coordinator.ebus.find_registers.assert_not_awaited()


# Intent: stop map probes as soon as unload starts during a probe.
# Why: dump export can await several active reads before returning to its caller.
async def test_export_dump_stops_map_probes_after_unload_requested(tmp_path: Path) -> None:
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator.ebus.version = "26.1"
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator.ebus.read_register = AsyncMock()
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {
        "hmu.FirstProbe": MagicMock(enabled=True, writable=False, fallback_read=True),
        "hmu.SecondProbe": MagicMock(enabled=True, writable=False, fallback_read=True),
    }

    # Intent: flip the teardown flag while the current map probe is suspended.
    # Why: the exporter must stop before attempting the next mapped read.
    async def _read_and_unload(*args, **kwargs):
        coordinator._unload_requested = True
        return "42"

    coordinator.ebus.read_register.side_effect = _read_and_unload
    try:
        with pytest.raises(HomeAssistantError, match="integration is unloading"):
            await DUMP.async_export_discovery_dump(hass, coordinator)
    finally:
        DUMP.REGISTER_MAP = original_map

    coordinator.ebus.read_register.assert_awaited_once()


# Intent: skip every map probe when unload starts during discovery find.
# Why: the dump service must check lifecycle state before iterating discovered mappings.
async def test_export_dump_stops_map_probes_after_find_unload(tmp_path: Path) -> None:
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    coordinator.ebus.read_register = AsyncMock(return_value="42")

    # Intent: request teardown while find_registers is suspended.
    # Why: no map probe may start after the find reply arrives.
    async def _find_then_unload():
        coordinator._unload_requested = True
        return []

    coordinator.ebus.find_registers = AsyncMock(side_effect=_find_then_unload)
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {"hmu.FirstProbe": MagicMock(enabled=True, writable=False, fallback_read=True)}
    try:
        with pytest.raises(HomeAssistantError, match="integration is unloading"):
            await DUMP.async_export_discovery_dump(hass, coordinator)
    finally:
        DUMP.REGISTER_MAP = original_map

    coordinator.ebus.read_register.assert_not_awaited()


# Intent: dump export does not write YAML if unload starts during directory creation.
# Why: executor work must not cross the teardown boundary into persistent output.
async def test_export_dump_stops_before_yaml_write_after_unload_during_mkdir(tmp_path: Path) -> None:
    _ha_components.persistent_notification.create.reset_mock()
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator.ebus.get_info = AsyncMock(return_value={"version": "test"})
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )

    # Intent: request teardown after mkdir completes but before the persistence helper resumes.
    # Why: the exporter must skip the subsequent YAML write and success notification.
    async def _mkdir_then_unload(func, *args):
        func(*args)
        coordinator._unload_requested = True

    hass.async_add_executor_job = AsyncMock(side_effect=_mkdir_then_unload)
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {}
    try:
        with pytest.raises(HomeAssistantError, match="integration is unloading"):
            await DUMP.async_export_discovery_dump(hass, coordinator)
    finally:
        DUMP.REGISTER_MAP = original_map

    assert hass.async_add_executor_job.await_count == 1
    _ha_components.persistent_notification.create.assert_not_called()


# Intent: discard the staged dump when unload starts during file serialization.
# Why: the final persisted path must appear only after a post-write lifecycle check.
async def test_export_dump_discards_staged_file_after_unload_during_yaml_write(tmp_path: Path) -> None:
    _ha_components.persistent_notification.create.reset_mock()
    hass = MagicMock()
    output_dir = tmp_path / "vaillant_ebus"
    hass.config.path.return_value = str(output_dir)
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator.ebus.version = "26.1"
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator.ebus.get_info = AsyncMock(return_value={"version": "test"})
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )

    # Intent: begin and finish the background serialization before requesting unload.
    # Why: staged output must be removed rather than promoted to the final dump path.
    async def _run_executor_then_unload(func, *args):
        result = func(*args)
        if func is DUMP._write_yaml_temp:
            coordinator._unload_requested = True
        return result

    hass.async_add_executor_job = AsyncMock(side_effect=_run_executor_then_unload)
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {}
    try:
        with pytest.raises(HomeAssistantError, match="integration is unloading"):
            await DUMP.async_export_discovery_dump(hass, coordinator)
    finally:
        DUMP.REGISTER_MAP = original_map

    assert list(output_dir.glob("discovery_dump_*.yaml")) == []
    _ha_components.persistent_notification.create.assert_not_called()


# Intent: abort raw traffic capture promptly and stop ebusd grab when unload begins.
# Why: a dump request can otherwise keep its capture active for up to five minutes.
async def test_async_grab_stops_when_unload_starts() -> None:
    unloading = False
    commands: list[str] = []

    # Intent: toggle teardown during the capture wait without real-time sleeping.
    # Why: the capture loop must recheck lifecycle state between wait intervals.
    async def _sleep(_duration: float) -> None:
        nonlocal unloading
        unloading = True

    # Intent: record the ebusd command sequence for the capture lifecycle.
    # Why: cleanup must send `grab stop` and must not request captured results after unload.
    async def _grab_cmd(host, port, command, ensure_active=None):
        commands.append(command)
        if ensure_active is not None:
            ensure_active()
        return ["ok"]

    def _ensure_active() -> None:
        if unloading:
            raise HomeAssistantError("integration is unloading")

    original_sleep = asyncio.sleep
    original_grab_cmd = DUMP._grab_cmd
    DUMP.asyncio.sleep = _sleep
    DUMP._grab_cmd = _grab_cmd
    try:
        with pytest.raises(HomeAssistantError, match="integration is unloading"):
            await DUMP.async_grab("127.0.0.1", 8888, 300, ensure_active=_ensure_active)
    finally:
        DUMP.asyncio.sleep = original_sleep
        DUMP._grab_cmd = original_grab_cmd

    assert commands == ["grab", "grab stop"]


# Intent: preserve dump cancellation when the cleanup stop command also fails.
# Why: cleanup errors must not make a cancelled capture appear successful.
async def test_async_grab_cancellation_survives_stop_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    capture_waiting = asyncio.Event()
    stop_started = asyncio.Event()
    allow_stop_to_fail = asyncio.Event()

    # Intent: pause the capture until the parent task is cancelled.
    # Why: cancellation should enter grab cleanup before the stop command is tested.
    async def _capture_wait(_duration: float) -> None:
        capture_waiting.set()
        await asyncio.Event().wait()

    # Intent: fail grab stop only after a second cancellation reaches its awaiter.
    # Why: cancellation must remain visible even when cleanup also reports an error.
    async def _grab_cmd(host, port, command, ensure_active=None):
        if command == "grab stop":
            stop_started.set()
            await allow_stop_to_fail.wait()
            raise OSError("stop connection failed")
        return ["ok"]

    monkeypatch.setattr(DUMP.asyncio, "sleep", _capture_wait)
    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)
    grab_task = asyncio.create_task(DUMP.async_grab("127.0.0.1", 8888, 300))
    await capture_waiting.wait()
    grab_task.cancel()
    await stop_started.wait()
    allow_stop_to_fail.set()

    with pytest.raises(asyncio.CancelledError):
        await grab_task


# Intent: preserve cancellation when grab stop finishes in the same loop turn.
# Why: a completed stop command must not turn a cancelled capture into success.
@pytest.mark.parametrize("stop_response", [["done"], ["ERR: stop failed"], []])
async def test_stop_grab_keeps_cancellation_when_command_completes(
    stop_response: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_task: asyncio.Task | None = None

    # Intent: cancel the parent while the child stop command is completing.
    # Why: exercise the done-task race in the uninterruptible cleanup helper.
    async def _finish_stop(host, port, command, ensure_active=None):
        assert parent_task is not None
        parent_task.cancel()
        return stop_response

    monkeypatch.setattr(DUMP, "_grab_cmd", _finish_stop)
    parent_task = asyncio.create_task(DUMP._stop_grab_uninterruptibly("127.0.0.1", 8888))

    with pytest.raises(asyncio.CancelledError):
        await parent_task


# Intent: report a failed grab-stop command instead of a successful capture.
# Why: ebusd may otherwise continue capturing after the service reports completion.
async def test_async_grab_fails_when_stop_command_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Intent: fail only the cleanup command after an otherwise successful capture.
    # Why: cleanup failure must not be swallowed by the capture service.
    async def _fail_stop(host, port, command, ensure_active=None):
        if command == "grab stop":
            raise OSError("stop connection failed")
        return ["ok"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _fail_stop)

    with pytest.raises(HomeAssistantError, match="Could not stop ebusd traffic capture"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)


# Intent: reject stop responses that do not confirm ebusd ended the grab.
# Why: error-shaped replies and closed connections can leave bus capture active.
@pytest.mark.parametrize("stop_response", [[], ["ERR: invalid command"]])
async def test_async_grab_rejects_unconfirmed_stop_response(
    stop_response: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Intent: return an empty/error response only for the cleanup command.
    # Why: a dump must not report successful capture when ebusd rejected grab stop.
    async def _grab_cmd(host, port, command, ensure_active=None):
        if command == "grab stop":
            return stop_response
        return ["ok"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(HomeAssistantError, match="grab stop|confirm"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)


# Intent: reject textual ebusd errors from grab start and result commands.
# Why: error replies must not be serialized as a successful traffic capture.
@pytest.mark.parametrize(
    ("failed_command", "expected_error"),
    [("grab", "grab failed"), ("grab result all", "grab result all failed")],
)
async def test_async_grab_rejects_error_responses(
    failed_command: str,
    expected_error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []

    # Intent: return an ERR reply at the selected stage and acknowledge cleanup.
    # Why: response-shaped failures must abort the dump after the stop attempt.
    async def _grab_cmd(host, port, command, ensure_active=None):
        commands.append(command)
        if command == failed_command:
            return ["ERR: unavailable"]
        return ["done"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(HomeAssistantError, match=expected_error):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands[-1] == "grab stop"


# Intent: abort when ebusd never acknowledges that raw capture started.
# Why: an unconfirmed start must not be reported as a successful empty capture.
async def test_async_grab_rejects_missing_start_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    # Intent: return no acknowledgement for grab but confirm the cleanup stop.
    # Why: the failed start must surface while still attempting grab stop.
    async def _grab_cmd(host, port, command, ensure_active=None):
        commands.append(command)
        return [] if command == "grab" else ["done"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(HomeAssistantError, match="did not confirm that the grab started"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == ["grab", "grab stop"]


# Intent: preserve a capture transport exception after issuing grab stop.
# Why: result retrieval failure must not leave the bus grab active or return partial success.
async def test_async_grab_transport_failure_still_stops_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    # Intent: fail result retrieval while allowing the cleanup command to succeed.
    # Why: the original transport failure must propagate after cleanup.
    async def _grab_cmd(host, port, command, ensure_active=None):
        commands.append(command)
        if command == "grab result all":
            raise ConnectionError("grab transport failed")
        return ["done"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(ConnectionError, match="grab transport failed"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == ["grab", "grab result all", "grab stop"]


# Intent: fail dump export if the raw-grab transport fails after capture starts.
# Why: an error response must not be serialized or announced as a successful dump.
async def test_export_dump_fails_when_grab_transport_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ha_components.persistent_notification.create.reset_mock()
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    monkeypatch.setattr(DUMP, "async_grab", AsyncMock(side_effect=ConnectionError("grab transport failed")))
    monkeypatch.setattr(DUMP, "_persist_dump", AsyncMock())
    monkeypatch.setattr(DUMP, "REGISTER_MAP", {})

    with pytest.raises(HomeAssistantError, match="Failed to capture raw eBUS traffic"):
        await DUMP.async_export_discovery_dump(hass, coordinator, grab_duration=1)

    DUMP._persist_dump.assert_not_awaited()
    DUMP.async_grab.assert_awaited_once()
    _ha_components.persistent_notification.create.assert_not_called()


# Intent: bound a stalled raw ebusd TCP connection attempt.
# Why: unload cannot wait indefinitely for a socket connect that never completes.
async def test_grab_command_connection_has_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # Intent: keep the mocked connect pending until wait_for cancels it.
    # Why: verify the raw-grab transport applies its configured connection timeout.
    async def _blocked_open_connection(host, port):
        await asyncio.Event().wait()

    monkeypatch.setattr(DUMP.asyncio, "open_connection", _blocked_open_connection)
    monkeypatch.setattr(DUMP, "GRAB_CONNECT_TIMEOUT", 0.001)

    with pytest.raises(TimeoutError):
        await DUMP._grab_cmd("127.0.0.1", 8888, "grab")


# Intent: unload cancels a tracked dump capture and waits for its grab-stop cleanup.
# Why: diagnostic tasks must not outlive the config entry that owns their transport.
async def test_export_dump_is_cancelled_by_coordinator_unload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    capture_started = asyncio.Event()
    stop_started = asyncio.Event()
    allow_stop_to_finish = asyncio.Event()
    commands: list[str] = []

    # Intent: block capture until unload, then block cleanup until a second cancel arrives.
    # Why: repeated cancellation must not interrupt the final ebusd grab-stop command.
    async def _grab_cmd(host, port, command, ensure_active=None):
        commands.append(command)
        if command == "grab":
            capture_started.set()
        if command == "grab stop":
            stop_started.set()
            await allow_stop_to_finish.wait()
        if ensure_active is not None:
            ensure_active()
        return ["ok"]

    # Intent: keep the capture waiting until the test requests unload.
    # Why: test repeated cancellation while the stop command owns cleanup.
    async def _capture_wait(_duration: float) -> None:
        await asyncio.Event().wait()

    original_map = DUMP.REGISTER_MAP
    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)
    monkeypatch.setattr(DUMP.asyncio, "sleep", _capture_wait)
    DUMP.REGISTER_MAP = {}
    coordinator.ebus.request_shutdown = MagicMock()
    coordinator.ebus.disconnect = AsyncMock()
    try:
        export_task = asyncio.create_task(DUMP.async_export_discovery_dump(hass, coordinator, grab_duration=300))
        await capture_started.wait()
        coordinator.request_unload()
        await stop_started.wait()
        export_task.cancel()
        stop_task = asyncio.create_task(coordinator.async_stop())
        assert not stop_task.done()
        allow_stop_to_finish.set()
        await stop_task
        with pytest.raises(asyncio.CancelledError):
            await export_task
    finally:
        allow_stop_to_finish.set()
        DUMP.REGISTER_MAP = original_map

    assert commands == ["grab", "grab stop"]
    assert coordinator._active_dump_tasks == set()


# Intent: remove a staged dump file if export is cancelled during executor serialization.
# Why: cancellation can arrive before the executor returns the temporary path.
async def test_persist_dump_cancellation_removes_staged_file(tmp_path: Path) -> None:
    hass = MagicMock()
    staged = asyncio.Event()
    allow_executor_return = asyncio.Event()
    write_finished = asyncio.Event()

    # Intent: create the staged file, then hold the executor result until cancellation.
    # Why: persistence must recover the path and clean it even when the caller is cancelled.
    async def _executor(func, *args):
        result = func(*args)
        if func is DUMP._write_yaml_temp:
            staged.set()
            await allow_executor_return.wait()
            write_finished.set()
        return result

    hass.async_add_executor_job = _executor
    target = tmp_path / "discovery_dump.yaml"
    persist_task = asyncio.create_task(DUMP._persist_dump(hass, str(target), {"metadata": {}}))
    await staged.wait()
    staged_files = list(tmp_path.glob(".discovery_dump_*.yaml"))
    assert len(staged_files) == 1

    persist_task.cancel()
    persist_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await persist_task
    allow_executor_return.set()
    await write_finished.wait()
    await asyncio.sleep(0)

    assert list(tmp_path.glob(".discovery_dump_*.yaml")) == []


# Intent: dump map probes skip logical aliases with ambiguous graph ownership.
# Why: prevents dump probing of aliases with unresolved ownership.
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


# Intent: dump map probes skip a logical alias with no discovered owner.
# Why: prevents dump probing of aliases that have no hardware.
async def test_dump_registers_skip_missing_alias() -> None:
    ebus = MagicMock()
    ebus.find_registers = AsyncMock(return_value=[])
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {"hmu.OutsideTemp": MagicMock(enabled=True, writable=False)}
    try:
        registers, _, _ = await DUMP._dump_registers(ebus, circuit_aliases={"hmu": None})
    finally:
        DUMP.REGISTER_MAP = original_map

    assert registers == []
    ebus.read_register.assert_not_called()


# Intent: dump map probes respect fallback_read while retaining metadata for skipped registers.
# Why: discovery export must not reintroduce active reads disabled for unsafe B524 states.
async def test_dump_registers_skip_disabled_fallback_reads() -> None:
    ebus = MagicMock()
    ebus.find_registers = AsyncMock(return_value=[])
    ebus.read_register = AsyncMock(return_value="42")
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {
        "ctlv2.Hc1FlowTempCalc": MagicMock(enabled=True, writable=False, fallback_read=False),
        "ctlv2.Hc1ActualFlowTempDesired": MagicMock(enabled=True, writable=False, fallback_read=True),
    }
    try:
        registers, _, _ = await DUMP._dump_registers(ebus, circuit_aliases={"ctlv2": "ctlv3"})
    finally:
        DUMP.REGISTER_MAP = original_map

    by_name = {register["name"]: register for register in registers}
    assert by_name["Hc1FlowTempCalc"]["values"] == [None]
    assert by_name["Hc1FlowTempCalc"]["from_map"] is True
    assert by_name["Hc1ActualFlowTempDesired"]["values"] == ["42"]
    ebus.read_register.assert_awaited_once_with("ctlv3", "Hc1ActualFlowTempDesired", raise_transport_errors=True)


# Intent: _redact replaces sensitive register names with a placeholder and leaves others untouched.
# Why: protects serial-like secrets from appearing in exported dumps.
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
# Why: protects the common single-entry service call path.
async def test_service_dispatch_single_entry_auto_selected() -> None:
    hass = MagicMock()
    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    hass.data = {"vaillant_ebus": {"entry-a": coord}}
    await INIT._svc_refresh(hass, _call({}))
    coord.async_request_refresh.assert_awaited_once()


# Intent: an explicit entry_id routes the service to that coordinator only.
# Why: protects deterministic routing when multiple entries are loaded.
async def test_service_dispatch_explicit_entry_id_wins() -> None:
    hass, coord_a, coord_b = _two_entry_hass()
    await INIT._svc_refresh(hass, _call({"entry_id": "entry-b"}))
    coord_b.async_request_refresh.assert_awaited_once()
    coord_a.async_request_refresh.assert_not_awaited()


# Intent: an ambiguous call and an unknown entry_id both raise HomeAssistantError.
# Why: prevents silently picking the wrong coordinator.
async def test_service_dispatch_requires_selector_when_ambiguous() -> None:
    hass, coord_a, _coord_b = _two_entry_hass()
    with pytest.raises(HomeAssistantError):
        await INIT._svc_refresh(hass, _call({}))
    with pytest.raises(HomeAssistantError):
        await INIT._svc_refresh(hass, _call({"entry_id": "missing"}))


# Intent: service dispatch raises when no entries are loaded.
# Why: surfaces a misconfigured integration instead of silently doing nothing.
async def test_service_dispatch_fails_without_loaded_entries() -> None:
    hass = MagicMock()
    hass.data = {"vaillant_ebus": {}}
    with pytest.raises(HomeAssistantError):
        await INIT._svc_refresh(hass, _call({}))


# Intent: read_parameter calls the selected coordinator with the raw circuit and empty field.
# Why: protects multi-entry read routing.
async def test_read_parameter_routes_to_selected_coordinator() -> None:
    hass, coord_a, coord_b = _two_entry_hass()
    for coord in (coord_a, coord_b):
        coord.async_read_register = AsyncMock(return_value="21.5")
    await INIT._svc_read_parameter(hass, _call({"circuit": "hmu", "name": "OutsideTemp", "entry_id": "entry-a"}))
    coord_a.async_read_register.assert_awaited_once_with("hmu", "OutsideTemp", "")
    coord_b.async_read_register.assert_not_awaited()


# Intent: read_parameter resolves the logical circuit to the discovered owner before reading.
# Why: protects service reads on HMUX0 hardware via graph identity.
async def test_read_parameter_uses_discovered_circuit_resolution() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = tc._hass(tmpdir)
        coordinator = VaillantCoordinator(hass, tc._entry())
        coordinator._graph = tc.DeviceGraph(
            nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
            raw_registers={},
            placeholder_registers=set(),
        )
        coordinator._ebusd_connected = True
        coordinator.ebus = MagicMock()
        coordinator.ebus.is_connected = True
        coordinator.ebus.read_register = AsyncMock(return_value="21.5")
        hass.data = {"vaillant_ebus": {"entry-a": coordinator}}

        await INIT._svc_read_parameter(hass, _call({"circuit": "hmu", "name": "OutsideTemp", "entry_id": "entry-a"}))

        coordinator.ebus.read_register.assert_awaited_once_with("hmux0", "OutsideTemp", "")


# Intent: read_parameter performs no transport read when the circuit owner is absent.
# Why: prevents service reads of aliases that have no discovered hardware.
async def test_read_parameter_does_not_read_when_circuit_owner_is_missing() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        hass = tc._hass(tmpdir)
        coordinator = VaillantCoordinator(hass, tc._entry())
        coordinator._graph = tc.DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
        coordinator.ebus = MagicMock()
        coordinator.ebus.is_connected = True
        coordinator.ebus.read_register = AsyncMock(return_value="21.5")
        hass.data = {"vaillant_ebus": {"entry-a": coordinator}}

        await INIT._svc_read_parameter(hass, _call({"circuit": "hmu", "name": "OutsideTemp", "entry_id": "entry-a"}))

        coordinator.ebus.read_register.assert_not_awaited()


# Intent: integration-scope setup registers every service once with schemas
# that accept the optional entry selector.
# Why: protects the service surface from missing or renamed registrations.
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


# Intent: every registered service handler is an async coroutine function.
# Why: Home Assistant requires async handlers, so this guards against a sync regression.
async def test_registered_service_handlers_are_async_callbacks() -> None:
    hass = MagicMock()
    registered: dict[str, object] = {}

    def _register(domain, name, handler, schema=None):  # noqa: ARG001
        registered[name] = handler

    hass.services.async_register.side_effect = _register
    await INIT.async_setup(hass, {})

    assert all(inspect.iscoroutinefunction(handler) for handler in registered.values())
