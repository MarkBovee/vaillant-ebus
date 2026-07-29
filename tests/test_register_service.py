"""Unit tests for RegisterService."""

from __future__ import annotations

import datetime
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

BACKEND_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend"
COMPONENT_PATH = BACKEND_PATH.parent

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

EBUS_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.ebus_service", BACKEND_PATH / "ebus_service.py"
)
assert EBUS_SPEC and EBUS_SPEC.loader
EBUS_MOD = importlib.util.module_from_spec(EBUS_SPEC)
sys.modules["vaillant_ebus.backend.ebus_service"] = EBUS_MOD
EBUS_SPEC.loader.exec_module(EBUS_MOD)

REG_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.register_service", BACKEND_PATH / "register_service.py"
)
assert REG_SPEC and REG_SPEC.loader
REG_MOD = importlib.util.module_from_spec(REG_SPEC)
sys.modules["vaillant_ebus.backend.register_service"] = REG_MOD
REG_SPEC.loader.exec_module(REG_MOD)

RegisterService = REG_MOD.RegisterService
RegisterValue = REG_MOD.RegisterValue
Writeability = REG_MOD.Writeability
ParsedValue = REG_MOD.ParsedValue
EbusService = EBUS_MOD.EbusService
SendResult = MODELS.SendResult
WriteResult = MODELS.WriteResult


# =============================================================================
# Mock helpers
# =============================================================================

def _mock_ebus() -> EbusService:
    ebus = AsyncMock(spec=EbusService)
    ebus.is_connected = True
    return ebus


def _service(ebus: EbusService | None = None) -> RegisterService:
    return RegisterService(ebus or _mock_ebus())


# =============================================================================
# A. Value parsing tests (pure function)
# =============================================================================

def test_parse_numeric_data1b() -> None:
    svc = _service()
    result = svc.parse_value("22.5", "DATA1b")
    assert result.value == 22.5
    assert result.field_type == "DATA1b"
    assert result.is_sentinel is False
    assert result.is_placeholder is False


def test_parse_numeric_data2c() -> None:
    svc = _service()
    result = svc.parse_value("-15.3", "DATA2c")
    assert result.value == -15.3
    assert result.field_type == "DATA2c"


def test_parse_exp() -> None:
    svc = _service()
    result = svc.parse_value("52", "EXP")
    assert result.value == 52.0
    assert result.field_type == "EXP"


def test_parse_bcd_date() -> None:
    svc = _service()
    result = svc.parse_value("29.07.2026", "BCD")
    assert result.value == datetime.date(2026, 7, 29)
    assert result.field_type == "BCD"


def test_parse_bcd_sentinel_open() -> None:
    svc = _service()
    result = svc.parse_value("Open", "BCD")
    assert result.value is None
    assert result.is_sentinel is True


def test_parse_string() -> None:
    svc = _service()
    result = svc.parse_value("Standby", "STR")
    assert result.value == "Standby"
    assert result.field_type == "STR"


def test_parse_placeholder_no_data() -> None:
    svc = _service()
    result = svc.parse_value("no data stored", "DATA1b")
    assert result.value is None
    assert result.is_placeholder is True


def test_parse_placeholder_dash() -> None:
    svc = _service()
    result = svc.parse_value("-", "DATA1b")
    assert result.value is None
    assert result.is_placeholder is True


def test_parse_placeholder_empty() -> None:
    svc = _service()
    result = svc.parse_value("empty", "DATA1b")
    assert result.value is None
    assert result.is_placeholder is True


def test_parse_placeholder_blank() -> None:
    svc = _service()
    result = svc.parse_value("", "DATA1b")
    assert result.value is None
    assert result.is_placeholder is True


def test_parse_ign() -> None:
    svc = _service()
    result = svc.parse_value("anyvalue", "IGN")
    assert result.value is None


def test_parse_unknown_type() -> None:
    svc = _service()
    result = svc.parse_value("foo", "UNKNOWN")
    assert result.value == "foo"


def test_parse_empty_field_type() -> None:
    svc = _service()
    result = svc.parse_value("bar", "")
    assert result.value == "bar"


# =============================================================================
# B. Writeability tests
# =============================================================================

async def test_writeability_writable() -> None:
    ebus = _mock_ebus()
    ebus.send_command.return_value = SendResult(
        data="name=HwcTempDesired, circuit=ctlv2, value=45, writable=true"
    )
    svc = RegisterService(ebus)
    result = await svc.verify_writeability("ctlv2", "HwcTempDesired")
    assert result.writable is True
    assert result.source == "csv_definition"


async def test_writeability_read_only() -> None:
    ebus = _mock_ebus()
    ebus.send_command.return_value = SendResult(
        data="name=SetMode, circuit=hmu, value=auto 17, writable=false"
    )
    svc = RegisterService(ebus)
    result = await svc.verify_writeability("hmu", "SetMode")
    assert result.writable is False
    assert result.source == "csv_definition"


async def test_writeability_unknown() -> None:
    ebus = _mock_ebus()
    ebus.send_command.return_value = SendResult(data="", error="not_connected")
    svc = RegisterService(ebus)
    result = await svc.verify_writeability("unknown", "FakeReg")
    assert result.writable is False
    assert result.source == "unknown"


# =============================================================================
# C. Read tests
# =============================================================================

async def test_read_success() -> None:
    ebus = _mock_ebus()
    ebus.read_register.return_value = "22.5"
    svc = RegisterService(ebus)
    result = await svc.read("hmu", "Status", "DATA1b")
    assert result.raw == "22.5"
    assert result.parsed == 22.5
    assert result.is_placeholder is False


async def test_read_err_element_not_found() -> None:
    ebus = _mock_ebus()
    ebus.read_register.return_value = "ERR: element not found"
    svc = RegisterService(ebus)
    result = await svc.read("ctlv2", "Z1Name1")
    assert result.raw == "ERR: element not found"
    assert result.parsed is None
    assert result.is_placeholder is True


async def test_read_no_data_stored() -> None:
    ebus = _mock_ebus()
    ebus.read_register.return_value = "no data stored"
    svc = RegisterService(ebus)
    result = await svc.read("hmu", "CompressorSpeed", "DATA1b")
    assert result.raw == "no data stored"
    assert result.parsed is None
    assert result.is_placeholder is True


async def test_read_sentinel_open() -> None:
    ebus = _mock_ebus()
    ebus.read_register.return_value = "Open"
    svc = RegisterService(ebus)
    result = await svc.read("ctlv2", "HolidayEnd", "BCD")
    assert result.raw == "Open"
    assert result.parsed is None
    assert result.is_placeholder is False


async def test_read_none_response() -> None:
    ebus = _mock_ebus()
    ebus.read_register.return_value = None
    svc = RegisterService(ebus)
    result = await svc.read("hmu", "Status")
    assert result.raw == ""
    assert result.parsed is None
    assert result.is_placeholder is True


# =============================================================================
# D. Write tests
# =============================================================================

async def test_write_success() -> None:
    ebus = _mock_ebus()
    ebus.send_command.return_value = SendResult(
        data="name=HwcTempDesired, circuit=ctlv2, value=45, writable=true"
    )
    ebus.write_register.return_value = WriteResult(success=True, verified_value="45")
    svc = RegisterService(ebus)
    result = await svc.write("ctlv2", "HwcTempDesired", "45")
    assert result.success is True
    assert result.verified_value == "45"


async def test_write_read_only_blocked() -> None:
    ebus = _mock_ebus()
    ebus.send_command.return_value = SendResult(
        data="name=SetMode, circuit=hmu, value=auto 17, writable=false"
    )
    svc = RegisterService(ebus)
    result = await svc.write("hmu", "SetMode", "cooling")
    assert result.success is False
    assert "read-only" in result.error_message.lower()


async def test_write_not_connected() -> None:
    ebus = _mock_ebus()
    ebus.is_connected = False
    svc = RegisterService(ebus)
    result = await svc.write("hmu", "SetMode", "auto")
    assert result.success is False
    assert "not connected" in result.error_message.lower()


async def test_write_verification_fails() -> None:
    ebus = _mock_ebus()
    ebus.send_command.return_value = SendResult(
        data="name=HwcTempDesired, circuit=ctlv2, value=45, writable=true"
    )
    ebus.write_register.return_value = WriteResult(
        success=True,
        error_message="Write verification failed: 40",
        verified_value="40",
    )
    svc = RegisterService(ebus)
    result = await svc.write("ctlv2", "HwcTempDesired", "45")
    assert result.success is True
    assert result.verified_value == "40"


async def test_write_ebus_error() -> None:
    ebus = _mock_ebus()
    ebus.send_command.return_value = SendResult(
        data="name=HwcTempDesired, circuit=ctlv2, value=45, writable=true"
    )
    ebus.write_register.return_value = WriteResult(success=False, error_message="timeout")
    svc = RegisterService(ebus)
    result = await svc.write("ctlv2", "HwcTempDesired", "45")
    assert result.success is False
    assert "timeout" in result.error_message


# =============================================================================
# E. SetMode regression tests
# =============================================================================

async def test_setmode_is_read_only() -> None:
    ebus = _mock_ebus()
    ebus.send_command.return_value = SendResult(
        data="name=SetMode, circuit=hmu, value=auto 17, writable=false"
    )
    svc = RegisterService(ebus)
    result = await svc.verify_writeability("hmu", "SetMode")
    assert result.writable is False
    assert result.source == "csv_definition"


async def test_setmode_write_blocked() -> None:
    ebus = _mock_ebus()
    ebus.read_register.return_value = "auto 17"
    ebus.send_command.return_value = SendResult(
        data="name=SetMode, circuit=hmu, value=auto 17, writable=false"
    )
    svc = RegisterService(ebus)
    result = await svc.write("hmu", "SetMode", "cooling")
    assert result.success is False
    assert "read-only" in result.error_message.lower()


# =============================================================================
# F. Cache hydrate
# =============================================================================

async def test_hydrate_from_cache() -> None:
    ebus = _mock_ebus()
    svc = RegisterService(ebus)
    await svc.hydrate_from_cache({"ctlv2.HwcTempDesired": "45", "hmu.Status": "Standby"})
    result1 = await svc.read("ctlv2", "HwcTempDesired")
    assert result1.raw == "45"
    result2 = await svc.read("hmu", "Status")
    assert result2.raw == "Standby"
    ebus.read_register.assert_not_called()


async def test_hydrate_from_cache_falls_back_to_ebusd_for_uncached() -> None:
    ebus = _mock_ebus()
    ebus.read_register.return_value = "new_value"
    svc = RegisterService(ebus)
    await svc.hydrate_from_cache({"ctlv2.HwcTempDesired": "45"})
    result = await svc.read("hmu", "Status")
    assert result.raw == "new_value"
    ebus.read_register.assert_called_once_with("hmu", "Status")


async def test_hydrate_from_cache_caches_ebusd_result() -> None:
    ebus = _mock_ebus()
    ebus.read_register.return_value = "first_read"
    svc = RegisterService(ebus)
    result1 = await svc.read("hmu", "Status")
    assert result1.raw == "first_read"
    assert ebus.read_register.call_count == 1
    result2 = await svc.read("hmu", "Status")
    assert result2.raw == "first_read"
    assert ebus.read_register.call_count == 1
