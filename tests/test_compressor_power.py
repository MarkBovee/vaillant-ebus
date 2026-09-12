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
derive_operating_state = MODELS.derive_operating_state


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


# Intent: derive_operating_state maps RunDataStatuscode strings to the five
# Energy Manager states, with defrost and shutdown handled before heat/cool.
# Why: issue #102 - the derived state must be correct for every documented
# compressor status without inventing a state machine.
def test_derive_operating_state_from_run_data_statuscode() -> None:
    cases = {
        "hwc_compressor_active": "DHW",
        "heat_compressor_active": "Heating",
        "heat_prerun": "Heating",
        "heat_overrun": "Heating",
        "cool_compressor_active": "Cooling",
        "cool_compressor_active;ok": "Cooling",
        "cool_prerun": "Cooling",
        "defrost": "Defrost",
        "standby": "Standby",
        "heat_compressor_shutdown": "Standby",
        "cool_compressor_shutdown": "Standby",
    }
    for raw, expected in cases.items():
        values = {"hmu.RunDataStatuscode.value": raw}
        assert derive_operating_state(values, "hmu") == expected, raw


# Intent: derive_operating_state falls back to HMU Status07 heater bits.
# Why: issue #102 - HW5103 can rely on Status07 when RunDataStatuscode is absent.
def test_derive_operating_state_from_status07_bits() -> None:
    assert derive_operating_state({"hmu.Status07.heatermain_b3_heating": "on"}, "hmu") == "Heating"
    assert derive_operating_state({"hmu.Status07.heatermain_b4_cooling": "on"}, "hmu") == "Cooling"
    assert derive_operating_state({"hmu.Status07.heatermain_b7_warmwater": "on"}, "hmu") == "DHW"


# Intent: derive_operating_state maps HMUX0 Status00 compressor states.
# Why: issue #102 - HMUX0 reports operating state through Status00, not Statuscode.
def test_derive_operating_state_from_status00() -> None:
    assert derive_operating_state({"hmu.Status00.compressorstate": "hot_water"}, "hmu") == "DHW"
    assert derive_operating_state({"hmu.Status00.compressorstate": "heating_prerun"}, "hmu") == "Heating"
    assert derive_operating_state({"hmu.Status00.compressorstate": "defrosting"}, "hmu") == "Defrost"
    assert derive_operating_state({"hmu.Status00.compressorstate": "off"}, "hmu") == "Standby"


# Intent: derive_operating_state is unknown when nothing reports a state.
# Why: a missing status must not be coerced into Standby or another default.
def test_derive_operating_state_unknown_without_data() -> None:
    assert derive_operating_state({}, "hmu") is None
    assert derive_operating_state({"hmu.RunDataStatuscode.value": "no data stored"}, "hmu") is None
    assert derive_operating_state({"hmu.RunDataStatuscode.value": "standby"}, None) is None


# Intent: derive_operating_state reports Cooling from SetMode.releaseCooling,
# the only cooling signal on units without Status00/Status07 (RunDataStatuscode
# stays 0 while a cooling period is active).
# Why: issue #102 - Energy Manager State must not stick to Standby during cooling.
def test_derive_operating_state_uses_setmode_releasecooling() -> None:
    cooling_setmode = "auto;19.0;-;-;1;1;1;0;0;1"
    idle_setmode = "auto;19.0;-;-;1;1;1;0;0;0"
    base = {"hmu.RunDataStatuscode.value": "0"}
    assert derive_operating_state({**base, "hmu.SetMode.value": cooling_setmode}, "hmu") == "Cooling"
    assert derive_operating_state({**base, "hmu.SetMode.value": idle_setmode}, "hmu") == "Standby"
    assert derive_operating_state({"hmu.SetMode.value": cooling_setmode}, "hmu") == "Cooling"
    assert derive_operating_state({"hmu.SetMode.value": idle_setmode}, "hmu") is None
    # Explicit controller states always outrank the cooling request flag.
    heat = {"hmu.RunDataStatuscode.value": "heat_compressor_active"}
    assert derive_operating_state({**heat, "hmu.SetMode.value": cooling_setmode}, "hmu") == "Heating"
    standby = {"hmu.RunDataStatuscode.value": "standby"}
    assert derive_operating_state({**standby, "hmu.SetMode.value": cooling_setmode}, "hmu") == "Standby"
    off = {"hmu.Status00.compressorstate": "off"}
    assert derive_operating_state({**off, "hmu.SetMode.value": cooling_setmode}, "hmu") == "Standby"
    # A cooling descriptor never overrides an explicit compressor-off.
    assert (
        derive_operating_state({"hmu.Status00.compressorstate": "off", "hmu.Status00.heatingstate": "cooling"}, "hmu")
        == "Standby"
    )
    assert (
        derive_operating_state({"hmu.RunDataStatuscode.value": "off", "hmu.SetMode.value": cooling_setmode}, "hmu")
        == "Standby"
    )
