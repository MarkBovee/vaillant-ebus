"""SessionReplay — replay recorded SHIP/SPINE sessions as a test transport."""

from __future__ import annotations

import json
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


class SessionReplay:
    """Replay a recorded JSONL session as a fake WebSocket transport.

    Walks through recorded events in order. `recv()` returns the next rx event
    payload as bytes. `send()` advances past the next tx event (validates payload
    if strict=True).

    Usage:
        replay = SessionReplay("capture.jsonl")
        client = VaillantClient(test_transport=replay, cert_ski="...")
        await client.connect_and_subscribe("replay", 0)
        # client now has state from the capture
    """

    def __init__(self, path: str, *, strict: bool = False) -> None:
        self._events = _load_events(path)
        self._idx = 0
        self._strict = strict
        self._sent: list[dict[str, Any]] = []
        self._closed = False

    @property
    def idx(self) -> int:
        return self._idx

    @property
    def total_events(self) -> int:
        return len(self._events)

    @property
    def remaining(self) -> int:
        return self.total_events - self._idx

    @property
    def sent_count(self) -> int:
        return len(self._sent)

    async def recv(self) -> bytes:
        if self._closed:
            raise ConnectionError("Replay closed")
        while self._idx < len(self._events):
            ev = self._events[self._idx]
            self._idx += 1
            if ev["dir"] == "rx":
                return _event_to_bytes(ev)
        raise _ReplayEndError()

    async def send(self, data: bytes) -> None:
        if self._closed:
            raise ConnectionError("Replay closed")
        self._sent.append({"data": data, "idx": self._idx})
        if self._strict:
            expected = self._next_tx()
            if expected is not None and data != expected:
                _LOGGER.warning(
                    "Replay strict: send mismatch at idx=%d\n  got=%r\n  exp=%r",
                    self._idx - 1, data[:50], expected[:50],
                )

    def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    def sent_events(self) -> list[dict[str, Any]]:
        """Return summary of all send events for test assertions."""
        return [
            {
                "idx": s["idx"],
                "data_len": len(s["data"]),
                "preview": s["data"][:80],
            }
            for s in self._sent
        ]

    # -- helpers --

    def _next_tx(self) -> bytes | None:
        if self._idx >= len(self._events):
            return None
        ev = self._events[self._idx]
        if ev["dir"] != "tx":
            return None
        self._idx += 1
        return _event_to_bytes(ev)


class _ReplayEndError(Exception):
    """Raised when replay has no more events."""


def _load_events(path: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("dir") in ("rx", "tx"):
                events.append(ev)
    _LOGGER.info("SessionReplay: loaded %d events from %s", len(events), path)
    return events


def _event_to_bytes(ev: dict[str, Any]) -> bytes:
    """Reconstruct the original bytes from a recorded event.

    The event stores the payload as text (decoded UTF-8).
    We reconstruct by determining the msg_type from the event type.
    """
    payload_text = ev.get("payload", "")
    if isinstance(payload_text, str):
        payload_bytes = payload_text.encode("utf-8")
    elif isinstance(payload_text, bytes):
        payload_bytes = payload_text
    else:
        payload_bytes = str(payload_text).encode("utf-8")

    event_type = ev.get("type", "ship_data")
    msg_type = 1 if event_type == "ship_control" else 2
    return bytes([msg_type]) + payload_bytes
