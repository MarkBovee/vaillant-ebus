from __future__ import annotations

import os
import tempfile

import pytest

from tools.recorder import SessionRecorder
from tools.replay import SessionReplay


@pytest.fixture
def capture_path():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name
    with SessionRecorder(path) as rec:
        rec.record_rx(b"\x02ship_data_packet", msg_type=2)
        rec.record_tx(b"\x01control_frame", msg_type=1)
        rec.record_rx(b"\x02another_data_packet", msg_type=2)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.mark.asyncio
async def test_replay_recv(capture_path):
    replay = SessionReplay(capture_path)
    rx1 = await replay.recv()
    assert rx1 == b"\x02ship_data_packet"
    rx2 = await replay.recv()
    assert rx2 == b"\x02another_data_packet"


@pytest.mark.asyncio
async def test_replay_send_advances(capture_path):
    replay = SessionReplay(capture_path)
    await replay.recv()
    await replay.send(b"\x01something")
    assert replay.sent_count == 1
    remaining_before = replay.remaining
    rx2 = await replay.recv()
    assert rx2 == b"\x02another_data_packet"
    assert replay.remaining < remaining_before


@pytest.mark.asyncio
async def test_replay_end_raises(capture_path):
    replay = SessionReplay(capture_path)
    await replay.recv()
    await replay.send(b"\x01x")
    await replay.recv()
    from tools.replay import _ReplayEndError
    with pytest.raises(_ReplayEndError):
        await replay.recv()


@pytest.mark.asyncio
async def test_replay_sent_events(capture_path):
    replay = SessionReplay(capture_path)
    await replay.recv()
    await replay.send(b"\x02msg1")
    await replay.recv()
    sent = replay.sent_events()
    assert len(sent) == 1
    assert sent[0]["data_len"] == 5
    assert sent[0]["idx"] == 1


@pytest.mark.asyncio
async def test_replay_empty():
    path = "/tmp/test_replay_empty.jsonl"
    try:
        with open(path, "w") as f:
            f.write('{"ts": 0, "dir": "event", "type": "test", "payload": {}}\n')
        replay = SessionReplay(path)
        from tools.replay import _ReplayEndError
        with pytest.raises(_ReplayEndError):
            await replay.recv()
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_replay_load_events():
    """Verify that only rx/tx events are loaded, not event entries."""
    path = "/tmp/test_replay_filter.jsonl"
    try:
        with open(path, "w") as f:
            f.write('{"ts": 1, "dir": "event", "type": "session_start", "payload": {}}\n')
            f.write('{"ts": 2, "dir": "rx", "type": "ship_data", "payload": "data1"}\n')
            f.write('{"ts": 3, "dir": "event", "type": "handshake_phase", "payload": {}}\n')
            f.write('{"ts": 4, "dir": "tx", "type": "ship_data", "payload": "data2"}\n')
        from tools.replay import _load_events
        events = _load_events(path)
        assert len(events) == 2
        assert events[0]["dir"] == "rx"
        assert events[1]["dir"] == "tx"
    finally:
        if os.path.exists(path):
            os.unlink(path)
