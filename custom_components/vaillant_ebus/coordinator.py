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

        scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

        # Immediately seed entities from REGISTER_MAP + cache (no ebusd needed)
        self._seed_entities_from_cache()

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
        # Without ebusd data, treat all known REGISTER_MAP circuits as active
        self.entities = generate_entity_descriptions(
            list(self.registers.values()),
            active_zone_circuits=known_circuits,
            skip_active_check=True,
        )
        _LOGGER.info("Seeded %d entities from REGISTER_MAP + cache (%d circuits)",
                     len(self.entities), len(known_circuits))

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

        self.entities = generate_entity_descriptions(
            list(self.registers.values()),
            active_zone_circuits=self._active_zone_circuits,
            present_circuits=self._present_circuits,
        )
        _LOGGER.info("Generated %d entity descriptions after ebusd discovery", len(self.entities))
        self.async_update_listeners()
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
                    values[f"{reg.circuit}.{reg.name}.{field}"] = translated
        self._save_cache(values)
        return values

    @property
    def _cache_path(self) -> str:
        return self.hass.config.path(DOMAIN, "register_cache.json")

    def _save_cache(self, values: dict[str, str]) -> None:
        cache_dir = os.path.dirname(self._cache_path)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(self._cache_path, "w") as f:
                json.dump(values, f)
        except Exception:
            pass

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
            if value is not None and value not in ("-", "no data stored", ""):
                self._scan_metadata.setdefault(device_id, {})[reg.name.upper()] = str(value)
                self._present_devices.add(device_id)
        if self._scan_metadata:
            _LOGGER.info("Scan metadata: %s | present devices: %s",
                         self._scan_metadata, self._present_devices)

    DEVICE_ID_TO_CIRCUIT = {
        "08": "hmu", "15": "ctlv2", "76": "vwz", "f6": "Broadcast",
    }

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
            self.entities = generate_entity_descriptions(
                list(self.registers.values()),
                active_zone_circuits=self._active_zone_circuits,
                present_circuits=self._present_circuits,
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
        "ctlv2": "hmu", "z1": "ctlv2", "dhw": "ctlv2", "Broadcast": "hmu",
    }
    CIRCUIT_TO_DEVICE_ID: dict[str, str] = {
        "hmu": "08", "ctlv2": "15", "vwz": "76", "Broadcast": "f6",
    }

    def get_device_info(self, circuit: str) -> DeviceInfo:
        name = CIRCUIT_NAMES.get(circuit, f"Vaillant ({circuit})")
        device_id = self.CIRCUIT_TO_DEVICE_ID.get(circuit)
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
