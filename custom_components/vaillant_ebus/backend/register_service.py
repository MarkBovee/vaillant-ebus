"""Register parsing, writeability detection, and read/write orchestration."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any

from .ebus_service import EbusService
from .models import WriteResult

_LOGGER = logging.getLogger("vaillant_ebus.register")

PLACEHOLDER_VALUES: frozenset[str] = frozenset({"no data stored", "-", "empty", ""})
SENTINEL_VALUES: frozenset[str] = frozenset({"Open"})


@dataclass
class RegisterValue:
    raw: str
    parsed: Any
    is_placeholder: bool


@dataclass
class Writeability:
    writable: bool
    source: str


@dataclass
class ParsedValue:
    value: Any
    field_type: str
    unit: str | None = None
    is_sentinel: bool = False
    is_placeholder: bool = False


def _parse_find_metadata(data: str) -> dict[str, str]:
    # Parse comma-separated key=value find metadata response into dict
    result: dict[str, str] = {}
    for part in data.split(","):
        kv = part.strip().split("=", 1)
        if len(kv) == 2:
            result[kv[0].strip()] = kv[1].strip()
    return result


class RegisterService:
    def __init__(self, ebus: EbusService) -> None:
        self._ebus = ebus
        self._cache: dict[str, str] = {}

    # Read register via EbusService, parse value, return RegisterValue
    async def read(self, circuit: str, name: str, field_type: str = "") -> RegisterValue:
        cache_key = f"{circuit}.{name}"
        raw = self._cache.get(cache_key)
        if raw is None:
            raw = await self._ebus.read_register(circuit, name)
            if raw is not None:
                self._cache[cache_key] = raw

        if raw is None:
            return RegisterValue(raw="", parsed=None, is_placeholder=True)
        if raw.startswith("ERR:"):
            return RegisterValue(raw=raw, parsed=None, is_placeholder=True)

        parsed = self.parse_value(raw, field_type)
        return RegisterValue(
            raw=raw,
            parsed=parsed.value,
            is_placeholder=parsed.is_placeholder,
        )

    # Write register after writeability check, delegate to EbusService
    async def write(self, circuit: str, name: str, value: str) -> WriteResult:
        if not self._ebus.is_connected:
            return WriteResult(success=False, error_message="Not connected to ebusd")

        writeability = await self.verify_writeability(circuit, name)
        if not writeability.writable:
            return WriteResult(
                success=False,
                error_message=f"Register {circuit}.{name} is read-only per CSV definition",
            )

        result = await self._ebus.write_register(circuit, name, value)
        if result.success:
            _LOGGER.info(
                "Write %s.%s = %s succeeded (verified=%s)",
                circuit, name, value, result.verified_value,
            )
        return result

    # Query ebusd find metadata to determine write permission from CSV flags
    async def verify_writeability(self, circuit: str, name: str) -> Writeability:
        find_result = await self._ebus.send_command(f"find -c {circuit} {name}")
        if find_result.error or not find_result.data:
            return Writeability(writable=False, source="unknown")

        meta = _parse_find_metadata(find_result.data)
        writable = meta.get("writable", "").lower() == "true"
        source = "csv_definition"
        return Writeability(writable=writable, source=source)

    # Parse raw string into typed value based on field_type
    def parse_value(self, raw: str, field_type: str) -> ParsedValue:
        if raw in SENTINEL_VALUES:
            return ParsedValue(value=None, field_type=field_type, is_sentinel=True)
        if raw in PLACEHOLDER_VALUES:
            return ParsedValue(value=None, field_type=field_type, is_placeholder=True)

        ft = field_type.upper() if field_type else ""

        if ft in ("DATA1B", "DATA2C", "EXP"):
            try:
                return ParsedValue(value=float(raw), field_type=field_type)
            except (ValueError, TypeError):
                return ParsedValue(value=None, field_type=field_type, is_placeholder=True)

        if ft == "BCD":
            try:
                date_part = raw.split(" ")[0]
                parts = date_part.split(".")
                if len(parts) == 3:
                    d = int(parts[0])
                    m = int(parts[1])
                    y = int(parts[2])
                    return ParsedValue(value=datetime.date(y, m, d), field_type=field_type)
            except (ValueError, TypeError):
                pass
            return ParsedValue(value=raw, field_type=field_type)

        if ft == "IGN":
            return ParsedValue(value=None, field_type=field_type)

        return ParsedValue(value=raw, field_type=field_type)

    # Restore register values from cache JSON without ebusd reads
    async def hydrate_from_cache(self, cache: dict[str, str]) -> None:
        self._cache.update(cache)
