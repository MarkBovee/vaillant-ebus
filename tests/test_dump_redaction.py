"""Tests for the discovery dump redaction (backlog C10).

The redaction hides serial numbers, key codes and the installer data. It matched short fragments inside register
names, so the heat pump status code and the zone mapping disappeared from every dump.
"""

from __future__ import annotations

import sys

import pytest

from tests import test_coordinator as tc  # noqa: F401 — loads the shared modules once
from tests.backend_loader import load_backend

DUMP = sys.modules["vaillant_ebus.dump_service"]
REDACTION = load_backend("redaction")


# Intent: names that only contain a sensitive fragment inside another word keep their value in the dump.
# Why: RunDataStatuscode ("code"), Z1RoomZoneMapping and SourceTempInput ("pin") carry the evidence the analysis needs
# (compressor mode, zone ownership) and are not secrets; the owner's dump showed all three as <redacted>.
@pytest.mark.parametrize(
    "name",
    ["RunDataStatuscode", "Z1RoomZoneMapping", "Z3RoomZoneMapping", "SourceTempInput", "Status01", "HwcOpMode"],
)
def test_dump_keeps_values_of_registers_that_only_contain_a_sensitive_fragment(name: str) -> None:
    assert DUMP._redact("hwc_compressor_active", name) == "hwc_compressor_active"


# Intent: serial numbers, key codes, installer data and credential-like names are still redacted.
# Why: narrowing the match must not leak the real secrets that the redaction exists for.
@pytest.mark.parametrize(
    "name",
    [
        "SerialNumber",
        "KeyCodeforConfigMenu",
        "Installer1",
        "Installer2",
        "PinCode",
        "Pincode",
        "Passcode",
        "Password",
        "ApiToken",
        "Secret",
    ],
)
def test_dump_still_redacts_sensitive_register_names(name: str) -> None:
    assert DUMP._redact("1234", name) == "<redacted>"
    assert DUMP._redact(None, name) is None


# Intent: the shipped sensitive-name sets contain no short fragment that matches inside ordinary words.
# Why: short fragments in the substring set are how "code" and "pin" hid the status code in the first place.
def test_substring_set_holds_only_unambiguous_fragments() -> None:
    assert all(len(fragment) >= 5 for fragment in REDACTION.SENSITIVE_FIELDS)
    assert {"code", "pin", "bc"} <= set(REDACTION.SENSITIVE_WORDS)
