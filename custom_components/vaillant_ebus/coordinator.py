"""Coordinator for Vaillant eBUS."""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import repairs
from .backend.entity_factory import (
    EntityDescription,
    _detect_active_circuits,
    generate_entity_descriptions,
)
from .backend.mapping import REGISTER_MAP
from .backend.models import CIRCUIT_NAMES, COMPRESSOR_STATUS_LABELS, EbusdRegister, zero_idle_registers
from .backend.tcp import EbusdTcpBackend
from .const import (
    CONF_EBUSD_HOST,
    CONF_EBUSD_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_EBUSD_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

class VaillantCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    # Initialize coordinator with HA instance and config entry
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry

        self.ebusd_backend: EbusdTcpBackend | None = None
        self.registers: dict[str, EbusdRegister] = {}
        self.entities: list[EntityDescription] = []
        self._active_zone_circuits: set[str] = set()
        self._started = False
        self._ebusd_connected = False
        self._heating_circuit = "ctlv2"

        scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

        # Immediately seed entities from REGISTER_MAP + cache (no ebusd needed)
        self._seed_entities_from_cache()

    # Seed register dict + entities from REGISTER_MAP and local cache before ebusd connects
    def _seed_entities_from_cache(self) -> None:
        cache = self._load_cache()
        known_circuits: set[str] = set()
        for key, meta in REGISTER_MAP.items():
            if not meta.enabled:
                continue
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            known_circuits.add(parts[0])
            cached = cache.get(f"{key}.value")
            self.registers[key] = EbusdRegister(
                circuit=parts[0], name=parts[1],
                fields=["value"],
                value={"value": cached} if cached else {"value": None},
                has_data=cached is not None,
            )
        core_circuits: set[str] = {"hmu", self.heating_circuit, "Broadcast"}
        active: set[str] = set(core_circuits)
        for reg in self.registers.values():
            if reg.has_data:
                active.add(reg.circuit)
        self.entities = generate_entity_descriptions(
            list(self.registers.values()),
            active_zone_circuits=known_circuits,
            present_circuits=active,
        )
        _LOGGER.info("Seeded %d entities from REGISTER_MAP + cache (%d circuits present)",
                     len(self.entities), len(active))

    @property
    def ebusd_host(self) -> str:
        return self._entry.data.get(CONF_EBUSD_HOST, "")

    @property
    def ebusd_port(self) -> int:
        return self._entry.data.get(CONF_EBUSD_PORT, 8888)

    # Connect backend, define custom registers, discover all registers
    async def _ebusd_connect_and_discover(self) -> None:
        host = self._entry.data.get(CONF_EBUSD_HOST)
        port = self._entry.data.get(CONF_EBUSD_PORT, 8888)
        if not host:
            return
        _LOGGER.info("Connecting to ebusd at %s:%s", host, port)
        backend = EbusdTcpBackend(host=host, port=port)
        try:
            await backend.async_connect()
        except Exception as exc:
            _LOGGER.warning("ebusd connect failed, will retry: %s", exc)
            return
        self.ebusd_backend = backend
        self._ebusd_connected = True

        version = backend.version
        if version:
            _LOGGER.info("ebusd version: %s", version)
        try:
            await self._define_custom_registers()
        except Exception as exc:
            _LOGGER.warning("define_custom_registers failed: %s", exc)

        try:
            discovered = await backend.async_find()
        except Exception as exc:
            _LOGGER.warning("ebusd find failed: %s", exc)
            return
        self._last_find_keys = {r.key for r in discovered}
        for reg in discovered:
            self.registers[reg.key] = reg
        _LOGGER.info("Found %d registers across %d circuit(s): %s",
                     len(discovered),
                     len({r.circuit for r in discovered}),
                     sorted({r.circuit for r in discovered}))

        cache = self._load_cache()
        for key, meta in REGISTER_MAP.items():
            if key in self.registers or not meta.enabled:
                continue
            cached = cache.get(f"{key}.value")
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            self.registers[key] = EbusdRegister(
                circuit=parts[0], name=parts[1],
                fields=["value"],
                value={"value": cached} if cached else {"value": None},
                has_data=cached is not None,
            )

        try:
            await self._fallback_read()
        except Exception as exc:
            _LOGGER.warning("Initial fallback read failed: %s", exc)

        self._active_zone_circuits = {
            reg.circuit for reg in discovered
            if reg.circuit in {"hc2", "hc3", "z2", "z3"} and reg.has_data
        }
        if self._active_zone_circuits:
            _LOGGER.info("Active zone circuits: %s", self._active_zone_circuits)

        self._parse_scan_metadata()
        self._build_circuit_to_device_id()

        active_present: set[str] = {"hmu", self.heating_circuit, "Broadcast"}
        for reg in self.registers.values():
            if reg.has_data:
                active_present.add(reg.circuit)
        self.entities = generate_entity_descriptions(
            list(self.registers.values()),
            active_zone_circuits=self._active_zone_circuits,
            present_circuits=active_present,
        )
        _LOGGER.info("Generated %d entity descriptions after ebusd discovery", len(self.entities))
        self.async_update_listeners()

    # Define runtime registers (z1RoomHumidity) via ebusd define command
    async def _define_custom_registers(self) -> None:
        if not self.ebusd_backend:
            return
        defines = [
            "r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800"
            ",value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity",
        ]
        for definition in defines:
            try:
                resp = await self.ebusd_backend.async_send_raw(f'define -r "{definition}"')
                _LOGGER.debug("Define %s: %s", definition.split(",")[2], resp)
            except Exception as exc:
                _LOGGER.warning("Failed to define register: %s", exc)

    # Flatten register values into circuit.name.field -> value dict
    def _values_from_registers(
        self, registers: list[EbusdRegister] | None = None
    ) -> dict[str, str]:
        values: dict[str, str] = {}
        for reg in registers or list(self.registers.values()):
            for field, value in reg.value.items():
                if value is not None:
                    translated = value
                    if reg.key == "hmu.RunDataStatuscode":
                        translated = COMPRESSOR_STATUS_LABELS.get(value, value)
                    for suffix in (";ok", ";err", ";inv", ";too_small", ";too_big", ";nan", ";unknown"):
                        if translated.endswith(suffix):
                            translated = translated[:-len(suffix)]
                            break
                    values[f"{reg.circuit}.{reg.name}.{field}"] = translated
        self._save_cache(values)
        return values

    @property
    def _cache_path(self) -> str:
        return self.hass.config.path(DOMAIN, "register_cache.json")

    # Persist register values to JSON cache for fast startup on next HA boot
    def _save_cache(self, values: dict[str, str]) -> None:
        cache_dir = os.path.dirname(self._cache_path)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(self._cache_path, "w") as f:
                json.dump(values, f)
        except Exception:
            pass

    # Load previously cached register values from JSON file
    def _load_cache(self) -> dict[str, str]:
        try:
            with open(self._cache_path) as f:
                return json.load(f)
        except Exception:
            return {}

    # Store device metadata (makes, models, versions) from scan.* registers.
    # Scan registers use circuit names like "Scan.08" (HMU), "Scan.15" (CTLV2), etc.
    def _parse_scan_metadata(self) -> None:
        self._scan_metadata: dict[str, dict[str, str]] = {}
        self._present_devices: set[str] = set()
        for key, reg in self.registers.items():
            if not reg.circuit.lower().startswith("scan"):
                continue
            if "." in reg.circuit:
                device_id = reg.circuit.split(".")[1].lower()
            else:
                device_id = "general"
            value = reg.value.get("value")
            if value is None or value in ("-", "no data stored", ""):
                continue
            val = str(value)
            # Parse model lines: "Vaillant;BASV2;0507;1704" → MF;TYPE;SW;HW
            if not reg.name:
                parts = val.split(";")
                if len(parts) == 4:
                    meta = self._scan_metadata.setdefault(device_id, {})
                    meta["MF"] = parts[0]
                    meta["TYPE"] = parts[1]
                    meta["SW"] = parts[2]
                    meta["HW"] = parts[3]
                    self._present_devices.add(device_id)
                    continue
            self._scan_metadata.setdefault(device_id, {})[reg.name.upper()] = val
            self._present_devices.add(device_id)
        if self._scan_metadata:
            _LOGGER.info("Scan metadata: %s | present devices: %s",
                         self._scan_metadata, self._present_devices)

    # Map circuit prefix → device type. Prefixes match all numeric variants (ctlv1-9, basv2, etc.)
    CIRCUIT_TYPE_BY_PREFIX: dict[str, str] = {
        "hmu": "heat_pump",
        "ctlv": "heating_controller",
        "basv": "heating_controller",
        "bai": "heating_controller",
        "z": "zone",
        "dhw": "dhw",
        "Broadcast": "bus",
        "vwz": "ventilation",
        "vwzio": "ventilation",
    }
    # Map scan TYPE field → circuit type
    DEVICE_TYPE_TO_CIRCUIT_TYPE: dict[str, str] = {
        "hmu": "heat_pump", "hmu00": "heat_pump",
        "basv": "heating_controller", "basv2": "heating_controller",
        "vwz": "ventilation", "vwzio": "ventilation",
    }
    # Map scan TYPE → circuit name when TYPE doesn't match circuit prefix
    TYPE_TO_CIRCUIT_OVERRIDE: dict[str, str] = {
        "netx2": "Broadcast",
    }

    # Determine circuit type from scan TYPE string
    @classmethod
    def _resolve_type(cls, raw_type: str) -> str | None:
        low = raw_type.lower()
        ctype = cls.DEVICE_TYPE_TO_CIRCUIT_TYPE.get(low)
        if ctype:
            return ctype
        for prefix, t in [("ctlv", "heating_controller"), ("bai", "heating_controller")]:
            if low.startswith(prefix):
                return t
        return None

    # Classify each circuit by device type using scan metadata + circuit prefix
    def _detect_circuit_types(self) -> None:
        ctypes: dict[str, str] = {}
        # Priority 1: scan TYPE → circuit, using known mapping + TYPE prefix fallback
        for device_id, meta in getattr(self, "_scan_metadata", {}).items():
            raw_type = meta.get("TYPE", "").lower()
            ctype = self._resolve_type(raw_type)
            if not ctype:
                continue
            # Known circuits from static mapping for this device
            known_ckt = self.DEVICE_ID_TO_CIRCUIT.get(device_id)
            if known_ckt and known_ckt in self.registers:
                ctypes[known_ckt] = ctype
            # Any additional circuits matching the TYPE prefix (e.g. basv from TYPE=BASV2)
            ckt_prefix = raw_type.rstrip("0123456789")
            # Handle TYPEs that map to different circuit names
            if ckt_prefix in ("netx",):
                circuit_name = self.TYPE_TO_CIRCUIT_OVERRIDE.get(raw_type)
                if circuit_name and circuit_name in self.registers:
                    ctypes[circuit_name] = ctype
                continue
            for circuit in self.registers:
                if circuit in ctypes or circuit.lower().startswith(("scan",)) or "." in circuit:
                    continue
                if circuit.lower().startswith(ckt_prefix):
                    ctypes[circuit] = ctype
        # Priority 2: circuit prefix heuristic (for circuits not in scan data)
        for circuit in self.registers:
            if circuit in ctypes or circuit.lower().startswith(("scan",)) or "." in circuit:
                continue
            for prefix, ctype in self.CIRCUIT_TYPE_BY_PREFIX.items():
                if circuit.lower().startswith(prefix):
                    ctypes[circuit] = ctype
                    break
        # Priority 3: fallback for heating_controller via Z1OpMode
        if "heating_controller" not in ctypes.values():
            for reg in self.registers.values():
                if reg.name == "Z1OpMode" and reg.has_data:
                    ctypes[reg.circuit] = "heating_controller"
                    break
        self._circuit_types = ctypes

    # Return all circuits matching a device type
    def circuits_by_type(self, ctype: str) -> list[str]:
        return [c for c, t in getattr(self, "_circuit_types", {}).items() if t == ctype]

    @property
    def heating_circuit(self) -> str:
        # Prefer circuit with actual HVAC register data over no-data circuits
        circuits = self.circuits_by_type("heating_controller")
        if not circuits:
            return self._heating_circuit
        if len(circuits) == 1:
            return circuits[0]
        for reg in self.registers.values():
            if reg.name in ("Z1OpMode", "HwcOpMode", "Z1DayTemp") and reg.has_data:
                if reg.circuit in circuits:
                    return reg.circuit
        return circuits[0]

    # Build dynamic circuit→device_id mapping from scan metadata + discovered circuits
    def _build_circuit_to_device_id(self) -> None:
        mapping: dict[str, str] = {}
        for device_id, meta in getattr(self, "_scan_metadata", {}).items():
            raw_type = meta.get("TYPE", "").lower()
            # Static mapping first
            known_ckt = self.DEVICE_ID_TO_CIRCUIT.get(device_id)
            if known_ckt and known_ckt in self.registers:
                mapping[known_ckt] = device_id
            # Also map TYPE-matched circuits (e.g. basv from TYPE=BASV2)
            if raw_type:
                ckt_prefix = raw_type.rstrip("0123456789")
                if ckt_prefix in ("netx",):
                    continue
                for circuit in self.registers:
                    if circuit in mapping or circuit.lower().startswith(("scan",)):
                        continue
                    if circuit.lower().startswith(ckt_prefix):
                        mapping[circuit] = device_id
        self._dynamic_circuit_to_device_id = mapping

    DEVICE_ID_TO_CIRCUIT = {
        "08": "hmu", "15": "ctlv2", "76": "vwz", "f6": "Broadcast",
    }

    # Map scan-detected device IDs to known circuit names
    @property
    def _present_circuits(self) -> set[str]:
        devices = getattr(self, "_present_devices", set())
        result: set[str] = set()
        for did in devices:
            ckt = self.DEVICE_ID_TO_CIRCUIT.get(did)
            if ckt:
                result.add(ckt)
        return result

    # Read REGISTER_MAP entries that find missed, add entities if new
    async def _fallback_read(self) -> None:
        if not self.ebusd_backend:
            return
        need_read = [
            key for key in REGISTER_MAP
            if REGISTER_MAP[key].enabled
        ]
        if not need_read:
            return
        find_keys = getattr(self, "_last_find_keys", set())
        to_read = [k for k in need_read if k not in find_keys]
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
                value = await self.ebusd_backend.async_read(circuit, name)
                was_new = key not in self.registers
                if value and (value.startswith(("or:", "ERR:")) or "read [-" in value):
                    value = None
                if value is None:
                    cache = self._load_cache()
                    cached = cache.get(f"{circuit}.{name}.value")
                    if cached is not None:
                        value = cached
                if value is not None:
                    if was_new:
                        self.registers[key] = EbusdRegister(
                            circuit=circuit,
                            name=name,
                            fields=["value"],
                            value={"value": value},
                            has_data=True,
                        )
                        added += 1
                    else:
                        self.registers[key].value["value"] = value
                        self.registers[key].has_data = True
                    _LOGGER.debug("Fallback read %s = %s", key, value)
                elif was_new and REGISTER_MAP[key].enabled:
                    self.registers[key] = EbusdRegister(
                        circuit=circuit,
                        name=name,
                        fields=["value"],
                        value={"value": None},
                        has_data=False,
                    )
                    added += 1
                    _LOGGER.debug("Fallback added empty %s (will populate on poll)", key)
            except Exception as exc:
                _LOGGER.warning("Fallback read failed: %s (%s)", key, exc)
        if added:
            self._active_zone_circuits = _detect_active_circuits(
                list(self.registers.values())
            )
            fp_present: set[str] = {"hmu", self.heating_circuit, "Broadcast"}
            for reg in self.registers.values():
                if reg.has_data:
                    fp_present.add(reg.circuit)
            self.entities = generate_entity_descriptions(
                list(self.registers.values()),
                active_zone_circuits=self._active_zone_circuits,
                present_circuits=fp_present,
            )
        _LOGGER.info("Fallback: %d/%d known registers checked",
                     len(need_read), len(REGISTER_MAP))

    # Poll ebusd for register values, called by HA update loop
    async def _async_update_data(self) -> dict[str, Any]:
        if not self._ebusd_connected:
            # First poll: return cached data immediately, connect in background
            if not self._started:
                self._started = True
                self.hass.async_create_task(self._ebusd_connect_and_discover())
            return {"ebusd": self._values_from_registers()}

        if self.ebusd_backend and self.ebusd_backend.connected:
            try:
                discovered = await self.ebusd_backend.async_find()
                self._last_find_keys = {r.key for r in discovered}
                for reg in discovered:
                    if reg.has_data:
                        self.registers[reg.key] = reg
                    elif reg.key not in self.registers:
                        self.registers[reg.key] = reg
                await self._fallback_read()
                zero_idle_registers(self.registers)
                return {"ebusd": self._values_from_registers()}
            except (ConnectionError, TimeoutError, OSError):
                _LOGGER.warning("ebusd connection lost, reconnecting")
                try:
                    await self.ebusd_backend.async_reconnect()
                    await repairs.async_dismiss_ebusd_unreachable(self.hass)
                except Exception as exc:
                    _LOGGER.error("ebusd reconnect failed: %s", exc)
                    await repairs.async_create_ebusd_unreachable(self.hass)

        return {"ebusd": self._values_from_registers()}

    # Disconnect ebusd backend on integration unload
    async def async_stop(self) -> None:
        if self.ebusd_backend:
            await self.ebusd_backend.async_disconnect()

    PARENT_CIRCUITS: dict[str, str] = {
        "ctlv2": "hmu", "basv": "hmu", "z1": "ctlv2", "dhw": "ctlv2", "Broadcast": "hmu",
    }
    CIRCUIT_TO_DEVICE_ID: dict[str, str] = {
        "hmu": "08", "ctlv2": "15", "basv": "15", "vwz": "76", "Broadcast": "f6",
    }

    # Build HA DeviceInfo for a circuit, using scan metadata (SW/HW) when available
    def get_device_info(self, circuit: str) -> DeviceInfo:
        name = CIRCUIT_NAMES.get(circuit, f"Vaillant ({circuit})")
        device_id = self.CIRCUIT_TO_DEVICE_ID.get(circuit)
        if not device_id:
            dyn = getattr(self, "_dynamic_circuit_to_device_id", {})
            device_id = dyn.get(circuit)
        scan = {}
        if hasattr(self, "_scan_metadata") and device_id:
            scan = self._scan_metadata.get(device_id, {})
        model = scan.get("ID") or name
        manufacturer = "Vaillant"
        sw_version = scan.get("SW")
        hw_version = scan.get("HW")
        via_device: tuple[str, str] | None = None
        parent = self.PARENT_CIRCUITS.get(circuit)
        if parent:
            via_device = (DOMAIN, parent)
        return DeviceInfo(
            identifiers={(DOMAIN, circuit)},
            name=name,
            manufacturer=manufacturer,
            model=model,
            sw_version=sw_version or (self.ebusd_backend.version if self.ebusd_backend else None),
            hw_version=hw_version,
            via_device=via_device,
        )
