"""Coordinator for Vaillant eBUS — thin orchestration layer."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import repairs
from .backend.analysis_service import AnalysisResult, AnalysisService
from .backend.discovery_service import HIDDEN_DEVICE_KEYWORDS, DiscoveryService
from .backend.ebus_service import EbusService
from .backend.entity_factory import EntityDescription, EntityFactoryService
from .backend.mapping import REGISTER_MAP, split_multi_field
from .backend.models import (
    CIRCUIT_NAMES,
    COMPRESSOR_STATUS_LABELS,
    DeviceGraph,
    DeviceNode,
    DeviceType,
    EbusdRegister,
    zero_idle_registers,
)
from .backend.register_service import RegisterService
from .const import (
    CONF_EBUSD_HOST,
    CONF_EBUSD_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_EBUSD_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


EBUSD_STATUS_SUFFIXES: tuple[str, ...] = (
    ";ok",
    ";err",
    ";inv",
    ";too_small",
    ";too_big",
    ";nan",
    ";unknown",
)
DELAYED_REDISCOVERY_DELAY = timedelta(minutes=5)
ANALYSIS_INTERVAL = timedelta(minutes=15)


# Build the per-field value dict for a register (split multi-field values).
def _register_values(register_key: str, raw: str | None) -> dict[str, str | None]:
    return split_multi_field(register_key, raw)


# Merge a delayed graph without removing devices that initial discovery found.
def _merge_device_graphs(existing: DeviceGraph, discovered: DeviceGraph) -> DeviceGraph:
    nodes = dict(existing.nodes)
    for circuit, node in discovered.nodes.items():
        previous = nodes.get(circuit)
        if previous is None:
            nodes[circuit] = node
            continue
        nodes[circuit] = DeviceNode(
            circuit=circuit,
            device_type=(node.device_type if node.device_type != DeviceType.UNKNOWN else previous.device_type),
            registers=list(dict.fromkeys(previous.registers + node.registers)),
            parent=node.parent or previous.parent,
            zone_circuits=list(dict.fromkeys(previous.zone_circuits + node.zone_circuits)),
            heating_circuits=list(dict.fromkeys(previous.heating_circuits + node.heating_circuits)),
            has_data=previous.has_data or node.has_data,
            scan_type=node.scan_type or previous.scan_type,
            scan_sw=node.scan_sw or previous.scan_sw,
            scan_hw=node.scan_hw or previous.scan_hw,
        )

    raw_registers = dict(existing.raw_registers)
    raw_registers.update(discovered.raw_registers)
    placeholder_registers = (existing.placeholder_registers | discovered.placeholder_registers) - set(raw_registers)
    return DeviceGraph(
        nodes=nodes,
        raw_registers=raw_registers,
        placeholder_registers=placeholder_registers,
    )


# Append entity descriptions without duplicating keys already present.
def _merge_entities(
    existing: list[EntityDescription],
    additions: list[EntityDescription],
) -> list[EntityDescription]:
    known = {entity.key for entity in existing}
    merged = list(existing)
    for entity in additions:
        if entity.key not in known:
            merged.append(entity)
            known.add(entity.key)
    return merged


class VaillantCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._started = False
        self._ebusd_connected = False
        self._heating_circuit = "ctlv2"

        self.ebus: EbusService | None = None
        self.register: RegisterService | None = None
        self.discovery: DiscoveryService | None = None
        self.entity_factory = EntityFactoryService()
        self.registers: dict[str, EbusdRegister] = {}
        self.entities: list[EntityDescription] = []
        self._graph: DeviceGraph | None = None
        self._last_find_keys: set[str] = set()
        self._cancel_delayed_rediscovery: Callable[[], None] | None = None
        self._delayed_rediscovery_scheduled = False
        self._live_since_analysis: set[str] = set()
        self._cancel_analysis: Callable[[], None] | None = None
        self._analysis_scheduled = False
        self._analysis = AnalysisService()
        self.entity_adders: dict[str, Callable[[list[EntityDescription]], None]] = {}

        scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

        self._cache_seeded = False

    @property
    def ebusd_host(self) -> str:
        return self._entry.data.get(CONF_EBUSD_HOST, "")

    @property
    def ebusd_port(self) -> int:
        return self._entry.data.get(CONF_EBUSD_PORT, 8888)

    @property
    def heating_circuit(self) -> str:
        if self._graph:
            for node in self._graph.nodes.values():
                if node.device_type == DeviceType.HEATING_CONTROLLER:
                    return node.circuit
        return self._heating_circuit

    async def _async_seed_entities_from_cache(self) -> None:
        cache = await self._async_load_cache()
        find_lines: list[str] = []
        seen_keys: set[str] = set()

        for cache_key, cached_value in cache.items():
            if cached_value is None or not cached_value.strip():
                continue
            parts = cache_key.split(".")
            if len(parts) < 2:
                continue
            circuit, name = parts[0], parts[1]
            if any(kw in circuit.lower() for kw in HIDDEN_DEVICE_KEYWORDS):
                continue
            rk = f"{circuit}.{name}"
            normalized = rk.lower()
            if normalized in seen_keys:
                continue
            seen_keys.add(normalized)
            find_lines.append(f"{circuit} {name} = {cached_value}")
            self.registers[rk] = EbusdRegister(
                circuit=circuit,
                name=name,
                fields=["value"],
                value=_register_values(rk, cached_value),
                has_data=True,
            )

        # Reuse live discovery so cached ZN and HcN registers form logical devices.
        graph = DiscoveryService.build_device_graph(find_lines)
        if graph.nodes:
            self._graph = graph
        self.entities = self.entity_factory.generate(graph)
        _LOGGER.info(
            "Seeded %d entities from %d cache entries (%d circuits)", len(self.entities), len(cache), len(graph.nodes)
        )

    async def _ebusd_connect_and_discover(self) -> None:
        host = self.ebusd_host
        if not host:
            return
        ebus = EbusService(host=host, port=self.ebusd_port)
        try:
            await ebus.connect()
        except Exception as exc:
            _LOGGER.warning("ebusd connect failed, will retry: %s", exc)
            return
        self.ebus = ebus
        self.register = RegisterService(ebus)
        self.discovery = DiscoveryService(ebus)
        self._ebusd_connected = True

        version = ebus.version
        if version:
            _LOGGER.info("ebusd version: %s", version)

        await self._define_custom_registers()

        try:
            graph = await self.discovery.discover()
        except Exception as exc:
            _LOGGER.warning("ebusd discovery failed: %s", exc)
            return

        await self._apply_discovery_graph(graph, "initial")
        self._schedule_delayed_rediscovery()
        self._schedule_analysis()

    # Apply a complete device graph from initial or delayed discovery.
    async def _apply_discovery_graph(self, graph: DeviceGraph, source: str) -> None:
        is_delayed = source == "delayed" and self._graph is not None
        if is_delayed:
            graph = _merge_device_graphs(self._graph, graph)
        self._graph = graph

        for rk, raw in graph.raw_registers.items():
            if "." not in rk:
                continue
            circuit, name = rk.split(".", 1)
            if rk not in self.registers:
                self.registers[rk] = EbusdRegister(
                    circuit=circuit,
                    name=name,
                    fields=["value"],
                    value=_register_values(rk, raw),
                    has_data=True,
                )
            else:
                self.registers[rk].value.update(_register_values(rk, raw))
                self.registers[rk].has_data = True

        self._last_find_keys.update(graph.raw_registers)

        try:
            await self._fallback_read()
        except Exception as exc:
            _LOGGER.warning("%s fallback read failed: %s", source.capitalize(), exc)

        generated_entities = self.entity_factory.generate(graph)
        if is_delayed:
            existing_entity_keys = {entity.key for entity in self.entities}
            self.entities.extend(entity for entity in generated_entities if entity.key not in existing_entity_keys)
        else:
            self.entities = generated_entities
        _LOGGER.info(
            "Generated %d entity descriptions after %s ebusd discovery",
            len(self.entities),
            source,
        )
        self.async_update_listeners()

    # Schedule exactly one delayed pass for ebusd values unavailable at startup.
    def _schedule_delayed_rediscovery(self) -> None:
        if self._delayed_rediscovery_scheduled:
            return
        self._delayed_rediscovery_scheduled = True
        self._cancel_delayed_rediscovery = async_call_later(
            self.hass,
            DELAYED_REDISCOVERY_DELAY,
            self._async_delayed_rediscover,
        )

    # Refresh the full graph once after the initial ebusd startup window.
    async def _async_delayed_rediscover(self, _: datetime) -> None:
        self._cancel_delayed_rediscovery = None
        if not self.ebus or not self.ebus.is_connected or not self.discovery:
            return
        try:
            graph = await self.discovery.discover()
        except Exception as exc:
            _LOGGER.warning("Delayed ebusd discovery failed: %s", exc)
            return
        await self._apply_discovery_graph(graph, "delayed")

    # Schedule the recurring background analysis for recently live registers.
    def _schedule_analysis(self) -> None:
        if self._analysis_scheduled:
            return
        self._analysis_scheduled = True
        self._cancel_analysis = async_call_later(
            self.hass,
            ANALYSIS_INTERVAL,
            self._async_run_analysis,
        )

    # Reschedule the analysis loop and hand the live-register set to the service.
    async def _async_run_analysis(self, _: datetime) -> None:
        self._cancel_analysis = None
        self._analysis_scheduled = False
        if self.ebus and self.ebus.is_connected:
            await self._analyze_live_registers()
        self._schedule_analysis()

    # Analyze registers that went live since the last tick, discover + enable.
    async def _analyze_live_registers(self) -> None:
        live: dict[str, str] = {}
        for key in list(self._live_since_analysis):
            register = self.registers.get(key)
            raw = register.value.get("value") if register else None
            if raw is not None:
                live[key] = raw
        self._live_since_analysis.clear()
        if not live or self._graph is None:
            return

        result: AnalysisResult = self._analysis.analyze(live, self._graph, self.entities)
        if result.new_entities:
            self.entities = _merge_entities(self.entities, result.new_entities)
            self._add_new_entities(result.new_entities)
        if result.registers_to_enable:
            await self._enable_registry_entities(result.registers_to_enable)
        for suggestion in result.suggestions:
            _LOGGER.info("Analysis suggestion: %s", suggestion)

    # Register a platform callback to add newly discovered entities at runtime.
    def register_entity_adder(
        self, entity_type: str, callback: Callable[[list[EntityDescription]], None]
    ) -> None:
        self.entity_adders[entity_type] = callback

    # Run a background analysis pass on-demand (used by the analyze service).
    async def async_run_analysis(self) -> None:
        if not self.ebus or not self.ebus.is_connected:
            return
        await self._analyze_live_registers()

    # Push newly discovered entity descriptions to the matching platform adder.
    def _add_new_entities(self, new_entities: list[EntityDescription]) -> None:
        by_type: dict[str, list[EntityDescription]] = {}
        for entity in new_entities:
            by_type.setdefault(entity.entity_type, []).append(entity)
        for entity_type, descriptions in by_type.items():
            adder = self.entity_adders.get(entity_type)
            if adder is None:
                _LOGGER.debug("No adder for entity type %s", entity_type)
                continue
            try:
                adder(descriptions)
            except Exception as exc:
                _LOGGER.warning("Entity adder failed for %s: %s", entity_type, exc)

    # Enable entities that map to recently live registers (respect user choice).
    async def _enable_registry_entities(self, register_keys: list[str]) -> list[str]:
        entity_registry = self.hass.helpers.entity_registry.async_get(self.hass)
        desired_uids = {
            f"ebusd_{key.split('.')[0]}_{key.split('.', 1)[1].lower().replace(' ', '_')}"
            for key in register_keys
        }
        enabled: list[str] = []
        for entity_id, entry in entity_registry.entities.items():
            if entry.config_entry_id != self._entry.entry_id:
                continue
            if entry.unique_id not in desired_uids:
                continue
            if entry.disabled_by != "integration":
                continue
            entity_registry.async_update_entity(entity_id, disabled_by=None)
            enabled.append(entity_id)
        if enabled:
            _LOGGER.info("Auto-enabled entities with live data: %s", ", ".join(enabled))
        return enabled

    async def _define_custom_registers(self) -> None:
        if not self.ebus or not self.ebus.is_connected:
            return
        defines = [
            "r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800"
            ",value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity",
        ]
        for definition in defines:
            try:
                resp = await self.ebus.define_register(definition)
                _LOGGER.debug("Define %s: %s", definition.split(",")[2], resp)
            except Exception as exc:
                _LOGGER.warning("Failed to define register: %s", exc)

    async def _async_values_from_registers(self, registers: list[EbusdRegister] | None = None) -> dict[str, str]:
        values: dict[str, str] = {}
        for reg in registers or list(self.registers.values()):
            for field, value in reg.value.items():
                if value is not None:
                    translated = value
                    if reg.key == "hmu.RunDataStatuscode":
                        translated = COMPRESSOR_STATUS_LABELS.get(value, value)
                    for suffix in EBUSD_STATUS_SUFFIXES:
                        if translated.endswith(suffix):
                            translated = translated[: -len(suffix)]
                            break
                    values[f"{reg.circuit}.{reg.name}.{field}"] = translated
        await self._async_save_cache(values)
        return values

    @property
    def _cache_path(self) -> str:
        return self.hass.config.path(DOMAIN, "register_cache.json")

    async def _async_save_cache(self, values: dict[str, str]) -> None:
        cache_dir = os.path.dirname(self._cache_path)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            def _write():
                with open(self._cache_path, "w") as f:
                    json.dump(values, f)
            await self.hass.async_add_executor_job(_write)
        except Exception:
            pass

    async def _async_load_cache(self) -> dict[str, str]:
        try:
            def _read():
                with open(self._cache_path) as f:
                    return json.load(f)
            return await self.hass.async_add_executor_job(_read)
        except Exception:
            return {}

    def get_device_info(self, circuit: str) -> DeviceInfo:
        scan_type = ""
        scan_sw = ""
        scan_hw = ""
        parent: str | None = None
        node: DeviceNode | None = None

        if self._graph:
            node = self._graph.nodes.get(circuit)

        if node:
            scan_type = node.scan_type
            scan_sw = node.scan_sw
            scan_hw = node.scan_hw
            parent = node.parent

        circuit_lower = circuit.lower()
        if circuit_lower in CIRCUIT_NAMES:
            name = CIRCUIT_NAMES[circuit_lower]
        elif len(circuit_lower) == 5 and circuit_lower.startswith("ctlv") and circuit_lower[-1].isdigit():
            name = "Vaillant sensoCOMFORT Control"
        elif scan_type:
            name = f"Vaillant {scan_type}"
        elif circuit_lower.startswith("z"):
            name = f"Zone {circuit[1:]}"
        elif circuit_lower.startswith("hc"):
            name = f"Heating Circuit {circuit[2:]}"
        else:
            name = f"Vaillant {circuit}"

        via_device: tuple[str, str] | None = None
        if parent:
            via_device = (DOMAIN, parent)

        ebusd_version = self.ebus.version if self.ebus else None
        return DeviceInfo(
            identifiers={(DOMAIN, circuit)},
            name=name,
            manufacturer="Vaillant",
            model=name,
            sw_version=scan_sw or ebusd_version,
            hw_version=scan_hw,
            via_device=via_device,
        )

    async def _fallback_read(self) -> None:
        if not self.ebus or not self.ebus.is_connected:
            return
        graph_keys = self._last_find_keys
        to_read = [k for k in REGISTER_MAP if REGISTER_MAP[k].enabled and k not in graph_keys]
        if not to_read:
            return
        _LOGGER.debug("Fallback reading %d known register(s)", len(to_read))
        added = 0
        for key in to_read:
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            circuit, name = parts
            try:
                value = await self.ebus.read_register(circuit, name)
                was_new = key not in self.registers
                if value and (value.startswith(("or:", "ERR:", "no data stored")) or "read [-" in value):
                    value = None
                if value is None:
                    cache = await self._async_load_cache()
                    cached = cache.get(f"{circuit}.{name}.value")
                    if cached is not None:
                        value = cached
                if value is not None:
                    if was_new:
                        self.registers[key] = EbusdRegister(
                            circuit=circuit,
                            name=name,
                            fields=["value"],
                            value=_register_values(key, value),
                            has_data=True,
                        )
                        added += 1
                    else:
                        self.registers[key].value.update(_register_values(key, value))
                        self.registers[key].has_data = True
                    _LOGGER.debug("Fallback read %s = %s", key, value)
                elif was_new and REGISTER_MAP[key].enabled:
                    self.registers[key] = EbusdRegister(
                        circuit=circuit,
                        name=name,
                        fields=["value"],
                        value=_register_values(key, None),
                        has_data=False,
                    )
                    added += 1
                    _LOGGER.debug("Fallback added empty %s (will populate on poll)", key)
            except Exception as exc:
                _LOGGER.warning("Fallback read failed: %s (%s)", key, exc)
        if added and self._graph:
            self.entities = self.entity_factory.generate(self._graph)
            _LOGGER.info("Regenerated entities after fallback: added %d new", added)

    async def _async_update_data(self) -> dict[str, Any]:
        if not self._cache_seeded:
            self._cache_seeded = True
            await self._async_seed_entities_from_cache()

        if not self._ebusd_connected:
            if not self._started:
                self._started = True
                self.hass.async_create_task(self._ebusd_connect_and_discover())
            return {"ebusd": await self._async_values_from_registers()}

        if self.ebus and self.ebus.is_connected:
            try:
                lines = await self.ebus.find_registers()
                updated = 0
                for line in lines:
                    line = line.strip()
                    if not line or "=" not in line:
                        continue
                    lhs, rhs = line.split("=", 1)
                    parts = lhs.strip().split(" ", 1)
                    circuit = parts[0]
                    name = parts[1].strip() if len(parts) > 1 else ""
                    if not circuit or not name:
                        continue
                    val = rhs.strip()
                    key = f"{circuit}.{name}"
                    if val in ("-", "") or val.startswith(("(empty ", "(ERR", "no data stored")):
                        continue
                    self._live_since_analysis.add(key)
                    if key not in self.registers:
                        self.registers[key] = EbusdRegister(
                            circuit=circuit,
                            name=name,
                            fields=["value"],
                            value=_register_values(key, val),
                            has_data=True,
                        )
                        updated += 1
                    else:
                        self.registers[key].value.update(_register_values(key, val))
                        self.registers[key].has_data = True
                        updated += 1
                self._last_find_keys = {k for k in self.registers}
                await self._fallback_read()
                zero_idle_registers(self.registers)
                if updated:
                    _LOGGER.debug("Poll updated %d registers", updated)
                return {"ebusd": await self._async_values_from_registers()}
            except ConnectionError, TimeoutError, OSError:
                _LOGGER.warning("ebusd connection lost, reconnecting")
                try:
                    if self.ebus:
                        await self.ebus._reconnect()
                    await repairs.async_dismiss_ebusd_unreachable(self.hass)
                except Exception as exc:
                    _LOGGER.error("ebusd reconnect failed: %s", exc)
                    await repairs.async_create_ebusd_unreachable(self.hass)

        return {"ebusd": await self._async_values_from_registers()}

    async def async_stop(self) -> None:
        if self._cancel_delayed_rediscovery:
            self._cancel_delayed_rediscovery()
            self._cancel_delayed_rediscovery = None
        if self._cancel_analysis:
            self._cancel_analysis()
            self._cancel_analysis = None
        if self.ebus:
            await self.ebus.disconnect()
        self.ebus = None
