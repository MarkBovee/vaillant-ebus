"""Config flow for Vaillant eBUS."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_EBUSD_HOST,
    CONF_EBUSD_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_EBUSD_POLL_INTERVAL,
    DEFAULT_EBUSD_PORT,
    DISCOVERY_CANDIDATES,
    DISCOVERY_PORT,
    DISCOVERY_TIMEOUT,
    DOMAIN,
)

_DEFAULT_EBUSD_HOST = ""

_LOGGER = logging.getLogger(__name__)

# Attempt a TCP connect + info command against one ebusd candidate.
# Returns (host, port, info_line) on success, None on failure.
async def _probe_candidate(
    host: str, port: int = DISCOVERY_PORT
) -> tuple[str, int, str] | None:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=DISCOVERY_TIMEOUT,
        )
        writer.write(b"i\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=DISCOVERY_TIMEOUT)
        writer.close()
        await writer.wait_closed()
        decoded = line.decode("utf-8").strip()
        if decoded:
            return host, port, decoded
    except (OSError, TimeoutError, ConnectionError):
        pass
    return None

# Validate ebusd info response: check signal and Vaillant presence.
# Returns (error_key | None).
def _validate_info(info: str) -> str | None:
    if "signal acquired" not in info:
        return "no_bus_signal"
    if "Vaillant" not in info:
        return "no_vaillant_device"
    return None


class VaillantConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    # Try to discover ebusd automatically, fall back to manual form
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            host = str(user_input[CONF_EBUSD_HOST]).strip()
            port = int(user_input[CONF_EBUSD_PORT])
            info_line = await _probe_candidate(host, port)
            if info_line is None:
                return self.async_show_form(
                    step_id="user",
                    data_schema=_user_schema(user_input),
                    errors={"base": "cannot_connect"},
                )
            error = _validate_info(info_line[2])
            if error:
                return self.async_show_form(
                    step_id="user",
                    data_schema=_user_schema(user_input),
                    errors={"base": error},
                )
            return self._create_entry(host, port, user_input)

        result = await self._try_discover()
        if result:
            return result

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
        )

    # Probe discovery candidates in order, return entry on first success
    async def _try_discover(self) -> FlowResult | None:
        for host in DISCOVERY_CANDIDATES:
            _LOGGER.debug("Probing ebusd candidate: %s", host)
            result = await _probe_candidate(host, DISCOVERY_PORT)
            if result is None:
                continue
            found_host, found_port, info_line = result
            error = _validate_info(info_line)
            if error:
                _LOGGER.warning("ebusd found at %s but %s: %s", found_host, error, info_line)
                continue
            _LOGGER.info("ebusd discovered at %s:%s — %s", found_host, found_port, info_line)
            unique_id = f"ebusd_{found_host}:{found_port}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self._create_entry(found_host, found_port)

        _LOGGER.info("No ebusd discovered on candidates: %s", DISCOVERY_CANDIDATES)
        return None

    # Build and return a config entry
    def _create_entry(
        self,
        host: str,
        port: int,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        return self.async_create_entry(
            title="Vaillant eBUS (ebusd)",
            data={
                CONF_EBUSD_HOST: host,
                CONF_EBUSD_PORT: port,
                CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL)
                if user_input else DEFAULT_EBUSD_POLL_INTERVAL,
            },
        )

    # Return the options flow handler for this config entry
    @staticmethod
    def async_get_options_flow(config_entry: dict[str, Any]) -> OptionsFlow:
        return VaillantOptionsFlow(config_entry)


class VaillantOptionsFlow(OptionsFlow):
    # Initialize options flow with config entry
    def __init__(self, config_entry: dict[str, Any]) -> None:
        self._config_entry = config_entry

    # Handle options flow init step (scan interval config)
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = self._config_entry.data if hasattr(self._config_entry, "data") else self._config_entry
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=data.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            }),
        )


# Build vol schema for user config step with optional defaults
def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_EBUSD_HOST, default=defaults.get(CONF_EBUSD_HOST, _DEFAULT_EBUSD_HOST)): str,
            vol.Required(CONF_EBUSD_PORT, default=defaults.get(CONF_EBUSD_PORT, DEFAULT_EBUSD_PORT)): int,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
        }
    )
