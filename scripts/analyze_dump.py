#!/usr/bin/env python3
"""Analyze a discovery dump: compare vs REGISTER_MAP, detect program patterns."""
import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import yaml
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml"], check=True)
    import yaml

try:
    from custom_components.vaillant_ebus.backend.mapping import REGISTER_MAP
except ImportError:
    REGISTER_MAP = {}


DATE_PATTERN = re.compile(r"(Start|End)(Period|Date|Time)$", re.IGNORECASE)
TEMP_PATTERN = re.compile(r"(Temp(erature)?|Setpoint|Desired)$", re.IGNORECASE)
MODE_PATTERN = re.compile(r"(Mode|Enabled|Status)$", re.IGNORECASE)


def get_val(entry: dict) -> str:
    vals = entry.get("values")
    if isinstance(vals, list) and vals:
        return str(vals[0]) if vals[0] is not None else "-"
    if "value" in entry:
        return str(entry["value"]) if entry["value"] is not None else "-"
    return "-"


def classify_name(name: str) -> str:
    if DATE_PATTERN.search(name):
        return "date"
    if TEMP_PATTERN.search(name):
        return "temp"
    if MODE_PATTERN.search(name):
        return "mode"
    return "other"


def load_dump(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_register_set(dump: dict) -> dict[str, dict]:
    result = {}
    for entry in dump.get("before_registers", []):
        key = f"{entry['circuit']}.{entry['name']}"
        if "value" in entry and "values" not in entry:
            entry["values"] = [entry["value"]]
            entry["fields"] = ["value"]
        result[key] = entry
    return result


def cmd_compare(dump: dict, opts) -> int:
    registers = build_register_set(dump)
    dump_keys = set(registers.keys())
    map_keys = set(REGISTER_MAP.keys())

    unmapped = dump_keys - map_keys
    map_only = map_keys - dump_keys
    mapped = dump_keys & map_keys

    by_circuit: dict[str, list[str]] = defaultdict(list)
    for key in sorted(unmapped):
        circuit = key.split(".", 1)[0]
        by_circuit[circuit].append(key)

    print("=== Unmapped registers (in dump but NOT in REGISTER_MAP) ===\n")
    for circuit in sorted(by_circuit):
        regs = by_circuit[circuit]
        print(f"  Circuit: {circuit} ({len(regs)} unmapped)")
        for key in regs:
            r = registers[key]
            c = classify_name(r["name"])
            val = get_val(r)
            writable = r.get("writable", False)
            print(f"    {r['name']:45s} [{c:6s}]  value: {val:20s}  writable: {writable}")
        print()

    print(f"=== REGISTER_MAP-only entries (not found by find) ===\n")
    if map_only:
        by_circuit_mo: dict[str, list[str]] = defaultdict(list)
        for key in sorted(map_only):
            circuit = key.split(".", 1)[0]
            by_circuit_mo[circuit].append(key)
        for circuit in sorted(by_circuit_mo):
            regs = by_circuit_mo[circuit]
            print(f"  Circuit: {circuit} ({len(regs)} map-only)")
            for key in regs:
                meta = REGISTER_MAP.get(key, {})
                print(f"    {key.split('.', 1)[1]:45s}  entity_type: {getattr(meta, 'entity_type', '?')}")
            print()
    else:
        print("  (none)\n")

    if opts.cooling:
            cooling_keys = {k for k in unmapped if "cool" in k.lower()}
            if cooling_keys:
                print("=== Cooling-related unmapped registers ===\n")
                for key in sorted(cooling_keys):
                    r = registers[key]
                    print(f"  {key:50s}  value: {get_val(r):20s}  writable: {r.get('writable', False)}")
                print()

    print(f"=== Summary ===")
    print(f"  Total in dump:    {len(dump_keys)}")
    print(f"  In REGISTER_MAP:  {len(mapped)}")
    print(f"  Unmapped:         {len(unmapped)}")
    print(f"  Map-only:         {len(map_only)}")

    if opts.output:
        out = {
            "unmapped": sorted(unmapped),
            "map_only": sorted(map_only),
            "mapped_count": len(mapped),
            "unmapped_count": len(unmapped),
            "map_only_count": len(map_only),
        }
        with open(opts.output, "w") as f:
            yaml.dump(out, f)
        print(f"\nWrote structured export to {opts.output}")

    return 0


def cmd_patterns(dump: dict, opts) -> int:
    registers = build_register_set(dump)
    dump_keys = set(registers.keys())
    map_keys = set(REGISTER_MAP.keys())
    unmapped = dump_keys - map_keys

    by_circuit: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)
    for key in sorted(unmapped):
        circuit = key.split(".", 1)[0]
        r = registers[key]
        c = classify_name(r["name"])
        by_circuit[circuit].append((r["name"], c, r))

    print("=== Registers by pattern classification ===\n")
    for circuit in sorted(by_circuit):
        entries = by_circuit[circuit]
        print(f"  Circuit: {circuit} ({len(entries)} unmapped)")
        has_date = any(c == "date" for _, c, _ in entries)
        has_temp = any(c == "temp" for _, c, _ in entries)
        has_mode = any(c == "mode" for _, c, _ in entries)
        for name, c, r in entries:
            val = get_val(r)
            cool_flag = " ← COOLING" if "cool" in name.lower() else ""
            print(f"    {name:45s} [{c:6s}]  {str(val):20s}{cool_flag}")
        if has_date and has_temp and has_mode:
            date_regs = [n for n, c, _ in entries if c == "date"]
            temp_regs = [n for n, c, _ in entries if c == "temp"]
            mode_regs = [n for n, c, _ in entries if c == "mode"]
            print(f"    >>> PROGRAM CANDIDATE: date({len(date_regs)}) + temp({len(temp_regs)}) + mode({len(mode_regs)})")
        print()

    if opts.cooling:
        print("=== Cooling program candidates ===\n")
        for circuit in sorted(by_circuit):
            entries = by_circuit[circuit]
            cool_entries = [(n, c, r) for n, c, r in entries if "cool" in n.lower()]
            if not cool_entries:
                continue
            has_date = any(c == "date" for _, c, _ in cool_entries)
            has_temp = any(c == "temp" for _, c, _ in cool_entries)
            has_mode = any(c == "mode" for _, c, _ in cool_entries)
            for name, c, r in cool_entries:
                print(f"  {circuit}.{name:40s} [{c:6s}]")
            if has_date and has_temp and has_mode:
                print(f"  >>> COOLING PROGRAM CANDIDATE: {circuit}")
            print()

    return 0


def cmd_cooling(dump: dict, opts) -> int:
    registers = build_register_set(dump)
    cooling_keys = {k: v for k, v in registers.items() if "cool" in k.lower() or "dew" in k.lower()}

    print("=== Cooling/Dew registers ===\n")
    for key in sorted(cooling_keys):
        r = cooling_keys[key]
        in_map = key in REGISTER_MAP
        c = classify_name(r["name"])
        val = get_val(r)
        writable = r.get("writable", False)
        map_tag = "  [MAPPED]" if in_map else "  [UNMAPPED]"
        print(f"  {key:50s} [{c:6s}]  {str(val):20s}  writable={writable}{map_tag}")
    print()
    print(f"  Total: {len(cooling_keys)} cooling registers")

    by_circuit: dict[str, list[str]] = defaultdict(list)
    for key in cooling_keys:
        circuit = key.split(".", 1)[0]
        by_circuit[circuit].append(key)

    print(f"\n=== Cooling program candidates per circuit ===")
    for circuit in sorted(by_circuit):
        keys = by_circuit[circuit]
        names = [k.split(".", 1)[1] for k in keys]
        has_date = any(DATE_PATTERN.search(n) for n in names)
        has_temp = any(TEMP_PATTERN.search(n) for n in names)
        has_mode = any(MODE_PATTERN.search(n) for n in names)
        parts = []
        if has_date:
            parts.append("date")
        if has_temp:
            parts.append("temp")
        if has_mode:
            parts.append("mode")
        status = " + ".join(parts) if parts else "incomplete"
        print(f"  {circuit}: {status}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Analyze vaillant_ebus discovery dump")
    parser.add_argument("dump", help="Path to discovery_dump_*.yaml file")
    parser.add_argument("-c", "--compare", action="store_true", help="Compare vs REGISTER_MAP")
    parser.add_argument("-p", "--patterns", action="store_true", help="Classify unmapped registers")
    parser.add_argument("-C", "--cooling", action="store_true", help="Filter cooling registers")
    parser.add_argument("--output", "-o", help="Write structured export to YAML file")
    args = parser.parse_args()

    if not os.path.isfile(args.dump):
        print(f"Error: dump file not found: {args.dump}", file=sys.stderr)
        return 1

    dump = load_dump(args.dump)
    version = dump.get("metadata", {}).get("dump_version", "?")
    print(f"Dump: {args.dump}")
    print(f"Version: v{version}")
    print(f"Timestamp: {dump.get('metadata', {}).get('timestamp', '?')}")
    print()

    if not (args.compare or args.patterns or args.cooling):
        args.compare = True

    if args.compare:
        cmd_compare(dump, args)
        print()
    if args.patterns:
        cmd_patterns(dump, args)
        print()
    if args.cooling:
        cmd_cooling(dump, args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
