"""Plan which registers the coordinator reads actively when ebusd `find` does not list them.

Pure planning (no I/O): the coordinator performs the reads. Every candidate is resolved against
the discovered device graph and passes the per-hardware polling restrictions.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Collection, Mapping, Sequence

from .mapping import (
    HMUX0_SW0407_FALLBACK_NAMES,
    VWZIO_SW0500_FALLBACK_NAMES,
    hmux0_candidate_circuits,
    hmux0_fallback_blocked_circuits,
    hmux0_precise_temperature_owner,
    is_field_key,
    metadata_circuits,
    vwz_station_scan_76_circuit,
    vwzio_sw0500_circuit,
)
from .models import (
    HMUX0_PRECISE_TEMPERATURE_REGISTERS,
    DeviceGraph,
    DeviceType,
    RegisterMeta,
    is_controller_circuit,
    is_heat_pump_circuit,
)
from .reread_plan import hmux0_sw0407_active_reads, plan_rereads


# Select a unique discovered owner for a logical register map entry.
# Registers live under basv3/ctlv3/vwzio too, so the literal map circuit must not be assumed.
def fallback_candidate(
    graph: DeviceGraph | None, resolve_circuit: Callable[[str], str | None], logical_circuit: str, name: str
) -> str | None:
    """Return the circuit to read a register from.

    Prefer the circuit where the register was discovered (its raw or
    placeholder graph key); otherwise fall back to the literal map circuit.
    Mirrors the ctlv2/hmu aliasing used by get_meta() so registers that
    live under basv3/ctlv3/vwzio are read from the correct circuit.
    """
    expected_type = (
        DeviceType.HEATING_CONTROLLER
        if is_controller_circuit(logical_circuit)
        else DeviceType.HEAT_PUMP
        if is_heat_pump_circuit(logical_circuit)
        else DeviceType.HEATING_CONTROLLER
        if logical_circuit == "bai"
        else None
    )
    candidates: list[str] = []
    if graph is not None:
        keys = list(graph.raw_registers) + list(graph.placeholder_registers)
        candidates = list(
            dict.fromkeys(
                circuit
                for circuit in (rk.split(".", 1)[0] for rk in keys if rk.casefold().endswith(f".{name}".casefold()))
                if expected_type is None
                or (
                    next(
                        (node for node_key, node in graph.nodes.items() if node_key.casefold() == circuit.casefold()),
                        None,
                    )
                    is not None
                    and next(
                        node for node_key, node in graph.nodes.items() if node_key.casefold() == circuit.casefold()
                    ).device_type
                    == expected_type
                )
            )
        )
    resolved = resolve_circuit(logical_circuit)
    if resolved is not None:
        return next((candidate for candidate in candidates if candidate.casefold() == resolved.casefold()), None)
    if expected_type is None and len(candidates) == 1:
        return candidates[0]
    return None


# List the (circuit, register) pairs to read actively, in order, without duplicates.
# Fallback probes must not bypass per-register polling restrictions. Registers whose cached ebusd value is an error are
# skipped, except the keys in `retry_reads`: ebusd keeps a transient error until the next read, so without an occasional
# retry one read timeout would stop the register for good (issue #223).
def plan_fallback_reads(
    graph: DeviceGraph,
    last_find_keys: Collection[str],
    runtime_definitions: Mapping[str, str],
    resolve_circuit: Callable[[str], str | None],
    register_map: Mapping[str, RegisterMeta],
    *,
    include_placeholders: bool = False,
    include_energy: bool = False,
    skip_reads: Collection[str] | None = None,
    withheld: Collection[tuple[str, str]] = (),
    retry_reads: Collection[str] = (),
) -> list[tuple[str, str]]:
    graph_keys = last_find_keys

    # Resolve metadata for a discovered source circuit without changing its owner.
    # Family metadata is presentation compatibility, not bus routing.
    def _meta_key(circuit: str, name: str) -> str | None:
        for alt in metadata_circuits(circuit):
            key = f"{alt}.{name}"
            if any(map_key.casefold() == key.casefold() for map_key in register_map):
                return next(map_key for map_key in register_map if map_key.casefold() == key.casefold())
        return None

    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    skipped_read_keys = {key.casefold() for key in (skip_reads or set())}
    skipped_read_keys.update(key.casefold() for key in graph.error_registers)
    skipped_read_keys.difference_update(key.casefold() for key in retry_reads)
    withheld_keys = set(withheld)
    passive_register_keys = {
        (parts[1].casefold(), parts[2].casefold())
        for definition in runtime_definitions.values()
        if len(parts := definition.split(",", 3)) >= 3 and parts[0].startswith("u")
    }
    hmux0_blocked_circuits = {circuit.casefold() for circuit in hmux0_fallback_blocked_circuits(graph)}
    hmux0_candidates = {circuit.casefold() for circuit in hmux0_candidate_circuits(graph)}
    hmux0_precise_temperature = hmux0_precise_temperature_owner(graph)
    vwzio_sw0500 = vwzio_sw0500_circuit(graph)
    vwz_station_76 = vwz_station_scan_76_circuit(graph)
    sw0407_active_reads = hmux0_sw0407_active_reads(graph, runtime_definitions)
    sw0407_active_keys = {(circuit.casefold(), name.casefold()) for circuit, name in sw0407_active_reads}

    # Add each resolved fallback candidate once.
    # map, passive-definition, and placeholder paths can nominate the same register.
    def _add(circuit: str, name: str) -> None:
        circuit_key = circuit.casefold()
        name_key = name.casefold()
        if "." in name or f"{circuit}.{name}".casefold() in skipped_read_keys:
            return
        if (circuit_key, name_key) in passive_register_keys:
            return
        # Never read a register whose runtime definition was withheld because its owner cannot answer it.
        # The map-driven pass would otherwise still send a one-off read for it each cycle (issue #179).
        if (circuit_key, name_key) in withheld_keys:
            return
        # B511 counters remain passive even if their map fallback metadata changes.
        if name_key == "runstatsimmersionheaterhwc":
            return
        if (
            name_key == "status01"
            and circuit_key in {"vwz", "vwzio"}
            and (vwz_station_76 is None or circuit_key != vwz_station_76.casefold())
        ):
            return
        if (
            circuit_key in hmux0_blocked_circuits
            and name_key in HMUX0_SW0407_FALLBACK_NAMES
            and (circuit_key, name_key) not in sw0407_active_keys
        ):
            return
        if name_key in HMUX0_PRECISE_TEMPERATURE_REGISTERS and circuit_key in hmux0_candidates:
            if hmux0_precise_temperature is None or circuit_key != hmux0_precise_temperature.casefold():
                return
        if (
            vwzio_sw0500 is not None
            and circuit_key == vwzio_sw0500.casefold()
            and name_key in VWZIO_SW0500_FALLBACK_NAMES
        ):
            return
        key = (circuit, name)
        if key not in seen:
            seen.add(key)
            candidates.append(key)

    # Plain-`r` registers ebusd never polls: every rule lives in `reread_plan.REREAD_RULES` (#171, #193, #207,
    # #213, #227). Each read still passes `_add`, so a rule cannot bypass a passive, withheld or hardware gate.
    for circuit, name in plan_rereads(graph, runtime_definitions, include_energy=include_energy):
        _add(circuit, name)

    # Map-driven reads: registers with metadata not yet in the graph.
    graph_key_folds = {key.casefold() for key in graph_keys}
    for key in register_map:
        meta = register_map[key]
        if not meta.enabled or not meta.fallback_read or key.casefold() in graph_key_folds:
            continue
        map_circuit, name = key.split(".", 1)
        if is_field_key(key):
            continue
        candidate_circuit = fallback_candidate(graph, resolve_circuit, map_circuit, name)
        if (
            candidate_circuit is None
            and graph
            and any(
                rk.casefold().endswith(f".{name}".casefold())
                for rk in (*graph.raw_registers, *graph.placeholder_registers)
            )
        ):
            continue
        resolved_circuit = candidate_circuit if candidate_circuit is not None else resolve_circuit(map_circuit)
        # RunDataFlowTemp is only evidenced for the current SW0303/SW0406 HW0504 HMUX0 owner (issue #171); an
        # HMUX0 alias key must not trigger an active B509 read on any other heat-pump circuit.
        if (
            resolved_circuit is not None
            and name.casefold() == "rundataflowtemp"
            and (
                hmux0_precise_temperature is None or resolved_circuit.casefold() != hmux0_precise_temperature.casefold()
            )
        ):
            continue
        if resolved_circuit is not None:
            _add(resolved_circuit, name)

    # Placeholder reads: discovered no-data registers whose metadata
    # resolves via the circuit alias (15-minute interval).
    if include_placeholders and graph:
        for key in graph.placeholder_registers:
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            circuit, name = parts
            if "." in name or key.casefold() in skipped_read_keys:
                continue
            if key.casefold() in {raw_key.casefold() for raw_key in graph.raw_registers}:
                continue
            meta_key = _meta_key(circuit, name)
            if meta_key:
                placeholder_meta = next(
                    (value for map_key, value in register_map.items() if map_key.casefold() == meta_key.casefold()),
                    None,
                )
            else:
                placeholder_meta = None
            if placeholder_meta and placeholder_meta.enabled and placeholder_meta.fallback_read:
                resolved = fallback_candidate(graph, resolve_circuit, circuit, name)
                if resolved is not None:
                    _add(resolved, name)
    return interleave_by_circuit(candidates)


# Reorder reads so every circuit is asked in turn, keeping the planned order inside each circuit.
# Issue #193 - the bus guard needs bus errors from two circuits before it pauses, and a plan grouped by circuit
# sent dozens of reads to the first circuit of a stuck adapter before the second one was asked. Nothing is dropped
# or added, so a healthy bus gets the same reads.
def interleave_by_circuit(reads: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    queues: dict[str, deque[tuple[str, str]]] = {}
    for read in reads:
        queues.setdefault(read[0].casefold(), deque()).append(read)
    ordered: list[tuple[str, str]] = []
    while queues:
        for circuit_key in list(queues):
            ordered.append(queues[circuit_key].popleft())
            if not queues[circuit_key]:
                del queues[circuit_key]
    return ordered
