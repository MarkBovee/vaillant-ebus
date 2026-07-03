"""Config flow for Vaillant EEBUS."""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
_SHIP_SERVICE = "_ship._tcp.local."


class VaillantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vaillant EEBUS."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step — mDNS discovery first, manual fallback."""
        _LOGGER.info("async_step_user called, user_input=%s", user_input)
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])
            _LOGGER.info("Manual entry: host=%s port=%s", host, port)
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=5,
                )
                writer.close()
                await writer.wait_closed()
                _LOGGER.info("TCP connect OK, creating entry")
            except Exception as exc:
                _LOGGER.warning("TCP connect failed: %s", exc)
                return self.async_show_form(
                    step_id="user",
                    data_schema=_user_schema(user_input),
                    errors={"base": "cannot_connect"},
                )

            return self.async_create_entry(
                title="Vaillant EEBUS (VR921)",
                data={**user_input, CONF_HOST: host, CONF_PORT: port},
            )

        _LOGGER.info("Trying mDNS discovery")
        host, port = await self._async_discover()
        if host and port:
            _LOGGER.info("mDNS discovered VR921 at %s:%s", host, port)
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Vaillant EEBUS (VR921)",
                data={CONF_HOST: host, CONF_PORT: port},
            )

        _LOGGER.info("mDNS discovery found nothing, showing manual form")
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
        )

    async def async_step_zeroconf(
        self, discovery_info: Any | None = None
    ) -> FlowResult:
        """Handle zeroconf discovery — auto-configure, no IP needed."""
        _LOGGER.info("async_step_zeroconf called: %s", discovery_info)
        if discovery_info is None:
            return self.async_abort(reason="unknown")
        host = str(getattr(discovery_info, "host", "") or "")
        port = int(getattr(discovery_info, "port", DEFAULT_PORT))
        if not host:
            return self.async_abort(reason="unknown")

        _LOGGER.info("zeroconf discovered %s:%s", host, port)
        await self.async_set_unique_id(f"{host}:{port}")
        self._abort_if_unique_id_configured()

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=5,
            )
            writer.close()
            await writer.wait_closed()
        except Exception as exc:
            _LOGGER.warning("zeroconf TCP connect failed: %s", exc)
            return self.async_abort(reason="cannot_connect")

        _LOGGER.info("zeroconf entry created for %s:%s", host, port)
        return self.async_create_entry(
            title="Vaillant EEBUS (VR921)",
            data={CONF_HOST: host, CONF_PORT: port},
        )

    async def async_step_dhcp(
        self, discovery_info: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle DHCP discovery."""
        return await self.async_step_user()

    async def _async_discover(self) -> tuple[str, int] | tuple[None, None]:
        """Discover VR921 via HA's shared zeroconf. Returns (host, port) or (None, None)."""
        try:
            from homeassistant.components.zeroconf import async_get_instance
            from zeroconf.asyncio import AsyncServiceBrowser

            from vaillant.certificate import get_or_create_certificate
            from vaillant.discovery import MDNSHandler

            _LOGGER.info("Starting mDNS discovery (15s timeout)")
            hass = self.hass
            zc = await async_get_instance(hass)
            _LOGGER.info("Got HA shared zeroconf instance")
            cert_ski = await hass.async_add_executor_job(get_or_create_certificate)
            _LOGGER.info("Certificate loaded, SKI=%s", cert_ski[:16])

            handler = MDNSHandler(cert_ski)
            browser = AsyncServiceBrowser(zc, _SHIP_SERVICE, handler)

            for i in range(15):
                await asyncio.sleep(1)
                if handler.target_info is not None:
                    _LOGGER.info("mDNS found target after %ds", i + 1)
                    break

            browser.cancel()

            if handler.target_info is not None:
                ip = socket.inet_ntoa(handler.target_info.addresses[0])
                port = handler.target_info.port
                _LOGGER.info("mDNS discovered VR921 at %s:%s", ip, port)
                return ip, port
            _LOGGER.warning("mDNS discovery timed out, no VR921 found")
        except Exception as exc:
            _LOGGER.error("mDNS discovery error: %s", exc, exc_info=True)
        return None, None


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): int,
        }
    )
