"""Services that read and write whole controller timer programs (`Z1Timer`, `HwcTimer`, `CcTimer`, ...).

`read_time_program` returns every weekday with its slots, so a dashboard card can show a program without one sensor
per slot. `write_time_program` replaces the slots of one or more weekdays and reads each day back.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError

from .backend.timer_program import (
    WEEKDAYS,
    TimerProgramError,
    TimeSlot,
    slot_from_input,
    slot_to_output,
    validate_day,
)
from .timer_access import TimerProgramAccess

if TYPE_CHECKING:
    from .coordinator import VaillantCoordinator

# Zone programs live on the circuit that hosts the zone; all other programs on the heating controller.
_ZONE_PROGRAM = re.compile(r"^Z(\d+)(?:Cooling)?Timer$")
# A program name is the ebusd message prefix, e.g. `Z1Timer`; it becomes part of a message name.
PROGRAM_PATTERN = r"^[A-Za-z][A-Za-z0-9]*Timer$"


# Pick the circuit a program's messages are read from: an explicit circuit wins, then the zone's host, then the
# heating controller.
def timer_circuit(coordinator: VaillantCoordinator, program: str, circuit: str | None = None) -> str:
    if circuit:
        return circuit
    match = _ZONE_PROGRAM.match(program)
    if match:
        hosted = coordinator.zone_circuits().get(f"z{match.group(1)}")
        if hosted:
            return hosted
    controller = coordinator.heating_circuit
    if controller is None:
        raise HomeAssistantError("The heating controller is not discovered yet; try again in a moment")
    return controller


# Map a weekday from service input (`monday`, `Monday` or `mon`) to the controller's name (`Monday`).
def weekday(text: str) -> str:
    key = str(text).strip().casefold()
    for day in WEEKDAYS:
        if key in (day.casefold(), day[:3].casefold()):
            return day
    raise HomeAssistantError(f"Unknown weekday {text!r}")


# Read all seven weekdays of a program. `force` reads past ebusd's cache.
# A day whose slots cannot all be read is listed under `incomplete`; its visible slots are still returned.
async def async_read_time_program(
    coordinator: VaillantCoordinator, program: str, circuit: str | None = None, force: bool = False
) -> dict[str, Any]:
    access = TimerProgramAccess(coordinator, program, timer_circuit(coordinator, program, circuit))
    days: dict[str, list[dict[str, Any]]] = {}
    incomplete: list[str] = []
    with_temperature = False
    readable = False
    for day in WEEKDAYS:
        read = await access.inspect_day(day, force=force)
        readable = readable or read.readable > 0
        with_temperature = with_temperature or read.with_temperature
        days[day.lower()] = [slot_to_output(slot) for slot in read.slots]
        if not read.complete:
            incomplete.append(day.lower())
    if not readable:
        raise HomeAssistantError(f"{program} is not available on this controller")
    return {
        "program": program,
        "circuit": access.circuit,
        "temperature": with_temperature,
        "days": days,
        "incomplete": incomplete,
    }


# Replace the slots of the given weekdays with the same slots, one day after the other, each read back.
# Stops at the first day that fails; the error names the days that were already written.
async def async_write_time_program(
    coordinator: VaillantCoordinator,
    program: str,
    days: list[str],
    slots: list[dict[str, Any]],
    circuit: str | None = None,
) -> dict[str, Any]:
    targets = list(dict.fromkeys(weekday(day) for day in days))
    if not targets:
        raise HomeAssistantError("No weekday to write")
    requested = _requested_slots(slots)
    access = TimerProgramAccess(coordinator, program, timer_circuit(coordinator, program, circuit))
    written: dict[str, list[dict[str, Any]]] = {}
    for day in targets:
        try:
            read = await access.inspect_day(day)
            if read.readable == 0:
                raise HomeAssistantError(f"{program}_{day} is not available on this controller")
            # Check before writing: the count write would otherwise drop slots this configuration cannot read.
            access.ensure_no_hidden_slots(day, read)
            stored = await access.write_day(
                day,
                requested,
                read.with_temperature,
                _default_temperature(read.slots, clearing=not requested),
                compare_temperature=all(slot.temperature is not None for slot in requested),
            )
        except HomeAssistantError as exc:
            done = ", ".join(written) or "none"
            raise HomeAssistantError(f"{exc} (days already written: {done})") from exc
        written[day.lower()] = [slot_to_output(slot) for slot in stored]
    return {"program": program, "circuit": access.circuit, "days": written}


# Turn the service's slot list into checked slots: valid times, no overlap, at most three.
def _requested_slots(slots: list[dict[str, Any]]) -> list[TimeSlot]:
    try:
        requested = [
            slot_from_input(
                item["start"],
                item["end"],
                None if item.get("temperature") is None else float(item["temperature"]),
            )
            for item in slots
        ]
        return validate_day(requested)
    except (KeyError, TypeError, ValueError) as exc:
        # TimerProgramError is a ValueError, so its message is kept; a missing key or bad number gets a plain one.
        if isinstance(exc, TimerProgramError):
            raise HomeAssistantError(str(exc)) from exc
        raise HomeAssistantError(
            "Each slot needs `start` and `end` (HH:MM) and an optional number `temperature`"
        ) from exc


# A temperature for slots sent without one: the first one the day already has. Clearing a day on a layout with a
# temperature column still needs a value there; 0.0 is what the myVAILLANT app sends for an empty day.
def _default_temperature(slots: list[TimeSlot], clearing: bool) -> float | None:
    known = next((slot.temperature for slot in slots if slot.temperature is not None), None)
    return 0.0 if known is None and clearing else known
