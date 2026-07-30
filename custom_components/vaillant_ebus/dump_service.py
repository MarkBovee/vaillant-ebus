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


# Redact sensitive fields (serial, keycode, etc.) before writing dump
def _redact(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    name_lower = name.lower()
    if any(substr in name_lower for substr in SENSITIVE_FIELDS):
        return "<redacted>"
    return value


# Parse raw find lines into register dicts for dump serialization
def _parse_find_lines(raw_lines: list[str]) -> list[dict]:
    result: list[dict] = []
    for line in raw_lines:
        line = line.strip()
        if not line or "=" not in line:
            continue
        lhs, rhs = line.split("=", 1)
        lhs = lhs.strip()
        rhs = rhs.strip()
        parts = lhs.split(" ", 1)
        circuit = parts[0]
        name = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            continue
        val = rhs
        key = f"{circuit}.{name}"
        result.append(
            {
                "circuit": circuit,
                "name": name,
                "key": key,
                "fields": ["value"],
                "values": [val],
                "writable": False,
                "has_data": val not in ("-", "no data stored", "") and not val.startswith(("(empty ", "(ERR")),
            }
        )
    return result


# Collect discovered + REGISTER_MAP registers into serializable dicts
async def _dump_registers(ebus, seen_keys: set[str] | None = None) -> tuple[list[dict], set[str], list[str]]:
    raw_lines = await ebus.find_registers()
    discovered = _parse_find_lines(raw_lines)
    if seen_keys is None:
        seen_keys = set()
    register_list: list[dict] = []

    for reg in discovered:
        seen_keys.add(reg["key"])
        vals = [_redact(v, reg["name"]) for v in reg["values"]]
        entry = {
            "circuit": reg["circuit"],
            "name": reg["name"],
            "fields": reg["fields"],
            "values": vals,
            "writable": reg["writable"],
            "has_data": reg["has_data"],
        }
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
            val = await ebus.read_register(circuit, name)
            if val:
                entry["values"] = [_redact(val, name)]
                entry["has_data"] = True
        except Exception:
            pass
        register_list.append(entry)

    register_list.sort(key=lambda r: (r["circuit"], r["name"]))
    return register_list, seen_keys, raw_lines


# Send a raw grab command to ebusd and collect response lines
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


# Capture raw eBUS traffic for N seconds via ebusd grab command
async def async_grab(host: str, port: int, duration: int) -> list[str]:
    lines: list[str] = []

    enable_resp = await _grab_cmd(host, port, "grab")
    lines.append(f"[grab] {enable_resp[0] if enable_resp else 'no response'}")

    await asyncio.sleep(duration)

    result_resp = await _grab_cmd(host, port, "grab result all")
    for line in result_resp:
        lines.append(line)

    stop_resp = await _grab_cmd(host, port, "grab stop")
    lines.append(f"[grab stop] {stop_resp[0] if stop_resp else 'no response'}")

    return lines


# Main entry point: dump registers + optional grab to YAML, notify user
async def async_export_discovery_dump(
    hass: HomeAssistant,
    coordinator: VaillantCoordinator,
    grab_duration: int = 0,
) -> None:
    ebus = coordinator.ebus
    if not ebus or not ebus.is_connected:
        _LOGGER.error("Cannot export dump: ebusd not connected")
        return

    before_registers, seen, raw_find_lines = await _dump_registers(ebus)

    grab_lines = []
    if grab_duration > 0:
        _LOGGER.info("Capturing raw eBUS traffic for %d seconds...", grab_duration)
        try:
            grab_lines = await async_grab(coordinator.ebusd_host, coordinator.ebusd_port, grab_duration)
            _LOGGER.info("Captured %d raw lines", len(grab_lines))
        except Exception as exc:
            _LOGGER.warning("Grab failed: %s", exc)

    after_registers = []
    after_raw_lines: list[str] = []
    if grab_duration > 0:
        after_registers, _, after_raw_lines = await _dump_registers(ebus)

    output_dir = hass.config.path(DOMAIN)
    hass.async_add_executor_job(_mkdir, output_dir)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filepath = f"{output_dir}/discovery_dump_{timestamp}.yaml"

    dump_data: dict = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "ebusd_version": ebus.version,
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
        (f"Discovery dump written to:<br><code>{filepath}</code><br><br>Captured {len(grab_lines)} raw grab lines."),
        title="Vaillant eBUS Discovery Dump",
        notification_id="vaillant_ebus_discovery_dump",
    )


# Create output directory if it does not exist
def _mkdir(path: str) -> None:
    import os

    os.makedirs(path, exist_ok=True)


# Write YAML dump file with security header
def _write_yaml(filepath: str, data: dict) -> None:
    header = "# Discovery dump for vaillant_ebus\n# Review this file for sensitive information before sharing\n"
    body = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    with open(filepath, "w") as f:
        f.write(header + body)
