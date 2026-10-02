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
    coordinator.ebus.find_registers = AsyncMock(return_value=["hmux0 Status01 = off"])
    coordinator.ebus.last_find_usable = True
    coordinator.ebus.read_register = AsyncMock()
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {
        "hmux0.FirstProbe": MagicMock(enabled=True, writable=False, fallback_read=True),
        "hmux0.SecondProbe": MagicMock(enabled=True, writable=False, fallback_read=True),
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
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        if ensure_active is not None:
            ensure_active()
        return ["grab started"] if command == "grab" else ["grab stopped"]

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


# Intent: read every ebusd grab-result line past the former 200-line cap.
# Why: the blank line terminates the TCP response; returning at an arbitrary count silently loses telegrams.
async def test_grab_cmd_reads_until_blank_line_after_more_than_200_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    expected = [f"telegram-{index}" for index in range(250)]
    reader.feed_data(("\n".join(expected) + "\n\n").encode())
    reader.feed_eof()
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    monkeypatch.setattr(DUMP.asyncio, "open_connection", AsyncMock(return_value=(reader, writer)))

    lines = await DUMP._grab_cmd("127.0.0.1", 8888, "grab result all")

    assert lines == expected
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


# Intent: allow an inter-line delay over two seconds when the complete response meets its total deadline.
# Why: a fixed per-line timeout can reject a valid, slowly streamed multi-line grab.
async def test_grab_cmd_allows_delayed_lines_within_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"first\n")

    # Intent: deliver the remaining lines after the former per-line timeout.
    # Why: this regression must distinguish a 30-second total deadline from a two-second line timeout.
    def _release_remaining_lines() -> None:
        reader.feed_data(b"second\n\n")
        reader.feed_eof()

    asyncio.get_running_loop().call_later(2.05, _release_remaining_lines)
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    monkeypatch.setattr(DUMP.asyncio, "open_connection", AsyncMock(return_value=(reader, writer)))

    assert await DUMP._grab_cmd("127.0.0.1", 8888, "grab result all") == ["first", "second"]


# Intent: retain grab ownership if unload begins on the response terminator before caller resumption.
# Why: the caller must record the start ACK before its lifecycle guard triggers global stop cleanup.
async def test_async_grab_stops_owned_capture_when_unload_follows_start_terminator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unloading = False
    start_line = 0
    start_reader = MagicMock()
    stop_reader = MagicMock()

    # Intent: flip unload exactly as the start response reaches its blank-line terminator.
    # Why: this was the gap between _grab_cmd's final lifecycle check and ownership assignment.
    async def _read_start_line() -> bytes:
        nonlocal start_line, unloading
        start_line += 1
        if start_line == 1:
            return b"grab started\n"
        unloading = True
        return b"\n"

    start_reader.readline = AsyncMock(side_effect=_read_start_line)
    stop_reader.readline = AsyncMock(side_effect=[b"grab stopped\n", b"\n"])
    writers = [MagicMock(), MagicMock()]
    for writer in writers:
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
    monkeypatch.setattr(
        DUMP.asyncio,
        "open_connection",
        AsyncMock(side_effect=[(start_reader, writers[0]), (stop_reader, writers[1])]),
    )

    # Intent: mirror the export's teardown guard.
    # Why: a teardown just after the start acknowledgement must still stop the owned grab.
    def _ensure_active() -> None:
        if unloading:
            raise HomeAssistantError("integration is unloading")

    with pytest.raises(HomeAssistantError, match="integration is unloading"):
        await DUMP.async_grab("127.0.0.1", 8888, 0, ensure_active=_ensure_active)

    assert writers[0].write.call_args.args == (b"grab\n",)
    assert writers[1].write.call_args.args == (b"grab stop\n",)


# Intent: stop an owned grab when cancellation interrupts socket cleanup after the start ACK.
# Why: the start response can be complete before `_grab_cmd` returns its result to the caller.
async def test_async_grab_cancellation_during_start_socket_cleanup_stops_owned_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_reader = asyncio.StreamReader()
    start_reader.feed_data(b"grab started\n\n")
    start_reader.feed_eof()
    stop_reader = asyncio.StreamReader()
    stop_reader.feed_data(b"grab stopped\n\n")
    stop_reader.feed_eof()
    start_close_started = asyncio.Event()
    wait_for_close = asyncio.Event()

    # Intent: hold the first TCP writer after its full response but before `_grab_cmd` returns.
    # Why: cancellation at this point must retain the ownership callback's state.
    async def _block_start_close() -> None:
        start_close_started.set()
        await wait_for_close.wait()

    writers = [MagicMock(), MagicMock()]
    for writer in writers:
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
    writers[0].wait_closed.side_effect = _block_start_close
    monkeypatch.setattr(
        DUMP.asyncio,
        "open_connection",
        AsyncMock(side_effect=[(start_reader, writers[0]), (stop_reader, writers[1])]),
    )

    task = asyncio.create_task(DUMP.async_grab("127.0.0.1", 8888, 0))
    await start_close_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert writers[0].write.call_args.args == (b"grab\n",)
    assert writers[1].write.call_args.args == (b"grab stop\n",)


# Intent: fail instead of returning a partial grab when the defensive line ceiling is exceeded.
# Why: an oversized result must remain visibly incomplete rather than pass as a complete discovery dump.
async def test_grab_cmd_fails_when_response_exceeds_line_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"line-1\nline-2\nline-3\n\n")
    reader.feed_eof()
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    monkeypatch.setattr(DUMP.asyncio, "open_connection", AsyncMock(return_value=(reader, writer)))
    monkeypatch.setattr(DUMP, "GRAB_MAX_RESPONSE_LINES", 2)

    with pytest.raises(HomeAssistantError, match="exceeded.*line limit"):
        await DUMP._grab_cmd("127.0.0.1", 8888, "grab result all")

    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


# Intent: classify a single over-limit TCP line as an incomplete capture response.
# Why: StreamReader.readline can raise ValueError before the total-line ceiling is reached.
async def test_grab_cmd_converts_oversized_single_line_to_capture_error(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = MagicMock()
    reader.readline = AsyncMock(side_effect=ValueError("line exceeds stream limit"))
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    monkeypatch.setattr(DUMP.asyncio, "open_connection", AsyncMock(return_value=(reader, writer)))

    with pytest.raises(HomeAssistantError, match="response line exceeded the stream limit"):
        await DUMP._grab_cmd("127.0.0.1", 8888, "grab result all")

    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


# Intent: treat EOF before the ebusd response terminator as incomplete data.
# Why: TCP closure is not the protocol's blank-line success terminator.
async def test_grab_cmd_fails_on_eof_before_response_terminator(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"partial telegram\n")
    reader.feed_eof()
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    monkeypatch.setattr(DUMP.asyncio, "open_connection", AsyncMock(return_value=(reader, writer)))

    with pytest.raises(ConnectionError, match="closed.*before.*terminator"):
        await DUMP._grab_cmd("127.0.0.1", 8888, "grab result all")

    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


# Intent: apply one overall deadline when ebusd never terminates a grab response.
# Why: a response that trickles lines indefinitely must not hang a dump request.
async def test_grab_cmd_fails_when_response_terminator_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    monkeypatch.setattr(DUMP.asyncio, "open_connection", AsyncMock(return_value=(reader, writer)))
    monkeypatch.setattr(DUMP, "GRAB_RESPONSE_TIMEOUT", 0.01)

    with pytest.raises(TimeoutError, match="before.*terminator"):
        await DUMP._grab_cmd("127.0.0.1", 8888, "grab result all")

    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


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
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        if command == "grab stop":
            stop_started.set()
            await allow_stop_to_fail.wait()
            raise OSError("stop connection failed")
        return ["grab started"]

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
@pytest.mark.parametrize("stop_response", [["grab stopped"], ["ERR: stop failed"], []])
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
    async def _fail_stop(host, port, command, ensure_active=None, on_grab_started=None):
        if command == "grab stop":
            raise OSError("stop connection failed")
        return ["grab started"] if command == "grab" else []

    monkeypatch.setattr(DUMP, "_grab_cmd", _fail_stop)

    with pytest.raises(DUMP.GrabIntervalUnavailableError, match="could not stop exporter-started"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)


# Intent: reject stop responses that do not confirm ebusd ended the grab.
# Why: error-shaped replies and closed connections can leave bus capture active.
@pytest.mark.parametrize("stop_response", [[], ["ERR: invalid command"]])
async def test_async_grab_rejects_unconfirmed_stop_response(
    stop_response: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Intent: return an empty/error response only for the cleanup command.
    # Why: a dump must not report successful capture when ebusd rejected grab stop.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        if command == "grab stop":
            return stop_response
        return ["grab started"] if command == "grab" else []

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

    # Intent: return an ERR reply at the selected stage and acknowledge owned cleanup.
    # Why: a failed start owns no global grab; result failure after a confirmed start must still stop it.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        if command == failed_command:
            return ["ERR: unavailable"]
        if command == "grab":
            return ["grab started"]
        if command == "grab stop":
            return ["grab stopped"]
        return []

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(HomeAssistantError, match=expected_error):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == (["grab"] if failed_command == "grab" else ["grab", "grab result all", "grab stop"])


# Intent: reject ebusd usage responses instead of serializing them as captured traffic.
# Why: valid query data can be empty, but a usage response means the command itself was rejected.
async def test_async_grab_rejects_result_usage_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        if command == "grab result all":
            return ["usage: grab result [all|decode]"]
        return ["grab started"] if command == "grab" else ["grab stopped"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(HomeAssistantError, match="grab result all failed: usage:"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)


# Intent: reject non-error grab-result text that is not a telegram record.
# Why: only parsed ebusd telegram output can be reported as a successful discovery capture.
@pytest.mark.parametrize("invalid_line", ["ok", "done", "grab not running", "invalid command"])
async def test_async_grab_rejects_arbitrary_result_text(invalid_line: str, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    # Intent: inject an arbitrary result line after a confirmed start.
    # Why: verify malformed success-shaped text does not bypass result validation.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        if command == "grab result all":
            return [invalid_line]
        return ["grab started"] if command == "grab" else ["grab stopped"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(HomeAssistantError, match="invalid telegram"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == ["grab", "grab result all", "grab stop"]


# Intent: retain valid raw hex telegram lines and an empty successful result.
# Why: both are legitimate grab-result responses under ebusd's TCP protocol.
@pytest.mark.parametrize(
    "result_lines",
    (
        [],
        ["f108b509055402008813 / 0e020188136400ffffffffffffffff = 1"],
    ),
)
async def test_async_grab_accepts_empty_or_valid_telegram_result(
    result_lines: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Intent: return the selected valid result shape with exact lifecycle acknowledgements.
    # Why: valid empty and raw-telegram results must both survive stricter validation.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        if command == "grab result all":
            return result_lines
        return ["grab started"] if command == "grab" else ["grab stopped"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    result = await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert result.lines == ("[grab] grab started", *result_lines, "[grab stop] grab stopped")
    assert result.status == "captured"


# Intent: abort when ebusd never acknowledges that raw capture started.
# Why: an unconfirmed start must not be reported as a successful empty capture.
async def test_async_grab_rejects_missing_start_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    # Intent: return no acknowledgement for grab.
    # Why: an unconfirmed global start must surface without stopping another capture.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        return [] if command == "grab" else ["grab stopped"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(HomeAssistantError, match="did not confirm that the grab started"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == ["grab"]


# Intent: derive only interval telegram counts when ebusd's global grab is already active.
# Why: current ebusd starts a daemon-wide grab automatically and must not be stopped by the export.
async def test_async_grab_diffs_existing_capture_without_stopping_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
    results = iter(
        [
            [
                "f108b509055402000d0a / 0802010d0a00000000 = 5: hmu RunDataCompressorSpeed",
                "10feb51603016019 / 00 = 7",
            ],
            [
                "f108b509055402000d0a / 0802010d0a00000001 = 8: hmu RunDataCompressorSpeed",
                "10feb51603016019 / 00 = 9",
                "10feb51603026019 / 00 = 2",
            ],
        ]
    )

    # Intent: provide cumulative ebusd snapshots around the requested interval.
    # Why: count deltas isolate new keys without mutating the global capture buffer.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        if command == "grab":
            return ["grab continued"]
        if command == "grab result all":
            return next(results)
        raise AssertionError(f"unexpected ebusd command: {command}")

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    capture = await DUMP.async_grab("127.0.0.1", 8888, 1)

    assert capture.status == "continued"
    assert capture.lines == (
        "[grab] grab continued",
        "f108b509055402000d0a / 0802010d0a00000001 = 3: hmu RunDataCompressorSpeed",
        "10feb51603016019 / 00 = 2",
        "10feb51603026019 / 00 = 2",
    )
    assert capture.duration >= 0.9
    assert commands == ["grab", "grab result all", "grab result all"]


# Intent: reject request or source-key changes that make a cumulative delta ambiguous.
# Why: known message labels and unknown raw IDs must not be merged under guessed keys.
@pytest.mark.parametrize(
    ("baseline", "final", "expected_commands"),
    [
        (
            [
                "f108b5240100 / 00 = 2: ctlv3 Z1OpMode",
                "f108b5240101 / 01 = 3: ctlv3 Z1OpMode",
            ],
            [
                "f108b5240100 / 00 = 4: ctlv3 Z1OpMode",
                "f108b5240102 / 02 = 2: ctlv3 Z1OpMode",
            ],
            ["grab", "grab result all", "grab result all"],
        ),
        (
            ["1008b5110100 / 09abcdef0000000000 = 2"],
            ["f108b5110100 / 09abcdef0000000000 = 3"],
            ["grab", "grab result all", "grab result all"],
        ),
        (
            ["1008b5240100 / 00 = 2: ctlv3 Z1OpMode"],
            ["f108b5240100 / 00 = 3: ctlv3 Z1OpMode"],
            ["grab", "grab result all", "grab result all"],
        ),
        (
            ["f108b5240100 / 00 = 2: ctlv3 Z1OpMode"],
            [],
            ["grab", "grab result all", "grab result all"],
        ),
        (
            ["f108b5240100 / 00 = 5: ctlv3 Z1OpMode"],
            ["f108b5240100 / 00 = 2: ctlv3 Z1OpMode"],
            ["grab", "grab result all", "grab result all"],
        ),
        (
            [
                "f108b5240100 / 00 = 2: ctlv3 Z1OpMode",
                "f108b5240100 / 01 = 3: ctlv3 Z1OpMode",
            ],
            ["f108b5240100 / 01 = 4: ctlv3 Z1OpMode"],
            ["grab", "grab result all", "grab result all"],
        ),
    ],
)
async def test_async_grab_fails_closed_when_interval_keys_are_ambiguous(
    baseline: list[str],
    final: list[str],
    expected_commands: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter([baseline, final])
    commands: list[str] = []

    # Intent: provide an unsafe before/after pair while preserving the global grab.
    # Why: identity changes, missing baseline rows, and counter resets cannot yield a reliable delta.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        return ["grab continued"] if command == "grab" else next(results)

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(DUMP.GrabIntervalUnavailableError):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == expected_commands


# Intent: report malformed and incomplete grab snapshots as safe register-only fallbacks.
# Why: optional raw capture failures must not discard the valid register snapshot already collected.
@pytest.mark.parametrize("failure_stage", ["baseline", "final", "oversized"])
async def test_async_grab_converts_snapshot_failures_to_interval_unavailable(
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
    result_calls = 0

    # Intent: simulate malformed rows, transport loss, and an oversized response.
    # Why: every unusable continued snapshot should be classified as unsafe.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        nonlocal result_calls
        commands.append(command)
        if command == "grab":
            return ["grab continued"]
        result_calls += 1
        if failure_stage == "baseline" and result_calls == 1:
            return ["not an ebusd telegram"]
        if failure_stage == "final" and result_calls == 2:
            return ["not an ebusd telegram"]
        if failure_stage == "oversized" and result_calls == 1:
            raise HomeAssistantError("ebusd grab result all response exceeded the line limit")
        return ["f108b5240100 / 00 = 2: ctlv3 Z1OpMode"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(DUMP.GrabIntervalUnavailableError):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    expected = (
        ["grab", "grab result all"]
        if failure_stage in {"baseline", "oversized"}
        else ["grab", "grab result all", "grab result all"]
    )
    assert commands == expected


# Intent: include baseline latency but exclude final-result latency from the reported interval.
# Why: metadata should track the capture interval, not time spent serializing snapshots.
async def test_async_grab_duration_covers_baseline_and_excludes_final_query(monkeypatch: pytest.MonkeyPatch) -> None:
    result_calls = 0

    # Intent: delay both snapshot responses around the measured interval.
    # Why: baseline latency belongs to capture duration, while final-query latency does not.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        nonlocal result_calls
        if command == "grab":
            return ["grab continued"]
        if command == "grab result all":
            result_calls += 1
            await asyncio.sleep(0.4)
            return ["f108b5240100 / 00 = 2: ctlv3 Z1OpMode"]
        raise AssertionError(f"unexpected ebusd command: {command}")

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)
    wall_started = asyncio.get_running_loop().time()
    capture = await DUMP.async_grab("127.0.0.1", 8888, 1)
    wall_duration = asyncio.get_running_loop().time() - wall_started

    assert result_calls == 2
    assert capture.duration >= 0.9
    assert capture.duration < 1.2
    assert wall_duration >= 1.3
    assert wall_duration < 1.8


# Intent: start the owned-session timer as soon as ebusd sends its start ACK.
# Why: socket terminator latency must not shorten the requested capture interval.
async def test_owned_grab_duration_starts_at_ack_before_response_terminator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Intent: delay the owned start response after its acknowledgement callback.
    # Why: the interval must begin when ebusd sends the ACK, not at the blank terminator.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        if command == "grab":
            assert on_grab_started is not None
            on_grab_started()
            await asyncio.sleep(0.3)
            return ["grab started"]
        if command == "grab result all":
            return ["f108b5240100 / 00 = 2: ctlv3 Z1OpMode"]
        if command == "grab stop":
            return ["grab stopped"]
        raise AssertionError(f"unexpected ebusd command: {command}")

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)
    wall_started = asyncio.get_running_loop().time()
    capture = await DUMP.async_grab("127.0.0.1", 8888, 1)
    wall_duration = asyncio.get_running_loop().time() - wall_started

    assert capture.status == "captured"
    assert capture.duration >= 0.9
    assert capture.duration < 1.2
    assert wall_duration < 1.2


# Intent: pair one-row broadcast families by effective ID despite request-length variation.
# Why: ebusd's broadcast key uses only the first master-data byte, not raw NN.
def test_unknown_broadcast_length_change_uses_effective_id() -> None:
    baseline = DUMP._validate_grab_result_response(["10feb51603016019 / 00 = 5"])
    final = DUMP._validate_grab_result_response(["10feb5160401602021 / 00 = 8"])

    assert DUMP._grab_result_delta(baseline, final) == ["10feb5160401602021 / 00 = 3"]


# Intent: pair one-row slave families by the effective four-byte ID despite trailing data changes.
# Why: ebusd's generic slave-message key ignores master bytes after the first four ID bytes.
def test_unknown_slave_length_change_uses_effective_id() -> None:
    baseline = DUMP._validate_grab_result_response(["1008b511050102030405 / 00 = 4"])
    final = DUMP._validate_grab_result_response(["1008b51106010203040607 / 01 = 7"])

    assert DUMP._grab_result_delta(baseline, final) == ["1008b51106010203040607 / 01 = 3"]


# Intent: pair one-row known message families when their request payload changes.
# Why: the retained global key persists while its latest request/response payload is replaced.
def test_known_single_row_family_uses_count_delta_across_payload_change() -> None:
    baseline = DUMP._validate_grab_result_response(["f108b5240100 / 00 = 2: ctlv3 Z1OpMode"])
    final = DUMP._validate_grab_result_response(["f108b5240101 / 01 = 4: ctlv3 Z1OpMode"])

    assert DUMP._grab_result_delta(baseline, final) == ["f108b5240101 / 01 = 2: ctlv3 Z1OpMode"]


# Intent: retain separate ebusd result rows that share one unknown ID prefix.
# Why: configured messages can use longer IDs than the generic unknown-message key.
def test_grab_delta_matches_distinct_unknown_rows_with_shared_id_prefix() -> None:
    baseline = DUMP._validate_grab_result_response(
        [
            "3108b516081001ffff02054135 / 0b0100050205413500000000 = 5",
            "3108b516081001ffff02053e35 / 0b01000502053e3500000000 = 4",
        ]
    )
    final = DUMP._validate_grab_result_response(
        [
            "3108b516081001ffff02054135 / 0b0100050205413500000000 = 6",
            "3108b516081001ffff02053e35 / 0b01000502053e3500000000 = 7",
        ]
    )

    assert DUMP._grab_result_delta(baseline, final) == [
        "3108b516081001ffff02054135 / 0b0100050205413500000000 = 1",
        "3108b516081001ffff02053e35 / 0b01000502053e3500000000 = 3",
    ]


# Intent: include a new final request variant only when prior rows in its family remain stable.
# Why: ebusd can retain separate hidden message keys under one visible unknown ID prefix.
def test_grab_delta_includes_new_row_in_stable_multi_row_family() -> None:
    baseline = DUMP._validate_grab_result_response(
        [
            "3108b516081001ffff02054135 / 0b0100050205413500000000 = 5",
            "3108b516081001ffff02053e35 / 0b01000502053e3500000000 = 4",
        ]
    )
    final = DUMP._validate_grab_result_response(
        [
            "3108b516081001ffff02054135 / 0b0100050205413500000000 = 7",
            "3108b516081001ffff02053e35 / 0b01000502053e3500000000 = 5",
            "3108b516081001ffff02053d35 / 0b01000502053d3500000000 = 2",
        ]
    )

    assert DUMP._grab_result_delta(baseline, final) == [
        "3108b516081001ffff02054135 / 0b0100050205413500000000 = 2",
        "3108b516081001ffff02053e35 / 0b01000502053e3500000000 = 1",
        "3108b516081001ffff02053d35 / 0b01000502053d3500000000 = 2",
    ]


# Intent: reject label changes in a multi-row known-message family.
# Why: the label is part of the visible row signature used when ebusd hides its internal key.
def test_grab_delta_fails_when_multi_row_label_changes() -> None:
    baseline = DUMP._validate_grab_result_response(
        [
            "f108b5240100 / 00 = 5: ctlv3 Z1OpMode",
            "f108b5240101 / 01 = 4: ctlv3 Z1OpMode",
        ]
    )
    final = DUMP._validate_grab_result_response(
        [
            "f108b5240100 / 00 = 7: ctlv3 Z1OpMode",
            "f108b5240101 / 01 = 6: ctlv3 z1opmode",
        ]
    )

    with pytest.raises(DUMP.GrabIntervalUnavailableError, match="row changed"):
        DUMP._grab_result_delta(baseline, final)


# Intent: verify that a new final-only message family contributes its cumulative count.
# Why: ebusd stores new message keys in the shared auto-grab result without clearing the baseline.
def test_grab_delta_includes_final_only_family() -> None:
    baseline = DUMP._validate_grab_result_response(["f108b5240100 / 00 = 7: ctlv3 Z1OpMode"])
    final = DUMP._validate_grab_result_response(
        [
            "f108b5240100 / 00 = 7: ctlv3 Z1OpMode",
            "f108b5240101 / 01 = 3: ctlv3 Z1DhwOpMode",
        ]
    )

    assert DUMP._grab_result_delta(baseline, final) == [
        "f108b5240101 / 01 = 3: ctlv3 Z1DhwOpMode",
    ]


# Intent: retain known message variants with the same header and label when their requests stay stable.
# Why: ebusd can store multiple message definitions under one visible circuit/name family.
def test_grab_delta_matches_known_variants_by_stable_request() -> None:
    baseline = DUMP._validate_grab_result_response(
        [
            "10feb516080037560802100526 = 5: Broadcast Vdatetime",
            "10feb516080016551428090126 = 2: Broadcast Vdatetime",
        ]
    )
    final = DUMP._validate_grab_result_response(
        [
            "10feb516080037560802100526 = 6: Broadcast Vdatetime",
            "10feb516080016551428090126 = 4: Broadcast Vdatetime",
        ]
    )

    assert DUMP._grab_result_delta(baseline, final) == [
        "10feb516080037560802100526 = 1: Broadcast Vdatetime",
        "10feb516080016551428090126 = 2: Broadcast Vdatetime",
    ]


# Intent: expose the global grab reset/refill case that count snapshots cannot distinguish.
# Why: the dump metadata must state this upstream limitation instead of claiming exact isolation.
def test_grab_delta_documents_unobservable_external_reset_refill() -> None:
    baseline = DUMP._validate_grab_result_response(["f108b5240100 / 00 = 7: ctlv3 Z1OpMode"])
    final = DUMP._validate_grab_result_response(["f108b5240100 / 01 = 10: ctlv3 Z1OpMode"])

    assert DUMP._grab_result_delta(baseline, final) == ["f108b5240100 / 01 = 3: ctlv3 Z1OpMode"]
    assert "no grab epoch" in DUMP.GRAB_COUNT_DELTA_LIMITATION
    assert "cannot be detected" in DUMP.GRAB_COUNT_DELTA_LIMITATION


# Intent: sum per-key counts when ebusd emits identical visible duplicate rows.
# Why: each received telegram updates one internal key even when output rows look identical.
def test_grab_delta_sums_identical_visible_rows() -> None:
    baseline = DUMP._validate_grab_result_response(
        [
            "f115b503020001 / 0affffffffffffffffffff = 1: ctlv2 Currenterror",
            "f115b503020001 / 0affffffffffffffffffff = 5340: ctlv2 Currenterror",
        ]
    )
    final = DUMP._validate_grab_result_response(
        [
            "f115b503020001 / 0affffffffffffffffffff = 1: ctlv2 Currenterror",
            "f115b503020001 / 0affffffffffffffffffff = 3: ctlv2 Currenterror",
            "f115b503020001 / 0affffffffffffffffffff = 5342: ctlv2 Currenterror",
        ]
    )

    assert DUMP._grab_result_delta(baseline, final) == [
        "f115b503020001 / 0affffffffffffffffffff = 5: ctlv2 Currenterror"
    ]


# Intent: enforce the supported decimal counter width without rejecting the boundary value.
# Why: ebusd counters must stay parseable and oversized input must fall back safely.
def test_grab_result_count_length_boundary() -> None:
    valid = DUMP._validate_grab_result_response([f"f108b5240100 / 00 = {'9' * 20}: ctlv3 Z1OpMode"])

    assert valid[0].count == int("9" * 20)
    with pytest.raises(HomeAssistantError, match="invalid telegram"):
        DUMP._validate_grab_result_response([f"f108b5240100 / 00 = {'9' * 21}: ctlv3 Z1OpMode"])


# Intent: reject a result snapshot after ebusd stopped global grabbing.
# Why: `grab disabled` is not an empty but valid capture result.
async def test_async_grab_rejects_disabled_continued_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    # Intent: simulate another client stopping the global grab between snapshots.
    # Why: the continued export must not claim traffic after ebusd cleared its buffer.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        return ["grab continued"] if command == "grab" else ["grab disabled"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(DUMP.GrabIntervalUnavailableError, match="disabled"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == ["grab", "grab result all"]


# Intent: keep continued-capture cancellation from stopping ebusd's global grab.
# Why: a canceled service owns no daemon-wide capture when ebusd reports `grab continued`.
async def test_async_grab_cancellation_does_not_stop_continued_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
    waiting = asyncio.Event()

    # Intent: block after the baseline snapshot until the test cancels the caller.
    # Why: cancellation must preserve the always-on ebusd grab.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        return ["grab continued"] if command == "grab" else []

    # Intent: expose the capture wait so cancellation occurs inside the interval.
    # Why: this is the lifecycle boundary that could otherwise trigger grab cleanup.
    async def _blocked_sleep(seconds: float) -> None:
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)
    monkeypatch.setattr(DUMP.asyncio, "sleep", _blocked_sleep)
    task = asyncio.create_task(DUMP.async_grab("127.0.0.1", 8888, 30))
    await asyncio.wait_for(waiting.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert commands == ["grab", "grab result all"]


# Intent: write a register-only snapshot when continued-grab counts cannot be isolated.
# Why: raw data must not be presented as interval capture after ebusd clears its shared buffer.
async def test_export_dump_falls_back_when_continued_grab_delta_is_unsafe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ha_components.persistent_notification.create.reset_mock()
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    # Intent: execute the persistence worker inline for this export test.
    # Why: assertions inspect the completed YAML before returning.
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator.ebus.version = "26.1"
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator.ebus.get_info = AsyncMock(return_value={"version": "26.1"})
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    commands: list[str] = []
    snapshots = iter(
        [
            ["f108b5240100 / 00 = 5: ctlv3 Z1OpMode"],
            ["f108b5240100 / 00 = 2: ctlv3 Z1OpMode"],
        ]
    )

    # Intent: feed a cumulative-counter reset through the real exporter capture flow.
    # Why: the saved YAML must mark raw data unavailable while retaining registers.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        return ["grab continued"] if command == "grab" else next(snapshots)

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)
    monkeypatch.setattr(DUMP, "REGISTER_MAP", {})

    await DUMP.async_export_discovery_dump(hass, coordinator, grab_duration=0.01)

    dump_path = next(tmp_path.glob("discovery_dump_*.yaml"))
    dump_data = DUMP.yaml.safe_load(dump_path.read_text())
    assert dump_data["metadata"]["grab_duration"] == 0.01
    assert dump_data["metadata"]["grab_status"] == "skipped_active"
    assert dump_data["metadata"]["grab_captured_duration"] == 0
    assert dump_data["metadata"]["grab_capture_method"] == "count_delta"
    assert "counter decreased" in dump_data["metadata"]["grab_error"]
    assert "grab" not in dump_data
    assert {"metadata", "raw_find_lines", "before_registers", "registers"} <= dump_data.keys()
    assert commands == ["grab", "grab result all", "grab result all"]
    notification = _ha_components.persistent_notification.create.call_args.args[1]
    assert "raw ebus capture could not be isolated" in notification.casefold()


# Intent: record a continued global capture as a count-delta interval in the dump metadata.
# Why: users need to distinguish a daemon-owned grab from a service-owned capture.
async def test_export_dump_records_continued_capture_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ha_components.persistent_notification.create.reset_mock()
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    # Intent: execute the persistence worker inline for this export test.
    # Why: assertions inspect the completed YAML before returning.
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator.ebus.version = "26.1.8"
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator.ebus.get_info = AsyncMock(return_value={"version": "26.1.8"})
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    monkeypatch.setattr(
        DUMP,
        "async_grab",
        AsyncMock(
            return_value=DUMP.GrabCaptureResult(
                lines=("[grab] grab continued", "10feb51603016019 / 00 = 2"),
                status="continued",
                duration=1.25,
            )
        ),
    )
    monkeypatch.setattr(DUMP, "REGISTER_MAP", {})

    await DUMP.async_export_discovery_dump(hass, coordinator, grab_duration=1)

    dump_path = next(tmp_path.glob("discovery_dump_*.yaml"))
    dump_data = DUMP.yaml.safe_load(dump_path.read_text())
    metadata = dump_data["metadata"]
    assert metadata["grab_duration"] == 1
    assert metadata["grab_status"] == "continued"
    assert metadata["grab_captured_duration"] == 1.25
    assert metadata["grab_capture_method"] == "count_delta"
    assert "no grab epoch" in metadata["grab_capture_limitation"]
    assert dump_data["grab"] == ["[grab] grab continued", "10feb51603016019 / 00 = 2"]


# Intent: mark zero-second exports as having no raw capture requested or captured.
# Why: the live release smoke test must distinguish a register dump from a traffic capture.
async def test_export_dump_marks_zero_second_capture_as_not_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    # Intent: execute the persistence worker inline for this export test.
    # Why: assertions inspect the completed YAML before returning.
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator.ebus.version = "26.1"
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator.ebus.get_info = AsyncMock(return_value={"version": "26.1"})
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    async_grab = AsyncMock()
    monkeypatch.setattr(DUMP, "async_grab", async_grab)
    monkeypatch.setattr(DUMP, "REGISTER_MAP", {})

    await DUMP.async_export_discovery_dump(hass, coordinator, grab_duration=0)

    dump_path = next(tmp_path.glob("discovery_dump_*.yaml"))
    metadata = DUMP.yaml.safe_load(dump_path.read_text())["metadata"]
    assert metadata["grab_duration"] == 0
    assert metadata["grab_status"] == "not_requested"
    assert metadata["grab_captured_duration"] == 0
    assert metadata["grab_capture_method"] == "none"
    assert "grab_error" not in metadata
    async_grab.assert_not_awaited()


# Intent: fall back to register-only data after result retrieval fails, then clean an acknowledged owned grab.
# Why: raw capture is optional, but an exporter-started global session still needs cleanup.
async def test_async_grab_transport_failure_still_stops_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    # Intent: fail result retrieval while allowing the cleanup command to succeed.
    # Why: the service should save registers after the raw interval becomes unavailable.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        if command == "grab result all":
            raise ConnectionError("grab transport failed")
        return ["grab started"] if command == "grab" else ["grab stopped"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(DUMP.GrabIntervalUnavailableError, match="grab transport failed"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == ["grab", "grab result all", "grab stop"]


# Intent: accept only ebusd's explicit grab lifecycle acknowledgements while allowing an empty result.
# Why: capture output is data, so a non-error but invalid command reply must not be reported as success.
async def test_async_grab_accepts_exact_acknowledgements_and_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        return {
            "grab": ["grab started"],
            "grab result all": [],
            "grab stop": ["grab stopped"],
        }[command]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    capture = await DUMP.async_grab("127.0.0.1", 8888, 0)
    assert capture.lines == ("[grab] grab started", "[grab stop] grab stopped")
    assert capture.status == "captured"
    assert commands == ["grab", "grab result all", "grab stop"]


# Intent: reject non-error text that is not ebusd's start/stop acknowledgement.
# Why: a usage or invalid-state reply must not look like a completed capture.
@pytest.mark.parametrize(
    ("failed_command", "failure_reply"),
    [
        ("grab", "ok"),
        ("grab", "done"),
        ("grab", "grab not running"),
        ("grab stop", "ok"),
        ("grab stop", "done"),
        ("grab stop", "grab not running"),
    ],
)
async def test_async_grab_rejects_unexpected_lifecycle_acknowledgements(
    failed_command: str,
    failure_reply: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []

    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        if command == failed_command:
            return [failure_reply]
        if command == "grab":
            return ["grab started"]
        if command == "grab stop":
            return ["grab stopped"]
        return []

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(HomeAssistantError, match="confirm|acknowledge"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    if failed_command == "grab":
        assert commands == ["grab"]
    else:
        assert commands == ["grab", "grab result all", "grab stop"]


# Intent: reject extra response lines after a grab lifecycle acknowledgement.
# Why: only a single exact acknowledgement proves this export owns the global grab state.
@pytest.mark.parametrize(
    ("failed_command", "reply"),
    [
        ("grab", ["grab started", "unexpected"]),
        ("grab stop", ["grab stopped", "unexpected"]),
    ],
)
async def test_async_grab_rejects_extra_lifecycle_response_lines(
    failed_command: str,
    reply: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []

    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        if command == failed_command:
            return reply
        if command == "grab":
            return ["grab started"]
        if command == "grab stop":
            return ["grab stopped"]
        return []

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(HomeAssistantError, match="confirm"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == (["grab"] if failed_command == "grab" else ["grab", "grab result all", "grab stop"])


# Intent: save a register-only dump when grab startup or a continued snapshot fails.
# Why: raw capture is optional, and an unowned stop could disable another client's global grab.
@pytest.mark.parametrize("failure_stage", ["start", "baseline", "final", "baseline_count", "baseline_line"])
async def test_export_dump_falls_back_when_capture_transport_fails(
    failure_stage: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ha_components.persistent_notification.create.reset_mock()
    hass = MagicMock()
    hass.config.path.return_value = str(tmp_path)
    # Intent: execute the persistence worker inline for this export test.
    # Why: assertions inspect the completed YAML before returning.
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    coordinator = _coordinator(str(tmp_path))
    coordinator.ebus = MagicMock()
    coordinator.ebus.is_connected = True
    coordinator.ebus.version = "26.1"
    coordinator.ebus.find_registers = AsyncMock(return_value=[])
    coordinator.ebus.get_info = AsyncMock(return_value={"version": "26.1"})
    coordinator._ebusd_connected = True
    coordinator._graph = tc.DeviceGraph(
        nodes={"hmux0": tc.DeviceNode("hmux0", tc.DeviceType.HEAT_PUMP, has_data=True)},
        raw_registers={},
        placeholder_registers=set(),
    )
    commands: list[str] = []
    result_calls = 0

    # Intent: fail start or snapshot transport at the selected point in the flow.
    # Why: prove each optional raw-capture failure persists register-only output.
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        nonlocal result_calls
        commands.append(command)
        if command == "grab":
            if failure_stage == "start":
                raise ConnectionError("start acknowledgement lost")
            return ["grab continued"]
        result_calls += 1
        if failure_stage == "baseline" and result_calls == 1:
            raise ConnectionError("baseline transport failed")
        if failure_stage == "baseline_count" and result_calls == 1:
            return [f"f108b5240100 / 00 = {'9' * 4301}: ctlv3 Z1OpMode"]
        if failure_stage == "baseline_line" and result_calls == 1:
            raise HomeAssistantError("ebusd grab result all response line exceeded the stream limit")
        if failure_stage == "final" and result_calls == 2:
            raise ConnectionError("final transport failed")
        return ["f108b5240100 / 00 = 2: ctlv3 Z1OpMode"]

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)
    monkeypatch.setattr(DUMP, "REGISTER_MAP", {})

    await DUMP.async_export_discovery_dump(hass, coordinator, grab_duration=1)

    dump_path = next(tmp_path.glob("discovery_dump_*.yaml"))
    dump_data = DUMP.yaml.safe_load(dump_path.read_text())
    expected_status = "unavailable" if failure_stage == "start" else "skipped_active"
    expected_method = "none" if failure_stage == "start" else "count_delta"
    expected_error = {
        "start": "start acknowledgement lost",
        "baseline": "baseline transport failed",
        "final": "final transport failed",
        "baseline_count": "invalid telegram",
        "baseline_line": "response line exceeded the stream limit",
    }[failure_stage]
    assert dump_data["metadata"]["grab_status"] == expected_status
    assert dump_data["metadata"]["grab_capture_method"] == expected_method
    assert expected_error in dump_data["metadata"]["grab_error"]
    if failure_stage != "start":
        assert "grab_capture_limitation" in dump_data["metadata"]
    assert "grab" not in dump_data
    expected_commands = (
        ["grab"]
        if failure_stage == "start"
        else [
            "grab",
            "grab result all",
        ]
    )
    if failure_stage == "final":
        expected_commands.append("grab result all")
    assert commands == expected_commands
    _ha_components.persistent_notification.create.assert_called_once()


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
    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        if command == "grab":
            capture_started.set()
        if command == "grab stop":
            stop_started.set()
            await allow_stop_to_finish.wait()
        if ensure_active is not None:
            ensure_active()
        return ["grab started"] if command == "grab" else ["grab stopped"]

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


# Intent: do not stop a grab when the start command's transport result is ambiguous.
# Why: grab state is global, so stopping without an acknowledgement can cancel another capture.
async def test_async_grab_does_not_stop_after_ambiguous_start_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    async def _grab_cmd(host, port, command, ensure_active=None, on_grab_started=None):
        commands.append(command)
        raise ConnectionError("start acknowledgement lost")

    monkeypatch.setattr(DUMP, "_grab_cmd", _grab_cmd)

    with pytest.raises(DUMP.GrabIntervalUnavailableError, match="start acknowledgement lost"):
        await DUMP.async_grab("127.0.0.1", 8888, 0)

    assert commands == ["grab"]


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
    ebus.last_find_usable = True
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


# Intent: an unusable current find retains diagnostic rows but prevents active map probes.
# Why: stale discovery or no-data scan rows must not authorize active map probes.
@pytest.mark.parametrize("raw_line", ["ERR: no usable find result", "scan.08 = no data stored"])
async def test_dump_registers_skip_active_map_reads_after_unusable_find(raw_line: str) -> None:
    ebus = MagicMock()
    ebus.find_registers = AsyncMock(return_value=[raw_line])
    ebus.last_find_usable = False
    ebus.read_register = AsyncMock(return_value="8.0")
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {"hmu.RunDataElPowerConsumption": MagicMock(enabled=True, writable=False, fallback_read=True)}
    try:
        registers, _, raw_lines = await DUMP._dump_registers(ebus, circuit_aliases={"hmu": "hmux0"})
    finally:
        DUMP.REGISTER_MAP = original_map

    assert raw_lines == [raw_line]
    assert len(registers) == 1
    assert registers[0]["circuit"] == "hmux0"
    assert registers[0]["name"] == "RunDataElPowerConsumption"
    assert registers[0]["from_map"] is True
    assert registers[0]["values"] == [None]
    ebus.read_register.assert_not_awaited()


# Intent: raw discovery dumps omit field-shaped pseudo-registers.
# Why: each field is part of its parent telegram and must not appear as a bus register.
def test_dump_find_parser_skips_field_shaped_keys() -> None:
    registers = DUMP._parse_find_lines(
        ["hmu Status01 = 20;on", "hmu Status01.temp = 20", "hmu Status01.pumpstate = on"]
    )

    assert [register["key"] for register in registers] == ["hmu.Status01"]


# Intent: HMUX0 SW0407 map probes skip the exact unsafe set in discovery dumps while daily B516 reads remain enabled.
# Why: dump exports must apply the same hardware-scoped fallback safety as coordinator polling.
async def test_dump_registers_skip_issue161_hmux0_fallback_set() -> None:
    fixture = "community/hmux0_issue161_2026-09-28_154109_discovery.yaml"
    graph = tc.DISCOVERY.DiscoveryService.build_device_graph(tc.load_find_lines(fixture, after=True))
    expected_names = {
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
    skip_reads = DUMP._fallback_read_skip_keys(
        graph,
        [
            "u,hmux0,RunDataElPowerConsumption",
            "u,vwzio,PowerConsumptionVwz",
            "r5,ctlv2,z1RoomHumidity",
            "wi,bai,HeatingSwitch",
        ],
    )
    skip_without_definitions = DUMP._fallback_read_skip_keys(graph, [])
    assert {("hmux0", name.casefold()) for name in expected_names} <= skip_reads
    assert ("hmux0", "rundataelpowerconsumption") in skip_reads
    assert ("vwzio", "powerconsumptionvwz") in skip_reads
    assert ("vwzio", "status01") in skip_reads
    assert ("ctlv2", "z1roomhumidity") not in skip_reads
    assert ("bai", "heatingswitch") not in skip_reads
    assert ("hmux0", "rundataelpowerconsumption") in skip_without_definitions
    assert ("vwzio", "powerconsumptionvwz") in skip_without_definitions

    ebus = MagicMock()
    ebus.find_registers = AsyncMock(return_value=[])
    ebus.read_register = AsyncMock(return_value=None)
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {
        **{f"hmux0.{name}": MagicMock(enabled=True, writable=False, fallback_read=True) for name in expected_names},
        "hmux0.HcElecConsDay": MagicMock(enabled=True, writable=False, fallback_read=True),
        "hmux0.HwcElecConsDay": MagicMock(enabled=True, writable=False, fallback_read=True),
        "vwzio.Status01": MagicMock(enabled=True, writable=False, fallback_read=True),
        "vwzio.PowerConsumptionVwz": MagicMock(enabled=True, writable=False, fallback_read=True),
    }
    try:
        await DUMP._dump_registers(
            ebus,
            circuit_aliases={"hmux0": "hmux0"},
            skip_fallback_reads=skip_reads,
        )
    finally:
        DUMP.REGISTER_MAP = original_map

    calls = [call.args[:2] for call in ebus.read_register.await_args_list]
    assert not any(circuit.casefold() == "hmux0" and name in expected_names for circuit, name in calls)
    assert ("hmux0", "HcElecConsDay") in calls
    assert ("hmux0", "HwcElecConsDay") in calls
    assert ("vwzio", "Status01") not in calls
    assert ("vwzio", "PowerConsumptionVwz") not in calls

    other_graph = tc.DISCOVERY.DiscoveryService.build_device_graph(
        tc.load_find_lines("community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml", after=True)
    )
    other_skip_reads = DUMP._fallback_read_skip_keys(other_graph, [])
    assert not {("hmux0", name.casefold()) for name in expected_names} & other_skip_reads


# Intent: dump export does not actively probe the passive HW0504 HWC counter if ebusd rejects its definition.
# Why: the mapped parent must remain passive even when no runtime definition is available to build a skip list.
async def test_dump_registers_skip_issue161_vwzio_hwc_counter_without_definition() -> None:
    fixture = "community/hmux0_issue161_2026-09-28_154109_discovery.yaml"
    graph = tc.DISCOVERY.DiscoveryService.build_device_graph(tc.load_find_lines(fixture, after=True))
    assert graph.nodes["vwzio"].scan_sw == "0500"
    assert graph.nodes["vwzio"].scan_hw == "0504"

    ebus = MagicMock()
    ebus.find_registers = AsyncMock(return_value=[])
    ebus.read_register = AsyncMock(return_value=None)
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {
        "vwzio.RunStatsImmersionHeaterHwc": MagicMock(enabled=False, writable=False, fallback_read=False)
    }
    try:
        registers, _, _ = await DUMP._dump_registers(ebus, circuit_aliases={"vwzio": "vwzio"})
    finally:
        DUMP.REGISTER_MAP = original_map

    assert registers == [
        {
            "circuit": "vwzio",
            "name": "RunStatsImmersionHeaterHwc",
            "fields": ["value"],
            "values": [None],
            "writable": False,
            "has_data": False,
            "from_map": True,
            "disabled": True,
        }
    ]
    ebus.read_register.assert_not_awaited()


# Intent: dump fallback reads Status01 only from the station currently scanned at 0x76.
# Why: an alias that resolves to a VWZIO at 0x77 must not probe slave 0x76 through stale metadata.
async def test_dump_status01_fallback_respects_current_station_address() -> None:
    wrong_address_graph = tc.DISCOVERY.DiscoveryService.build_device_graph(
        [
            "scan.76 = MF=Vaillant;ID=VWZ00;SW=0522;HW=5103",
            "scan.77 = MF=Vaillant;ID=VWZIO;SW=0500;HW=0504",
            "vwz Status01 = no data stored",
            "vwzio Status01 = no data stored",
        ]
    )
    correct_address_graph = tc.DISCOVERY.DiscoveryService.build_device_graph(
        [
            "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
            "scan.50 = MF=Vaillant;ID=CTLV2;SW=0514;HW=1104",
            "scan.50 = MF=Vaillant;ID=CTLV2;SW=0515;HW=1104",
            "scan.51 = MF=Vaillant;ID=CTLV2;SW=;HW=",
            "vwzio Status01 = no data stored",
        ]
    )
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {
        "vwz.Status01": MagicMock(enabled=True, writable=False, fallback_read=True),
        "vwzio.Status01": MagicMock(enabled=True, writable=False, fallback_read=True),
        "vwzio.RunStatsImmersionHeaterHwc": MagicMock(enabled=True, writable=False, fallback_read=True),
    }
    try:
        wrong_ebus = MagicMock()
        wrong_ebus.find_registers = AsyncMock(
            return_value=[
                "scan.76 = MF=Vaillant;ID=VWZ00;SW=0522;HW=5103",
                "scan.77 = MF=Vaillant;ID=VWZIO;SW=0500;HW=0504",
                "vwz Other = live",
                "vwzio Other = live",
            ]
        )
        wrong_ebus.read_register = AsyncMock(return_value=None)
        wrong_skips = DUMP._fallback_read_skip_keys(wrong_address_graph, [])
        await DUMP._dump_registers(
            wrong_ebus,
            circuit_aliases={"vwz": "vwz", "vwzio": "vwzio"},
            skip_fallback_reads=wrong_skips,
        )

        correct_ebus = MagicMock()
        correct_ebus.find_registers = AsyncMock(
            return_value=[
                "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
                "vwzio Other = live",
            ]
        )
        correct_ebus.read_register = AsyncMock(return_value=None)
        correct_skips = DUMP._fallback_read_skip_keys(correct_address_graph, [])
        await DUMP._dump_registers(
            correct_ebus,
            circuit_aliases={"vwzio": "vwzio"},
            skip_fallback_reads=correct_skips,
        )
    finally:
        DUMP.REGISTER_MAP = original_map

    wrong_calls = [call.args[:2] for call in wrong_ebus.read_register.await_args_list]
    assert ("vwzio", "Status01") not in wrong_calls
    assert ("vwzio", "RunStatsImmersionHeaterHwc") not in wrong_calls
    assert ("vwz", "Status01") in wrong_calls
    correct_calls = [call.args[:2] for call in correct_ebus.read_register.await_args_list]
    assert ("vwzio", "Status01") in correct_calls
    assert ("vwzio", "RunStatsImmersionHeaterHwc") not in correct_calls

    partial_address_graph = tc.DISCOVERY.DiscoveryService.build_device_graph(
        [
            "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
            "vwzio Status01 = no data stored",
        ]
    )
    assert DUMP.vwz_station_scan_76_circuit(partial_address_graph) == "vwzio"
    partial_ebus = MagicMock()
    partial_ebus.find_registers = AsyncMock(
        return_value=[
            "scan.76 = MF=Vaillant;ID=VWZIO;SW=0901;HW=5103",
            "scan.76 = MF=Vaillant;ID=VWZ00;SW=;HW",
            "vwzio Other = live",
        ]
    )
    partial_ebus.read_register = AsyncMock(return_value=None)
    partial_skips = DUMP._fallback_read_skip_keys(partial_address_graph, [])
    await DUMP._dump_registers(
        partial_ebus,
        circuit_aliases={"vwzio": "vwzio"},
        skip_fallback_reads=partial_skips,
        current_graph=partial_address_graph,
        runtime_definitions=[],
    )
    assert DUMP.vwz_station_scan_76_circuit(partial_address_graph) == "vwzio"
    assert ("vwzio", "Status01") not in [call.args[:2] for call in partial_ebus.read_register.await_args_list]


# Intent: map aliases in a dump resolve against the current find rather than stale coordinator nodes.
# Why: an old controller circuit must not receive fallback probes after a different controller is discovered.
async def test_dump_fallback_alias_uses_current_controller_circuit() -> None:
    stale_graph = tc.DISCOVERY.DiscoveryService.build_device_graph(
        ["scan.15 = MF=Vaillant;ID=CTLV2;SW=0514;HW=1104", "ctlv2 Z1OpMode = auto"]
    )
    current_find = ["scan.15 = MF=Vaillant;ID=CTLV3;SW=0808;HW=8004", "ctlv3 Z1OpMode = auto"]
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {
        "ctlv2.Hc1FlowTempCalc": MagicMock(enabled=True, writable=False, fallback_read=True),
    }
    ebus = MagicMock()
    ebus.find_registers = AsyncMock(return_value=current_find)
    ebus.read_register = AsyncMock(return_value=None)
    try:
        await DUMP._dump_registers(
            ebus,
            circuit_aliases={"ctlv2": "ctlv2"},
            current_graph=stale_graph,
            runtime_definitions=[],
        )
    finally:
        DUMP.REGISTER_MAP = original_map

    calls = [call.args[:2] for call in ebus.read_register.await_args_list]
    assert ("ctlv3", "Hc1FlowTempCalc") in calls
    assert ("ctlv2", "Hc1FlowTempCalc") not in calls


# Intent: hardware-specific dump blocklists use the firmware in the current raw find.
# Why: an old coordinator graph must not authorize a fallback prohibited by a newly discovered variant.
async def test_dump_hmux0_blocklist_uses_current_scan_firmware() -> None:
    stale_graph = tc.DISCOVERY.DiscoveryService.build_device_graph(
        ["scan.08 = MF=Vaillant;ID=HMUX0;SW=0303;HW=0504", "hmux0 Status01 = no data stored"]
    )
    assert tc.MAPPING.hmux0_sw0407_circuit(stale_graph) is None
    current_find = [
        "scan.08 = MF=Vaillant;ID=HMUX0;SW=0407;HW=0504",
        "hmux0 Status01 = no data stored",
    ]
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {
        "hmux0.FlowTemp": MagicMock(enabled=True, writable=False, fallback_read=True),
    }
    ebus = MagicMock()
    ebus.find_registers = AsyncMock(return_value=current_find)
    ebus.read_register = AsyncMock(return_value=None)
    try:
        await DUMP._dump_registers(
            ebus,
            circuit_aliases={"hmux0": "hmux0"},
            skip_fallback_reads=DUMP._fallback_read_skip_keys(stale_graph, []),
            current_graph=stale_graph,
            runtime_definitions=[],
        )
    finally:
        DUMP.REGISTER_MAP = original_map

    assert ("hmux0", "FlowTemp") not in [call.args[:2] for call in ebus.read_register.await_args_list]


# Intent: incomplete or multi-address HMUX0 scans block dump map probes despite a retained SW0303 skip set.
# Why: the dump service must apply current scan uncertainty to every active reader, not only coordinator polling.
async def test_dump_hmux0_incomplete_current_identity_blocks_map_probes() -> None:
    stale_graph = tc.DISCOVERY.DiscoveryService.build_device_graph(
        ["scan.08 = MF=Vaillant;ID=HMUX0;SW=0303;HW=0504", "hmux0 Other = live"]
    )
    stale_skips = DUMP._fallback_read_skip_keys(stale_graph, [])
    assert ("hmux0", "status01") not in stale_skips
    assert ("hmux0", "flowtemp") not in stale_skips

    current_find_cases = (
        ["scan.08 = Vaillant;HMUX0;0407", "hmux0 Other = live"],
        [
            "scan.08 = Vaillant;HMUX0;0407;0504",
            "scan.09 = Vaillant;HMUX0;0407;0504",
            "hmux0 Other = live",
        ],
    )
    original_map = DUMP.REGISTER_MAP
    DUMP.REGISTER_MAP = {
        "hmux0.Status01": MagicMock(enabled=True, writable=False, fallback_read=True),
        "hmux0.FlowTemp": MagicMock(enabled=True, writable=False, fallback_read=True),
    }
    try:
        for current_find in current_find_cases:
            ebus = MagicMock()
            ebus.find_registers = AsyncMock(return_value=current_find)
            ebus.last_find_usable = True
            ebus.read_register = AsyncMock(return_value=None)

            await DUMP._dump_registers(
                ebus,
                circuit_aliases={"hmux0": "hmux0"},
                skip_fallback_reads=stale_skips,
                current_graph=stale_graph,
                runtime_definitions=[],
            )

            calls = [call.args[:2] for call in ebus.read_register.await_args_list]
            assert not any(circuit.casefold() == "hmux0" for circuit, _ in calls), calls
    finally:
        DUMP.REGISTER_MAP = original_map


# Intent: resolve host aliases to the socket address used for dump-lock identity.
# Why: a DNS name and its IP address can reach the same daemon-global grab state.
async def test_grab_endpoint_lock_key_uses_resolved_socket_address(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "getaddrinfo",
        AsyncMock(return_value=[(2, 1, 6, "", ("192.0.2.10", 8888))]),
    )

    expected = {("192.0.2.10", 8888), ("*", 8888)}
    assert await DUMP._grab_endpoint_keys("ebusd.local", 8888) == expected
    assert await DUMP._grab_endpoint_keys("192.0.2.10", 8888) == expected


# Intent: use a shared port lock when DNS cannot establish a canonical socket address.
# Why: transient resolver failure must not let aliases start overlapping daemon-global captures.
async def test_grab_endpoint_lock_key_falls_back_to_shared_port_on_dns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(side_effect=OSError("resolver unavailable")))

    assert await DUMP._grab_endpoint_keys("ebusd.local", 8888) == {("*", 8888)}


# Intent: serialize dump exports that resolve to the same ebusd endpoint.
# Why: ebusd's grab state is global and overlapping integration exports would interfere.
async def test_dump_exports_to_same_ebusd_endpoint_are_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    active_exports = 0
    maximum_active_exports = 0
    export_count = 0

    # Intent: hold the first export inside the protected capture section.
    # Why: prove the second export cannot enter until the first releases the endpoint lock.
    async def _export_impl(hass, coordinator, grab_duration=0):
        nonlocal active_exports, maximum_active_exports, export_count
        active_exports += 1
        export_count += 1
        maximum_active_exports = max(maximum_active_exports, active_exports)
        if export_count == 1:
            first_entered.set()
            await release_first.wait()
        active_exports -= 1

    monkeypatch.setattr(DUMP, "_async_export_discovery_dump_impl", _export_impl)
    monkeypatch.setattr(DUMP, "_grab_endpoint_keys", AsyncMock(return_value={("192.0.2.10", 8888)}))
    coordinators = [
        SimpleNamespace(
            _active_dump_tasks=set(),
            ebus=SimpleNamespace(is_connected=True),
            ebusd_host="ebusd.local",
            ebusd_port=8888,
        ),
        SimpleNamespace(
            _active_dump_tasks=set(),
            ebus=SimpleNamespace(is_connected=True),
            ebusd_host="127.0.0.1",
            ebusd_port=8888,
        ),
    ]

    first_task = asyncio.create_task(DUMP.async_export_discovery_dump(MagicMock(), coordinators[0]))
    await asyncio.wait_for(first_entered.wait(), timeout=1)
    second_task = asyncio.create_task(DUMP.async_export_discovery_dump(MagicMock(), coordinators[1]))
    await asyncio.sleep(0)

    assert export_count == 1
    assert maximum_active_exports == 1
    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert export_count == 2
    assert maximum_active_exports == 1
    assert active_exports == 0


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
