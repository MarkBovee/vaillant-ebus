"""Unit tests for EbusService."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.fake_ebusd import FakeEbusdServer

SERVICE_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend/ebus_service.py"

for name in ("vaillant_ebus", "vaillant_ebus.backend"):
    pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    pkg.__path__ = [str(SERVICE_PATH.parents[1])] if name == "vaillant_ebus" else [str(SERVICE_PATH.parent)]
    sys.modules[name] = pkg

SPEC = importlib.util.spec_from_file_location("vaillant_ebus.backend.ebus_service", SERVICE_PATH)
assert SPEC and SPEC.loader
EBUS = importlib.util.module_from_spec(SPEC)
sys.modules["vaillant_ebus.backend.ebus_service"] = EBUS
SPEC.loader.exec_module(EBUS)

EbusService = EBUS.EbusService
SendResult = EBUS.SendResult
WriteResult = EBUS.WriteResult


# Build a mocked service with fake reader/writer for isolated tests
def _service() -> EbusService:
    s = EbusService(host="127.0.0.1", port=8888)
    s._reader = AsyncMock(spec=asyncio.StreamReader)
    s._writer = MagicMock(spec=asyncio.StreamWriter)
    return s


# =============================================================================
# Approach A — Mocked TCP socket tests
# =============================================================================


# send_command: single-line response returned as SendResult
# Intent: send_command drains stale socket data, sends the command once, and returns the response line with no error.
# Why: the drain-write-read sequence is the transport contract every register operation depends on.
async def test_send_command_success() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"Standby\n"])
    result = await s.send_command("state")
    assert result.data == "Standby"
    assert result.error is None
    s._writer.write.assert_called_once()
    s._writer.drain.assert_called_once()


# send_command: not connected returns not_connected error
# Intent: send_command on a service with no writer or reader returns error not_connected and empty data.
# Why: callers must get a typed failure instead of an exception when ebusd is down.
async def test_send_command_not_connected() -> None:
    s = EbusService(host="127.0.0.1", port=8888)
    result = await s.send_command("state")
    assert result.data == ""
    assert result.error == "not_connected"


# send_command: read timeout returns timeout error
# Intent: a read that times out returns a SendResult with error timeout.
# Why: distinguishes a slow ebusd from a closed connection so callers can decide to reconnect.
async def test_send_command_timeout() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), TimeoutError()])
    result = await s.send_command("state")
    assert result.data == ""
    assert result.error == "timeout"


# send_command: empty response (connection closed) returns error
# Intent: an empty read line returns error connection_closed.
# Why: signals the peer dropped the socket so the integration can reconnect instead of hanging.
async def test_send_command_connection_closed() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    result = await s.send_command("state")
    assert result.data == ""
    assert result.error == "connection_closed"


# read_register: returns stripped value on success
# Intent: read_register returns the value with the ebusd status suffix stripped.
# Why: raw status suffixes would corrupt sensor values.
async def test_read_register_success() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"25.5;ok\n"])
    val = await s.read_register("hmu", "Status")
    assert val == "25.5"


# read_register: error response returns None
# Intent: read_register returns None when the transport reports an error.
# Why: unavailable reads must yield None so the coordinator marks the entity unavailable.
async def test_read_register_error_returns_none() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    val = await s.read_register("hmu", "Status")
    assert val is None


# read_register: timeout returns None
# Intent: read_register returns None on read timeout.
# Why: timeouts must not surface as values or raise into polling.
async def test_read_register_timeout_returns_none() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), TimeoutError()])
    val = await s.read_register("hmu", "Status")
    assert val is None


# read_register: with field parameter
# Intent: read_register with a field issues the field read and returns the parsed value.
# Why: multi-field registers are read per field, so the field must be included in the command.
async def test_read_register_with_field() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"field_value\n"])
    val = await s.read_register("hmu", "Status", "field1")
    assert val == "field_value"


# read_register: strip suffix ";ok" from value
# Intent: read_register strips the err status suffix from the value.
# Why: suffix text is transport metadata, not part of the register value.
async def test_read_register_strips_suffix() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"23.50;err\n"])
    val = await s.read_register("ctlv2", "OutdoorTemp")
    assert val == "23.50"


# read_register: empty value returns None
# Intent: a blank response line yields None.
# Why: an empty payload means no data, not an empty-string sensor state.
async def test_read_register_empty_value_returns_none() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"\n"])
    val = await s.read_register("hmu", "Status")
    assert val is None


# write_register: success with read-back verification
# Intent: a done write with a matching semicolon-form read-back succeeds and returns the verified value.
# Why: write verification is the safety net that prevents silently-unapplied writes.
async def test_write_register_success() -> None:
    s = _service()
    s._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),  # drain for write
            b"done\n",  # write response
            TimeoutError(),  # drain for read-back
            b"auto;17;-;-;1;1;1;0;0;1\n",  # read-back (semicolon form)
        ]
    )
    result = await s.write_register("hmu", "SetMode", "auto 17 - - 1 1 1 0 0 1")
    assert result.success
    assert result.verified_value == "auto;17;-;-;1;1;1;0;0;1"


# write_register: read-back that does not match the written value fails.
# Covers the DHW boost case where ebusd answers "done" but the controller
# keeps HwcSFMode on "load" while a boost cycle is still running.
# Intent: a done write whose read-back still reports the old value fails with a verification-mismatch error.
# Why: ebusd accepts writes it does not apply (DHW HwcSFMode stays load), so trusting done would falsely report success.
async def test_write_register_readback_mismatch_fails() -> None:
    s = _service()
    s._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),  # drain for write
            b"done\n",  # write response
            TimeoutError(),  # drain for read-back
            b"load\n",  # read-back: value did not change
        ]
    )
    result = await s.write_register("basv", "HwcSFMode", "auto")
    assert not result.success
    assert "Write verification mismatch" in result.error_message
    assert "load" in result.error_message


# write_register: with strict_verify=False a read-back mismatch is logged but
# not treated as a failure. Used for HwcSFMode, whose physical state lags the
# accepted write while the cylinder is still charging.
# Intent: with strict_verify=False a read-back mismatch is reported as success with the observed value.
# Why: HwcSFMode physical state lags the accepted write, so strict polling would fail valid boost toggles.
async def test_write_register_readback_mismatch_non_strict() -> None:
    s = _service()
    s._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),  # drain for write
            b"done\n",  # write response
            TimeoutError(),  # drain for read-back
            b"load\n",  # read-back: value did not change yet
        ]
    )
    result = await s.write_register("basv", "HwcSFMode", "auto", strict_verify=False)
    assert result.success
    assert result.verified_value == "load"


# write_register: numeric formatting differences are tolerated
# Intent: write verification accepts numeric-format differences such as 23.5 versus 23.50.
# Why: ebusd canonical formatting must not be flagged as a write failure.
async def test_write_register_readback_numeric_tolerance() -> None:
    s = _service()
    s._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),
            b"done\n",
            TimeoutError(),
            b"23.50\n",  # written as 23.5
        ]
    )
    result = await s.write_register("ctlv2", "Z1DayTemp", "23.5")
    assert result.success
    assert result.verified_value == "23.50"


# write_register: connection error propagates as failure
# Intent: a write on a closed connection fails with error_message connection_closed.
# Why: propagates the transport failure so the caller can reconnect.
async def test_write_register_connection_error() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    result = await s.write_register("hmu", "SetMode", "auto")
    assert not result.success
    assert result.error_message == "connection_closed"


# write_register: ERR response from ebusd returns failure
# Intent: an ERR response fails the write and preserves the error text.
# Why: surfaces invalid-value rejections instead of reporting success.
async def test_write_register_unexpected_response() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"ERR: invalid value\n"])
    result = await s.write_register("hmu", "SetMode", "bad")
    assert not result.success
    assert "ERR: invalid value" in result.error_message


# write_register: empty write response followed by successful read-back
# Intent: an empty write response followed by a matching read-back still succeeds.
# Why: some ebusd versions return a blank line instead of done, and read-back is authoritative.
async def test_write_register_empty_response_verified() -> None:
    s = _service()
    s._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),
            b"\n",
            TimeoutError(),
            b"auto;22.0;-;-;1;1;1;0;0;1\n",
        ]
    )
    result = await s.write_register("hmu", "SetMode", "auto;22.0;-;-;1;1;1;0;0;1")
    assert result.success
    assert result.verified_value == "auto;22.0;-;-;1;1;1;0;0;1"


# write_register: empty write + empty read-back = failure
# Intent: an empty write response and empty read-back fails with Write verification returned empty.
# Why: prevents a no-op write from being reported as success.
async def test_write_register_empty_both() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"\n", TimeoutError(), b"\n"])
    result = await s.write_register("hmu", "SetMode", "auto")
    assert not result.success
    assert "Write verification returned empty" in result.error_message


# write_register: done response but read-back returns SYN error
# Intent: a read-back containing ERR: SYN received fails the write with that message.
# Why: bus synchronization errors must not be treated as a verified write.
async def test_write_register_readback_syn_error() -> None:
    s = _service()
    s._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),
            b"done\n",
            TimeoutError(),
            b"ERR: SYN received\n",
        ]
    )
    result = await s.write_register("ctlv2", "Z1OpMode", "night")
    assert not result.success
    assert "Write verification failed: ERR: SYN received" in result.error_message


# find_registers: returns raw lines from _send_find
# Intent: find_registers sends f -a and collects the multi-line response until the read times out.
# Why: discovery depends on every find line, and a truncated list silently loses registers.
async def test_find_registers_returns_lines() -> None:
    s = _service()
    s._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),  # drain
            b"hmu Status = Standby\n",  # first find line
            b"ctlv2 Temp = 25.5\n",  # second find line
            TimeoutError(),  # end
        ]
    )
    lines = await s.find_registers()
    assert lines == ["hmu Status = Standby", "ctlv2 Temp = 25.5"]
    s._writer.write.assert_called_once_with(b"f -a\n")


# find_registers: not connected returns empty list
# Intent: find_registers on a not-connected service returns an empty list.
# Why: discovery must degrade to no registers rather than raise.
async def test_find_registers_not_connected_returns_empty() -> None:
    s = EbusService(host="127.0.0.1", port=8888)
    lines = await s.find_registers()
    assert lines == []


# get_info: parse info command response into dict
# Intent: get_info parses the info banner into key/value pairs.
# Why: version and signal metadata feed diagnostics and discovery dumps.
async def test_get_info_returns_dict() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"version: ebusd 1.0, signal: acquired\n"])
    info = await s.get_info()
    assert info == {"version": "ebusd 1.0", "signal": "acquired"}


# get_info: error returns empty dict
# Intent: get_info returns an empty dict when the transport errors.
# Why: missing info must not break setup.
async def test_get_info_error_returns_empty() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    info = await s.get_info()
    assert info == {}


# get_info: empty response returns empty dict
# Intent: get_info returns an empty dict for a blank response.
# Why: guards the parser against an empty banner.
async def test_get_info_empty_response() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"\n"])
    info = await s.get_info()
    assert info == {}


# define_register: sends define command and returns response
# Intent: define_register sends a define -r command and returns done.
# Why: runtime register definitions require a confirmed define response.
async def test_define_register_returns_done() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"done\n"])
    resp = await s.define_register("r5,ctlv2,z1RoomHumidity,test")
    assert resp == "done"


# define_register: error propagates
# Intent: define_register returns an ERR string when the transport fails.
# Why: callers can detect a failed definition instead of assuming success.
async def test_define_register_error() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    resp = await s.define_register("invalid")
    assert resp.startswith("ERR:")


# is_connected: True when writer is set
# Intent: is_connected is True when a writer is present.
# Why: connection state drives polling and reconnect decisions.
def test_is_connected_true() -> None:
    s = _service()
    assert s.is_connected is True


# is_connected: False when no writer
# Intent: is_connected is False on a fresh service.
# Why: prevents use of an unopened socket.
def test_is_connected_false() -> None:
    s = EbusService()
    assert s.is_connected is False


# version: returns cached version string
# Intent: version is None before connecting.
# Why: discovery-dump metadata must be null until the version is known.
def test_version_default_none() -> None:
    s = EbusService()
    assert s.version is None


# version: returns set value
# Intent: version returns the cached version string.
# Why: cached ebusd version is exposed without an extra command.
def test_version_returns_value() -> None:
    s = EbusService()
    s._version = "ebusd 1.0"
    assert s.version == "ebusd 1.0"


# stale socket data is drained before each command
# Intent: send_command discards buffered stale lines before reading the real response.
# Why: leftover data would otherwise be mistaken for the command response.
async def test_stale_data_drained_before_command() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[b"stale\n", TimeoutError(), b"Standby\n"])
    result = await s.send_command("read -c hmu Status")
    assert result.data == "Standby"
    assert result.error is None


# command log records one entry per send_command call
# Intent: each send_command appends a command-log entry with cmd, data, error and duration.
# Why: diagnostics rely on the command log to debug bus issues.
async def test_command_log_records_entry() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"Standby\n"])
    await s.send_command("state")
    assert len(s._command_log) == 1
    entry = s._command_log[0]
    assert entry["cmd"] == "state"
    assert entry["data"] == "Standby"
    assert entry["error"] is None
    assert entry["duration_ms"] >= 0


# command log ring buffer evicts oldest entries beyond maxlen 20
# Intent: the command log keeps only the most recent twenty entries.
# Why: bounds memory for long-running polling.
async def test_command_log_ring_buffer_eviction() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"ok\n"])
    for i in range(25):
        await s.send_command(f"cmd{i}")
        s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"ok\n"])
    assert len(s._command_log) == 20
    assert s._command_log[0]["cmd"] == "cmd5"
    assert s._command_log[-1]["cmd"] == "cmd24"


# debug_info returns command log, connection state, and reconnect count
# Intent: debug_info reports the command log, connection state and reconnect count.
# Why: Home Assistant diagnostics consume this structure.
async def test_debug_info() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"Standby\n"])
    await s.send_command("state")
    info = s.debug_info
    assert "command_log" in info
    assert "connected" in info
    assert "reconnect_count" in info
    assert info["connected"] is True
    assert info["reconnect_count"] == 0


# =============================================================================
# Approach B — FakeEbusdServer integration tests
# =============================================================================


# Integration: connect to fake ebusd and verify state response
# Intent: connecting to the fake ebusd server and sending state returns a
# signal-acquired banner, and disconnect clears the connection.
# Why: end-to-end exercise of connect, command and disconnect over a real socket.
async def test_integration_connect_and_state() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        assert s.is_connected
        result = await s.send_command("state")
        assert "signal acquired" in result.data
        await s.disconnect()
        assert not s.is_connected


# Integration: connect and read a known register
# Intent: reading ctlv2.AdaptHeatCurve through the fake server returns yes.
# Why: validates the full read path including framing over a real socket.
async def test_integration_read_register() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        val = await s.read_register("ctlv2", "AdaptHeatCurve")
        assert val == "yes"
        await s.disconnect()


# Integration: connect and read register with timestamp data
# Intent: reading Broadcast.Vdatetime returns a semicolon-joined multi-field value.
# Why: confirms compound values pass through the wire unmangled.
async def test_integration_read_register_with_semicolons() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        val = await s.read_register("Broadcast", "Vdatetime")
        assert val is not None
        assert ";" in val
        await s.disconnect()


# Integration: connect and run find_registers
# Intent: find_registers through the fake server returns non-empty lines containing an equals sign.
# Why: validates multi-line find framing end to end.
async def test_integration_find_registers() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        lines = await s.find_registers()
        assert len(lines) > 0
        assert any("=" in line for line in lines)
        await s.disconnect()


# Integration: connect and get info
# Intent: get_info through the fake server returns a version containing ebusd.
# Why: validates info parsing over a real socket.
async def test_integration_get_info() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        info = await s.get_info()
        assert "version" in info
        assert "ebusd" in info["version"]
        await s.disconnect()


# Integration: connect populates the cached version from the info banner, so
# discovery-dump metadata carries the ebusd version instead of null.
# Intent: connect caches the ebusd version parsed from the info banner.
# Why: discovery-dump metadata should carry the version rather than null.
async def test_connect_populates_version() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        assert s.version
        assert "ebusd" in s.version
        await s.disconnect()


# Integration: connect and define register
# Intent: define_register through the fake server returns done.
# Why: validates runtime definition over a real socket.
async def test_integration_define_register() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        resp = await s.define_register("r5,ctlv2,z1RoomHumidity,test")
        assert resp == "done"
        await s.disconnect()


# Intent: after a transport failure the stale writer must be discarded and a
# real redial attempted — a silent no-op reconnect is a regression (the stale
# writer stays set because transport errors never clear it themselves).
# Why: a failed redial that leaves a stale writer makes is_connected lie, so the coordinator never recovers.
async def test_reconnect_clears_stale_writer_and_raises_when_dial_fails(monkeypatch) -> None:
    s = EbusService(host="127.0.0.1", port=59999)
    s._writer = MagicMock(spec=asyncio.StreamWriter)
    s._reader = AsyncMock(spec=asyncio.StreamReader)
    s._reconnect_delay = 0

    async def _refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(asyncio, "open_connection", _refuse)
    with pytest.raises(ConnectionError):
        await s._reconnect()
    assert s._writer is None
    assert s.is_connected is False
    assert s._reconnecting is False


# Intent: concurrent reconnect callers must single-flight — only one dials.
# Why: concurrent redials would stack connections and corrupt the shared socket.
async def test_reconnect_guard_single_flight(monkeypatch) -> None:
    s = EbusService(host="127.0.0.1", port=59999)
    s._reconnect_delay = 0
    calls = {"n": 0}

    async def _slow_open(*args, **kwargs):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        raise OSError("connection refused")

    monkeypatch.setattr(asyncio, "open_connection", _slow_open)
    results = await asyncio.gather(s._reconnect(), s._reconnect(), return_exceptions=True)
    raised = [r for r in results if isinstance(r, ConnectionError)]
    skipped = [r for r in results if r is False]
    assert len(raised) == 1, f"expected exactly one redial attempt, got {calls['n']}"
    assert len(skipped) == 1, "concurrent caller must be told its reconnect was skipped"
    assert calls["n"] == 1
    assert s._reconnecting is False
