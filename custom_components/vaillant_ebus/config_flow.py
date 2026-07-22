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
    DEFAULT_EBUSD_HOST,
    DEFAULT_EBUSD_POLL_INTERVAL,
    DEFAULT_EBUSD_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class VaillantConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    # Handle user-initiated config flow for ebusd connection
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            host = str(user_input[CONF_EBUSD_HOST]).strip()
            port = int(user_input[CONF_EBUSD_PORT])
            unique_id = f"ebusd_{host}:{port}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=5,
                )
                writer.write(b"i\n")
                await writer.drain()
                response = await asyncio.wait_for(reader.readline(), timeout=5)
                writer.close()
                await writer.wait_closed()
                _LOGGER.info("ebusd connect OK: %s", response.decode().strip())
            except Exception as exc:
                _LOGGER.warning("ebusd connect failed: %s", exc)
                return self.async_show_form(
                    step_id="user",
                    data_schema=_user_schema(user_input),
                    errors={"base": "cannot_connect"},
                )

            return self.async_create_entry(
                title="Vaillant eBUS (ebusd)",
                data={
                    CONF_EBUSD_HOST: host,
                    CONF_EBUSD_PORT: port,
                    CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL),
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
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
            vol.Required(CONF_EBUSD_HOST, default=defaults.get(CONF_EBUSD_HOST, DEFAULT_EBUSD_HOST)): str,
            vol.Required(CONF_EBUSD_PORT, default=defaults.get(CONF_EBUSD_PORT, DEFAULT_EBUSD_PORT)): int,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_EBUSD_POLL_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
        }
    )
