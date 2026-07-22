"""Data models for EBUS backend."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

COMPRESSOR_ACTIVE_STATUS_CODES = {104, 114, 134}
COMPRESSOR_STATUS_CODES = {
    34,
    100,
    101,
    102,
    103,
    107,
    111,
    112,
    113,
    117,
    125,
    132,
    133,
    135,
    137,
    141,
    142,
    151,
    152,
    202,
    240,
    252,
    255,
    256,
    260,
    275,
    277,
    280,
    281,
    282,
    283,
    284,
    285,
    286,
    287,
    288,
    289,
    302,
    303,
    304,
    305,
    306,
    308,
    312,
    314,
    351,
    516,
    575,
    581,
    590,
} | COMPRESSOR_ACTIVE_STATUS_CODES


@dataclass
class EbusdRegister:
    circuit: str
    name: str
    fields: list[str]
    value: dict[str, str | None] = field(default_factory=dict)
    has_data: bool = False
    writable: bool = False

    @property
    def key(self) -> str:
        # Dot-separated circuit.name unique identifier
        return f"{self.circuit}.{self.name}"


# Return whether current compressor state explicitly indicates idle.
def compressor_is_idle(registers: Mapping[str, EbusdRegister]) -> bool:
    status = registers.get("hmu.RunDataStatuscode")
    raw_status = status.value.get("value") if status else None
    if raw_status is not None:
        try:
            status_code = int(raw_status)
        except (TypeError, ValueError):
            status_code = None
        if status_code in COMPRESSOR_ACTIVE_STATUS_CODES:
            return False
        if status_code in COMPRESSOR_STATUS_CODES:
            return True

    signals: list[float] = []
    for key in ("hmu.RunDataCompressorSpeed", "hmu.CurrentCompressorUtil"):
        register = registers.get(key)
        raw_value = register.value.get("value") if register else None
        try:
            signals.append(float(raw_value))
        except (TypeError, ValueError):
            continue
    return bool(signals) and all(value == 0 for value in signals)


# Clear cached compressor power when discovery confirms the compressor is idle.
def set_idle_compressor_power(
    registers: Mapping[str, EbusdRegister],
    discovered_power: EbusdRegister | None,
) -> None:
    power = registers.get("hmu.CurrentConsumedPower")
    if discovered_power and not discovered_power.has_data and power and compressor_is_idle(registers):
        power.value["value"] = "0"
        power.has_data = True


CIRCUIT_NAMES: dict[str, str] = {
    "hmu": "Vaillant aroTHERM (Heat Pump)",
    "ctlv2": "Vaillant CTLV2 (Heating Control)",
    "z1": "Woonkamer (Z1)",
    "dhw": "Boiler (DHW)",
    "Broadcast": "Vaillant eBUS (Diagnostic)",
    "vwz": "Vaillant VWZ (Ventilation)",
    "global": "ebusd (Daemon)",
    "scan": "Scan",
}


@dataclass
class RegisterMeta:
    friendly_name: str = ""
    icon: str = ""
    unit: str = ""
    device_class: str = ""
    state_class: str = ""
    entity_category: str = ""
    writable: bool = False
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    options: list[str] | None = None
    enabled: bool = True
    entity_type: str = ""
    device_circuit: str | None = None


@dataclass
class WriteResult:
    success: bool
    error_message: str = ""
    verified_value: str | None = None
