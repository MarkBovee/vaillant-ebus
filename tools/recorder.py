"""SessionRecorder — capture raw SHIP/SPINE traffic to JSONL."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)


class SessionRecorder:
    """Record SHIP control/data frames and session events to JSONL.

    One file per session. Each line is a JSON object with:
      ts: float — unix timestamp
      dir: str — "rx" | "tx" | "event"
      type: str — message type classifier
      payload: any — the recorded data
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._handle: Any = None
        self._count = 0
        _LOGGER.info("SessionRecorder → %s", path)

    def open(self) -> None:
        dir_path = os.path.dirname(self._path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
        self._handle = open(self._path, "a", encoding="utf-8")
        self._write_event("session_start", {"path": self._path})

    def close(self) -> None:
        if self._handle is not None:
            self._write_event("session_end", {"total_events": self._count})
            self._handle.close()
            self._handle = None
            _LOGGER.info("SessionRecorder closed: %d events → %s", self._count, self._path)

    def __enter__(self) -> SessionRecorder:
        self.open()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def event_count(self) -> int:
        return self._count

    # -- record methods --

    def record_rx(self, data: bytes, msg_type: int = 2) -> None:
        self._write_bytes("rx", data, msg_type)

    def record_tx(self, data: bytes, msg_type: int = 2) -> None:
        self._write_bytes("tx", data, msg_type)

    def record_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        self._write_line({
            "ts": time.time(),
            "dir": "event",
            "type": event_type,
            "payload": data or {},
        })

    def record_handshake_phase(self, phase: str) -> None:
        self.record_event("handshake_phase", {"phase": phase})

    def record_discovery(self, discovery: dict[str, Any]) -> None:
        self.record_event("discovery", discovery)

    def record_subscription(self, feature_type: str, entity: list[int], feature: int) -> None:
        self.record_event("subscription", {
            "feature_type": feature_type,
            "entity": entity,
            "feature": feature,
        })

    def record_measurement(self, scope: str, value: Any, unit: str) -> None:
        self.record_event("measurement", {"scope": scope, "value": value, "unit": unit})

    def record_write_call(self, feature_type: str, entity: list[int], feature: int, cmd: str) -> None:
        self.record_event("write_call", {
            "feature_type": feature_type,
            "entity": entity,
            "feature": feature,
            "cmd": cmd,
        })

    def record_error(self, message: str, traceback: str | None = None) -> None:
        self.record_event("error", {"message": message, "traceback": traceback})

    # -- internal --

    def _write_bytes(self, direction: str, data: bytes, msg_type: int) -> None:
        try:
            payload_text = data[1:].decode("utf-8", errors="replace")
        except Exception:
            payload_text = data.hex()
        entry_type = "ship_control" if msg_type == 1 else "ship_data"
        self._write_line({
            "ts": time.time(),
            "dir": direction,
            "type": entry_type,
            "payload": payload_text,
        })

    def _write_event(self, event_type: str, data: dict[str, Any]) -> None:
        self._write_line({
            "ts": time.time(),
            "dir": "event",
            "type": event_type,
            "payload": data,
        })

    def _write_line(self, obj: dict[str, Any]) -> None:
        if self._handle is None:
            return
        try:
            line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            self._handle.write(line + "\n")
            self._handle.flush()
            self._count += 1
        except Exception as exc:
            _LOGGER.warning("SessionRecorder write error: %s", exc)
