"""One table of the plain-`r` registers the integration re-reads itself, because ebusd never polls them.

A plain `r` message is read by ebusd only when someone asks. Once `find` lists it, the map-driven pass of
`plan_fallback_reads` skips it, so without an explicit re-read its value freezes at the first read. That bug came back
six times (#171, #193, #207, #213, #223, #227), each time fixed with its own list. Every such rule now lives in
`REREAD_RULES`: what to read, why, and how often. The planner expands the table and filters each read through its
single `_add` gate (passive, withheld, error and hardware blocks), so a rule only nominates and never bypasses a gate.

Pure module: no I/O and no Home Assistant imports.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from .mapping import HMUX0_SW0407_ACTIVE_READ_REGISTERS, hmux0_precise_temperature_owner, hmux0_sw0407_circuit
from .models import DeviceGraph, zone_circuit_declared_inactive
from .runtime_definitions import (
    DISCOVERED_PLAIN_READ_POLLED_REGISTERS,
    HEAT_PUMP_PLAIN_READ_ENERGY_REGISTERS,
    HEAT_PUMP_PLAIN_READ_EVERY_POLL_REGISTERS,
    HMUX0_COMPRESSOR_COUNTER_NAMES,
    HWC_TIMER_SLOT_FIELDS,
    INTEGRATION_POLLED_CONTROLLER_REGISTERS,
)

# Register names of the HMUX0 precise (1/16 degC) temperatures that need an explicit active read.
HMUX0_PRECISE_TEMPERATURE_NAMES = ("RunDataFlowTemp", "RunDataReturnTemp")
# Heating-circuit state registers the climate entity derives `hvac_action` from (issue #207).
ZONE_STATE_REGISTER = re.compile(r"^Hc(\d+)(?:Pump)?Status$", re.IGNORECASE)

Read = tuple[str, str]
Nominator = Callable[[DeviceGraph, Mapping[str, str]], list[Read]]


class Cadence(Enum):
    """How often a rule's registers are re-read."""

    EVERY_POLL = "every_poll"
    ENERGY_INTERVAL = "energy_interval"


@dataclass(frozen=True)
class RereadRule:
    """One reason to re-read plain-`r` registers: the issue that proved it, its cadence and its nominator."""

    issue: str
    cadence: Cadence
    nominate: Nominator


# True when a runtime definition is one of the plain-`r` messages the energy poll re-reads: B516 energy counters
# (#53/#97), the HMUX0 compressor counters, the controller registers moved off `r5` (#193) and the hot water timer
# slots (#208).
def _is_energy_polled_definition(access: str, name: str, message: str, definition: str) -> bool:
    if access != "r":
        return False
    return (
        message == "B516"
        or (message == "B511" and name in HMUX0_COMPRESSOR_COUNTER_NAMES)
        or (message == "B524" and name in INTEGRATION_POLLED_CONTROLLER_REGISTERS)
        or (message == "B555" and definition.endswith(HWC_TIMER_SLOT_FIELDS))
    )


# Nominate the integration's own plain-`r` definitions that the energy poll re-reads, on a circuit the graph has.
def _energy_polled_definitions(graph: DeviceGraph, runtime_definitions: Mapping[str, str]) -> list[Read]:
    node_keys = {node_key.casefold() for node_key in graph.nodes}
    reads: list[Read] = []
    for definition in runtime_definitions.values():
        access, circuit, name, _, _, _, message = definition.split(",", 7)[:7]
        if _is_energy_polled_definition(access, name, message, definition) and circuit.casefold() in node_keys:
            reads.append((circuit, name))
    return reads


# Nominate the discovered registers whose name is in `names`, on the circuit where they were discovered. With
# `circuit`, only registers of that circuit are nominated.
def _discovered_reads(graph: DeviceGraph, names: frozenset[str], circuit: str | None = None) -> list[Read]:
    reads: list[Read] = []
    for key in (*graph.raw_registers, *graph.placeholder_registers):
        key_circuit, _, name = key.partition(".")
        if name in names and (circuit is None or key_circuit.casefold() == circuit.casefold()):
            reads.append((key_circuit, name))
    return reads


# Nominate plain-`r` registers that ebusd's own CSV defines (issue #227), on the circuit where they were discovered.
def _discovered_plain_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    return _discovered_reads(graph, DISCOVERED_PLAIN_READ_POLLED_REGISTERS)


# Nominate the plain-`r` registers in `names` on the unique discovered heat pump only (issue #233).
def _heat_pump_reads(graph: DeviceGraph, names: frozenset[str]) -> list[Read]:
    heat_pump = graph.heat_pump_result().node
    if heat_pump is None:
        return []
    return _discovered_reads(graph, names, heat_pump.circuit)


# Nominate the heat pump counters of issue #233 for the energy interval.
def _heat_pump_energy_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    return _heat_pump_reads(graph, HEAT_PUMP_PLAIN_READ_ENERGY_REGISTERS)


# Nominate the heat pump source temperatures of issue #233 for every poll.
def _heat_pump_every_poll_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    return _heat_pump_reads(graph, HEAT_PUMP_PLAIN_READ_EVERY_POLL_REGISTERS)


# Nominate the HMUX0 precise temperatures on the evidenced firmware owner only (#171), when the graph lists them.
def _hmux0_precise_temperatures(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    owner = hmux0_precise_temperature_owner(graph)
    if owner is None:
        return []
    discovered = {key.casefold() for key in (*graph.raw_registers, *graph.placeholder_registers)}
    return [(owner, name) for name in HMUX0_PRECISE_TEMPERATURE_NAMES if f"{owner}.{name}".casefold() in discovered]


# Nominate the SW0407 registers the integration defined itself as plain `r` (discussion #213), on the confirmed owner.
# Without its runtime definition ebusd cannot read the register, so nothing is nominated when the define is absent.
def hmux0_sw0407_active_reads(graph: DeviceGraph, runtime_definitions: Mapping[str, str]) -> list[Read]:
    owner = hmux0_sw0407_circuit(graph)
    if owner is None:
        return []
    reads: list[Read] = []
    for definition in runtime_definitions.values():
        parts = definition.split(",", 3)
        if (
            len(parts) >= 3
            and parts[0] == "r"
            and parts[1].casefold() == owner.casefold()
            and parts[2] in HMUX0_SW0407_ACTIVE_READ_REGISTERS
        ):
            reads.append((owner, parts[2]))
    return reads


# Nominate `Hc<N>Status`/`Hc<N>PumpStatus` of the discovered controller (#207). A circuit the controller reports as
# inactive is skipped: it has no climate entity, so reading it would only cost bus time.
def _zone_state_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    controller = graph.heating_controller_result().node
    if controller is None:
        return []
    prefix = f"{controller.circuit}.".casefold()
    reads: list[Read] = []
    for key in graph.raw_registers:
        if not key.casefold().startswith(prefix):
            continue
        name = key.split(".", 1)[1]
        match = ZONE_STATE_REGISTER.match(name)
        if match and not zone_circuit_declared_inactive(graph, controller.circuit, match.group(1)):
            reads.append((controller.circuit, name))
    return reads


# Every re-read rule, in planning order. The order is part of the behaviour: the planner keeps the first nomination
# of a register and keeps the order of reads per circuit.
REREAD_RULES: tuple[RereadRule, ...] = (
    RereadRule("#53/#97/#193/#208", Cadence.ENERGY_INTERVAL, _energy_polled_definitions),
    RereadRule("#227", Cadence.ENERGY_INTERVAL, _discovered_plain_reads),
    RereadRule("#233", Cadence.ENERGY_INTERVAL, _heat_pump_energy_reads),
    RereadRule("#171", Cadence.EVERY_POLL, _hmux0_precise_temperatures),
    RereadRule("#213", Cadence.EVERY_POLL, hmux0_sw0407_active_reads),
    RereadRule("#207", Cadence.EVERY_POLL, _zone_state_reads),
    RereadRule("#233", Cadence.EVERY_POLL, _heat_pump_every_poll_reads),
)


# Expand the rules due this cycle into reads, in table order. Energy-interval rules run only when `include_energy`.
# An empty graph nominates nothing.
def plan_rereads(
    graph: DeviceGraph,
    runtime_definitions: Mapping[str, str],
    *,
    include_energy: bool,
    rules: tuple[RereadRule, ...] = REREAD_RULES,
) -> list[Read]:
    if not graph:
        return []
    reads: list[Read] = []
    for rule in rules:
        if rule.cadence is Cadence.ENERGY_INTERVAL and not include_energy:
            continue
        reads.extend(rule.nominate(graph, runtime_definitions))
    return reads
