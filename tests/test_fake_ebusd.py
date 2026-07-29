"""Tests for fake ebusd server used as test fixture."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from tests.fake_ebusd import FakeEbusdServer, load_find_lines, _parse_find_line_register

# Load tcp module same pattern as test_tcp.py
TCP_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend/tcp.py"
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


# Fixture loads aroTHERM data
async def test_arotherm_fixture_loads() -> None:
    async with FakeEbusdServer() as server:
        assert server.register_count > 0
        assert ("Broadcast", "Outsidetemp") in server._registers


# All three fixtures load without error
@pytest.mark.parametrize("fixture,min_registers", [
    ("arotherm_find.txt", 50),
    ("community/basv_find.txt", 50),
    ("community/v32_find.txt", 5),
])
async def test_all_fixtures_load(fixture: str, min_registers: int) -> None:
    async with FakeEbusdServer(fixture) as server:
        assert server.register_count >= min_registers, f"{fixture}: got {server.register_count} registers"


# state returns acquired message
async def test_state_command() -> None:
    async with FakeEbusdServer() as server:
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        w.write(b"state\n")
        await w.drain()
        resp = (await r.readline()).decode().strip()
        assert "signal acquired" in resp
        w.close()


# info returns version string
async def test_info_command() -> None:
    async with FakeEbusdServer() as server:
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        w.write(b"info\n")
        await w.drain()
        resp = (await r.readline()).decode().strip()
        assert "ebusd" in resp
        w.close()


# read returns value for known register
async def test_read_known_register() -> None:
    async with FakeEbusdServer() as server:
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        w.write(b"read -c Broadcast Outsidetemp\n")
        await w.drain()
        resp = (await r.readline()).decode().strip()
        assert resp and resp not in ("", "no data stored")
        w.close()


# read returns empty for unknown register
async def test_read_unknown_register() -> None:
    async with FakeEbusdServer() as server:
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        w.write(b"read -c hmu NonExistentRegister\n")
        await w.drain()
        resp = (await r.readline()).decode().strip()
        assert resp == ""
        w.close()


# write stores value, read-back returns it
async def test_write_then_read() -> None:
    async with FakeEbusdServer() as server:
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        w.write(b"write -c hmu SetMode test_value\n")
        await w.drain()
        assert (await r.readline()).decode().strip() == "done"
        w.write(b"read -c hmu SetMode\n")
        await w.drain()
        assert (await r.readline()).decode().strip() == "test_value"
        w.close()


# find dumps all fixture lines, subsequent commands work
async def test_find_multi_line() -> None:
    async with FakeEbusdServer() as server:
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        w.write(b"f\n")
        await w.drain()
        count = 0
        while True:
            try:
                line = await asyncio.wait_for(r.readline(), timeout=0.3)
                if not line:
                    break
                count += 1
            except asyncio.TimeoutError:
                break
        assert count > 50, f"Expected >50 find lines, got {count}"
        # Next command still works
        w.write(b"state\n")
        await w.drain()
        assert "signal acquired" in (await r.readline()).decode().strip()
        w.close()


# define returns done
async def test_define_command() -> None:
    async with FakeEbusdServer() as server:
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        w.write(b"define -r r5,ctlv2,z1RoomHumidity,...\n")
        await w.drain()
        assert (await r.readline()).decode().strip() == "done"
        w.close()


# The fake server works with the real EbusdTcpBackend
async def test_with_real_tcp_backend() -> None:
    async with FakeEbusdServer() as fake:
        backend = EbusdTcpBackend(host="127.0.0.1", port=fake.port)
        await backend.async_connect()

        regs = await backend.async_find()
        assert len(regs) > 0

        val = await backend.async_read("Broadcast", "Outsidetemp")
        assert val is not None

        result = await backend.async_write("hmu", "SetMode", "auto 17")
        assert result.success

        await backend.async_disconnect()


# Community basv system works with ebusd backend
async def test_basv_with_tcp_backend() -> None:
    async with FakeEbusdServer("community/basv_find.txt") as fake:
        backend = EbusdTcpBackend(host="127.0.0.1", port=fake.port)
        await backend.async_connect()
        regs = await backend.async_find()
        circuits = {r.circuit for r in regs}
        assert "basv" in circuits
        await backend.async_disconnect()
