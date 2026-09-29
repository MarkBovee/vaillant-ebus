"""TCP transport service for ebusd communication."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import TypedDict

from .discovery_service import has_usable_find_records
from .models import SendResult, WriteResult

_LOGGER = logging.getLogger(__name__)

MAX_RECONNECT_DELAY = 60
INITIAL_RECONNECT_DELAY = 1
READ_TIMEOUT = 10
MULTILINE_RESPONSE_TIMEOUT = 1.0
MULTILINE_RESPONSE_MAX_DURATION = 60
MULTILINE_RESPONSE_MAX_LINES = 10_000
DONE_STR = "done"
# ebusd serves `read` from its cache unless forced; a freshly written value is
# cached by the write itself. Re-read once from the bus before treating a
# mismatch as an unapplied write, so a controller that applies the value just
# after the bus ack is not reported as a failure.
WRITE_VERIFY_RETRY_DELAY = 0.25

EBUSD_STATUS_SUFFIXES = (";ok", ";err", ";inv", ";too_small", ";too_big", ";nan", ";unknown")


class CommandLogEntry(TypedDict):
    cmd: str
    data: str
    error: str | None
    duration_ms: int


# Strip ebusd read status suffix from value (e.g. "23.50;ok" -> "23.50")
def _strip_suffix(value: str) -> str:
    for suffix in EBUSD_STATUS_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


# Normalize a register value for write/read-back comparison. ebusd echoes
# multi-field registers with ";" separators while callers write them with
# spaces, and numeric fields may gain or lose trailing zeros. Split on either
# separator and compare field-wise so only real value changes are flagged.
def _value_tokens(value: str) -> list[str]:
    return [tok for tok in value.replace(";", " ").split() if tok]


# Compare a written value against the ebusd read-back, tolerating separator
# and numeric-format differences but not actual value changes. Used to detect
# writes that ebusd accepted but did not apply (e.g. HwcSFMode stays "load"
# after writing "auto" while a boost cycle is still running).
def _values_match(written: str, read_back: str) -> bool:
    written_tokens = _value_tokens(written)
    read_tokens = _value_tokens(read_back)
    if len(written_tokens) != len(read_tokens):
        return False
    for expected, actual in zip(written_tokens, read_tokens):
        if expected == actual:
            continue
        try:
            if float(expected) == float(actual):
                continue
        except ValueError:
            pass
        return False
    return True


# Parse ebusd 'info' response into key/value pairs. ebusd returns newline-
# separated "key: value" lines; some lines bundle a second pair after ", ".
AddressConfig = dict[str, str | list[str]]


def _parse_info_data(data: str) -> dict[str, str | dict[str, AddressConfig]]:
    info: dict[str, str | dict[str, AddressConfig]] = {}
    for line in data.splitlines():
        for part in line.split(", "):
            pair = part.split(": ", 1)
            if len(pair) == 2:
                info[pair[0].strip()] = pair[1].strip()
    loaded = _parse_address_configs(data)
    if loaded:
        info["loaded_configs"] = loaded
    return info


# Extract per-address load information from the ebusd 'info' output. Each
# "address NN:" line lists the scanned identity and the CSV/include files the
# configuration actually loaded for that slave, e.g.:
#   address 08: slave #11, scanned "MF=Vaillant;ID=BAI00;SW=0503;HW=9602",
#     loaded "vaillant/bai.0010015600.inc", "vaillant/08.bai.csv"
# Returns {address: {"role": ..., "scanned": ..., "loaded": [...]}}. This is
# what tells us which register layout (e.g. 15.700.csv vs 15.ctlv2.csv) the
# installed ebusd-configuration really applies to each device.
def _parse_address_configs(data: str) -> dict[str, AddressConfig]:
    configs: dict[str, AddressConfig] = {}
    for line in data.splitlines():
        if not line.startswith("address "):
            continue
        address, _, rest = line[len("address ") :].partition(": ")
        if not address:
            continue
        entry: AddressConfig = {}
        scanned = _extract_quoted(rest, "scanned ")
        if scanned:
            entry["scanned"] = scanned
        loaded_index = rest.find("loaded ")
        if loaded_index >= 0:
            loaded: list[str] = []
            for token in rest[loaded_index:].split('"'):
                token = token.strip()
                if token.endswith((".csv", ".inc")) and token not in loaded:
                    loaded.append(token)
            if loaded:
                entry["loaded"] = loaded
        role = rest.split(",", 1)[0].strip()
        if role:
            entry["role"] = role
        if entry:
            configs[address] = entry
    return configs


# Return the value of the first quoted token following a marker on a line.
def _extract_quoted(line: str, marker: str) -> str:
    start = line.find(marker)
    if start < 0:
        return ""
    rest = line[start + len(marker) :]
    quote = rest.find('"')
    if quote < 0:
        return ""
    end = rest.find('"', quote + 1)
    if end < 0:
        return ""
    return rest[quote + 1 : end]


# Reject empty identifiers and CR/LF injection at the backend boundary, before
# they are interpolated into protocol commands. Spaces and semicolons remain
# valid inside register names and values (ebusd syntax).
def _validate_identifier(kind: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ebusd {kind} must be a non-empty string")
    if "\r" in value or "\n" in value:
        raise ValueError(f"ebusd {kind} must not contain line breaks")


class EbusService:
    # Initialize TCP service with host and port
    def __init__(self, host: str = "192.168.1.100", port: int = 8888) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._version: str | None = None
        self._last_find_usable: bool | None = None
        self._reconnect_delay = INITIAL_RECONNECT_DELAY
        self._reconnect_count = 0
        self._reconnecting = False
        self._shutdown_requested = False
        self._lock = asyncio.Lock()
        self._command_log: deque[CommandLogEntry] = deque(maxlen=20)

    @property
    def is_connected(self) -> bool:
        # Return whether TCP socket is currently connected
        return self._writer is not None

    # Intent: expose the active TCP peer so dump locking uses the connected daemon identity.
    # Why: DNS aliases may differ even when they reach the same ebusd process.
    @property
    def connected_endpoint(self) -> tuple[str, int] | None:
        if self._writer is None:
            return None
        peer = self._writer.get_extra_info("peername")
        if not isinstance(peer, tuple) or len(peer) < 2 or not isinstance(peer[0], str):
            return None
        try:
            return peer[0].casefold(), int(peer[1])
        except TypeError, ValueError:
            return None

    @property
    def version(self) -> str | None:
        # Return cached ebusd daemon version string
        return self._version

    # Intent: expose whether the most recent find contained a usable row.
    # Why: an empty/error-only response is distinct from both transport failure and discovery success.
    @property
    def last_find_usable(self) -> bool | None:
        return self._last_find_usable

    @property
    def debug_info(self) -> dict[str, object]:
        # Return command log and connection state for diagnostics
        return {
            "connected": self._writer is not None,
            "reconnect_count": self._reconnect_count,
            "command_log": list(self._command_log),
        }

    # Open TCP connection to ebusd, raise ConnectionError on failure
    async def connect(self) -> None:
        if self._shutdown_requested:
            raise ConnectionError("shutdown requested")
        async with self._lock:
            if self._shutdown_requested:
                raise ConnectionError("shutdown requested")
            if self._writer:
                return
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=READ_TIMEOUT,
                )
                if self._shutdown_requested:
                    await self._disconnect_nolock()
                    raise ConnectionError("shutdown requested")
                self._reconnect_delay = INITIAL_RECONNECT_DELAY
                self._reconnect_count = 0
                _LOGGER.info("Connected to ebusd at %s:%s", self._host, self._port)
                try:
                    info_result = await self._send_line_locked("info")
                    parsed = _parse_info_data(info_result.data)
                    version = parsed.get("version")
                    if isinstance(version, str) and version:
                        self._version = version
                except Exception:
                    self._version = None
            except Exception as exc:
                self._writer = None
                self._reader = None
                raise ConnectionError(f"Failed to connect to {self._host}:{self._port}: {exc}") from exc

    # Close TCP connection cleanly
    async def disconnect(self) -> None:
        async with self._lock:
            await self._disconnect_nolock()

    # Intent: prevent a pending reconnect from opening a socket after unload.
    # Why: disconnect alone cannot cancel a reconnect that is sleeping outside the lock.
    def request_shutdown(self) -> None:
        self._shutdown_requested = True

    # Intent: allow a failed Home Assistant platform unload to resume normally.
    # Why: a temporary unload failure must not permanently disable the coordinator.
    def clear_shutdown_request(self) -> None:
        self._shutdown_requested = False

    # Disconnect without acquiring the lock (caller must hold _lock)
    async def _disconnect_nolock(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    # Drain stale data from socket to prevent polluting next response
    async def _drain_stale(self) -> None:
        if not self._reader:
            return
        while True:
            try:
                stale = await asyncio.wait_for(self._reader.readline(), timeout=0.05)
                if not stale:
                    break
            except TimeoutError:
                break

    # Send raw command string to ebusd, return SendResult
    async def send_command(self, cmd: str) -> SendResult:
        async with self._lock:
            if self._shutdown_requested:
                return SendResult(data="", error="shutdown_requested")
            t0 = time.monotonic()
            result = await self._send_line_locked(cmd)
            return self._log_cmd(cmd, result, t0)

    # Intent: send one serialized command and clear the socket after EOF or timeout.
    # Why: later operations must not reuse a TCP stream that stopped returning lines.
    # Drain stale data, send one command, and read its single-line response.
    # Caller must hold _lock for the whole transaction.
    async def _send_line_locked(self, cmd: str) -> SendResult:
        if not self._writer or not self._reader:
            return SendResult(data="", error="not_connected")
        try:
            await self._drain_stale()
            if self._shutdown_requested:
                return SendResult(data="", error="shutdown_requested")
            data = (cmd + "\n").encode("utf-8")
            self._writer.write(data)
            await self._writer.drain()
        except (ConnectionError, OSError) as exc:
            await self._disconnect_nolock()
            return SendResult(data="", error=f"connection_closed: {exc}")
        except ValueError as exc:
            await self._disconnect_nolock()
            return SendResult(data="", error=f"invalid_response_line: {exc}")
        try:
            response = await asyncio.wait_for(self._reader.readline(), timeout=READ_TIMEOUT)
        except TimeoutError:
            await self._disconnect_nolock()
            return SendResult(data="", error="timeout")
        except (ConnectionError, OSError) as exc:
            await self._disconnect_nolock()
            return SendResult(data="", error=f"connection_closed: {exc}")
        except (ValueError, UnicodeDecodeError) as exc:
            await self._disconnect_nolock()
            return SendResult(data="", error=f"invalid_response_line: {exc}")
        if not response:
            await self._disconnect_nolock()
            return SendResult(data="", error="connection_closed")
        try:
            decoded = response.decode("utf-8").rstrip("\n\r")
        except UnicodeDecodeError as exc:
            await self._disconnect_nolock()
            return SendResult(data="", error=f"invalid_response_line: {exc}")
        return SendResult(data=decoded)

    # Record command in ring-buffer log with duration for diagnostics
    def _log_cmd(self, command: str, result: SendResult, t0: float | None = None) -> SendResult:
        duration = int((time.monotonic() - t0) * 1000) if t0 else 0
        self._command_log.append(
            {
                "cmd": command,
                "data": result.data,
                "error": result.error,
                "duration_ms": duration,
            }
        )
        return result

    # Intent: collect multi-line responses and report EOF before the quiet terminator.
    # Why: a truncated find/info response must not be treated as a complete result.
    # Send one command and collect every response line until ebusd goes quiet.
    # Holds the lock for the whole multi-line transaction so concurrent
    # commands cannot drain these lines or receive one as their own response.
    # Multi-line responses (find, info) must be read to completion: leaving
    # lines buffered would pollute the next command's read.
    async def _send_lines_locked(self, cmd: str) -> list[str]:
        if not self._writer or not self._reader:
            self._log_cmd(cmd, SendResult(data="", error="not_connected"))
            return []
        t0 = time.monotonic()
        deadline = asyncio.get_running_loop().time() + MULTILINE_RESPONSE_MAX_DURATION
        remaining = deadline - asyncio.get_running_loop().time()
        try:
            first = await asyncio.wait_for(self._send_line_locked(cmd), timeout=remaining)
        except TimeoutError as exc:
            await self._disconnect_nolock()
            self._log_cmd(cmd, SendResult(data="", error="response_timeout"), t0)
            raise TimeoutError(f"ebusd {cmd} exceeded the total response deadline") from exc
        self._log_cmd(cmd, first, t0)
        if first.error:
            return []
        lines: list[str] = []
        try:
            if first.data.strip():
                if len(lines) >= MULTILINE_RESPONSE_MAX_LINES:
                    await self._disconnect_nolock()
                    self._command_log[-1]["error"] = "response_too_large"
                    raise ConnectionError(
                        f"ebusd {cmd} response exceeded the {MULTILINE_RESPONSE_MAX_LINES}-line limit"
                    )
                lines.append(first.data)
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    await self._disconnect_nolock()
                    self._command_log[-1]["error"] = "response_timeout"
                    raise TimeoutError(f"ebusd {cmd} exceeded the total response deadline")
                try:
                    line = await asyncio.wait_for(
                        self._reader.readline(), timeout=min(MULTILINE_RESPONSE_TIMEOUT, remaining)
                    )
                except TimeoutError:
                    if asyncio.get_running_loop().time() >= deadline:
                        await self._disconnect_nolock()
                        self._command_log[-1]["error"] = "response_timeout"
                        raise TimeoutError(f"ebusd {cmd} exceeded the total response deadline")
                    break
                except (ConnectionError, OSError) as exc:
                    await self._disconnect_nolock()
                    self._command_log[-1]["error"] = f"connection_closed: {exc}"
                    raise ConnectionError(f"ebusd connection failed while reading {cmd}: {exc}") from exc
                except ValueError as exc:
                    await self._disconnect_nolock()
                    self._command_log[-1]["error"] = "invalid_response_line"
                    raise ConnectionError(f"ebusd returned an invalid response line for {cmd}: {exc}") from exc
                if not line:
                    await self._disconnect_nolock()
                    self._command_log[-1]["error"] = "connection_closed"
                    raise ConnectionError(f"ebusd connection closed while reading {cmd}")
                try:
                    decoded = line.decode("utf-8").rstrip("\n\r")
                except UnicodeDecodeError as exc:
                    await self._disconnect_nolock()
                    self._command_log[-1]["error"] = "invalid_response_line"
                    raise ConnectionError(f"ebusd returned an invalid response line for {cmd}: {exc}") from exc
                if len(lines) >= MULTILINE_RESPONSE_MAX_LINES:
                    await self._disconnect_nolock()
                    self._command_log[-1]["error"] = "response_too_large"
                    raise ConnectionError(
                        f"ebusd {cmd} response exceeded the {MULTILINE_RESPONSE_MAX_LINES}-line limit"
                    )
                lines.append(decoded)
        finally:
            self._command_log[-1]["duration_ms"] = int((time.monotonic() - t0) * 1000)
        return lines

    # Intent: record when a completed find contains no usable register or scan rows.
    # Why: an empty response is not TCP failure, but it cannot prove discovery recovered.
    async def _send_find(self) -> list[str]:
        async with self._lock:
            self._last_find_usable = None
            lines = await self._send_lines_locked("f -a")
            result = self._command_log[-1]
            if result["cmd"] == "f -a" and result["error"]:
                if result["error"] == "timeout":
                    raise TimeoutError("ebusd find command timed out")
                raise ConnectionError(f"ebusd find command failed: {result['error']}")
            try:
                self._last_find_usable = has_usable_find_records(lines)
            except ValueError as exc:
                self._last_find_usable = False
                await self._disconnect_nolock()
                self._command_log[-1]["error"] = "malformed_find_response"
                raise ConnectionError(f"ebusd returned a malformed find response: {exc}") from exc
            if not self._last_find_usable:
                self._command_log[-1]["error"] = "no_usable_lines"
                return lines
            return lines

    # Intent: propagate incomplete `info` transport responses instead of returning a success-shaped empty banner.
    # Why: discovery dumps must not save as complete when the ebusd metadata read failed.
    # Send 'info' and return every banner line. ebusd lists the per-address
    # loaded CSV/include files after the version line, so get_info needs the
    # whole response rather than the first line only.
    async def _send_info(self) -> list[str]:
        async with self._lock:
            lines = await self._send_lines_locked("info")
            result = self._command_log[-1]
            if result["cmd"] == "info" and result["error"]:
                if result["error"] == "timeout":
                    raise TimeoutError("ebusd info command timed out")
                raise ConnectionError(f"ebusd info command failed: {result['error']}")
            return lines

    # Return raw find response lines
    async def find_registers(self) -> list[str]:
        return await self._send_find()

    # Intent: read a register value and optionally surface transport errors to pollers.
    # Why: unsupported values are unavailable data, while TCP failures need a reconnect.
    # Read a single register value from ebusd, strip status suffix. By default
    # ebusd may answer from its cache; force=True adds "-f" so an active-read
    # register is queried from the device instead (used to verify writes).
    async def read_register(
        self,
        circuit: str,
        name: str,
        field: str = "",
        force: bool = False,
        raise_transport_errors: bool = False,
    ) -> str | None:
        _validate_identifier("circuit", circuit)
        _validate_identifier("register name", name)
        if field:
            _validate_identifier("field", field)
        cmd = f"read -f -c {circuit} {name}" if force else f"read -c {circuit} {name}"
        if field:
            cmd += f" {field}"
        result = await self.send_command(cmd)
        if result.error:
            _LOGGER.debug("Read error %s.%s: %s", circuit, name, result.error)
            if raise_transport_errors:
                await self.disconnect()
                if result.error == "timeout":
                    raise TimeoutError(f"ebusd read timed out for {circuit}.{name}")
                raise ConnectionError(f"ebusd read failed for {circuit}.{name}: {result.error}")
            return None
        raw = result.data.strip()
        return _strip_suffix(raw) if raw else None

    # Write a value to an ebusd register, verify by a forced bus read-back.
    # The read-back bypasses ebusd's cache because ebusd stores the written
    # value in that cache during the write, which would make a cached read
    # always "verify" a write the controller never applied. Each failed or
    # empty read is retried once after a short delay, so a controller that
    # applies the write just after the bus ack still succeeds.
    #
    # strict_verify=True requires the controller to confirm the written value;
    # an unreadable or mismatching read-back fails the write. strict_verify=False
    # accepts the write when ebusd acknowledged it, and only warns when the
    # controller does not confirm it (e.g. HwcSFMode keeps reporting "load"
    # while the cylinder finishes charging after boost is turned off, or a
    # write-only register has no read message to verify against).
    async def write_register(self, circuit: str, name: str, value: str, strict_verify: bool = True) -> WriteResult:
        if self._shutdown_requested:
            return WriteResult(success=False, error_message="shutdown requested")
        if "\r" in value or "\n" in value:
            return WriteResult(success=False, error_message="register value must not contain line breaks")
        _validate_identifier("circuit", circuit)
        _validate_identifier("register name", name)
        cmd = f"write -c {circuit} {name} {value}"
        result = await self.send_command(cmd)
        if result.error:
            return WriteResult(success=False, error_message=result.error)
        data = result.data.strip()
        if data and data != DONE_STR:
            return WriteResult(success=False, error_message=f"Unexpected response: {data}")
        verified = await self.read_register(circuit, name, force=True)
        if strict_verify and (not verified or verified.startswith("ERR:")):
            # No usable answer on the first post-write read. Retry once; idle
            # heat-pump registers can return no data on the first attempt. A
            # non-strict write needs no confirmation, so it skips the retry.
            await asyncio.sleep(WRITE_VERIFY_RETRY_DELAY)
            retry = await self.read_register(circuit, name, force=True)
            if retry and not retry.startswith("ERR:"):
                verified = retry
        if not verified or verified.startswith("ERR:"):
            # A write-only register has no read message, so an unreadable
            # read-back is not proof the write failed. Only strict callers
            # require the controller to confirm the value.
            _LOGGER.warning(
                "Write verification unreadable %s.%s: wrote %r, read back %r",
                circuit,
                name,
                value,
                verified,
            )
            if strict_verify:
                return WriteResult(
                    success=False,
                    error_message=f"Write verification failed: wrote {value!r}, read back {verified!r}",
                )
            return WriteResult(success=True, verified_value=None)
        if not _values_match(value, verified):
            await asyncio.sleep(WRITE_VERIFY_RETRY_DELAY)
            retry = await self.read_register(circuit, name, force=True)
            if retry and not retry.startswith("ERR:") and _values_match(value, retry):
                verified = retry
            else:
                _LOGGER.warning(
                    "Write verification mismatch %s.%s: wrote %r, read back %r",
                    circuit,
                    name,
                    value,
                    verified,
                )
                if strict_verify:
                    return WriteResult(
                        success=False,
                        error_message=f"Write verification mismatch: wrote {value!r}, read back {verified!r}",
                    )
        _LOGGER.debug("Write %s.%s=%r acked, verification read-back %r", circuit, name, value, verified)
        return WriteResult(success=True, verified_value=verified)

    # Send 'info' command and parse the full multi-line banner
    async def get_info(self) -> dict[str, str | dict[str, AddressConfig]]:
        lines = await self._send_info()
        if not lines:
            return {}
        return _parse_info_data("\n".join(lines))

    # Send 'define' command for runtime register definition
    async def define_register(self, definition: str) -> str:
        if self._shutdown_requested:
            return "ERR: shutdown requested"
        if not isinstance(definition, str) or not definition.strip():
            raise ValueError("ebusd register definition must be a non-empty string")
        if "\r" in definition or "\n" in definition:
            raise ValueError("ebusd register definition must not contain line breaks")
        cmd = f'define -r "{definition}"'
        result = await self.send_command(cmd)
        if result.error:
            return f"ERR: {result.error}"
        return result.data.strip()

    # Disconnect, backoff-sleep outside the lock, then reconnect to ebusd.
    # Returns True when this call actually dialed, False when a concurrent
    # reconnect was already in flight (callers must not treat the skip as a
    # restored connection). The disconnect is unconditional because transport
    # failures leave a stale writer behind that must be cleared before dialing.
    async def _reconnect(self) -> bool:
        if self._shutdown_requested or self._reconnecting:
            return False
        self._reconnecting = True
        try:
            delay = min(self._reconnect_delay, MAX_RECONNECT_DELAY)
            _LOGGER.info("Reconnecting in %ds (attempt %d)", delay, self._reconnect_count + 1)
            await asyncio.sleep(delay)
            if self._shutdown_requested:
                return False
            async with self._lock:
                if self._shutdown_requested:
                    return False
                await self._disconnect_nolock()
                self._reconnect_delay = min(self._reconnect_delay * 2, MAX_RECONNECT_DELAY)
                self._reconnect_count += 1
                try:
                    self._reader, self._writer = await asyncio.wait_for(
                        asyncio.open_connection(self._host, self._port),
                        timeout=READ_TIMEOUT,
                    )
                    if self._shutdown_requested:
                        await self._disconnect_nolock()
                        return False
                    self._reconnect_delay = INITIAL_RECONNECT_DELAY
                    self._reconnect_count = 0
                    _LOGGER.info("Reconnected to ebusd at %s:%s", self._host, self._port)
                    return True
                except Exception as exc:
                    self._writer = None
                    self._reader = None
                    raise ConnectionError(f"Failed to reconnect to {self._host}:{self._port}: {exc}") from exc
        finally:
            self._reconnecting = False
