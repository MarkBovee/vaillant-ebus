"""Default mapping metadata for all ebusd registers."""

from __future__ import annotations

from datetime import datetime

from .hardware_profiles import (
    HMUX0_PRECISE_TEMPERATURE,
    HMUX0_SW0303,
    HMUX0_SW0407,
    VWZ_STATION_76,
    VWZIO_SW0500,
    HardwareProfile,
    has_current_unique_scan_identity,
    profile_owner,
    scan_matches,
)
from .models import DeviceGraph, RegisterMeta, ScanIdentity, is_controller_circuit, is_heat_pump_circuit
from .register_map_controller import CONTROLLER_REGISTERS
from .register_map_heat_pump import HEAT_PUMP_AND_BOILER_REGISTERS
from .register_map_other import SYSTEM_AND_OTHER_REGISTERS

HMUX0_SW0407_FALLBACK_BLOCKLIST: frozenset[str] = frozenset(
    {
        "Status00",
        "Status01",
        "Status07",
        "BuildingCircuitFlow",
        "CopCooling",
        "CopCoolingMonth",
        "CopHc",
        "CopHcMonth",
        "CopHwc",
        "CopHwcMonth",
        "CurrentCompressorUtil",
        "CurrentConsumedPower",
        "CurrentYieldPower",
        "FlowTemp",
        "FlowTemperature",
        "HoursCool",
        "LiveMonitorCurrentConsumedPower",
        "SourceTempInput",
        "SourceTempOutput",
        "TotalEnergyUsage",
        "YieldCoolDay",
        "YieldCooling",
        "YieldCoolingMonth",
        "YieldHc",
        "YieldHcDay",
        "YieldHcMonth",
        "YieldHwc",
        "YieldHwcDay",
        "YieldHwcMonth",
    }
)
HMUX0_SW0407_PASSIVE_REGISTER_NAMES: frozenset[str] = frozenset(
    {
        "RunDataStatuscode",
        "RunDataCompressorSpeed",
        "RunDataElPowerConsumption",
        "RunDataBuildingCPumpPower",
        "KmKreisVerflTemp",
        "UnterkuehlungSoll",
        "UnterkuehlungIst",
        "EEVAuslassTemp",
        "KmKreisKompEinlTemp",
        "KmKreisKompAuslTemp",
        "KmKreisHochdruck",
        "PowerConsumptionHmu",
        "CompressorHc",
        "CompressorHwc",
    }
)
HMUX0_SW0407_FALLBACK_NAMES: frozenset[str] = frozenset(
    item.casefold() for item in HMUX0_SW0407_FALLBACK_BLOCKLIST | HMUX0_SW0407_PASSIVE_REGISTER_NAMES
)
HMUX0_SW0407_ENVYIELD_REGISTERS: frozenset[str] = frozenset(
    {
        "HcEnvYieldTotal",
        "HcEnvYieldDay",
        "HcEnvYieldMonth",
        "HwcEnvYieldTotal",
        "HwcEnvYieldDay",
        "HwcEnvYieldMonth",
    }
)
VWZIO_SW0500_FALLBACK_BLOCKLIST: frozenset[str] = frozenset(
    {"PowerConsumptionVwz", "RunStatsImmersionHeaterHwc", "HeaterYieldHwcTotal", "Status01"}
)
VWZIO_SW0500_FALLBACK_NAMES: frozenset[str] = frozenset(item.casefold() for item in VWZIO_SW0500_FALLBACK_BLOCKLIST)


# Intent: return the discovered circuit only for the exact HMUX0 firmware whose map probes are unavailable.
# Why: the fallback blocklist must not leak to other heat-pump variants or guessed circuits.
def hmux0_sw0407_circuit(graph: DeviceGraph | None) -> str | None:
    return profile_owner(graph, HMUX0_SW0407)


# Intent: identify HMUX0 circuits whose latest scan evidence cannot authorize fallback polling.
# Why: retained firmware metadata must not bypass hardware-specific blocklists after incomplete or conflicting scans.
def hmux0_uncertain_scan_circuits(graph: DeviceGraph | None) -> frozenset[str]:
    if graph is None:
        return frozenset()
    return frozenset(
        node.circuit
        for node in graph.nodes.values()
        if node.device_type.name == "HEAT_PUMP"
        and (
            node.scan_type.casefold() == "hmux0"
            or any(
                row.scan_type.casefold() == "hmux0"
                and _normalize_scan_name(node.circuit) == _normalize_scan_name(row.scan_type)
                for row in graph.scan_identities
            )
        )
        and not has_current_unique_scan_identity(graph, node)
    )


# Intent: normalize a scan identity or circuit name for generic ownership comparison.
# Why: incomplete scan rows still need to identify the circuit whose hardware fallback must fail closed.
def _normalize_scan_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


# Intent: share HMUX0 fallback restrictions between coordinator polling and dump map probes.
# Why: both readers must block confirmed SW0407 and uncertain current scan identities identically.
def hmux0_fallback_blocked_circuits(graph: DeviceGraph | None) -> frozenset[str]:
    blocked = set(hmux0_uncertain_scan_circuits(graph))
    sw0407 = hmux0_sw0407_circuit(graph)
    if sw0407 is not None:
        blocked.add(sw0407)
    return frozenset(blocked)


# Intent: identify HMUX0 scan evidence for one physical heat-pump owner, including aliases.
# Why: ebusd may expose a scanned HMUX0 device through the logical `hmu` circuit.
def hmux0_owner_scan(graph: DeviceGraph | None) -> tuple[str, ScanIdentity] | None:
    if graph is None:
        return None
    owners = [node for node in graph.nodes.values() if node.device_type.name == "HEAT_PUMP"]
    scans = [row for row in graph.scan_identities if row.scan_type.casefold() == "hmux0"]
    identified = [
        node
        for node in owners
        if node.scan_type.casefold() == "hmux0" and has_current_unique_scan_identity(graph, node)
    ]
    if len(scans) == 1 and len(identified) == 1:
        return identified[0].circuit, scans[0]
    if not graph.scan_identities and len(owners) == 1 and owners[0].scan_type.casefold() == "hmux0":
        return None
    if len(owners) != 1 or len(scans) != 1:
        return None
    node = owners[0]
    scan = scans[0]
    if node.scan_type and node.scan_type.casefold() != "hmux0":
        return None
    return node.circuit, scan


# Intent: HMUX0 firmware revisions (with HW0504) whose B509 RunDataFlowTemp/RunDataReturnTemp use the 1/16 degC layout.
# Why: SW0303 was confirmed live (issue #171) and SW0406 answers the same layout (27.3125 read on SW0406/HW0504);
# other HMUX0 revisions returned absurd decodes (issue #99), so they stay out until they have their own evidence.
HMUX0_PRECISE_TEMPERATURE_SW_VERSIONS: frozenset[str] = HMUX0_PRECISE_TEMPERATURE.sw


# Intent: return the HMUX0 owner circuit only when its complete, current, unique scan matches the given firmware set.
# Why: retained node firmware fields cannot authorize a definition or an active read after a partial refresh.
def _hmux0_owner_for_profile(graph: DeviceGraph | None, profile: HardwareProfile) -> str | None:
    owner_scan = hmux0_owner_scan(graph)
    if graph is None or owner_scan is None:
        return None
    circuit, scan = owner_scan
    if not scan_matches(profile, scan):
        return None
    if (
        graph.scan_identities
        and graph.nodes[circuit].scan_type
        and not has_current_unique_scan_identity(graph, graph.nodes[circuit])
    ):
        return None
    return circuit


# Intent: allow SW0303-only runtime definitions only for current unique evidence.
# Why: ebusd's own CSV lacks the SW0303 RunData definitions, so only this revision needs a runtime `define`.
def hmux0_sw0303_owner(graph: DeviceGraph | None) -> str | None:
    return _hmux0_owner_for_profile(graph, HMUX0_SW0303)


# Intent: allow active RunDataFlowTemp/RunDataReturnTemp reads only for HMUX0 revisions with evidenced layout.
# Why: SW0406 units already receive both registers from ebusd's CSV and need polling, not a `define` (issue #171).
def hmux0_precise_temperature_owner(graph: DeviceGraph | None) -> str | None:
    return _hmux0_owner_for_profile(graph, HMUX0_PRECISE_TEMPERATURE)


# Intent: identify circuits that may be an HMUX0 owner when identity is incomplete.
# Why: only these candidates need the HMUX0-specific RunDataReturnTemp fallback restriction.
def hmux0_candidate_circuits(graph: DeviceGraph | None) -> frozenset[str]:
    if graph is None:
        return frozenset()
    if any(row.scan_type.casefold() == "hmux0" for row in graph.scan_identities):
        return frozenset(node.circuit for node in graph.nodes.values() if node.device_type.name == "HEAT_PUMP")
    if not graph.scan_identities:
        if any(node.scan_type.casefold() == "hmux0" for node in graph.nodes.values()):
            return frozenset(node.circuit for node in graph.nodes.values() if node.device_type.name == "HEAT_PUMP")
        return frozenset()
    return frozenset()


# Intent: resolve the discovered circuit only for the VWZIO scan with passive telemetry evidence.
# Why: SW0500/HW0504 supports captured B516/B511 frames, not HW5103's active Status01 probe.
def vwzio_sw0500_circuit(graph: DeviceGraph | None) -> str | None:
    return profile_owner(graph, VWZIO_SW0500)


# Intent: return the physical VWZ-family circuit currently scanned at slave 0x76.
# Why: generic VWZ/VWZIO Status01 definitions embed address 0x76 and cannot follow a matching device elsewhere.
def vwz_station_scan_76_circuit(graph: DeviceGraph | None) -> str | None:
    return profile_owner(graph, VWZ_STATION_76)


# BAI registers that are gas/combustion-specific and do not apply to the
# electric eloBLOCK. They remain discoverable, but are disabled by default
# when the confirmed eloBLOCK part number is present.
ELOBLOCK_GAS_REGISTERS: frozenset[str] = frozenset(
    {
        "Gasvalve",
        "Gasvalve3UC",
        "GasvalveASICFeedback",
        "GasvalveUC",
        "ExternGasvalve",
        "Fluegasvalve",
        "FluegasvalveOpen",
        "FanSpeed",
        "FanMaxSpeedOperation",
        "FanMinSpeedOperation",
        "TargetFanSpeed",
        "TargetFanSpeedOutput",
        "Flame",
        "FlameSensingASIC",
        "Ignitor",
        "IonisationVoltageLevel",
        "AverageIgnitiontime",
        "MaxIgnitiontime",
        "CounterStartattempts1",
        "CounterStartattempts2",
        "CounterStartAttempts3",
        "CounterStartAttempts4",
        "HcStarts",
        "HwcStarts",
    }
)

# Multi-field registers: register key -> field names in semicolon order of the
# raw ebusd value. Field names follow the ebusd CSV definitions.
# Source: ebusd vaillant CSV (08.hmu.csv) + community dumps.
MULTI_FIELD_FIELDS: dict[str, list[str]] = {
    "hmu.Status01": ["temp", "temp_1", "temp_2", "temp_3", "temp_4", "pumpstate"],
    # VWZIO/VWZ Hydraulikstation Status01 (upstream PR #598) reuses the HMU
    # layout on address 0x76; the fields are parsed the same way.
    "vwz.Status01": ["temp", "temp_1", "temp_2", "temp_3", "temp_4", "pumpstate"],
    "vwzio.Status01": ["temp", "temp_1", "temp_2", "temp_3", "temp_4", "pumpstate"],
    "hmu.Status00": [
        "supplytemp",
        "waterpressure",
        "compressormodulation",
        "compressorstate",
        "heatingstate",
        "field6",
        "defrost",
        "compressorpower",
    ],
    "hmu.Status07": [
        "power",
        "dailyenvyield",
        "display_b0_heaterenabled",
        "display_b1",
        "display_b2_backupheater",
        "display_b3",
        "display_b4",
        "display_b5_noisereduction",
        "display_b6_dhwecomode",
        "display_b7",
        "heatermain_b0",
        "heatermain_b1_error",
        "heatermain_b2",
        "heatermain_b3_heating",
        "heatermain_b4_cooling",
        "heatermain_b5_pressureloss",
        "heatermain_b6",
        "heatermain_b7_warmwater",
        "displaypressure",
        "heaterbackup_b0",
        "heaterbackup_b1_error",
        "heaterbackup_b2",
        "heaterbackup_b3_heating",
        "heaterbackup_b4_cooling",
        "heaterbackup_b5_pressureloss",
        "heaterbackup_b6",
        "heaterbackup_b7_warmwater",
    ],
    "hmux0.Status01": ["temp", "temp_1", "temp_2", "temp_3", "temp_4", "pumpstate"],
    "bai.Status01": ["temp", "temp_1", "temp_2", "temp_3", "temp_4", "pumpstate"],
    "hmu.CompressorHc": ["runtime", "cycles"],
    "hmu.CompressorHwc": ["runtime", "cycles"],
    "hmu.RunStatsCompressorHc": ["runtime", "cycles"],
    "hmu.RunStatsCompressorHwc": ["runtime", "cycles"],
    "vwzio.RunStatsImmersionHeaterHwc": ["runtime", "cycles"],
    "hmu.RunDataElPowerConsumption": ["value"],
    # v32 gas boiler (ecoTEC plus via VR32, bai.308523.inc + hcmode.inc).
    # Status01/Status02 share the hmu Status01 layout (hcmode.inc B511).
    # Single-field sensor registers expose only the first field; the trailing
    # fields are tempmirror/status values (see _templates.tsp models).
    "v32.Status01": ["temp", "temp_1", "temp_2", "temp_3", "temp_4", "pumpstate"],
    "v32.Status02": ["hwcmode", "temp0", "temp1", "temp0_1", "temp1_1"],
    "v32.FlowTemp": ["value"],
    "v32.ReturnTemp": ["value"],
    "v32.StorageTemp": ["value"],
    "v32.WaterPressure": ["value"],
    "v32.HwcTemp": ["value"],
    "v32.OutdoorstempSensor": ["value"],
}


# Intent: resolve multi-field metadata without depending on register-name casing.
# Why: lower-case Status registers must still expose their parsed fields.
def _multi_field_lookup(register_key: str) -> list[str] | None:
    fields = MULTI_FIELD_FIELDS.get(register_key)
    if fields is not None:
        return fields
    expected = register_key.casefold()
    fields = next((fields for key, fields in MULTI_FIELD_FIELDS.items() if key.casefold() == expected), None)
    if fields is not None:
        return fields
    if "." not in register_key:
        return None
    circuit, name = register_key.split(".", 1)
    for alias in metadata_circuits(circuit)[1:]:
        alias_key = f"{alias}.{name}".casefold()
        fields = next(
            (value for key, value in MULTI_FIELD_FIELDS.items() if key.casefold() == alias_key),
            None,
        )
        if fields is not None:
            return fields
    return None


def multi_field_fields(register_key: str) -> list[str] | None:
    """Return the field names for a multi-field register, or None."""
    return _multi_field_lookup(register_key)


# Identify parsed field keys so callers never poll them as ebusd registers.
def is_field_key(register_key: str) -> bool:
    return register_key.count(".") > 1


# Return the parent register key for a parsed field, preserving ordinary keys.
def parent_register_name(register_key: str) -> str:
    return register_key.rsplit(".", 1)[0] if is_field_key(register_key) else register_key


def split_multi_field(register_key: str, raw: str | None) -> dict[str, str | None]:
    """Split a raw register value into named fields; keep the raw value under "value"."""
    fields = _multi_field_lookup(register_key)
    values: dict[str, str | None] = {"value": raw}
    if not fields or raw is None:
        return values
    parts = raw.split(";")
    values.update({field: parts[i] if i < len(parts) else None for i, field in enumerate(fields)})
    return values


REGISTER_MAP: dict[str, RegisterMeta] = {
    **HEAT_PUMP_AND_BOILER_REGISTERS,
    **CONTROLLER_REGISTERS,
    **SYSTEM_AND_OTHER_REGISTERS,
}

# VWZIO/VWZ Hydraulikstation Status01 (upstream PR #598) reuses the HMU layout.
# Give it explicit metadata so the outside/storage fields are enabled here: the
# shared HMU entries disable those because a heat pump exposes them elsewhere.
for _vwz_circuit in ("vwz", "vwzio"):
    REGISTER_MAP.update(
        {
            f"{_vwz_circuit}.Status01": RegisterMeta(
                friendly_name="Status", icon="mdi:information", entity_category="diagnostic"
            ),
            f"{_vwz_circuit}.Status01.temp": RegisterMeta(
                friendly_name="Flow Temperature", device_class="temperature", unit="°C"
            ),
            f"{_vwz_circuit}.Status01.temp_1": RegisterMeta(
                friendly_name="Return Temperature", device_class="temperature", unit="°C"
            ),
            f"{_vwz_circuit}.Status01.temp_2": RegisterMeta(
                friendly_name="Outside Temperature", device_class="temperature", unit="°C"
            ),
            f"{_vwz_circuit}.Status01.temp_3": RegisterMeta(
                friendly_name="Hot Water Temperature", device_class="temperature", unit="°C"
            ),
            f"{_vwz_circuit}.Status01.temp_4": RegisterMeta(
                friendly_name="Storage Temperature", device_class="temperature", unit="°C"
            ),
            f"{_vwz_circuit}.Status01.pumpstate": RegisterMeta(
                friendly_name="Pump State", entity_type="binary_sensor", entity_category="diagnostic"
            ),
        }
    )
del _vwz_circuit


# Encode the W/V/QQ date bytes of the b516 energy-statistics API (upstream
# john30/ebusd-configuration issue #490). W is a month nibble that restarts at
# 0 for the last five months of the year, V a day nibble, and QQ counts
# half-years since 2000 plus one from August onwards. Each month owns two W
# values: days 1-15 stay on the even value (V=day), days 16-31 flip to the
# odd value with V=day-16. Worked examples from the thread: Feb 23 2025 ->
# "5732", Aug 24 2026 -> "1835".
def b516_date_bytes(now: datetime) -> str:
    qq = (now.year - 2000) * 2
    if now.month >= 8:
        qq += 1
        w = (now.month - 8) * 2
    else:
        w = now.month * 2
    if now.day > 15:
        w += 1
        v = now.day - 16
    else:
        v = now.day
    return f"{(w << 4) | v:02x}{qq:02x}"


# Intent: return metadata namespaces applicable to a discovered circuit.
# Why: physical controller numbers map to the shared controller metadata without becoming targets.
def metadata_circuits(circuit: str) -> tuple[str, ...]:
    if is_controller_circuit(circuit):
        return (circuit, "ctlv2", "hmu")
    if is_heat_pump_circuit(circuit):
        return (circuit, "hmu", "ctlv2")
    if circuit.casefold() in {"vwz", "vwzio"}:
        return (circuit, "vwz", "vwzio")
    if circuit.casefold() in {"bai", "v32"}:
        return (circuit, "hmu", "ctlv2")
    if circuit.isdigit():
        return (circuit, "ctlv2", "hmu")
    return (circuit,)


# Intent: look up register metadata without depending on ebusd name casing.
# Why: lower-case discovery keys must retain their canonical metadata and entity type.
def _map_get(key: str) -> RegisterMeta | None:
    meta = REGISTER_MAP.get(key)
    if meta is not None:
        return meta
    key_lower = key.casefold()
    return next((value for map_key, value in REGISTER_MAP.items() if map_key.casefold() == key_lower), None)


# Look up RegisterMeta by circuit.name, return empty meta if unknown
def get_meta(circuit: str, name: str, field: str = "value") -> RegisterMeta:
    key = f"{circuit}.{name}"
    if field != "value":
        key += f".{field}"
    meta = _map_get(key)
    # Fallbacks for hardware variants that expose the same register under a
    # different circuit. The ctlv2 variant can appear as its own circuit (do not
    # self-alias), and heat-pump statistics (Stat* energy, etc.) map onto the hmu
    # keys across controller circuits.
    if meta is None:
        for alt_circuit in metadata_circuits(circuit)[1:]:
            if alt_circuit == circuit:
                continue
            alt = f"{alt_circuit}.{name}"
            if field != "value":
                alt += f".{field}"
            meta = _map_get(alt)
            if meta is not None:
                break
    return meta or RegisterMeta()
