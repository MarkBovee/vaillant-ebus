"""Service to export a full discovery dump to a YAML file."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import yaml
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant

from .backend.mapping import REGISTER_MAP
from .const import DOMAIN, SENSITIVE_FIELDS
from .coordinator import VaillantCoordinator

_LOGGER = logging.getLogger(__name__)


def _redact(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    name_lower = name.lower()
    if any(substr in name_lower for substr in SENSITIVE_FIELDS):
        return "<redacted>"
    return value


async def _dump_registers(
    backend, seen_keys: set[str] | None = None
) -> tuple[list[dict], set[str], list[str]]:
    raw_lines = await backend.async_find_lines()
    discovered = await backend.async_find()
    if seen_keys is None:
        seen_keys = set()
    register_list: list[dict] = []

    for reg in discovered:
        seen_keys.add(reg.key)
        vals = [_redact(reg.value.get(f), reg.name) for f in reg.fields]
        entry = {
            "circuit": reg.circuit,
            "name": reg.name,
            "fields": reg.fields,
            "values": vals,
            "writable": reg.writable,
            "has_data": reg.has_data,
        }
        if reg.message_type:
            entry["message_type"] = reg.message_type
        if reg.address:
            entry["address"] = reg.address
        register_list.append(entry)

    for key, meta in REGISTER_MAP.items():
        if key in seen_keys:
            continue
        parts = key.split(".", 1)
        if len(parts) != 2:
            continue
        circuit, name = parts
        entry: dict = {
            "circuit": circuit,
            "name": name,
            "fields": ["value"],
            "values": [None],
            "writable": meta.writable,
            "has_data": False,
            "from_map": True,
        }
        if not meta.enabled:
            entry["disabled"] = True
        try:
            val = await backend.async_read(circuit, name)
            if val:
                entry["values"] = [_redact(val, name)]
                entry["has_data"] = True
        except Exception:
            pass
        register_list.append(entry)

    register_list.sort(key=lambda r: (r["circuit"], r["name"]))
    return register_list, seen_keys, raw_lines


async def _grab_cmd(host: str, port: int, command: str) -> list[str]:
    r, w = await asyncio.open_connection(host, port)
    try:
        w.write(f"{command}\n".encode())
        await w.drain()
        resp = []
        for _ in range(200):
            try:
                line = await asyncio.wait_for(r.readline(), timeout=2)
                if not line:
                    break
                decoded = line.decode().strip()
                if decoded:
                    resp.append(decoded)
            except TimeoutError:
                break
        return resp
    finally:
        w.close()
        await w.wait_closed()


async def async_grab(host: str, port: int, duration: int) -> list[str]:
    lines: list[str] = []

    # Enable grab (uses global ebusd flag)
    enable_resp = await _grab_cmd(host, port, "grab")
    lines.append(f"[grab] {enable_resp[0] if enable_resp else 'no response'}")

    # Wait for capture duration
    await asyncio.sleep(duration)

    # Get buffered results
    result_resp = await _grab_cmd(host, port, "grab result all")
    for line in result_resp:
        lines.append(line)

    # Disable grab
    stop_resp = await _grab_cmd(host, port, "grab stop")
    lines.append(f"[grab stop] {stop_resp[0] if stop_resp else 'no response'}")

    return lines


async def async_export_discovery_dump(
    hass: HomeAssistant,
    coordinator: VaillantCoordinator,
    grab_duration: int = 0,
) -> None:
    backend = coordinator.ebusd_backend
    if not backend or not backend.connected:
        _LOGGER.error("Cannot export dump: ebusd not connected")
        return

    before_registers, seen, raw_find_lines = await _dump_registers(backend)

    grab_lines = []
    if grab_duration > 0:
        _LOGGER.info(
            "Capturing raw eBUS traffic for %d seconds...", grab_duration
        )
        try:
            grab_lines = await async_grab(
                coordinator.ebusd_host, coordinator.ebusd_port, grab_duration
            )
            _LOGGER.info("Captured %d raw lines", len(grab_lines))
        except Exception as exc:
            _LOGGER.warning("Grab failed: %s", exc)

    after_registers = []
    after_raw_lines: list[str] = []
    if grab_duration > 0:
        after_registers, _, after_raw_lines = await _dump_registers(backend)

    output_dir = hass.config.path(DOMAIN)
    hass.async_add_executor_job(_mkdir, output_dir)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filepath = f"{output_dir}/discovery_dump_{timestamp}.yaml"

    dump_data: dict = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "ebusd_version": backend.version,
            "register_count": len(after_registers or before_registers),
            "grab_duration": grab_duration,
            "dump_version": 3,
        },
        "raw_find_lines": raw_find_lines,
        "before_registers": before_registers,
    }
    if grab_lines:
        dump_data["grab"] = grab_lines
    if after_registers:
        dump_data["after_registers"] = after_registers
        dump_data["raw_find_lines_after"] = after_raw_lines

    await hass.async_add_executor_job(_write_yaml, filepath, dump_data)
    _LOGGER.info("Discovery dump written to %s", filepath)

    persistent_notification.create(
        hass,
        (
            f"Discovery dump written to:<br><code>{filepath}</code><br><br>"
            f"Captured {len(grab_lines)} raw grab lines."
        ),
        title="Vaillant eBUS Discovery Dump",
        notification_id="vaillant_ebus_discovery_dump",
    )


def _mkdir(path: str) -> None:
    import os

    os.makedirs(path, exist_ok=True)


def _write_yaml(filepath: str, data: dict) -> None:
    header = (
        "# Discovery dump for vaillant_ebus\n"
        "# Review this file for sensitive information before sharing\n"
    )
    body = yaml.dump(
        data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    with open(filepath, "w") as f:
        f.write(header + body)
