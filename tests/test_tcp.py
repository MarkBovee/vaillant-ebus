"""Unit tests for ebusd TCP backend."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Load backend.tcp directly without triggering vaillant_ebus.__init__ (needs HA)
TCP_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend/tcp.py"
# Seed the parent packages so relative imports in tcp.py work
for name in ("vaillant_ebus", "vaillant_ebus.backend"):
    pkg = importlib.util.module_from_spec(
        importlib.machinery.ModuleSpec(name, None)
    )
    pkg.__path__ = [str(TCP_PATH.parents[1])] if name == "vaillant_ebus" else [str(TCP_PATH.parent)]
    sys.modules[name] = pkg

SPEC = importlib.util.spec_from_file_location("vaillant_ebus.backend.tcp", TCP_PATH)
assert SPEC and SPEC.loader
TCP = importlib.util.module_from_spec(SPEC)
sys.modules["vaillant_ebus.backend.tcp"] = TCP
SPEC.loader.exec_module(TCP)

EbusdTcpBackend = TCP.EbusdTcpBackend
SendResult = TCP.SendResult


# Build a mocked backend with fake reader/writer for isolated tests
def _backend() -> EbusdTcpBackend:
    b = EbusdTcpBackend(host="127.0.0.1", port=8888)
    b._reader = AsyncMock(spec=asyncio.StreamReader)
    b._writer = MagicMock(spec=asyncio.StreamWriter)
    return b


# SendResult with data and no error
def test_send_result_success() -> None:
    r = SendResult(data="hello")
    assert r.data == "hello"
    assert r.error is None


# SendResult with error and no data
def test_send_result_error() -> None:
    r = SendResult(data="", error="timeout")
    assert r.data == ""
    assert r.error == "timeout"


# async_send_raw: normal response received
async def test_send_raw_success() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"Standby\n"])
    result = await b.async_send_raw("read -c hmu Status")
    assert result.data == "Standby"
    assert result.error is None
    b._writer.write.assert_called_once()
    b._writer.drain.assert_called_once()


# async_send_raw: no connection returns not_connected error
async def test_send_raw_not_connected() -> None:
    b = EbusdTcpBackend(host="127.0.0.1", port=8888)
    result = await b.async_send_raw("read -c hmu Status")
    assert result.data == ""
    assert result.error == "not_connected"


# async_send_raw: read timeout returns timeout error
async def test_send_raw_timeout() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), TimeoutError()])
    result = await b.async_send_raw("read -c hmu Status")
    assert result.data == ""
    assert result.error == "timeout"


# async_send_raw: empty response (connection closed) returns error
async def test_send_raw_connection_closed() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    result = await b.async_send_raw("read -c hmu Status")
    assert result.data == ""
    assert result.error == "connection_closed"


# async_read: returns string value on success
async def test_read_success() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"25.5\n"])
    val = await b.async_read("hmu", "Status")
    assert val == "25.5"


# async_read: empty response returns None
async def test_read_error_returns_none() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    val = await b.async_read("hmu", "Status")
    assert val is None


# async_read: timeout returns None
async def test_read_timeout_returns_none() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), TimeoutError()])
    val = await b.async_read("hmu", "Status")
    assert val is None


# async_read with field parameter sends field name in command
async def test_read_with_field() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"field_value\n"])
    val = await b.async_read("hmu", "Status", "field1")
    assert val == "field_value"


# async_write: success path (done response + successful read-back)
async def test_write_success() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"done\n", TimeoutError(), b"1\n"])
    result = await b.async_write("hmu", "SetMode", "auto 17 - - 1 1 1 0 0 1")
    assert result.success
    assert result.verified_value == "1"


# async_write: connection error propagates as failure
async def test_write_error_propagated() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b""])
    result = await b.async_write("hmu", "SetMode", "auto 17 - - 1 1 1 0 0 1")
    assert not result.success
    assert result.error_message == "connection_closed"


# async_write: ERR response from ebusd returns failure
async def test_write_unexpected_response() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"ERR: invalid value\n"])
    result = await b.async_write("hmu", "SetMode", "bad value")
    assert not result.success
    assert "ERR: invalid value" in result.error_message


# async_write: empty write response followed by successful read-back succeeds
async def test_write_empty_response_verified() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),  # drain for write
            b"\n",  # write returns empty
            TimeoutError(),  # drain for read-back
            b"auto;22.0;-;-;1;1;1;0;0;1\n",  # read-back succeeds
        ]
    )
    result = await b.async_write("hmu", "SetMode", "auto;22.0;-;-;1;1;1;0;0;1")
    assert result.success
    assert result.verified_value == "auto;22.0;-;-;1;1;1;0;0;1"


# async_write: both write response and read-back empty = write failed
async def test_write_empty_response_and_readback_empty() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),  # drain for write
            b"\n",  # write returns empty
            TimeoutError(),  # drain for read-back
            b"\n",  # read-back also empty — write failed
        ]
    )
    result = await b.async_write("hmu", "SetMode", "auto;22.0;-;-;1;1;1;0;0;1")
    assert not result.success
    assert "Write verification returned empty" in result.error_message


# async_write: ebusd returns done but read-back returns bus error
async def test_write_write_done_readback_syn() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),  # drain for write
            b"done\n",  # write returns done
            TimeoutError(),  # drain for read-back
            b"ERR: SYN received\n",  # bus error on read-back
        ]
    )
    result = await b.async_write("ctlv2", "Z1OpMode", "night")
    assert not result.success
    assert "Write verification failed: ERR: SYN received" in result.error_message


# _send_find: collects multi-line find response until timeout
async def test_send_find_returns_lines() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(
        side_effect=[
            TimeoutError(),  # drain
            b"hmu Status = Standby\n",  # first find result line
            b"ctlv2 Temp = 25.5\n",  # second find result line
            TimeoutError(),  # end of results
        ]
    )
    lines = await b._send_find()
    assert lines == ["hmu Status = Standby", "ctlv2 Temp = 25.5"]


# _send_find: not connected returns empty list
async def test_send_find_not_connected_returns_empty() -> None:
    b = EbusdTcpBackend(host="127.0.0.1", port=8888)
    lines = await b._send_find()
    assert lines == []


# stale socket data is drained before each command
async def test_stale_data_drained_before_command() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(
        side_effect=[b"stale\n", TimeoutError(), b"Standby\n"]
    )
    result = await b.async_send_raw("read -c hmu Status")
    assert result.data == "Standby"
    assert result.error is None


# command log records one entry per send_raw call
async def test_command_log_records_entry() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"Standby\n"])
    await b.async_send_raw("read -c hmu Status")
    assert len(b._command_log) == 1
    entry = b._command_log[0]
    assert entry["cmd"] == "read -c hmu Status"
    assert entry["data"] == "Standby"
    assert entry["error"] is None
    assert entry["duration_ms"] >= 0


# command log ring buffer evicts oldest entries beyond maxlen 20
async def test_command_log_ring_buffer_eviction() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"ok\n"])
    for i in range(25):
        await b.async_send_raw(f"cmd{i}")
        b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"ok\n"])
    assert len(b._command_log) == 20
    assert b._command_log[0]["cmd"] == "cmd5"
    assert b._command_log[-1]["cmd"] == "cmd24"


# debug_info returns command log, connection state, and reconnect count
async def test_debug_info() -> None:
    b = _backend()
    b._reader.readline = AsyncMock(side_effect=[TimeoutError(), b"Standby\n"])
    await b.async_send_raw("read -c hmu Status")
    info = b.debug_info
    assert "command_log" in info
    assert "connected" in info
    assert "reconnect_count" in info
    assert info["connected"] is True
    assert info["reconnect_count"] == 0
