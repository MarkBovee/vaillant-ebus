"""Device discovery service — build structured device graph from ebusd find output."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import DeviceGraph, DeviceNode, DeviceType

if TYPE_CHECKING:
    from .ebus_service import EbusService

_LOGGER = logging.getLogger("vaillant_ebus.discovery")

HIDDEN_BROADCAST = {"id", "idanswer", "load", "signoflife"}
HIDDEN_CIRCUITS = {"general"}
ALWAYS_HIDDEN = {"memory"}
HIDDEN_REGISTERS = frozenset({"hmu.FlowTemperature", "Broadcast.FlowTemp"})
SECONDARY_ZONE_CIRCUITS = frozenset({"hc2", "hc3", "z2", "z3"})

PLACEHOLDER_VALUES = frozenset({"-", "no data stored", "empty", "", "unknown", "unavailable"})


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
            "Device graph: %d devices (%s)",
            len(graph.nodes),
            ", ".join(f"{v} {k}" for k, v in sorted(type_counts.items())),
        )
        return graph

    @staticmethod
    def _parse_register(line: str) -> tuple[str, str, str | None]:
        """Parse a find line into (circuit, name, value_or_None)."""
        line = line.strip()
        if not line or "=" not in line:
            return ("", "", None)
        lhs, rhs = line.split("=", 1)
        parts = lhs.strip().split(None, 1)
        circuit = parts[0]
        name = parts[1].strip() if len(parts) > 1 else ""
        val = rhs.strip()
        if val.lower() in PLACEHOLDER_VALUES:
            return (circuit, name, None)
        if val.lower().startswith("no data stored"):
            return (circuit, name, None)
        if val.startswith(("(empty ", "(ERR")):
            return (circuit, name, None)
        return (circuit, name, val)

    @staticmethod
    def _parse_scan(line: str) -> tuple[str, str, str, str] | None:
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
        return (lhs.strip(), parts[1].strip(), parts[2].strip(), parts[3].strip())

    @staticmethod
    def _infer_circuit_from_scan_type(scan_type: str) -> str:
        low = scan_type.lower()
        if low == "netx2":
            return "Broadcast"
        prefix = low.rstrip("0123456789")
        if prefix in ("hmu", "ctlv", "basv", "bai", "vwz", "vwzio"):
            return prefix
        return ""

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
        if c_lower.startswith("scan"):
            return True
        if c_lower in ALWAYS_HIDDEN or c_lower in HIDDEN_CIRCUITS:
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
        scan_entries: list[tuple[str, str, str, str]] = []  # (scan_addr, TYPE, SW, HW)
        regs_by_circuit: dict[str, list[str]] = {}

        for line in find_lines:
            scan = DiscoveryService._parse_scan(line)
            if scan is not None:
                scan_entries.append(scan)
                continue

            circuit, name, value = DiscoveryService._parse_register(line)
            if not circuit or not name:
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
            if c_lower in ALWAYS_HIDDEN or c_lower in HIDDEN_CIRCUITS:
                continue

            scan_info = scan_by_circuit.get(circuit)
            scan_type = scan_info[0] if scan_info else ""
            scan_sw = scan_info[1] if scan_info else ""
            scan_hw = scan_info[2] if scan_info else ""

            regs: list[str] = []
            for rk in reg_keys:
                if rk in assigned_regs:
                    continue
                if DiscoveryService._is_hidden(rk, has_data):
                    continue
                regs.append(rk)

            node = DeviceNode(
                circuit=circuit,
                device_type=DiscoveryService.categorize_circuit(circuit, regs, scan_type),
                registers=regs,
                has_data=any(raw_registers.get(rk) is not None for rk in regs),
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


def _sub_name(sub_key: str) -> str:
    return sub_key.split("/", 1)[1]


def _compute_has_data(
    regs_by_circuit: dict[str, list[str]],
    raw_registers: dict[str, str],
) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for circuit, reg_keys in regs_by_circuit.items():
        c_lower = circuit.lower()
        broadcast_hidden = HIDDEN_BROADCAST if c_lower == "broadcast" else set()
        result[circuit] = any(
            raw_registers.get(rk) is not None
            for rk in reg_keys
            if rk.split(".", 1)[1].lower() not in broadcast_hidden
        )
    return result


def _detect_sub_devices(
    regs_by_circuit: dict[str, list[str]],
) -> dict[str, tuple[str, DeviceType]]:
    result: dict[str, tuple[str, DeviceType]] = {}
    for circuit, reg_keys in regs_by_circuit.items():
        c_lower = circuit.lower()
        if c_lower.startswith(("scan", "broadcast")) or c_lower in ALWAYS_HIDDEN | HIDDEN_CIRCUITS:
            continue
        reg_names = {rk.split(".", 1)[1] for rk in reg_keys if "." in rk}
        hwc_seen = any(
            n.lower().startswith(("hwc", "cylinder", "maxcylinder", "dhw", "solar"))
            for n in reg_names
        )
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


def _match_scan_to_circuits(
    scan_entries: list[tuple[str, str, str, str]],
    regs_by_circuit: dict[str, list[str]],
) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    circuit_names = [c for c in regs_by_circuit if not c.lower().startswith("scan")]
    for scan_addr, scan_type, scan_sw, scan_hw in scan_entries:
        # Direct mapping for NETX2 → Broadcast
        if scan_type.lower() == "netx2":
            result["Broadcast"] = (scan_type, scan_sw, scan_hw)
            continue
        prefix = scan_type.lower().rstrip("0123456789")
        for ckt in circuit_names:
            if ckt.lower().startswith(prefix):
                result[ckt] = (scan_type, scan_sw, scan_hw)
                break
    return result


def _apply_relationships(
    nodes: dict[str, DeviceNode],
    sub_devices: dict[str, tuple[str, DeviceType]],
) -> None:
    heat_pump = next(
        (n for n in nodes.values() if n.device_type == DeviceType.HEAT_PUMP), None
    )
    controller = next(
        (n for n in nodes.values() if n.device_type == DeviceType.HEATING_CONTROLLER), None
    )

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
    "ctlv": DeviceType.HEATING_CONTROLLER,
    "ctlv1": DeviceType.HEATING_CONTROLLER,
    "ctlv2": DeviceType.HEATING_CONTROLLER,
    "basv": DeviceType.HEATING_CONTROLLER,
    "basv2": DeviceType.HEATING_CONTROLLER,
    "bai": DeviceType.HEATING_CONTROLLER,
    "vwz": DeviceType.PASSIVE_COOLING,
    "vwz00": DeviceType.PASSIVE_COOLING,
    "vwzio": DeviceType.PASSIVE_COOLING,
    "netx": DeviceType.BUS,
    "netx2": DeviceType.BUS,
    "v32": DeviceType.VENTILATION,
}

_PREFIX_TO_DEVICE: dict[str, DeviceType] = {
    "hmu": DeviceType.HEAT_PUMP,
    "ctlv": DeviceType.HEATING_CONTROLLER,
    "basv": DeviceType.HEATING_CONTROLLER,
    "bai": DeviceType.HEATING_CONTROLLER,
    "broadcast": DeviceType.BUS,
    "vwz": DeviceType.PASSIVE_COOLING,
    "vwzio": DeviceType.PASSIVE_COOLING,
    "v32": DeviceType.VENTILATION,
}


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


def _categorize_by_prefix(circuit: str) -> DeviceType | None:
    c_lower = circuit.lower()
    for prefix, d_type in _PREFIX_TO_DEVICE.items():
        if c_lower.startswith(prefix):
            _LOGGER.info("Circuit %s categorized as %s (prefix '%s')", circuit, d_type.name, prefix)
            return d_type
    return None


def _categorize_by_registers(circuit: str, registers: list[str]) -> DeviceType | None:
    for rk in registers:
        name = rk.split(".", 1)[-1] if "." in rk else ""
        if name in ("Z1OpMode", "HwcOpMode"):
            _LOGGER.info("Circuit %s categorized as HEATING_CONTROLLER (register %s)", circuit, name)
            return DeviceType.HEATING_CONTROLLER
    return None
