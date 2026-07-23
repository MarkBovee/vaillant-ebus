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
COMPRESSOR_ZERO_REGISTERS = MODELS.COMPRESSOR_ZERO_REGISTERS


def _register(key: str, value: str) -> tuple[str, EbusdRegister]:
    circuit, name = key.split(".", 1)
    return key, EbusdRegister(
        circuit=circuit,
        name=name,
        fields=["value"],
        value={"value": value},
        has_data=True,
    )


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


def test_zero_idle_registers_clears_all() -> None:
    regs = dict([
        _register("hmu.CurrentConsumedPower", "2.4"),
        _register("hmu.CurrentYieldPower", "5.1"),
        _register("hmu.CurrentCompressorUtil", "42"),
        _register("hmu.RunDataCompressorSpeed", "4500"),
        _register("hmu.RunDataFan1Speed", "800"),
        _register("hmu.RunDataFan2Speed", "800"),
        _register("hmu.RunDataEEVPositionAbs", "30"),
        _register("hmu.RunDataStatuscode", "100"),
    ])
    zero_idle_registers(regs)
    for key in COMPRESSOR_ZERO_REGISTERS:
        assert regs[key].value["value"] == "0", f"{key} not zeroed"
        assert regs[key].has_data, f"{key} has_data not set"


def test_zero_idle_registers_skips_when_compressor_active() -> None:
    regs = dict([
        _register("hmu.CurrentConsumedPower", "2.7"),
        _register("hmu.RunDataStatuscode", "104"),
    ])
    zero_idle_registers(regs)
    assert regs["hmu.CurrentConsumedPower"].value["value"] == "2.7"


def test_compressor_is_idle_string_status_standby() -> None:
    regs = dict([
        _register("hmu.RunDataStatuscode", "standby"),
        _register("hmu.RunDataCompressorSpeed", "4500"),
    ])
    assert compressor_is_idle(regs)


def test_compressor_is_idle_string_status_hwc_active() -> None:
    regs = dict([
        _register("hmu.RunDataStatuscode", "hwc_compressor_active"),
        _register("hmu.RunDataCompressorSpeed", "0"),
    ])
    assert not compressor_is_idle(regs)


def test_zero_idle_registers_skips_on_hwc_active_string() -> None:
    regs = dict([
        _register("hmu.CurrentConsumedPower", "1.8"),
        _register("hmu.RunDataStatuscode", "hwc_compressor_active"),
        _register("hmu.RunDataCompressorSpeed", "0"),
    ])
    zero_idle_registers(regs)
    assert regs["hmu.CurrentConsumedPower"].value["value"] == "1.8"
