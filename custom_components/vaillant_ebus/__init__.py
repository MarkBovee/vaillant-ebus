"""Vaillant eBUS integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .coordinator import VaillantCoordinator

_LOGGER = logging.getLogger(__name__)


# Set up coordinator, forward platforms, register services.
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up vaillant_ebus entry: %s", entry.data)
    hass.data.setdefault(DOMAIN, {})

    coordinator = VaillantCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Read a single register by circuit and name.
    async def svc_read_parameter(call: ServiceCall) -> None:
        circuit = call.data["circuit"]
        name = call.data["name"]
        field = call.data.get("field", "")
        if coordinator.ebusd_backend:
            value = await coordinator.ebusd_backend.async_read(circuit, name, field)
            _LOGGER.info("read_parameter %s.%s = %s", circuit, name, value)

    # Write a value with read-after-write verification.
    async def svc_write_parameter(call: ServiceCall) -> None:
        circuit = call.data["circuit"]
        name = call.data["name"]
        value = call.data["value"]
        if coordinator.ebusd_backend:
            result = await coordinator.ebusd_backend.async_write(circuit, name, value)
            _LOGGER.info(
                "write_parameter %s.%s=%s: success=%s, verified=%s",
                circuit, name, value, result.success, result.verified_value,
            )

    # Force re-read all active registers.
    async def svc_refresh(call: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    # Re-run entity discovery from scratch.
    async def svc_rediscover(call: ServiceCall) -> None:
        if coordinator.ebusd_backend:
            await coordinator.ebusd_backend.async_disconnect()
            await coordinator.async_start()

    hass.services.async_register(
        DOMAIN, "read_parameter", svc_read_parameter,
        schema=vol.Schema({
            vol.Required("circuit"): cv.string,
            vol.Required("name"): cv.string,
            vol.Optional("field", default=""): cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN, "write_parameter", svc_write_parameter,
        schema=vol.Schema({
            vol.Required("circuit"): cv.string,
            vol.Required("name"): cv.string,
            vol.Required("value"): cv.string,
        }),
    )
    hass.services.async_register(DOMAIN, "refresh", svc_refresh, schema=vol.Schema({}))
    hass.services.async_register(DOMAIN, "rediscover", svc_rediscover, schema=vol.Schema({}))

    _LOGGER.info("vaillant_ebus setup complete")
    return True


# Tear down coordinator and unregister services.
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    for service in ("read_parameter", "write_parameter", "refresh", "rediscover"):
        hass.services.async_remove(DOMAIN, service)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return True
