"""Entity factory — generate HA entities from discovered ebusd registers."""

from __future__ import annotations

from typing import Any

from .mapping import REGISTER_MAP, RegisterMeta, get_meta
from .models import EbusdRegister

HIDDEN_BROADCAST = {"id", "idanswer", "load", "signoflife"}


def _infer_device_circuit(circuit: str, name: str) -> str | None:
    if circuit == "Broadcast":
        return "hmu"
    if circuit == "ctlv2":
        if name.startswith(("Hwc", "Cylinder", "MaxCylinder", "DHW", "Solar")):
            return "dhw"
        if name.startswith(("Z1", "Hc1")):
            return "z1"
    return None


def _is_hidden_register(register: EbusdRegister) -> bool:
    circuit = register.circuit
    name = register.name.lower()
    if circuit.lower().startswith("scan"):
        return True
    if circuit.lower() in ("memory",):
        return True
    if name.startswith(("cctimer_", "hwctimer_", "z1timer_", "z2timer_", "z3timer_")):
        return True
    if name.startswith(("prfuelsum",)):
        return True
    if name.startswith(("installer", "phonenumber", "keycode", "maintenancedate", "maintenancedue")):
        return True
    if name in ("general_valuerange", "date_time", "datetime"):
        return True
    if circuit == "Broadcast" and name.lower() in HIDDEN_BROADCAST:
        return True
    if name.startswith(("hc2", "hc3", "z2", "z3")):
        # ponytail: single-zone system (HC1+Z1 only). Remove for multi-zone setups.
        return True
    return False


class EntityDescription:
    def __init__(
        self,
        circuit: str,
        name: str,
        field: str,
        meta: RegisterMeta,
        register: EbusdRegister,
        raw_value: str | None = None,
    ) -> None:
        self.circuit = circuit
        self.name = name
        self.field = field
        self.meta = meta
        self.register = register
        self.raw_value = raw_value or ""

    @property
    def unique_id(self) -> str:
        suffix = self.name.lower().replace(" ", "_")
        if self.field != "value":
            suffix += f"_{self.field}"
        return f"ebusd_{self.circuit}_{suffix}"

    @property
    def key(self) -> str:
        return f"{self.circuit}.{self.name}.{self.field}"

    @property
    def device_circuit(self) -> str:
        if self.meta.device_circuit:
            return self.meta.device_circuit
        inferred = _infer_device_circuit(self.circuit, self.name)
        return inferred or self.circuit

    @property
    def entity_type(self) -> str:
        return self.meta.entity_type or ("binary_sensor" if self._is_binary else "sensor")

    @property
    def _is_binary(self) -> bool:
        low = self.raw_value.lower().strip() if self.raw_value else ""
        return low in ("on", "off", "true", "false", "1", "0", "yes", "no")


def _is_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _classify_register(
    register: EbusdRegister, field: str, raw_value: str | None
) -> str:
    meta = get_meta(register.circuit, register.name, field)
    if meta.entity_type:
        return meta.entity_type

    if raw_value is None or raw_value == "" or raw_value == "-":
        return "sensor"

    low = raw_value.strip().lower()
    if low in ("on", "off", "true", "false"):
        return "binary_sensor" if not register.writable else "switch"
    if low in ("0", "1", "yes", "no"):
        if register.writable:
            return "switch"
        return "binary_sensor"
    if not _is_numeric(raw_value) and ";" not in raw_value:
        pass

    if register.writable and _is_numeric(raw_value):
        meta_min = meta.min_value
        meta_max = meta.max_value
        if meta_min is not None and meta_max is not None:
            return "number"

    return "sensor"


def generate_entity_descriptions(
    registers: list[EbusdRegister],
    yaml_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[EntityDescription]:
    overrides = yaml_overrides or {}
    seen: set[str] = set()
    entities: list[EntityDescription] = []

    for reg in registers:
        if _is_hidden_register(reg):
            continue

        for field in reg.fields:
            raw = reg.value.get(field)
            key = f"{reg.circuit}.{reg.name}.{field}"
            entity_key = f"{reg.circuit}.{reg.name}"
            if field == "value":
                entity_key = key

            if entity_key in seen:
                continue
            seen.add(entity_key)

            meta = get_meta(reg.circuit, reg.name, field)
            override = overrides.get(f"{reg.circuit}.{reg.name}") or {}
            override = overrides.get(key) or override

            merged_meta = _merge_overrides(meta, override)

            if merged_meta.entity_type == "":
                merged_meta.entity_type = _classify_register(reg, field, raw)

            known_register = f"{reg.circuit}.{reg.name}" in REGISTER_MAP
            if not reg.has_data and not known_register:
                merged_meta.enabled = False

            if not merged_meta.enabled:
                continue

            entity = EntityDescription(
                circuit=reg.circuit,
                name=reg.name,
                field=field,
                meta=merged_meta,
                register=reg,
                raw_value=raw,
            )
            entities.append(entity)

    discovered_keys = {f"{reg.circuit}.{reg.name}" for reg in registers}
    for map_key, meta in REGISTER_MAP.items():
        if map_key in discovered_keys or map_key in seen:
            continue
        if map_key.count(".") != 1:
            continue
        circuit, name = map_key.split(".", 1)
        virtual_reg = EbusdRegister(
            circuit=circuit,
            name=name,
            fields=["value"],
            value={"value": None},
            has_data=False,
        )
        merged = _merge_overrides(meta, overrides.get(map_key) or {})
        if not merged.enabled:
            continue
        entity = EntityDescription(
            circuit=circuit,
            name=name,
            field="value",
            meta=merged,
            register=virtual_reg,
            raw_value=None,
        )
        entities.append(entity)

    return entities


def _merge_overrides(meta: RegisterMeta, override: dict[str, Any]) -> RegisterMeta:
    if not override:
        return meta
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
