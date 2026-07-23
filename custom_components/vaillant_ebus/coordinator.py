"""Coordinator for Vaillant eBUS."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .backend.entity_factory import EntityDescription, generate_entity_descriptions
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
        _LOGGER.info("Initializing coordinator")
        self._entry = entry

        self.ebusd_backend: EbusdTcpBackend | None = None
        self.registers: dict[str, EbusdRegister] = {}
        self.entities: list[EntityDescription] = []
        self._started = False

        scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    # Connect backend, define custom registers, discover all registers
    async def async_start(self) -> None:
        if self._started:
            return
        self._started = True
        host = self._entry.data.get(CONF_EBUSD_HOST)
        port = self._entry.data.get(CONF_EBUSD_PORT, 8888)
        if not host:
            raise UpdateFailed("Missing ebusd host")
        _LOGGER.info("Starting ebusd backend to %s:%s", host, port)
        self.ebusd_backend = EbusdTcpBackend(host=host, port=port)
        await self.ebusd_backend.async_connect()

        await self._define_custom_registers()

        discovered = await self.ebusd_backend.async_find()
        for reg in discovered:
            self.registers[reg.key] = reg
        _LOGGER.info("Discovered %d ebusd registers", len(discovered))

        self.entities = generate_entity_descriptions(discovered)

    # Define runtime registers (e.g. z1RoomHumidity) on ebusd
    async def _define_custom_registers(self) -> None:
        if not self.ebusd_backend:
            return
        defines = [
            "r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800"
            ",value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity",
            "r,hmu,PowerConsumptionHmu,PowerConsumptionHmu,31,08,B516,14"
            ",value,,UCH,1,W,PowerConsumptionHmu",
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
        return values

    # Read REGISTER_MAP entries that find missed, add entities if new
    async def _fallback_read(self) -> None:
        if not self.ebusd_backend:
            return
        known_missing = [
            key for key in REGISTER_MAP
            if REGISTER_MAP[key].enabled
            and (key not in self.registers or not self.registers[key].has_data)
        ]
        if not known_missing:
            return
        _LOGGER.debug("Fallback reading %d known register(s)", len(known_missing))
        added = 0
        for key in known_missing:
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            circuit, name = parts
            try:
                value = await self.ebusd_backend.async_read(circuit, name)
                if value is not None:
                    was_new = key not in self.registers
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
            except Exception as exc:
                _LOGGER.warning("Fallback read failed: %s (%s)", key, exc)
        if added:
            self.entities = generate_entity_descriptions(list(self.registers.values()))
        _LOGGER.info("Fallback: %d/%d known registers re-read (%d added, %d had data)",
                     len(known_missing), len(REGISTER_MAP), added,
                     len(known_missing) - sum(1 for k in known_missing
                         if k not in self.registers or not self.registers[k].has_data))

    # Poll ebusd for register values, called by HA update loop
    async def _async_update_data(self) -> dict[str, Any]:
        _LOGGER.debug("Coordinator update, started=%s", self._started)
        if not self._started:
            await self.async_start()
            return {"ebusd": self._values_from_registers()}

        if self.ebusd_backend and self.ebusd_backend.connected:
            try:
                discovered = await self.ebusd_backend.async_find()
                for reg in discovered:
                    if reg.has_data:
                        self.registers[reg.key] = reg
                    elif reg.key not in self.registers:
                        self.registers[reg.key] = reg
                await self._fallback_read()
                zero_idle_registers(self.registers)
                return {"ebusd": self._values_from_registers()}
            except ConnectionError:
                _LOGGER.warning("ebusd connection lost, reconnecting")
                try:
                    await self.ebusd_backend.async_reconnect()
                except Exception as exc:
                    _LOGGER.error("ebusd reconnect failed: %s", exc)

        return {}

    # Disconnect ebusd backend on integration unload
    async def async_stop(self) -> None:
        if self.ebusd_backend:
            await self.ebusd_backend.async_disconnect()

    # Build DeviceInfo for a given circuit identifier
    def get_device_info(self, circuit: str) -> DeviceInfo:
        name = CIRCUIT_NAMES.get(circuit, f"Vaillant ({circuit})")
        return DeviceInfo(
            identifiers={(DOMAIN, circuit)},
            name=name,
            manufacturer="Vaillant",
            model=name,
            sw_version=self.ebusd_backend.version if self.ebusd_backend else None,
        )
