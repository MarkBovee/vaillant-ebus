"""Diagnostics support for Vaillant eBUS."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import VaillantCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    result: dict[str, Any] = {"entry_data": dict(entry.data)}

    if coordinator.ebusd_backend:
        result["ebusd"] = {
            "connected": coordinator.ebusd_backend.connected,
            "version": coordinator.ebusd_backend.version,
            "register_count": len(coordinator.registers),
            "entity_count": len(coordinator.entities),
            "circuits": _circuit_summary(coordinator),
        }

    return result


def _circuit_summary(coordinator: VaillantCoordinator) -> dict[str, int]:
    circuits: dict[str, int] = {}
    for reg in coordinator.registers.values():
        circuits[reg.circuit] = circuits.get(reg.circuit, 0) + 1
    return circuits
