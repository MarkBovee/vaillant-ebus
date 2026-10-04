"""Pure merge helpers for discovery graphs and entity descriptions (no I/O)."""

from __future__ import annotations

from dataclasses import replace

from .discovery_service import node_has_live_data
from .entity_factory import EntityDescription
from .models import (
    DeviceGraph,
    DeviceNode,
    DeviceType,
    ResolutionStatus,
    is_controller_circuit,
    is_heat_pump_circuit,
)


# Intent: identify cache rows from a logical alias that the current graph replaced.
# Why: preserve normal 1.9.x cache-backed entities while retiring proven old-device ghosts.
def is_stale_legacy_alias(circuit: str, graph: DeviceGraph) -> bool:
    is_logical_alias = (
        is_controller_circuit(circuit) or is_heat_pump_circuit(circuit) or circuit.casefold() in {"bai", "vwz", "vwzio"}
    )
    if not is_logical_alias:
        return False
    resolved = graph.resolve_circuit_result(circuit)
    if resolved.status == ResolutionStatus.UNIQUE and resolved.circuit:
        return resolved.circuit.casefold() != circuit.casefold()
    return False


# Intent: merge delayed discovery while replacing metadata that reflects the latest find response.
# Why: stale error-row markers must clear when a later usable find reports the register without an error.
def merge_device_graphs(existing: DeviceGraph, discovered: DeviceGraph) -> DeviceGraph:
    nodes = dict(existing.nodes)
    for circuit, node in discovered.nodes.items():
        existing_circuit = next((key for key in nodes if key.casefold() == circuit.casefold()), None)
        previous = nodes.get(existing_circuit) if existing_circuit is not None else None
        if previous is None:
            nodes[circuit] = node
            continue
        target_circuit = existing_circuit or circuit
        nodes[target_circuit] = DeviceNode(
            circuit=target_circuit,
            device_type=(node.device_type if node.device_type != DeviceType.UNKNOWN else previous.device_type),
            registers=list(dict.fromkeys(previous.registers + node.registers)),
            parent=node.parent or previous.parent,
            zone_circuits=list(dict.fromkeys(previous.zone_circuits + node.zone_circuits)),
            heating_circuits=list(dict.fromkeys(previous.heating_circuits + node.heating_circuits)),
            has_data=node.has_data,
            scan_type=node.scan_type or previous.scan_type,
            scan_sw=node.scan_sw or previous.scan_sw,
            scan_hw=node.scan_hw or previous.scan_hw,
            scan_address=node.scan_address,
        )

    discovered_circuits = {circuit.casefold() for circuit in discovered.nodes}
    for circuit, node in tuple(nodes.items()):
        if circuit.casefold() in {"vwz", "vwzio"} and circuit.casefold() not in discovered_circuits:
            nodes[circuit] = replace(node, scan_address="")

    unavailable_keys = {key.casefold() for key in discovered.placeholder_registers}
    raw_registers = {
        key: value for key, value in existing.raw_registers.items() if key.casefold() not in unavailable_keys
    }
    raw_by_fold = {key.casefold(): key for key in raw_registers}
    for key, value in discovered.raw_registers.items():
        raw_registers[raw_by_fold.get(key.casefold(), key)] = value
        raw_by_fold.setdefault(key.casefold(), key)
    placeholder_registers = set(existing.placeholder_registers)
    placeholder_by_fold = {key.casefold(): key for key in placeholder_registers}
    for key in discovered.placeholder_registers:
        placeholder_registers.add(placeholder_by_fold.get(key.casefold(), key))
        placeholder_by_fold.setdefault(key.casefold(), key)
    placeholder_registers = {
        key for key in placeholder_registers if key.casefold() not in {rk.casefold() for rk in raw_registers}
    }
    error_registers = set(discovered.error_registers)
    for node in nodes.values():
        node.has_data = node_has_live_data(node, raw_registers)
    return DeviceGraph(
        nodes=nodes,
        raw_registers=raw_registers,
        placeholder_registers=placeholder_registers,
        error_registers=error_registers,
        scan_identities=discovered.scan_identities,
    )


# Append entity descriptions without duplicating keys already present.
def merge_entities(
    existing: list[EntityDescription],
    additions: list[EntityDescription],
) -> list[EntityDescription]:
    known = {(entity.entity_type, entity.unique_id.casefold()): entity for entity in existing}
    merged = list(existing)
    for entity in additions:
        identity = (entity.entity_type, entity.unique_id.casefold())
        if identity not in known:
            merged.append(entity)
            known[identity] = entity
        else:
            # Cache spelling may differ from find; loaded entities keep this
            # description object, so update its lookup key without re-adding it.
            known[identity].name = entity.name
            known[identity].circuit = entity.circuit
            known[identity].field = entity.field
            known[identity].raw_value = entity.raw_value
            known[identity].register = entity.register
            known[identity].enabled_by_default = entity.enabled_by_default
    return merged
