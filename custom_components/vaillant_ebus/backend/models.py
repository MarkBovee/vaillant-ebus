"""Data models for EBUS backend."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

# ebusd values that mean "no usable data" rather than a measured value.
# Exact-match set; prefix/substring forms are handled by is_no_data_value().
# "none" is deliberately excluded: RoomZoneMapping legitimately reports it.
EBUSD_NO_DATA_VALUES: frozenset[str] = frozenset({"", "-", "empty", "unknown", "unavailable"})


# Return whether an ebusd value carries no usable data: an exact sentinel,
# a "no data stored..." reply, an "(empty ...)" placeholder, or an "(ERR...)" error.
def is_no_data_value(raw: str | None) -> bool:
    if raw is None:
        return True
    low = raw.strip().lower()
    if low in EBUSD_NO_DATA_VALUES:
        return True
    return low.startswith("no data stored") or low.startswith("(empty ") or "(err" in low


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
    message_type: str = ""
    address: str = ""

    @property
    def key(self) -> str:
        # Dot-separated circuit.name unique identifier
        return f"{self.circuit}.{self.name}"


# String statuses that explicitly indicate the compressor is NOT idle.
_COMPRESSOR_ACTIVE_STATUS_STRINGS: set[str] = {
    "hwc_compressor_active",
    "heat_compressor_active",
    "cooling_compressor_active",
    "cool_compressor_active",
    "defrost",
}

# String statuses that explicitly indicate the compressor IS idle.
_COMPRESSOR_IDLE_STATUS_STRINGS: set[str] = {
    "standby",
}

# Map ebusd compressor status strings to human-readable labels.
COMPRESSOR_STATUS_LABELS: dict[str, str] = {
    "standby": "Standby",
    "hwc_compressor_active": "Active (DHW)",
    "heat_compressor_active": "Active (Heating)",
    "cooling_compressor_active": "Active (Cooling)",
    "cool_compressor_active": "Active (Cooling)",
    "heat_compressor_shutdown": "Shutdown (Heating)",
    "defrost": "Defrost",
}


# Return whether current compressor state explicitly indicates idle.
# hp_circuit lets callers whose heat pump answers on a non-"hmu" circuit
# resolve the status/speed registers correctly.
def compressor_is_idle(registers: Mapping[str, EbusdRegister], hp_circuit: str = "hmu") -> bool:
    status = registers.get(f"{hp_circuit}.RunDataStatuscode")
    raw_status = status.value.get("value") if status else None
    if raw_status is not None:
        try:
            status_code = int(raw_status)
        except (TypeError, ValueError):
            if raw_status in _COMPRESSOR_ACTIVE_STATUS_STRINGS:
                return False
            if raw_status in _COMPRESSOR_IDLE_STATUS_STRINGS:
                return True
            # Unknown string: don't assume idle
            return False

        if status_code in COMPRESSOR_ACTIVE_STATUS_CODES:
            return False
        if status_code in COMPRESSOR_STATUS_CODES:
            return True

    signals: list[float] = []
    for key in (f"{hp_circuit}.RunDataCompressorSpeed", f"{hp_circuit}.CurrentCompressorUtil"):
        register = registers.get(key)
        raw_value = register.value.get("value") if register else None
        if raw_value is None:
            continue
        try:
            signals.append(float(raw_value))
        except ValueError:
            continue
    return bool(signals) and all(value == 0 for value in signals)


# Bare register names zeroed out when the compressor is idle (stale-value
# prevention); they live on the resolved heat-pump circuit.
COMPRESSOR_ZERO_REGISTER_NAMES: frozenset[str] = frozenset(
    {
        "CurrentConsumedPower",
        "CurrentYieldPower",
        "CurrentCompressorUtil",
        "RunDataCompressorSpeed",
        "RunDataFan1Speed",
        "RunDataFan2Speed",
        "RunDataEEVPositionAbs",
    }
)


# Zero stale compressor-dependent registers when the compressor is idle.
def zero_idle_registers(registers: Mapping[str, EbusdRegister], hp_circuit: str = "hmu") -> None:
    if not compressor_is_idle(registers, hp_circuit):
        return
    for name in COMPRESSOR_ZERO_REGISTER_NAMES:
        reg = registers.get(f"{hp_circuit}.{name}")
        if reg:
            reg.value["value"] = "0"
            reg.has_data = True


CIRCUIT_NAMES: dict[str, str] = {
    "hmu": "Vaillant aroTHERM heat pump",
    "basv": "Vaillant BASV2 Heating Control",
    "z1": "Zone 1",
    "dhw": "Boiler (DHW)",
    "hc1": "Heating Circuit 1",
    "Broadcast": "Vaillant eBUS (Diagnostic)",
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
class SendResult:
    data: str
    error: str | None = None


@dataclass
class WriteResult:
    success: bool
    error_message: str = ""
    verified_value: str | None = None


class DeviceType(Enum):
    HEAT_PUMP = "heat_pump"
    HEATING_CONTROLLER = "controller"
    ZONE = "zone"
    DHW = "dhw"
    VENTILATION = "ventilation"
    PASSIVE_COOLING = "cooling"
    BUS = "bus"
    SOLAR = "solar"
    MIXING_MODULE = "mixing_module"
    UNKNOWN = "unknown"


@dataclass
class DeviceNode:
    circuit: str
    device_type: DeviceType
    registers: list[str] = field(default_factory=list)
    parent: str | None = None
    zone_circuits: list[str] = field(default_factory=list)
    heating_circuits: list[str] = field(default_factory=list)
    has_data: bool = False
    scan_type: str = ""
    scan_sw: str = ""
    scan_hw: str = ""


@dataclass
class DeviceGraph:
    nodes: dict[str, DeviceNode]
    raw_registers: dict[str, str]
    placeholder_registers: set[str]
