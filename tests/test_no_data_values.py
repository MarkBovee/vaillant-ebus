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


# Real measured values and legitimate domain strings stay live
def test_live_values_pass() -> None:
    for raw in ("21.5", "none", "on", "off", "day", "auto", "58.0;1200"):
        assert not is_no_data_value(raw), f"{raw!r} should stay live"


# Missing values count as no usable data
def test_none_input() -> None:
    assert is_no_data_value(None)
