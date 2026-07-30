"""TCP transport service for ebusd communication."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from .models import SendResult, WriteResult

_LOGGER = logging.getLogger("vaillant_ebus.ebus")

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
            if not self._writer or not self._reader:
                return self._log_cmd(cmd, SendResult(data="", error="not_connected"))
            await self._drain_stale()
            t0 = time.monotonic()
            data = (cmd + "\n").encode("utf-8")
            self._writer.write(data)
            await self._writer.drain()
            try:
                response = await asyncio.wait_for(self._reader.readline(), timeout=READ_TIMEOUT)
            except TimeoutError:
                return self._log_cmd(cmd, SendResult(data="", error="timeout"), t0)
            if not response:
                return self._log_cmd(cmd, SendResult(data="", error="connection_closed"), t0)
            res = response.decode("utf-8").rstrip("\n\r")
            return self._log_cmd(cmd, SendResult(data=res), t0)

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

    # Send a complete find command, including conditional and write messages.
    async def _send_find(self) -> list[str]:
        result = await self.send_command("f -a")
        if result.error:
            return []
        async with self._lock:
            lines: list[str] = []
            if result.data.strip():
                lines.append(result.data)
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
        cmd = f'define -r "{definition}"'
        result = await self.send_command(cmd)
        if result.error:
            return f"ERR: {result.error}"
        return result.data.strip()

    # Disconnect, backoff-sleep, then reconnect to ebusd
    async def _reconnect(self) -> None:
        async with self._lock:
            await self._disconnect_nolock()
            delay = min(self._reconnect_delay, MAX_RECONNECT_DELAY)
            _LOGGER.info("Reconnecting in %ds (attempt %d)", delay, self._reconnect_count + 1)
            await asyncio.sleep(delay)
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
            except Exception as exc:
                self._writer = None
                self._reader = None
                raise ConnectionError(f"Failed to reconnect to {self._host}:{self._port}: {exc}") from exc
