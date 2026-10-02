"""Coordinator for Vaillant eBUS — thin orchestration layer."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, TypedDict

import yaml
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import repairs
from .backend.analysis_service import AnalysisResult, AnalysisService
from .backend.discovery_service import HIDDEN_DEVICE_KEYWORDS, DiscoveryService, node_has_live_data
from .backend.ebus_service import EBUSD_STATUS_SUFFIXES, EbusService
from .backend.entity_factory import EntityDescription, EntityFactoryService
from .backend.mapping import (
    HMUX0_SW0407_ENVYIELD_REGISTERS,
    HMUX0_SW0407_FALLBACK_NAMES,
    REGISTER_MAP,
    VWZIO_SW0500_FALLBACK_NAMES,
    b516_date_bytes,
    hmux0_candidate_circuits,
    hmux0_fallback_blocked_circuits,
    hmux0_owner_scan,
    hmux0_sw0303_owner,
    hmux0_sw0407_circuit,
    is_field_key,
    metadata_circuits,
    multi_field_fields,
    split_multi_field,
    vwz_station_scan_76_circuit,
    vwzio_sw0500_circuit,
)
from .backend.models import (
    CIRCUIT_NAMES,
    COMPRESSOR_STATUS_LABELS,
    DeviceGraph,
    DeviceNode,
    DeviceType,
    EbusdRegister,
    ResolutionStatus,
    heat_pump_product,
    is_controller_circuit,
    is_ebusd_error_value,
    is_heat_pump_circuit,
    is_no_data_value,
    is_valid_hmux0_return_temperature,
    zero_idle_registers,
)
from .const import (
    CONF_EBUSD_HOST,
    CONF_EBUSD_PORT,
    CONF_ENERGY_DIVISOR,
    CONF_SCAN_INTERVAL,
    DEFAULT_EBUSD_POLL_INTERVAL,
    DEFAULT_ENERGY_DIVISOR,
    DOMAIN,
)
from .migration import (
    disable_legacy_room_temp_switch_sensor_aliases,
    enable_legacy_room_temp_switch_sensor_entities,
    remove_legacy_room_temp_switch_sensor_entities,
)

_LOGGER = logging.getLogger(__name__)


def _registry_matches_description(registry_unique_id: str, description_unique_id: str) -> bool:
    """Match HA's config-entry-prefixed ID to integration entity ID."""
    return registry_unique_id == description_unique_id or registry_unique_id.endswith(f"_{description_unique_id}")


DELAYED_REDISCOVERY_DELAY = timedelta(minutes=5)
ANALYSIS_INTERVAL = timedelta(minutes=15)
PLACEHOLDER_POLL_INTERVAL = timedelta(minutes=15)
ENERGY_POLL_INTERVAL = timedelta(minutes=5)
WRITE_LOG_SIZE = 100

# VWZIO/VWZ Status01 field layout (upstream PR #598); reuses the HMU layout.
# Explicit types are required: the hcmode_inc template aliases (temp1/temp2/
# pumpstate) are not resolvable in a runtime `define`.
VWZ_STATUS01_FIELDS = (
    "temp,,D1C,,,,temp_1,,D1C,,,,temp_2,,D2B,,,,temp_3,,D1C,,,,temp_4,,D1C,,,,"
    "pumpstate,,UCH,0=off;1=on;2=overrun;4=hwc,,"
)

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

HMUX0_SW0407_STATUS_VALUES = (
    "34=frost_protection;100=standby;101=heat_compressor_off;102=heat_compressor_blocked;"
    "103=heat_pump_prerun;104=heat_compressor_active;107=heat_pump_postrun;111=cool_compressor_off;"
    "112=cool_compressor_blocked;113=cool_pump_prerun;114=cool_compressor_active;117=cool_pump_postrun;"
    "125=heating_immersion_heater_active;132=dhw_compressor_blocked;133=dhw_pump_prerun;"
    "134=hwc_compressor_active;135=hwc_immersion_heater_active;137=dhw_pump_postrun;"
    "141=heating_immersion_heater_off;142=heating_immersion_heater_blocked;"
    "151=dhw_immersion_heater_off;152=dhw_immersion_heater_blocked;516=defrost"
)
HMUX0_SW0407_PASSIVE_REGISTERS = (
    (
        "RunDataStatuscode",
        "B509",
        "055402008813",
        f"value,,IGN:4,,,,value,,UIN,{HMUX0_SW0407_STATUS_VALUES},,",
    ),
    (
        "RunDataCompressorSpeed",
        "B509",
        "055402000d0a",
        "value,,IGN:4,,,,value,,EXP,,rps,HMUX0 compressor speed",
    ),
    (
        "RunDataElPowerConsumption",
        "B509",
        "055402005b0d",
        "value,,IGN:4,,,,value,,EXP,,W,HMUX0 electrical power consumption",
    ),
    (
        "RunDataBuildingCPumpPower",
        "B509",
        "05540200c509",
        "value,,IGN:4,,,,value,,EXP,,%,HMUX0 building circuit pump power",
    ),
    ("KmKreisVerflTemp", "B51A", "05ff3546", "value,,IGN:3,,,,value,,D2C,,°C,temperature"),
    ("UnterkuehlungSoll", "B51A", "05ff354a", "value,,IGN:3,,,,value,,D2C,,K,"),
    ("UnterkuehlungIst", "B51A", "05ff354b", "value,,IGN:3,,,,value,,D2C,,K,"),
    ("EEVAuslassTemp", "B51A", "05ff3702", "value,,IGN:3,,,,value,,D2C,,°C,temperature"),
    ("KmKreisKompEinlTemp", "B51A", "05ff3704", "value,,IGN:3,,,,value,,D2C,,°C,temperature"),
    ("KmKreisKompAuslTemp", "B51A", "05ff3705", "value,,IGN:3,,,,value,,D2C,,°C,temperature"),
    ("KmKreisHochdruck", "B51A", "05ff370b", "value,,IGN:3,,,,value,,UIN,10,bar,"),
)

# Registers whose live (non-sentinel) value marks a discovered zone as
# genuinely present. DayTemp/OpMode are excluded: ebusd reports static
# defaults for these even on unused zones, so they cannot distinguish a real
# zone from a ghost.
ZONE_LIVE_REGISTERS: tuple[str, ...] = ("RoomTemp", "ActualRoomTempDesired")


# Build the per-field value dict for a register (split multi-field values).
def _register_values(register_key: str, raw: str | None) -> dict[str, str | None]:
    return split_multi_field(register_key, raw)


# Intent: discard a staged cache after its executor finishes if its caller was cancelled.
# Why: the temporary path is returned only when the executor job completes.
def _discard_cancelled_cache_write(future: asyncio.Future[str]) -> None:
    try:
        staged_path = future.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        _LOGGER.warning("Failed to finish cancelled register-cache write: %s", exc)
        return
    try:
        os.unlink(staged_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        _LOGGER.warning("Failed to remove cancelled register-cache staging file: %s", exc)


# Intent: stage register-cache JSON before lifecycle-gated replacement.
# Why: executor completion can race with config-entry teardown or reload.
def _write_cache_temp(cache_path: str, values: dict[str, str]) -> str:
    cache_dir = os.path.dirname(cache_path)
    file_descriptor, staged_path = tempfile.mkstemp(prefix=".register_cache_", suffix=".tmp", dir=cache_dir)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as cache_file:
            json.dump(values, cache_file)
    except Exception:
        os.unlink(staged_path)
        raise
    return staged_path


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


# Whether an enabled REGISTER_MAP entry accounts for a register, applying the
# same ctlv2/hmu circuit aliasing as get_meta(). Registers covered by the map
# may legitimately be present via runtime definitions or the fallback read even
# when the current find output does not list them.
# Intent: report whether a map entry may support a cache-only register.
# Why: disabled fallback reads must not keep stale B524 values alive after discovery.
def _register_has_enabled_map_entry(register_key: str) -> bool:
    if "." not in register_key:
        return False
    circuit, name = register_key.split(".", 1)
    for alt in metadata_circuits(circuit):
        meta = next(
            (value for key, value in REGISTER_MAP.items() if key.casefold() == f"{alt}.{name}".casefold()),
            None,
        )
        if meta is not None and meta.enabled and meta.fallback_read:
            return True
    return False


# Intent: detect placeholders that metadata explicitly forbids polling or exposing.
# Why: cached descriptions must not survive when a live error is the only discovery result.
def _register_disables_fallback_placeholder(register_key: str) -> bool:
    if "." not in register_key:
        return False
    circuit, name = register_key.split(".", 1)
    for alt in metadata_circuits(circuit):
        meta = next(
            (value for key, value in REGISTER_MAP.items() if key.casefold() == f"{alt}.{name}".casefold()),
            None,
        )
        if meta is not None and meta.enabled and not meta.fallback_read:
            return True
    return False


# Intent: resolve a register dictionary key while preferring the current spelling.
# Why: cache/live updates with different casing must update one register object.
def _mapping_key(mapping: Mapping[str, object], key: str) -> str | None:
    if key in mapping:
        return key
    expected = key.casefold()
    return next((current for current in mapping if current.casefold() == expected), None)


# Intent: determine whether a cache-only mapped register still belongs to the
# discovered circuit rather than a legacy logical alias.
# Why: a BASS3/BAI bus can retain ctlv2 or hmu cache values from an older
# installation; preserving those aliases creates stale entities and ghost
# devices even though initial discovery has authoritative circuit metadata.
def _cache_register_is_supported(register_key: str, live_keys: set[str], graph: DeviceGraph) -> bool:
    register_fold = register_key.casefold()
    raw_keys = {key.casefold() for key in graph.raw_registers}
    placeholder_keys = {key.casefold() for key in graph.placeholder_registers}
    if register_fold in raw_keys:
        return True
    if register_fold in placeholder_keys:
        return False
    if register_fold in {key.casefold() for key in live_keys}:
        return True
    if not _register_has_enabled_map_entry(register_key):
        return False
    circuit = register_key.split(".", 1)[0]
    if _is_stale_legacy_alias(circuit, graph):
        return False
    return True


# Intent: identify cache rows from a logical alias that the current graph replaced.
# Why: preserve normal 1.9.x cache-backed entities while retiring proven old-device ghosts.
def _is_stale_legacy_alias(circuit: str, graph: DeviceGraph) -> bool:
    is_logical_alias = (
        is_controller_circuit(circuit) or is_heat_pump_circuit(circuit) or circuit.casefold() in {"bai", "vwz", "vwzio"}
    )
    if not is_logical_alias:
        return False
    resolved = graph.resolve_circuit_result(circuit)
    if resolved.status == ResolutionStatus.UNIQUE and resolved.circuit:
        return resolved.circuit.casefold() != circuit.casefold()
    return False


# Intent: disable registry entries whose cached source circuit disappeared from
# the current discovery graph.
# Why: cache-seeded platform entities may already be registered before the first
# real discovery completes; leaving them enabled would keep stale alias devices
# visible after the coordinator prunes their descriptions.
def _disable_stale_registry_entities(hass: HomeAssistant, entry_id: str, entities: list[EntityDescription]) -> None:
    registry = entity_registry.async_get(hass)
    stale_uids = {entity.unique_id for entity in entities}
    for entity_id, entry in registry.entities.items():
        if (
            entry.config_entry_id == entry_id
            and any(_registry_matches_description(entry.unique_id, uid) for uid in stale_uids)
            and entry.disabled_by != "user"
        ):
            registry.async_update_entity(entity_id, disabled_by=RegistryEntryDisabler.INTEGRATION)


# Intent: merge delayed discovery while replacing metadata that reflects the latest find response.
# Why: stale error-row markers must clear when a later usable find reports the register without an error.
def _merge_device_graphs(existing: DeviceGraph, discovered: DeviceGraph) -> DeviceGraph:
    nodes = dict(existing.nodes)
    for circuit, node in discovered.nodes.items():
        existing_circuit = next((key for key in nodes if key.casefold() == circuit.casefold()), None)
        previous = nodes.get(existing_circuit) if existing_circuit is not None else None
        if previous is None:
            nodes[circuit] = node
            continue
        target_circuit = existing_circuit or circuit
        nodes[target_circuit] = DeviceNode(
            circuit=target_circuit,
            device_type=(node.device_type if node.device_type != DeviceType.UNKNOWN else previous.device_type),
            registers=list(dict.fromkeys(previous.registers + node.registers)),
            parent=node.parent or previous.parent,
            zone_circuits=list(dict.fromkeys(previous.zone_circuits + node.zone_circuits)),
            heating_circuits=list(dict.fromkeys(previous.heating_circuits + node.heating_circuits)),
            has_data=node.has_data,
            scan_type=node.scan_type or previous.scan_type,
            scan_sw=node.scan_sw or previous.scan_sw,
            scan_hw=node.scan_hw or previous.scan_hw,
            scan_address=node.scan_address,
        )

    discovered_circuits = {circuit.casefold() for circuit in discovered.nodes}
    for circuit, node in tuple(nodes.items()):
        if circuit.casefold() in {"vwz", "vwzio"} and circuit.casefold() not in discovered_circuits:
            nodes[circuit] = replace(node, scan_address="")

    unavailable_keys = {key.casefold() for key in discovered.placeholder_registers}
    raw_registers = {
        key: value for key, value in existing.raw_registers.items() if key.casefold() not in unavailable_keys
    }
    raw_by_fold = {key.casefold(): key for key in raw_registers}
    for key, value in discovered.raw_registers.items():
        raw_registers[raw_by_fold.get(key.casefold(), key)] = value
        raw_by_fold.setdefault(key.casefold(), key)
    placeholder_registers = set(existing.placeholder_registers)
    placeholder_by_fold = {key.casefold(): key for key in placeholder_registers}
    for key in discovered.placeholder_registers:
        placeholder_registers.add(placeholder_by_fold.get(key.casefold(), key))
        placeholder_by_fold.setdefault(key.casefold(), key)
    placeholder_registers = {
        key for key in placeholder_registers if key.casefold() not in {rk.casefold() for rk in raw_registers}
    }
    error_registers = set(discovered.error_registers)
    for node in nodes.values():
        node.has_data = node_has_live_data(node, raw_registers)
    return DeviceGraph(
        nodes=nodes,
        raw_registers=raw_registers,
        placeholder_registers=placeholder_registers,
        error_registers=error_registers,
        scan_identities=discovered.scan_identities,
    )


# Append entity descriptions without duplicating keys already present.
def _merge_entities(
    existing: list[EntityDescription],
    additions: list[EntityDescription],
) -> list[EntityDescription]:
    known = {(entity.entity_type, entity.unique_id.casefold()): entity for entity in existing}
    merged = list(existing)
    for entity in additions:
        identity = (entity.entity_type, entity.unique_id.casefold())
        if identity not in known:
            merged.append(entity)
            known[identity] = entity
        else:
            # Cache spelling may differ from find; loaded entities keep this
            # description object, so update its lookup key without re-adding it.
            known[identity].name = entity.name
            known[identity].circuit = entity.circuit
            known[identity].field = entity.field
            known[identity].raw_value = entity.raw_value
            known[identity].register = entity.register
            known[identity].enabled_by_default = entity.enabled_by_default
    return merged


# Intent: retrieve a register value case-insensitively from a coordinator-like object.
# Why: platform tests and delayed discovery stubs may provide a coordinator without the concrete method.
def get_register_value(coordinator: Any, circuit: str, name: str, field: str = "value") -> str | None:
    expected = f"{circuit}.{name}.{field}".casefold()
    data = getattr(coordinator, "data", {}) or {}
    ebusd = data.get("ebusd", {}) if isinstance(data, dict) else {}
    exact_key = f"{circuit}.{name}.{field}"
    if exact_key in ebusd:
        value = ebusd[exact_key]
        return str(value) if value is not None else None
    for key, value in ebusd.items():
        if key.casefold() == expected:
            return str(value) if value is not None else None
    return None


class VaillantCoordinator(DataUpdateCoordinator[CoordinatorState]):
    # Intent: initialize per-entry connection, cache and recovery state.
    # Why: setup and retry tasks rely on one consistent starting lifecycle.
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._stopped = False
        self._unload_requested = False
        self._pending_ebus: EbusService | None = None
        self._started = False
        self._setup_task: asyncio.Task[None] | None = None
        self._active_dump_tasks: set[asyncio.Task] = set()
        self._ebusd_connected = False
        self._ebusd_repair_pending = False
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
        self._delayed_rediscovery_retry_count = 0
        self._live_since_analysis: set[str] = set()
        self._cancel_analysis: Callable[[], None] | None = None
        self._analysis_scheduled = False
        self._last_placeholder_poll = datetime.min
        self._last_energy_poll = datetime.min
        self._runtime_definitions: dict[str, str] = {}
        self._write_log: list[dict] = []  # recent write attempts (verification/telegram diag)
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

    # Intent: report when reads and writes can trust the current discovery graph.
    # Why: a live TCP socket alone does not establish register ownership.
    @property
    def discovery_ready(self) -> bool:
        return self._ebusd_connected and self._graph is not None and bool(self._graph.nodes)

    @property
    def heating_circuit(self) -> str | None:
        if self._graph is None:
            return None
        result = self._graph.heating_controller_result()
        return result.circuit if result.status == ResolutionStatus.UNIQUE else None

    @property
    def heat_pump_circuit(self) -> str | None:
        if self._graph is None:
            return None
        result = self._graph.heat_pump_result()
        return result.circuit if result.status == ResolutionStatus.UNIQUE else None

    def resolve_register_circuit(self, circuit: str) -> str | None:
        """Resolve legacy map circuits to circuits discovered on this bus."""
        if self._graph is not None:
            resolution = self._graph.resolve_circuit_result(circuit)
            if resolution.status != ResolutionStatus.UNIQUE:
                return None
            return resolution.circuit or circuit
        return None

    # Intent: allow user-initiated reads only after the discovered graph is authoritative.
    # Why: cache-seeded aliases must not route requests during initial discovery.
    async def async_read_register(self, circuit: str, name: str, field: str = "") -> str | None:
        """Read a register only after resolving its discovered circuit owner."""
        if (
            self._stopped
            or self._unload_requested
            or not self.ebus
            or not self.ebus.is_connected
            or not self.discovery_ready
        ):
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

    # Intent: select the lowest-numbered discovered active zone as the primary UI zone.
    # Why: primary-zone entities must not assume that z1 is present on every controller.
    @property
    def primary_zone(self) -> str | None:
        zones = self.zone_circuits()
        if not zones:
            return None
        return min(zones, key=lambda zone: int(zone[1:]) if zone[1:].isdigit() else zone)

    # Intent: read a coordinator value without depending on ebusd register casing.
    # Why: protocol dumps may preserve lower-case names while metadata uses canonical casing.
    def value_for_register(self, circuit: str, name: str, field: str = "value") -> str | None:
        return get_register_value(self, circuit, name, field)

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
        expected_mapping = f"{circuit}.{zn}RoomZoneMapping".casefold()
        mapping = next(
            (value for key, value in self._graph.raw_registers.items() if key.casefold() == expected_mapping),
            None,
        )
        if self._zone_value_has_data(mapping):
            return True
        # Fall back to a measured value on a live register. Static defaults
        # (DayTemp/OpMode) and sentinel values (empty/unknown/no data stored)
        # do not prove the zone is real.
        for name in ZONE_LIVE_REGISTERS:
            expected = f"{circuit}.{zn}{name}".casefold()
            value = next(
                (raw for key, raw in self._graph.raw_registers.items() if key.casefold() == expected),
                None,
            )
            if self._zone_value_has_data(value):
                return True
        return False

    # Return whether a zone register is supported, unsupported, or not discovered yet.
    def zone_register_discovery_status(self, circuit: str, zone: str, name: str) -> bool | None:
        if self._graph is None or not self._last_find_keys:
            return None
        key = f"{circuit}.{zone.upper()}{name}"
        if key in self._graph.raw_registers or key in self._graph.placeholder_registers:
            return True
        lower = key.lower()
        return any(rk.lower() == lower for rk in self._graph.raw_registers) or any(
            rk.lower() == lower for rk in self._graph.placeholder_registers
        )

    # Preserve optimistic pre-discovery UI feature visibility for non-write capabilities.
    def has_zone_register(self, circuit: str, zone: str, name: str) -> bool:
        status = self.zone_register_discovery_status(circuit, zone, name)
        return status is not False

    # Intent: check a discovered HcN register on its owning source circuit.
    # Why: flow-range and heating-circuit writes must not be confused with ZN registers.
    def has_heating_circuit_register(self, circuit: str, heating_circuit: str, name: str) -> bool:
        if self._graph is None or not self._last_find_keys:
            return False
        resolved = self.resolve_register_circuit(circuit) or circuit
        key = f"{resolved}.{heating_circuit.upper()}{name}"
        return (
            key in self._graph.raw_registers
            or key in self._graph.placeholder_registers
            or any(rk.casefold() == key.casefold() for rk in self._last_find_keys)
        )

    # Whether a controller-owned register exists on the discovered controller circuit.
    def has_controller_register(self, name: str) -> bool:
        if self._graph is None or not self._last_find_keys:
            return False
        circuit = self.heating_circuit
        if circuit is None:
            return False
        key = f"{circuit}.{name}"
        if key in self._graph.raw_registers or key in self._graph.placeholder_registers:
            return True
        lower = key.lower()
        return any(rk.lower() == lower for rk in self._graph.raw_registers) or any(
            rk.lower() == lower for rk in self._graph.placeholder_registers
        )

    # Retain no-data discovery keys while polling so capability gates stay authoritative.
    def _refresh_find_keys(self) -> None:
        if self._graph is None:
            self._last_find_keys = set(self.registers)
            return
        self._last_find_keys = set(self._graph.raw_registers) | set(self._graph.placeholder_registers)

    # Intent: stage cached discovery state until all asynchronous inputs are ready.
    # Why: cache and YAML reads may overlap an unload request.
    async def _async_seed_entities_from_cache(self) -> None:
        cache = await self._async_load_cache()
        if self._stopped or self._unload_requested:
            return
        find_lines: list[str] = []
        cached_registers: dict[str, EbusdRegister] = {}
        seen_keys: set[str] = set()

        for cache_key, cached_value in cache.items():
            if cached_value is None or not cached_value.strip() or is_no_data_value(cached_value):
                continue
            parts = cache_key.split(".")
            if len(parts) < 2:
                continue
            if len(parts) > 2 and parts[2].casefold() != "value":
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
            cached_registers[rk] = EbusdRegister(
                circuit=circuit,
                name=name,
                fields=["value"],
                value=_register_values(rk, cached_value),
                has_data=True,
            )

        # Reuse live discovery so cached ZN and HcN registers form logical devices.
        graph = DiscoveryService.build_device_graph(find_lines)
        yaml_overrides = await self._async_load_yaml_overrides()
        if self._stopped or self._unload_requested:
            return
        cached_entities = self.entity_factory.generate(graph, yaml_overrides=yaml_overrides)
        self.registers.update(cached_registers)
        if graph.nodes:
            self._graph = graph
        self.entities = [entity for entity in cached_entities if not entity.meta.writable]
        _LOGGER.info(
            "Seeded %d entities from %d cache entries (%d circuits)", len(self.entities), len(cache), len(graph.nodes)
        )

    # Intent: establish a working ebusd session before clearing connection repairs.
    # Why: a prior startup failure must stop surfacing once fresh discovery succeeds.
    async def _ebusd_connect_and_discover(self) -> None:
        if self._stopped or self._unload_requested:
            return
        host = self.ebusd_host
        if not host:
            self._started = False
            return
        ebus = EbusService(host=host, port=self.ebusd_port)
        self._pending_ebus = ebus
        try:
            await ebus.connect()
        except Exception as exc:
            self._pending_ebus = None
            if self._stopped or self._unload_requested:
                self._started = False
                return
            await self._async_mark_ebusd_unreachable(f"connect failed: {exc}")
            return
        if self._stopped or self._unload_requested:
            await ebus.disconnect()
            self._pending_ebus = None
            self._started = False
            return
        self.ebus = ebus
        self._pending_ebus = None
        self.discovery = DiscoveryService(ebus)
        self._runtime_definitions.clear()
        self._last_energy_poll = datetime.min

        version = ebus.version
        if version:
            _LOGGER.info("ebusd version: %s", version)

        try:
            graph = await self.discovery.discover()
        except Exception as exc:
            await ebus.disconnect()
            if self._stopped or self._unload_requested:
                self._started = False
                return
            await self._async_mark_ebusd_unreachable(f"discovery failed: {exc}")
            return
        if self._stopped or self._unload_requested:
            await ebus.disconnect()
            self.ebus = None
            self.discovery = None
            self._started = False
            return
        if not graph.nodes:
            _LOGGER.warning("ebusd discovery returned no usable graph; retaining the repair and retrying setup")
            await ebus.disconnect()
            self.ebus = None
            self.discovery = None
            await self._async_mark_ebusd_unreachable("initial discovery returned no device graph")
            return

        # Scan-only nodes preserve identity when ebusd has no matching CSV. Runtime
        # definitions are therefore always resolved from discovered ownership.
        self._graph = graph
        try:
            await self._define_custom_registers()
            if self._stopped or self._unload_requested:
                await ebus.disconnect()
                self.ebus = None
                self.discovery = None
                self._started = False
                return
            # Refresh once so every newly defined register enters the initial graph.
            # This also avoids polling generic HMU definitions before scan discovery
            # can identify an HMUX0 device.
            if self._runtime_definitions:
                refreshed_graph = await self.discovery.discover()
                if self._stopped or self._unload_requested:
                    await ebus.disconnect()
                    self.ebus = None
                    self.discovery = None
                    self._started = False
                    return
                if graph.nodes and not refreshed_graph.nodes:
                    if getattr(ebus, "last_find_usable", None) is not False:
                        _LOGGER.warning(
                            "Post-definition find returned no graph nodes; merging the current scan snapshot"
                        )
                        graph = _merge_device_graphs(graph, refreshed_graph)
                    else:
                        _LOGGER.warning("Post-definition find was unusable; retaining the initial discovery graph")
                    if self._ebusd_repair_pending:
                        await ebus.disconnect()
                        await self._async_mark_ebusd_unreachable(
                            "post-definition find returned no usable graph during recovery"
                        )
                        return
                else:
                    graph = refreshed_graph
        except Exception as exc:
            await ebus.disconnect()
            await self._async_mark_ebusd_unreachable(f"post-definition discovery failed: {exc}")
            return
        try:
            self._ebusd_connected = True
            await self._apply_discovery_graph(graph, "initial")
        except Exception as exc:
            self._ebusd_connected = False
            await ebus.disconnect()
            await self._async_mark_ebusd_unreachable(f"initial graph application failed: {exc}")
            return
        if not ebus.is_connected:
            if not self._ebusd_repair_pending:
                await self._async_mark_ebusd_unreachable("connection closed while applying initial discovery")
            return
        self._ebusd_connected = True
        await repairs.async_dismiss_ebusd_unreachable(self.hass)
        self._ebusd_repair_pending = False
        await repairs.async_dismiss_detection_incomplete(self.hass)
        self._delayed_rediscovery_retry_count = 0
        self._schedule_delayed_rediscovery()
        self._schedule_analysis()

    # Intent: restore retry eligibility and clean up transport state after setup cancellation.
    # Why: cancelled background setup must not strand a pending ebusd connection.
    async def _async_run_setup_task(self) -> None:
        try:
            await self._ebusd_connect_and_discover()
        except asyncio.CancelledError:
            clients = [self._pending_ebus]
            if self.ebus is not self._pending_ebus:
                clients.append(self.ebus)
            for ebus in clients:
                if ebus is None:
                    continue
                ebus.request_shutdown()
                await ebus.disconnect()
                if self._pending_ebus is ebus:
                    self._pending_ebus = None
                if self.ebus is ebus:
                    self.ebus = None
                    self.discovery = None
                    self._ebusd_connected = False
            self._started = False
            raise
        finally:
            if not self._ebusd_connected and not self._stopped and not self._unload_requested:
                self._started = False

    # Intent: reset the coordinator after an ebusd transport or discovery failure.
    # Why: future polls must launch a fresh connection instead of reusing a dead client.
    async def _async_mark_ebusd_unreachable(self, reason: str) -> None:
        if self._stopped or self._unload_requested:
            return
        self._ebusd_connected = False
        self._started = False
        self._ebusd_repair_pending = True
        _LOGGER.warning("ebusd unavailable, will retry: %s", reason)
        await repairs.async_create_ebusd_unreachable(self.hass)

    # Intent: apply discovery results to cached and generated entity descriptions.
    # Why: initial and delayed rediscovery must retire stale entities before forwarding replacements.
    async def _apply_discovery_graph(self, graph: DeviceGraph, source: str) -> None:
        if self._stopped or self._unload_requested:
            return
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
            existing_key = _mapping_key(self.registers, rk)
            if existing_key is None:
                self.registers[rk] = EbusdRegister(
                    circuit=circuit,
                    name=name,
                    fields=["value"],
                    value=_register_values(rk, raw),
                    has_data=True,
                )
            else:
                register = self.registers[existing_key]
                if existing_key != rk:
                    del self.registers[existing_key]
                    register.circuit, register.name = rk.split(".", 1)
                    self.registers[rk] = register
                register.value.update(_register_values(rk, raw))
                register.has_data = True

        raw_key_folds = {key.casefold() for key in graph.raw_registers}
        for key in graph.placeholder_registers:
            if key.casefold() in raw_key_folds:
                continue
            existing_key = _mapping_key(self.registers, key)
            if existing_key is not None:
                register = self.registers[existing_key]
                register.value = _register_values(existing_key, None)
                register.has_data = False

        self._refresh_find_keys()

        # A cache-seeded rebuild at startup can carry registers the real bus no
        # longer exposes (e.g. a stale test register from an old CSV or session).
        # Registers explained by neither the discovered graph nor an enabled
        # REGISTER_MAP entry are pruned so ghost devices cannot survive on
        # cached leftovers. Only on initial discovery: delayed rediscovery blends
        # into a growing graph and must not drop registers that were merely slow
        # to appear.
        if source == "initial":
            live_keys = set(graph.raw_registers) | set(graph.placeholder_registers)
            stale = [rk for rk in self.registers if not _cache_register_is_supported(rk, live_keys, graph)]
            for rk in stale:
                del self.registers[rk]
            if stale:
                _LOGGER.info(
                    "Pruned %d stale cache register(s) absent from the bus: %s",
                    len(stale),
                    ", ".join(sorted(stale)),
                )
            stale_keys = set(stale)
            raw_key_folds = {key.casefold() for key in graph.raw_registers}
            placeholder_keys = {key for key in graph.placeholder_registers if key.casefold() not in raw_key_folds}
            non_exposable_placeholder_keys = {
                key for key in placeholder_keys if _register_disables_fallback_placeholder(key)
            }
            for entity in self.entities:
                entity_key = f"{entity.circuit}.{entity.name}"
                if entity_key.casefold() in {key.casefold() for key in placeholder_keys}:
                    entity.raw_value = ""
                    entity.enabled_by_default = False
            stale_entity_key_folds = {
                key.casefold() for key in (stale_keys - placeholder_keys) | non_exposable_placeholder_keys
            }
            stale_entities = [
                entity
                for entity in self.entities
                if f"{entity.circuit}.{entity.name}".casefold() in stale_entity_key_folds
            ]
            if stale_entities:
                self.entities = [
                    entity
                    for entity in self.entities
                    if f"{entity.circuit}.{entity.name}".casefold() not in stale_entity_key_folds
                ]
                _disable_stale_registry_entities(self.hass, self._entry.entry_id, stale_entities)
                _LOGGER.info("Pruned %d stale cache entit(y/ies) after discovery", len(stale_entities))

        try:
            await self._fallback_read()
        except Exception as exc:
            _LOGGER.warning("%s fallback read failed: %s", source.capitalize(), exc)
            if not self.ebus or not self.ebus.is_connected:
                await self._async_mark_ebusd_unreachable(f"{source} fallback read lost transport: {exc}")
        if self._stopped or self._unload_requested:
            return

        generated_entities = self.entity_factory.generate(graph, yaml_overrides=await self._async_load_yaml_overrides())
        if self._stopped or self._unload_requested:
            return
        room_temp_select_unique_ids = {
            entity.unique_id
            for entity in generated_entities
            if entity.name.casefold() == "hc1roomtempswitchon" and entity.entity_type == "select"
        }
        if room_temp_select_unique_ids:
            self.entities = [
                entity
                for entity in self.entities
                if not (entity.name.casefold() == "hc1roomtempswitchon" and entity.entity_type == "sensor")
            ]
            remove_legacy_room_temp_switch_sensor_entities(
                entity_registry.async_get(self.hass),
                self._entry.entry_id,
                DOMAIN,
                {f"{self._entry.entry_id}_{unique_id}" for unique_id in room_temp_select_unique_ids},
            )
            disable_legacy_room_temp_switch_sensor_aliases(
                entity_registry.async_get(self.hass),
                self._entry.entry_id,
                DOMAIN,
                "Hc1RoomTempSwitchOn",
            )
        controller = graph.heating_controller_result().node
        if controller is not None and controller.scan_type.upper() == "CTLV2":
            room_temp_sensor_unique_ids = {
                entity.unique_id
                for entity in generated_entities
                if entity.name.casefold() == "hc1roomtempswitchon"
                and entity.entity_type == "sensor"
                and entity.circuit.casefold() == controller.circuit.casefold()
            }
            for entity in generated_entities:
                if entity.unique_id in room_temp_sensor_unique_ids:
                    entity.enabled_by_default = True
            enable_legacy_room_temp_switch_sensor_entities(
                entity_registry.async_get(self.hass),
                self._entry.entry_id,
                DOMAIN,
                {f"{self._entry.entry_id}_{unique_id}" for unique_id in room_temp_sensor_unique_ids},
            )
        await self._enable_registry_entities(list(graph.raw_registers))
        existing_entity_keys = {(entity.entity_type, entity.unique_id.casefold()) for entity in self.entities}
        additions = [
            entity
            for entity in generated_entities
            if (entity.entity_type, entity.unique_id.casefold()) not in existing_entity_keys
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
        if source == "delayed":
            values = await self._async_values_from_registers()
            if self._stopped or self._unload_requested:
                return
            self.async_set_updated_data({"ebusd": values})
        else:
            self.async_update_listeners()
        for callback in self._post_discovery_callbacks:
            try:
                callback()
            except Exception:
                _LOGGER.warning("Post-discovery callback failed", exc_info=True)

    # Intent: refresh live scan ownership from each usable find before any runtime definition or fallback read.
    # Why: discovery-ready graphs still need current address evidence when bus identities change.
    async def _refresh_graph_from_usable_find(self, find_lines: list[str]) -> None:
        discovered = DiscoveryService.build_device_graph(find_lines)
        if self.discovery_ready and self._graph is not None:
            self._graph = _merge_device_graphs(self._graph, discovered)
        elif discovered.nodes:
            await self._apply_discovery_graph(discovered, "delayed")
        elif self._graph is not None:
            self._graph = _merge_device_graphs(self._graph, discovered)

    # Intent: keep at most one delayed discovery callback pending.
    # Why: one bounded retry handles transient find failures without polling continuously.
    def _schedule_delayed_rediscovery(self) -> None:
        if self._stopped or self._unload_requested or self._delayed_rediscovery_scheduled:
            return
        self._delayed_rediscovery_scheduled = True
        self._cancel_delayed_rediscovery = async_call_later(
            self.hass,
            DELAYED_REDISCOVERY_DELAY,
            self._async_delayed_rediscover,
        )

    # Intent: refresh discovery once after the initial ebusd startup window.
    # Why: delayed discovery can fill registers that were unavailable during setup.
    async def _async_delayed_rediscover(self, _: datetime) -> None:
        if self._stopped or self._unload_requested:
            self._cancel_delayed_rediscovery = None
            self._delayed_rediscovery_scheduled = False
            return
        self._cancel_delayed_rediscovery = None
        self._delayed_rediscovery_scheduled = False
        if not self.ebus or not self.ebus.is_connected:
            if self._ebusd_connected:
                await self._async_mark_ebusd_unreachable("ebusd disconnected before delayed discovery")
            return
        if not self.discovery:
            _LOGGER.warning("Delayed ebusd discovery skipped: no discovery service is available")
            return
        try:
            graph = await self.discovery.discover()
        except Exception as exc:
            _LOGGER.warning("Delayed ebusd discovery failed: %s", exc)
            if not self.ebus.is_connected:
                await self._async_mark_ebusd_unreachable(f"delayed discovery lost transport: {exc}")
            elif self._delayed_rediscovery_retry_count == 0:
                self._delayed_rediscovery_retry_count = 1
                if not self._unload_requested:
                    self._schedule_delayed_rediscovery()
            return
        if not graph.nodes:
            _LOGGER.warning("Delayed find returned no graph; retaining current discovery")
            if self._delayed_rediscovery_retry_count == 0:
                self._delayed_rediscovery_retry_count = 1
                if not self._unload_requested:
                    self._schedule_delayed_rediscovery()
            return
        try:
            await self._apply_discovery_graph(graph, "delayed")
        except Exception as exc:
            _LOGGER.warning("Delayed ebusd graph application failed: %s", exc)
            if self._delayed_rediscovery_retry_count == 0:
                self._delayed_rediscovery_retry_count = 1
                if not self._unload_requested:
                    self._schedule_delayed_rediscovery()
            return
        self._delayed_rediscovery_retry_count = 0

    # Schedule the recurring background analysis for recently live registers.
    def _schedule_analysis(self) -> None:
        if self._stopped or self._unload_requested or self._analysis_scheduled:
            return
        self._analysis_scheduled = True
        self._cancel_analysis = async_call_later(
            self.hass,
            ANALYSIS_INTERVAL,
            self._async_run_analysis,
        )

    # Reschedule the analysis loop and hand the live-register set to the service.
    async def _async_run_analysis(self, _: datetime) -> None:
        if self._stopped or self._unload_requested:
            self._cancel_analysis = None
            self._analysis_scheduled = False
            return
        self._cancel_analysis = None
        self._analysis_scheduled = False
        try:
            if self.ebus and self.ebus.is_connected:
                await self._analyze_live_registers()
        except Exception:
            _LOGGER.warning("Background register analysis failed", exc_info=True)
        finally:
            if not self._stopped:
                self._schedule_analysis()

    # Analyze registers that went live since the last tick, discover + enable.
    async def _analyze_live_registers(self) -> None:
        if self._stopped or self._unload_requested:
            return
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
        if self._stopped or self._unload_requested:
            return
        _LOGGER.info("Manual ebusd rediscovery requested; reconnecting and rebuilding the discovery graph")
        if self.ebus:
            await self.ebus.disconnect()
        self.ebus = None
        self._ebusd_connected = False
        self._started = False
        if self._stopped or self._unload_requested:
            return
        await self.async_request_refresh()

    # Push newly discovered entity descriptions to the matching platform adder.
    def _add_new_entities(self, new_entities: list[EntityDescription]) -> None:
        if self._stopped or self._unload_requested:
            return
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
    # them when the register later returns a real value. An enabled registry
    # entry (disabled_by is None) whose description carries no live value is
    # disabled unless it is a non-default entity — Home Assistant never
    # auto-enables such an entity, so an enabled entry there is an explicit
    # user choice that a temporary no-data result must not undo (issue #152).
    # The supported CTLV2 room-temperature threshold sensor also stays enabled
    # as unknown while its register has no current value.
    def _disable_no_data_registry_entities(self, descriptions: list[EntityDescription]) -> None:
        registry = entity_registry.async_get(self.hass)
        disabled = 0
        controller = self._graph.heating_controller_result().node if self._graph is not None else None
        for description in descriptions:
            if (
                str(getattr(description, "name", "") or "").casefold() == "hc1roomtempswitchon"
                and getattr(description, "entity_type", None) == "sensor"
                and controller is not None
                and controller.circuit.casefold() == getattr(description, "circuit", "").casefold()
                and controller.scan_type.upper() == "CTLV2"
            ):
                continue
            if description.raw_value:
                continue
            # Only the integration may manage (re-disable) entries it already
            # disabled; a user-disabled entry is never touched.
            for entity_id, entry in registry.entities.items():
                if entry.config_entry_id != self._entry.entry_id or not _registry_matches_description(
                    entry.unique_id, description.unique_id
                ):
                    continue
                if entry.disabled_by is None:
                    # Default-enabled entities lose their enabled state when
                    # no data is present; non-default entities stay as the user
                    # left them.
                    if not description.enabled_by_default:
                        continue
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

    # Intent: inject only evidence-backed runtime register definitions after the bus owner is known.
    # Why: definitions must follow discovered circuit identity and preserve safe absent-register behavior.
    async def _define_custom_registers(self) -> None:
        if (
            self._stopped
            or self._unload_requested
            or not self.ebus
            or not self.ebus.is_connected
            or self._graph is None
        ):
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
            # eloBLOCK/BAI boiler control: the generic BAI configuration exposes
            # HeatingSwitch/HwcSwitch read-only. Redefine them writable on B509
            # using the upstream product-specific convention: read id `0dF203` /
            # `0dF303`, write prefix byte `0e` (`0eF203`/`0eF303`), and a UCH
            # onoff field. The `onoff` template is not in the runtime define's
            # template scope, so `value,,onoff` fails element lookup with
            # `ERR: element not found`; UCH decodes identically. Only emitted
            # when a BAI controller is discovered.
            "wi,bai,HeatingSwitch,Heating Switch,,08,B509,0ef203,value,,UCH,0=off;1=on,,",
            "wi,bai,HwcSwitch,DHW Switch,,08,B509,0ef303,value,,UCH,0=off;1=on,,",
            # VWZIO/VWZ Hydraulikstation process telemetry (upstream PR #598).
            # Status01 (b511 01, 9 bytes) reuses the HMU layout: flow, return,
            # outside, DHW, storage, pump. Read actively like hmu.Status01 so it
            # populates immediately; emitted for whichever of vwz/vwzio the bus
            # exposes, and resolution drops the variant that is not discovered.
            "r,vwz,Status01,Status01,31,76,B511,01," + VWZ_STATUS01_FIELDS,
            "r,vwzio,Status01,Status01,31,76,B511,01," + VWZ_STATUS01_FIELDS,
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
            "compressormodulation,,UCH,,%,,compressorstate,,UCH,0=off;1=heating_prerun;"
            "4=heating;5=heating_overrun;24=hot_water;110=defrosting,,,"
            "heatingstate,,UCH,8=off;9=heating,,,field6,,UCH,,,,"
            "defrost,,UCH,0=inactive;32=active,,,compressorpower,,percent1,,%,HMUX0 Status00",
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
        hmux0_sw0407_owner = hmux0_sw0407_circuit(self._graph)
        if hmux0_sw0407_owner is not None:
            circuit = hmux0_sw0407_owner
            defines.extend(
                [
                    f"r,{circuit},HcEnvYieldTotal,HcEnvYieldTotal,31,08,B516"
                    ",1000ffff02030000,value,,IGN:7,,,,value,,EXP,,Wh"
                    ",HMUX0 heating environmental yield total",
                    f"r,{circuit},HcEnvYieldDay,HcEnvYieldDay,31,08,B516"
                    f",1001ffff0203{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
                    ",HMUX0 heating environmental yield today",
                    f"r,{circuit},HcEnvYieldMonth,HcEnvYieldMonth,31,08,B516"
                    f",1002ffff0203{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
                    ",HMUX0 heating environmental yield this month",
                    f"r,{circuit},HwcEnvYieldTotal,HwcEnvYieldTotal,31,08,B516"
                    ",1000ffff02040000,value,,IGN:7,,,,value,,EXP,,Wh"
                    ",HMUX0 DHW environmental yield total",
                    f"r,{circuit},HwcEnvYieldDay,HwcEnvYieldDay,31,08,B516"
                    f",1001ffff0204{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
                    ",HMUX0 DHW environmental yield today",
                    f"r,{circuit},HwcEnvYieldMonth,HwcEnvYieldMonth,31,08,B516"
                    f",1002ffff0204{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
                    ",HMUX0 DHW environmental yield this month",
                ]
            )
        hmux0_owner = hmux0_owner_scan(self._graph)
        hmux0_sw0303_circuit = hmux0_sw0303_owner(self._graph)
        is_hmux0_0303_0504 = hmux0_sw0303_circuit is not None
        is_hmux0_b509_0504 = bool(
            hmux0_owner
            and hmux0_owner[1].complete
            and hmux0_owner[1].scan_sw in {"0302", "0303"}
            and hmux0_owner[1].scan_hw == "0504"
        )
        vwzio_circuit = vwzio_sw0500_circuit(self._graph)
        vwzio = next(
            (
                node
                for node in self._graph.nodes.values()
                if node.circuit.casefold() == (vwzio_circuit or "").casefold()
            ),
            None,
        )
        is_vwzio_0500_0504 = vwzio is not None
        # HMU-only layouts on HMUX0: the brine source-temperature probe is
        # always incompatible with air/water HMUX0. Status00 remains gated to
        # the confirmed 0303/0504 variant, while the B509 monitoring block is
        # evidence-gated for 0302/0504 and 0303/0504. Shared B516 statistics
        # remain available for every discovered HMUX0.
        if hmux0_owner is not None:
            hmu_only_layouts = {"SourceTempInput"}
            if not is_hmux0_0303_0504:
                hmu_only_layouts.add("Status00")
            if not is_hmux0_b509_0504:
                hmu_only_layouts.add("RunDataElPowerConsumption")
            defines = [
                definition
                for definition in defines
                if not (
                    is_heat_pump_circuit(definition.split(",", 3)[1])
                    and definition.split(",", 3)[2] in hmu_only_layouts
                )
            ]

        # Intent: compile each logical runtime definition against its discovered owner.
        # Why: definitions must never be sent to a guessed physical circuit.
        def _resolve_definition_circuit(definition: str) -> str | None:
            parts = definition.split(",", 3)
            if len(parts) < 3 or not self._graph:
                return definition
            if (
                hmux0_sw0407_owner
                and parts[1].casefold() == hmux0_sw0407_owner.casefold()
                and parts[2] in HMUX0_SW0407_ENVYIELD_REGISTERS
            ):
                return definition
            resolution = (
                self._graph.heating_controller_result()
                if is_controller_circuit(parts[1])
                else self._graph.heat_pump_result()
                if is_heat_pump_circuit(parts[1])
                else self._graph.resolve_circuit_result(parts[1])
            )
            if resolution.status != ResolutionStatus.UNIQUE:
                return None
            resolved = resolution.circuit or parts[1]
            if (
                parts[0] == "r"
                and parts[2].casefold() == "status01"
                and parts[1].casefold() in {"vwz", "vwzio"}
                and (
                    (station_circuit := vwz_station_scan_76_circuit(self._graph)) is None
                    or resolved.casefold() != station_circuit.casefold()
                )
            ):
                return None
            if resolved == parts[1]:
                return definition
            parts[1] = resolved
            return ",".join(parts)

        # B524 Hc1/Hc2 state reads stay metadata-only until a hardware-scoped capture proves safe polling.
        controller_node = self._graph.heating_controller_result().node if self._graph is not None else None

        # BAS*/BASS* heating controllers (e.g. `Vaillant;BASS3;0708;4304`)
        # expose the zone-1 day setpoint at sub-address 0x22, not the 0x07 slot
        # the shipped `15.700`-lineage CSV poll uses. On this family the 0x07
        # read returns `ERR: invalid position` while 0x22 decodes a live value
        # (upstream issue #646 BASS0 live read, #522 "0700 -> 2200", #1063 root
        # cause; community fixtures for ctlv0/ctlv3 confirm 0x22). Both read and
        # write definitions are overridden because the shipped write path still
        # targets 0x07. Hardware-gated so ctlv2/ctlv3 (where 0x07 works) remain
        # unaffected.
        if controller_node and controller_node.scan_type.upper().startswith("BAS"):
            circuit = controller_node.circuit
            defines.append(
                f"r5,{circuit},Z1DayTemp,Z1DayTemp,31,15,B524,020003002200"
                ",ign,,IGN:4,,,,value,,EXP,,°C,day setpoint for zone 1"
            )
            defines.append(
                f"wi,{circuit},Z1DayTemp,Z1DayTemp,31,15,B524,020103002200,value,m,EXP,,°C,day setpoint for zone 1"
            )
            # Upstream issue #522 documents the same 0x07 -> 0x22 move for
            # Z1..Z3 on BASV3. Enable Zone 2 only when its room-temperature
            # register has a live value; inactive placeholder zones stay out
            # of active polling. This is a reasonable, fixture-backed
            # assumption for the BASS3 scope captured in issue #129.
            if any(key.casefold() == f"{circuit}.Z2RoomTemp".casefold() for key in self._graph.raw_registers):
                defines.extend(
                    [
                        f"r5,{circuit},Z2DayTemp,Z2DayTemp,31,15,B524,020003012200"
                        ",ign,,IGN:4,,,,value,,EXP,,°C,day setpoint for zone 2",
                        f"wi,{circuit},Z2DayTemp,Z2DayTemp,31,15,B524,020103012200"
                        ",value,m,EXP,,°C,day setpoint for zone 2",
                    ]
                )

        defines = [definition for definition in (_resolve_definition_circuit(item) for item in defines) if definition]
        if is_hmux0_0303_0504:
            circuit = hmux0_sw0303_circuit
            assert circuit is not None
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
        if is_hmux0_b509_0504:
            assert heat_pump is not None
            circuit = heat_pump.circuit
            defines.extend(
                [
                    f"r,{circuit},RunDataCompressorSpeed,RunDataCompressorSpeed,31,08,B509,055402000d0a"
                    ",value,,IGN:4,,,,value,,EXP,,rps,HMUX0 compressor speed",
                    f"r,{circuit},RunDataBuildingCPumpPower,RunDataBuildingCPumpPower,31,08,B509,05540200c509"
                    ",value,,IGN:4,,,,value,,EXP,,%,HMUX0 building circuit pump power",
                ]
            )
        if hmux0_sw0407_owner is not None:
            defines.extend(
                f"u,{hmux0_sw0407_owner},{name},{name},f1,08,{message_id},{subaddress},{fields}"
                for name, message_id, subaddress, fields in HMUX0_SW0407_PASSIVE_REGISTERS
            )
        if is_vwzio_0500_0504 and vwzio is not None:
            # The dump captures the gateway's passive B516/14 station-power frame.
            # Unlike PR #598's later SW0901 active read, this definition only decodes observed traffic.
            defines.append(
                f"u,{vwzio.circuit},PowerConsumptionVwz,PowerConsumptionVwz,f1,76,B516,14"
                ",value,,IGN:1,,,,value,,EXP,1000,kW,Hydraulic station power consumption"
            )
            # Intent: decode the captured DHW backup-heater runtime/start counters without polling.
            # Why: issue #161 correlates the HW0504 delta to two runs; absent data must stay unavailable.
            defines.append(
                f"u,{vwzio.circuit},RunStatsImmersionHeaterHwc,RunStatsImmersionHeaterHwc,f1,76,B511,021802"
                ",ign,,IGN:1,,,,runtime,,ULG,,min,,cycles,,ULG"
            )
            # Status01's active field layout is documented for VWZIO HW5103, not this HW0504 scan.
            defines = [
                definition
                for definition in defines
                if not (definition.startswith(("r,vwz,Status01,", "r,vwzio,Status01,")))
            ]
        if not is_hmux0_0303_0504:
            defines = [definition for definition in defines if ",Status00," not in definition]
        if not is_hmux0_b509_0504:
            defines = [
                definition
                for definition in defines
                if not (
                    definition.split(",", 3)[0] == "r" and definition.split(",", 3)[2] == "RunDataElPowerConsumption"
                )
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
            if self._stopped or self._unload_requested:
                return
            access, circuit, name = definition.split(",", 3)[:3]
            key = f"{access}.{circuit}.{name}"
            if self._runtime_definitions.get(key) == definition:
                continue
            try:
                resp = await self.ebus.define_register(definition)
                if self._stopped:
                    return
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

    # Intent: avoid cache I/O and state publication after teardown begins.
    # Why: an in-flight poll may reach this helper after unload is requested.
    async def _async_values_from_registers(self, registers: list[EbusdRegister] | None = None) -> dict[str, str]:
        if self._stopped or self._unload_requested:
            return {}
        values: dict[str, str] = {}
        for reg in registers or list(self.registers.values()):
            for field, value in reg.value.items():
                if value is not None:
                    translated = value
                    if (
                        self.heat_pump_circuit is not None
                        and reg.key.casefold() == f"{self.heat_pump_circuit}.RunDataStatuscode".casefold()
                    ):
                        translated = COMPRESSOR_STATUS_LABELS.get(value, value)
                    for suffix in EBUSD_STATUS_SUFFIXES:
                        if translated.endswith(suffix):
                            translated = translated[: -len(suffix)]
                            break
                    values[f"{reg.circuit}.{reg.name}.{field}"] = translated
        if self._stopped or self._unload_requested:
            return {}
        await self._async_save_cache(values)
        if self._stopped or self._unload_requested:
            return {}
        return values

    @property
    def _cache_path(self) -> str:
        return self.hass.config.path(DOMAIN, "register_cache.json")

    def _yaml_overrides_path(self) -> str:
        """Path of the optional user-facing entity metadata override file."""
        return self.hass.config.path(DOMAIN, "entities.yaml")

    @property
    def _energy_counter_divisor(self) -> float:
        """Global energy-counter scale (divisor) from the Options Flow.

        Defaults to 1.0 (identity), so existing installations see no change.
        The reported value is divided by this factor for the Wh-declared b516
        energy counters; a local ebusd definition that already scales a counter
        (e.g. reports kWh on a Wh register) can be corrected once for the whole
        installation by setting the divisor below/above 1.0 (issue #141).
        """
        options = self._entry.options if hasattr(self._entry, "options") else {}
        raw = options.get(CONF_ENERGY_DIVISOR, DEFAULT_ENERGY_DIVISOR)
        try:
            value = float(raw)
        except TypeError:
            return DEFAULT_ENERGY_DIVISOR
        except ValueError:
            return DEFAULT_ENERGY_DIVISOR
        return value if value > 0 else DEFAULT_ENERGY_DIVISOR

    async def _async_load_yaml_overrides(self) -> dict[str, dict[str, object]]:
        """Load ``config/vaillant_ebus/entities.yaml`` metadata overrides.

        The file is optional; a missing or invalid file yields an empty mapping
        (with a warning for invalid YAML) so discovery and entity generation
        always proceed. Keys are ``<circuit>.<name>`` register keys, values are
        the metadata keys documented in ``docs/setup.md``.
        """
        overrides: dict[str, dict[str, object]] = {}
        path = self._yaml_overrides_path()
        if await self.hass.async_add_executor_job(os.path.isfile, path):

            def _read() -> object:
                with open(path, encoding="utf-8") as handle:
                    return yaml.safe_load(handle)

            try:
                raw = await self.hass.async_add_executor_job(_read)
            except Exception as exc:  # noqa: BLE001 - surface invalid YAML safely
                _LOGGER.warning("Unable to load %s: %s", path, exc)
                raw = None

            if raw is not None and not isinstance(raw, dict):
                _LOGGER.warning("%s must be a mapping; ignoring invalid overrides", path)
                raw = None
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if isinstance(key, str) and isinstance(value, dict):
                        overrides[key] = dict(value)

        # Apply Options Flow settings even when the optional YAML file is absent
        # or invalid; the global setting must not depend on a second config file.
        self._apply_global_energy_divisor(overrides)
        return overrides

    # Wh-declared energy counters that carry a scalar accumulation and may be
    # scaled differently by local ebusd definitions (issue #141). When the
    # global energy-counter divisor differs from 1.0, the reported value is
    # divided by it here unless the user's entities.yaml already sets an
    # explicit per-register divisor.
    _ENERGY_DIVISOR_REGISTERS = (
        "CoolEnvYieldTotal",
        "CoolEnvYieldDay",
        "CoolEnvYieldMonth",
        "CoolElecConsTotal",
        "CoolElecConsDay",
        "HcElecConsTotal",
        "HcElecConsDay",
        "HwcElecConsTotal",
        "HwcElecConsDay",
    )

    def _apply_global_energy_divisor(self, overrides: dict[str, dict[str, object]]) -> None:
        divisor = self._energy_counter_divisor
        if divisor == 1.0:
            return
        # The b516/runtime energy counters live on the discovered heat-pump circuit.
        # This is only a metadata override namespace; it is not a bus target.
        circuit = self.heat_pump_circuit or "hmu"
        for name in self._ENERGY_DIVISOR_REGISTERS:
            key = f"{circuit}.{name}"
            entry = overrides.setdefault(key, {})
            if "divisor" not in entry:
                entry["divisor"] = divisor

    # Intent: commit register-cache updates only while the coordinator is active.
    # Why: a late executor write can overwrite cache data from a reloaded coordinator.
    async def _async_save_cache(self, values: dict[str, str]) -> None:
        if self._stopped or self._unload_requested:
            return
        cache_path = self._cache_path
        cache_dir = os.path.dirname(cache_path)
        staged_path: str | None = None
        try:
            os.makedirs(cache_dir, exist_ok=True)
            write_future = asyncio.ensure_future(
                self.hass.async_add_executor_job(_write_cache_temp, cache_path, values)
            )
            try:
                try:
                    staged_path = await asyncio.shield(write_future)
                except asyncio.CancelledError:
                    write_future.add_done_callback(_discard_cancelled_cache_write)
                    raise
                if self._stopped or self._unload_requested:
                    return
                os.replace(staged_path, cache_path)
            finally:
                if staged_path is not None and os.path.exists(staged_path):
                    try:
                        os.unlink(staged_path)
                    except FileNotFoundError:
                        pass
        except Exception:
            # Log the path and failure class only — never cache values.
            _LOGGER.warning("Failed to save register cache to %s", cache_path, exc_info=True)

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

    # Whether a circuit is present in the current discovery graph. Used to
    # decide whether a Home Assistant device is still provided by the
    # integration (and may not be deleted) or is a stale ghost.
    def has_discovered_circuit(self, circuit: str) -> bool:
        return self._graph is not None and any(key.casefold() == circuit.casefold() for key in self._graph.nodes)

    # Name the logical DHW device after the hardware that owns it: a heat pump
    # has a hot-water cylinder, not a boiler. Boiler-only and unresolved buses
    # keep the historical "Boiler (DHW)" name for stability.
    def _dhw_device_name(self) -> str:
        if self._graph is not None and self._graph.heat_pump_result().status == ResolutionStatus.UNIQUE:
            return "Domestic Hot Water"
        return CIRCUIT_NAMES.get("dhw", "Boiler (DHW)")

    def get_device_info(self, circuit: str) -> DeviceInfo:
        scan_type = ""
        scan_sw = ""
        scan_hw = ""
        parent: str | None = None
        node: DeviceNode | None = None

        if self._graph is not None:
            node = next(
                (candidate for key, candidate in self._graph.nodes.items() if key.casefold() == circuit.casefold()),
                None,
            )

        if node:
            scan_type = node.scan_type
            scan_sw = node.scan_sw
            scan_hw = node.scan_hw
            parent = node.parent

        circuit_lower = circuit.lower()
        if node is not None and node.device_type == DeviceType.HEAT_PUMP:
            name, manufacturer = heat_pump_product(self._graph)
            if not name:
                name = CIRCUIT_NAMES.get("hmu", "Vaillant heat pump")
                manufacturer = "Vaillant"
        elif circuit_lower == "dhw":
            name = self._dhw_device_name()
            manufacturer = "Vaillant"
        elif circuit_lower in CIRCUIT_NAMES:
            name = CIRCUIT_NAMES[circuit_lower]
            manufacturer = "Vaillant"
        elif len(circuit_lower) == 5 and circuit_lower.startswith("ctlv") and circuit_lower[-1].isdigit():
            name = "Vaillant sensoCOMFORT Control"
            manufacturer = "Vaillant"
        elif scan_type:
            name = f"Vaillant {scan_type}"
            manufacturer = "Vaillant"
        elif circuit_lower.startswith("z"):
            name = f"Zone {circuit[1:]}"
            manufacturer = "Vaillant"
        elif circuit_lower.startswith("hc"):
            name = f"Heating Circuit {circuit[2:]}"
            manufacturer = "Vaillant"
        else:
            name = f"Vaillant {circuit}"
            manufacturer = "Vaillant"

        ebusd_version = self.ebus.version if self.ebus else None
        info = DeviceInfo(
            identifiers={(DOMAIN, circuit)},
            name=name,
            manufacturer=manufacturer,
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
        if self._graph is not None:
            keys = list(self._graph.raw_registers) + list(self._graph.placeholder_registers)
            candidates = list(
                dict.fromkeys(
                    circuit
                    for circuit in (rk.split(".", 1)[0] for rk in keys if rk.casefold().endswith(f".{name}".casefold()))
                    if expected_type is None
                    or (
                        next(
                            (
                                node
                                for node_key, node in self._graph.nodes.items()
                                if node_key.casefold() == circuit.casefold()
                            ),
                            None,
                        )
                        is not None
                        and next(
                            node
                            for node_key, node in self._graph.nodes.items()
                            if node_key.casefold() == circuit.casefold()
                        ).device_type
                        == expected_type
                    )
                )
            )
        resolved = self.resolve_register_circuit(logical_circuit)
        if resolved is not None:
            return next((candidate for candidate in candidates if candidate.casefold() == resolved.casefold()), None)
        if expected_type is None and len(candidates) == 1:
            return candidates[0]
        return None

    # Intent: read only mapped registers that are safe for active fallback polling.
    # Why: fallback probes must not bypass per-register polling restrictions.
    async def _fallback_read(
        self,
        include_placeholders: bool = False,
        include_energy: bool = False,
        skip_cache: set[str] | None = None,
        skip_reads: set[str] | None = None,
    ) -> None:
        if not self.ebus or not self.ebus.is_connected or self._graph is None:
            return
        # Intent: do not let a retained graph authorize polls after an unusable find.
        # Why: its circuit ownership may no longer match the devices currently on the bus.
        if getattr(self.ebus, "last_find_usable", None) is False:
            return
        graph_keys = self._last_find_keys

        # Intent: resolve metadata for a discovered source circuit without changing its owner.
        # Why: family metadata is presentation compatibility, not bus routing.
        def _meta_key(circuit: str, name: str) -> str | None:
            for alt in metadata_circuits(circuit):
                key = f"{alt}.{name}"
                if any(map_key.casefold() == key.casefold() for map_key in REGISTER_MAP):
                    return next(map_key for map_key in REGISTER_MAP if map_key.casefold() == key.casefold())
            return None

        candidates: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        skipped_read_keys = {key.casefold() for key in (skip_reads or set())}
        skipped_read_keys.update(key.casefold() for key in self._graph.error_registers)
        passive_register_keys = {
            (parts[1].casefold(), parts[2].casefold())
            for definition in self._runtime_definitions.values()
            if len(parts := definition.split(",", 3)) >= 3 and parts[0].startswith("u")
        }
        hmux0_blocked_circuits = {circuit.casefold() for circuit in hmux0_fallback_blocked_circuits(self._graph)}
        hmux0_candidates = {circuit.casefold() for circuit in hmux0_candidate_circuits(self._graph)}
        hmux0_sw0303 = hmux0_sw0303_owner(self._graph)
        vwzio_sw0500 = vwzio_sw0500_circuit(self._graph)
        vwz_station_76 = vwz_station_scan_76_circuit(self._graph)

        # Intent: add each resolved fallback candidate once.
        # Why: map, passive-definition, and placeholder paths can nominate the same register.
        def _add(circuit: str, name: str) -> None:
            circuit_key = circuit.casefold()
            name_key = name.casefold()
            if "." in name or f"{circuit}.{name}".casefold() in skipped_read_keys:
                return
            if (circuit_key, name_key) in passive_register_keys:
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
            if circuit_key in hmux0_blocked_circuits and name_key in HMUX0_SW0407_FALLBACK_NAMES:
                return
            if name_key == "rundatareturntemp" and circuit_key in hmux0_candidates:
                if hmux0_sw0303 is None or circuit_key != hmux0_sw0303.casefold():
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

        # Plain-r B516 definitions are not polled by ebusd. Re-read supported
        # counters even after find has cached their first value (#53/#97).
        if include_energy and self._graph:
            for definition in self._runtime_definitions.values():
                access, circuit, name, _, _, _, message = definition.split(",", 7)[:7]
                if (
                    access == "r"
                    and message == "B516"
                    and any(node_key.casefold() == circuit.casefold() for node_key in self._graph.nodes)
                ):
                    _add(circuit, name)

        # Map-driven reads: registers with metadata not yet in the graph.
        graph_key_folds = {key.casefold() for key in graph_keys}
        for key in REGISTER_MAP:
            meta = REGISTER_MAP[key]
            if not meta.enabled or not meta.fallback_read or key.casefold() in graph_key_folds:
                continue
            map_circuit, name = key.split(".", 1)
            if is_field_key(key):
                continue
            candidate_circuit = self._fallback_candidate(map_circuit, name)
            if (
                candidate_circuit is None
                and self._graph
                and any(
                    rk.casefold().endswith(f".{name}".casefold())
                    for rk in (*self._graph.raw_registers, *self._graph.placeholder_registers)
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
                if "." in name or key.casefold() in skipped_read_keys:
                    continue
                if key.casefold() in {raw_key.casefold() for raw_key in self._graph.raw_registers}:
                    continue
                meta_key = _meta_key(circuit, name)
                if meta_key:
                    meta = next(
                        (value for map_key, value in REGISTER_MAP.items() if map_key.casefold() == meta_key.casefold()),
                        None,
                    )
                else:
                    meta = None
                if meta and meta.enabled and meta.fallback_read:
                    resolved = self._fallback_candidate(circuit, name)
                    if resolved is not None:
                        _add(resolved, name)

        if not candidates:
            return
        _LOGGER.info("Fallback reading %d known register(s)", len(candidates))
        added = 0
        read_with_data = 0
        for circuit, name in candidates:
            if self._stopped or self._unload_requested:
                return
            key = f"{circuit}.{name}"
            register_key = _mapping_key(self.registers, key) or key
            try:
                value = await self.ebus.read_register(circuit, name, raise_transport_errors=True)
                if self._stopped or self._unload_requested:
                    return
                was_new = register_key not in self.registers
                value = _usable_register_value(register_key, value)
                if value and (value.startswith("or:") or "read [-" in value):
                    value = None
                if value is None:
                    # Never resurrect a stale value for a register the bus no
                    # longer exposes: the issue #99 clearing reports "no data
                    # stored" as unknown, so the cache may only back a value for
                    # a register the discovery graph still configures (currently
                    # idle) or before a graph exists (startup/cache seeding).
                    graph = self._graph
                    if graph is None or any(raw_key.casefold() == key.casefold() for raw_key in graph.raw_registers):
                        cache = await self._async_load_cache()
                        if self._stopped or self._unload_requested:
                            return
                        cache_key = f"{circuit}.{name}.value"
                        cached = next(
                            (
                                cached_value
                                for cached_name, cached_value in cache.items()
                                if cached_name.casefold() == cache_key.casefold()
                            ),
                            None,
                        )
                        cached = _usable_register_value(register_key, cached)
                        skipped = {item.casefold() for item in (skip_cache or set())}
                        if cached is not None and key.casefold() not in skipped:
                            value = cached
                if value is None:
                    register = self.registers.get(register_key)
                    current_value = register.value.get("value") if register is not None else None
                    is_empty_marker = isinstance(current_value, str) and current_value.strip().lower().startswith(
                        "(empty"
                    )
                    if (
                        register is not None
                        and (
                            graph is None
                            or not any(raw_key.casefold() == key.casefold() for raw_key in graph.raw_registers)
                        )
                        and not is_empty_marker
                    ):
                        register.value = _register_values(register_key, None)
                        register.has_data = False
                    continue
                if value is not None:
                    read_with_data += 1
                    if was_new:
                        self.registers[register_key] = EbusdRegister(
                            circuit=circuit,
                            name=name,
                            fields=["value"],
                            value=_register_values(register_key, value),
                            has_data=True,
                        )
                        added += 1
                    else:
                        self.registers[register_key].value.update(_register_values(register_key, value))
                        self.registers[register_key].has_data = True
                    _LOGGER.debug("Fallback read %s = %s", key, value)
            except ConnectionError, TimeoutError, OSError:
                raise
            except Exception as exc:
                _LOGGER.warning("Fallback read failed: %s (%s)", key, exc)
        if self._stopped or self._unload_requested:
            return
        if self._graph is not None:
            graph = self._graph
            graph_additions = [
                (key, register)
                for key, register in self.registers.items()
                if register.has_data and key not in graph.raw_registers and register.circuit in graph.nodes
            ]
            if graph_additions:
                yaml_overrides = await self._async_load_yaml_overrides()
                if self._stopped or self._unload_requested:
                    return
                graph = self._graph
                if graph is None:
                    return
                graph_additions = [
                    (key, register)
                    for key, register in self.registers.items()
                    if register.has_data and key not in graph.raw_registers and register.circuit in graph.nodes
                ]
                for key, register in graph_additions:
                    node = graph.nodes[register.circuit]
                    graph.raw_registers[key] = register.value.get("value") or ""
                    if key not in node.registers:
                        node.registers.append(key)
                    node.has_data = True
                    self._last_find_keys.add(key)
                if graph_additions:
                    _LOGGER.info("Fallback read added %d register(s) to discovery", len(graph_additions))
                    generated = self.entity_factory.generate(graph, yaml_overrides=yaml_overrides)
                    if self._stopped or self._unload_requested:
                        return
                    known = {(entity.entity_type, entity.unique_id) for entity in self.entities}
                    additions = [entity for entity in generated if (entity.entity_type, entity.unique_id) not in known]
                    self.entities = _merge_entities(self.entities, generated)
                    self._add_new_entities(additions)
                    await self._enable_registry_entities(list(graph.raw_registers))
                    if self._stopped or self._unload_requested:
                        return
        _LOGGER.info(
            "Fallback read complete: %d/%d registers with data (%d new)", read_with_data, len(candidates), added
        )

    # Intent: refresh register data and recover disconnected ebusd sessions.
    # Why: failed reconnects must retry, and repairs clear only after a valid poll cycle.
    async def _async_update_data(self) -> CoordinatorState:
        if self._stopped or self._unload_requested:
            return {"ebusd": {}}
        if not self._cache_seeded:
            await self._async_seed_entities_from_cache()
            if self._stopped or self._unload_requested:
                return {"ebusd": {}}
            self._cache_seeded = True

        if self._ebusd_connected and (self.ebus is None or not self.ebus.is_connected):
            await self._async_mark_ebusd_unreachable("ebusd transport closed between coordinator polls")
            if self._stopped or self._unload_requested:
                return {"ebusd": {}}

        if not self._ebusd_connected:
            if self._setup_task is not None:
                if not self._setup_task.done():
                    return {"ebusd": await self._async_values_from_registers()}
                setup_task = self._setup_task
                self._setup_task = None
                setup_failed = setup_task.cancelled()
                if not setup_failed:
                    setup_error = setup_task.exception()
                    if setup_error is not None:
                        _LOGGER.error("ebusd setup task failed unexpectedly: %s", setup_error)
                        setup_failed = True
                if setup_failed or not self._ebusd_connected:
                    self._started = False
            if not self._started:
                self._started = True
                if not self._unload_requested:
                    self._setup_task = self.hass.async_create_task(self._async_run_setup_task())
            return {"ebusd": await self._async_values_from_registers()}

        if self.ebus and self.ebus.is_connected:
            try:
                now = datetime.now()
                poll_energy = now - self._last_energy_poll >= ENERGY_POLL_INTERVAL
                lines = await self.ebus.find_registers()
                if self._stopped or self._unload_requested:
                    return {"ebusd": await self._async_values_from_registers()}
                if getattr(self.ebus, "last_find_usable", None) is False:
                    _LOGGER.warning("ebusd find returned no usable rows; keeping the current graph topology")
                    error_registers: set[str] = set()
                    for line in lines:
                        circuit, name, value = DiscoveryService._parse_register(line)
                        if not circuit or not name or value is not None or "." in name:
                            continue
                        raw_value = line.partition("=")[2]
                        if not is_ebusd_error_value(raw_value):
                            continue
                        source_key = f"{circuit}.{name}"
                        register_key = _mapping_key(self.registers, source_key) or source_key
                        error_registers.update((source_key, register_key))
                        register = self.registers.get(register_key)
                        if register is not None:
                            register.value = _register_values(register_key, None)
                            register.has_data = False
                    if self._graph is not None:
                        self._graph.error_registers = error_registers
                    return {"ebusd": await self._async_values_from_registers()}
                await self._refresh_graph_from_usable_find(lines)
                if self._stopped or self._unload_requested or not self.ebus or not self.ebus.is_connected:
                    return {"ebusd": await self._async_values_from_registers()}
                if not self._ebusd_connected and self.discovery_ready:
                    self._ebusd_connected = True
                if poll_energy:
                    previous_definitions = self._runtime_definitions.copy()
                    await self._define_custom_registers()
                    if self._stopped or self._unload_requested:
                        return {"ebusd": await self._async_values_from_registers()}
                    if self._runtime_definitions != previous_definitions:
                        lines = await self.ebus.find_registers()
                        if self._stopped or self._unload_requested:
                            return {"ebusd": await self._async_values_from_registers()}
                        if getattr(self.ebus, "last_find_usable", None) is False:
                            _LOGGER.warning(
                                "Post-definition ebusd find returned no usable rows; skipping active fallback reads"
                            )
                            return {"ebusd": await self._async_values_from_registers()}
                        await self._refresh_graph_from_usable_find(lines)
                        if self._stopped or self._unload_requested or not self.ebus or not self.ebus.is_connected:
                            return {"ebusd": await self._async_values_from_registers()}
                updated = 0
                invalid_values: set[str] = set()
                no_data_values: set[str] = set()
                error_values: set[str] = set()
                batch_with_data: set[str] = set()
                for line in lines:
                    # Shared parser: sentinel/no-data values come back as None.
                    circuit, name, val = DiscoveryService._parse_register(line)
                    if not circuit or not name:
                        continue
                    source_key = f"{circuit}.{name}"
                    if "." in name:
                        continue
                    key = source_key
                    key = _mapping_key(self.registers, key) or key
                    if val is None:
                        no_data_values.add(key)
                        if is_ebusd_error_value(line.partition("=")[2]) and key not in batch_with_data:
                            error_values.update((source_key, key))
                        if key.lower() == "hmux0.rundatareturntemp":
                            raw = line.split("=", 1)[1].strip()
                            if not is_no_data_value(raw):
                                invalid_values.add(key)
                        # The DHW storage-temp register can return an explicit
                        # empty/NaN sentinel ("(empty ...7fffffff)") that means a
                        # cylinder is NOT connected. That is a meaningful value,
                        # not generic "no data", so keep it through to the
                        # tank-presence sensor instead of collapsing it to None.
                        # Only is_no_data_value-known sentinels that are NOT the
                        # empty-NaN marker stay generic no-data.
                        elif name.lower() == "hwcstoragetemp":
                            raw = line.split("=", 1)[1].strip()
                            is_empty_marker = raw.strip().lower().startswith("(empty")
                            if is_empty_marker and key not in batch_with_data:
                                self.registers.setdefault(
                                    key,
                                    EbusdRegister(
                                        circuit=circuit,
                                        name=name,
                                        fields=["value"],
                                        value=_register_values(key, raw.strip()),
                                        has_data=False,
                                    ),
                                ).value.update(_register_values(key, raw.strip()))
                                # Guard against a later stale "no data stored"
                                # double-line in the same batch wiping this
                                # explicit marker: treat it as "has data" for
                                # this pass like a readable value.
                                batch_with_data.add(key)
                                continue
                        # A register that no longer carries data must not keep
                        # emitting its last value, otherwise the entity freezes
                        # at a stale reading (issue #99). But ebusd's `find -a`
                        # lists some registers twice — a readable definition and
                        # a stale one reporting "no data stored". When this batch
                        # already carried a readable value for the key, the stale
                        # line must not wipe it.
                        if key not in batch_with_data and key in self.registers:
                            # Clear every field, not just the synthetic `value`:
                            # a multi-field register (e.g. hmu Status01) stores
                            # its named fields separately, and leaving them set
                            # would keep the per-field sensors frozen at their
                            # last decode (issue #99/#102).
                            self.registers[key].value = _register_values(key, None)
                        continue
                    val = _usable_register_value(key, val)
                    if val is None:
                        continue
                    error_values.discard(source_key)
                    error_values.discard(key)
                    self._live_since_analysis.add(key)
                    batch_with_data.add(key)
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
                self._refresh_find_keys()
                if self._graph is not None:
                    self._graph.error_registers = error_values
                poll_placeholders = now - self._last_placeholder_poll >= PLACEHOLDER_POLL_INTERVAL
                if poll_placeholders:
                    self._last_placeholder_poll = now
                await self._fallback_read(
                    include_placeholders=poll_placeholders,
                    include_energy=poll_energy,
                    skip_cache=invalid_values | no_data_values,
                    skip_reads=error_values,
                )
                if self._stopped or self._unload_requested:
                    return {"ebusd": await self._async_values_from_registers()}
                self._disable_no_data_registry_entities(self.entities)
                if poll_energy:
                    self._last_energy_poll = now
                heat_pump_circuit = self.heat_pump_circuit
                if heat_pump_circuit is not None:
                    zero_idle_registers(self.registers, heat_pump_circuit)
                if self._ebusd_repair_pending and self.discovery_ready:
                    await repairs.async_dismiss_ebusd_unreachable(self.hass)
                    if self._stopped or self._unload_requested:
                        return {"ebusd": {}}
                    self._ebusd_repair_pending = False
                if updated:
                    _LOGGER.info("Poll updated %d registers", updated)
                return {"ebusd": await self._async_values_from_registers()}
            except ConnectionError, TimeoutError, OSError:
                if self._stopped or self._unload_requested:
                    return {"ebusd": await self._async_values_from_registers()}
                _LOGGER.warning("ebusd connection lost, reconnecting")
                self._ebusd_repair_pending = True
                try:
                    # Only dismiss the repair issue when this call actually
                    # dialed; a skipped single-flight reconnect proves nothing.
                    reconnected = await self.ebus._reconnect() if self.ebus else False
                    if self._stopped or self._unload_requested:
                        return {"ebusd": await self._async_values_from_registers()}
                    if reconnected:
                        self._runtime_definitions.clear()
                        self._last_energy_poll = datetime.min
                        ebus = self.ebus
                        if ebus:
                            await ebus.disconnect()
                        self.ebus = None
                        self.discovery = None
                        await self._async_mark_ebusd_unreachable("transport restored; fresh discovery is required")
                except Exception as exc:
                    _LOGGER.error("ebusd reconnect failed: %s", exc)
                    reconnected = False
                if not reconnected:
                    await self._async_mark_ebusd_unreachable("transport reconnect failed")

        return {"ebusd": await self._async_values_from_registers()}

    # Write one or more registers through the central write path. Each write is
    # verified by read-back. Sequences are dependent: stop at the first failure
    # instead of writing later registers on a broken assumption; refresh only
    # after full success. Already-written registers are reported, not rolled back.
    # Keep the most recent write attempts for the discovery dump's `writes`
    # section. Bounded ring buffer; never raises — diagnostics must not break
    # the write path.
    def _record_write(
        self, circuit: str, name: str, value: str, resolved_circuit: str | None, success: bool, error: str | None = None
    ) -> None:
        try:
            self._write_log.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "circuit": circuit,
                    "name": name,
                    "value": str(value),
                    "resolved_circuit": resolved_circuit,
                    "success": bool(success),
                    "error": error,
                }
            )
        except Exception:
            return
        if len(self._write_log) > WRITE_LOG_SIZE:
            del self._write_log[: len(self._write_log) - WRITE_LOG_SIZE]

    # Intent: verify a write target remains present in the authoritative graph.
    # Why: entities can outlive a partial reconnect and must fail closed before any batch write.
    def _graph_has_register(self, circuit: str, name: str) -> bool:
        if self._graph is None:
            return False
        expected = f"{circuit}.{name}".casefold()
        return any(
            key.casefold() == expected for key in (*self._graph.raw_registers, *self._graph.placeholder_registers)
        )

    # Intent: write only through an authoritative discovered register owner.
    # Why: service calls during setup must not target cached or assumed circuits.
    async def async_write_registers(
        self,
        writes: list[tuple[str, str, str]],
        strict_verify: bool = True,
        refresh: bool = True,
        require_discovered: bool = True,
    ) -> bool:
        if (
            self._stopped
            or self._unload_requested
            or not self.ebus
            or not self.ebus.is_connected
            or not self.discovery_ready
        ):
            return False
        if require_discovered:
            for circuit, name, value in writes:
                resolved_circuit = self.resolve_register_circuit(circuit)
                mapped = any(
                    any(map_key.casefold() == f"{alias}.{name}".casefold() for map_key in REGISTER_MAP)
                    for alias in metadata_circuits(circuit)
                )
                if mapped and (resolved_circuit is None or not self._graph_has_register(resolved_circuit, name)):
                    self._record_write(circuit, name, value, resolved_circuit, False, "register not discovered")
                    return False
        for circuit, name, value in writes:
            resolved_circuit = self.resolve_register_circuit(circuit)
            if resolved_circuit is None:
                _LOGGER.warning("Write skipped: ambiguous discovered circuit for %s.%s", circuit, name)
                self._record_write(circuit, name, value, None, False, "ambiguous discovered circuit")
                return False
            result = await self.ebus.write_register(resolved_circuit, name, value, strict_verify=strict_verify)
            if not result.success:
                _LOGGER.warning("Write failed %s.%s=%s: %s", circuit, name, value, result.error_message)
                self._record_write(circuit, name, value, resolved_circuit, False, result.error_message)
                return False
            self._record_write(circuit, name, value, resolved_circuit, True)
            if self._stopped or self._unload_requested or not self.ebus or not self.ebus.is_connected:
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
        require_discovered: bool = True,
    ) -> bool:
        return await self.async_write_registers(
            [(circuit, name, value)],
            strict_verify=strict_verify,
            refresh=refresh,
            require_discovered=require_discovered,
        )

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
        ok = await self.async_write_register(
            "bai", "SetModeOverride", payload, strict_verify=False, require_discovered=False
        )
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

    # Intent: stop polling, scheduled work, and the active ebusd session.
    # Why: a successfully unloaded config entry must not retain transport or callbacks.
    async def async_stop(self) -> None:
        self._stopped = True
        self._ebusd_connected = False
        self._started = False
        self._post_discovery_callbacks.clear()
        self.entity_adders.clear()
        self.async_clear_mode_override()
        if self._cancel_delayed_rediscovery:
            self._cancel_delayed_rediscovery()
            self._cancel_delayed_rediscovery = None
        if self._cancel_analysis:
            self._cancel_analysis()
            self._cancel_analysis = None
        current_task = asyncio.current_task()
        dump_tasks = tuple(task for task in self._active_dump_tasks if task is not current_task)
        for task in dump_tasks:
            if not task.done() and task.cancelling() == 0:
                task.cancel()
        if dump_tasks:
            await asyncio.gather(*dump_tasks, return_exceptions=True)
        setup_task = self._setup_task
        if setup_task is not None:
            if not setup_task.done():
                setup_task.cancel()
            try:
                await setup_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                _LOGGER.warning("ebusd setup task failed during stop: %s", exc)
            self._setup_task = None
        clients = [self._pending_ebus]
        if self.ebus is not self._pending_ebus:
            clients.append(self.ebus)
        for ebus in clients:
            if ebus is None:
                continue
            request_shutdown = getattr(ebus, "request_shutdown", None)
            if request_shutdown is not None:
                request_shutdown()
            await ebus.disconnect()
        self._pending_ebus = None
        self.ebus = None
        self.discovery = None

    # Intent: block transport reconnects while Home Assistant unloads platforms.
    # Why: platform teardown may await while a failed poll is sleeping before reconnect.
    def request_unload(self) -> None:
        self._unload_requested = True
        self._started = False
        current_task = asyncio.current_task()
        for task in tuple(self._active_dump_tasks):
            if task is not current_task and not task.done() and task.cancelling() == 0:
                task.cancel()
        for ebus in (self.ebus, self._pending_ebus):
            if ebus is None:
                continue
            request_shutdown = getattr(ebus, "request_shutdown", None)
            if request_shutdown is not None:
                request_shutdown()

    # Intent: restore transport reconnects when platform unload did not complete.
    # Why: HA may retry an unload using the still-loaded coordinator.
    def cancel_unload_request(self) -> None:
        self._unload_requested = False
        self._started = False
        for ebus in (self.ebus, self._pending_ebus):
            if ebus is None:
                continue
            clear_shutdown = getattr(ebus, "clear_shutdown_request", None)
            if clear_shutdown is not None:
                clear_shutdown()
        if not self._stopped and self.ebus and self.ebus.is_connected:
            self._schedule_delayed_rediscovery()
            self._schedule_analysis()
