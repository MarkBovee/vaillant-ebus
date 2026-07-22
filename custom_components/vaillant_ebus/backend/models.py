"""Data models for EBUS backend."""

from __future__ import annotations

from dataclasses import dataclass, field


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
        return f"{self.circuit}.{self.name}"


@dataclass
class Circuit:
    name: str
    registers: dict[str, EbusdRegister] = field(default_factory=dict)

    @property
    def friendly_name(self) -> str:
        return CIRCUIT_NAMES.get(self.name, self.name)

    @property
    def register_count(self) -> int:
        return len(self.registers)


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


def parse_find_value(raw: str) -> dict[str, str | None]:
    parts = raw.split(";")
    return {str(i): (p if p != "-" else None) for i, p in enumerate(parts)}
