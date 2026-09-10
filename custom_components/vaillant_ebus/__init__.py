"""Vaillant eBUS integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from . import repairs  # noqa: F401 — registers issue translation keys
from .const import DOMAIN, PLATFORMS
from .coordinator import VaillantCoordinator
from .dump_service import async_export_discovery_dump

_LOGGER = logging.getLogger(__name__)

# Shared optional selector so every service works unchanged on single-entry
# installs and stays deterministic when multiple host/port entries exist.
_ENTRY_SELECTOR: dict[vol.Optional, object] = {vol.Optional("entry_id"): cv.string}


# Resolve the coordinator a service call targets: an explicit entry_id wins,
# a single loaded entry is used automatically, anything else fails loudly so
# calls never depend on which entry happened to load last.
def _resolve_coordinator(hass: HomeAssistant, call: ServiceCall) -> VaillantCoordinator:
    coordinators: dict[str, VaillantCoordinator] = hass.data.get(DOMAIN, {})
    requested = call.data.get("entry_id")
    if requested:
        coordinator = coordinators.get(requested)
        if coordinator is None:
            raise HomeAssistantError(f"vaillant_ebus config entry '{requested}' is not loaded")
        return coordinator
    if len(coordinators) == 1:
        return next(iter(coordinators.values()))
    if not coordinators:
        raise HomeAssistantError("no loaded vaillant_ebus config entries")
    raise HomeAssistantError(
        "multiple vaillant_ebus config entries are loaded; pass entry_id to select one"
    )


def _service_handler(hass: HomeAssistant, handler):
    async def callback(call: ServiceCall) -> None:
        await handler(hass, call)

    return callback


# Read a single register by circuit and name.
async def _svc_read_parameter(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(hass, call)
    circuit = call.data["circuit"]
    name = call.data["name"]
    field = call.data.get("field", "")
    value = await coordinator.async_read_register(circuit, name, field)
    _LOGGER.info("read_parameter %s.%s = %s", circuit, name, value)


# Write a value with read-after-write verification via the central write path.
async def _svc_write_parameter(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(hass, call)
    circuit = call.data["circuit"]
    name = call.data["name"]
    value = call.data["value"]
    ok = await coordinator.async_write_register(circuit, name, value)
    _LOGGER.info("write_parameter %s.%s=%s: success=%s", circuit, name, value, ok)


# Write the eloBLOCK B510 thermostat override and keep it alive while enabled.
async def _svc_set_mode_override(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(hass, call)
    ok = await coordinator.async_set_mode_override(
        call.data["flow_temperature"],
        call.data["storage_temperature"],
        call.data.get("mode", 0),
        call.data.get("keep_alive", True),
    )
    if not ok:
        raise HomeAssistantError("SetModeOverride write failed")


async def _svc_clear_mode_override(hass: HomeAssistant, call: ServiceCall) -> None:
    _resolve_coordinator(hass, call).async_clear_mode_override()


# Force re-read all active registers.
async def _svc_refresh(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(hass, call)
    await coordinator.async_request_refresh()


# Re-run entity discovery from scratch via the coordinator's public path.
async def _svc_rediscover(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(hass, call)
    await coordinator.async_request_rediscover()


# Run background analysis on-demand: discover + enable new devices/entities.
async def _svc_analyze(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(hass, call)
    await coordinator.async_run_analysis()


# Export full discovery dump to YAML, optionally with raw grab.
async def _svc_export_discovery_dump(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(hass, call)
    raw = call.data.get("grab_duration", 0)
    grab_duration = min(max(int(raw), 0), 300)
    await async_export_discovery_dump(hass, coordinator, grab_duration)


# Register all services once at integration scope; they resolve their target
# coordinator per call instead of closing over whichever entry set them up.
async def _register_services(hass: HomeAssistant) -> None:
    hass.services.async_register(
        DOMAIN,
        "read_parameter",
        _service_handler(hass, _svc_read_parameter),
        schema=vol.Schema(
            {
                vol.Required("circuit"): cv.string,
                vol.Required("name"): cv.string,
                vol.Optional("field", default=""): cv.string,
                **_ENTRY_SELECTOR,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "write_parameter",
        _service_handler(hass, _svc_write_parameter),
        schema=vol.Schema(
            {
                vol.Required("circuit"): cv.string,
                vol.Required("name"): cv.string,
                vol.Required("value"): cv.string,
                **_ENTRY_SELECTOR,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "set_mode_override",
        _service_handler(hass, _svc_set_mode_override),
        schema=vol.Schema(
            {
                vol.Required("flow_temperature"): vol.Coerce(float),
                vol.Required("storage_temperature"): vol.Coerce(float),
                vol.Optional("mode", default=0): vol.Coerce(int),
                vol.Optional("keep_alive", default=True): cv.boolean,
                **_ENTRY_SELECTOR,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "clear_mode_override",
        _service_handler(hass, _svc_clear_mode_override),
        schema=vol.Schema(dict(_ENTRY_SELECTOR)),
    )
    hass.services.async_register(
        DOMAIN, "refresh", _service_handler(hass, _svc_refresh), schema=vol.Schema(dict(_ENTRY_SELECTOR))
    )
    hass.services.async_register(
        DOMAIN,
        "rediscover",
        _service_handler(hass, _svc_rediscover),
        schema=vol.Schema(dict(_ENTRY_SELECTOR)),
    )
    hass.services.async_register(
        DOMAIN,
        "analyze_registers",
        _service_handler(hass, _svc_analyze),
        schema=vol.Schema(dict(_ENTRY_SELECTOR)),
    )
    hass.services.async_register(
        DOMAIN,
        "export_discovery_dump",
        _service_handler(hass, _svc_export_discovery_dump),
        schema=vol.Schema({vol.Optional("grab_duration"): vol.Coerce(int), **_ENTRY_SELECTOR}),
    )


# Integration-scope setup: register services once for all config entries.
async def async_setup(hass: HomeAssistant, config: dict) -> bool:  # noqa: ARG001
    await _register_services(hass)
    return True


# Set up coordinator, forward platforms.
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up vaillant_ebus entry: %s", entry.data)
    hass.data.setdefault(DOMAIN, {})

    coordinator = VaillantCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.disable_no_data_entities()

    # Reload the entry when data/options change so connection and behavior
    # settings apply without restarting Home Assistant.
    async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
        await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


# Tear down the coordinator; integration-scope services stay available and
# resolve against whatever entries remain loaded.
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return True
