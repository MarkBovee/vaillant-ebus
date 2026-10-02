"""Service to export a full discovery dump to a YAML file."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from weakref import WeakKeyDictionary

import yaml
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .backend.discovery_service import DiscoveryService
from .backend.dump_analysis import CURRENT_DUMP_VERSION, normalize_dump
from .backend.grab_parser import parse_grab_lines, unknown_telegrams
from .backend.mapping import (
    HMUX0_SW0407_FALLBACK_NAMES,
    REGISTER_MAP,
    VWZIO_SW0500_FALLBACK_NAMES,
    hmux0_candidate_circuits,
    hmux0_fallback_blocked_circuits,
    hmux0_sw0303_owner,
    is_field_key,
    vwz_station_scan_76_circuit,
    vwzio_sw0500_circuit,
)
from .backend.models import DeviceGraph, is_no_data_value
from .const import DOMAIN, INTEGRATION_VERSION, SENSITIVE_FIELDS
from .coordinator import VaillantCoordinator

_LOGGER = logging.getLogger(__name__)
GRAB_CONNECT_TIMEOUT = 5
GRAB_MAX_RESPONSE_LINES = 10_000
GRAB_RESPONSE_TIMEOUT = 30
GRAB_COUNT_DELTA_LIMITATION = (
    "results keep the latest payload per key; identical visible rows are coalesced by summed counts; "
    "ebusd exposes no grab epoch, so a stop/restart followed by count refill during this interval cannot be detected; "
    "external grab commands or daemon restarts must not run during export"
)
_GRAB_SESSION_LOCKS: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[str, int], asyncio.Lock]] = (
    WeakKeyDictionary()
)


class GrabIntervalUnavailableError(HomeAssistantError):
    """Raised when ebusd's shared grab snapshots cannot be safely diffed."""

    capture_method = "count_delta"


@dataclass(frozen=True, slots=True)
class GrabResultEntry:
    """One validated row from `grab result all`."""

    key: str
    family: str
    count: int
    line: str
    request: bytes
    response: bytes | None


@dataclass(frozen=True, slots=True)
class GrabCaptureResult:
    """Raw lines and timing metadata for one exporter-owned capture interval."""

    lines: tuple[str, ...]
    status: Literal["captured", "continued"]
    duration: float


# Intent: resolve hostnames to the socket addresses used for dump-lock identity.
# Why: DNS names and literal IPs can refer to one ebusd process with global grab state.
async def _grab_endpoint_keys(
    host: str,
    port: int,
    connected_endpoint: tuple[str, int] | None = None,
) -> set[tuple[str, int]]:
    loop = asyncio.get_running_loop()
    endpoints: set[tuple[str, int]] = set()
    if (
        isinstance(connected_endpoint, tuple)
        and len(connected_endpoint) == 2
        and isinstance(connected_endpoint[0], str)
        and isinstance(connected_endpoint[1], int)
    ):
        endpoints.add((connected_endpoint[0].casefold(), connected_endpoint[1]))
    try:
        addresses = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=GRAB_CONNECT_TIMEOUT
        )
    except OSError, TimeoutError:
        endpoints.add(("*", port))
        return endpoints
    endpoints.update((str(address[4][0]).casefold(), int(address[4][1])) for address in addresses)
    if not endpoints or not isinstance(connected_endpoint, tuple):
        endpoints.add(("*", port))
    return endpoints


# Intent: serialize dump captures for every resolved address on the Home Assistant event loop.
# Why: different host strings can resolve to one daemon whose grab state is global.
@asynccontextmanager
async def _grab_session_lock(
    host: str,
    port: int,
    connected_endpoint: tuple[str, int] | None = None,
) -> AsyncIterator[None]:
    loop = asyncio.get_running_loop()
    endpoint_locks = _GRAB_SESSION_LOCKS.get(loop)
    if endpoint_locks is None:
        endpoint_locks = {}
        _GRAB_SESSION_LOCKS[loop] = endpoint_locks
    locks: list[asyncio.Lock] = []
    try:
        for endpoint in sorted(await _grab_endpoint_keys(host, port, connected_endpoint)):
            lock = endpoint_locks.get(endpoint)
            if lock is None:
                lock = asyncio.Lock()
                endpoint_locks[endpoint] = lock
            await lock.acquire()
            locks.append(lock)
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


# Intent: block only passive runtime definitions and firmware-specific unsafe diagnostic reads.
# Why: dump map probes must not reintroduce active requests omitted by coordinator policy.
def _fallback_read_skip_keys(graph: DeviceGraph | None, runtime_definitions: list[str]) -> set[tuple[str, str]]:
    skipped: set[tuple[str, str]] = set()
    for definition in runtime_definitions:
        parts = definition.split(",", 3)
        if len(parts) >= 3 and parts[0].startswith("u"):
            skipped.add((parts[1].casefold(), parts[2].casefold()))

    for hmux0 in hmux0_fallback_blocked_circuits(graph):
        skipped.update((hmux0.casefold(), name) for name in HMUX0_SW0407_FALLBACK_NAMES)
    hmux0_sw0303 = hmux0_sw0303_owner(graph)
    for circuit in hmux0_candidate_circuits(graph):
        if hmux0_sw0303 is None or circuit.casefold() != hmux0_sw0303.casefold():
            skipped.add((circuit.casefold(), "rundatareturntemp"))
    vwzio = vwzio_sw0500_circuit(graph)
    if vwzio is not None:
        skipped.update((vwzio.casefold(), name) for name in VWZIO_SW0500_FALLBACK_NAMES)
    station_at_76 = vwz_station_scan_76_circuit(graph)
    for alias in ("vwz", "vwzio"):
        resolution = graph.resolve_circuit_result(alias) if graph is not None else None
        resolved = resolution.circuit if resolution and resolution.status.name == "UNIQUE" else None
        if station_at_76 is None or resolved is None or resolved.casefold() != station_at_76.casefold():
            skipped.add((alias.casefold(), "status01"))
            if resolved:
                skipped.add((resolved.casefold(), "status01"))
    resolution = graph.resolve_circuit_result("vwzio") if graph is not None else None
    resolved = resolution.circuit if resolution and resolution.status.name == "UNIQUE" else None
    # B511 runtime/start counters are decoded from observed frames, never actively probed.
    skipped.add(("vwzio", "runstatsimmersionheaterhwc"))
    if resolved:
        skipped.add((resolved.casefold(), "runstatsimmersionheaterhwc"))
    return skipped


# Redact sensitive fields (serial, keycode, etc.) before writing dump
def _redact(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    name_lower = name.lower()
    if any(substr in name_lower for substr in SENSITIVE_FIELDS):
        return "<redacted>"
    return value


# Intent: parse raw find rows into standalone bus registers for dump serialization.
# Why: field-shaped keys are parsed values of their parent telegram, not separate registers.
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
        if "." in name:
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
                "has_data": not is_no_data_value(val),
            }
        )
    return result


# Intent: export discovered and mapped registers without polling unsafe fallback entries.
# Why: a diagnostic dump must not restart the active reads suppressed by coordinator metadata.
async def _dump_registers(
    ebus,
    seen_keys: set[str] | None = None,
    circuit_aliases: dict[str, str | None] | None = None,
    ensure_active: Callable[[], None] | None = None,
    skip_fallback_reads: set[tuple[str, str]] | None = None,
    current_graph: DeviceGraph | None = None,
    runtime_definitions: list[str] | None = None,
) -> tuple[list[dict], set[str], list[str]]:
    if ensure_active is not None:
        ensure_active()
    raw_lines = await ebus.find_registers()
    if ensure_active is not None:
        ensure_active()
    discovered = _parse_find_lines(raw_lines)
    find_is_usable = getattr(ebus, "last_find_usable", None)
    skip_map_probes = find_is_usable is False
    fallback_read_skip_keys = set(skip_fallback_reads or ())
    aliases = dict(circuit_aliases or {})
    if current_graph is not None and find_is_usable is not False:
        current_graph = DiscoveryService.build_device_graph(raw_lines)
        fallback_read_skip_keys.update(_fallback_read_skip_keys(current_graph, runtime_definitions or []))
        aliases = {
            alias: (
                resolution.circuit
                if (resolution := current_graph.resolve_circuit_result(alias)).status.name == "UNIQUE"
                else None
            )
            for alias in aliases
        }
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
        if ensure_active is not None:
            ensure_active()
        parts = key.split(".", 1)
        if len(parts) != 2:
            continue
        circuit, name = parts
        if is_field_key(key):
            continue
        target_circuit = aliases.get(circuit, circuit)
        if target_circuit is None:
            continue
        target_key = f"{target_circuit}.{name}"
        seen_key_folds = {seen_key.casefold() for seen_key in seen_keys}
        if key.casefold() in seen_key_folds or target_key.casefold() in seen_key_folds:
            continue
        map_entry: dict = {
            "circuit": target_circuit,
            "name": name,
            "fields": ["value"],
            "values": [None],
            "writable": meta.writable,
            "has_data": False,
            "from_map": True,
        }
        if not meta.enabled:
            map_entry["disabled"] = True
        if (
            meta.fallback_read
            and not skip_map_probes
            and (target_circuit.casefold(), name.casefold()) not in fallback_read_skip_keys
        ):
            try:
                if ensure_active is not None:
                    ensure_active()
                val = await ebus.read_register(target_circuit, name, raise_transport_errors=True)
                if ensure_active is not None:
                    ensure_active()
                if val:
                    map_entry["values"] = [_redact(val, name)]
                    map_entry["has_data"] = not is_no_data_value(val)
            except HomeAssistantError:
                raise
            except ConnectionError, TimeoutError, OSError:
                raise
            except Exception:
                pass
        register_list.append(map_entry)

    register_list.sort(key=lambda r: (r["circuit"], r["name"]))
    return register_list, seen_keys, raw_lines


# Send a raw grab command to ebusd and collect response lines.
# Intent: close the raw command socket as soon as lifecycle teardown is observed.
# Why: a read may be suspended while HA unloads the config entry.
async def _grab_cmd(
    host: str,
    port: int,
    command: str,
    ensure_active: Callable[[], None] | None = None,
    on_grab_started: Callable[[], None] | None = None,
) -> list[str]:
    if ensure_active is not None:
        ensure_active()
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=GRAB_CONNECT_TIMEOUT)
    try:
        if ensure_active is not None:
            ensure_active()
        writer.write(f"{command}\n".encode())
        await writer.drain()
        if ensure_active is not None:
            ensure_active()
        response = []
        deadline = asyncio.get_running_loop().time() + GRAB_RESPONSE_TIMEOUT
        # ebusd terminates each response with a blank line; limits fail closed if it never arrives.
        for _ in range(GRAB_MAX_RESPONSE_LINES + 1):
            if ensure_active is not None:
                ensure_active()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"ebusd {command} response timed out before its blank-line terminator")
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=remaining)
            except TimeoutError as exc:
                raise TimeoutError(f"ebusd {command} response timed out before its blank-line terminator") from exc
            except ValueError as exc:
                raise HomeAssistantError(f"ebusd {command} response line exceeded the stream limit") from exc
            if not line:
                raise ConnectionError(f"ebusd closed {command} response before its blank-line terminator")
            decoded = line.decode().strip()
            if command == "grab" and not response and decoded.casefold() == "grab started" and on_grab_started:
                on_grab_started()
            if not decoded:
                break
            if len(response) >= GRAB_MAX_RESPONSE_LINES:
                raise HomeAssistantError(
                    f"ebusd {command} response exceeded the {GRAB_MAX_RESPONSE_LINES}-line limit before termination"
                )
            response.append(decoded)
        else:
            raise HomeAssistantError(
                f"ebusd {command} response exceeded the {GRAB_MAX_RESPONSE_LINES}-line limit before termination"
            )
        return response
    finally:
        writer.close()
        await writer.wait_closed()


# Intent: finish the grab-stop command even if the caller is cancelled again.
# Why: ebusd must not keep capturing after HA has unloaded the integration.
async def _stop_grab_uninterruptibly(host: str, port: int) -> list[str]:
    stop_task = asyncio.create_task(_grab_cmd(host, port, "grab stop"))
    interrupted = False
    try:
        while True:
            try:
                stop_response = await asyncio.shield(stop_task)
                break
            except asyncio.CancelledError:
                interrupted = True
                if stop_task.done():
                    stop_response = stop_task.result()
                    break
                current_task = asyncio.current_task()
                if current_task is not None:
                    current_task.uncancel()
    except Exception as exc:
        if interrupted:
            _LOGGER.warning("Failed to stop ebusd grab during cancellation: %s", exc)
            raise asyncio.CancelledError from exc
        raise
    try:
        _validate_grab_stop_response(stop_response)
    except HomeAssistantError as exc:
        _LOGGER.error("ebusd grab stop response was not successful: %s", exc)
        if interrupted:
            raise asyncio.CancelledError from exc
        raise
    if interrupted:
        raise asyncio.CancelledError
    return stop_response


# Intent: validate ebusd grab errors and recognize owned or already-active sessions.
# Why: `_grab_cmd` treats protocol replies as data rather than exceptions.
def _validate_grab_response(command: str, response: list[str]) -> None:
    error = next(
        (line for line in response if line.strip().upper().startswith(("ERR:", "USAGE:"))),
        None,
    )
    if error is not None:
        raise HomeAssistantError(f"ebusd {command} failed: {error}")
    if command == "grab" and len(response) == 1 and response[0].strip().casefold() == "grab continued":
        return
    expected_acknowledgement = {"grab": "grab started", "grab stop": "grab stopped"}.get(command)
    if expected_acknowledgement and (len(response) != 1 or response[0].strip().casefold() != expected_acknowledgement):
        action = "that the grab started" if command == "grab" else "that the grab stopped"
        raise HomeAssistantError(f"ebusd did not confirm {action}: {response}")


# Intent: require ebusd's explicit acknowledgement that raw traffic capture stopped.
# Why: arbitrary non-error text does not prove the bus capture has ended.
def _validate_grab_stop_response(response: list[str]) -> None:
    _validate_grab_response("grab stop", response)


# Intent: validate and index one ebusd grab-result snapshot.
# Why: interval deltas need stable message identities and cumulative counts.
def _validate_grab_result_response(response: list[str]) -> list[GrabResultEntry]:
    _validate_grab_response("grab result all", response)
    if response == ["grab disabled"]:
        raise GrabIntervalUnavailableError("ebusd disabled the global grab during capture")
    entries: list[GrabResultEntry] = []
    for line in response:
        payload, separator, summary = line.partition(" = ")
        request, response_separator, response_data = payload.partition(" / ")
        count_text, label_separator, label = summary.partition(": ")
        count_text = count_text.strip()
        try:
            request_bytes = bytes.fromhex(request.strip())
            response_bytes = bytes.fromhex(response_data.strip()) if response_separator else None
        except ValueError as exc:
            raise HomeAssistantError(f"ebusd grab result all returned an invalid telegram: {line}") from exc
        if (
            not separator
            or len(request_bytes) < 5
            or len(request_bytes) != 5 + request_bytes[4]
            or not count_text.isdecimal()
            or len(count_text) > 20
            or int(count_text) < 1
        ):
            raise HomeAssistantError(f"ebusd grab result all returned an invalid telegram: {line}")
        if response_separator and not response_bytes:
            raise HomeAssistantError(f"ebusd grab result all returned an invalid telegram: {line}")
        if label_separator:
            family = f"known:{request_bytes[1:4].hex()}:{label}"
            key = f"known:{request_bytes.hex()}:{response_bytes.hex() if response_bytes is not None else ''}:{label}"
        else:
            id_length = min(request_bytes[4], 1 if request_bytes[1] == 0xFE else 4)
            id_bytes = request_bytes[5 : 5 + id_length].hex()
            family = f"unknown:{request_bytes[1:4].hex()}:{id_length}:{id_bytes}"
            key = f"unknown:{request_bytes.hex()}:{response_bytes.hex() if response_bytes is not None else ''}"
        entries.append(GrabResultEntry(key, family, int(count_text), line, request_bytes, response_bytes))
    return entries


# Intent: combine counts for ebusd rows with the same visible request/response/label.
# Why: duplicate definitions can expose identical rows while each bus event updates only one internal message key.
def _coalesce_grab_result_entries(entries: list[GrabResultEntry]) -> list[GrabResultEntry]:
    by_key: dict[str, GrabResultEntry] = {}
    for entry in entries:
        previous = by_key.get(entry.key)
        if previous is None:
            by_key[entry.key] = entry
        else:
            by_key[entry.key] = GrabResultEntry(
                entry.key,
                entry.family,
                previous.count + entry.count,
                entry.line,
                entry.request,
                entry.response,
            )
    return list(by_key.values())


# Intent: derive only messages observed between two snapshots of a continued grab.
# Why: ebusd keeps one latest payload and cumulative count per global message key.
def _grab_result_delta(
    baseline: list[GrabResultEntry],
    final: list[GrabResultEntry],
) -> list[str]:
    baseline = _coalesce_grab_result_entries(baseline)
    final = _coalesce_grab_result_entries(final)
    final_by_key = {entry.key: entry for entry in final}
    baseline_families: dict[str, list[GrabResultEntry]] = {}
    final_families: dict[str, list[GrabResultEntry]] = {}
    for entry in baseline:
        baseline_families.setdefault(entry.family, []).append(entry)
    for entry in final:
        final_families.setdefault(entry.family, []).append(entry)

    previous_counts: dict[str, int] = {}
    for family, baseline_entries in baseline_families.items():
        if family not in final_families:
            raise GrabIntervalUnavailableError("ebusd grab baseline message family disappeared during capture")
        final_entries = final_families[family]
        if len(baseline_entries) == 1 and len(final_entries) == 1:
            previous, current = baseline_entries[0], final_entries[0]
            if previous.request[0] != current.request[0]:
                raise GrabIntervalUnavailableError("ebusd grab source address changed during capture")
            previous_counts[current.key] = previous.count
            continue
        final_keys = {entry.key for entry in final_entries}
        for previous in baseline_entries:
            if previous.key not in final_keys:
                raise GrabIntervalUnavailableError("ebusd grab row changed in a multi-row message family")
            current = final_by_key[previous.key]
            if previous.request[0] != current.request[0]:
                raise GrabIntervalUnavailableError("ebusd grab source address changed during capture")
            previous_counts[previous.key] = previous.count

    delta_lines: list[str] = []
    for key, entry in final_by_key.items():
        previous_count = previous_counts.get(key, 0)
        if entry.count < previous_count:
            raise GrabIntervalUnavailableError("ebusd grab counter decreased during capture")
        delta_count = entry.count - previous_count
        if delta_count == 0:
            continue
        payload, _, summary = entry.line.partition(" = ")
        _, label_separator, label = summary.partition(": ")
        suffix = f": {label}" if label_separator else ""
        delta_lines.append(f"{payload} = {delta_count}{suffix}")
    return delta_lines


# Intent: capture raw traffic for a bounded duration without stopping shared auto-grab.
# Why: unload cleans up owned captures, but a continued session belongs to ebusd.
async def async_grab(
    host: str,
    port: int,
    duration: int,
    ensure_active: Callable[[], None] | None = None,
) -> GrabCaptureResult:
    lines: list[str] = []
    grab_started = False
    cancelled = False
    capture_status: Literal["captured", "continued"] = "captured"
    captured_duration = 0.0
    capture_started_at: float | None = None

    # Intent: record an exporter-started grab as soon as ebusd sends its start ACK.
    # Why: the shared protocol has no session ID, so the operator must not mutate grab state during export.
    def _mark_grab_started() -> None:
        nonlocal capture_started_at, grab_started
        grab_started = True
        capture_started_at = asyncio.get_running_loop().time()

    try:
        if ensure_active is not None:
            ensure_active()
        enable_resp = await _grab_cmd(
            host,
            port,
            "grab",
            ensure_active=ensure_active,
            on_grab_started=_mark_grab_started,
        )
        _validate_grab_response("grab", enable_resp)
        grab_started = enable_resp[0].strip().casefold() == "grab started"
        capture_status = "captured" if grab_started else "continued"
        lines.append(f"[grab] {enable_resp[0]}")
        if grab_started and capture_started_at is None:
            capture_started_at = asyncio.get_running_loop().time()
        if ensure_active is not None:
            ensure_active()

        baseline_entries: list[GrabResultEntry] = []
        if capture_status == "continued":
            loop = asyncio.get_running_loop()
            capture_started_at = loop.time()
            baseline_response = await _grab_cmd(host, port, "grab result all", ensure_active=ensure_active)
            if ensure_active is not None:
                ensure_active()
            try:
                baseline_entries = _validate_grab_result_response(baseline_response)
            except HomeAssistantError as exc:
                raise GrabIntervalUnavailableError(f"ebusd grab baseline was unusable: {exc}") from exc
        loop = asyncio.get_running_loop()
        assert capture_started_at is not None
        deadline = capture_started_at + duration
        while True:
            if ensure_active is not None:
                ensure_active()
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(0.25, remaining))

        if ensure_active is not None:
            ensure_active()
        captured_duration = max(0.0, loop.time() - capture_started_at)
        result_resp = await _grab_cmd(host, port, "grab result all", ensure_active=ensure_active)
        if ensure_active is not None:
            ensure_active()
        try:
            result_entries = _validate_grab_result_response(result_resp)
        except HomeAssistantError as exc:
            raise GrabIntervalUnavailableError(f"ebusd grab final snapshot was unusable: {exc}") from exc
        if capture_status == "continued":
            lines.extend(_grab_result_delta(baseline_entries, result_entries))
        else:
            lines.extend(entry.line for entry in result_entries)
    except GrabIntervalUnavailableError as exc:
        if grab_started:
            exc.capture_method = "owned_session"
        raise
    except asyncio.CancelledError:
        cancelled = True
        raise
    except (HomeAssistantError, ConnectionError, EOFError, OSError, TimeoutError, UnicodeError) as exc:
        unavailable = GrabIntervalUnavailableError(f"ebusd grab capture failed: {exc}")
        unavailable.capture_method = (
            "owned_session" if grab_started else "count_delta" if capture_status == "continued" else "none"
        )
        raise unavailable from exc
    finally:
        if grab_started:
            try:
                stop_resp = await _stop_grab_uninterruptibly(host, port)
                lines.append(f"[grab stop] {stop_resp[0]}")
            except HomeAssistantError as exc:
                if cancelled:
                    raise asyncio.CancelledError from exc
                unavailable = GrabIntervalUnavailableError(f"could not stop exporter-started ebusd grab: {exc}")
                unavailable.capture_method = "owned_session"
                raise unavailable from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.error("Failed to stop ebusd grab after capture: %s", exc)
                if cancelled:
                    raise asyncio.CancelledError from exc
                unavailable = GrabIntervalUnavailableError("could not stop exporter-started ebusd grab")
                unavailable.capture_method = "owned_session"
                raise unavailable from exc

    return GrabCaptureResult(tuple(lines), capture_status, captured_duration)


# Intent: track dump exports so config-entry unload can cancel them.
# Why: raw capture and file persistence may outlive platform teardown.
async def async_export_discovery_dump(
    hass: HomeAssistant,
    coordinator: VaillantCoordinator,
    grab_duration: int = 0,
) -> None:
    task = asyncio.current_task()
    active_tasks = getattr(coordinator, "_active_dump_tasks", None)
    if task is not None and isinstance(active_tasks, set):
        active_tasks.add(task)
    try:
        if not coordinator.ebus or not coordinator.ebus.is_connected:
            await _async_export_discovery_dump_impl(hass, coordinator, grab_duration)
            return
        async with _grab_session_lock(
            coordinator.ebusd_host or "",
            coordinator.ebusd_port,
            getattr(coordinator.ebus, "connected_endpoint", None),
        ):
            await _async_export_discovery_dump_impl(hass, coordinator, grab_duration)
    finally:
        if task is not None and isinstance(active_tasks, set):
            active_tasks.discard(task)


# Intent: export a discovery dump only from an authoritative ebusd graph.
# Why: map probes before ownership discovery can poll an assumed circuit.
async def _async_export_discovery_dump_impl(
    hass: HomeAssistant,
    coordinator: VaillantCoordinator,
    grab_duration: int = 0,
) -> None:
    # Intent: stop diagnostic reads when platform teardown starts.
    # Why: dump export can outlive the config-entry unload request.
    def ensure_active() -> None:
        if getattr(coordinator, "_stopped", False) is True or getattr(coordinator, "_unload_requested", False) is True:
            raise HomeAssistantError("Cannot export discovery dump while the integration is unloading.")

    ensure_active()
    ebus = coordinator.ebus
    if not ebus or not ebus.is_connected:
        message = "Cannot export discovery dump because ebusd is not connected."
        _LOGGER.error(message)
        persistent_notification.create(
            hass,
            message,
            title="Vaillant eBUS Discovery Dump Failed",
            notification_id="vaillant_ebus_discovery_dump_error",
        )
        raise HomeAssistantError(message)
    ensure_active()
    if not coordinator.discovery_ready:
        message = "Cannot export discovery dump before ebusd discovery is complete."
        _LOGGER.error(message)
        persistent_notification.create(
            hass,
            message,
            title="Vaillant eBUS Discovery Dump Failed",
            notification_id="vaillant_ebus_discovery_dump_error",
        )
        raise HomeAssistantError(message)

    # Skip ambiguous logical aliases rather than polling a legacy circuit.
    aliases = {
        logical_circuit: coordinator.resolve_register_circuit(logical_circuit)
        for logical_circuit in ("ctlv2", "hmu", "bai", "vwz", "vwzio")
    }
    runtime_definitions = list(coordinator._runtime_definitions.values())
    before_registers, seen, raw_find_lines = await _dump_registers(
        ebus,
        circuit_aliases=aliases,
        ensure_active=ensure_active,
        current_graph=coordinator._graph,
        runtime_definitions=runtime_definitions,
    )
    ensure_active()

    grab_lines: list[str] = []
    grab_status = "not_requested"
    grab_captured_duration = 0.0
    grab_capture_method = "none"
    grab_error: str | None = None
    grab_capture_limitation: str | None = None
    if grab_duration > 0:
        _LOGGER.info("Capturing raw eBUS traffic for %d seconds...", grab_duration)
        try:
            capture = await async_grab(
                coordinator.ebusd_host, coordinator.ebusd_port, grab_duration, ensure_active=ensure_active
            )
            grab_lines = list(capture.lines)
            grab_status = capture.status
            grab_captured_duration = capture.duration
            grab_capture_method = "owned_session" if capture.status == "captured" else "count_delta"
            if capture.status == "continued":
                grab_capture_limitation = GRAB_COUNT_DELTA_LIMITATION
            _LOGGER.info("Captured %d raw lines", len(grab_lines))
        except GrabIntervalUnavailableError as exc:
            grab_status = "skipped_active" if exc.capture_method == "count_delta" else "unavailable"
            grab_capture_method = exc.capture_method
            grab_error = str(exc)
            if exc.capture_method == "count_delta":
                grab_capture_limitation = GRAB_COUNT_DELTA_LIMITATION
            _LOGGER.warning("Raw eBUS capture could not be isolated from the active global grab: %s", exc)
        except HomeAssistantError:
            raise
        except Exception as exc:
            _LOGGER.warning("Grab failed: %s", exc)
            raise HomeAssistantError("Failed to capture raw eBUS traffic.") from exc
        ensure_active()

    after_registers: list[dict] = []
    after_raw_lines: list[str] = []
    has_after_snapshot = grab_duration > 0
    if has_after_snapshot:
        ensure_active()
        after_registers, _, after_raw_lines = await _dump_registers(
            ebus,
            circuit_aliases=aliases,
            ensure_active=ensure_active,
            current_graph=coordinator._graph,
            runtime_definitions=runtime_definitions,
        )

    output_dir = hass.config.path(DOMAIN)
    # Directory creation and the YAML write are ordered inside _persist_dump;
    # a fire-and-forget mkdir here used to race the write.
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filepath = f"{output_dir}/discovery_dump_{timestamp}.yaml"
    ebusd_info = await ebus.get_info()
    ensure_active()

    dump_data: dict = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "ebusd_version": ebus.version,
            "register_count": len(after_registers if has_after_snapshot else before_registers),
            "grab_duration": grab_duration,
            "grab_status": grab_status,
            "grab_captured_duration": grab_captured_duration,
            "grab_capture_method": grab_capture_method,
            "dump_version": CURRENT_DUMP_VERSION,
            "integration_version": INTEGRATION_VERSION,
            "ebusd_info": ebusd_info,
            "ebusd_configuration": {
                "available": False,
                "reason": "ebusd info does not expose addon command-line options or seed_mqtt_cfg",
                "requested_fields": ["seed_mqtt_cfg", "commandline_options"],
            },
        },
        "raw_find_lines": raw_find_lines,
        "before_registers": before_registers,
    }
    if grab_capture_limitation is not None:
        dump_data["metadata"]["grab_capture_limitation"] = grab_capture_limitation
    if grab_error is not None:
        dump_data["metadata"]["grab_error"] = grab_error
    parsed_telegrams = None
    if grab_lines:
        dump_data["grab"] = grab_lines
        try:
            parsed_telegrams = parse_grab_lines(grab_lines)
            dump_data["labeled_telegrams"] = [t for t in parsed_telegrams if t["label"]]
            dump_data["unknown_telegrams"] = unknown_telegrams(parsed_telegrams)
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning("Failed to parse grab telegrams: %s", exc)
    # Recent writes the integration itself sent (register, value, resolved
    # circuit, verification result). Correlates with grab traffic for
    # write-vs-app analysis; empty when nothing was written this session.
    write_log = list(getattr(coordinator, "_write_log", []) or [])
    if write_log:
        dump_data["writes"] = write_log
    if has_after_snapshot:
        dump_data["after_registers"] = after_registers
        dump_data["raw_find_lines_after"] = after_raw_lines

    normalized = normalize_dump(dump_data, parsed_telegrams=parsed_telegrams)
    if grab_lines:
        dump_data["traffic"] = normalized["traffic"]
    dump_data["registers"] = normalized["registers"]
    if has_after_snapshot:
        dump_data["changes"] = normalized["changes"]

    ensure_active()
    await _persist_dump(hass, filepath, dump_data, ensure_active=ensure_active)
    ensure_active()
    _LOGGER.info("Discovery dump written to %s", filepath)

    message = f"Discovery dump written to:<br><code>{filepath}</code><br><br>Captured {len(grab_lines)} raw grab lines."
    if grab_error is not None:
        message += (
            f"<br><br>Raw eBUS capture could not be isolated: {grab_error}. The register snapshot was still saved."
        )
    elif grab_status == "continued":
        message += "<br><br>Used ebusd auto-grab count deltas; only the latest payload per message key is retained."
    persistent_notification.create(
        hass,
        message,
        title="Vaillant eBUS Discovery Dump",
        notification_id="vaillant_ebus_discovery_dump",
    )


# Create output directory if it does not exist
def _mkdir(path: str) -> None:
    import os

    os.makedirs(path, exist_ok=True)


# Intent: discard a staged dump after its executor finishes if its caller was cancelled.
# Why: the temporary path is returned only when the executor job completes.
def _discard_cancelled_dump_write(future: asyncio.Future[str]) -> None:
    try:
        staged_filepath = future.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        _LOGGER.warning("Failed to finish cancelled dump serialization: %s", exc)
        return
    try:
        os.unlink(staged_filepath)
    except FileNotFoundError:
        pass
    except OSError as exc:
        _LOGGER.warning("Failed to remove cancelled dump staging file: %s", exc)


# Ordered persistence: the directory must exist before the YAML write lands.
# Intent: persist the dump only while its coordinator remains active.
# Why: directory creation yields before the YAML write is submitted.
async def _persist_dump(
    hass: HomeAssistant,
    filepath: str,
    dump_data: dict,
    ensure_active: Callable[[], None] | None = None,
) -> None:
    output_dir = os.path.dirname(filepath)
    if ensure_active is not None:
        ensure_active()
    await hass.async_add_executor_job(_mkdir, output_dir)
    if ensure_active is not None:
        ensure_active()
    write_future = asyncio.ensure_future(hass.async_add_executor_job(_write_yaml_temp, filepath, dump_data))
    staged_filepath: str | None = None
    try:
        try:
            staged_filepath = await asyncio.shield(write_future)
        except asyncio.CancelledError:
            write_future.add_done_callback(_discard_cancelled_dump_write)
            raise
        if ensure_active is not None:
            ensure_active()
        os.replace(staged_filepath, filepath)
    finally:
        if staged_filepath is not None and os.path.exists(staged_filepath):
            try:
                os.unlink(staged_filepath)
            except FileNotFoundError:
                pass


# Write YAML dump file with security header
def _write_yaml(filepath: str, data: dict) -> None:
    header = "# Discovery dump for vaillant_ebus\n# Review this file for sensitive information before sharing\n"
    body = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    with open(filepath, "w") as f:
        f.write(header + body)


# Intent: serialize a dump to a unique temporary file beside its final path.
# Why: unload can discard the staged file before atomically publishing it.
def _write_yaml_temp(filepath: str, data: dict) -> str:
    file_descriptor, staged_filepath = tempfile.mkstemp(
        prefix=".discovery_dump_", suffix=".yaml", dir=os.path.dirname(filepath)
    )
    try:
        os.close(file_descriptor)
        _write_yaml(staged_filepath, data)
    except Exception:
        os.unlink(staged_filepath)
        raise
    return staged_filepath
