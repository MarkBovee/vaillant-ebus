from __future__ import annotations

import json
import os
import tempfile

from tools.recorder import SessionRecorder


def test_recorder_writes_jsonl() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    try:
        rec = SessionRecorder(path)
        rec.open()
        rec.record_rx(b"\x02{\"hello\":\"world\"}", msg_type=2)
        rec.record_tx(b"\x01{\"ping\":true}", msg_type=1)
        rec.record_event("test_event", {"key": "val"})
        rec.close()

        with open(path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        # session_start + 3 recorded + session_end = 5 lines
        assert len(lines) == 5
        assert lines[0]["dir"] == "event"
        assert lines[0]["type"] == "session_start"

        rx_line = lines[1]
        assert rx_line["dir"] == "rx"
        assert rx_line["type"] == "ship_data"

        tx_line = lines[2]
        assert tx_line["dir"] == "tx"
        assert tx_line["type"] == "ship_control"

        event_line = lines[3]
        assert event_line["dir"] == "event"
        assert event_line["type"] == "test_event"
        assert event_line["payload"]["key"] == "val"

        end_line = lines[4]
        assert end_line["type"] == "session_end"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_recorder_context_manager() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    try:
        with SessionRecorder(path) as rec:
            rec.record_event("inside_context")

        with open(path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 3
        assert lines[1]["type"] == "inside_context"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_recorder_count() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    try:
        rec = SessionRecorder(path)
        rec.open()
        rec.record_rx(b"\x02data")
        rec.record_tx(b"\x01data")
        assert rec.event_count == 3  # session_start + rx + tx
        rec.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)
