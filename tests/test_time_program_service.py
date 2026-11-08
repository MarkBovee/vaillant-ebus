"""Tests for the `read_time_program` and `write_time_program` services.

The fake controller behaves like the CTLV2 programs tested live for issue #208: slot 0 carries the day's count, a later
slot is ignored until the count includes it, and count 0 clears the day.
"""

from __future__ import annotations

import sys
from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests import test_coordinator as tc  # noqa: F401 — shared test helpers
from tests.backend_loader import load_backend

SERVICE = sys.modules["vaillant_ebus.time_program_service"]
INIT = sys.modules["vaillant_ebus.integration_init"]
HomeAssistantError = sys.modules["homeassistant.exceptions"].HomeAssistantError
TIMER = load_backend("timer_program")
WEEKDAYS = TIMER.WEEKDAYS


class _FakeProgram:
    """One timer program of a CTLV2 controller, answering reads and writes like ebusd."""

    # Intent: hold the slots per weekday, the layout and the circuit the program lives on.
    # Why: the two proven layouts differ in the temperature column, the readable slots and the count message name.
    def __init__(
        self,
        prefix: str = "Z1Timer",
        with_temperature: bool = True,
        readable: int = 3,
        count_name: str = "Timeframes",
        circuit: str = "ctlv2",
    ) -> None:
        self.prefix = prefix
        self.with_temperature = with_temperature
        self.readable = readable
        self.count_name = count_name
        self.circuit = circuit
        self.days: dict[str, list[tuple[str, str, str]]] = {day: [] for day in WEEKDAYS}
        self.writes: list[str] = []
        self.reads: list[tuple[str, str, bool]] = []

    # Intent: answer slot and count reads; an unknown message or circuit reads as `element not found`.
    # Why: the services must tell a missing message apart from a bus error.
    async def read(self, circuit: str, name: str, field: str = "", force: bool = False) -> str:
        self.reads.append((circuit, name, force))
        if circuit != self.circuit or not name.startswith(f"{self.prefix}_"):
            return "ERR: element not found"
        if name == f"{self.prefix}_{self.count_name}":
            return ";".join(str(len(self.days[day])) for day in WEEKDAYS)
        if not name[-1].isdigit():
            return "ERR: element not found"
        day, index = name[len(self.prefix) + 1 : -1], int(name[-1])
        if index >= self.readable:
            return "ERR: element not found"
        slots = self.days[day]
        start, end, temperature = slots[index] if index < len(slots) else ("00:00", "00:00", "-")
        return f"{start};{end};{temperature}" if self.with_temperature else f"{start};{end}"

    # Intent: apply a slot write like the controller does.
    # Why: the owner's live test showed slot 1 acknowledged but ignored before slot 0 carried count 2.
    async def write(self, circuit: str, name: str, value: str, **kwargs: object) -> bool:
        self.writes.append(f"{circuit}.{name}={value}")
        parts = value.split(";")
        index, count, start, end = int(parts[0]), int(parts[1]), parts[2], parts[3]
        temperature = parts[4] if len(parts) > 4 else "-"
        day = name[len(self.prefix) + 1 :]
        slots = self.days[day]
        if count == 0:
            self.days[day] = []
        elif index == 0:
            self.days[day] = ([(start, end, temperature)] + slots[1:count])[:count]
            self.days[day] += [("00:00", "00:00", "-")] * (count - len(self.days[day]))
        elif index < len(slots):
            slots[index] = (start, end, temperature)
        return True


# Intent: a coordinator mock that routes reads and writes to the fake program.
# Why: the services only use the coordinator's read, write, refresh and circuit lookups.
def _coordinator(program: _FakeProgram, zones: dict[str, str] | None = None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.heating_circuit = "ctlv2"
    coordinator.zone_circuits = MagicMock(return_value=zones or {})
    coordinator.async_read_register = program.read
    coordinator.async_write_register = program.write
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


# Intent: the read service returns every weekday with times, temperatures and the layout, from ebusd's cache.
# Why: a dashboard card shows the week from this response; reading past the cache for display would load the bus.
async def test_read_returns_the_week_from_the_cache() -> None:
    program = _FakeProgram()
    program.days["Monday"] = [("06:00", "08:00", "21.0"), ("17:00", "24:00", "20.5")]
    program.days["Saturday"] = [("07:30", "23:00", "22.0")]

    result = await SERVICE.async_read_time_program(_coordinator(program), "Z1Timer")

    assert result["program"] == "Z1Timer"
    assert result["circuit"] == "ctlv2"
    assert result["temperature"] is True
    assert result["incomplete"] == []
    assert result["days"]["monday"] == [
        {"start": "06:00", "end": "08:00", "temperature": 21.0},
        {"start": "17:00", "end": "24:00", "temperature": 20.5},
    ]
    assert result["days"]["saturday"] == [{"start": "07:30", "end": "23:00", "temperature": 22.0}]
    assert result["days"]["tuesday"] == []
    assert list(result["days"]) == [day.lower() for day in WEEKDAYS]
    assert not any(force for _, _, force in program.reads)


# Intent: `force` reads every slot past ebusd's cache.
# Why: after a change made elsewhere (the controller's own display), the cache can be up to its max age old.
async def test_read_with_force_bypasses_the_cache() -> None:
    program = _FakeProgram(prefix="CcTimer", with_temperature=False)

    result = await SERVICE.async_read_time_program(_coordinator(program), "CcTimer", force=True)

    assert result["temperature"] is False
    assert all(force for _, _, force in program.reads)


# Intent: a day with more slots than the configuration can read is listed as incomplete, with its visible slots.
# Why: issue #208 config decodes only slot 0; a card must not show such a day as complete or let it be rewritten.
async def test_read_lists_days_with_hidden_slots_as_incomplete() -> None:
    program = _FakeProgram(prefix="HwcTimer", with_temperature=False, readable=1, count_name="Timeslots")
    program.days["Tuesday"] = [("03:00", "03:10", "-"), ("03:20", "03:30", "-")]

    result = await SERVICE.async_read_time_program(_coordinator(program), "HwcTimer")

    assert result["incomplete"] == ["tuesday"]
    assert result["days"]["tuesday"] == [{"start": "03:00", "end": "03:10", "temperature": None}]


# Intent: a program the controller does not know raises instead of returning an empty week.
# Why: an empty week would look like "no heating times" and invite overwriting it.
async def test_read_refuses_an_unknown_program() -> None:
    with pytest.raises(HomeAssistantError, match="not available"):
        await SERVICE.async_read_time_program(_coordinator(_FakeProgram()), "Z3Timer")


# Intent: zone programs are read from the circuit hosting the zone, other programs from the heating controller.
# Why: a zone can live on another circuit than the controller; an explicit circuit always wins.
def test_timer_circuit_routes_zones_to_their_host() -> None:
    coordinator = _coordinator(_FakeProgram(), zones={"z2": "vr71"})

    assert SERVICE.timer_circuit(coordinator, "Z2Timer") == "vr71"
    assert SERVICE.timer_circuit(coordinator, "Z2CoolingTimer") == "vr71"
    assert SERVICE.timer_circuit(coordinator, "Z1Timer") == "ctlv2"
    assert SERVICE.timer_circuit(coordinator, "HwcTimer") == "ctlv2"
    assert SERVICE.timer_circuit(coordinator, "HwcTimer", "other") == "other"
    coordinator.heating_circuit = None
    with pytest.raises(HomeAssistantError, match="not discovered"):
        SERVICE.timer_circuit(coordinator, "HwcTimer")


# Intent: writing two days sends slot 0 first with the new count for each day, reads back and returns the result.
# Why: the controller only keeps slot N when slot 0 was written with the new count first (issue #208).
async def test_write_replaces_each_day_slot_zero_first() -> None:
    program = _FakeProgram()
    program.days["Monday"] = [("05:00", "06:00", "19.0")]
    coordinator = _coordinator(program)

    result = await SERVICE.async_write_time_program(
        coordinator,
        "Z1Timer",
        ["monday", "Tue"],
        [
            {"start": "17:00", "end": "24:00", "temperature": 20.5},
            {"start": "06:00", "end": "08:00", "temperature": 21},
        ],
    )

    assert program.writes == [
        "ctlv2.Z1Timer_Monday=0;2;06:00;08:00;21.0",
        "ctlv2.Z1Timer_Monday=1;2;17:00;24:00;20.5",
        "ctlv2.Z1Timer_Tuesday=0;2;06:00;08:00;21.0",
        "ctlv2.Z1Timer_Tuesday=1;2;17:00;24:00;20.5",
    ]
    expected = [
        {"start": "06:00", "end": "08:00", "temperature": 21.0},
        {"start": "17:00", "end": "24:00", "temperature": 20.5},
    ]
    assert result == {"program": "Z1Timer", "circuit": "ctlv2", "days": {"monday": expected, "tuesday": expected}}
    assert coordinator.async_request_refresh.await_count == 2


# Intent: an empty slot list clears the day with count 0, with a temperature column only on that layout.
# Why: issue #208 and the myVAILLANT trace - `0;0;00:00;00:00` (plus `0.0` on the temperature layout) clears a day.
@pytest.mark.parametrize(
    ("with_temperature", "expected"),
    [(True, "ctlv2.Z1Timer_Sunday=0;0;00:00;00:00;0.0"), (False, "ctlv2.Z1Timer_Sunday=0;0;00:00;00:00")],
)
async def test_write_clears_a_day(with_temperature: bool, expected: str) -> None:
    program = _FakeProgram(with_temperature=with_temperature)

    result = await SERVICE.async_write_time_program(_coordinator(program), "Z1Timer", ["sunday"], [])

    assert program.writes == [expected]
    assert result["days"] == {"sunday": []}


# Intent: invalid slots are refused before anything is written.
# Why: a write the controller cannot store would leave a day half changed.
@pytest.mark.parametrize(
    ("slots", "message"),
    [
        ([{"start": "06:00", "end": "05:00"}], "end after it starts"),
        ([{"start": "06:00", "end": "08:00"}, {"start": "07:00", "end": "09:00"}], "overlap"),
        ([{"start": f"0{h}:00", "end": f"0{h}:30"} for h in range(1, 5)], "at most 3"),
        ([{"start": "06:05", "end": "08:00"}], "10-minute grid"),
        ([{"start": "6", "end": "08:00"}], "HH:MM"),
        ([{"start": "24:00", "end": "24:00"}], "valid time"),
        ([{"start": "06:00"}], "start` and `end"),
    ],
)
async def test_write_refuses_invalid_slots(slots: list, message: str) -> None:
    program = _FakeProgram(with_temperature=False)

    with pytest.raises(HomeAssistantError, match=message):
        await SERVICE.async_write_time_program(_coordinator(program), "Z1Timer", ["monday"], slots)
    assert program.writes == []


# Intent: an unknown weekday or an empty day list is refused before anything is written.
# Why: a typo must not write a different day.
@pytest.mark.parametrize("days", [["funday"], []])
async def test_write_refuses_bad_days(days: list[str]) -> None:
    program = _FakeProgram()

    with pytest.raises(HomeAssistantError):
        await SERVICE.async_write_time_program(_coordinator(program), "Z1Timer", days, [])
    assert program.writes == []


# Intent: a day the controller acknowledges but does not store fails, and the error names the days already written.
# Why: the owner's first live write was acknowledged and ignored; a caller must know which days changed.
async def test_write_reports_an_ignored_day_and_the_days_before_it() -> None:
    program = _FakeProgram()
    coordinator = _coordinator(program)
    working_write = program.write

    # Intent: acknowledge every write but store nothing on Tuesday.
    # Why: mirrors a controller that ignores one day.
    async def _ignore_tuesday(circuit: str, name: str, value: str, **kwargs: object) -> bool:
        return True if name.endswith("Tuesday") else await working_write(circuit, name, value, **kwargs)

    coordinator.async_write_register = _ignore_tuesday
    slot = [{"start": "06:00", "end": "08:00", "temperature": 21.0}]
    with pytest.raises(HomeAssistantError, match=r"did not store.*days already written: monday"):
        await SERVICE.async_write_time_program(coordinator, "Z1Timer", ["monday", "tuesday", "wednesday"], slot)
    assert program.days["Wednesday"] == []


# Intent: writing a day that holds a slot the configuration cannot read is refused before anything is written,
#         and the hidden slots stay stored.
# Why: review of PR #229 - the write action skipped the hidden-slot check, so on the issue #208 configuration the
#      count write `0;1;...` silently dropped the two slots the integration could not see.
async def test_write_refuses_a_day_with_hidden_slots() -> None:
    program = _FakeProgram(prefix="HwcTimer", with_temperature=False, readable=1, count_name="Timeslots")
    program.days["Tuesday"] = [("03:00", "03:10", "-"), ("03:20", "03:30", "-")]
    slot = [{"start": "06:00", "end": "08:00"}]

    with pytest.raises(HomeAssistantError, match="days already written: none"):
        await SERVICE.async_write_time_program(_coordinator(program), "HwcTimer", ["tuesday"], slot)
    assert program.writes == []
    assert len(program.days["Tuesday"]) == 2


# Intent: a stored temperature that differs from the requested one fails the write.
# Why: the card's promise is that what it shows is what the controller has; a dropped temperature must not pass.
async def test_write_checks_the_temperature() -> None:
    program = _FakeProgram()
    coordinator = _coordinator(program)
    working_write = program.write

    # Intent: store every slot with a fixed temperature.
    # Why: mirrors a controller that clamps or ignores the temperature column.
    async def _clamp(circuit: str, name: str, value: str, **kwargs: object) -> bool:
        return await working_write(circuit, name, value.rsplit(";", 1)[0] + ";20.0", **kwargs)

    coordinator.async_write_register = _clamp
    with pytest.raises(HomeAssistantError, match="did not store"):
        await SERVICE.async_write_time_program(
            coordinator, "Z1Timer", ["monday"], [{"start": "06:00", "end": "08:00", "temperature": 21.0}]
        )


# Intent: slots without a temperature on the temperature layout take the day's known temperature.
# Why: an automation that only moves times must not have to know the temperature.
async def test_write_keeps_the_known_temperature() -> None:
    program = _FakeProgram(prefix="HwcTimer")
    program.days["Friday"] = [("05:00", "06:00", "50.0")]

    await SERVICE.async_write_time_program(
        _coordinator(program), "HwcTimer", ["friday"], [{"start": "05:30", "end": "06:30"}]
    )

    assert program.writes == ["ctlv2.HwcTimer_Friday=0;1;05:30;06:30;50.0"]


# Intent: the service handlers route to the selected coordinator and return the response.
# Why: `SupportsResponse` services must return the data, not only log it like `read_parameter`.
async def test_service_handlers_return_the_response() -> None:
    program = _FakeProgram(prefix="CcTimer", with_temperature=False)
    program.days["Monday"] = [("06:00", "07:00", "-")]
    hass = MagicMock()
    hass.data = {"vaillant_ebus": {"entry-a": _coordinator(program)}}

    read = await INIT._svc_read_time_program(hass, SimpleNamespace(data={"program": "CcTimer"}))
    assert read["days"]["monday"] == [{"start": "06:00", "end": "07:00", "temperature": None}]

    written = await INIT._svc_write_time_program(
        hass, SimpleNamespace(data={"program": "CcTimer", "days": ["monday"], "slots": []})
    )
    assert written["days"] == {"monday": []}


# Intent: a slot ending at midnight (`24:00`) parses, sorts last and formats back to `24:00`.
# Why: the controller ends a slot at midnight with `24:00`, which `datetime.time` cannot hold; such slots read as empty.
def test_timer_program_handles_24_00() -> None:
    slot = TIMER.parse_slot("22:00;24:00;20.0")

    assert slot == TIMER.TimeSlot(time(22, 0), TIMER.END_OF_DAY, 20.0)
    assert TIMER.build_day_writes([slot], True, None) == ["0;1;22:00;24:00;20.0"]
    assert TIMER.slot_to_output(slot) == {"start": "22:00", "end": "24:00", "temperature": 20.0}
    assert TIMER.slot_from_input("22:00", "24:00") == TIMER.TimeSlot(time(22, 0), TIMER.END_OF_DAY)


# Intent: `write_day` refuses a day it has not inspected, before any bus write.
# Why: the hidden-slot guard lives inside `write_day`; a new write path that forgets to read the day first must fail
#      instead of writing blind (lesson from the PR #229 review).
async def test_write_day_refuses_a_day_it_never_read() -> None:
    program = _FakeProgram()
    access = SERVICE.TimerProgramAccess(_coordinator(program), "Z1Timer", "ctlv2")
    slot = TIMER.slot_from_input("06:00", "08:00", 21.0)

    with pytest.raises(HomeAssistantError, match="was not read before the change"):
        await access.write_day("Monday", [slot], True, 21.0)
    assert program.writes == []
