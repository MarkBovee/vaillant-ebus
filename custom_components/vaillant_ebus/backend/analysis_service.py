"""Background analysis — detect new devices/entities from recently live data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .discovery_service import DiscoveryService
from .entity_factory import EntityDescription, EntityFactoryService
from .mapping import REGISTER_MAP
from .models import DeviceGraph, DeviceType

_LOGGER = logging.getLogger("vaillant_ebus.analysis")


@dataclass
class AnalysisResult:
    """Detected changes from one analysis pass (empty when nothing new)."""

    new_devices: list[str] = field(default_factory=list)
    new_entities: list[EntityDescription] = field(default_factory=list)
    registers_to_enable: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class AnalysisService:
    """Detect devices/entities from registers that became live since the last tick."""

    def __init__(self, entity_factory: EntityFactoryService | None = None) -> None:
        self._entity_factory = entity_factory or EntityFactoryService()

    def analyze(
        self,
        live_registers: dict[str, str],
        graph: DeviceGraph,
        entities: list[EntityDescription],
    ) -> AnalysisResult:
        """Diff the current graph/entities against registers that went live.

        live_registers maps register keys (circuit.name) to their raw live value.
        graph/entities are the current state; anything in live_registers absent
        from them is reported as newly discovered or as an enable candidate.
        """
        result = AnalysisResult()

        if not live_registers:
            return result

        result.registers_to_enable = [
            key for key in live_registers if key in REGISTER_MAP and not REGISTER_MAP[key].enabled
        ]

        find_lines = [f"{key.replace('.', ' ')} = {value}" for key, value in live_registers.items()]
        live_graph = DiscoveryService.build_device_graph(find_lines)
        if not live_graph.nodes:
            return result

        result.new_devices = [circuit for circuit in live_graph.nodes if circuit not in graph.nodes]

        existing_entity_keys = {entity.key for entity in entities}
        for entity in self._entity_factory.generate(live_graph):
            if entity.key not in existing_entity_keys:
                result.new_entities.append(entity)

        result.suggestions = [
            f"circuit {node.circuit} (scan={node.scan_type or '-'}) is UNKNOWN"
            for node in live_graph.nodes.values()
            if node.device_type == DeviceType.UNKNOWN
        ]

        if result.new_devices or result.new_entities or result.registers_to_enable or result.suggestions:
            _LOGGER.info(
                "Analysis found %d new device(s), %d new entity(ies), %d enable candidate(s)",
                len(result.new_devices),
                len(result.new_entities),
                len(result.registers_to_enable),
            )
        return result
