"""Tests for the "Trouble Codes" binary sensor (issue #264)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from tests import test_coordinator as tc  # noqa: F401 — loads the shared modules once

mock_homeassistant = sys.modules["homeassistant"]

from vaillant_ebus.binary_sensor import EbusdFaultSensor  # noqa: E402


# Build a coordinator stub with the given heat pump and controller `Currenterror` values (None = not present).
def _sensor(heat_pump: str | None, controller: str | None) -> EbusdFaultSensor:
    coordinator = MagicMock()
    coordinator.heating_circuit = "ctlv3"
    coordinator.heat_pump_circuit = "hmux0"
    data: dict[str, str] = {}
    if heat_pump is not None:
        data["hmux0.Currenterror.value"] = heat_pump
    if controller is not None:
        data["ctlv3.Currenterror.value"] = controller
    coordinator.data = {"ebusd": data}
    entry = MagicMock()
    entry.entry_id = "entry-1"
    return EbusdFaultSensor(coordinator, entry)


# Intent: an ebusd error text or `no data stored` never counts as a fault when the other source says "no error".
# Why: issue #264 - the sensor stayed on while the controller, the heat pump display and the cloud showed no fault;
#      any value other than `-` counted as an error code, including decode errors.
@pytest.mark.parametrize(
    "heat_pump",
    [
        "ERR: invalid position in decode",
        "20579;32768;26713;0 (ERR: invalid position for 3115b503020001)",
        "no data stored",
        None,
    ],
)
def test_unusable_currenterror_is_no_fault(heat_pump: str | None) -> None:
    assert _sensor(heat_pump, "-;-;-;-;-").is_on is False


# Intent: a real error code still turns the sensor on.
# Why: the issue #264 fix must keep reporting genuine faults from either source.
@pytest.mark.parametrize(
    ("heat_pump", "controller"), [("1035;-;-;-;-", "-;-;-;-;-"), ("no data stored", "516;-;-;-;-")]
)
def test_real_error_code_is_a_fault(heat_pump: str, controller: str) -> None:
    assert _sensor(heat_pump, controller).is_on is True


# Intent: without any usable answer the sensor is unknown, not "no problem".
# Why: unavailable data must not collapse into a default (AGENTS.md); "off" would claim the system is fault-free.
def test_no_usable_answer_is_unknown() -> None:
    assert _sensor("no data stored", "ERR: element not found").is_on is None
