"""Vaillant EEBUS integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from vaillant.certificate import get_or_create_certificate

from .const import DOMAIN, PLATFORMS
from .coordinator import VaillantCoordinator

_LOGGER = logging.getLogger(__name__)


async def _handle_set_dhw_temperature(call: ServiceCall, coordinator: VaillantCoordinator) -> None:
    temperature = call.data["temperature"]
    for cap in coordinator.capabilities.by_feature_type("SetpointServer"):
        etype = coordinator.capabilities.get_entity_type(list(cap.entity))
        if etype and "DHW" in etype:
            server = {"entity": list(cap.entity), "feature": cap.feature}
            await coordinator.client.write_setpoint(server, temperature)
            return
    _LOGGER.warning("No DHW setpoint server found")


async def _handle_set_hvac_mode(call: ServiceCall, coordinator: VaillantCoordinator) -> None:
    mode = call.data["mode"]
    for cap in coordinator.capabilities.by_feature_type("HVAC"):
        etype = coordinator.capabilities.get_entity_type(list(cap.entity))
        if etype and ("HVAC" in etype or "Room" in etype or "Zone" in etype):
            server = {"entity": list(cap.entity), "feature": cap.feature}
            await coordinator.client.write_hvac_mode(server, mode)
            return
    _LOGGER.warning("No HVAC server found")


SET_DHW_SCHEMA = vol.Schema({vol.Required("temperature"): vol.All(vol.Coerce(float), vol.Range(min=5, max=80))})
SET_HVAC_SCHEMA = vol.Schema({vol.Required("mode"): vol.In(["heating", "cooling", "ventilation", "standby", "auto"])})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    logging.getLogger("vaillant").setLevel(logging.INFO)
    logging.getLogger("custom_components.vaillant_eebus").setLevel(logging.DEBUG)
    _LOGGER.info("Setting up vaillant_eebus entry: %s", entry.data)
    hass.data.setdefault(DOMAIN, {})
    try:
        cert_ski = await hass.async_add_executor_job(get_or_create_certificate)
        _LOGGER.info("Certificate loaded, SKI=%s", cert_ski[:16])
    except Exception as exc:
        _LOGGER.error("Failed to load certificate: %s", exc, exc_info=True)
        return False
    try:
        coordinator = VaillantCoordinator(hass, entry, cert_ski)
        hass.data[DOMAIN][entry.entry_id] = coordinator
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.info("Coordinator first refresh OK")
    except Exception as exc:
        _LOGGER.error("Coordinator setup failed: %s", exc, exc_info=True)
        return False
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def svc_set_dhw(call: ServiceCall) -> None:
        await _handle_set_dhw_temperature(call, coordinator)

    async def svc_set_hvac(call: ServiceCall) -> None:
        await _handle_set_hvac_mode(call, coordinator)

    hass.services.async_register(DOMAIN, "set_dhw_target_temperature", svc_set_dhw, schema=SET_DHW_SCHEMA)
    hass.services.async_register(DOMAIN, "set_hvac_mode", svc_set_hvac, schema=SET_HVAC_SCHEMA)
    _LOGGER.info("vaillant_eebus setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.services.async_remove(DOMAIN, "set_dhw_target_temperature")
    hass.services.async_remove(DOMAIN, "set_hvac_mode")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.stop()
    return True
