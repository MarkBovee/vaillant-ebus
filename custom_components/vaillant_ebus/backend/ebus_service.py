"""TCP transport service for ebusd communication."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from .models import SendResult, WriteResult

_LOGGER = logging.getLogger(__name__)

MAX_RECONNECT_DELAY = 60
INITIAL_RECONNECT_DELAY = 1
READ_TIMEOUT = 10
DONE_STR = "done"

EBUSD_STATUS_SUFFIXES = (";ok", ";err", ";inv", ";too_small", ";too_big", ";nan", ";unknown")


# Strip ebusd read status suffix from value (e.g. "23.50;ok" -> "23.50")
def _strip_suffix(value: str) -> str:
    for suffix in EBUSD_STATUS_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


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
        self._reconnect_delay = INITIAL_RECONNECT_DELAY
        self._reconnect_count = 0
        self._reconnecting = False
        self._lock = asyncio.Lock()
        self._command_log: deque[dict] = deque(maxlen=20)

    @property
    def is_connected(self) -> bool:
        # Return whether TCP socket is currently connected
        return self._writer is not None

    @property
    def version(self) -> str | None:
        # Return cached ebusd daemon version string
        return self._version

    @property
    def debug_info(self) -> dict:
        # Return command log and connection state for diagnostics
        return {
            "connected": self._writer is not None,
            "reconnect_count": self._reconnect_count,
            "command_log": list(self._command_log),
        }

    # Open TCP connection to ebusd, raise ConnectionError on failure
    async def connect(self) -> None:
        async with self._lock:
            if self._writer:
                return
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=READ_TIMEOUT,
                )
                self._reconnect_delay = INITIAL_RECONNECT_DELAY
                self._reconnect_count = 0
                _LOGGER.info("Connected to ebusd at %s:%s", self._host, self._port)
            except Exception as exc:
                self._writer = None
                self._reader = None
                raise ConnectionError(f"Failed to connect to {self._host}:{self._port}: {exc}") from exc

    # Close TCP connection cleanly
    async def disconnect(self) -> None:
        async with self._lock:
            await self._disconnect_nolock()

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
            t0 = time.monotonic()
            result = await self._send_line_locked(cmd)
            return self._log_cmd(cmd, result, t0)

    # Drain stale data, send one command, and read its single-line response.
    # Caller must hold _lock for the whole transaction.
    async def _send_line_locked(self, cmd: str) -> SendResult:
        if not self._writer or not self._reader:
            return SendResult(data="", error="not_connected")
        await self._drain_stale()
        data = (cmd + "\n").encode("utf-8")
        self._writer.write(data)
        await self._writer.drain()
        try:
            response = await asyncio.wait_for(self._reader.readline(), timeout=READ_TIMEOUT)
        except TimeoutError:
            return SendResult(data="", error="timeout")
        if not response:
            return SendResult(data="", error="connection_closed")
        return SendResult(data=response.decode("utf-8").rstrip("\n\r"))

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

    # Send a complete find command, holding the lock for the whole multi-line
    # transaction so concurrent commands cannot drain find lines or receive
    # one as their own response.
    async def _send_find(self) -> list[str]:
        async with self._lock:
            if not self._writer or not self._reader:
                self._log_cmd("f -a", SendResult(data="", error="not_connected"))
                return []
            t0 = time.monotonic()
            first = await self._send_line_locked("f -a")
            self._log_cmd("f -a", first, t0)
            if first.error:
                return []
            lines: list[str] = []
            if first.data.strip():
                lines.append(first.data)
            while True:
                try:
                    line = await asyncio.wait_for(self._reader.readline(), timeout=1.0)
                except TimeoutError:
                    break
                if not line:
                    break
                decoded = line.decode("utf-8").rstrip("\n\r")
                lines.append(decoded)
            return lines

    # Return raw find response lines
    async def find_registers(self) -> list[str]:
        return await self._send_find()

    # Read a single register value from ebusd, strip status suffix
    async def read_register(self, circuit: str, name: str, field: str = "") -> str | None:
        _validate_identifier("circuit", circuit)
        _validate_identifier("register name", name)
        if field:
            _validate_identifier("field", field)
        cmd = f"read -c {circuit} {name}"
        if field:
            cmd += f" {field}"
        result = await self.send_command(cmd)
        if result.error:
            _LOGGER.debug("Read error %s.%s: %s", circuit, name, result.error)
            return None
        raw = result.data.strip()
        return _strip_suffix(raw) if raw else None

    # Write a value to an ebusd register, verify by read-back
    async def write_register(self, circuit: str, name: str, value: str) -> WriteResult:
        _validate_identifier("circuit", circuit)
        _validate_identifier("register name", name)
        cmd = f"write -c {circuit} {name} {value}"
        result = await self.send_command(cmd)
        if result.error:
            return WriteResult(success=False, error_message=result.error)
        data = result.data.strip()
        if data and data != DONE_STR:
            return WriteResult(success=False, error_message=f"Unexpected response: {data}")
        verified = await self.read_register(circuit, name)
        if not data and not verified:
            return WriteResult(success=False, error_message="Write verification returned empty")
        if verified and verified.startswith("ERR:"):
            return WriteResult(success=False, error_message=f"Write verification failed: {verified}")
        return WriteResult(success=True, verified_value=verified)

    # Send 'info' command and parse key=value response
    async def get_info(self) -> dict[str, str]:
        result = await self.send_command("info")
        if result.error:
            return {}
        info: dict[str, str] = {}
        data = result.data.strip()
        if not data:
            return info
        for part in data.split(", "):
            pair = part.split(": ", 1)
            if len(pair) == 2:
                info[pair[0].strip()] = pair[1].strip()
        return info

    # Send 'define' command for runtime register definition
    async def define_register(self, definition: str) -> str:
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
        if self._reconnecting:
            return False
        self._reconnecting = True
        try:
            delay = min(self._reconnect_delay, MAX_RECONNECT_DELAY)
            _LOGGER.info("Reconnecting in %ds (attempt %d)", delay, self._reconnect_count + 1)
            await asyncio.sleep(delay)
            async with self._lock:
                await self._disconnect_nolock()
                self._reconnect_delay = min(self._reconnect_delay * 2, MAX_RECONNECT_DELAY)
                self._reconnect_count += 1
                try:
                    self._reader, self._writer = await asyncio.wait_for(
                        asyncio.open_connection(self._host, self._port),
                        timeout=READ_TIMEOUT,
                    )
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
