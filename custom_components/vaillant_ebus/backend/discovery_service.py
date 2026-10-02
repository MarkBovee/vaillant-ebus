"""Device discovery service — build structured device graph from ebusd find output."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, NamedTuple

from .models import (
    DeviceGraph,
    DeviceNode,
    DeviceType,
    ScanIdentity,
    is_ebusd_error_value,
    is_no_data_value,
    is_valid_hmux0_return_temperature,
)

if TYPE_CHECKING:
    from .ebus_service import EbusService

_LOGGER = logging.getLogger(__name__)

HIDDEN_BROADCAST = {"id", "idanswer", "load", "signoflife"}
ALWAYS_HIDDEN = {"memory"}
HIDDEN_DEVICE_KEYWORDS = {"broadcast", "scan", "general"}
HIDDEN_REGISTER_NAMES = {"tmpb516montheven"}
# Intent: identify numbered zone and heating-circuit node names.
# Why: filtering must continue to work beyond the common z1/hc3 range.
_NUMBERED_ZONE_RE = re.compile(r"^(?:hc|z)(\d+)$", re.IGNORECASE)


# Intent: identify secondary numbered zone and heating-circuit nodes.
# Why: inactive-zone filtering must apply consistently beyond z1/hc1.
def _is_secondary_zone_circuit(circuit: str) -> bool:
    match = _NUMBERED_ZONE_RE.fullmatch(circuit)
    return bool(match and int(match.group(1)) > 1)


# Intent: detect static registers belonging to inactive numbered zones.
# Why: DayTemp/OpMode defaults must not authorize a ghost zone entity.
def _is_inactive_zone_register(name: str, has_data: dict[str, bool]) -> bool:
    lower = name.lower()
    for prefix in ("hc", "z"):
        match = re.match(rf"{prefix}(\d+)", lower)
        if match and int(match.group(1)) > 1:
            return not has_data.get(f"{prefix}{match.group(1)}", False)
    return False


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
    address: str


class DiscoveryService:
    def __init__(self, ebus: EbusService) -> None:
        self._ebus = ebus

    # Intent: build a device graph only from a find response with usable rows.
    # Why: error-only register lines can otherwise masquerade as discovered nodes.
    async def discover(self) -> DeviceGraph:
        find_lines = await self._ebus.find_registers()
        if getattr(self._ebus, "last_find_usable", None) is False:
            _LOGGER.warning("Skipping graph build from an empty/error-only ebusd find response")
            return DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
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

    # Intent: parse one register row without crashing on an empty or malformed LHS.
    # Why: malformed find data must be rejected at the transport boundary, not crash discovery.
    @staticmethod
    def _parse_register(line: str) -> ParsedRegister:
        """Parse a find line into (circuit, name, value_or_None)."""
        line = line.strip()
        if not line or "=" not in line:
            return ParsedRegister("", "", None)
        lhs, rhs = line.split("=", 1)
        parts = lhs.strip().split(None, 1)
        if not parts:
            return ParsedRegister("", "", None)
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
        if circuit.lower() == "hmux0" and name.lower() == "rundatareturntemp":
            if not is_valid_hmux0_return_temperature(val):
                return ParsedRegister(circuit, name, None)
        return ParsedRegister(circuit, name, val)

    # Intent: accept only ebusd's address-qualified scan metadata row shape.
    # Why: scan-prefixed register names such as `Scan.08 Id` must remain register rows.
    @staticmethod
    def _parse_scan(line: str) -> ScanEntry | None:
        """Parse a scan metadata line into (scan_addr, TYPE, SW, HW) or None."""
        line = line.strip()
        if not line or "=" not in line:
            return None
        lhs, rhs = line.split("=", 1)
        if not re.fullmatch(r"scan\.[0-9a-f]{2}", lhs.strip(), re.IGNORECASE):
            return None
        rhs = rhs.strip()
        if rhs.lower() == "no data stored":
            return None
        parts = rhs.split(";")
        if len(parts) != 4:
            return None
        if all("=" in part for part in parts):
            required = {"MF", "ID", "SW", "HW"}
            metadata: dict[str, str] = {}
            for part in parts:
                key, value = part.split("=", 1)
                metadata[key.strip()] = value.strip()
            if metadata.keys() == required and all(metadata[key] for key in required):
                return ScanEntry(lhs.strip(), metadata["ID"], metadata["SW"], metadata["HW"])
            return None
        if any("=" in part for part in parts) or not all(part.strip() for part in parts):
            return None
        return ScanEntry(lhs.strip(), parts[1].strip(), parts[2].strip(), parts[3].strip())

    # Intent: retain recognized address-qualified scan observations even when their identity fields are incomplete.
    # Why: incomplete evidence at a fixed target address must invalidate hardware authorization, not disappear.
    @staticmethod
    def _parse_scan_identity(line: str) -> ScanIdentity | None:
        line = line.strip()
        if not line or "=" not in line:
            return None
        lhs, rhs = line.split("=", 1)
        address = lhs.strip()
        if not re.fullmatch(r"scan\.[0-9a-f]{2}", address, re.IGNORECASE):
            return None
        raw_value = rhs.strip()
        if not raw_value:
            return ScanIdentity(address, "", "", "", complete=False)
        parts = [part.strip() for part in raw_value.split(";")]
        if len(parts) == 1 and parts[0].casefold() == "no data stored":
            return None
        if 2 <= len(parts) < 4 and not any("=" in part for part in parts) and parts[0].casefold() == "vaillant":
            return ScanIdentity(
                address,
                parts[1],
                parts[2] if len(parts) > 2 else "",
                "",
                complete=False,
            )
        if len(parts) == 4 and not any("=" in part for part in parts):
            return ScanIdentity(address, parts[1], parts[2], parts[3], complete=all(parts))
        metadata: dict[str, str] = {}
        for part in parts:
            if "=" not in part:
                key = part.strip().upper()
                if key not in {"MF", "ID", "SW", "HW"} or key in metadata:
                    return None
                metadata[key] = ""
                continue
            key, value = part.split("=", 1)
            key = key.strip().upper()
            if key not in {"MF", "ID", "SW", "HW"} or key in metadata:
                return None
            metadata[key] = value.strip()
        if not metadata:
            return None
        return ScanIdentity(
            address,
            metadata.get("ID", ""),
            metadata.get("SW", ""),
            metadata.get("HW", ""),
            complete=set(metadata) == {"MF", "ID", "SW", "HW"} and all(metadata.values()),
        )

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
        if n_lower.startswith(("cctimer_", "hwctimer_")) or re.match(r"z\d+timer_", n_lower):
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
            if _is_secondary_zone_circuit(c_lower) and not has_data.get(c_lower):
                return True
            if _is_inactive_zone_register(n_lower, has_data):
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

    # Intent: build a device graph from register and scan observations.
    # Why: unavailable rows retain ownership metadata without fabricating a raw value.
    @staticmethod
    def build_device_graph(find_lines: list[str]) -> DeviceGraph:
        raw_registers: dict[str, str] = {}
        placeholder_registers: set[str] = set()
        scan_entries = [scan for line in find_lines if (scan := DiscoveryService._parse_scan(line)) is not None]
        suppress_hmu_alias = _is_hmux0_0303_0504_without_hmu(scan_entries) or _is_boiler_without_heat_pump(scan_entries)
        regs_by_circuit: dict[str, list[str]] = {}
        error_registers: set[str] = set()

        for line in find_lines:
            if DiscoveryService._parse_scan(line) is not None:
                continue

            circuit, name, value = DiscoveryService._parse_register(line)
            if not circuit or not name:
                continue
            circuit = circuit.casefold()
            if suppress_hmu_alias and circuit.lower() == "hmu":
                continue
            if "." in name:
                continue
            register_key = f"{circuit}.{name}"

            if circuit.lower() == "hmu" and name.lower() == "sourcetempinput":
                raw_value = line.split("=", 1)[1].strip()
                if value is None and raw_value:
                    continue

            raw_value = line.split("=", 1)[1].strip()
            if is_ebusd_error_value(raw_value):
                error_registers.add(register_key)
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
                    has_data=existing.has_data or _subdevice_has_data(sub_name, parent_circuit, raw_registers),
                )
                continue
            nodes[sub_name] = DeviceNode(
                circuit=sub_name,
                device_type=d_type,
                registers=regs,
                has_data=(
                    _subdevice_has_data(sub_name, parent_circuit, raw_registers)
                    if d_type == DeviceType.ZONE
                    else any(raw_registers.get(rk) is not None for rk in regs)
                ),
            )

        for circuit, reg_keys in regs_by_circuit.items():
            c_lower = circuit.lower()
            if c_lower.startswith("scan"):
                continue
            if c_lower in ALWAYS_HIDDEN or any(kw in c_lower for kw in HIDDEN_DEVICE_KEYWORDS):
                continue

            scan_info = scan_by_circuit.get(circuit)
            scan_type = scan_info.scan_type if scan_info else ""
            scan_sw = scan_info.scan_sw if scan_info else ""
            scan_hw = scan_info.scan_hw if scan_info else ""
            if _is_address_circuit(circuit) and not scan_type:
                continue

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
                scan_address=scan_info.address if scan_info else "",
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

        # A scan is evidence of a physical device even if ebusd has no matching
        # CSV yet. Retain its identity so narrowly scoped runtime definitions can
        # bootstrap that device without guessing a different circuit name.
        for circuit, metadata in _scan_only_circuits(scan_entries, regs_by_circuit).items():
            if circuit in nodes:
                continue
            device_type = DiscoveryService.categorize_circuit(circuit, [], metadata.scan_type)
            if device_type == DeviceType.UNKNOWN:
                continue
            nodes[circuit] = DeviceNode(
                circuit=circuit,
                device_type=device_type,
                scan_type=metadata.scan_type,
                scan_sw=metadata.scan_sw,
                scan_hw=metadata.scan_hw,
                scan_address=metadata.address,
            )

        # A scan-less controller carrying only the integration's own runtime
        # control probes (e.g. a stale `bai SetModeOverride` write-only define
        # left behind by an earlier ebusd session) is not a physical device.
        # Real controllers are scan-bound or own native control/data registers,
        # so this targeted rule cannot hide a genuine boiler or controller.
        nodes = {circuit: node for circuit, node in nodes.items() if not _is_runtime_only_controller_alias(node)}

        _apply_relationships(nodes, sub_devices)

        return DeviceGraph(
            nodes=nodes,
            raw_registers=raw_registers,
            placeholder_registers=placeholder_registers,
            error_registers={
                key
                for key in error_registers
                if key.casefold() not in {raw_key.casefold() for raw_key in raw_registers}
            },
            scan_identities=tuple(
                identity for line in find_lines if (identity := DiscoveryService._parse_scan_identity(line)) is not None
            ),
        )


# Intent: accept find rows that discovery can parse into registers or scan observations.
# Why: incomplete address-qualified scans must remain usable evidence so they can
# block ambiguous hardware authorization.
def has_usable_find_records(find_lines: Sequence[str]) -> bool:
    usable = False
    for line in find_lines:
        line = line.strip()
        if not line:
            continue
        if line.casefold().startswith(("err:", "(err:")):
            continue
        lhs, separator, raw_value = line.partition("=")
        if not separator:
            raise ValueError(f"find response contains a row without '=': {line}")
        lhs = lhs.strip()
        raw_value = raw_value.strip()
        if not lhs:
            raise ValueError(f"find response contains an empty row name: {line}")
        if DiscoveryService._parse_scan_identity(line) is not None:
            usable = True
            continue
        parsed = DiscoveryService._parse_register(line)
        if not parsed.circuit or not parsed.name:
            if re.fullmatch(r"scan\.[0-9a-f]{2}", lhs, re.IGNORECASE) and is_no_data_value(raw_value):
                continue
            raise ValueError(f"find response contains malformed register row: {line}")
        if "." in parsed.name:
            continue
        if is_no_data_value(raw_value):
            if is_ebusd_error_value(raw_value):
                continue
            usable = True
            continue
        usable = True
    return usable


# Intent: recompute a merged node's live-data state from its current register graph.
# Why: delayed discovery can remove the register that previously made a device active.
def node_has_live_data(node: DeviceNode, raw_registers: dict[str, str]) -> bool:
    raw_by_fold = {key.casefold(): (key, value) for key, value in raw_registers.items()}
    if node.device_type == DeviceType.ZONE:
        zone_number = node.circuit[1:] if node.circuit.casefold().startswith("z") else ""
        static_suffixes = {"daytemp", "nighttemp", "opmode", "holidaytemp", "roomzonemapping"}
        for key in node.registers:
            row = raw_by_fold.get(key.casefold())
            if row is None:
                continue
            name = row[0].split(".", 1)[1]
            lowered_name = name.casefold()
            if lowered_name == f"z{zone_number}roomzonemapping" and row[1].strip().casefold() not in {"", "none"}:
                return True
            if not is_no_data_value(row[1]) and lowered_name.removeprefix(f"z{zone_number}") not in static_suffixes:
                return True
        return False
    return any(
        key.casefold() in raw_by_fold and not is_no_data_value(raw_by_fold[key.casefold()][1]) for key in node.registers
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
    n_upper = name.upper()
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
    n_upper = name.upper()
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


# Intent: determine whether a zone or heating-circuit subdevice has live evidence.
# Why: static defaults are insufficient to create owner-dependent entities.
def _subdevice_has_data(sub_name: str, parent_circuit: str, raw_registers: dict[str, str]) -> bool:
    """Return whether a zone/heating-circuit node has live ownership evidence."""
    number = sub_name[1:] if sub_name.startswith("z") else sub_name[2:]
    if sub_name.startswith("z"):
        expected_mapping = f"{parent_circuit}.z{number}roomzonemapping".casefold()
        mapping = next(
            (value for key, value in raw_registers.items() if key.casefold() == expected_mapping),
            None,
        )
        if mapping is not None and mapping.strip().lower() not in {"", "none"} and not is_no_data_value(mapping):
            return True
        static_suffixes = {"daytemp", "nighttemp", "opmode", "holidaytemp", "roomzonemapping"}
        return any(
            value is not None
            and not is_no_data_value(value)
            and name.casefold().removeprefix(f"z{number}") not in static_suffixes
            for key, value in raw_registers.items()
            if key.casefold().startswith(f"{parent_circuit}.z{number}".casefold())
            for name in (key.split(".", 1)[1],)
        )
    elif sub_name.startswith("hc"):
        return any(
            value is not None and not is_no_data_value(value)
            for key, value in raw_registers.items()
            if key.casefold().startswith(f"{parent_circuit}.hc{number}".casefold())
        )
    else:
        return False


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
#   2. Exact normalized TYPE ↔ circuit match, including numeric VRC70000 ↔ 700.
#   3. Family match after stripping variant digits (HMU00 ↔ hmu, BASV3 ↔ basv).
#   4. Stable family-prefix fallback (circuit starts with the scan family).
# A scan entry is consumed by at most one circuit. Ambiguous associations are
# intentionally left unmatched instead of guessed: scan metadata drives device
# naming, classification and hardware-gated runtime definitions (HMUX0 SW/HW),
# so a wrong assignment poisons the graph. Identical repeated scan lines (find
# output may repeat them) collapse to the first occurrence, keeping the result
# deterministic regardless of duplication.
# Intent: map unique physical scan identities to their logical ebusd circuits.
# Why: scan metadata controls hardware-gated runtime definitions and must never be guessed across addresses.
def _unambiguous_scan_entries(
    scan_entries: Sequence[ScanEntry | tuple[str, str, str, str]],
) -> list[ScanEntry]:
    # Intent: retain one compatible scan identity per address/type pair and reject ambiguous physical identities.
    # Why: a repeated row at one address is harmless, but scan addresses/types cannot be guessed across devices.
    grouped: dict[tuple[str, str], list[ScanEntry]] = {}
    for raw_entry in scan_entries:
        entry = raw_entry if isinstance(raw_entry, ScanEntry) else ScanEntry(*raw_entry)
        key = (entry.address.casefold(), entry.scan_type.casefold())
        grouped.setdefault(key, []).append(entry)

    normalized: list[ScanEntry] = []
    conflicting_groups: set[tuple[str, str]] = set()
    for key, entries in grouped.items():
        software = {entry.scan_sw.casefold() for entry in entries if entry.scan_sw}
        hardware = {entry.scan_hw.casefold() for entry in entries if entry.scan_hw}
        if len(software) > 1 or len(hardware) > 1:
            conflicting_groups.add(key)
            continue
        first = entries[0]
        normalized.append(ScanEntry(first.address, first.scan_type, next(iter(software), ""), next(iter(hardware), "")))

    type_identities: dict[str, set[tuple[str, str]]] = {}
    address_identities: dict[str, set[tuple[str, str, str]]] = {}
    for entry in normalized:
        type_key = entry.scan_type.casefold()
        address_key = entry.address.casefold()
        identity = (type_key, entry.scan_sw.casefold(), entry.scan_hw.casefold())
        type_identities.setdefault(type_key, set()).add((entry.scan_sw.casefold(), entry.scan_hw.casefold()))
        address_identities.setdefault(address_key, set()).add(identity)

    conflicting_types = {scan_type for scan_type, identities in type_identities.items() if len(identities) > 1}
    conflicting_types.update(scan_type for _, scan_type in conflicting_groups)
    ambiguous_addresses = {address for address, identities in address_identities.items() if len(identities) > 1}
    ambiguous_addresses.update(address for address, _ in conflicting_groups)
    return [
        entry
        for entry in normalized
        if (entry.address.casefold(), entry.scan_type.casefold()) not in conflicting_groups
        and entry.scan_type.casefold() not in conflicting_types
        and entry.address.casefold() not in ambiguous_addresses
    ]


# Intent: bind each usable scan identity to at most one discovered circuit.
# Why: runtime definitions depend on circuit ownership and physical bus address.
def _match_scan_to_circuits(
    scan_entries: Sequence[ScanEntry | tuple[str, str, str, str]],
    regs_by_circuit: dict[str, list[str]],
) -> dict[str, ScanMetadata]:
    circuit_names = [c for c in regs_by_circuit if not c.lower().startswith("scan")]

    entries_by_type: dict[str, list[ScanEntry]] = {}
    for entry in _unambiguous_scan_entries(scan_entries):
        entries_by_type.setdefault(entry.scan_type.casefold(), []).append(entry)
    scans_by_type: dict[str, ScanMetadata] = {}
    for entries in entries_by_type.values():
        first = entries[0]
        addresses = {entry.address.casefold() for entry in entries}
        scans_by_type[first.scan_type.casefold()] = ScanMetadata(
            first.scan_type,
            first.scan_sw,
            first.scan_hw,
            first.address if len(addresses) == 1 else "",
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
        numeric_candidates = [c for c in circuit_names if _numeric_scan_matches_circuit(scan_type, c)]
        exact_candidates.extend(c for c in numeric_candidates if c not in exact_candidates)
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


def _numeric_scan_matches_circuit(scan_type: str, circuit: str) -> bool:
    """Match numeric VRC scan IDs to their shortened ebusd circuit names."""
    if len(scan_type) != 5 or len(circuit) != 3 or not scan_type.isdigit() or not circuit.isdigit():
        return False
    return scan_type[:3] == circuit and scan_type[3:] == "00"


# Intent: retain physical HMUX0 and target VWZIO scans even when no CSV creates a circuit node.
# Why: exact scan identity can gate additive runtime definitions without inventing a device or address.
def _scan_only_circuits(
    scan_entries: Sequence[ScanEntry], regs_by_circuit: dict[str, list[str]]
) -> dict[str, ScanMetadata]:
    """Expose supported physical scans when ebusd has no configured circuit."""
    represented = {_normalize_name(circuit) for circuit in regs_by_circuit}
    scans: dict[str, ScanMetadata] = {}
    conflicts: set[str] = set()
    for entry in _unambiguous_scan_entries(scan_entries):
        key = _normalize_name(entry.scan_type)
        if key in conflicts or key not in {"hmux0", "vwzio"} or key in represented:
            continue
        current = scans.get(key)
        if current is None:
            scans[key] = ScanMetadata(entry.scan_type, entry.scan_sw, entry.scan_hw, entry.address)
            continue
        if (
            current.address.casefold() != entry.address.casefold()
            or current.scan_sw.casefold() != entry.scan_sw.casefold()
            or current.scan_hw.casefold() != entry.scan_hw.casefold()
        ):
            scans.pop(key, None)
            conflicts.add(key)
            continue
        scans[key] = ScanMetadata(
            current.scan_type,
            current.scan_sw or entry.scan_sw,
            current.scan_hw or entry.scan_hw,
            current.address,
        )
    result: dict[str, ScanMetadata] = {}
    for circuit, metadata in scans.items():
        if circuit == "vwzio" and (metadata.scan_sw != "0500" or metadata.scan_hw != "0504"):
            continue
        if _categorize_by_scan_type(circuit, metadata.scan_type) is not None:
            result[circuit] = metadata
    return result


def _is_hmux0_0303_0504_without_hmu(scan_entries: Sequence[ScanEntry]) -> bool:
    """Identify confirmed HMUX0 hardware without an independently scanned HMU."""
    hmux0 = [entry for entry in scan_entries if _normalize_name(entry.scan_type) == "hmux0"]
    if not hmux0 or any(entry.scan_sw != "0303" or entry.scan_hw != "0504" for entry in hmux0):
        return False
    return not any(_name_family(entry.scan_type) == "hmu" for entry in scan_entries)


# A boiler bus (BAI burner interface) with no heat-pump scan can still report a
# bare `hmu` circuit made only of runtime-defined b516 energy probes. That alias
# must not be exposed as a real aroTHERM heat pump. Suppress it only when a BAI
# scan is present and no heat-pump scan exists, so genuine HMU/HMUX buses and
# scan-less legacy captures keep their heat-pump node.
def _is_boiler_without_heat_pump(scan_entries: Sequence[ScanEntry]) -> bool:
    """Identify a BAI boiler bus with no scanned heat pump."""
    has_bai = any(_name_family(entry.scan_type) == "bai" for entry in scan_entries)
    has_heat_pump = any(_name_family(entry.scan_type) in ("hmu", "hmux") for entry in scan_entries)
    return has_bai and not has_heat_pump


# Runtime control-only registers the integration defines itself; a circuit that
# only carries these and has no scan/data is an alias left by an old ebusd
# session, not a device.
_RUNTIME_ONLY_CONTROLLER_REGISTERS = frozenset({"SetModeOverride", "HeatingSwitch", "HwcSwitch"})


def _is_runtime_only_controller_alias(node: DeviceNode) -> bool:
    """Return whether a node is a scan-less runtime-only controller alias."""
    if node.device_type != DeviceType.HEATING_CONTROLLER or node.scan_type or node.has_data:
        return False
    names = {register.rsplit(".", 1)[-1].casefold() for register in node.registers}
    return bool(names) and names <= {name.casefold() for name in _RUNTIME_ONLY_CONTROLLER_REGISTERS}


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
    "70000": DeviceType.HEATING_CONTROLLER,
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
