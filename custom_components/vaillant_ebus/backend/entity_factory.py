"""Entity mapping — pure function from device graph to HA EntityDescriptions."""

from __future__ import annotations

import logging
import re
from copy import copy
from typing import Any

from .mapping import (
    ELOBLOCK_GAS_REGISTERS,
    REGISTER_MAP,
    get_meta,
    is_field_key,
    multi_field_fields,
    secondary_zone_setting_number,
    split_multi_field,
)
from .models import (
    DeviceGraph,
    DeviceNode,
    DeviceType,
    EbusdRegister,
    RegisterMeta,
    is_no_data_value,
)

_LOGGER = logging.getLogger(__name__)

_DHW_PREFIXES = ("dhw", "hwc", "cylinder", "maxcylinder", "solar")


class EntityDescription:
    """Store entity metadata linking register to HA platform."""

    def __init__(
        self,
        circuit: str,
        name: str,
        field: str,
        meta: RegisterMeta,
        register: EbusdRegister,
        raw_value: str | None = None,
        enabled_by_default: bool = True,
        device_circuit: str | None = None,
    ) -> None:
        self.circuit = circuit
        self.name = name
        self.field = field
        self.meta = meta
        self.register = register
        self.raw_value = raw_value or ""
        self.enabled_by_default = enabled_by_default
        self._device_circuit = device_circuit

    @property
    def unique_id(self) -> str:
        """Globally unique entity identifier for HA registry."""
        suffix = self.name.lower().replace(" ", "_")
        if self.field != "value":
            suffix += f"_{self.field}"
        return f"ebusd_{self.circuit}_{suffix}"

    @property
    def key(self) -> str:
        """Dot-separated key for data lookup."""
        return f"{self.circuit}.{self.name}.{self.field}"

    @property
    def device_circuit(self) -> str:
        """Resolve logical device circuit for grouping in HA."""
        if self.meta.device_circuit:
            return self.meta.device_circuit
        return self._device_circuit or self.circuit

    @property
    def entity_type(self) -> str:
        """Return HA platform type (sensor, binary_sensor, etc.).

        `generate()` always classifies before construction, so this is set
        for every production entity.
        """
        return self.meta.entity_type


def _is_numeric(value: str) -> bool:
    """Check if string can be parsed as a number."""
    try:
        float(value)
        return True
    except ValueError, TypeError:
        return False


# Intent: register-name fragments that mark a numeric measurement (counter, energy, power) rather than a flag.
# Why: a counter that currently reads 0 or 1 (for example YieldTotal at 0) must stay a sensor and not flip
# into a binary_sensor that disagrees with its own later values.
_NUMERIC_MEASURE_NAME_PATTERN = re.compile(
    r"(yield|energy|hours|starts|cycles|count|total|sum(?!mer)|power|consumption)", re.IGNORECASE
)


def _classify_register(
    register: EbusdRegister,
    field: str,
    raw_value: str | None,
    meta: RegisterMeta,
) -> str:
    """Auto-detect HA platform type for a register+value."""
    if meta.entity_type:
        return meta.entity_type

    if raw_value is None or raw_value == "" or raw_value == "-":
        return "sensor"

    low = raw_value.strip().lower()
    if low in ("on", "off", "true", "false"):
        return "binary_sensor" if not register.writable else "switch"
    if low in ("0", "1", "yes", "no"):
        if meta.unit or meta.device_class:
            return "sensor"
        if not register.writable and _NUMERIC_MEASURE_NAME_PATTERN.search(register.name):
            return "sensor"
        if register.writable:
            return "switch"
        return "binary_sensor"
    if register.writable and _is_numeric(raw_value):
        meta_min = meta.min_value
        meta_max = meta.max_value
        if meta_min is not None and meta_max is not None:
            return "number"

    return "sensor"


# Intent: merge user-facing overrides without changing the register's polling policy.
# Why: YAML entity overrides can adjust presentation, but cannot make unsafe fallback reads safe.
def _merge_overrides(meta: RegisterMeta, override: dict[str, Any]) -> RegisterMeta:
    """Merge YAML overrides into a RegisterMeta, returning new instance."""
    if not override:
        return copy(meta)
    merged = RegisterMeta(
        friendly_name=override.get("friendly_name", meta.friendly_name),
        icon=override.get("icon", meta.icon),
        unit=override.get("unit", meta.unit),
        device_class=override.get("device_class", meta.device_class),
        state_class=override.get("state_class", meta.state_class),
        entity_category=override.get("entity_category", meta.entity_category),
        writable=override.get("writable", meta.writable),
        min_value=override.get("min", meta.min_value),
        max_value=override.get("max", meta.max_value),
        step=override.get("step", meta.step),
        options=override.get("options", meta.options),
        enabled=override.get("enabled", meta.enabled),
        entity_type=override.get("entity_type", meta.entity_type),
        device_circuit=override.get("device_circuit", meta.device_circuit),
        divisor=override.get("divisor", meta.divisor),
        fallback_read=meta.fallback_read,
    )
    return merged


def _determine_enabled_by_default(
    register_key: str,
    raw_value: str | None,
    node_has_data: bool,
    meta: RegisterMeta,
) -> bool:
    """Determine if entity should be enabled by default in HA."""
    if not meta.enabled:
        return False
    known_in_map = register_key in REGISTER_MAP
    mapped_variant = not known_in_map and bool(meta.friendly_name)
    if raw_value is not None:
        rv = raw_value.strip().lower()
        if is_no_data_value(rv) or "no data" in rv:
            return False
    if raw_value is None and not known_in_map and not mapped_variant:
        return False
    if known_in_map:
        return raw_value is not None
    if node_has_data:
        return True
    if raw_value is not None:
        return True
    return False


# Intent: report whether the controller itself declares heating circuit N unused.
# Why: ebusd keeps static defaults (heat curve, min flow) for unused circuits, so they look live (issue #152);
# only the controller's own `HcNCircuitType = inactive` is evidence, and an unreadable type must never hide a circuit.
def _heating_circuit_inactive(graph: DeviceGraph, circuit: str, number: str) -> bool:
    expected = f"{circuit}.Hc{number}CircuitType".casefold()
    value = next((raw for key, raw in graph.raw_registers.items() if key.casefold() == expected), None)
    return value is not None and value.strip().casefold() == "inactive"


_CIRCUIT_TYPE_KEY = re.compile(r"^([^.]+)\.Hc(\d+)CircuitType$", re.IGNORECASE)

# The ebusd circuit of the solar controller configuration (ec.sol.sc.csv).
SOLAR_CIRCUIT = "sc"


# Intent: list the (circuit, number) pairs of secondary heating circuits that the controller itself declares unused.
# Why: ebusd and the controller answer static defaults for zones that are not installed (day temperature 21.0, holiday
# dates 2015), so their registers look live and created about 40 entities for two zones that do not exist (the owner's
# HA, issue #152). Only `HcNCircuitType = inactive` is evidence. Zone 1 is never declared unused, an unreadable
# type never is, and a zone that reports a room temperature is kept because contradictory evidence must fail safe.
def declared_unused_zones(graph: DeviceGraph) -> frozenset[tuple[str, int]]:
    unused: set[tuple[str, int]] = set()
    for key, raw in graph.raw_registers.items():
        match = _CIRCUIT_TYPE_KEY.match(key)
        if match is None or int(match.group(2)) < 2:
            continue
        circuit, number = match.group(1), int(match.group(2))
        if raw is None or raw.strip().casefold() != "inactive":
            continue
        if _zone_reports_room_temperature(graph, circuit, number):
            continue
        unused.add((circuit.casefold(), number))
    return frozenset(unused)


# Intent: list the zone numbers that every reporting controller declares unused.
# Why: zone devices are shared by number across controllers, so a number is unused only when none of them uses it.
def _unused_zone_numbers(graph: DeviceGraph) -> frozenset[int]:
    declared = declared_unused_zones(graph)
    in_use = {
        int(match.group(2))
        for key in graph.raw_registers
        if (match := _CIRCUIT_TYPE_KEY.match(key)) and (match.group(1).casefold(), int(match.group(2))) not in declared
    }
    return frozenset({number for _, number in declared} - in_use)


# Intent: list the solar-controller circuits that only mirror the heating controller.
# Why: in all 14 captures with a scan of address `ec` the "solar controller" has the same SW and HW as the heating
# controller and every `sc` row reads `no data stored`; the controller answers at the solar address. A real solar module
# has its own identity and answers its registers, so either difference keeps the circuit.
def ghost_solar_circuits(graph: DeviceGraph) -> frozenset[str]:
    all_keys = (*graph.raw_registers, *graph.placeholder_registers)
    solar_keys = [key for key in all_keys if _circuit_of(key) == SOLAR_CIRCUIT]
    if not solar_keys:
        return frozenset()
    if any(key in graph.raw_registers and not is_no_data_value(graph.raw_registers[key]) for key in solar_keys):
        return frozenset()
    controller = graph.heating_controller_result().node
    scans = [identity for identity in graph.scan_identities if identity.scan_type.upper().startswith("SOL")]
    if controller is None or not controller.scan_sw or not scans:
        return frozenset()
    mirrored = all(
        identity.complete and (identity.scan_sw, identity.scan_hw) == (controller.scan_sw, controller.scan_hw)
        for identity in scans
    )
    return frozenset({SOLAR_CIRCUIT}) if mirrored else frozenset()


# Intent: return the zone or heating-circuit number of a zone node circuit such as `z2` or `hc3`, or None.
def _zone_node_number(circuit: str) -> int | None:
    digits = re.sub(r"^\D+", "", circuit)
    return int(digits) if digits.isdigit() else None


# Intent: return the lower-cased circuit part of a `circuit.name` register key.
def _circuit_of(register_key: str) -> str:
    return register_key.partition(".")[0].casefold()


# Intent: report whether zone N currently reports a real room temperature.
# Why: the controller keeps static defaults for a zone that is not installed (issue #186, Z3); only a live room
# temperature proves the zone exists, so writable settings must not appear for a placeholder zone.
def _zone_reports_room_temperature(graph: DeviceGraph, circuit: str, zone_number: int) -> bool:
    expected = f"{circuit}.Z{zone_number}RoomTemp".casefold()
    value = next((raw for key, raw in graph.raw_registers.items() if key.casefold() == expected), None)
    return value is not None and not is_no_data_value(value)


# Intent: give a placeholder zone's setting the empty metadata it had before zone templating.
# Why: the zone keeps showing its raw value as a plain sensor, exactly as in 1.11.1, without a write control.
def _placeholder_zone_meta() -> RegisterMeta:
    return RegisterMeta()


def _is_eloblock(graph: DeviceGraph) -> bool:
    """Identify the confirmed eloBLOCK VE 28 BAI hardware."""
    for key, raw in graph.raw_registers.items():
        if not key.lower().endswith(".partnumberbox"):
            continue
        normalized = "".join(character for character in (raw or "").lower() if character.isalnum())
        if normalized == "0020260270":
            return True
    return False


def _resolve_device_circuit(
    register_key: str,
    node: DeviceNode,
    graph: DeviceGraph,
) -> str | None:
    """Determine which HA device group this entity belongs to from the device graph.

    Returns None when the entity should be suppressed (no-data orphan circuit).
    """
    parent = node.parent
    if node.device_type == DeviceType.BUS:
        return parent or node.circuit
    if node.has_data:
        return node.circuit
    if parent:
        return parent
    if "." in register_key and register_key in graph.raw_registers:
        raw = graph.raw_registers[register_key]
        if raw is not None and not is_no_data_value(raw):
            return register_key.split(".", 1)[0]
    return None


# Intent: return a zone or heating-circuit number from a register name.
def _extract_prefixed_number(name: str, prefix: str) -> str:
    suffix = name[len(prefix) :]
    digits = ""
    for character in suffix:
        if not character.isdigit():
            break
        digits += character
    return digits


# Intent: place controller-owned sub-device registers on their logical devices.
def _redistribute_device_assignments(
    entities: list[EntityDescription],
    graph: DeviceGraph,
    yaml_overrides: dict[str, dict[str, Any]],
) -> list[EntityDescription]:
    # A zone the controller declares unused keeps no zone device, so its circuit type lands on the controller device.
    unused_numbers = _unused_zone_numbers(graph)
    active_zones = {
        node.circuit
        for node in graph.nodes.values()
        if node.device_type == DeviceType.ZONE
        and node.has_data
        and _zone_node_number(node.circuit) not in unused_numbers
    }
    redistributed: list[EntityDescription] = []

    for entity in entities:
        override = yaml_overrides.get(f"{entity.circuit}.{entity.name}", {})
        if override.get("device_circuit"):
            redistributed.append(entity)
            continue

        name_lower = entity.name.lower()
        zone_number = _extract_prefixed_number(name_lower, "z") if name_lower.startswith("z") else ""
        heating_circuit_number = _extract_prefixed_number(name_lower, "hc") if name_lower.startswith("hc") else ""
        target_zone = f"z{zone_number or heating_circuit_number}"

        if zone_number or heating_circuit_number:
            if target_zone in active_zones:
                entity._device_circuit = target_zone
            elif target_zone != "z1":
                entity._device_circuit = entity.circuit
        elif name_lower.startswith(_DHW_PREFIXES) and "dhw" in graph.nodes:
            entity._device_circuit = "dhw"
        elif name_lower == "hydraulicscheme" and entity.circuit.lower() == "sc":
            controller = graph.heating_controller()
            if controller:
                entity._device_circuit = controller.circuit

        redistributed.append(entity)

    return redistributed


class EntityFactoryService:
    """Pure mapper: device graph + REGISTER_MAP → EntityDescription list."""

    # Intent: map each discovered register using its owning hardware metadata.
    # Why: writable controls must not leak across controller variants.
    def generate(
        self,
        graph: DeviceGraph,
        yaml_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> list[EntityDescription]:
        """Generate HA entity descriptions from a device graph."""
        overrides = yaml_overrides or {}
        eloblock = _is_eloblock(graph)
        seen: set[str] = set()
        entities: list[EntityDescription] = []
        controller = graph.heating_controller_result().node
        unused_zones = declared_unused_zones(graph)
        ghost_solar = ghost_solar_circuits(graph)

        reg_to_node: dict[str, DeviceNode] = {}
        for node in graph.nodes.values():
            for rk in node.registers:
                reg_to_node.setdefault(rk, node)

        for node in graph.nodes.values():
            for rk in node.registers:
                if reg_to_node.get(rk) is not node:
                    continue
                if rk.lower() in seen:
                    continue
                if "." not in rk:
                    continue
                seen.add(rk.lower())

                circuit, name = rk.split(".", 1)
                name_lower = name.casefold()
                raw = graph.raw_registers.get(rk)
                # Keys containing a second dot are parsed fields of a parent
                # register, not standalone ebusd registers.
                if is_field_key(rk):
                    continue
                base_meta = copy(get_meta(circuit, name))
                zone_setting_number = secondary_zone_setting_number(name)
                if (
                    zone_setting_number is not None
                    and base_meta.writable
                    and not _zone_reports_room_temperature(graph, circuit, zone_setting_number)
                ):
                    base_meta = _placeholder_zone_meta()
                if (
                    name_lower == "hc1roomtempswitchon"
                    and controller is not None
                    and controller.circuit.casefold() == circuit.casefold()
                    and controller.scan_type.upper() == "CTLV3"
                    and controller.scan_sw.upper() == "0808"
                    and controller.scan_hw.upper() == "8004"
                ):
                    base_meta.friendly_name = "Room Temperature Influence (HC1)"
                    base_meta.icon = "mdi:thermostat"
                    base_meta.unit = ""
                    base_meta.writable = True
                    base_meta.options = ["off", "modulating", "thermostat"]
                    base_meta.entity_type = "select"
                    base_meta.entity_category = "config"

                # The threshold is an ebusd enum (`off`, `modulating`, `thermostat`), never a temperature (issue #152);
                # a unit on a text value makes the sensor report unknown, and the first reading may still be empty.
                if re.fullmatch(r"hc\d+roomtempswitchon", name_lower):
                    base_meta.unit = ""
                    base_meta.device_class = ""

                # Date-like empty sentinel is not a supported entity value;
                # unlike normal no-data placeholders it cannot become useful
                # through later polling and should not create a device.
                if raw and raw.strip() == "-.-.-":
                    continue

                # Do not expose opaque multi-field ebusd values as a raw sensor.
                # Registers with an explicit MULTI_FIELD_FIELDS mapping still
                # generate their parsed field entities below.
                if raw and ";" in raw and not multi_field_fields(rk) and not base_meta.friendly_name:
                    continue

                override = overrides.get(rk) or {}
                # Intent: skip registers of devices and zones that the bus proves unused; `enabled: true` overrides win.
                # Why: a mirrored solar controller and zones the controller declares inactive only add dead entities.
                if override.get("enabled") is not True:
                    if circuit.casefold() in ghost_solar:
                        continue
                    unused_match = re.match(r"^(?:Z|Hc)(\d+)", name, re.IGNORECASE)
                    if (
                        unused_match
                        and not name_lower.endswith("circuittype")
                        and (circuit.casefold(), int(unused_match.group(1))) in unused_zones
                    ):
                        continue
                keep_ctlv2_sensor = (
                    name_lower == "hc1roomtempswitchon"
                    and controller is not None
                    and controller.circuit.casefold() == circuit.casefold()
                )
                if name_lower == "hc1roomtempswitchon" and not keep_ctlv2_sensor:
                    continue
                live_zone_register = bool(
                    re.match(
                        r"^(?:Z\d+(?:RoomTemp|ActualRoomTempDesired)|Hc\d+(?:FlowTemp|ActualFlowTempDesired|PumpStatus))$",
                        name,
                        re.IGNORECASE,
                    )
                )
                if (
                    node.device_type == DeviceType.ZONE
                    and not node.has_data
                    and override.get("enabled") is not True
                    and not keep_ctlv2_sensor
                    and not (raw is not None and live_zone_register)
                ):
                    continue
                zone_match = re.match(r"^(?:Z|Hc)(\d+)", name, re.IGNORECASE)
                if (
                    zone_match
                    and override.get("enabled") is not True
                    and (zone_node := graph.nodes.get(f"z{zone_match.group(1)}")) is not None
                    and not zone_node.has_data
                    and name_lower != "hc1roomtempswitchon"
                ):
                    continue
                inactive_match = re.match(r"^Hc(\d+)", name, re.IGNORECASE)
                if (
                    inactive_match
                    and override.get("enabled") is not True
                    and not name_lower.endswith("circuittype")
                    and _heating_circuit_inactive(graph, circuit, inactive_match.group(1))
                ):
                    continue
                if (
                    node.device_type == DeviceType.ZONE
                    and not node.has_data
                    and node.circuit.startswith("hc")
                    and node.circuit[2:].isdigit()
                    and f"z{node.circuit[2:]}" in graph.nodes
                ):
                    continue
                meta = _merge_overrides(base_meta, override)
                # A metadata-only register is exposed only after ebusd returns a live value.
                if raw is None and not meta.fallback_read:
                    continue

                dc = _resolve_device_circuit(rk, node, graph)
                if dc is None:
                    continue
                if override.get("device_circuit"):
                    dc = override["device_circuit"]

                entity_enabled = override.get(
                    "enabled",
                    _determine_enabled_by_default(rk, raw, node.has_data, meta),
                )
                if (
                    name_lower == "hc1roomtempswitchon"
                    and override.get("entity_type", base_meta.entity_type) != "select"
                    and controller is not None
                    and controller.circuit.casefold() == circuit.casefold()
                    and controller.scan_type.upper() == "CTLV2"
                ):
                    entity_enabled = True
                if eloblock and circuit.lower() == "bai" and name in ELOBLOCK_GAS_REGISTERS:
                    entity_enabled = False
                # Why: the composite "a;b;c" Status string repeats values that the per-field entities
                # already expose and changes on almost every poll, which floods the recorder history.
                if name_lower.startswith("status") and multi_field_fields(rk) and override.get("enabled") is not True:
                    entity_enabled = False

                dummy_reg = EbusdRegister(
                    circuit=circuit,
                    name=name,
                    fields=["value"],
                    value={"value": raw},
                    has_data=node.has_data,
                    writable=meta.writable,
                )

                if not meta.entity_type:
                    meta.entity_type = _classify_register(dummy_reg, "value", raw, meta)

                entity = EntityDescription(
                    circuit=circuit,
                    name=name,
                    field="value",
                    meta=meta,
                    register=dummy_reg,
                    raw_value=raw,
                    enabled_by_default=entity_enabled,
                    device_circuit=dc,
                )
                entities.append(entity)

                field_names = multi_field_fields(rk)
                if field_names:
                    field_values = split_multi_field(rk, raw)
                    for field_name in field_names:
                        if field_name == "value":
                            # Single-field mappings reuse the base entity.
                            continue
                        field_raw = field_values.get(field_name)
                        field_meta = get_meta(circuit, name, field_name)
                        field_override = overrides.get(f"{rk}.{field_name}") or {}
                        field_meta = _merge_overrides(field_meta, field_override)
                        field_enabled = _determine_enabled_by_default(
                            f"{rk}.{field_name}", field_raw, node.has_data, field_meta
                        )
                        field_reg = EbusdRegister(
                            circuit=circuit,
                            name=name,
                            fields=[field_name],
                            value={field_name: field_raw},
                            has_data=field_raw is not None,
                            writable=field_meta.writable,
                        )
                        if not field_meta.entity_type:
                            field_meta.entity_type = _classify_register(field_reg, field_name, field_raw, field_meta)
                        entities.append(
                            EntityDescription(
                                circuit=circuit,
                                name=name,
                                field=field_name,
                                meta=field_meta,
                                register=field_reg,
                                raw_value=field_raw,
                                enabled_by_default=field_enabled,
                                device_circuit=dc,
                            )
                        )

        entities = _redistribute_device_assignments(entities, graph, overrides)
        _LOGGER.info("Generated %d entity descriptions from device graph", len(entities))
        return entities
