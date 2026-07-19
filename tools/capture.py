"""Capture a live VR921 session to JSONL for replay analysis."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime

# Ensure project root is on path when running as script
if __name__ == "__main__" and not __package__:
    sys.path.insert(0, ".")

from tools.recorder import SessionRecorder
from vaillant.client import VaillantClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
# Keep vaillant chatter quiet during capture
logging.getLogger("vaillant").setLevel(logging.WARNING)
logging.getLogger("tools.recorder").setLevel(logging.WARNING)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Capture VR921 session to JSONL")
    parser.add_argument("--host", default="192.168.1.130", help="VR921 host")
    parser.add_argument("--port", type=int, default=12480, help="VR921 SHIP port")
    parser.add_argument("--duration", type=int, default=60, help="Capture duration (seconds)")
    parser.add_argument("--output", default=None, help="Output JSONL path (default: auto)")
    args = parser.parse_args()

    output = args.output or f"capture-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    print(f"Output: {output}", flush=True)
    print(f"Target: {args.host}:{args.port}", flush=True)
    print(f"Duration: {args.duration}s", flush=True)
    print()
    print("Approve the handshake in the myVAILLANT app when prompted.", flush=True)
    print(flush=True)

    with SessionRecorder(output) as recorder:
        client = VaillantClient(
            recorder=recorder,
            publish_jsonl=True,
        )
        # Start connection in background
        task = asyncio.create_task(
            client.connect_and_subscribe(args.host, args.port)
        )

        # Wait for capture duration
        for remaining in range(args.duration, 0, -5):
            print(f"\rCapturing... {remaining}s remaining  ({recorder.event_count} events)", end="")
            sys.stderr.flush()
            await asyncio.sleep(5)

        print(f"\rDone. {recorder.event_count} events captured.")
        await client.stop()
        await task

    print(f"\nSaved to: {output}")
    live = len(client.capabilities.with_value())
    total = len(client.capabilities.all)
    print(f"Measurements: {live} live of {total} total capabilities")

    # Summary
    print("\n--- Live values ---")
    for cap in client.capabilities.with_value():
        print(f"  {cap.scope_type}: {cap.value} {cap.unit or ''} (entity={list(cap.entity)}, feature={cap.feature})")

    unknown = client.unknown
    if unknown.total_discarded:
        print(f"\nUnknown commands discarded: {unknown.total_discarded}")
        for uc in unknown.unknown_commands[-5:]:
            print(f"  {uc['cmd_name']} ({uc['direction']})")

    print("\n--- All capabilities ---")
    for cap in sorted(client.capabilities.all, key=lambda c: (c.entity, c.feature)):
        tag = "LIVE" if cap.has_value else "    "
        scope = cap.scope_type or "-"
        cmds = cap.supported_commands
        print(f"  [{tag}] e{list(cap.entity)} f{cap.feature}  {cap.feature_type:25s}  scope={scope:30s}  cmd={cmds}")


if __name__ == "__main__":
    asyncio.run(main())
