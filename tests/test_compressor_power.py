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
set_idle_compressor_power = MODELS.set_idle_compressor_power


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


def test_set_idle_compressor_power_clears_cached_value() -> None:
    key, power = _register("hmu.CurrentConsumedPower", "2.4")
    status_key, status = _register("hmu.RunDataStatuscode", "100")
    _, discovered_power = _register("hmu.CurrentConsumedPower", "-")
    discovered_power.has_data = False
    registers = {key: power, status_key: status}

    set_idle_compressor_power(registers, discovered_power)

    assert power.value["value"] == "0"
    assert power.has_data
