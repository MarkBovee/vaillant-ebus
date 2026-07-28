#!/usr/bin/env python3
"""Standalone ebusd TCP CLI — find, read, write, grab, dump."""
import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import yaml
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml"], check=True)
    import yaml

from custom_components.vaillant_ebus.backend.tcp import EbusdTcpBackend, SendResult
from custom_components.vaillant_ebus.backend.mapping import REGISTER_MAP
from custom_components.vaillant_ebus.backend.models import EbusdRegister


async def cmd_find(backend: EbusdTcpBackend, args) -> int:
    raw_lines = await backend.async_find_lines()
    circuits: dict[str, dict[str, EbusdRegister]] = {}
    for line in raw_lines:
        parsed = EbusdTcpBackend._parse_find_line(line)
        if parsed is None:
            continue
        circuit_name, reg_name, fields, values, msg_type, address = parsed
        if circuit_name not in circuits:
            circuits[circuit_name] = {}
        reg = EbusdRegister(
            circuit=circuit_name,
            name=reg_name,
            fields=fields,
            value=values,
            has_data=any(v is not None for v in values.values()),
            message_type=msg_type,
            address=address,
        )
        circuits[circuit_name][reg_name] = reg
    result: list[EbusdRegister] = []
    for circuit_name in sorted(circuits):
        result.extend(sorted(circuits[circuit_name].values(), key=lambda r: r.name))
    for reg in result:
        parts = [f"{reg.circuit}.{reg.name}"]
        for f in reg.fields:
            parts.append(f"  {f}={reg.value.get(f, '-')}")
        if reg.message_type:
            parts.append(f"  [{reg.message_type} @ {reg.address}]")
        parts.append(f"  {'rw' if reg.writable else 'ro'}")
        print("".join(parts))
    print(f"\n{len(result)} registers")
    return 0


async def cmd_read(backend: EbusdTcpBackend, args) -> int:
    val = await backend.async_read(args.read_circuit, args.read_name)
    key = f"{args.read_circuit}.{args.read_name}"
    if val is None:
        print(f"{key} = (no data)")
        return 1
    print(f"{key} = {val}")
    return 0


async def cmd_write(backend: EbusdTcpBackend, args) -> int:
    circuit = args.write_circuit
    name = args.write_name
    value = args.write_value
    key = f"{circuit}.{name}"
    print(f"Write: {key} = {value}")
    result = await backend.async_write(circuit, name, value)
    if result.success:
        print(f"  → done (verified: {result.verified_value})")
        return 0
    else:
        print(f"  → FAILED: {result.error_message}")
        return 1


async def _grab_cmd(host: str, port: int, command: str) -> list[str]:
    r, w = await asyncio.open_connection(host, port)
    try:
        w.write(f"{command}\n".encode())
        await w.drain()
        resp = []
        for _ in range(200):
            try:
                line = await asyncio.wait_for(r.readline(), timeout=2)
                if not line:
                    break
                decoded = line.decode().strip()
                if decoded:
                    resp.append(decoded)
            except TimeoutError:
                break
        return resp
    finally:
        w.close()
        await w.wait_closed()


async def cmd_grab(backend: EbusdTcpBackend, args) -> int:
    duration = args.grab_seconds
    host = backend._host
    port = backend._port
    print(f"Capturing eBUS traffic for {duration}s...", file=sys.stderr)
    enable_resp = await _grab_cmd(host, port, "grab")
    print(f"[grab] {enable_resp[0] if enable_resp else 'no response'}")
    await asyncio.sleep(duration)
    lines = await _grab_cmd(host, port, "grab result all")
    for line in lines:
        print(line)
    stop_resp = await _grab_cmd(host, port, "grab stop")
    print(f"[grab stop] {stop_resp[0] if stop_resp else 'no response'}")
    print(f"\n{len(lines)} lines captured")
    return 0


async def cmd_dump(backend: EbusdTcpBackend, args) -> int:
    raw_lines = await backend.async_find_lines()
    discovered = await backend.async_find()
    register_list = []
    seen_keys = set()
    for reg in discovered:
        seen_keys.add(reg.key)
        vals = [reg.value.get(f) for f in reg.fields]
        entry = {
            "circuit": reg.circuit,
            "name": reg.name,
            "fields": reg.fields,
            "values": vals,
            "writable": reg.writable,
            "has_data": reg.has_data,
        }
        if reg.message_type:
            entry["message_type"] = reg.message_type
        if reg.address:
            entry["address"] = reg.address
        register_list.append(entry)
    for key, meta in REGISTER_MAP.items():
        if key in seen_keys:
            continue
        parts = key.split(".", 1)
        if len(parts) != 2:
            continue
        circuit, name = parts
        entry = {
            "circuit": circuit,
            "name": name,
            "fields": ["value"],
            "values": [None],
            "writable": meta.writable,
            "has_data": False,
            "from_map": True,
        }
        if not meta.enabled:
            entry["disabled"] = True
        try:
            val = await backend.async_read(circuit, name)
            if val:
                entry["values"] = [val]
                entry["has_data"] = True
        except Exception:
            pass
        register_list.append(entry)
    register_list.sort(key=lambda r: (r["circuit"], r["name"]))
    dump = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dump_version": 3,
            "register_count": len(register_list),
        },
        "raw_find_lines": raw_lines,
        "registers": register_list,
    }
    yaml.dump(dump, sys.stdout, default_flow_style=False, allow_unicode=True)
    return 0


async def amain(args) -> int:
    backend = EbusdTcpBackend(host=args.host, port=args.port)
    try:
        await backend.async_connect()
    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.cmd_find:
        return await cmd_find(backend, args)
    elif args.read_circuit:
        return await cmd_read(backend, args)
    elif args.write_circuit:
        return await cmd_write(backend, args)
    elif args.cmd_grab:
        return await cmd_grab(backend, args)
    elif args.cmd_dump:
        return await cmd_dump(backend, args)
    return 0


def main():
    parser = argparse.ArgumentParser(description="ebusd TCP CLI tool")
    parser.add_argument("host", help="ebusd hostname or IP")
    parser.add_argument("-p", "--port", type=int, default=8888, help="ebusd TCP port")
    parser.add_argument("-t", "--timeout", type=int, default=10, help="command timeout")
    parser.add_argument("--find", dest="cmd_find", action="store_true", help="Run find, output all registers")
    parser.add_argument("--read", dest="read_circuit", nargs=2, metavar=("CIRCUIT", "NAME"), help="Read register")
    parser.add_argument("--write", dest="write_circuit", nargs=3, metavar=("CIRCUIT", "NAME", "VALUE"), help="Write + readback verify")
    parser.add_argument("--grab", dest="cmd_grab", type=int, metavar="SECONDS", help="Capture raw eBUS traffic")
    parser.add_argument("--dump", dest="cmd_dump", action="store_true", help="Full v3 dump to stdout")
    args = parser.parse_args()
    try:
        exit_code = asyncio.run(amain(args))
    except KeyboardInterrupt:
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
