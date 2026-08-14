"""Entity mapping — pure function from device graph to HA EntityDescriptions."""

from __future__ import annotations

import logging
from copy import copy
from typing import Any

from .mapping import REGISTER_MAP, RegisterMeta, get_meta, multi_field_fields, split_multi_field
from .models import DeviceGraph, DeviceNode, DeviceType, EbusdRegister

_LOGGER = logging.getLogger(__name__)

_PLACEHOLDER_VALUES = frozenset({"-", "empty", "", "unknown", "unavailable"})
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
        """Return HA platform type (sensor, binary_sensor, etc.)."""
        return self.meta.entity_type or ("binary_sensor" if self._is_binary else "sensor")

    @property
    def _is_binary(self) -> bool:
        """Heuristic: raw value looks like on/off/true/false."""
        low = self.raw_value.lower().strip() if self.raw_value else ""
        return low in ("on", "off", "true", "false", "1", "0", "yes", "no")


def _is_numeric(value: str) -> bool:
    """Check if string can be parsed as a number."""
    try:
        float(value)
        return True
    except ValueError, TypeError:
        return False


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
        if register.writable:
            return "switch"
        return "binary_sensor"
    if register.writable and _is_numeric(raw_value):
        meta_min = meta.min_value
        meta_max = meta.max_value
        if meta_min is not None and meta_max is not None:
            return "number"

    return "sensor"


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
    if known_in_map:
        return True
    if node_has_data:
        return True
    if raw_value is not None:
        rv = raw_value.strip().lower()
        if rv not in _PLACEHOLDER_VALUES and "no data" not in rv:
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
    active_zones = {
        node.circuit for node in graph.nodes.values() if node.device_type == DeviceType.ZONE and node.has_data
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
                continue
        elif name_lower.startswith(_DHW_PREFIXES) and "dhw" in graph.nodes:
            entity._device_circuit = "dhw"

        redistributed.append(entity)

    return redistributed


class EntityFactoryService:
    """Pure mapper: device graph + REGISTER_MAP → EntityDescription list."""

    def generate(
        self,
        graph: DeviceGraph,
        yaml_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> list[EntityDescription]:
        """Generate HA entity descriptions from a device graph."""
        overrides = yaml_overrides or {}
        seen: set[str] = set()
        entities: list[EntityDescription] = []

        reg_to_node: dict[str, DeviceNode] = {}
        for node in graph.nodes.values():
            for rk in node.registers:
                reg_to_node[rk] = node

        for node in graph.nodes.values():
            for rk in node.registers:
                if rk.lower() in seen:
                    continue
                if "." not in rk:
                    continue
                seen.add(rk.lower())

                circuit, name = rk.split(".", 1)
                raw = graph.raw_registers.get(rk)
                base_meta = get_meta(circuit, name)

                override = overrides.get(rk) or {}
                meta = _merge_overrides(base_meta, override)

                dc = _resolve_device_circuit(rk, node, graph)
                if dc is None:
                    continue
                if override.get("device_circuit"):
                    dc = override["device_circuit"]

                entity_enabled = _determine_enabled_by_default(rk, raw, node.has_data, meta)

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
                            field_meta.entity_type = _classify_register(
                                field_reg, field_name, field_raw, field_meta
                            )
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
