"""Decide which register names hold data that a shared discovery dump must hide."""

from __future__ import annotations

import re

# Fragments that identify a secret anywhere in a register name (for example SerialNumber, KeyCodeforConfigMenu,
# Installer1). Each is long enough that it does not occur inside an ordinary word.
SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {"serial", "keycode", "installer", "password", "secret", "token", "pincode", "passcode"}
)

# Short fragments that count only as a whole CamelCase word (PinCode, but not Statuscode or Mapping).
SENSITIVE_WORDS: frozenset[str] = frozenset({"bc", "code", "pin"})

_WORD_PATTERN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


# Intent: report whether a register name holds data that a shared dump must hide.
# Why: the old substring match for "code", "pin" and "bc" hid RunDataStatuscode, Z1RoomZoneMapping and SourceTempInput,
# which are the evidence an analysis needs (compressor mode, zone ownership), while real secrets must stay hidden.
def is_sensitive_register_name(name: str) -> bool:
    lowered = name.lower()
    if any(fragment in lowered for fragment in SENSITIVE_FIELDS):
        return True
    return any(word.lower() in SENSITIVE_WORDS for word in _WORD_PATTERN.findall(name))
