"""Unit tests for the shared ebusd no-data value helper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODELS_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend/models.py"
SPEC = importlib.util.spec_from_file_location("vaillant_ebus_models_no_data", MODELS_PATH)
assert SPEC and SPEC.loader
MODELS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODELS
SPEC.loader.exec_module(MODELS)

is_no_data_value = MODELS.is_no_data_value


# Exact sentinel values carry no usable data
def test_exact_sentinels() -> None:
    for raw in ("", "-", "empty", "unknown", "unavailable"):
        assert is_no_data_value(raw), f"{raw!r} should be no-data"


# Prefix and embedded error forms carry no usable data
def test_prefix_and_error_forms() -> None:
    for raw in (
        "no data stored",
        "no data stored (hmu CurrentYieldPowerToday)",
        "(empty message)",
        "58.0 (ERR: element not found)",
        "ERR: invalid position in decode",
        "ERR: element not found",
    ):
        assert is_no_data_value(raw), f"{raw!r} should be no-data"


# Sensor fault statuses (Values_sensor enum: circuit=85, cutoff=170) mean the
# sensor is not present, so the register carries no usable measurement.
def test_sensor_fault_statuses_are_no_data() -> None:
    for raw in (
        "116.06;circuit",
        "-60.44;cutoff",
        "circuit",
        "cutoff",
    ):
        assert is_no_data_value(raw), f"{raw!r} should be no-data"


# Real measured values and legitimate domain strings stay live
def test_live_values_pass() -> None:
    for raw in (
        "21.5",
        "none",
        "on",
        "off",
        "day",
        "auto",
        "58.0;1200",
        "55.31;64650;ok",
        "47.06;ok",
        "1.771;ok",
        "43.5;53.5;-;-;62.0;off",
    ):
        assert not is_no_data_value(raw), f"{raw!r} should stay live"


# Missing values count as no usable data
def test_none_input() -> None:
    assert is_no_data_value(None)
