"""Tests for fake ebusd server used as test fixture."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from tests.fake_ebusd import FakeEbusdServer, load_discovery_dump, load_find_lines

# Load ebus_service module
EBUS_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend/ebus_service.py"
for name in ("vaillant_ebus", "vaillant_ebus.backend"):
    pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    pkg.__path__ = [str(EBUS_PATH.parents[1])] if name == "vaillant_ebus" else [str(EBUS_PATH.parent)]
    sys.modules[name] = pkg
SPEC = importlib.util.spec_from_file_location("vaillant_ebus.backend.ebus_service", EBUS_PATH)
assert SPEC and SPEC.loader
EBUS = importlib.util.module_from_spec(SPEC)
sys.modules["vaillant_ebus.backend.ebus_service"] = EBUS
SPEC.loader.exec_module(EBUS)
EbusService = EBUS.EbusService


# Fixture loads aroTHERM data
async def test_arotherm_fixture_loads() -> None:
    async with FakeEbusdServer() as server:
        assert server.register_count > 0
        assert ("Broadcast", "Outsidetemp") in server._registers


# All fixtures load without error
@pytest.mark.parametrize(
    "fixture,min_registers",
    [
        ("arotherm_find.txt", 50),
        ("community/basv_find.txt", 50),
        ("community/v32_find.txt", 5),
        ("community/flexotherm_discovery.yaml", 50),
        ("community/arotherm_plus_2zone_discovery.yaml", 50),
        ("community/arotherm_plus_basv3_discovery.yaml", 50),
        ("community/arotherm_pro7_discovery.yaml", 5),
        ("community/flexocompact_find.txt", 50),
        ("community/arotherm_ecotec_discovery.yaml", 50),
        ("community/arotherm_plus_prenergy_discovery.yaml", 50),
        ("community/arotherm_plus_cooling_run_discovery.yaml", 50),
        ("community/arotherm_plus_hwc_run_discovery.yaml", 50),
        ("community/arotherm_plus_ctlv2_cooling_discovery.yaml", 50),
        ("community/geniaset_bass3_discovery.yaml", 50),
    ],
)
async def test_all_fixtures_load(fixture: str, min_registers: int) -> None:
    async with FakeEbusdServer(fixture) as server:
        assert server.register_count >= min_registers, f"{fixture}: got {server.register_count} registers"


# Discovery-dump YAML fixtures expose their metadata and raw find lines
def test_load_discovery_dump_metadata() -> None:
    dump = load_find_lines("community/flexotherm_discovery.yaml")
    assert dump
    assert any("ctlv3" in line for line in dump)
    assert any("scan.15" in line for line in dump)


# dumpvalues.yaml records field names for multi-field registers
def test_dumpvalues_field_names_match_multi_field_map() -> None:
    from tests.fake_ebusd import MULTI_FIELD_MAP

    dump = load_discovery_dump("community/dumpvalues.yaml")
    assert "ebusd/hmux0" in dump
    for (circuit, name), fields in MULTI_FIELD_MAP.items():
        reg_fields = dump.get(f"ebusd/{circuit}", {}).get(name)
        if reg_fields is None:
            reg_fields = dump.get("ebusd/hmux0", {}).get(name)
        assert reg_fields is not None, f"{circuit}.{name} ontbreekt in dumpvalues.yaml"
        for field in fields:
            assert field in reg_fields, f"{circuit}.{name} field {field} ontbreekt in dumpvalues.yaml"


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
            except TimeoutError:
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


# The fake server works with the real EbusService
async def test_with_real_ebus_service() -> None:
    async with FakeEbusdServer() as fake:
        ebus = EbusService(host="127.0.0.1", port=fake.port)
        await ebus.connect()

        regs = await ebus.find_registers()
        assert len(regs) > 0

        val = await ebus.read_register("Broadcast", "Outsidetemp")
        assert val is not None

        result = await ebus.write_register("hmu", "SetMode", "auto 17")
        assert result.success

        await ebus.disconnect()


# Field-level read for known multi-field register
async def test_field_level_read_releasecooling() -> None:
    async with FakeEbusdServer() as fake:
        ebus = EbusService(host="127.0.0.1", port=fake.port)
        await ebus.connect()
        val = await ebus.read_register("hmu", "SetMode", "releaseCooling")
        assert val == "0"
        val = await ebus.read_register("hmu", "SetMode", "hcmode")
        assert val is not None
        val = await ebus.read_register("hmu", "SetMode", "nonexistent")
        assert val == "water;-;-;132;1;1;1;1;0;0"  # falls back to full value
        await ebus.disconnect()


# Field-level read for non-existent register returns None
async def test_field_level_read_nonexistent() -> None:
    async with FakeEbusdServer() as fake:
        ebus = EbusService(host="127.0.0.1", port=fake.port)
        await ebus.connect()
        val = await ebus.read_register("hmu", "Status00", "defrost")
        assert val is None
        await ebus.disconnect()


# Field-level read of hmu.Status01 flow/return temp (issue #51)
async def test_field_level_read_status01() -> None:
    async with FakeEbusdServer("community/arotherm_plus_basv3_discovery.yaml") as fake:
        ebus = EbusService(host="127.0.0.1", port=fake.port)
        await ebus.connect()
        flow = await ebus.read_register("hmu", "Status01", "temp")
        assert flow == "39.5"
        ret = await ebus.read_register("hmu", "Status01", "temp_1")
        assert ret == "40.5"
        pump = await ebus.read_register("hmu", "Status01", "pumpstate")
        assert pump == "off"
        await ebus.disconnect()


# Community basv system works with ebus service
async def test_basv_with_ebus_service() -> None:
    async with FakeEbusdServer("community/basv_find.txt") as fake:
        ebus = EbusService(host="127.0.0.1", port=fake.port)
        await ebus.connect()
        regs = await ebus.find_registers()
        # Check that basv circuit appears in find output
        has_basv = any("basv" in line for line in regs)
        assert has_basv
        await ebus.disconnect()
