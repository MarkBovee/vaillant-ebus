"""Vaillant eBUS integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from . import repairs  # noqa: F401 — registers issue translation keys
from .const import DOMAIN, PLATFORMS
from .coordinator import VaillantCoordinator
from .dump_service import async_export_discovery_dump

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
        if coordinator.ebus:
            value = await coordinator.ebus.read_register(circuit, name, field)
            _LOGGER.info("read_parameter %s.%s = %s", circuit, name, value)

    # Write a value with read-after-write verification via the central write path.
    async def svc_write_parameter(call: ServiceCall) -> None:
        circuit = call.data["circuit"]
        name = call.data["name"]
        value = call.data["value"]
        ok = await coordinator.async_write_register(circuit, name, value)
        _LOGGER.info("write_parameter %s.%s=%s: success=%s", circuit, name, value, ok)

    # Force re-read all active registers.
    async def svc_refresh(call: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    # Re-run entity discovery from scratch.
    async def svc_rediscover(call: ServiceCall) -> None:
        if coordinator.ebus:
            await coordinator.ebus.disconnect()
        coordinator.ebus = None
        coordinator._ebusd_connected = False
        coordinator._started = False
        await coordinator.async_request_refresh()

    # Run background analysis on-demand: discover + enable new devices/entities.
    async def svc_analyze(call: ServiceCall) -> None:
        await coordinator.async_run_analysis()

    hass.services.async_register(
        DOMAIN,
        "read_parameter",
        svc_read_parameter,
        schema=vol.Schema(
            {
                vol.Required("circuit"): cv.string,
                vol.Required("name"): cv.string,
                vol.Optional("field", default=""): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "write_parameter",
        svc_write_parameter,
        schema=vol.Schema(
            {
                vol.Required("circuit"): cv.string,
                vol.Required("name"): cv.string,
                vol.Required("value"): cv.string,
            }
        ),
    )
    hass.services.async_register(DOMAIN, "refresh", svc_refresh, schema=vol.Schema({}))
    hass.services.async_register(DOMAIN, "rediscover", svc_rediscover, schema=vol.Schema({}))
    hass.services.async_register(DOMAIN, "analyze_registers", svc_analyze, schema=vol.Schema({}))

    # Export full discovery dump to YAML, optionally with raw grab.
    async def svc_export_discovery_dump(call: ServiceCall) -> None:
        raw = call.data.get("grab_duration", 0)
        grab_duration = min(max(int(raw), 0), 300)
        await async_export_discovery_dump(hass, coordinator, grab_duration)

    hass.services.async_register(
        DOMAIN,
        "export_discovery_dump",
        svc_export_discovery_dump,
        schema=vol.Schema(
            {
                vol.Optional("grab_duration"): vol.Coerce(int),
            }
        ),
    )

    return True


# Tear down coordinator and unregister services.
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    for service in (
        "read_parameter",
        "write_parameter",
        "refresh",
        "rediscover",
        "analyze_registers",
        "export_discovery_dump",
    ):
        hass.services.async_remove(DOMAIN, service)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return True
