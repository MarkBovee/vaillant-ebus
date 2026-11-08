"""Pure helpers for the weekly timer programs of the controller (time slots per weekday).

A day holds up to three slots. ebusd reads each slot as `from;to` or `from;to;temperature` (`00:00;00:00` marks an
empty slot) and writes a day slot by slot as `index;count;from;to[;temperature]`. Issue #208 and the owner's CTLV2
proved the write order: the controller only keeps slot N when slot 0 was written with the new count first, and
lowering the count drops the slots behind it. A count of 0 clears the day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MAX_SLOTS_PER_DAY = 3
# Message suffixes that hold the slot count per weekday; the name differs between ebusd configurations.
SLOT_COUNT_SUFFIXES = ("Timeframes", "Timeslots")
# A slot that runs until midnight ends at `24:00` on the controller; `time` has no such value, so the last moment of
# the day stands for it.
END_OF_DAY = time.max


@dataclass(frozen=True, order=True)
class TimeSlot:
    """One switching slot of a day: start, end and an optional target temperature."""

    start: time
    end: time
    temperature: float | None = None


class TimerProgramError(ValueError):
    """A requested change cannot be written safely; the message is shown to the user."""


# Parse one ebusd slot answer into a slot, or None for an empty or unreadable slot.
# `00:00;00:00` is how the controller reports an unused slot; `-` stands for a missing temperature.
def parse_slot(value: str | None) -> TimeSlot | None:
    if not value:
        return None
    parts = [part.strip() for part in value.split(";")]
    if len(parts) < 2 or (parts[0] == "00:00" and parts[1] == "00:00"):
        return None
    try:
        start = _parse_time(parts[0])
        end = _parse_time(parts[1])
    except ValueError:
        return None
    temperature = _parse_temperature(parts[2]) if len(parts) > 2 else None
    return TimeSlot(start, end, temperature)


# Report whether a slot answer carries a temperature column, also for an empty slot (`00:00;00:00;-`).
# The write message of that layout expects the temperature as a fifth value.
def has_temperature_column(value: str | None) -> bool:
    return value is not None and len(value.split(";")) >= 3


# Parse the slot-count message into one count per weekday, or None when it is not seven numbers.
def parse_slot_counts(value: str | None) -> list[int] | None:
    if not value:
        return None
    try:
        counts = [int(part.strip()) for part in value.split(";")]
    except ValueError:
        return None
    return counts if len(counts) == len(WEEKDAYS) else None


# Check that a day's slots can be written: at most three, each ending after it starts, none overlapping.
# The controller has no slot that crosses midnight, so a slot must start and end on the same day.
def validate_day(slots: list[TimeSlot]) -> list[TimeSlot]:
    ordered = sorted(slots)
    if len(ordered) > MAX_SLOTS_PER_DAY:
        raise TimerProgramError(f"A day holds at most {MAX_SLOTS_PER_DAY} time slots")
    for slot in ordered:
        if slot.end <= slot.start:
            raise TimerProgramError("A time slot must end after it starts on the same day")
    for earlier, later in zip(ordered, ordered[1:]):
        if later.start < earlier.end:
            raise TimerProgramError("Time slots of one day must not overlap")
    return ordered


# Build the ebusd write values for one day, slot 0 first so the controller takes the new count.
# An empty day is written as count 0, which clears every slot (issue #208, confirmed by read-back).
def build_day_writes(slots: list[TimeSlot], with_temperature: bool, default_temperature: float | None) -> list[str]:
    ordered = validate_day(slots)
    if with_temperature and default_temperature is None and any(slot.temperature is None for slot in ordered):
        raise TimerProgramError("No target temperature is known for the new time slot")
    if not ordered:
        empty = "0;0;00:00;00:00"
        return [f"{empty};{_format_temperature(default_temperature)}" if with_temperature else empty]
    writes = []
    for index, slot in enumerate(ordered):
        value = f"{index};{len(ordered)};{_format_time(slot.start)};{_format_time(slot.end)}"
        if with_temperature:
            temperature = slot.temperature if slot.temperature is not None else default_temperature
            value += f";{_format_temperature(temperature)}"
        writes.append(value)
    return writes


# Raise when the controller counts more slots for a day than the integration can read.
# Rewriting such a day would drop the slots that are not visible (issue #208: only slot 0 decodes on that config).
def ensure_all_slots_visible(day: str, visible: list[TimeSlot], counted: int | None) -> None:
    if counted is not None and counted > len(visible):
        raise TimerProgramError(
            f"{day} has {counted} time slots, but only {len(visible)} can be read; change it on the controller"
        )


# Parse `HH:MM` into a time. The controller ends a slot at midnight with `24:00`, which `time` cannot hold, so that
# end is kept as `END_OF_DAY` (it still sorts after every other time of the day).
def _parse_time(text: str) -> time:
    hours, minutes = text.split(":")
    if int(hours) == 24 and int(minutes) == 0:
        return END_OF_DAY
    return time(int(hours), int(minutes))


# Parse a temperature column, where `-` or text means no temperature.
def _parse_temperature(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


# Format a time the way ebusd's HTM type expects it, with `END_OF_DAY` as `24:00`.
def _format_time(value: time) -> str:
    if value == END_OF_DAY:
        return "24:00"
    return f"{value.hour:02d}:{value.minute:02d}"


# Format a temperature with one decimal, as the controller stores tenths of a degree.
def _format_temperature(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


# Build a slot from service input: `HH:MM` start and end on the controller's 10-minute grid, optional temperature.
# Input from a service call is checked strictly, so a typo fails before anything is written.
def slot_from_input(start: str, end: str, temperature: float | None = None) -> TimeSlot:
    return TimeSlot(_parse_input_time(start, allow_end_of_day=False), _parse_input_time(end), temperature)


# Turn a slot into the plain values a service response carries: `HH:MM` strings and the temperature or None.
def slot_to_output(slot: TimeSlot) -> dict[str, str | float | None]:
    return {"start": _format_time(slot.start), "end": _format_time(slot.end), "temperature": slot.temperature}


# Check one `HH:MM` time from service input; `24:00` is only valid as an end.
def _parse_input_time(text: str, allow_end_of_day: bool = True) -> time:
    parts = str(text).strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise TimerProgramError(f"{text!r} is not a time in HH:MM format")
    hours, minutes = int(parts[0]), int(parts[1])
    if hours == 24 and minutes == 0 and allow_end_of_day:
        return END_OF_DAY
    if hours > 23 or minutes > 59:
        raise TimerProgramError(f"{text!r} is not a valid time of day")
    if minutes % 10:
        raise TimerProgramError(f"{text!r} is not on the controller's 10-minute grid")
    return time(hours, minutes)
