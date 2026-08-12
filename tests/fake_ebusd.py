"""Fake ebusd TCP server for isolated unit testing.

Reads raw ebusd ``find`` output as fixture data and responds to
commands as a real ebusd would. Supports state, read, write, find,
info, define, and grab commands.

Usage::

    from tests.fake_ebusd import FakeEbusdServer

    async with FakeEbusdServer("arotherm_find.txt") as server:
        # server.port holds the dynamic port
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        w.write(b"state\\n")
        await w.drain()
        line = await r.readline()
        assert b"signal acquired" in line

For pytest fixtures::

    @pytest_asyncio.fixture
    async def fake_ebusd():
        async with FakeEbusdServer() as server:
            yield server
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Sentinel values that indicate "no real data"
SENTINELS = {"-", "no data stored", "no data stored (message not available due to condition)", ""}

SIGNAL_ACQUIRED = "signal acquired: ebusd test fixture v1.0"

# Known multi-field register field names (field order = semicolon order in raw value).
# Source: dumpvalues.json from live ebusd dumps.
MULTI_FIELD_MAP: dict[tuple[str, str], list[str]] = {
    ("hmu", "SetMode"): [
        "hcmode",
        "flowtempdesired",
        "hwctempdesired",
        "hwcflowtempdesired",
        "disablehc",
        "disablehwctapping",
        "disablehwcload",
        "remoteControlHcPump",
        "releaseBackup",
        "releaseCooling",
    ],
    ("hmu", "DateTime"): ["dcfstate", "btime", "bdate", "temp2"],
    ("hmu", "RunStatsCompressorHc"): ["runtime", "cycles"],
    ("hmu", "RunStatsCompressorHwc"): ["runtime", "cycles"],
    ("hmu", "Status01"): ["temp", "temp_1", "temp_2", "temp_3", "temp_4", "pumpstate"],
}


def _last_real_value(lines: list[str]) -> str | None:
    """Return the last non-sentinel value from find output lines."""
    for val in reversed(lines):
        if val not in SENTINELS:
            return val
    return None


def _parse_find_value(line: str) -> str | None:
    """Extract value from a single find line like ``circuit name = value``."""
    line = line.strip()
    if not line or "=" not in line:
        return None
    _, rhs = line.split("=", 1)
    val = rhs.strip()
    if not val or val in SENTINELS or val.startswith("(empty ") or val.startswith("(ERR") or val.startswith("ERR:"):
        return None
    return val


def _parse_find_line_register(line: str) -> tuple[str, str, str | None]:
    """Extract (circuit, name, value) from a find line."""
    line = line.strip()
    if not line or "=" not in line:
        return ("", "", None)
    lhs, rhs = line.split("=", 1)
    parts = lhs.strip().split(" ", 1)
    circuit = parts[0]
    name = parts[1].strip() if len(parts) > 1 else ""
    val = rhs.strip()
    if val in SENTINELS or val.startswith("(empty ") or val.startswith("(ERR") or val.startswith("ERR:"):
        return (circuit, name, None)
    return (circuit, name, val)


def load_discovery_dump(name: str) -> dict:
    """Load a discovery-dump YAML fixture and return its parsed structure.

    Discovery dumps (``discovery_dump_*.yaml``) contain ``metadata``,
    ``raw_find_lines``, ``before_registers``, and optionally ``grab`` /
    ``after_registers``. Fixtures are searched in ``tests/fixtures/``.
    """
    path = Path(name) if name.startswith("/") else FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise ValueError(f"Not a discovery dump YAML file: {path}")
    import yaml

    return yaml.safe_load(path.read_text())


def load_find_lines(name: str) -> list[str]:
    """Load find lines from a fixture file.

    Fixtures are searched in ``tests/fixtures/``. The ``name`` can be:
    - a relative path like ``arotherm_find.txt``
    - a discovery dump YAML like ``community/flexotherm_discovery.yaml``
      (its ``raw_find_lines`` are used)
    - an absolute path
    """
    path = Path(name) if name.startswith("/") else FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    if path.suffix.lower() in (".yaml", ".yml"):
        dump = load_discovery_dump(name)
        raw = dump.get("raw_find_lines") or dump.get("raw_find_lines_after")
        if not raw:
            raise ValueError(f"No raw_find_lines in fixture: {path}")
        return [ln.rstrip("\n\r") for ln in raw if ln.strip()]
    return [ln.rstrip("\n\r") for ln in path.read_text().splitlines() if ln.strip()]


class FakeEbusdServer:
    """Fake ebusd TCP server that responds using pre-recorded fixture data.

    Parameters
    ----------
    fixture :
        Path to raw ``find`` output text file, or list of raw lines.
        Relative paths are resolved under ``tests/fixtures/``.
    host :
        Bind address (default ``127.0.0.1``).
    port :
        Bind port (default ``0`` for dynamic allocation).

    Attributes
    ----------
    host : str
        Bound address.
    port : int
        Bound port (populated after context manager entry).
    """

    def __init__(
        self,
        fixture: str | list[str] = "arotherm_find.txt",
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._host = host
        self._port = port
        self._find_lines = fixture if isinstance(fixture, list) else load_find_lines(fixture)
        self._server: asyncio.AbstractServer | None = None
        self._registers: dict[tuple[str, str], str] = {}
        self._build_register_db()

    def _build_register_db(self) -> None:
        """Parse raw find lines into (circuit, name) -> last_real_value."""
        reg_map: dict[tuple[str, str], list[str]] = defaultdict(list)
        for line in self._find_lines:
            c, n, v = _parse_find_line_register(line)
            if c and n:
                reg_map[(c, n)].append(str(v) if v is not None else "no data stored")
        self._registers = {}
        for key, vals in reg_map.items():
            last_real = _last_real_value(vals)
            if last_real is not None:
                self._registers[key] = last_real

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def register_count(self) -> int:
        return len(self._registers)

    async def start(self) -> None:
        """Start the TCP server on the configured host:port."""
        self._server = await asyncio.start_server(self._handle_client, host=self._host, port=self._port)
        if self._server.sockets:
            self._port = self._server.sockets[0].getsockname()[1]
        _LOGGER.debug("Fake ebusd listening on %s:%s", self._host, self._port)

    async def stop(self) -> None:
        """Stop the TCP server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def __aenter__(self) -> FakeEbusdServer:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single TCP client connection."""
        peer = writer.get_extra_info("peername")
        _LOGGER.debug("Client connected: %s", peer)
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=30)
                if not line:
                    break
                raw = line.decode("utf-8").strip()
                if not raw:
                    continue

                # find/f command: dump all fixture lines directly
                # Client reads them line by line with timeout loop
                if raw in ("f", "find", "f -a", "find -a"):
                    for fline in self._find_lines:
                        writer.write((fline + "\n").encode())
                    await writer.drain()
                    # No explicit response — find output IS the response
                    continue

                response = self._handle_command(raw)
                writer.write((response + "\n").encode())
                await writer.drain()
        except TimeoutError, ConnectionError, OSError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    def _handle_command(self, cmd: str) -> str:
        """Parse a single ebusd command and return the response string."""
        parts = cmd.split()
        if not parts:
            return "ERR: empty command"

        command = parts[0].lower()

        if command == "state":
            return SIGNAL_ACQUIRED

        if command == "info" or command == "i":
            return self._handle_info(parts)

        if command in ("read", "r"):
            return self._handle_read(parts)

        if command in ("write", "w"):
            return self._handle_write(parts)

        if command in ("find", "f"):
            return self._handle_find(parts)

        if command == "define":
            return "done"

        if command == "grab":
            return "grab enabled"

        if command == "scan":
            return "scan: finished"

        return f"ERR: unknown command: {command}"

    def _handle_info(self, parts: list[str]) -> str:
        return "version: ebusd 26.1.p20260503 (fake)"

    def _handle_read(self, parts: list[str]) -> str:
        """Handle ``read [-c circuit] name [field]``."""
        rest = parts[1:] if len(parts) > 1 else []
        circuit = ""
        name = ""
        field: str | None = None

        idx = 0
        while idx < len(rest):
            if rest[idx] == "-c" and idx + 1 < len(rest):
                circuit = rest[idx + 1]
                idx += 2
            elif field is None and name and not circuit:
                name = rest[idx]
                idx += 1
            elif name:
                field = rest[idx]
                idx += 1
            else:
                name = rest[idx]
                idx += 1

        if not circuit:
            if "." in name:
                circuit, name = name.split(".", 1)
            elif not circuit:
                circuit = parts[1] if len(parts) > 1 else ""

        if not circuit or not name:
            return "ERR: missing circuit or name"

        key = (circuit, name)
        val = self._registers.get(key)
        if val is None:
            return ""

        if field:
            return self._extract_field(val, circuit, name, field)
        return val

    @staticmethod
    def _extract_field(raw_val: str, circuit: str, name: str, field: str) -> str:
        """Extract a named field from a multi-field semicolon-separated value."""
        field_names = MULTI_FIELD_MAP.get((circuit, name))
        if field_names is None:
            return raw_val
        parts_val = raw_val.split(";")
        try:
            idx = field_names.index(field)
        except ValueError:
            return raw_val
        if idx >= len(parts_val):
            return ""
        return parts_val[idx]

    def _handle_write(self, parts: list[str]) -> str:
        """Handle ``write [-c circuit] name value...``."""
        rest = parts[1:] if len(parts) > 1 else []
        circuit = ""
        name = ""
        value_parts: list[str] = []

        idx = 0
        while idx < len(rest):
            if rest[idx] == "-c" and idx + 1 < len(rest):
                circuit = rest[idx + 1]
                idx += 2
            elif not name:
                name = rest[idx]
                idx += 1
            else:
                value_parts.append(rest[idx])
                idx += 1

        if not circuit and "_" in name and "." in name:
            circuit, name = name.split(".", 1)

        if not circuit or not name:
            return "ERR: missing circuit or name"

        value = " ".join(value_parts) if value_parts else ""
        if not value:
            return "ERR: missing value"

        self._registers[(circuit, name)] = value
        return "done"

    def _handle_find(self, parts: list[str]) -> str:
        """Handle ``find -c <circuit> <name>`` — single register metadata."""
        rest = parts[1:] if len(parts) > 1 else []
        circuit = ""
        name = ""
        idx = 0
        while idx < len(rest):
            if rest[idx] == "-c" and idx + 1 < len(rest):
                circuit = rest[idx + 1]
                idx += 2
            elif not name:
                name = rest[idx]
                idx += 1
            else:
                idx += 1
        if circuit and name:
            key = (circuit, name)
            val = self._registers.get(key, "no data stored")
            return f"name={name}, circuit={circuit}, value={val}, writable=true"
        return "ERR: missing circuit or name"
