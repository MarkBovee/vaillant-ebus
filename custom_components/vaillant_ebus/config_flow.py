"""Config flow for Vaillant eBUS."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry, entity_registry

from .const import (
    CONF_AWAY_DURATION,
    CONF_COOLING_DURATION,
    CONF_EBUSD_HOST,
    CONF_EBUSD_PORT,
    CONF_QUICK_VETO_DURATION,
    CONF_QUICK_VETO_TEMP,
    CONF_SCAN_INTERVAL,
    DEFAULT_AWAY_DURATION,
    DEFAULT_COOLING_DURATION,
    DEFAULT_EBUSD_POLL_INTERVAL,
    DEFAULT_EBUSD_PORT,
    DEFAULT_QUICK_VETO_DURATION,
    DEFAULT_QUICK_VETO_TEMP,
    DISCOVERY_CANDIDATES,
    DISCOVERY_PORT,
    DISCOVERY_TIMEOUT,
    DOMAIN,
)


# Detect host IP from HA supervisor network info for auto-discovery
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
PURGE_ENTITY_SUFFIXES = ("_tmpb516montheven",)


def _current_device_circuits(coordinator: Any) -> set[str]:
    """Return device circuits present in current discovery, including placeholders."""
    graph = getattr(coordinator, "_graph", None)
    return set(graph.nodes) if graph is not None else set()


# Attempt a TCP connect + state command against one ebusd candidate.
# Returns (host, port, "acquired") on success, None on failure.
async def _probe_candidate(host: str, port: int = DISCOVERY_PORT) -> tuple[str, int, str] | None:
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


class VaillantConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    # User-facing config step: probe host or auto-discover, then confirm
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_EBUSD_HOST]
            port = user_input[CONF_EBUSD_PORT]

            result = await _probe_candidate(host, port)
            if result is None:
                errors["base"] = "cannot_connect"
            else:
                self._discovered_host = host
                self._discovered_port = port
                self._discovered_info = result[2]
                unique_id = f"ebusd_{host}:{port}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return await self.async_step_confirm()

        if not errors:
            found = await self._try_discover()
            if found:
                host, port, info = found
                self._discovered_host = host
                self._discovered_port = port
                self._discovered_info = info
                return await self.async_step_confirm()

        defaults = {CONF_EBUSD_HOST: await _get_host_ip(), CONF_EBUSD_PORT: DEFAULT_EBUSD_PORT}
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(defaults),
            errors=errors or None,
        )

    # Confirm step: show connection info and accept scan interval
    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self._create_entry(self._discovered_host, self._discovered_port, user_input)

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "info": f"Connected to **{self._discovered_host}:{self._discovered_port}** — signal acquired."
            },
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=DEFAULT_EBUSD_POLL_INTERVAL,
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                }
            ),
        )

    # Try all discovery candidates, return first ebusd with acquired signal
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
            _LOGGER.info("ebusd discovered at %s:%s", found_host, found_port)
            unique_id = f"ebusd_{found_host}:{found_port}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            self._discovered_info = info
            return found_host, found_port, info

        _LOGGER.info("No ebusd discovered on candidates")
        return None

    # Create the config entry with host, port, and scan interval
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
                if user_input
                else DEFAULT_EBUSD_POLL_INTERVAL,
            },
        )

    # Return the options flow handler for this config entry
    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return VaillantOptionsFlow(config_entry)


class VaillantOptionsFlow(OptionsFlow):
    # Initialize options flow with config entry
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    # Menu: choose between settings, maintenance actions, and export dump
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "purge_entities", "rediscover", "export_dump"],
        )

    async def async_step_purge_entities(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Remove registry entities no longer present in current discovery."""
        if user_input is not None:
            if not user_input.get("confirm"):
                return self.async_abort(reason="purge_not_confirmed")
            coordinator = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
            current_circuits = _current_device_circuits(coordinator) if coordinator else set()
            if not coordinator or not coordinator.ebus or not coordinator.ebus.is_connected or not current_circuits:
                _LOGGER.error("Refusing to purge Vaillant eBUS entities without active discovery")
                return self.async_abort(reason="purge_unavailable")
            registry = entity_registry.async_get(self.hass)
            devices = device_registry.async_get(self.hass)
            active_device_ids = {
                device_id
                for device_id, device in devices.devices.items()
                if self._config_entry.entry_id in device.config_entries
                and any(
                    identifier[0] == DOMAIN and identifier[1] in current_circuits
                    for identifier in device.identifiers
                )
            }
            removed = 0
            for entity_id, entry in list(registry.entities.items()):
                state = self.hass.states.get(entity_id)
                is_internal_helper = entry.unique_id.lower().endswith(PURGE_ENTITY_SUFFIXES)
                if (
                    entry.config_entry_id == self._config_entry.entry_id
                    and entry.platform == DOMAIN
                    and (
                        is_internal_helper
                        or (state is not None and state.state == "unknown")
                        or (
                            entry.device_id is not None
                            and entry.device_id not in active_device_ids
                        )
                    )
                ):
                    registry.async_remove(entity_id)
                    removed += 1
            remaining_device_ids = {
                entry.device_id for entry in registry.entities.values() if entry.device_id
            }
            removed_devices = 0
            for device_id, device in list(devices.devices.items()):
                if (
                    self._config_entry.entry_id in device.config_entries
                    and any(identifier[0] == DOMAIN for identifier in device.identifiers)
                    and device_id not in remaining_device_ids
                ):
                    devices.async_remove_device(device_id)
                    removed_devices += 1
            _LOGGER.info(
                "Purged %d stale Vaillant eBUS entities and %d ghost devices",
                removed,
                removed_devices,
            )
            return self.async_abort(reason="entities_purged")

        coordinator = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        current_circuits = _current_device_circuits(coordinator) if coordinator else set()
        registry = entity_registry.async_get(self.hass)
        devices = device_registry.async_get(self.hass)
        active_device_ids = {
            device_id
            for device_id, device in devices.devices.items()
            if self._config_entry.entry_id in device.config_entries
            and any(
                identifier[0] == DOMAIN and identifier[1] in current_circuits
                for identifier in device.identifiers
            )
        }
        stale_count = sum(
            1
            for entry in registry.entities.values()
            if (
                entry.config_entry_id == self._config_entry.entry_id
                and entry.platform == DOMAIN
                and (
                    (
                        (state := self.hass.states.get(entry.entity_id)) is not None
                        and state.state == "unknown"
                    )
                    or (
                        entry.device_id is not None
                        and entry.device_id not in active_device_ids
                    )
                )
            )
        )
        return self.async_show_form(
            step_id="purge_entities",
            description_placeholders={"count": str(stale_count)},
            data_schema=vol.Schema({vol.Required("confirm", default=False): cv.boolean}),
        )

    async def async_step_rediscover(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Reconnect to ebusd and rebuild the discovery graph."""
        if user_input is not None:
            if not user_input.get("confirm"):
                return self.async_abort(reason="rediscover_not_confirmed")
            coordinator = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
            if coordinator is None:
                _LOGGER.error("Refusing to rediscover Vaillant eBUS without a loaded coordinator")
                return self.async_abort(reason="rediscover_unavailable")
            await coordinator.async_request_rediscover()
            return self.async_abort(reason="rediscover_started")

        return self.async_show_form(
            step_id="rediscover",
            description_placeholders={"host": str(self._config_entry.data.get(CONF_EBUSD_HOST, "ebusd"))},
            data_schema=vol.Schema({vol.Required("confirm", default=False): cv.boolean}),
        )

    # Settings form. Connection fields (host/port/scan interval) belong to
    # entry data — where the coordinator reads them — while behavior options
    # stay in entry.options. Both are written in one async_update_entry so the
    # update listener reloads the entry exactly once.
    _OPTION_KEYS = (CONF_AWAY_DURATION, CONF_QUICK_VETO_DURATION, CONF_QUICK_VETO_TEMP, CONF_COOLING_DURATION)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            data = dict(self._config_entry.data)
            host = str(user_input.get(CONF_EBUSD_HOST) or "").strip()
            # An emptied host keeps the stored value instead of silently
            # disabling the connection.
            if not host:
                host = data.get(CONF_EBUSD_HOST, "")
            if host:
                data[CONF_EBUSD_HOST] = host
            if user_input.get(CONF_EBUSD_PORT) is not None:
                data[CONF_EBUSD_PORT] = user_input[CONF_EBUSD_PORT]
            if user_input.get(CONF_SCAN_INTERVAL) is not None:
                data[CONF_SCAN_INTERVAL] = user_input[CONF_SCAN_INTERVAL]
            submitted_options = {key: user_input[key] for key in self._OPTION_KEYS if key in user_input}
            # Merge so a connection-only change preserves stored behavior options.
            merged_options = {**self._config_entry.options, **submitted_options}
            self.hass.config_entries.async_update_entry(self._config_entry, data=data, options=merged_options)
            return self.async_abort(reason="changes_saved")

        data = self._config_entry.data if hasattr(self._config_entry, "data") else self._config_entry
        options = self._config_entry.options if hasattr(self._config_entry, "options") else {}
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EBUSD_HOST,
                        default=data.get(CONF_EBUSD_HOST, ""),
                    ): str,
                    vol.Optional(
                        CONF_EBUSD_PORT,
                        default=data.get(CONF_EBUSD_PORT, DEFAULT_EBUSD_PORT),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
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
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_QUICK_VETO_TEMP,
                        default=options.get(CONF_QUICK_VETO_TEMP, DEFAULT_QUICK_VETO_TEMP),
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_COOLING_DURATION,
                        default=options.get(CONF_COOLING_DURATION, DEFAULT_COOLING_DURATION),
                    ): vol.Coerce(int),
                }
            ),
        )

    # Export dump: confirm + grab_duration, runs in background so long grabs
    # do not block the flow (frontend times out otherwise). Ends with abort so
    # the frontend shows our own message instead of "Options successfully saved".
    async def async_step_export_dump(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            coordinator = self.hass.data[DOMAIN].get(self._config_entry.entry_id)
            if coordinator:
                grab_duration = user_input.get("grab_duration", 10)
                from .dump_service import async_export_discovery_dump

                self.hass.async_create_task(
                    async_export_discovery_dump(self.hass, coordinator, grab_duration)
                )
            return self.async_abort(reason="export_started")

        return self.async_show_form(
            step_id="export_dump",
            data_schema=vol.Schema(
                {
                    vol.Optional("grab_duration", default=10): vol.All(vol.Coerce(int), vol.Range(min=0, max=300)),
                }
            ),
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
