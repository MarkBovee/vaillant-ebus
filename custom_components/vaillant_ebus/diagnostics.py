"""Diagnostics support for Vaillant eBUS."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import VaillantCoordinator


# Return diagnostics data for config entry
async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]
    result: dict[str, Any] = {"entry_data": dict(entry.data)}

    if coordinator.ebus:
        result["ebusd"] = {
            "connected": coordinator.ebus.is_connected,
            "version": coordinator.ebus.version,
            "register_count": len(coordinator.registers),
            "entity_count": len(coordinator.entities),
            "circuits": _circuit_summary(coordinator),
            "circuit_names": sorted({r.circuit for r in coordinator.registers.values()}),
        }

    return result


# Count registers per circuit for diagnostics
def _circuit_summary(coordinator: VaillantCoordinator) -> dict[str, int]:
    circuits: dict[str, int] = {}
    for reg in coordinator.registers.values():
        circuits[reg.circuit] = circuits.get(reg.circuit, 0) + 1
    return circuits
