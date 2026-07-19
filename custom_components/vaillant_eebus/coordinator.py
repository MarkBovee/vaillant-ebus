"""Coordinator for Vaillant EEBUS."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncZeroconf

from vaillant.client import VaillantClient

from .const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class VaillantCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator for Vaillant EEBUS data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, cert_ski: str) -> None:
        """Initialize coordinator."""
        _LOGGER.info("Initializing coordinator")
        self.client = VaillantClient(
            measurement_callback=self._async_heartbeat_callback,
            cert_ski=cert_ski,
        )
        self._host = entry.data.get(CONF_HOST)
        self._port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self._entry = entry
        self._started = False

        update_interval = timedelta(
            seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        _LOGGER.info("Coordinator initialized, target %s:%s", self._host, self._port)

    async def _async_heartbeat_callback(
        self, measurements: dict[str, dict[str, Any]]
    ) -> None:
        self.async_set_updated_data(dict(measurements))

    async def async_start(self) -> None:
        if self._started:
            return
        if not self._host:
            raise UpdateFailed("Missing host")
        _LOGGER.info("Starting client connection to %s:%s", self._host, self._port)
        from homeassistant.components.zeroconf import async_get_instance
        zc = await async_get_instance(self.hass)
        aiozc = AsyncZeroconf(zc=zc, ip_version=IPVersion.V4Only)
        await self.client.start(self._host, self._port, aiozc=aiozc)
        self._started = True
        _LOGGER.info("Client connection started")

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        _LOGGER.debug("Coordinator _async_update_data called, started=%s", self._started)
        if not self._started:
            await self.async_start()

        if not self.client.latest_measurements:
            _LOGGER.info("Waiting for measurements")
            for i in range(50):
                if self.client.latest_measurements:
                    _LOGGER.info("Measurements received after %ds", (i + 1) * 0.2)
                    break
                await asyncio.sleep(0.2)
            else:
                _LOGGER.warning(
                    "No measurements after 10s. If new device: approve the "
                    "handshake in the myVAILLANT app. If previously working: "
                    "check VR921 connectivity."
                )

        if self.client.latest_measurements:
            count = len(self.client.latest_measurements)
            _LOGGER.debug("Returning %d measurements", count)
            return dict(self.client.latest_measurements)
        _LOGGER.warning("UpdateFailed: no measurements yet")
        raise UpdateFailed("No measurements yet")

    @property
    def capabilities(self):
        return self.client.capabilities

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._host or "vaillant_eebus")},
            name="Vaillant EEBUS (VR921)",
            manufacturer="Vaillant",
            model="VR921",
        )
