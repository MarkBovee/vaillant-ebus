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

from .hardware_profiles import FIRMWARE_ENERGY_REREADS, profile_owner
from .mapping import (
    HMUX0_SW0407_ACTIVE_READ_REGISTERS,
    REGISTER_MAP,
    hmux0_precise_temperature_owner,
    hmux0_sw0406_owner,
    hmux0_sw0407_circuit,
)
from .models import DeviceGraph, zone_circuit_declared_inactive
from .runtime_definitions import (
    BOILER_PLAIN_READ_ENERGY_REGISTERS,
    DISCOVERED_PLAIN_READ_POLLED_REGISTERS,
    HEAT_PUMP_LIVE_ENERGY_REGISTERS,
    HEAT_PUMP_LIVE_EVERY_POLL_REGISTERS,
    HEAT_PUMP_PLAIN_READ_ENERGY_REGISTERS,
    HEAT_PUMP_PLAIN_READ_EVERY_POLL_REGISTERS,
    HEAT_PUMP_SETTING_NAMES,
    HMUX0_COMPRESSOR_COUNTER_NAMES,
    HMUX0_SW0406_ACTIVE_READ_REGISTERS,
    HMUX0_SW0406_ENERGY_READ_REGISTERS,
    HWC_CIRCULATION_PUMP_STATUS,
    HWC_TIMER_SLOT_FIELDS,
    INTEGRATION_POLLED_CONTROLLER_REGISTERS,
    TIMER_WEEKDAYS,
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
    # The 15-minute placeholder interval (`PLACEHOLDER_POLL_INTERVAL`), for values that change only when edited.
    PLACEHOLDER_INTERVAL = "placeholder_interval"


@dataclass(frozen=True)
class RereadRule:
    """One reason to re-read plain-`r` registers: the issue that proved it, its cadence and its nominator."""

    issue: str
    cadence: Cadence
    nominate: Nominator


# True when a runtime definition is one of the plain-`r` messages the energy poll re-reads: B516 energy counters
# (#53/#97), the HMUX0 compressor counters, the controller registers moved off `r5` (#193), the hot water timer
# slots (#208), the heat pump installer settings (#218) and the SW0406 refrigerant temperatures (#205).
def _is_energy_polled_definition(access: str, name: str, message: str, definition: str) -> bool:
    if access != "r":
        return False
    return (
        message == "B516"
        or (message == "B511" and name in HMUX0_COMPRESSOR_COUNTER_NAMES)
        or (message == "B524" and name in INTEGRATION_POLLED_CONTROLLER_REGISTERS)
        or (message == "B51A" and name in HEAT_PUMP_SETTING_NAMES)
        or (message == "B509" and name in HMUX0_SW0406_ENERGY_READ_REGISTERS)
        # Only the hot water slots of issue #208 here; the silent mode and BASS3 calendar slots follow the 15-minute
        # `_calendar_slot_reads` rule (issue #256), limited to the slots the controller counts.
        or (message == "B555" and name.startswith("HwcTimer_") and definition.endswith(HWC_TIMER_SLOT_FIELDS))
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


# Nominate the boiler fuel counters of discussion #242 where the integration maps them (exact REGISTER_MAP key), so a
# heat pump or module that lists the same B516 names gets no extra reads.
def _boiler_fuel_energy_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    return [
        (circuit, name)
        for circuit, name in _discovered_reads(graph, BOILER_PLAIN_READ_ENERGY_REGISTERS)
        if f"{circuit}.{name}" in REGISTER_MAP
    ]


# Nominate the firmware-specific counters of `FIRMWARE_ENERGY_REREADS` on their profile's owner (issue #233).
def _firmware_energy_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    reads: list[Read] = []
    for profile, names in FIRMWARE_ENERGY_REREADS:
        owner = profile_owner(graph, profile)
        if owner is not None:
            reads.extend(_discovered_reads(graph, names, owner))
    return reads


# Nominate the hot water circulation pump state of the discovered controller for every poll (issue #233). ebusd
# defines it as a plain `r` message, so it froze or went unknown and the discovery switched the entity off.
def _hwc_circulation_pump_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    controller = graph.heating_controller_result().node
    if controller is None:
        return []
    return _discovered_reads(graph, frozenset({HWC_CIRCULATION_PUMP_STATUS}), controller.circuit)


# Nominate the heat pump source temperatures of issue #233 for every poll.
def _heat_pump_every_poll_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    return _heat_pump_reads(graph, HEAT_PUMP_PLAIN_READ_EVERY_POLL_REGISTERS)


# Nominate the heat pump power and yield of issue #259 for every poll.
def _heat_pump_live_power_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    return _heat_pump_reads(graph, HEAT_PUMP_LIVE_EVERY_POLL_REGISTERS)


# Nominate the slow heat pump live values of issue #259 (flow, weighted supply temperature, energy integral) for the
# energy interval.
def _heat_pump_live_energy_reads(graph: DeviceGraph, _definitions: Mapping[str, str]) -> list[Read]:
    return _heat_pump_reads(graph, HEAT_PUMP_LIVE_ENERGY_REGISTERS)


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


# Nominate the SW0406 registers the integration defined itself as plain `r` (issue #205), on the SW0406 owner. When
# ebusd loads its own hmux0 CSV the integration defines nothing for SW0406, so nothing is nominated then.
def _hmux0_sw0406_active_reads(graph: DeviceGraph, runtime_definitions: Mapping[str, str]) -> list[Read]:
    owner = hmux0_sw0406_owner(graph)
    if owner is None:
        return []
    reads: list[Read] = []
    for definition in runtime_definitions.values():
        parts = definition.split(",", 3)
        if (
            len(parts) >= 3
            and parts[0] == "r"
            and parts[1].casefold() == owner.casefold()
            and parts[2] in HMUX0_SW0406_ACTIVE_READ_REGISTERS
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


# A slot or count message of a weekly program: `<prefix>_<Day><slot>` or `<prefix>_Timeslots`.
_PROGRAM_MESSAGE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9]+Timer)_(?:(?P<count>Timeslots)|(?P<day>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday"
    r"|Sunday)(?P<slot>\d))$"
)
_WEEKDAY_INDEX = {day: index for index, day in enumerate(TIMER_WEEKDAYS)}


# Return the slot count per weekday of a program from the graph, or None while it is unknown or not seven numbers.
def _graph_slot_counts(graph: DeviceGraph, circuit: str, prefix: str) -> list[int] | None:
    expected = f"{circuit}.{prefix}_Timeslots".casefold()
    raw = next((value for key, value in graph.raw_registers.items() if key.casefold() == expected), None)
    try:
        counts = [int(part.strip()) for part in (raw or "").split(";")]
    except ValueError:
        return None
    return counts if len(counts) == len(TIMER_WEEKDAYS) else None


# Nominate the calendar programs the integration reads over its own `B555` slot set (CTLV3 silent mode, BASS3), plus
# ebusd's own slot-0 messages of the same programs, for the 15-minute interval (issue #256: slots 1 and 2 were never
# re-read, so the calendar showed slot 0 only). The count message comes first; a slot at or above the day's last
# known count is skipped, which keeps the 88 BASS3 slots down to the ones in use. While the count is unknown every slot
# is read.
def _calendar_slot_reads(graph: DeviceGraph, runtime_definitions: Mapping[str, str]) -> list[Read]:
    names_by_program: dict[tuple[str, str], set[str]] = {}
    for definition in runtime_definitions.values():
        access, circuit, name, _, _, _, message = definition.split(",", 7)[:7]
        match = _PROGRAM_MESSAGE.match(name)
        if (
            access != "r"
            or message != "B555"
            or match is None
            or _is_energy_polled_definition(access, name, message, definition)
        ):
            continue
        names_by_program.setdefault((circuit, match["prefix"]), set()).add(name)
    reads: list[Read] = []
    for (circuit, prefix), names in names_by_program.items():
        for key in (*graph.raw_registers, *graph.placeholder_registers):
            key_circuit, _, name = key.partition(".")
            match = _PROGRAM_MESSAGE.match(name)
            if key_circuit.casefold() == circuit.casefold() and match is not None and match["prefix"] == prefix:
                names.add(name)
        counts = _graph_slot_counts(graph, circuit, prefix)
        count_names = sorted(name for name in names if name.endswith("_Timeslots"))
        slot_names = sorted(name for name in names if not name.endswith("_Timeslots"))
        reads.extend((circuit, name) for name in count_names)
        for name in slot_names:
            match = _PROGRAM_MESSAGE.match(name)
            if match is None or match["day"] is None:
                continue
            if counts is not None and int(match["slot"]) >= counts[_WEEKDAY_INDEX[match["day"]]]:
                continue
            reads.append((circuit, name))
    return reads


# Every re-read rule, in planning order. The order is part of the behaviour: the planner keeps the first nomination
# of a register and keeps the order of reads per circuit.
REREAD_RULES: tuple[RereadRule, ...] = (
    RereadRule("#53/#97/#193/#208", Cadence.ENERGY_INTERVAL, _energy_polled_definitions),
    RereadRule("#227", Cadence.ENERGY_INTERVAL, _discovered_plain_reads),
    RereadRule("#233", Cadence.ENERGY_INTERVAL, _heat_pump_energy_reads),
    RereadRule("#233 SW0308", Cadence.ENERGY_INTERVAL, _firmware_energy_reads),
    RereadRule("#242", Cadence.ENERGY_INTERVAL, _boiler_fuel_energy_reads),
    RereadRule("#259", Cadence.ENERGY_INTERVAL, _heat_pump_live_energy_reads),
    RereadRule("#171", Cadence.EVERY_POLL, _hmux0_precise_temperatures),
    RereadRule("#213", Cadence.EVERY_POLL, hmux0_sw0407_active_reads),
    RereadRule("#205 SW0406", Cadence.EVERY_POLL, _hmux0_sw0406_active_reads),
    RereadRule("#207", Cadence.EVERY_POLL, _zone_state_reads),
    RereadRule("#233", Cadence.EVERY_POLL, _heat_pump_every_poll_reads),
    RereadRule("#259", Cadence.EVERY_POLL, _heat_pump_live_power_reads),
    RereadRule("#233 HWC", Cadence.EVERY_POLL, _hwc_circulation_pump_reads),
    RereadRule("#256", Cadence.PLACEHOLDER_INTERVAL, _calendar_slot_reads),
)


# Expand the rules due this cycle into reads, in table order. Energy-interval rules run only when `include_energy`,
# placeholder-interval rules only when `include_placeholders`. An empty graph nominates nothing.
def plan_rereads(
    graph: DeviceGraph,
    runtime_definitions: Mapping[str, str],
    *,
    include_energy: bool,
    include_placeholders: bool = False,
    rules: tuple[RereadRule, ...] = REREAD_RULES,
) -> list[Read]:
    if not graph:
        return []
    reads: list[Read] = []
    for rule in rules:
        if rule.cadence is Cadence.ENERGY_INTERVAL and not include_energy:
            continue
        if rule.cadence is Cadence.PLACEHOLDER_INTERVAL and not include_placeholders:
            continue
        reads.extend(rule.nominate(graph, runtime_definitions))
    return reads
