"""Tests for the pure timer-program helpers (weekly time slots of the controller, issue #208)."""

from __future__ import annotations

from datetime import time

import pytest

from tests.backend_loader import load_backend

TIMER = load_backend("timer_program")
TimeSlot = TIMER.TimeSlot


# Intent: slot answers of both CTLV2 layouts parse into slots, and the empty marker reads as no slot.
# Why: the owner's config answers `from;to;temp` with `00:00;00:00;-` for an unused slot; the issue #208 config
#      answers `from;to` only.
def test_parse_slot_reads_both_layouts() -> None:
    assert TIMER.parse_slot("13:30;15:00;35.0") == TimeSlot(time(13, 30), time(15, 0), 35.0)
    assert TIMER.parse_slot("05:20;06:00") == TimeSlot(time(5, 20), time(6, 0), None)
    assert TIMER.parse_slot("00:00;00:00;-") is None
    # A slot that starts at midnight is a real slot; only 00:00 to 00:00 marks a free one.
    assert TIMER.parse_slot("00:00;06:00") == TimeSlot(time(0, 0), time(6, 0), None)
    assert TIMER.parse_slot("ERR: element not found") is None
    assert TIMER.has_temperature_column("00:00;00:00;-") is True
    assert TIMER.has_temperature_column("05:20;06:00") is False


# Intent: a day is written slot 0 first with the new count, with the temperature column only on that layout.
# Why: the owner's live test - the controller ignored slot 1 until slot 0 was written with count 2.
def test_build_day_writes_orders_slots_and_counts() -> None:
    slots = [TimeSlot(time(16, 0), time(16, 30)), TimeSlot(time(13, 30), time(15, 0), 35.0)]

    assert TIMER.build_day_writes(slots, True, 40.0) == ["0;2;13:30;15:00;35.0", "1;2;16:00;16:30;40.0"]
    assert TIMER.build_day_writes(slots, False, None) == ["0;2;13:30;15:00", "1;2;16:00;16:30"]


# Intent: an empty day is written as count 0, which clears every slot.
# Why: issue #208 - `0;0;00:00;00:00` deleted all slots of the day, confirmed by read-back.
def test_build_day_writes_clears_an_empty_day() -> None:
    assert TIMER.build_day_writes([], False, None) == ["0;0;00:00;00:00"]
    assert TIMER.build_day_writes([], True, 45.0) == ["0;0;00:00;00:00;45.0"]


# Intent: a day with too many, overlapping, reversed or temperature-less slots is refused before any write.
# Why: a write the controller cannot store would leave the day half changed.
@pytest.mark.parametrize(
    ("slots", "with_temperature", "default"),
    [
        ([TimeSlot(time(h, 0), time(h, 30)) for h in (1, 2, 3, 4)], False, None),
        ([TimeSlot(time(1, 0), time(2, 0)), TimeSlot(time(1, 30), time(3, 0))], False, None),
        ([TimeSlot(time(5, 0), time(4, 0))], False, None),
        ([TimeSlot(time(5, 0), time(6, 0))], True, None),
    ],
)
def test_build_day_writes_refuses_invalid_days(slots: list, with_temperature: bool, default: float | None) -> None:
    with pytest.raises(TIMER.TimerProgramError):
        TIMER.build_day_writes(slots, with_temperature, default)


# Intent: a day whose slot count is higher than the readable slots cannot be rewritten; counts parse per weekday.
# Why: issue #208 - only slot 0 decodes on that config, so rewriting a day with two slots would drop the second one.
def test_hidden_slots_block_a_rewrite() -> None:
    assert TIMER.parse_slot_counts("1;2;0;0;0;1;0") == [1, 2, 0, 0, 0, 1, 0]
    assert TIMER.parse_slot_counts("1;2") is None
    visible = [TimeSlot(time(3, 0), time(3, 10))]

    TIMER.ensure_all_slots_visible("Tuesday", visible, 1)
    TIMER.ensure_all_slots_visible("Tuesday", visible, None)
    with pytest.raises(TIMER.TimerProgramError, match="Tuesday has 2 time slots"):
        TIMER.ensure_all_slots_visible("Tuesday", visible, 2)
