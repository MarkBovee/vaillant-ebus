"""Capability model — typed wrappers for discovered EEBUS features."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass
class Capability:
    """Single discoverable EEBUS feature with runtime state."""

    device_address: str
    entity: tuple[int, ...]
    feature: int
    feature_type: str
    role: str
    supported_commands: list[str] = field(default_factory=list)
    supported_use_cases: list[str] = field(default_factory=list)
    scope_type: str | None = None
    unit: str | None = None
    measurement_type: str | None = None
    parameter_id: int | None = None
    value: Any = None
    last_updated: float = 0.0

    @property
    def key(self) -> tuple[tuple[int, ...], int]:
        return (self.entity, self.feature)

    @property
    def has_value(self) -> bool:
        return self.value is not None

    @property
    def age(self) -> float:
        return time.time() - self.last_updated if self.last_updated else float("inf")


def _entity_key(entity: list[int]) -> tuple[int, ...]:
    return tuple(int(x) for x in entity)


def _feature_key(entity: list[int], feature: int) -> tuple[tuple[int, ...], int]:
    return (_entity_key(entity), int(feature))


class CapabilityRegistry:
    """Registry of all discovered capabilities.

    Single source of truth for what the remote device exposes.
    Populated during discovery, enriched by description data,
    updated by notifications and poll results.
    """

    def __init__(self) -> None:
        self._capabilities: dict[tuple[tuple[int, ...], int], Capability] = {}
        self._entity_types: dict[tuple[int, ...], str] = {}

    # -- registration --

    def register_entity_type(self, entity: list[int], entity_type: str) -> None:
        self._entity_types[_entity_key(entity)] = entity_type

    def get_entity_type(self, entity: list[int]) -> str | None:
        return self._entity_types.get(_entity_key(entity))

    def register_feature(
        self,
        device_address: str,
        entity: list[int],
        feature: int,
        feature_type: str,
        role: str,
    ) -> Capability:
        key = _feature_key(entity, feature)
        if key not in self._capabilities:
            self._capabilities[key] = Capability(
                device_address=device_address,
                entity=tuple(int(x) for x in entity),
                feature=int(feature),
                feature_type=feature_type,
                role=role,
            )
        return self._capabilities[key]

    def register_from_discovery(
        self, device_address: str, discovery: dict[str, Any]
    ) -> None:
        entities = discovery.get("entityInformation")
        if isinstance(entities, list):
            for item in entities:
                if not isinstance(item, dict):
                    continue
                desc = item.get("description")
                if not isinstance(desc, dict):
                    continue
                eaddr = desc.get("entityAddress")
                if not isinstance(eaddr, dict):
                    continue
                ent = eaddr.get("entity")
                etype = desc.get("entityType")
                if isinstance(ent, list) and all(isinstance(x, int) for x in ent) and isinstance(etype, str):
                    self.register_entity_type(ent, etype)

        features = discovery.get("featureInformation")
        if isinstance(features, list):
            for item in features:
                if not isinstance(item, dict):
                    continue
                desc = item.get("description")
                if not isinstance(desc, dict):
                    continue
                faddr = desc.get("featureAddress")
                if not isinstance(faddr, dict):
                    continue
                ent = faddr.get("entity")
                feat = faddr.get("feature")
                ftype = desc.get("featureType")
                role = desc.get("role")
                if (
                    isinstance(ent, list) and all(isinstance(x, int) for x in ent)
                    and isinstance(feat, int)
                    and isinstance(ftype, str)
                    and isinstance(role, str)
                ):
                    self.register_feature(
                        device_address=device_address,
                        entity=ent,
                        feature=feat,
                        feature_type=ftype,
                        role=role,
                    )

    # -- enrichment --

    def load_measurement_descriptions(
        self,
        entity: list[int],
        feature: int,
        desc_map: dict[int, dict[str, Any]],
    ) -> None:
        key = _feature_key(entity, feature)
        cap = self._capabilities.get(key)
        if cap is None:
            _LOGGER.debug("load_measurement_descriptions: no capability for %s", key)
            return
        cap.supported_commands.append("measurementListData")
        if desc_map:
            first = next(iter(desc_map.values()))
            cap.scope_type = first.get("scopeType") or cap.scope_type
            cap.unit = first.get("unit") or cap.unit
            cap.measurement_type = first.get("measurementType") or cap.measurement_type

    def load_electrical_connection_descriptions(
        self,
        entity: list[int],
        feature: int,
        ec_map: dict[int, dict[str, Any]],
    ) -> None:
        key = _feature_key(entity, feature)
        cap = self._capabilities.get(key)
        if cap is None:
            return
        cap.supported_commands.append("electricalConnectionParameterListData")
        if ec_map:
            first = next(iter(ec_map.values()))
            cap.scope_type = first.get("scopeType") or cap.scope_type
            cap.unit = first.get("unit") or cap.unit

    def register_use_cases(
        self,
        entity: list[int],
        feature: int,
        use_cases: list[str],
    ) -> None:
        key = _feature_key(entity, feature)
        cap = self._capabilities.get(key)
        if cap is None:
            return
        cap.supported_use_cases = list(use_cases)

    # -- value updates --

    def update_value(
        self,
        entity: list[int],
        feature: int,
        value: Any,
        *,
        scope_type: str | None = None,
        unit: str | None = None,
        measurement_id: int | None = None,
    ) -> None:
        key = _feature_key(entity, feature)
        cap = self._capabilities.get(key)
        if cap is None:
            cap = Capability(
                device_address="",
                entity=tuple(int(x) for x in entity),
                feature=int(feature),
                feature_type="unknown",
                role="server",
            )
            self._capabilities[key] = cap
        cap.value = value
        cap.last_updated = time.time()
        if scope_type is not None:
            cap.scope_type = scope_type
        if unit is not None:
            cap.unit = unit
        if measurement_id is not None:
            cap.parameter_id = measurement_id

    def update_command_support(self, entity: list[int], feature: int, command: str) -> None:
        key = _feature_key(entity, feature)
        cap = self._capabilities.get(key)
        if cap is not None and command not in cap.supported_commands:
            cap.supported_commands.append(command)

    # -- queries --

    @property
    def all(self) -> list[Capability]:
        return list(self._capabilities.values())

    def get(self, entity: list[int], feature: int) -> Capability | None:
        return self._capabilities.get(_feature_key(entity, feature))

    def by_feature_type(self, feature_type: str) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.feature_type == feature_type]

    def by_scope_type(self, scope_type: str) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.scope_type == scope_type]

    def by_entity_type(self, entity_type: str) -> list[Capability]:
        entities_of_type = {
            e for e, t in self._entity_types.items() if t == entity_type
        }
        return [
            c for c in self._capabilities.values()
            if c.entity in entities_of_type
        ]

    def with_value(self) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.has_value]

    def without_value(self) -> list[Capability]:
        return [c for c in self._capabilities.values() if not c.has_value]

    def servers(self) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.role == "server"]

    def clients(self) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.role == "client"]

    def subscribe_candidates(self) -> list[Capability]:
        return [c for c in self.servers() if c.feature_type not in ("NodeManagement", "DeviceClassification")]

    @property
    def measurement_scopes(self) -> dict[str, dict[str, str]]:
        scopes: dict[str, dict[str, str]] = {}
        for cap in self.all:
            if not cap.scope_type:
                continue
            s = cap.scope_type
            if s not in scopes:
                scopes[s] = {"scopeType": s, "unit": cap.unit or ""}
        return scopes

    def clear(self) -> None:
        self._capabilities.clear()
        self._entity_types.clear()


class UnknownFeatureRegistry:
    """Capped store for unknown/unhandled EEBUS packets.

    Prevents memory leak while preserving samples for reverse engineering.
    """

    def __init__(self, capacity: int = 50) -> None:
        self._capacity = capacity
        self._unknown_commands: list[dict[str, Any]] = []
        self._last_unknown: str | None = None
        self._unknown_feature_types: dict[str, int] = {}
        self._total_discarded: int = 0

    @property
    def unknown_commands(self) -> list[dict[str, Any]]:
        return list(self._unknown_commands)

    @property
    def last_unknown(self) -> str | None:
        return self._last_unknown

    @property
    def unknown_feature_types(self) -> dict[str, int]:
        return dict(self._unknown_feature_types)

    @property
    def total_discarded(self) -> int:
        return self._total_discarded

    def record_command(
        self,
        cmd_name: str,
        header: dict[str, Any],
        cmd: dict[str, Any],
        *,
        direction: str = "rx",
    ) -> None:
        self._last_unknown = cmd_name
        self._total_discarded += 1
        entry = {
            "ts": time.time(),
            "direction": direction,
            "cmd_name": cmd_name,
            "header": {
                "cmdClassifier": header.get("cmdClassifier"),
                "msgCounter": header.get("msgCounter"),
                "addressSource": header.get("addressSource"),
            },
            "payload": str(cmd)[:500],
        }
        self._unknown_commands.append(entry)
        if len(self._unknown_commands) > self._capacity:
            self._unknown_commands.pop(0)

    def record_feature_type(self, feature_type: str) -> None:
        self._unknown_feature_types[feature_type] = (
            self._unknown_feature_types.get(feature_type, 0) + 1
        )

    def clear(self) -> None:
        self._unknown_commands.clear()
        self._last_unknown = None
        self._unknown_feature_types.clear()
        self._total_discarded = 0
