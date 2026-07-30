"""Unit tests for EbusService."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
async def test_send_command_success() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"Standby\n"])
    result = await s.send_command("state")
    assert result.data == "Standby"
    assert result.error is None
    s._writer.write.assert_called_once()
    s._writer.drain.assert_called_once()


# send_command: not connected returns not_connected error
async def test_send_command_not_connected() -> None:
    s = EbusService(host="127.0.0.1", port=8888)
    result = await s.send_command("state")
    assert result.data == ""
    assert result.error == "not_connected"


# send_command: read timeout returns timeout error
async def test_send_command_timeout() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), TimeoutError()])
    result = await s.send_command("state")
    assert result.data == ""
    assert result.error == "timeout"


# send_command: empty response (connection closed) returns error
async def test_send_command_connection_closed() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    result = await s.send_command("state")
    assert result.data == ""
    assert result.error == "connection_closed"


# read_register: returns stripped value on success
async def test_read_register_success() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"25.5;ok\n"])
    val = await s.read_register("hmu", "Status")
    assert val == "25.5"


# read_register: error response returns None
async def test_read_register_error_returns_none() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    val = await s.read_register("hmu", "Status")
    assert val is None


# read_register: timeout returns None
async def test_read_register_timeout_returns_none() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), TimeoutError()])
    val = await s.read_register("hmu", "Status")
    assert val is None


# read_register: with field parameter
async def test_read_register_with_field() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"field_value\n"])
    val = await s.read_register("hmu", "Status", "field1")
    assert val == "field_value"


# read_register: strip suffix ";ok" from value
async def test_read_register_strips_suffix() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"23.50;err\n"])
    val = await s.read_register("ctlv2", "OutdoorTemp")
    assert val == "23.50"


# read_register: empty value returns None
async def test_read_register_empty_value_returns_none() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"\n"])
    val = await s.read_register("hmu", "Status")
    assert val is None


# write_register: success with read-back verification
async def test_write_register_success() -> None:
    s = _service()
    s._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),  # drain for write
            b"done\n",  # write response
            TimeoutError(),  # drain for read-back
            b"1\n",  # read-back
        ]
    )
    result = await s.write_register("hmu", "SetMode", "auto 17 - - 1 1 1 0 0 1")
    assert result.success
    assert result.verified_value == "1"


# write_register: connection error propagates as failure
async def test_write_register_connection_error() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    result = await s.write_register("hmu", "SetMode", "auto")
    assert not result.success
    assert result.error_message == "connection_closed"


# write_register: ERR response from ebusd returns failure
async def test_write_register_unexpected_response() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"ERR: invalid value\n"])
    result = await s.write_register("hmu", "SetMode", "bad")
    assert not result.success
    assert "ERR: invalid value" in result.error_message


# write_register: empty write response followed by successful read-back
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
async def test_write_register_empty_both() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"\n", TimeoutError(), b"\n"])
    result = await s.write_register("hmu", "SetMode", "auto")
    assert not result.success
    assert "Write verification returned empty" in result.error_message


# write_register: done response but read-back returns SYN error
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
async def test_find_registers_not_connected_returns_empty() -> None:
    s = EbusService(host="127.0.0.1", port=8888)
    lines = await s.find_registers()
    assert lines == []


# get_info: parse info command response into dict
async def test_get_info_returns_dict() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"version: ebusd 1.0, signal: acquired\n"])
    info = await s.get_info()
    assert info == {"version": "ebusd 1.0", "signal": "acquired"}


# get_info: error returns empty dict
async def test_get_info_error_returns_empty() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    info = await s.get_info()
    assert info == {}


# get_info: empty response returns empty dict
async def test_get_info_empty_response() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"\n"])
    info = await s.get_info()
    assert info == {}


# define_register: sends define command and returns response
async def test_define_register_returns_done() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"done\n"])
    resp = await s.define_register("r5,ctlv2,z1RoomHumidity,test")
    assert resp == "done"


# define_register: error propagates
async def test_define_register_error() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    resp = await s.define_register("invalid")
    assert resp.startswith("ERR:")


# is_connected: True when writer is set
def test_is_connected_true() -> None:
    s = _service()
    assert s.is_connected is True


# is_connected: False when no writer
def test_is_connected_false() -> None:
    s = EbusService()
    assert s.is_connected is False


# version: returns cached version string
def test_version_default_none() -> None:
    s = EbusService()
    assert s.version is None


# version: returns set value
def test_version_returns_value() -> None:
    s = EbusService()
    s._version = "ebusd 1.0"
    assert s.version == "ebusd 1.0"


# stale socket data is drained before each command
async def test_stale_data_drained_before_command() -> None:
    s = _service()
    s._reader.readline = AsyncMock(side_effect=[b"stale\n", TimeoutError(), b"Standby\n"])
    result = await s.send_command("read -c hmu Status")
    assert result.data == "Standby"
    assert result.error is None


# command log records one entry per send_command call
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
async def test_integration_read_register() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        val = await s.read_register("ctlv2", "AdaptHeatCurve")
        assert val == "yes"
        await s.disconnect()


# Integration: connect and read register with timestamp data
async def test_integration_read_register_with_semicolons() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        val = await s.read_register("Broadcast", "Vdatetime")
        assert val is not None
        assert ";" in val
        await s.disconnect()


# Integration: connect and run find_registers
async def test_integration_find_registers() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        lines = await s.find_registers()
        assert len(lines) > 0
        assert any("=" in line for line in lines)
        await s.disconnect()


# Integration: connect and get info
async def test_integration_get_info() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        info = await s.get_info()
        assert "version" in info
        assert "ebusd" in info["version"]
        await s.disconnect()


# Integration: connect and define register
async def test_integration_define_register() -> None:
    async with FakeEbusdServer() as fake:
        s = EbusService(host=fake.host, port=fake.port)
        await s.connect()
        resp = await s.define_register("r5,ctlv2,z1RoomHumidity,test")
        assert resp == "done"
        await s.disconnect()
