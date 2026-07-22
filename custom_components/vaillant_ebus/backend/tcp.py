"""TCP backend for ebusd."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .models import EbusdRegister, WriteResult

# ponytail: single-backend, no ABC abstraction needed. Add if a second transport variant materializes.

_LOGGER = logging.getLogger(__name__)

MAX_RECONNECT_DELAY = 60
INITIAL_RECONNECT_DELAY = 1
READ_TIMEOUT = 10
WRITE_TIMEOUT = 10
FIND_TIMEOUT = 30
ERR_PREFIX = "ERR:"
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

    @property
    def connected(self) -> bool:
        # Return whether TCP socket is currently connected
        return self._writer is not None

    @property
    def version(self) -> str | None:
        # Return cached ebusd daemon version string
        return self._version

    # Open TCP connection to ebusd, raise ConnectionError on failure
    async def async_connect(self) -> None:
        if self.connected:
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
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    # Send raw command string to ebusd, return response line
    async def async_send_raw(self, command: str) -> str:
        if not self._writer or not self._reader:
            raise ConnectionError("Not connected")
        data = (command + "\n").encode("utf-8")
        self._writer.write(data)
        await self._writer.drain()
        response = await asyncio.wait_for(self._reader.readline(), timeout=READ_TIMEOUT)
        res = response.decode("utf-8").rstrip("\n\r")
        try:
            await asyncio.wait_for(self._reader.readline(), timeout=0.1)
        except (TimeoutError, ConnectionError):
            pass
        return res

    # Send 'f' command, return raw response lines
    async def _send_find(self) -> list[str]:
        if not self._writer or not self._reader:
            raise ConnectionError("Not connected")
        command = "f\n"
        self._writer.write(command.encode("utf-8"))
        await self._writer.drain()
        lines: list[str] = []
        while True:
            line = await asyncio.wait_for(self._reader.readline(), timeout=FIND_TIMEOUT)
            decoded = line.decode("utf-8").rstrip("\n\r")
            if not decoded:
                break
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
        response = await self.async_send_raw(cmd)
        if response.startswith(ERR_PREFIX):
            _LOGGER.debug("Read error %s.%s: %s", circuit, name, response)
            return None
        return response.strip() or None

    # Write a value to an ebusd register, verify by read-back
    async def async_write(self, circuit: str, name: str, value: str) -> WriteResult:
        cmd = f"write -c {circuit} {name} {value}"
        response = await self.async_send_raw(cmd)
        if response.startswith(ERR_PREFIX):
            return WriteResult(success=False, error_message=response)
        if response.strip() == DONE_STR:
            verified = await self.async_read(circuit, name)
            return WriteResult(success=True, verified_value=verified)
        return WriteResult(success=False, error_message=f"Unexpected response: {response}")

    # Bulk-read multiple register fields from ebusd
    async def async_poll(self, registers: list[tuple[str, str, str]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for circuit, name, field in registers:
            try:
                value = await self.async_read(circuit, name, field)
                if value is not None:
                    result[f"{circuit}.{name}.{field}"] = value
            except Exception as exc:
                _LOGGER.debug("Poll error %s.%s: %s", circuit, name, exc)
        return result

    # Disconnect, backoff-sleep, then reconnect to ebusd
    async def async_reconnect(self) -> None:
        await self.async_disconnect()
        delay = min(self._reconnect_delay, MAX_RECONNECT_DELAY)
        _LOGGER.info("Reconnecting in %ds (attempt %d)", delay, self._reconnect_count + 1)
        await asyncio.sleep(delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, MAX_RECONNECT_DELAY)
        self._reconnect_count += 1
        await self.async_connect()
