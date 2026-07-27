"""TCP backend for ebusd."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from .models import EbusdRegister, SendResult, WriteResult

# ponytail: single-backend, no ABC abstraction needed. Add if a second transport variant materializes.
# ponytail: global lock on async_send_raw serializes all TCP ops.
# Per-circuit or connection-pool locks if throughput matters.

_LOGGER = logging.getLogger(__name__)

MAX_RECONNECT_DELAY = 60
INITIAL_RECONNECT_DELAY = 1
READ_TIMEOUT = 10
DONE_STR = "done"


class EbusdTcpBackend:
    # Initialize TCP backend with host and port
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
    def connected(self) -> bool:
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
    async def async_connect(self) -> None:
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
                raise ConnectionError(f"Failed to connect to {self._host}:{self._port}: {exc}")

    # Close TCP connection cleanly
    async def async_disconnect(self) -> None:
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
    async def async_send_raw(self, command: str) -> SendResult:
        async with self._lock:
            if not self._writer or not self._reader:
                return self._log_cmd(command, SendResult(data="", error="not_connected"))
            await self._drain_stale()
            t0 = time.monotonic()
            data = (command + "\n").encode("utf-8")
            self._writer.write(data)
            await self._writer.drain()
            try:
                response = await asyncio.wait_for(self._reader.readline(), timeout=READ_TIMEOUT)
            except TimeoutError:
                return self._log_cmd(command, SendResult(data="", error="timeout"), t0)
            if not response:
                return self._log_cmd(command, SendResult(data="", error="connection_closed"), t0)
            res = response.decode("utf-8").rstrip("\n\r")
            return self._log_cmd(command, SendResult(data=res), t0)

    def _log_cmd(self, command: str, result: SendResult, t0: float | None = None) -> SendResult:
        duration = int((time.monotonic() - t0) * 1000) if t0 else 0
        self._command_log.append({
            "cmd": command,
            "data": result.data,
            "error": result.error,
            "duration_ms": duration,
        })
        return result

    # Send 'f' command, return raw response lines (multi-line)
    async def _send_find(self) -> list[str]:
        result = await self.async_send_raw("f")
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

    # Discover all registers from ebusd via find command
    async def async_find(self) -> list[EbusdRegister]:
        raw_lines = await self._send_find()
        circuits: dict[str, dict[str, EbusdRegister]] = {}
        for line in raw_lines:
            parsed = self._parse_find_line(line)
            if parsed is None:
                continue
            circuit_name, reg_name, fields, values = parsed
            if circuit_name not in circuits:
                circuits[circuit_name] = {}
            reg = EbusdRegister(
                circuit=circuit_name,
                name=reg_name,
                fields=fields,
                value=values,
                has_data=any(v is not None for v in values.values()),
            )
            circuits[circuit_name][reg_name] = reg
        result: list[EbusdRegister] = []
        for circuit_name in sorted(circuits):
            result.extend(sorted(circuits[circuit_name].values(), key=lambda r: r.name))
        return result

    # Parse a single find response line into circuit, name, fields, values
    @staticmethod
    def _parse_find_line(line: str) -> tuple[str, str, list[str], dict[str, str | None]] | None:
        line = line.strip()
        if not line or "=" not in line:
            return None
        lhs, rhs = line.split("=", 1)
        lhs = lhs.strip()
        rhs = rhs.strip()
        parts = lhs.split(" ", 1)
        circuit_name = parts[0]
        reg_name = parts[1].strip() if len(parts) > 1 else ""
        # Skip empty register names (scan.* lines with no name)
        if reg_name == "":
            return None
        if rhs in ("-", "no data stored", "") or rhs.startswith(("(empty ", "(ERR")):
            return circuit_name, reg_name, ["value"], {"value": None}
        return circuit_name, reg_name, ["value"], {"value": rhs}

    # Read a single register value from ebusd
    async def async_read(self, circuit: str, name: str, field: str = "") -> str | None:
        cmd = f"read -c {circuit} {name}"
        if field:
            cmd += f" {field}"
        result = await self.async_send_raw(cmd)
        if result.error:
            _LOGGER.debug("Read error %s.%s: %s", circuit, name, result.error)
            return None
        return result.data.strip() or None

    # Write a value to an ebusd register, verify by read-back
    async def async_write(self, circuit: str, name: str, value: str) -> WriteResult:
        cmd = f"write -c {circuit} {name} {value}"
        result = await self.async_send_raw(cmd)
        if result.error:
            return WriteResult(success=False, error_message=result.error)
        data = result.data.strip()
        if data and data != DONE_STR:
            return WriteResult(success=False, error_message=f"Unexpected response: {data}")
        verified = await self.async_read(circuit, name)
        if not data and not verified:
            return WriteResult(success=False, error_message="Write verification returned empty")
        return WriteResult(success=True, verified_value=verified)

    # Disconnect, backoff-sleep, then reconnect to ebusd
    async def async_reconnect(self) -> None:
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
                raise ConnectionError(f"Failed to reconnect to {self._host}:{self._port}: {exc}")
