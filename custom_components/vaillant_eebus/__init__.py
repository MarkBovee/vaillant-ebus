"""Vaillant EEBUS integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from vaillant.certificate import get_or_create_certificate

from .const import DOMAIN, PLATFORMS
from .coordinator import VaillantCoordinator

_LOGGER = logging.getLogger(__name__)


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
    _LOGGER.info("vaillant_eebus setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.stop()
    return True
