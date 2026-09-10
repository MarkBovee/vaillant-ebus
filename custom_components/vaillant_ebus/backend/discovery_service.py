"""Device discovery service — build structured device graph from ebusd find output."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, NamedTuple

from .models import DeviceGraph, DeviceNode, DeviceType, is_no_data_value

if TYPE_CHECKING:
    from .ebus_service import EbusService

_LOGGER = logging.getLogger(__name__)

HIDDEN_BROADCAST = {"id", "idanswer", "load", "signoflife"}
ALWAYS_HIDDEN = {"memory"}
HIDDEN_DEVICE_KEYWORDS = {"broadcast", "scan", "general"}
HIDDEN_REGISTER_NAMES = {"tmpb516montheven"}
SECONDARY_ZONE_CIRCUITS = frozenset({"hc2", "hc3", "z2", "z3"})


class ParsedRegister(NamedTuple):
    circuit: str
    name: str
    value: str | None


class ScanEntry(NamedTuple):
    address: str
    scan_type: str
    scan_sw: str
    scan_hw: str


class ScanMetadata(NamedTuple):
    scan_type: str
    scan_sw: str
    scan_hw: str


class DiscoveryService:
    def __init__(self, ebus: EbusService) -> None:
        self._ebus = ebus

    async def discover(self) -> DeviceGraph:
        find_lines = await self._ebus.find_registers()
        _LOGGER.info("Starting device discovery via ebusd find (%d lines)", len(find_lines))
        graph = self.build_device_graph(find_lines)
        type_counts: dict[str, int] = {}
        for node in graph.nodes.values():
            k = node.device_type.value
            type_counts[k] = type_counts.get(k, 0) + 1
            _LOGGER.info(
                "Discovered device %s: type=%s scan=%s regs=%d with_data=%d",
                node.circuit,
                node.device_type.name,
                node.scan_type or "-",
                len(node.registers),
                sum(1 for rk in node.registers if rk in graph.raw_registers),
            )
        _LOGGER.info(
            "Device graph: %d devices (%s)",
            len(graph.nodes),
            ", ".join(f"{v} {k}" for k, v in sorted(type_counts.items())),
        )
        return graph

    @staticmethod
    def _parse_register(line: str) -> ParsedRegister:
        """Parse a find line into (circuit, name, value_or_None)."""
        line = line.strip()
        if not line or "=" not in line:
            return ParsedRegister("", "", None)
        lhs, rhs = line.split("=", 1)
        parts = lhs.strip().split(None, 1)
        circuit = parts[0]
        name = parts[1].strip() if len(parts) > 1 else ""
        val = rhs.strip()
        if is_no_data_value(val):
            return ParsedRegister(circuit, name, None)
        if circuit.lower() == "hmu" and name.lower() == "sourcetempinput":
            try:
                if float(val) < -100:
                    return ParsedRegister(circuit, name, None)
            except ValueError:
                return ParsedRegister(circuit, name, None)
        return ParsedRegister(circuit, name, val)

    @staticmethod
    def _parse_scan(line: str) -> ScanEntry | None:
        """Parse a scan metadata line into (scan_addr, TYPE, SW, HW) or None."""
        line = line.strip()
        if not line or "=" not in line:
            return None
        lhs, rhs = line.split("=", 1)
        if not lhs.strip().lower().startswith("scan"):
            return None
        rhs = rhs.strip()
        if rhs.lower() == "no data stored":
            return None
        parts = rhs.split(";")
        if len(parts) != 4:
            return None
        if all("=" in part for part in parts):
            metadata = dict(part.split("=", 1) for part in parts)
            if {"MF", "ID", "SW", "HW"} <= metadata.keys():
                return ScanEntry(lhs.strip(), metadata["ID"], metadata["SW"], metadata["HW"])
        return ScanEntry(lhs.strip(), parts[1].strip(), parts[2].strip(), parts[3].strip())

    @staticmethod
    def _is_hidden(register_key: str, has_data: dict[str, bool] | None = None) -> bool:
        """Return True if register_key should not produce an HA entity."""
        rk_lower = register_key.lower()
        if rk_lower in ("hmu.flowtemperature", "broadcast.flowtemp"):
            return True
        if "." not in register_key:
            return True
        circuit, name = register_key.split(".", 1)
        c_lower = circuit.lower()
        n_lower = name.lower()
        if n_lower in HIDDEN_REGISTER_NAMES:
            return True
        if c_lower.startswith("scan"):
            return True
        if c_lower in ALWAYS_HIDDEN or any(kw in c_lower for kw in HIDDEN_DEVICE_KEYWORDS):
            return True
        if n_lower.startswith(("cctimer_", "hwctimer_", "z1timer_", "z2timer_", "z3timer_")):
            return True
        if n_lower.startswith("prfuelsum"):
            return True
        if n_lower.startswith(("installer", "phonenumber", "keycode", "maintenancedate", "maintenancedue")):
            return True
        if n_lower in ("general_valuerange", "date_time", "datetime"):
            return True
        if c_lower == "broadcast" and n_lower in HIDDEN_BROADCAST:
            return True
        if has_data:
            if c_lower in SECONDARY_ZONE_CIRCUITS and not has_data.get(c_lower):
                return True
            for suffix in SECONDARY_ZONE_CIRCUITS:
                if not has_data.get(suffix) and (n_lower.startswith(suffix) or n_lower.endswith(f"_{suffix}")):
                    return True
        return False

    @staticmethod
    def categorize_circuit(
        circuit: str,
        registers: list[str],
        scan_type: str = "",
    ) -> DeviceType:
        """Categorize a circuit by device type — dynamic, no allowlist."""
        if scan_type:
            result = _categorize_by_scan_type(circuit, scan_type)
            if result is not None:
                return result

        result = _categorize_by_prefix(circuit)
        if result is not None:
            return result

        result = _categorize_by_registers(circuit, registers)
        if result is not None:
            return result

        _LOGGER.info("Circuit %s categorized as UNKNOWN", circuit)
        return DeviceType.UNKNOWN

    @staticmethod
    def build_device_graph(find_lines: list[str]) -> DeviceGraph:
        raw_registers: dict[str, str] = {}
        placeholder_registers: set[str] = set()
        scan_entries: list[ScanEntry] = []
        regs_by_circuit: dict[str, list[str]] = {}

        for line in find_lines:
            scan = DiscoveryService._parse_scan(line)
            if scan is not None:
                scan_entries.append(scan)
                continue

            circuit, name, value = DiscoveryService._parse_register(line)
            if not circuit or not name:
                continue

            if circuit.lower() == "hmu" and name.lower() == "sourcetempinput":
                raw_value = line.split("=", 1)[1].strip()
                if value is None and raw_value:
                    continue

            register_key = f"{circuit}.{name}"
            if value is not None:
                raw_registers[register_key] = value
            else:
                placeholder_registers.add(register_key)

            regs_by_circuit.setdefault(circuit, []).append(register_key)

        scan_by_circuit = _match_scan_to_circuits(scan_entries, regs_by_circuit)

        has_data = _compute_has_data(regs_by_circuit, raw_registers)
        sub_devices = _detect_sub_devices(regs_by_circuit)

        nodes: dict[str, DeviceNode] = {}
        assigned_regs: set[str] = set()

        for sub_key, (parent_circuit, d_type) in sub_devices.items():
            sub_name = _sub_name(sub_key)
            regs = _collect_sub_regs(sub_name, parent_circuit, regs_by_circuit, sub_devices)
            if not regs:
                continue
            assigned_regs.update(regs)
            existing = nodes.get(sub_name)
            if existing is not None:
                # Two source circuits can map to one logical device name (for
                # example ctlv3/dhw and hmu/dhw both become "dhw"). Merge their
                # registers so a live variant is not silently dropped by the
                # later, data-less one.
                merged = list(existing.registers)
                merged.extend(rk for rk in regs if rk not in set(existing.registers))
                nodes[sub_name] = DeviceNode(
                    circuit=sub_name,
                    device_type=existing.device_type,
                    registers=merged,
                    has_data=existing.has_data or any(raw_registers.get(rk) is not None for rk in regs),
                )
                continue
            nodes[sub_name] = DeviceNode(
                circuit=sub_name,
                device_type=d_type,
                registers=regs,
                has_data=any(raw_registers.get(rk) is not None for rk in regs),
            )

        for circuit, reg_keys in regs_by_circuit.items():
            c_lower = circuit.lower()
            if c_lower.startswith("scan"):
                continue
            if c_lower in ALWAYS_HIDDEN or any(kw in c_lower for kw in HIDDEN_DEVICE_KEYWORDS):
                continue
            if _is_address_circuit(circuit):
                continue

            scan_info = scan_by_circuit.get(circuit)
            scan_type = scan_info.scan_type if scan_info else ""
            scan_sw = scan_info.scan_sw if scan_info else ""
            scan_hw = scan_info.scan_hw if scan_info else ""

            own_regs: list[str] = []
            for rk in reg_keys:
                if rk in assigned_regs:
                    continue
                if DiscoveryService._is_hidden(rk, has_data):
                    continue
                own_regs.append(rk)

            device_type = DiscoveryService.categorize_circuit(circuit, own_regs, scan_type)
            circuit_has_data = any(raw_registers.get(rk) is not None for rk in own_regs)
            if not circuit_has_data and device_type == DeviceType.UNKNOWN:
                continue

            node = DeviceNode(
                circuit=circuit,
                device_type=device_type,
                registers=own_regs,
                has_data=circuit_has_data,
                scan_type=scan_type,
                scan_sw=scan_sw,
                scan_hw=scan_hw,
            )

            for sub_key, (pc, _) in sub_devices.items():
                if pc != circuit:
                    continue
                sub_name = _sub_name(sub_key)
                if sub_name.startswith("z") and sub_name[1:].isdigit():
                    node.zone_circuits.append(sub_name)
                    zn = sub_name[1:]
                    hc_key = f"{pc}/hc{zn}"
                    if hc_key in sub_devices:
                        node.heating_circuits.append(f"hc{zn}")

            nodes[circuit] = node

        _apply_relationships(nodes, sub_devices)

        return DeviceGraph(
            nodes=nodes,
            raw_registers=raw_registers,
            placeholder_registers=placeholder_registers,
        )


# Extract the logical sub-device name from its parent-qualified key.
def _sub_name(sub_key: str) -> str:
    return sub_key.split("/", 1)[1]


def _is_address_circuit(circuit: str) -> bool:
    """Return whether ebusd used a raw hexadecimal bus address as circuit name."""
    try:
        int(circuit, 16)
    except ValueError:
        return False
    return True


# Determine whether each source circuit contains at least one live value.
def _compute_has_data(
    regs_by_circuit: dict[str, list[str]],
    raw_registers: dict[str, str],
) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for circuit, reg_keys in regs_by_circuit.items():
        c_lower = circuit.lower()
        broadcast_hidden = HIDDEN_BROADCAST if c_lower == "broadcast" else set()
        result[circuit] = any(
            raw_registers.get(rk) is not None for rk in reg_keys if rk.split(".", 1)[1].lower() not in broadcast_hidden
        )
    return result


# Detect logical DHW, zone, and heating-circuit devices within each source circuit.
def _detect_sub_devices(
    regs_by_circuit: dict[str, list[str]],
) -> dict[str, tuple[str, DeviceType]]:
    result: dict[str, tuple[str, DeviceType]] = {}
    for circuit, reg_keys in regs_by_circuit.items():
        c_lower = circuit.lower()
        if any(kw in c_lower for kw in HIDDEN_DEVICE_KEYWORDS) or c_lower in ALWAYS_HIDDEN:
            continue
        reg_names = {rk.split(".", 1)[1] for rk in reg_keys if "." in rk}
        hwc_seen = any(n.lower().startswith(("hwc", "cylinder", "maxcylinder", "dhw", "solar")) for n in reg_names)
        if hwc_seen:
            result[f"{circuit}/dhw"] = (circuit, DeviceType.DHW)
        for n in reg_names:
            zn = _extract_zn(n)
            if zn:
                result[f"{circuit}/z{zn}"] = (circuit, DeviceType.ZONE)
        for n in reg_names:
            hcn = _extract_hcn(n)
            if hcn:
                sub_key = f"{circuit}/hc{hcn}"
                if sub_key not in result:
                    result[sub_key] = (circuit, DeviceType.ZONE)
    return result


def _extract_zn(name: str) -> str:
    """Extract zone number from register name like 'Z1DayTemp' → '1'."""
    if not name or len(name) < 2:
        return ""
    n_upper = name.upper() if name[0].isupper() else name.lower()
    if n_upper[0] != "Z" or not n_upper[1].isdigit():
        return ""
    zn = n_upper[1]
    idx = 2
    while idx < len(n_upper) and n_upper[idx].isdigit():
        zn += n_upper[idx]
        idx += 1
    return zn


def _extract_hcn(name: str) -> str:
    """Extract heating circuit number from register name like 'Hc1FlowTemp' → '1'."""
    if not name or len(name) < 3:
        return ""
    n_upper = name.upper() if name[0].isupper() else name.lower()
    if not n_upper.startswith("HC") or not n_upper[2].isdigit():
        return ""
    hcn = n_upper[2]
    idx = 3
    while idx < len(n_upper) and n_upper[idx].isdigit():
        hcn += n_upper[idx]
        idx += 1
    return hcn


# Gather the visible source-circuit registers that belong to one logical device.
def _collect_sub_regs(
    sub_name: str,
    parent_circuit: str,
    regs_by_circuit: dict[str, list[str]],
    sub_devices: dict[str, tuple[str, DeviceType]],
) -> list[str]:
    result: list[str] = []
    for rk in regs_by_circuit.get(parent_circuit, []):
        if DiscoveryService._is_hidden(rk):
            continue
        name = rk.split(".", 1)[1]
        if _name_belongs_to_sub(name, sub_name):
            result.append(rk)
    return result


# Match a register name to a logical zone, heating circuit, or DHW device.
def _name_belongs_to_sub(name: str, sub_name: str) -> bool:
    if sub_name.startswith("z") and sub_name[1:].isdigit():
        zn = sub_name[1:]
        return _extract_zn(name) == zn
    if sub_name.startswith("hc") and sub_name[2:].isdigit():
        hcn = sub_name[2:]
        return _extract_hcn(name) == hcn
    if sub_name == "dhw":
        return name.lower().startswith(("hwc", "cylinder", "maxcylinder", "dhw", "solar"))
    return False


# Normalize a circuit name or scan TYPE for comparison: case-insensitive and
# underscore-insensitive (VR_71 ↔ VR71). Deliberately conservative — no other
# characters or digits are stripped, so HMU, HMUX0 and HMU00 remain
# distinguishable from each other.
def _normalize_name(name: str) -> str:
    return name.replace("_", "").lower()


# Stable family of a circuit name or scan TYPE: trailing variant digits
# removed (HMU00 → hmu, HMUX0 → hmux, BASV3 → basv). Digits inside the name
# are kept so related families (hmu vs hmux) never collapse into one.
def _name_family(name: str) -> str:
    return _normalize_name(name).rstrip("0123456789")


# Associate ebusd scan metadata with the discovered circuits it describes.
#
# Matching runs from strongest to weakest evidence and a circuit is bound at
# most once:
#   1. NETX2 → Broadcast (fixed relationship in the ebusd configuration).
#   2. Exact normalized TYPE ↔ circuit match (HMUX0 ↔ hmux0, CTLV3 ↔ ctlv3).
#   3. Family match after stripping variant digits (HMU00 ↔ hmu, BASV3 ↔ basv).
#   4. Stable family-prefix fallback (circuit starts with the scan family).
# A scan entry is consumed by at most one circuit. Ambiguous associations are
# intentionally left unmatched instead of guessed: scan metadata drives device
# naming, classification and hardware-gated runtime definitions (HMUX0 SW/HW),
# so a wrong assignment poisons the graph. Identical repeated scan lines (find
# output may repeat them) collapse to the first occurrence, keeping the result
# deterministic regardless of duplication.
def _match_scan_to_circuits(
    scan_entries: Sequence[ScanEntry | tuple[str, str, str, str]],
    regs_by_circuit: dict[str, list[str]],
) -> dict[str, ScanMetadata]:
    circuit_names = [c for c in regs_by_circuit if not c.lower().startswith("scan")]

    scans_by_type: dict[str, ScanMetadata] = {}
    conflicting_types: set[str] = set()
    for entry in scan_entries:
        normalized_entry = entry if isinstance(entry, ScanEntry) else ScanEntry(*entry)
        scan_type = normalized_entry.scan_type
        scan_key = scan_type.casefold()
        if scan_key in conflicting_types:
            continue
        existing = scans_by_type.get(scan_key)
        if existing is None:
            scans_by_type[scan_key] = ScanMetadata(scan_type, normalized_entry.scan_sw, normalized_entry.scan_hw)
            continue
        if existing.scan_sw and normalized_entry.scan_sw and existing.scan_sw != normalized_entry.scan_sw:
            conflicting_types.add(scan_key)
            scans_by_type.pop(scan_key, None)
            continue
        if existing.scan_hw and normalized_entry.scan_hw and existing.scan_hw != normalized_entry.scan_hw:
            conflicting_types.add(scan_key)
            scans_by_type.pop(scan_key, None)
            continue
        scans_by_type[scan_key] = ScanMetadata(
            existing.scan_type,
            existing.scan_sw or normalized_entry.scan_sw,
            existing.scan_hw or normalized_entry.scan_hw,
        )

    scans = list(scans_by_type.values())

    result: dict[str, ScanMetadata] = {}

    # Priority 1: NETX2 always describes the Broadcast pseudo-circuit.
    for scan in scans:
        if scan.scan_type.lower() == "netx2":
            result["Broadcast"] = scan

    # Priority 2: exact normalized match. Skipped when several circuits share
    # the normalized name — assigning one of them would be a coin flip.
    for scan in scans:
        scan_type = scan.scan_type
        if scan_type.lower() == "netx2":
            continue
        exact_candidates = [c for c in circuit_names if _normalize_name(c) == _normalize_name(scan_type)]
        if len(exact_candidates) == 1 and exact_candidates[0] not in result:
            result[exact_candidates[0]] = scan

    claimed = {info.scan_type.lower() for info in result.values()}

    # Priority 3: family match on digit-stripped names (HMU00 ↔ hmu, BASV3 ↔
    # basv). Only when exactly one circuit carries the family and exactly one
    # unclaimed scan shares it; a family shared by several circuits (or a
    # family with several scan variants) stays unmatched.
    unmatched = [c for c in circuit_names if c not in result]
    family_counts: dict[str, int] = {}
    for ckt in unmatched:
        fam = _name_family(ckt)
        if fam:
            family_counts[fam] = family_counts.get(fam, 0) + 1
    for ckt in unmatched:
        fam = _name_family(ckt)
        if not fam or family_counts.get(fam, 0) != 1:
            continue
        family_candidates = [
            scan
            for scan in scans
            if scan.scan_type.lower() != "netx2"
            and scan.scan_type.lower() not in claimed
            and _name_family(scan.scan_type) == fam
        ]
        if len(family_candidates) == 1:
            result[ckt] = family_candidates[0]
            claimed.add(family_candidates[0].scan_type.lower())

    # Priority 4: prefix fallback for circuits whose name only shares the scan
    # family as a prefix. Used only when exactly one unclaimed scan and one
    # unmatched circuit claim each other; anything broader stays unmatched.
    for scan in scans:
        scan_type = scan.scan_type
        if scan_type.lower() == "netx2" or scan_type.lower() in claimed:
            continue
        fam = _name_family(scan_type)
        if not fam:
            continue
        # Multiple unclaimed variants of the same family (e.g. CTLV2 and
        # CTLV3) cannot be told apart by a bare prefix — skip the family.
        same_family = [
            scan.scan_type
            for scan in scans
            if scan.scan_type.lower() != "netx2"
            and scan.scan_type.lower() not in claimed
            and _name_family(scan.scan_type) == fam
        ]
        if len(same_family) != 1:
            continue
        claimants = [c for c in circuit_names if c not in result and _normalize_name(c).startswith(fam)]
        if len(claimants) == 1:
            result[claimants[0]] = scan
            claimed.add(scan_type.lower())

    return result


# Link discovered logical devices to their source circuit and heat-pump parents.
def _apply_relationships(
    nodes: dict[str, DeviceNode],
    sub_devices: dict[str, tuple[str, DeviceType]],
) -> None:
    heat_pumps = [n for n in nodes.values() if n.device_type == DeviceType.HEAT_PUMP]
    controllers = [n for n in nodes.values() if n.device_type == DeviceType.HEATING_CONTROLLER]
    heat_pump = heat_pumps[0] if len(heat_pumps) == 1 else None
    controller = controllers[0] if len(controllers) == 1 else None

    if not heat_pump and not controller:
        return

    if heat_pump:
        for node in nodes.values():
            if node.circuit.lower() == "broadcast":
                node.parent = heat_pump.circuit
        if controller:
            controller.parent = heat_pump.circuit

    for sub_key, (parent_circuit, _) in sub_devices.items():
        sub_name = _sub_name(sub_key)
        if sub_name not in nodes:
            continue
        if parent_circuit in nodes:
            nodes[sub_name].parent = parent_circuit


_SCAN_TO_DEVICE: dict[str, DeviceType] = {
    "hmu": DeviceType.HEAT_PUMP,
    "hmu00": DeviceType.HEAT_PUMP,
    "hmux": DeviceType.HEAT_PUMP,
    "hmux0": DeviceType.HEAT_PUMP,
    "ctlv": DeviceType.HEATING_CONTROLLER,
    "ctlv1": DeviceType.HEATING_CONTROLLER,
    "ctlv2": DeviceType.HEATING_CONTROLLER,
    "basv": DeviceType.HEATING_CONTROLLER,
    "basv2": DeviceType.HEATING_CONTROLLER,
    "bass": DeviceType.HEATING_CONTROLLER,
    "bass3": DeviceType.HEATING_CONTROLLER,
    "bai": DeviceType.HEATING_CONTROLLER,
    "vwz": DeviceType.PASSIVE_COOLING,
    "vwz00": DeviceType.PASSIVE_COOLING,
    "vwzio": DeviceType.PASSIVE_COOLING,
    "netx": DeviceType.BUS,
    "netx2": DeviceType.BUS,
    "v32": DeviceType.VENTILATION,
    "sol": DeviceType.SOLAR,
    "sol00": DeviceType.SOLAR,
}

_PREFIX_TO_DEVICE: dict[str, DeviceType] = {
    "hmu": DeviceType.HEAT_PUMP,
    "hmux": DeviceType.HEAT_PUMP,
    "ctlv": DeviceType.HEATING_CONTROLLER,
    "basv": DeviceType.HEATING_CONTROLLER,
    "bass": DeviceType.HEATING_CONTROLLER,
    "bai": DeviceType.HEATING_CONTROLLER,
    "broadcast": DeviceType.BUS,
    "vwz": DeviceType.PASSIVE_COOLING,
    "vwzio": DeviceType.PASSIVE_COOLING,
    "v32": DeviceType.VENTILATION,
    "sol": DeviceType.SOLAR,
    "vr": DeviceType.MIXING_MODULE,
}


# Classify a circuit from the ebusd scan TYPE and its numeric-family prefix.
def _categorize_by_scan_type(circuit: str, scan_type: str) -> DeviceType | None:
    low = scan_type.lower()
    if low in _SCAN_TO_DEVICE:
        d_type = _SCAN_TO_DEVICE[low]
        _LOGGER.info("Circuit %s categorized as %s (scan TYPE=%s)", circuit, d_type.name, scan_type)
        return d_type
    prefix = low.rstrip("0123456789")
    if prefix in _SCAN_TO_DEVICE:
        d_type = _SCAN_TO_DEVICE[prefix]
        _LOGGER.info("Circuit %s categorized as %s (scan TYPE=%s prefix=%s)", circuit, d_type.name, scan_type, prefix)
        return d_type
    return None


# Classify a circuit from its stable ebusd circuit-name prefix.
def _categorize_by_prefix(circuit: str) -> DeviceType | None:
    c_lower = circuit.lower()
    for prefix, d_type in _PREFIX_TO_DEVICE.items():
        if c_lower.startswith(prefix):
            _LOGGER.info("Circuit %s categorized as %s (prefix '%s')", circuit, d_type.name, prefix)
            return d_type
    return None


# Classify a controller from characteristic heating or DHW register names.
def _categorize_by_registers(circuit: str, registers: list[str]) -> DeviceType | None:
    for rk in registers:
        name = rk.split(".", 1)[-1] if "." in rk else ""
        if name in ("Z1OpMode", "HwcOpMode"):
            _LOGGER.info("Circuit %s categorized as HEATING_CONTROLLER (register %s)", circuit, name)
            return DeviceType.HEATING_CONTROLLER
    return None
