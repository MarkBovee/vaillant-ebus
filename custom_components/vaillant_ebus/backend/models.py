"""Data models for EBUS backend."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from warnings import deprecated

# ebusd values that mean "no usable data" rather than a measured value.
# Exact-match set; prefix/substring forms are handled by is_no_data_value().
# "none" is deliberately excluded: RoomZoneMapping legitimately reports it.
EBUSD_NO_DATA_VALUES: frozenset[str] = frozenset({"", "-", "empty", "unknown", "unavailable", "-.-.-"})

# Sensor fault statuses from the Vaillant sensor enum (Values_sensor in the
# upstream ebusd configuration: ok=0, circuit=85, cutoff=170). Registers whose
# trailing sensor-status field reports a fault (e.g. "116.06;circuit",
# "-60.44;cutoff") carry no usable measurement: the sensor is not present.
SENSOR_FAULT_STATUSES: frozenset[str] = frozenset({"circuit", "cutoff"})


# Return whether an ebusd value carries no usable data: an exact sentinel,
# a "no data stored..." reply, an "(empty ...)" placeholder, an "(ERR...)" error,
# a bare "ERR: ..." reply from a direct read, or a sensor-fault status.
def is_no_data_value(raw: str | None) -> bool:
    if raw is None:
        return True
    low = raw.strip().lower()
    if low in EBUSD_NO_DATA_VALUES:
        return True
    if low.endswith((";circuit", ";cutoff")) or low in SENSOR_FAULT_STATUSES:
        return True
    if ";" in low and all(part.strip() in EBUSD_NO_DATA_VALUES for part in low.split(";")):
        return True
    return low.startswith("no data stored") or low.startswith("(empty ") or low.startswith("err:") or "(err" in low


def is_valid_hmux0_return_temperature(raw: str) -> bool:
    """Return whether an HMUX0 return-temperature decode is physically plausible."""
    try:
        return -50 <= float(raw) <= 100
    except ValueError:
        return False


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
        except TypeError, ValueError:
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


# Operating states exposed by the derived Energy Manager State sensor.
OPERATING_STATE_HEATING = "Heating"
OPERATING_STATE_DHW = "DHW"
OPERATING_STATE_COOLING = "Cooling"
OPERATING_STATE_STANDBY = "Standby"
OPERATING_STATE_DEFROST = "Defrost"

_ON_BITS = frozenset({"on", "1", "true", "yes"})


def _value_is_on(value: str | None) -> bool:
    return not is_no_data_value(value) and (value or "").strip().lower() in _ON_BITS


def _clean(value: str | None) -> str:
    """Normalize a status string, treating ebusd no-data sentinels as empty."""
    return "" if is_no_data_value(value) else (value or "").strip().lower()


# Semicolon-separated field index of the releaseCooling bit in the hmu SetMode
# value. Field order: hcmode, flowtempdesired, hwctempdesired,
# hwcflowtempdesired, disablehc, disablehwctapping, disablehwcload,
# remoteControlHcPump, releaseBackup, releaseCooling.
SETMODE_RELEASE_COOLING_INDEX = 9


def _setmode_release_cooling(values: Mapping[str, str | None], hp_circuit: str) -> bool:
    """Return whether the heat pump requests cooling via SetMode.releaseCooling."""
    raw = values.get(f"{hp_circuit}.SetMode.value")
    if not raw:
        return False
    parts = str(raw).split(";")
    return len(parts) > SETMODE_RELEASE_COOLING_INDEX and parts[SETMODE_RELEASE_COOLING_INDEX].strip() == "1"


# Derive one Energy Manager State from the protocol data the integration
# already polls. This is a direct mapping of the compressor status and heater
# bits the controller reports, not an invented state machine:
#   - RunDataStatuscode (translated label or raw string): standby, defrost,
#     hwc_compressor_active, heat_compressor_active/*_prerun/*_overrun,
#     cool_compressor_active/*_prerun.
#   - HMUX0/HMU Status00 compressorstate/defrost: off, heating*, hot_water,
#     defrosting.
#   - HMU00 HW5103 Status07 heatermain bits: heating/cooling/warmwater.
#   - SetMode.releaseCooling: units without Status00/Status07 (e.g. HMU00/CTLV3)
#     keep RunDataStatuscode at 0 while a cooling period is active and expose
#     only this request flag.
# Returns None when no status field carries data, so the entity stays unknown
# rather than guessing a state.
def derive_operating_state(values: Mapping[str, str | None], hp_circuit: str | None) -> str | None:
    if not hp_circuit:
        return None
    status = _clean(values.get(f"{hp_circuit}.RunDataStatuscode.value"))
    compressor = _clean(values.get(f"{hp_circuit}.Status00.compressorstate"))
    heating_state = _clean(values.get(f"{hp_circuit}.Status00.heatingstate"))
    defrost_bit = values.get(f"{hp_circuit}.Status00.defrost")
    heating_bit = values.get(f"{hp_circuit}.Status07.heatermain_b3_heating")
    cooling_bit = values.get(f"{hp_circuit}.Status07.heatermain_b4_cooling")
    warmwater_bit = values.get(f"{hp_circuit}.Status07.heatermain_b7_warmwater")
    release_cooling = _setmode_release_cooling(values, hp_circuit)

    blob = " ".join(part for part in (status, compressor, heating_state) if part)
    if (
        not blob
        and not release_cooling
        and not any(_value_is_on(bit) for bit in (heating_bit, cooling_bit, warmwater_bit, defrost_bit))
    ):
        return None

    if "defrost" in blob or _value_is_on(defrost_bit):
        return OPERATING_STATE_DEFROST
    # A shutdown/standby status string means the controller reports no active
    # demand; it always wins over any request flag.
    if "shutdown" in blob or "standby" in blob:
        return OPERATING_STATE_STANDBY
    # An explicit Status00 compressor-off also reports idle regardless of any
    # cooling descriptor or request flag.
    if compressor in ("off", "0"):
        return OPERATING_STATE_STANDBY
    if "hwc" in blob or "hot_water" in blob or "dhw" in blob or _value_is_on(warmwater_bit):
        return OPERATING_STATE_DHW
    if "cool" in blob or _value_is_on(cooling_bit):
        return OPERATING_STATE_COOLING
    if "heat" in blob or _value_is_on(heating_bit):
        return OPERATING_STATE_HEATING
    # Fallback for units without Status00/Status07 (e.g. HMU00/CTLV3): they keep
    # RunDataStatuscode at 0 while a cooling period is active and only expose
    # the SetMode releaseCooling request flag. Never use it to contradict an
    # explicit Status00 compressor-off or a literal "off" status.
    if release_cooling and compressor not in ("off", "0") and status != "off":
        return OPERATING_STATE_COOLING
    if status in ("off", "0") or compressor in ("off", "0"):
        return OPERATING_STATE_STANDBY
    return OPERATING_STATE_STANDBY


CIRCUIT_NAMES: dict[str, str] = {
    "hmu": "Vaillant aroTHERM heat pump",
    "basv": "Vaillant BASV2 Heating Control",
    "bai": "Vaillant boiler controller",
    "sc": "Vaillant solar controller",
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


class ResolutionStatus(Enum):
    UNIQUE = "unique"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    FALLBACK = "fallback"


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


@dataclass(frozen=True)
class ResolutionResult:
    status: ResolutionStatus
    circuit: str | None = None
    node: DeviceNode | None = None
    reason: str = ""


@dataclass
class DeviceGraph:
    nodes: dict[str, DeviceNode]
    raw_registers: dict[str, str]
    placeholder_registers: set[str]

    # Register names that identify the heating/DHW controller. Their source
    # circuit is authoritative even when ebusd exposes them under a logical
    # sub-device: the DHW node owns ``ctlv3.HwcOpMode`` while the controller
    # node itself lists no Hwc registers.
    _CONTROL_REGISTERS: frozenset[str] = frozenset(
        {"HwcTempDesired", "HwcStorageTemp", "HwcOpMode", "Z1DayTemp", "Z1OpMode"}
    )

    # Source circuits that own a discovered controller/DHW control register.
    # Runtime-defined registers can create a bare ``ctlv2`` node on a bus whose
    # real controller is ``ctlv3``; the control register's source circuit, not
    # the logical device that happens to list it, identifies the controller.
    def _control_owner_circuits(self) -> set[str]:
        owners: set[str] = set()
        for key in self.raw_registers:
            if key.rsplit(".", 1)[-1] in self._CONTROL_REGISTERS:
                owners.add(key.split(".", 1)[0].casefold())
        return owners

    # Resolve the discovered heating controller without relying on node order.
    def heating_controller_result(self) -> ResolutionResult:
        controllers = sorted(
            (node for node in self.nodes.values() if node.device_type == DeviceType.HEATING_CONTROLLER),
            key=lambda node: node.circuit.casefold(),
        )
        control_owners = self._control_owner_circuits()
        control_candidates = [
            node
            for node in controllers
            if node.circuit.casefold() in control_owners
            or any(register.rsplit(".", 1)[-1] in self._CONTROL_REGISTERS for register in node.registers)
        ]
        # A BAI boiler interface also exposes DHW control registers
        # (HwcTempDesired), but it is a burner, not the heating controller.
        # When a real controller circuit (ctlv*/basv*/bass*) also owns control
        # registers, it is authoritative; a bare runtime-probed ctlv2 alias must
        # never outrank it. This is what makes ecoTEC/VRT380 (bai + ctlv0)
        # resolve deterministically instead of staying AMBIGUOUS.
        prefix_control = [
            node for node in control_candidates if node.circuit.casefold().startswith(("ctlv", "basv", "bass"))
        ]
        if len(prefix_control) == 1:
            node = prefix_control[0]
            return ResolutionResult(
                ResolutionStatus.UNIQUE, node.circuit, node, "control registers (controller prefix)"
            )
        if len(prefix_control) > 1:
            return ResolutionResult(ResolutionStatus.AMBIGUOUS, reason="multiple controllers own control registers")
        if len(control_candidates) == 1:
            node = control_candidates[0]
            return ResolutionResult(ResolutionStatus.UNIQUE, node.circuit, node, "control registers")
        if len(control_candidates) > 1:
            return ResolutionResult(ResolutionStatus.AMBIGUOUS, reason="multiple controllers own control registers")

        prefix_candidates: list[DeviceNode] = []
        for prefix in ("ctlv", "basv", "bass"):
            prefix_candidates.extend(node for node in controllers if node.circuit.lower().startswith(prefix))
        if len(prefix_candidates) == 1:
            node = prefix_candidates[0]
            return ResolutionResult(ResolutionStatus.UNIQUE, node.circuit, node, "controller circuit prefix")
        if len(prefix_candidates) > 1:
            return ResolutionResult(ResolutionStatus.AMBIGUOUS, reason="multiple controller circuit prefixes")
        if len(controllers) == 1:
            node = controllers[0]
            return ResolutionResult(ResolutionStatus.UNIQUE, node.circuit, node, "only controller")
        if controllers:
            return ResolutionResult(ResolutionStatus.AMBIGUOUS, reason="multiple heating controllers")
        return ResolutionResult(ResolutionStatus.MISSING, reason="no heating controller discovered")

    # Resolve the discovered heat pump without relying on node order.
    def heat_pump_result(self) -> ResolutionResult:
        heat_pumps = sorted(
            (node for node in self.nodes.values() if node.device_type == DeviceType.HEAT_PUMP),
            key=lambda node: node.circuit.casefold(),
        )
        if len(heat_pumps) == 1:
            node = heat_pumps[0]
            return ResolutionResult(ResolutionStatus.UNIQUE, node.circuit, node, "only heat pump")
        identified = [node for node in heat_pumps if node.scan_type]
        if len(identified) == 1:
            node = identified[0]
            return ResolutionResult(ResolutionStatus.UNIQUE, node.circuit, node, "identified heat pump")
        if heat_pumps:
            return ResolutionResult(ResolutionStatus.AMBIGUOUS, reason="multiple heat pumps")
        return ResolutionResult(ResolutionStatus.MISSING, reason="no heat pump discovered")

    # Preserve the compact node API for callers that only need a unique owner.
    def heating_controller(self) -> DeviceNode | None:
        return self.heating_controller_result().node

    # Preserve the compact node API for callers that only need a unique owner.
    def heat_pump(self) -> DeviceNode | None:
        return self.heat_pump_result().node

    # Resolve logical metadata circuits and expose ambiguity to safety-sensitive callers.
    def resolve_circuit_result(self, circuit: str) -> ResolutionResult:
        exact_node = self.nodes.get(circuit)
        expected_type = {
            "ctlv2": DeviceType.HEATING_CONTROLLER,
            "hmu": DeviceType.HEAT_PUMP,
            "bai": DeviceType.HEATING_CONTROLLER,
        }.get(circuit)
        if circuit == "ctlv2":
            # Runtime-defined registers can leave a bare ctlv2 node behind even
            # when the real controller answering DHW/heating is ctlv3. Prefer
            # the controller that owns the control registers; fall back to the
            # exact discovered node only when that ownership is not unique.
            result = self.heating_controller_result()
            if result.status == ResolutionStatus.UNIQUE:
                return result
            if exact_node is not None and exact_node.device_type == DeviceType.HEATING_CONTROLLER:
                return ResolutionResult(
                    ResolutionStatus.UNIQUE, exact_node.circuit, exact_node, "exact discovered circuit"
                )
            if result.status == ResolutionStatus.AMBIGUOUS:
                return ResolutionResult(result.status, circuit, reason=result.reason)
            return ResolutionResult(ResolutionStatus.MISSING, circuit, reason=result.reason)
        if exact_node is not None and (expected_type is None or exact_node.device_type == expected_type):
            return ResolutionResult(ResolutionStatus.UNIQUE, exact_node.circuit, exact_node, "exact discovered circuit")
        if exact_node is not None and expected_type is not None:
            return ResolutionResult(
                ResolutionStatus.AMBIGUOUS, circuit=circuit, reason="exact circuit has wrong device role"
            )
        if circuit == "bai":
            bai_controllers = sorted(
                (
                    node
                    for node in self.nodes.values()
                    if node.device_type == DeviceType.HEATING_CONTROLLER and node.circuit.lower().startswith("bai")
                ),
                key=lambda node: node.circuit.casefold(),
            )
            if len(bai_controllers) == 1:
                node = bai_controllers[0]
                return ResolutionResult(ResolutionStatus.UNIQUE, node.circuit, node, "only BAI controller")
            if bai_controllers:
                return ResolutionResult(ResolutionStatus.AMBIGUOUS, circuit=circuit, reason="multiple BAI controllers")
            return ResolutionResult(ResolutionStatus.MISSING, circuit, reason="no BAI controller discovered")
        if circuit == "hmu":
            result = self.heat_pump_result()
            if result.status == ResolutionStatus.UNIQUE:
                return result
            if result.status == ResolutionStatus.AMBIGUOUS:
                exact_node = self.nodes.get(circuit)
                if exact_node is not None:
                    return ResolutionResult(
                        ResolutionStatus.UNIQUE, exact_node.circuit, exact_node, "exact discovered circuit"
                    )
                return ResolutionResult(result.status, circuit, reason=result.reason)
            return ResolutionResult(ResolutionStatus.MISSING, circuit, reason=result.reason)
        return ResolutionResult(ResolutionStatus.FALLBACK, circuit, reason="literal circuit")

    # Deprecated compatibility wrapper. Ownership-sensitive callers must use
    # resolve_circuit_result() so unresolved topology cannot be mistaken for a circuit.
    @deprecated("Use resolve_circuit_result() for ownership-sensitive resolution")
    def resolve_circuit(self, circuit: str) -> str:
        result = self.resolve_circuit_result(circuit)
        return result.circuit or circuit
