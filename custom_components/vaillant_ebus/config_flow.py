"""Config flow for Vaillant eBUS."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_AWAY_DURATION,
    CONF_EBUSD_HOST,
    CONF_EBUSD_PORT,
    CONF_QUICK_VETO_DURATION,
    CONF_QUICK_VETO_TEMP,
    CONF_SCAN_INTERVAL,
    DEFAULT_AWAY_DURATION,
    DEFAULT_EBUSD_POLL_INTERVAL,
    DEFAULT_EBUSD_PORT,
    DEFAULT_QUICK_VETO_DURATION,
    DISCOVERY_CANDIDATES,
    DISCOVERY_PORT,
    DISCOVERY_TIMEOUT,
    DOMAIN,
)


async def _get_host_ip() -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://supervisor/network/info") as resp:
                data = await resp.json()
                for iface in data.get("data", {}).get("interfaces", []):
                    if iface.get("primary"):
                        for addr in iface.get("ipv4", {}).get("address", []):
                            ip = addr.split("/")[0]
                            if ip and ip != "127.0.0.1":
                                return ip
    except Exception:
        pass
    return ""


_LOGGER = logging.getLogger(__name__)

# Attempt a TCP connect + state command against one ebusd candidate.
# Returns (host, port, "acquired") on success, None on failure.
async def _probe_candidate(
    host: str, port: int = DISCOVERY_PORT
) -> tuple[str, int, str] | None:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=DISCOVERY_TIMEOUT,
        )
        writer.write(b"s\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=DISCOVERY_TIMEOUT)
        writer.close()
        await writer.wait_closed()
        status = data.decode("utf-8", errors="replace").strip().lower()
        if "acquired" in status:
            return host, port, status
    except (OSError, TimeoutError, ConnectionError) as e:
        _LOGGER.debug("Probe failed for %s:%s: %s", host, port, e)
    return None

# Validate ebusd state response.
# Returns (error_key | None).
def _validate_info(info: str) -> str | None:
    if "acquired" not in info.lower():
        return "no_bus_signal"
    return None


class VaillantConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_EBUSD_HOST]
            port = user_input[CONF_EBUSD_PORT]

            result = await _probe_candidate(host, port)
            if result is None:
                errors["base"] = "cannot_connect"
            else:
                _, _, info = result
                if _validate_info(info):
                    errors["base"] = "no_bus_signal"
                else:
                    self._async_abort_entries_match({CONF_EBUSD_HOST: host, CONF_EBUSD_PORT: port})
                    return self._create_entry(host, port, user_input)

        if not errors:
            found = await self._try_discover()
            if found:
                host, port, info = found
                self._discovered_host = host
                self._discovered_port = port
                return await self.async_step_confirm()

        defaults = {CONF_EBUSD_HOST: await _get_host_ip(), CONF_EBUSD_PORT: DEFAULT_EBUSD_PORT}
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(defaults),
            errors=errors or None,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self._create_entry(
                self._discovered_host, self._discovered_port, user_input
            )

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"info": "ebusd is running and has acquired the bus signal."},
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=DEFAULT_EBUSD_POLL_INTERVAL,
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            }),
        )

    async def _try_discover(self) -> tuple[str, int, str] | None:
        candidates = set(DISCOVERY_CANDIDATES)
        host_ip = await _get_host_ip()
        if host_ip:
            candidates.add(host_ip)
        for host in candidates:
            _LOGGER.debug("Probing ebusd candidate: %s", host)
            result = await _probe_candidate(host, DISCOVERY_PORT)
            if result is None:
                continue
            found_host, found_port, info = result
            error = _validate_info(info)
            if error:
                _LOGGER.warning("ebusd found at %s but %s", found_host, error)
                continue
            _LOGGER.info("ebusd discovered at %s:%s", found_host, found_port)
            unique_id = f"ebusd_{found_host}:{found_port}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            self._discovered_info = info
            return found_host, found_port, info

        _LOGGER.info("No ebusd discovered on candidates")
        return None

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
        options = self._config_entry.options if hasattr(self._config_entry, "options") else {}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=data.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                vol.Optional(
                    CONF_AWAY_DURATION,
                    default=options.get(CONF_AWAY_DURATION, DEFAULT_AWAY_DURATION),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
                vol.Optional(
                    CONF_QUICK_VETO_DURATION,
                    default=options.get(CONF_QUICK_VETO_DURATION, DEFAULT_QUICK_VETO_DURATION),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                vol.Optional(
                    CONF_QUICK_VETO_TEMP,
                    default=options.get(CONF_QUICK_VETO_TEMP, ""),
                ): str,
            }),
        )


# Build vol schema for user config step with optional defaults
def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_EBUSD_HOST, default=defaults.get(CONF_EBUSD_HOST, "")): str,
            vol.Required(CONF_EBUSD_PORT, default=defaults.get(CONF_EBUSD_PORT, DEFAULT_EBUSD_PORT)): int,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
        }
    )
