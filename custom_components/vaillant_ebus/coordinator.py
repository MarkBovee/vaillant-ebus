"""Coordinator for Vaillant eBUS — thin orchestration layer."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import repairs
from .backend.analysis_service import AnalysisResult, AnalysisService
from .backend.discovery_service import HIDDEN_DEVICE_KEYWORDS, DiscoveryService
from .backend.ebus_service import EBUSD_STATUS_SUFFIXES, EbusService
from .backend.entity_factory import EntityDescription, EntityFactoryService
from .backend.mapping import REGISTER_MAP, b516_date_bytes, is_field_key, multi_field_fields, split_multi_field
from .backend.models import (
    CIRCUIT_NAMES,
    COMPRESSOR_STATUS_LABELS,
    DeviceGraph,
    DeviceNode,
    DeviceType,
    EbusdRegister,
    ResolutionStatus,
    is_no_data_value,
    is_valid_hmux0_return_temperature,
    zero_idle_registers,
)
from .const import (
    CONF_EBUSD_HOST,
    CONF_EBUSD_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_EBUSD_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _registry_matches_description(registry_unique_id: str, description_unique_id: str) -> bool:
    """Match HA's config-entry-prefixed ID to integration entity ID."""
    return registry_unique_id == description_unique_id or registry_unique_id.endswith(f"_{description_unique_id}")


DELAYED_REDISCOVERY_DELAY = timedelta(minutes=5)
ANALYSIS_INTERVAL = timedelta(minutes=15)
PLACEHOLDER_POLL_INTERVAL = timedelta(minutes=15)
ENERGY_POLL_INTERVAL = timedelta(minutes=5)

HMUX0_RUNTIME_REGISTERS = frozenset(
    {
        "RunDataReturnTemp",
        "YieldHc",
        "YieldHcDay",
        "YieldHcMonth",
        "YieldHwc",
        "YieldHwcDay",
        "YieldHwcMonth",
        "CopHc",
        "CopHcMonth",
        "CopHwc",
        "CopHwcMonth",
    }
)

# Registers whose live (non-sentinel) value marks a discovered zone as
# genuinely present. DayTemp/OpMode are excluded: ebusd reports static
# defaults for these even on unused zones, so they cannot distinguish a real
# zone from a ghost.
ZONE_LIVE_REGISTERS: tuple[str, ...] = ("RoomTemp", "ActualRoomTempDesired")


# Build the per-field value dict for a register (split multi-field values).
def _register_values(register_key: str, raw: str | None) -> dict[str, str | None]:
    return split_multi_field(register_key, raw)


class CoordinatorState(TypedDict):
    ebusd: dict[str, str]


def _usable_register_value(register_key: str, raw: str | None) -> str | None:
    """Reject ebusd sentinels and known invalid temperature decodes."""
    if raw is None or is_no_data_value(raw):
        return None
    if register_key.lower() == "hmu.sourcetempinput":
        try:
            if float(raw) < -100:
                return None
        except ValueError:
            return None
    if register_key.lower() == "hmux0.rundatareturntemp" and not is_valid_hmux0_return_temperature(raw):
        return None
    return raw


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
    known = {(entity.entity_type, entity.unique_id): entity for entity in existing}
    merged = list(existing)
    for entity in additions:
        identity = (entity.entity_type, entity.unique_id)
        if identity not in known:
            merged.append(entity)
            known[identity] = entity
        else:
            # Cache spelling may differ from find; loaded entities keep this
            # description object, so update its lookup key without re-adding it.
            known[identity].name = entity.name
    return merged


class VaillantCoordinator(DataUpdateCoordinator[CoordinatorState]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._started = False
        self._ebusd_connected = False
        self._heating_circuit = "ctlv2"
        # Desired DHW boost state (True when boost was requested). HwcSFMode
        # reports "load" while the cylinder charges even after boost is turned
        # off, so the switch/water-heater report this desired value instead of
        # the raw register. None until the user toggles boost.
        self.dhw_boost_desired: bool | None = None

        self.ebus: EbusService | None = None
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
        self._last_placeholder_poll = datetime.min
        self._last_energy_poll = datetime.min
        self._runtime_definitions: dict[str, str] = {}
        self._cancel_set_mode_override: Callable[[], None] | None = None
        self._set_mode_override_payload: str | None = None
        self._analysis = AnalysisService()
        self.entity_adders: dict[str, Callable[[list[EntityDescription]], None]] = {}
        self._post_discovery_callbacks: list[Callable[[], None]] = []

        options = entry.options if isinstance(entry.options, dict) else {}
        scan_interval = options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL),
        )
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
    def heating_circuit(self) -> str | None:
        if self._graph is None:
            return self._heating_circuit
        return self.resolve_register_circuit("ctlv2")

    @property
    def heat_pump_circuit(self) -> str | None:
        if self._graph is None:
            return "hmu"
        return self.resolve_register_circuit("hmu")

    def resolve_register_circuit(self, circuit: str) -> str | None:
        """Resolve legacy map circuits to circuits discovered on this bus."""
        if self._graph is not None:
            resolution = self._graph.resolve_circuit_result(circuit)
            if resolution.status != ResolutionStatus.UNIQUE:
                return None
            return resolution.circuit or circuit
        return circuit

    async def async_read_register(self, circuit: str, name: str, field: str = "") -> str | None:
        """Read a register only after resolving its discovered circuit owner."""
        if not self.ebus or not self.ebus.is_connected:
            return None
        resolved_circuit = self.resolve_register_circuit(circuit)
        if resolved_circuit is None:
            _LOGGER.warning("Read skipped: unresolved discovered circuit for %s.%s", circuit, name)
            return None
        return await self.ebus.read_register(resolved_circuit, name, field)

    # Active heating zones (zone id -> hosting circuit) derived from the
    # discovery graph. A zone counts as active when it has a room-zone mapping
    # (ZNRoomZoneMapping with a value other than none/empty) or live data on a
    # core register (ZNRoomTemp / ZNDayTemp / ZNOpMode / ZNActualRoomTempDesired).
    # Ghost zones - every ZN register present but unused (mapping none and no
    # live data) - are skipped so they never produce a permanently-unavailable
    # climate entity. Deliberately NOT filtered on the zone node's has_data:
    # ebusd reports ghost mapping values like "none" as real register values.
    def zone_circuits(self) -> dict[str, str]:
        owners: dict[str, set[str]] = {}
        if self._graph is None:
            return {}
        for node in self._graph.nodes.values():
            for zone in node.zone_circuits:
                if self._zone_is_valid(node.circuit, zone):
                    owners.setdefault(zone, set()).add(node.circuit)
        return {zone: next(iter(circuits)) for zone, circuits in owners.items() if len(circuits) == 1}

    # Whether a raw zone-register value proves real data: anything the shared
    # no-data helper rejects, except "none" which is a legitimate RoomZoneMapping
    # value for unused zones and must not count as live data.
    @staticmethod
    def _zone_value_has_data(raw: str | None) -> bool:
        return raw is not None and not is_no_data_value(raw) and raw.strip().lower() != "none"

    # Whether a discovered zone is a real heating zone rather than a ghost.
    def _zone_is_valid(self, circuit: str, zone: str) -> bool:
        if self._graph is None:
            return False
        zn = zone.upper()
        mapping = self._graph.raw_registers.get(f"{circuit}.{zn}RoomZoneMapping")
        if self._zone_value_has_data(mapping):
            return True
        # Fall back to a measured value on a live register. Static defaults
        # (DayTemp/OpMode) and sentinel values (empty/unknown/no data stored)
        # do not prove the zone is real.
        for name in ZONE_LIVE_REGISTERS:
            if self._zone_value_has_data(self._graph.raw_registers.get(f"{circuit}.{zn}{name}")):
                return True
        return False

    # Whether `circuit.<ZN><name>` was discovered on the bus. Both live values
    # and no-data placeholders count as present: ebusd returns `no data stored`
    # for registers the hardware supports while they are idle. Until a real
    # discovery has populated the find set, absence is not proof of hardware
    # absence (cache-seeded graphs only carry live values), so the register is
    # assumed present to preserve the pre-per-zone behavior.
    def has_zone_register(self, circuit: str, zone: str, name: str) -> bool:
        if self._graph is None or not self._last_find_keys:
            return True
        key = f"{circuit}.{zone.upper()}{name}"
        if key in self._graph.raw_registers or key in self._graph.placeholder_registers:
            return True
        lower = key.lower()
        return any(rk.lower() == lower for rk in self._graph.raw_registers) or any(
            rk.lower() == lower for rk in self._graph.placeholder_registers
        )

    async def _async_seed_entities_from_cache(self) -> None:
        cache = await self._async_load_cache()
        find_lines: list[str] = []
        seen_keys: set[str] = set()

        for cache_key, cached_value in cache.items():
            if cached_value is None or not cached_value.strip() or is_no_data_value(cached_value):
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
            self._started = False
            _LOGGER.warning("ebusd connect failed, will retry: %s", exc)
            return
        self.ebus = ebus
        self.discovery = DiscoveryService(ebus)
        self._ebusd_connected = True
        self._runtime_definitions.clear()
        self._last_energy_poll = datetime.min

        version = ebus.version
        if version:
            _LOGGER.info("ebusd version: %s", version)

        try:
            graph = await self.discovery.discover()
        except Exception as exc:
            self._ebusd_connected = False
            self._started = False
            await ebus.disconnect()
            _LOGGER.warning("ebusd discovery failed: %s", exc)
            return

        # Scan-only nodes preserve identity when ebusd has no matching CSV. Runtime
        # definitions are therefore always resolved from discovered ownership.
        self._graph = graph
        await self._define_custom_registers()
        # Refresh once so every newly defined register enters the initial graph.
        # This also avoids polling generic HMU definitions before scan discovery
        # can identify an HMUX0 device.
        if self._runtime_definitions:
            graph = await self.discovery.discover()
        await self._apply_discovery_graph(graph, "initial")
        await repairs.async_dismiss_detection_incomplete(self.hass)
        self._schedule_delayed_rediscovery()
        self._schedule_analysis()

    # Apply a complete device graph from initial or delayed discovery.
    async def _apply_discovery_graph(self, graph: DeviceGraph, source: str) -> None:
        # Delayed rediscovery merges into the known graph so existing entities
        # survive; only registers that are still missing get added afterwards.
        previous = self._graph if source == "delayed" else None
        if previous is not None:
            graph = _merge_device_graphs(previous, graph)
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
        existing_entity_keys = {(entity.entity_type, entity.unique_id) for entity in self.entities}
        additions = [
            entity
            for entity in generated_entities
            if (entity.entity_type, entity.unique_id) not in existing_entity_keys
        ]
        # Platforms can already be loaded from cache, even on "initial" discovery.
        # Retain known keys across reconnects to avoid adding the same entity twice.
        self.entities = _merge_entities(self.entities, generated_entities)
        self._disable_no_data_registry_entities(generated_entities)
        self._add_new_entities(additions)
        platform_counts: dict[str, int] = {}
        for entity in self.entities:
            ptype = str(entity.entity_type or "sensor")
            platform_counts[ptype] = platform_counts.get(ptype, 0) + 1
        _LOGGER.info(
            "Generated %d entity descriptions after %s ebusd discovery: %s (%d new entities)",
            len(self.entities),
            source,
            ", ".join(f"{count} {ptype}" for ptype, count in sorted(platform_counts.items())),
            len(additions),
        )
        self.async_update_listeners()
        for callback in self._post_discovery_callbacks:
            try:
                callback()
            except Exception:
                _LOGGER.warning("Post-discovery callback failed", exc_info=True)

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
    def register_entity_adder(self, entity_type: str, callback: Callable[[list[EntityDescription]], None]) -> None:
        self.entity_adders[entity_type] = callback

    # Register a callback invoked after every applied discovery graph, so
    # hand-built platforms (climate) can add entities once the graph exists.
    def register_post_discovery_callback(self, callback: Callable[[], None]) -> None:
        self._post_discovery_callbacks.append(callback)

    # Run a background analysis pass on-demand (used by the analyze service).
    async def async_run_analysis(self) -> None:
        if not self.ebus or not self.ebus.is_connected:
            return
        await self._analyze_live_registers()

    # Full rediscovery requested by the "rediscover" service: drop the ebusd
    # connection so the next poll reconnects and discovers from scratch.
    async def async_request_rediscover(self) -> None:
        _LOGGER.info("Manual ebusd rediscovery requested; reconnecting and rebuilding the discovery graph")
        if self.ebus:
            await self.ebus.disconnect()
        self.ebus = None
        self._ebusd_connected = False
        self._started = False
        await self.async_request_refresh()

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

    # Disable existing no-data entities after rediscovery; analysis re-enables
    # them when the register later returns a real value.
    def _disable_no_data_registry_entities(self, descriptions: list[EntityDescription]) -> None:
        registry = entity_registry.async_get(self.hass)
        disabled = 0
        for description in descriptions:
            if description.enabled_by_default or description.raw_value:
                continue
            for entity_id, entry in registry.entities.items():
                if entry.config_entry_id != self._entry.entry_id or not _registry_matches_description(
                    entry.unique_id, description.unique_id
                ):
                    continue
                if entry.disabled_by is None:
                    registry.async_update_entity(entity_id, disabled_by=RegistryEntryDisabler.INTEGRATION)
                    disabled += 1
        if disabled:
            _LOGGER.info("Disabled %d no-data entities after discovery", disabled)

    def disable_no_data_entities(self) -> None:
        """Disable restored entities whose current descriptions have no data."""
        self._disable_no_data_registry_entities(self.entities)
        registry = entity_registry.async_get(self.hass)
        for entity_id, entry in registry.entities.items():
            if (
                entry.config_entry_id == self._entry.entry_id
                and entry.platform == DOMAIN
                and entry.unique_id.lower().endswith("_ebusd_hmu_tmpb516montheven")
                and entry.disabled_by is None
            ):
                registry.async_update_entity(entity_id, disabled_by=RegistryEntryDisabler.INTEGRATION)

    # Enable entities that map to recently live registers (respect user choice).
    async def _enable_registry_entities(self, register_keys: list[str]) -> list[str]:
        registry = entity_registry.async_get(self.hass)
        desired_uids: set[str] = set()
        for key in register_keys:
            circuit, name = key.split(".", 1)
            suffix = name.lower().replace(" ", "_")
            desired_uids.add(f"ebusd_{circuit}_{suffix}")
            # Multi-field registers also expose per-field entities whose
            # unique ids carry a _{field} suffix; include those candidates so
            # they are auto-enabled as well.
            for field in multi_field_fields(key) or []:
                desired_uids.add(f"ebusd_{circuit}_{suffix}_{field}")
        enabled: list[str] = []
        for entity_id, entry in registry.entities.items():
            if entry.config_entry_id != self._entry.entry_id:
                continue
            if not any(_registry_matches_description(entry.unique_id, uid) for uid in desired_uids):
                continue
            if entry.disabled_by != "integration":
                continue
            registry.async_update_entity(entity_id, disabled_by=None)
            enabled.append(entity_id)
        if enabled:
            _LOGGER.info("Auto-enabled entities with live data: %s", ", ".join(enabled))
        return enabled

    async def _define_custom_registers(self) -> None:
        if not self.ebus or not self.ebus.is_connected:
            return
        # Definitions may target hardware not present on this bus. ebusd
        # reports those as unavailable; fallback/entity filtering handles that.
        # Keep only definitions verified by upstream or community evidence here.
        #
        # The b516 cooling-energy registers (Z=5 usage code, upstream issue
        # #490) are absent from the shipped HW5103 CSV (upstream issue #600).
        # They report environmental yield / electric consumption for cooling
        # regardless of compressor operation, so they also cover passive
        # brine cooling. Verified live against ebusd; values are Wh. Day and
        # Month variants carry a date payload that must also roll over while
        # connected. Only changed or previously failed definitions are sent.
        date_bytes = b516_date_bytes(datetime.now())
        defines = [
            "r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800"
            ",value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity",
            # eloBLOCK B510 thermostat override. It is harmless on hardware
            # without BAI; ebusd reports it unavailable and filters it out.
            "wi,bai,SetModeOverride,Operation Mode,,08,B510,00"
            ",hcmode,,UCH,,,,flowtempdesired,,D1C,,,,hwctempdesired,,D1C"
            ",,,,hwcflowtempdesired,,UCH,,,,setmode1,,UCH,,,,disablehc,,BI0"
            ",,,,disablehwctapping,,BI1,,,,disablehwcload,,BI2,,,,setmode2,,UCH"
            ",,,,remoteControlHcPump,,BI0,,,,releaseBackup,,BI1,,,,releaseCooling,,BI2",
            # B524 heating-circuit state registers (OP=0x02 GG=0x02, RR=0x20..0x25)
            # absent from the shipped CSVs (verified against the installed find
            # output and upstream 15.ctlv2.tsp). Layout documented in the
            # Helianthus B524 register map (community capture via discussion
            # #60); wire types EXP (f32) and ULG (u32 LE) confirmed against
            # ebusd datatype.cpp and the compiled eBUS CSVs. All are read-only
            # state (S) with no gates; absent hardware reports no data and
            # stays filtered by the existing no-data handling.
            "r5,ctlv2,Hc1FlowTempCalc,Hc1FlowTempCalc,31,15,B524"
            ",020002002000,value,,IGN:4,,,,value,,EXP,,°C,Hc1 Calculated Flow Temp",
            "r5,ctlv2,Hc1MixerPosition,Hc1MixerPosition,31,15,B524"
            ",020002002100,value,,IGN:4,,,,value,,EXP,,%,Hc1 Mixer Position",
            "r5,ctlv2,Hc1Humidity,Hc1Humidity,31,15,B524,020002002200,value,,IGN:4,,,,value,,EXP,,%,Hc1 Humidity",
            "r5,ctlv2,Hc1DewPointTemp,Hc1DewPointTemp,31,15,B524"
            ",020002002300,value,,IGN:4,,,,value,,EXP,,°C,Hc1 Dew Point Temp",
            "r5,ctlv2,Hc1PumpHours,Hc1PumpHours,31,15,B524,020002002400,value,,IGN:4,,,,value,,ULG,,h,Hc1 Pump Hours",
            "r5,ctlv2,Hc1PumpStarts,Hc1PumpStarts,31,15,B524,020002002500,value,,IGN:4,,,,value,,ULG,,,Hc1 Pump Starts",
            "r5,ctlv2,Hc2FlowTempCalc,Hc2FlowTempCalc,31,15,B524"
            ",020002012000,value,,IGN:4,,,,value,,EXP,,°C,Hc2 Calculated Flow Temp",
            "r5,ctlv2,Hc2MixerPosition,Hc2MixerPosition,31,15,B524"
            ",020002012100,value,,IGN:4,,,,value,,EXP,,%,Hc2 Mixer Position",
            "r5,ctlv2,Hc2Humidity,Hc2Humidity,31,15,B524,020002012200,value,,IGN:4,,,,value,,EXP,,%,Hc2 Humidity",
            "r5,ctlv2,Hc2DewPointTemp,Hc2DewPointTemp,31,15,B524"
            ",020002012300,value,,IGN:4,,,,value,,EXP,,°C,Hc2 Dew Point Temp",
            "r5,ctlv2,Hc2PumpHours,Hc2PumpHours,31,15,B524,020002012400,value,,IGN:4,,,,value,,ULG,,h,Hc2 Pump Hours",
            "r5,ctlv2,Hc2PumpStarts,Hc2PumpStarts,31,15,B524,020002012500,value,,IGN:4,,,,value,,ULG,,,Hc2 Pump Starts",
            # SourceTempInput is absent from the shipped CSVs (upstream issue
            # #632, last compiled 2026-04-19). Layout verified live on brine
            # units in john30/ebusd-configuration PR #565 (flexoTHERM and
            # flexoCOMPACT ground-source); air/water units answer with a
            # 3-byte stub and stay unavailable, which the ERR filtering keeps
            # out of entity values.
            "r,hmu,SourceTempInput,SourceTempInput,31,8,B51A,05ff3222,value,,IGN:3,,,,value,,D2C,,°C,Source temp input",
            # HMUX0 HW0504 community capture: upstream issue #249 / PR #330
            # identifies B511/00 as the multi-field compressor status block.
            # Unsupported variants return an empty response and remain filtered.
            "r,hmu,Status00,Status00,31,8,B511,00"
            ",supplytemp,,D2C,,°C,,waterpressure,,UCH,10,bar,,"
            "compressormodulation,,UCH,,%,,compressorstate,,UCH,"
            "0=off;1=heating_prerun;4=heating;5=heating_overrun;24=hot_water;"
            "110=defrosting,,heatingstate,,UCH,8=off;9=heating,,"
            "field6,,UCH,,,defrost,,UCH,0=inactive;32=active,,"
            "compressorpower,,percent1,,%,,HMUX0 Status00",
            # HMUX0 HW0504 community capture: upstream issue #522 identifies
            # B509/540200/5b0d as diagnostic electrical power in watts.
            # This is additive; absent hardware returns no data.
            "r,hmu,RunDataElPowerConsumption,RunDataElPowerConsumption,31,8,B509"
            ",055402005b0d,value,,IGN:4,,,,value,,EXP,,W,"
            "HMUX0 electrical power consumption",
            "r5,ctlv2,ManualCoolingStartDate,ManualCoolingStartDate,31,15,B524"
            ",02000000da00,value,,IGN:4,,,,value,,HDA:3",
            "r5,ctlv2,ManualCoolingEndDate,ManualCoolingEndDate,31,15,B524,02000000db00,value,,IGN:4,,,,value,,HDA:3",
            "w,ctlv2,ManualCoolingStartDate,ManualCoolingStartDate,31,15,B524,02010000da00,value,m,HDA:3",
            "w,ctlv2,ManualCoolingEndDate,ManualCoolingEndDate,31,15,B524,02010000db00,value,m,HDA:3",
            "r,hmu,CoolEnvYieldTotal,CoolEnvYieldTotal,31,08,B516"
            ",1000ffff02050000,value,,IGN:7,,,,value,,EXP,,Wh"
            ",hmu Cooling Env Yield Total",
            "r,hmu,CoolElecConsTotal,CoolElecConsTotal,31,08,B516"
            ",1000ffff03050000,value,,IGN:7,,,,value,,EXP,,Wh"
            ",hmu Cooling Electric Consumption",
            f"r,hmu,CoolEnvYieldDay,CoolEnvYieldDay,31,08,B516"
            f",1001ffff0205{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
            f",hmu Cooling Env Yield Today",
            f"r,hmu,CoolEnvYieldMonth,CoolEnvYieldMonth,31,08,B516"
            f",1002ffff0205{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
            f",hmu Cooling Env Yield This Month",
            # Daily electric consumption for cooling (issue #50 follow-up: the
            # integration only exposed the lifetime electric total, while the
            # myPyllant app shows a daily "Consumed Electrical Energy Cooling"
            # value). Same b516 API with the electric usage code (Y=3) and the
            # daily X=1 selector, so the layout matches the verified cooling
            # family; date payload rolls over like CoolEnvYieldDay.
            f"r,hmu,CoolElecConsDay,CoolElecConsDay,31,08,B516"
            f",1001ffff0305{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
            f",hmu Cooling Electric Consumption Today",
            # Lifetime and daily electric consumption for the heating (Z=3) and
            # hot-water (Z=4) domains, same b516 statistics API (upstream issue
            # #490). Conservative extension of the live-verified cooling layout
            # (Y=3 electric); absent hardware reports no data and stays hidden.
            "r,hmu,HcElecConsTotal,HcElecConsTotal,31,08,B516"
            ",1000ffff03030000,value,,IGN:7,,,,value,,EXP,,Wh"
            ",hmu Heating Electric Consumption",
            f"r,hmu,HcElecConsDay,HcElecConsDay,31,08,B516"
            f",1001ffff0303{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
            f",hmu Heating Electric Consumption Today",
            "r,hmu,HwcElecConsTotal,HwcElecConsTotal,31,08,B516"
            ",1000ffff03040000,value,,IGN:7,,,,value,,EXP,,Wh"
            ",hmu DHW Electric Consumption",
            f"r,hmu,HwcElecConsDay,HwcElecConsDay,31,08,B516"
            f",1001ffff0304{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
            f",hmu DHW Electric Consumption Today",
        ]

        heat_pump = self._graph.heat_pump_result().node if self._graph is not None else None
        is_hmux0_0303_0504 = bool(
            heat_pump
            and heat_pump.scan_type.upper() == "HMUX0"
            and heat_pump.scan_sw == "0303"
            and heat_pump.scan_hw == "0504"
        )
        # Generic HMU layouts are not valid for this HMUX0 variant. Define only
        # the independently evidenced HMUX0 register set below.
        if heat_pump and heat_pump.scan_type.upper() == "HMUX0":
            defines = [definition for definition in defines if definition.split(",", 3)[1] != "hmu"]

        # Resolve logical definition circuits only after discovery identifies their owners.
        # Drop definitions whose logical owner is ambiguous instead of guessing.
        def _resolve_definition_circuit(definition: str) -> str | None:
            parts = definition.split(",", 3)
            if len(parts) < 3 or not self._graph:
                return definition
            resolution = (
                self._graph.heating_controller_result()
                if parts[1] == "ctlv2"
                else self._graph.heat_pump_result()
                if parts[1] == "hmu"
                else self._graph.resolve_circuit_result(parts[1])
            )
            if resolution.status != ResolutionStatus.UNIQUE:
                return None
            resolved = resolution.circuit or parts[1]
            if resolved == parts[1]:
                return definition
            parts[1] = resolved
            return ",".join(parts)

        defines = [definition for definition in (_resolve_definition_circuit(item) for item in defines) if definition]
        if is_hmux0_0303_0504:
            assert heat_pump is not None
            circuit = heat_pump.circuit
            defines.extend(
                [
                    f"r,{circuit},RunDataReturnTemp,RunDataReturnTemp,31,08,B509,5402000609"
                    ",value,,IGN:4,,,,value,,D2C,,°C,HMUX0 return temperature",
                    f"r,{circuit},YieldHc,YieldHc,31,08,B51A,05ff3210"
                    ",value,,IGN:3,,,,value,,UIN,,kWh,HMUX0 heating yield",
                    f"r,{circuit},YieldHcDay,YieldHcDay,31,08,B51A,05ff3200"
                    ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 heating yield today",
                    f"r,{circuit},YieldHcMonth,YieldHcMonth,31,08,B51A,05ff320e"
                    ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 heating yield this month",
                    f"r,{circuit},YieldHwc,YieldHwc,31,08,B51A,05ff3216"
                    ",value,,IGN:3,,,,value,,UIN,,kWh,HMUX0 DHW yield",
                    f"r,{circuit},YieldHwcDay,YieldHwcDay,31,08,B51A,05ff3202"
                    ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 DHW yield today",
                    f"r,{circuit},YieldHwcMonth,YieldHwcMonth,31,08,B51A,05ff3212"
                    ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 DHW yield this month",
                    f"r,{circuit},CopHc,CopHc,31,08,B51A,05ff3211,value,,IGN:3,,,,value,,UIN,10,,HMUX0 heating COP",
                    f"r,{circuit},CopHcMonth,CopHcMonth,31,08,B51A,05ff320f"
                    ",value,,IGN:3,,,,value,,UIN,10,,HMUX0 heating COP this month",
                    f"r,{circuit},CopHwc,CopHwc,31,08,B51A,05ff3217,value,,IGN:3,,,,value,,UIN,10,,HMUX0 DHW COP",
                    f"r,{circuit},CopHwcMonth,CopHwcMonth,31,08,B51A,05ff3213"
                    ",value,,IGN:3,,,,value,,UIN,10,,HMUX0 DHW COP this month",
                ]
            )
        if not is_hmux0_0303_0504:
            defines = [
                definition
                for definition in defines
                if ",Status00," not in definition and ",RunDataElPowerConsumption," not in definition
            ]
        if heat_pump and heat_pump.scan_type.upper() == "HMU00" and heat_pump.scan_hw == "5103":
            # Upstream ebusd-configuration PR #614, confirmed for HW5103.
            # Status07 is active-read because this HW5103 variant polls b511/07;
            # unsupported hardware returns ERR and remains absent from entities.
            defines.append(
                f"r,{heat_pump.circuit},Status07,Status07,31,08,B511,07"
                ",power,,UCH,,%,,dailyenvyield,,UIN,10,kWh,"
                ",display_b0_heaterenabled,,BI0,0=off;1=on,,"
                ",display_b1,,BI1,0=off;1=on,,"
                ",display_b2_backupheater,,BI2,0=off;1=on,,"
                ",display_b3,,BI3,0=off;1=on,,"
                ",display_b4,,BI4,0=off;1=on,,"
                ",display_b5_noisereduction,,BI5,0=off;1=on,,"
                ",display_b6_dhwecomode,,BI6,0=off;1=on,,"
                ",display_b7,,BI7,0=off;1=on,,"
                ",heatermain_b0,,BI0,0=off;1=on,,"
                ",heatermain_b1_error,,BI1,0=off;1=on,,"
                ",heatermain_b2,,BI2,0=off;1=on,,"
                ",heatermain_b3_heating,,BI3,0=off;1=on,,"
                ",heatermain_b4_cooling,,BI4,0=off;1=on,,"
                ",heatermain_b5_pressureloss,,BI5,0=off;1=on,,"
                ",heatermain_b6,,BI6,0=off;1=on,,"
                ",heatermain_b7_warmwater,,BI7,0=off;1=on,,"
                ",displaypressure,,UCH,30,bar,,"
                ",heaterbackup_b0,,BI0,0=off;1=on,,"
                ",heaterbackup_b1_error,,BI1,0=off;1=on,,"
                ",heaterbackup_b2,,BI2,0=off;1=on,,"
                ",heaterbackup_b3_heating,,BI3,0=off;1=on,,"
                ",heaterbackup_b4_cooling,,BI4,0=off;1=on,,"
                ",heaterbackup_b5_pressureloss,,BI5,0=off;1=on,,"
                ",heaterbackup_b6,,BI6,0=off;1=on,,"
                ",heaterbackup_b7_warmwater,,BI7,0=off;1=on,,"
            )
        defined = 0
        unavailable = 0
        for definition in defines:
            access, circuit, name = definition.split(",", 3)[:3]
            key = f"{access}.{circuit}.{name}"
            if self._runtime_definitions.get(key) == definition:
                continue
            try:
                resp = await self.ebus.define_register(definition)
                if resp.startswith("ERR:"):
                    unavailable += 1
                    _LOGGER.debug("Runtime register unavailable: %s (%s)", name, resp)
                else:
                    self._runtime_definitions[key] = definition
                    defined += 1
                    _LOGGER.debug("Runtime register defined: %s", name)
            except Exception as exc:
                unavailable += 1
                _LOGGER.warning("Failed to define register: %s", exc)
        if defined or unavailable:
            _LOGGER.info(
                "Runtime register definitions complete: %d defined, %d unavailable, %d total",
                defined,
                unavailable,
                len(defines),
            )

    async def _async_values_from_registers(self, registers: list[EbusdRegister] | None = None) -> dict[str, str]:
        values: dict[str, str] = {}
        for reg in registers or list(self.registers.values()):
            for field, value in reg.value.items():
                if value is not None:
                    translated = value
                    if reg.key == f"{self.heat_pump_circuit}.RunDataStatuscode":
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
            # Log the path and failure class only — never cache values.
            _LOGGER.warning("Failed to save register cache to %s", self._cache_path, exc_info=True)

    async def _async_load_cache(self) -> dict[str, str]:
        try:

            def _read():
                with open(self._cache_path) as f:
                    return json.load(f)

            return await self.hass.async_add_executor_job(_read)
        except FileNotFoundError:
            # First run without a cache file is normal — not a failure.
            return {}
        except Exception:
            # Corrupt or unreadable cache falls back to empty; keep the reason visible.
            _LOGGER.warning("Could not read register cache from %s; using empty cache", self._cache_path, exc_info=True)
            return {}

    def get_device_info(self, circuit: str) -> DeviceInfo:
        scan_type = ""
        scan_sw = ""
        scan_hw = ""
        parent: str | None = None
        node: DeviceNode | None = None

        if self._graph is not None:
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

        ebusd_version = self.ebus.version if self.ebus else None
        info = DeviceInfo(
            identifiers={(DOMAIN, circuit)},
            name=name,
            manufacturer="Vaillant",
            model=name,
            sw_version=scan_sw or ebusd_version,
            hw_version=scan_hw,
        )
        if parent:
            try:
                info["via_device_id"] = device_registry.async_get_device_id_by_identifier(
                    self.hass,
                    (DOMAIN, parent),
                    config_entry_id=self._entry.entry_id,
                )
            except ValueError:
                _LOGGER.debug("Parent device %s is not registered yet", parent)
        return info

    # Select a unique discovered owner for a logical register map entry.
    def _fallback_candidate(self, logical_circuit: str, name: str) -> str | None:
        """Return the circuit to read a register from.

        Prefer the circuit where the register was discovered (its raw or
        placeholder graph key); otherwise fall back to the literal map circuit.
        Mirrors the ctlv2/hmu aliasing used by get_meta() so registers that
        live under basv3/ctlv3/vwzio are read from the correct circuit.
        """
        expected_type = {
            "ctlv2": DeviceType.HEATING_CONTROLLER,
            "hmu": DeviceType.HEAT_PUMP,
            "bai": DeviceType.HEATING_CONTROLLER,
        }.get(logical_circuit)
        candidates: list[str] = []
        if self._graph is not None:
            keys = list(self._graph.raw_registers) + list(self._graph.placeholder_registers)
            candidates = list(
                dict.fromkeys(
                    circuit
                    for circuit in (rk.split(".", 1)[0] for rk in keys if rk.endswith(f".{name}"))
                    if expected_type is None
                    or (
                        self._graph.nodes.get(circuit) is not None
                        and self._graph.nodes[circuit].device_type == expected_type
                    )
                )
            )
        resolved = self.resolve_register_circuit(logical_circuit)
        if resolved is not None and resolved in candidates:
            return resolved
        if expected_type is None and len(candidates) == 1:
            return candidates[0]
        return None

    async def _fallback_read(
        self,
        include_placeholders: bool = False,
        include_energy: bool = False,
        skip_cache: set[str] | None = None,
    ) -> None:
        if not self.ebus or not self.ebus.is_connected:
            return
        graph_keys = self._last_find_keys

        # Resolve the REGISTER_MAP entry for a discovered register, applying the
        # same ctlv2/hmu circuit aliasing as get_meta().
        def _meta_key(circuit: str, name: str) -> str | None:
            for alt in (circuit, "ctlv2", "hmu"):
                key = f"{alt}.{name}"
                if key in REGISTER_MAP:
                    return key
            return None

        candidates: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def _add(circuit: str, name: str) -> None:
            key = (circuit, name)
            if key not in seen:
                seen.add(key)
                candidates.append(key)

        # Plain-r B516 definitions are not polled by ebusd. Re-read supported
        # counters even after find has cached their first value (#53/#97).
        if include_energy and self._graph:
            for definition in self._runtime_definitions.values():
                access, circuit, name, _, _, _, message = definition.split(",", 7)[:7]
                register = self.registers.get(f"{circuit}.{name}")
                if (
                    access == "r"
                    and message == "B516"
                    and circuit in self._graph.nodes
                    and register is not None
                    and register.has_data
                ):
                    _add(circuit, name)

        # Map-driven reads: registers with metadata not yet in the graph.
        for key in REGISTER_MAP:
            meta = REGISTER_MAP[key]
            if not meta.enabled or key in graph_keys:
                continue
            map_circuit, name = key.split(".", 1)
            if is_field_key(key):
                continue
            candidate_circuit = self._fallback_candidate(map_circuit, name)
            if (
                candidate_circuit is None
                and self._graph
                and any(
                    rk.endswith(f".{name}") for rk in (*self._graph.raw_registers, *self._graph.placeholder_registers)
                )
            ):
                continue
            resolved_circuit = (
                candidate_circuit if candidate_circuit is not None else self.resolve_register_circuit(map_circuit)
            )
            if resolved_circuit is not None:
                _add(resolved_circuit, name)

        # Placeholder reads: discovered no-data registers whose metadata
        # resolves via the circuit alias (15-minute interval).
        if include_placeholders and self._graph:
            for key in self._graph.placeholder_registers:
                parts = key.split(".", 1)
                if len(parts) != 2:
                    continue
                circuit, name = parts
                meta_key = _meta_key(circuit, name)
                if meta_key and REGISTER_MAP[meta_key].enabled:
                    _add(circuit, name)

        if not candidates:
            return
        _LOGGER.info("Fallback reading %d known register(s)", len(candidates))
        added = 0
        read_with_data = 0
        for circuit, name in candidates:
            key = f"{circuit}.{name}"
            try:
                value = await self.ebus.read_register(circuit, name)
                was_new = key not in self.registers
                value = _usable_register_value(key, value)
                if value and (value.startswith("or:") or "read [-" in value):
                    value = None
                if value is None:
                    cache = await self._async_load_cache()
                    cached = cache.get(f"{circuit}.{name}.value")
                    cached = _usable_register_value(key, cached)
                    if cached is not None and key not in (skip_cache or set()):
                        value = cached
                if value is not None:
                    read_with_data += 1
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
            except Exception as exc:
                _LOGGER.warning("Fallback read failed: %s (%s)", key, exc)
        if self._graph is not None:
            graph_added = 0
            for key, register in self.registers.items():
                if not register.has_data or key in self._graph.raw_registers:
                    continue
                node = self._graph.nodes.get(register.circuit)
                if node is None:
                    continue
                self._graph.raw_registers[key] = register.value.get("value") or ""
                if key not in node.registers:
                    node.registers.append(key)
                node.has_data = True
                self._last_find_keys.add(key)
                graph_added += 1
            if graph_added:
                _LOGGER.info("Fallback read added %d register(s) to discovery", graph_added)
                generated = self.entity_factory.generate(self._graph)
                known = {(entity.entity_type, entity.unique_id) for entity in self.entities}
                additions = [entity for entity in generated if (entity.entity_type, entity.unique_id) not in known]
                self.entities = _merge_entities(self.entities, generated)
                self._add_new_entities(additions)
        _LOGGER.info(
            "Fallback read complete: %d/%d registers with data (%d new)", read_with_data, len(candidates), added
        )

    async def _async_update_data(self) -> CoordinatorState:
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
                now = datetime.now()
                poll_energy = now - self._last_energy_poll >= ENERGY_POLL_INTERVAL
                if poll_energy:
                    await self._define_custom_registers()
                lines = await self.ebus.find_registers()
                updated = 0
                invalid_values: set[str] = set()
                for line in lines:
                    # Shared parser: sentinel/no-data values come back as None.
                    circuit, name, val = DiscoveryService._parse_register(line)
                    if not circuit or not name:
                        continue
                    key = f"{circuit}.{name}"
                    if val is None:
                        if key.lower() == "hmux0.rundatareturntemp":
                            raw = line.split("=", 1)[1].strip()
                            if not is_no_data_value(raw):
                                invalid_values.add(key)
                            if key in self.registers:
                                self.registers[key].value["value"] = None
                        continue
                    val = _usable_register_value(key, val)
                    if val is None:
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
                poll_placeholders = now - self._last_placeholder_poll >= PLACEHOLDER_POLL_INTERVAL
                if poll_placeholders:
                    self._last_placeholder_poll = now
                await self._fallback_read(
                    include_placeholders=poll_placeholders,
                    include_energy=poll_energy,
                    skip_cache=invalid_values,
                )
                self._disable_no_data_registry_entities(self.entities)
                if poll_energy:
                    self._last_energy_poll = now
                heat_pump_circuit = self.heat_pump_circuit
                if heat_pump_circuit is not None:
                    zero_idle_registers(self.registers, heat_pump_circuit)
                if updated:
                    _LOGGER.info("Poll updated %d registers", updated)
                return {"ebusd": await self._async_values_from_registers()}
            except ConnectionError, TimeoutError, OSError:
                _LOGGER.warning("ebusd connection lost, reconnecting")
                try:
                    # Only dismiss the repair issue when this call actually
                    # dialed; a skipped single-flight reconnect proves nothing.
                    reconnected = await self.ebus._reconnect() if self.ebus else False
                    if reconnected:
                        self._runtime_definitions.clear()
                        self._last_energy_poll = datetime.min
                        await repairs.async_dismiss_ebusd_unreachable(self.hass)
                except Exception as exc:
                    _LOGGER.error("ebusd reconnect failed: %s", exc)
                    await repairs.async_create_ebusd_unreachable(self.hass)

        return {"ebusd": await self._async_values_from_registers()}

    # Write one or more registers through the central write path. Each write is
    # verified by read-back. Sequences are dependent: stop at the first failure
    # instead of writing later registers on a broken assumption; refresh only
    # after full success. Already-written registers are reported, not rolled back.
    async def async_write_registers(
        self,
        writes: list[tuple[str, str, str]],
        strict_verify: bool = True,
        refresh: bool = True,
    ) -> bool:
        if not self.ebus or not self.ebus.is_connected:
            return False
        for circuit, name, value in writes:
            resolved_circuit = self.resolve_register_circuit(circuit)
            if resolved_circuit is None:
                _LOGGER.warning("Write skipped: ambiguous discovered circuit for %s.%s", circuit, name)
                return False
            result = await self.ebus.write_register(resolved_circuit, name, value, strict_verify=strict_verify)
            if not result.success:
                _LOGGER.warning("Write failed %s.%s=%s: %s", circuit, name, value, result.error_message)
                return False
        if refresh:
            await self.async_request_refresh()
        return True

    # Convenience wrapper for a single-register write through the central path.
    async def async_write_register(
        self,
        circuit: str,
        name: str,
        value: str,
        strict_verify: bool = True,
        refresh: bool = True,
    ) -> bool:
        return await self.async_write_registers([(circuit, name, value)], strict_verify=strict_verify, refresh=refresh)

    async def async_set_mode_override(
        self,
        flow_temperature: float,
        storage_temperature: float,
        mode: int = 0,
        keep_alive: bool = True,
    ) -> bool:
        """Write eloBLOCK B510 override and optionally refresh it periodically."""
        if not self.ebus or not self.ebus.is_connected:
            return False
        payload = f"{mode};{flow_temperature:g};{storage_temperature:g};-;-;0;0;0;-;0;0;0"
        ok = await self.async_write_register("bai", "SetModeOverride", payload, strict_verify=False)
        if not ok:
            return False
        self.async_clear_mode_override()
        self._set_mode_override_payload = payload if keep_alive else None
        if keep_alive:
            self._cancel_set_mode_override = async_track_time_interval(
                self.hass, self._async_keep_mode_override_alive, timedelta(seconds=50)
            )
        return True

    async def _async_keep_mode_override_alive(self, _now: datetime) -> None:
        if not self._set_mode_override_payload or not self.ebus or not self.ebus.is_connected:
            return
        await self.async_write_register("bai", "SetModeOverride", self._set_mode_override_payload, strict_verify=False)

    def async_clear_mode_override(self) -> None:
        if self._cancel_set_mode_override:
            self._cancel_set_mode_override()
            self._cancel_set_mode_override = None
        self._set_mode_override_payload = None

    async def async_stop(self) -> None:
        self.async_clear_mode_override()
        if self._cancel_delayed_rediscovery:
            self._cancel_delayed_rediscovery()
            self._cancel_delayed_rediscovery = None
        if self._cancel_analysis:
            self._cancel_analysis()
            self._cancel_analysis = None
        if self.ebus:
            await self.ebus.disconnect()
        self.ebus = None
