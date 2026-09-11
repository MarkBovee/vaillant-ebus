"""Unit tests for compressor idle detection and zeroing."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODELS_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend/models.py"
SPEC = importlib.util.spec_from_file_location("vaillant_ebus_models", MODELS_PATH)
assert SPEC and SPEC.loader
MODELS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODELS
SPEC.loader.exec_module(MODELS)

EbusdRegister = MODELS.EbusdRegister
compressor_is_idle = MODELS.compressor_is_idle
zero_idle_registers = MODELS.zero_idle_registers
COMPRESSOR_ZERO_REGISTER_NAMES = MODELS.COMPRESSOR_ZERO_REGISTER_NAMES


# Build a register dict entry with given key and string value
def _register(key: str, value: str) -> tuple[str, EbusdRegister]:
    circuit, name = key.split(".", 1)
    return key, EbusdRegister(
        circuit=circuit,
        name=name,
        fields=["value"],
        value={"value": value},
        has_data=True,
    )


# Idle detection from status code + speed values
# Intent: compressor_is_idle is true for status 100 or when both speed and
# utilization are zero, and false for status 104.
# Why: idle detection must fire on a stopped status code or zero-speed signals so power is not zeroed while running.
def test_compressor_is_idle_from_status_and_values() -> None:
    stopped = dict(
        [
            _register("hmu.RunDataStatuscode", "100"),
            _register("hmu.RunDataCompressorSpeed", "0"),
        ]
    )
    running = dict(
        [
            _register("hmu.RunDataStatuscode", "104"),
            _register("hmu.RunDataCompressorSpeed", "0"),
        ]
    )
    idle_from_values = dict(
        [
            _register("hmu.RunDataCompressorSpeed", "0"),
            _register("hmu.CurrentCompressorUtil", "0"),
        ]
    )

    assert compressor_is_idle(stopped)
    assert not compressor_is_idle(running)
    assert compressor_is_idle(idle_from_values)


# All compressor-dependent registers are zeroed when compressor is idle
# Intent: zero_idle_registers sets every COMPRESSOR_ZERO_REGISTER_NAMES entry to
# "0" and keeps has_data when the status is idle.
# Why: prevents stale compressor power and flow readings from lingering as live values while the compressor is stopped.
def test_zero_idle_registers_clears_all() -> None:
    regs = dict(
        [
            _register("hmu.CurrentConsumedPower", "2.4"),
            _register("hmu.CurrentYieldPower", "5.1"),
            _register("hmu.CurrentCompressorUtil", "42"),
            _register("hmu.RunDataCompressorSpeed", "4500"),
            _register("hmu.RunDataFan1Speed", "800"),
            _register("hmu.RunDataFan2Speed", "800"),
            _register("hmu.RunDataEEVPositionAbs", "30"),
            _register("hmu.RunDataStatuscode", "100"),
        ]
    )
    zero_idle_registers(regs)
    for name in COMPRESSOR_ZERO_REGISTER_NAMES:
        key = f"hmu.{name}"
        assert regs[key].value["value"] == "0", f"{key} not zeroed"
        assert regs[key].has_data, f"{key} has_data not set"


# Registers are NOT zeroed when compressor status is active
# Intent: zero_idle_registers preserves CurrentConsumedPower when status code 104 indicates the compressor is active.
# Why: protects genuine running power readings from being wiped during active operation.
def test_zero_idle_registers_skips_when_compressor_active() -> None:
    regs = dict(
        [
            _register("hmu.CurrentConsumedPower", "2.7"),
            _register("hmu.RunDataStatuscode", "104"),
        ]
    )
    zero_idle_registers(regs)
    assert regs["hmu.CurrentConsumedPower"].value["value"] == "2.7"


# String status "standby" is correctly detected as idle
# Intent: the string status "standby" is treated as idle even when compressor speed is non-zero.
# Why: covers controllers that report a textual standby state instead of numeric status codes.
def test_compressor_is_idle_string_status_standby() -> None:
    regs = dict(
        [
            _register("hmu.RunDataStatuscode", "standby"),
            _register("hmu.RunDataCompressorSpeed", "4500"),
        ]
    )
    assert compressor_is_idle(regs)


# String status "hwc_compressor_active" is correctly detected as NOT idle
# Intent: the string status "hwc_compressor_active" is not idle even when compressor speed is zero.
# Why: prevents DHW compressor activity from being misread as idle and having its values zeroed.
def test_compressor_is_idle_string_status_hwc_active() -> None:
    regs = dict(
        [
            _register("hmu.RunDataStatuscode", "hwc_compressor_active"),
            _register("hmu.RunDataCompressorSpeed", "0"),
        ]
    )
    assert not compressor_is_idle(regs)


# Registers preserved when string status indicates active compressor
# Intent: zero_idle_registers preserves CurrentConsumedPower when the string status is "hwc_compressor_active".
# Why: guards active DHW power readings against zeroing when the controller reports a textual status.
def test_zero_idle_registers_skips_on_hwc_active_string() -> None:
    regs = dict(
        [
            _register("hmu.CurrentConsumedPower", "1.8"),
            _register("hmu.RunDataStatuscode", "hwc_compressor_active"),
            _register("hmu.RunDataCompressorSpeed", "0"),
        ]
    )
    zero_idle_registers(regs)
    assert regs["hmu.CurrentConsumedPower"].value["value"] == "1.8"


# A resolved non-"hmu" heat-pump circuit zeroes its own registers
# Intent: zero_idle_registers(regs, "um") zeroes the registers of the explicitly resolved non-"hmu" circuit.
# Why: supports heat-pump variants whose circuit is not literally "hmu" without hardcoding it.
def test_zero_idle_registers_non_hmu_circuit() -> None:
    regs = dict(
        [
            _register("um.CurrentConsumedPower", "3.2"),
            _register("um.RunDataStatuscode", "100"),
        ]
    )
    zero_idle_registers(regs, "um")
    assert regs["um.CurrentConsumedPower"].value["value"] == "0"


# Default call ignores circuits other than "hmu" (no silent cross-circuit zeroing)
# Intent: calling zero_idle_registers without a circuit argument leaves the non-"hmu" circuit register unchanged.
# Why: prevents silent cross-circuit zeroing when the caller has not resolved the actual heat-pump circuit.
def test_default_call_ignores_other_circuits() -> None:
    regs = dict(
        [
            _register("um.CurrentConsumedPower", "3.2"),
            _register("um.RunDataStatuscode", "100"),
        ]
    )
    zero_idle_registers(regs)
    assert regs["um.CurrentConsumedPower"].value["value"] == "3.2"
