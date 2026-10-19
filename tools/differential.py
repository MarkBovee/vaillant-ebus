#!/usr/bin/env python3
"""Behaviour-equality harness: dump what the integration decides for every community fixture, then compare two trees.

    PYTHONHASHSEED=0 python tools/differential.py dump <tree> <out.json>
    python tools/differential.py compare <a.json> <b.json> [--limit N]

`dump` records, for every community discovery fixture (raw and post-define find lines), the runtime `define` strings the
coordinator sends, the registers it withholds, the active reads it plans (all answered with no value) and the entity
descriptions the factory generates, plus the full REGISTER_MAP and MULTI_FIELD_FIELDS. Two checkouts behave the same
for those decisions when their JSON files are identical. Run it with `PYTHONHASHSEED=0`: placeholder registers are a
set, and without a fixed seed only the order of the read lists differs between runs. The coordinator clock is frozen
at 2026-01-15 12:00, because the day and month energy registers carry the date in their message id.

It covers the pure builders, not the coordinator lifecycle, repairs, cleanup, config flow or writes. Use it to prove
that a refactor or a merge kept the decisions, as done for the 1.12.0 structure merge (58 fixtures, byte-identical).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock


# Intent: turn a dataclass, container or scalar into JSON-safe data with a stable order for sets.
# Why: two dumps are compared byte for byte, so the same decision must always serialise the same way.
def plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [plain(item) for item in value]
        return sorted(items, key=json.dumps) if isinstance(value, (set, frozenset)) else items
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


# Intent: record the differences between two decoded dumps as readable lines and a count per top-level section.
# Why: a failed comparison must show where the trees diverge, not only that they do.
def diff_dumps(left: Any, right: Any) -> tuple[list[str], Counter[str]]:
    lines: list[str] = []
    counts: Counter[str] = Counter()

    def section(path: str) -> str:
        parts = path.split("/")
        return parts[1] if len(parts) > 1 else path

    def walk(a: Any, b: Any, path: str) -> None:
        if type(a) is not type(b):
            lines.append(f"{path}: type {type(a).__name__} vs {type(b).__name__}")
            counts[section(path)] += 1
        elif isinstance(a, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a:
                    lines.append(f"{path}/{key}: only in the second -> {json.dumps(b[key])[:140]}")
                    counts[section(f"{path}/{key}")] += 1
                elif key not in b:
                    lines.append(f"{path}/{key}: only in the first -> {json.dumps(a[key])[:140]}")
                    counts[section(f"{path}/{key}")] += 1
                else:
                    walk(a[key], b[key], f"{path}/{key}")
        elif isinstance(a, list):
            if a != b:
                only_a = [item for item in a if item not in b]
                only_b = [item for item in b if item not in a]
                if only_a or only_b:
                    lines.append(
                        f"{path}: first-only {json.dumps(only_a)[:200]} | second-only {json.dumps(only_b)[:200]}"
                    )
                else:
                    lines.append(f"{path}: same items, different order ({len(a)} items)")
                counts[section(path)] += 1
        elif a != b:
            lines.append(f"{path}: {json.dumps(a)[:120]} vs {json.dumps(b)[:120]}")
            counts[section(path)] += 1

    walk(left, right, "")
    return lines, counts


# Intent: run the coordinator define pass and two fallback passes on a graph and return what was sent and planned.
# Why: this is the part of the integration that decides which registers are defined and read for a hardware variant.
async def coordinator_decisions(lines: list[str], modules: Any) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = modules.discovery.DiscoveryService.build_device_graph(lines)
        coordinator = modules.VaillantCoordinator(modules.hass(tmpdir), modules.entry())
        coordinator.ebus = MagicMock(spec=modules.EbusService)
        coordinator.ebus.is_connected = True
        coordinator.ebus.define_register = AsyncMock(return_value="done")
        coordinator.ebus.read_register = AsyncMock(return_value=None)
        coordinator._graph = graph
        coordinator._refresh_find_keys()
        await coordinator._define_custom_registers()
        defines = [call.args[0] for call in coordinator.ebus.define_register.await_args_list]
        withheld = sorted(coordinator._withheld_runtime_registers)
        coordinator.ebus.read_register.reset_mock()
        await coordinator._fallback_read(include_placeholders=True, include_energy=True)
        reads_full = [list(call.args[:2]) for call in coordinator.ebus.read_register.await_args_list]
        coordinator.ebus.read_register.reset_mock()
        await coordinator._fallback_read()
        reads_basic = [list(call.args[:2]) for call in coordinator.ebus.read_register.await_args_list]
        return {"defines": defines, "withheld": withheld, "reads_full": reads_full, "reads_basic": reads_basic}


# Intent: generate the entity descriptions for a graph and list their decisions in a stable order.
# Why: enabled-by-default, device circuit and metadata are what users see, so they must not drift silently.
def entity_decisions(lines: list[str], modules: Any) -> list[Any]:
    graph = modules.discovery.DiscoveryService.build_device_graph(lines)
    rows = [
        [
            entity.key,
            entity.entity_type,
            entity.enabled_by_default,
            entity.device_circuit,
            entity.raw_value,
            plain(entity.meta),
        ]
        for entity in modules.factory.EntityFactoryService().generate(graph)
    ]
    return sorted(rows, key=json.dumps)


FROZEN_MOMENT = (2026, 1, 15, 12, 0, 0)


# Intent: make `datetime.now()` return a fixed moment inside one module.
# Why: the day and month energy registers carry the current date in their message id, so dumps made on different days
# would differ in their `define` strings even when the code is identical.
def freeze_clock(module: Any, moment: tuple[int, ...] = FROZEN_MOMENT) -> None:
    class FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz: datetime.tzinfo | None = None) -> FrozenDatetime:
            return cls(*moment)

    module.datetime = FrozenDatetime


# Intent: dump the decisions of one checkout for every community fixture into a JSON file.
# Why: the JSON of two checkouts is compared with the `compare` subcommand.
def dump_tree(tree: Path, out_path: Path) -> None:
    os.chdir(tree)
    sys.path.insert(0, str(tree))
    from tests import _component_loader  # noqa: F401, PLC0415  (registers the stubbed package modules)
    from tests.fake_ebusd import FIXTURES_DIR, load_find_lines  # noqa: PLC0415
    from tests.test_coordinator import DISCOVERY, EbusService, VaillantCoordinator, _entry, _hass  # noqa: PLC0415

    freeze_clock(sys.modules["vaillant_ebus.coordinator"])

    modules = type(
        "Modules",
        (),
        {
            "discovery": DISCOVERY,
            "factory": sys.modules["vaillant_ebus.backend.entity_factory"],
            "EbusService": EbusService,
            "VaillantCoordinator": VaillantCoordinator,
            "entry": staticmethod(_entry),
            "hass": staticmethod(_hass),
        },
    )
    mapping = sys.modules["vaillant_ebus.backend.mapping"]
    result: dict[str, Any] = {
        "register_map": plain(mapping.REGISTER_MAP),
        "multi_field": plain(mapping.MULTI_FIELD_FIELDS),
        "fixtures": {},
    }
    for name in sorted(path.name for path in (FIXTURES_DIR / "community").glob("*.yaml")):
        entry: dict[str, Any] = {}
        for label, after in (("raw", False), ("after", True)):
            try:
                lines = load_find_lines(f"community/{name}", after=after)
            except Exception:  # a fixture without that variant is simply skipped
                continue
            if not lines:
                continue
            try:
                entry[label] = {
                    **asyncio.run(coordinator_decisions(lines, modules)),
                    "entities": entity_decisions(lines, modules),
                }
            except Exception as exc:  # a failure is itself a result to compare
                entry[label] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        if entry:
            result["fixtures"][name] = entry
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(f"{len(result['fixtures'])} fixtures, {len(result['register_map'])} register map entries -> {out_path}")


# Intent: compare two dump files and print the differences; the exit code says whether they are identical.
# Why: byte-identical files are the proof that a refactor or merge kept every recorded decision.
def compare_files(first: Path, second: Path, limit: int) -> int:
    left = json.loads(first.read_text(encoding="utf-8"))
    right = json.loads(second.read_text(encoding="utf-8"))
    lines, counts = diff_dumps(left, right)
    print("differences:", len(lines))
    print(dict(counts))
    for line in lines[:limit]:
        print(line)
    return 1 if lines else 0


# Intent: dispatch the two subcommands.
# Why: one tool for both halves keeps the harness and its comparison in step.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    dump = sub.add_parser("dump")
    dump.add_argument("tree", type=Path)
    dump.add_argument("out", type=Path)
    compare = sub.add_parser("compare")
    compare.add_argument("first", type=Path)
    compare.add_argument("second", type=Path)
    compare.add_argument("--limit", type=int, default=25)
    args = parser.parse_args(argv)
    if args.command == "dump":
        if os.environ.get("PYTHONHASHSEED") != "0":
            print("warning: set PYTHONHASHSEED=0, otherwise only the order of the read lists will differ")
        dump_tree(args.tree.resolve(), args.out.resolve())
        return 0
    return compare_files(args.first, args.second, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
