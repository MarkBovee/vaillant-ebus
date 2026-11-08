"""Read and write single weekdays of a controller timer program over ebusd.

Shared by the calendar platform and the `read_time_program` / `write_time_program` services, so both use the same
safety rules: a slot that cannot be read stops a change, a day is written slot 0 first, and every write is read back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.exceptions import HomeAssistantError

from .backend.timer_program import (
    MAX_SLOTS_PER_DAY,
    SLOT_COUNT_SUFFIXES,
    WEEKDAYS,
    TimerProgramError,
    TimeSlot,
    build_day_writes,
    ensure_all_slots_visible,
    has_temperature_column,
    parse_slot,
    parse_slot_counts,
)

if TYPE_CHECKING:
    from .coordinator import VaillantCoordinator


@dataclass(frozen=True)
class DayRead:
    """What the controller answered for one weekday."""

    # The visible slots in controller order.
    slots: list[TimeSlot]
    # Whether the slot messages carry a temperature column (the write message then expects one too).
    with_temperature: bool
    # The slot count from the count message, or None when this configuration has no count message.
    counted: int | None
    # How many slot messages this configuration can read (0 to 3).
    readable: int

    # Whether every slot the controller counts is visible, so the day can be shown and rewritten safely.
    @property
    def complete(self) -> bool:
        if self.counted is None:
            return self.readable == MAX_SLOTS_PER_DAY
        return self.counted <= len(self.slots)


class TimerProgramAccess:
    """One timer program (`Z1Timer`, `HwcTimer`, ...) on one circuit."""

    # Remember the coordinator, the message prefix and the circuit that hosts the program.
    def __init__(self, coordinator: VaillantCoordinator, prefix: str, circuit: str) -> None:
        self.coordinator = coordinator
        self.prefix = prefix
        self.circuit = circuit
        # Slots per weekday that this configuration can read, learned at each read of the day.
        self.readable_slots: dict[str, int] = {}
        # The last inspection of each weekday. `write_day` checks it for hidden slots before its first bus write.
        self._last_reads: dict[str, DayRead] = {}

    # Read one weekday without judging it: slots, layout, count and how many slot messages decode.
    # `force` reads past ebusd's cache; a read for display may use the cache.
    async def inspect_day(self, day: str, force: bool = True) -> DayRead:
        raw = [await self._read(f"{self.prefix}_{day}{index}", force) for index in range(MAX_SLOTS_PER_DAY)]
        slots = [slot for slot in (parse_slot(value) for value in raw) if slot is not None]
        readable = sum(value is not None for value in raw)
        self.readable_slots[day] = readable
        read = DayRead(
            slots=slots,
            with_temperature=any(has_temperature_column(value) for value in raw if value),
            counted=await self._slot_count(day, force),
            readable=readable,
        )
        self._last_reads[day] = read
        return read

    # Read every slot of a weekday straight from the controller and check that none is hidden.
    # Returns the visible slots in order and whether the layout carries a temperature per slot.
    async def read_day(self, day: str) -> tuple[list[TimeSlot], bool]:
        read = await self.inspect_day(day)
        self.ensure_no_hidden_slots(day, read)
        # A copy: callers edit the list in place (the calendar pops a slot), and the guard in `write_day` must still
        # see what the controller answered.
        return list(read.slots), read.with_temperature

    # Refuse a change to a day that holds a slot this configuration cannot read, because rewriting the day would
    # drop it. `write_day` runs it before its first write, so every write path refuses before anything is written.
    @staticmethod
    def ensure_no_hidden_slots(day: str, read: DayRead) -> None:
        if read.counted is None and read.readable < MAX_SLOTS_PER_DAY:
            # Without a count message, an undefined slot read could hide a slot; only a fully readable day is safe.
            raise HomeAssistantError(
                f"Not every time slot of {day} can be read on this controller; nothing was changed"
            )
        try:
            ensure_all_slots_visible(day, read.slots, read.counted)
        except TimerProgramError as exc:
            raise HomeAssistantError(str(exc)) from exc

    # Write one weekday slot by slot, then read it back and refresh the coordinator.
    # A write the controller acknowledges but ignores is caught by comparing the read-back with the request.
    # Returns the slots the controller stored.
    async def write_day(
        self,
        day: str,
        slots: list[TimeSlot],
        with_temperature: bool,
        default_temperature: float | None,
        compare_temperature: bool = False,
    ) -> list[TimeSlot]:
        # The hidden-slot guard lives here, not in the callers: the PR #229 action skipped it once, and the count
        # write would have dropped slots this configuration cannot read. Without an inspection there is nothing to
        # check, so the write is refused.
        last_read = self._last_reads.get(day)
        if last_read is None:
            raise HomeAssistantError(f"{self.prefix}_{day} was not read before the change; nothing was changed")
        self.ensure_no_hidden_slots(day, last_read)
        readable = self.readable_slots.get(day, MAX_SLOTS_PER_DAY)
        if len(slots) > readable:
            # A slot the configuration cannot read back could neither be checked nor shown (issue #208 config).
            raise HomeAssistantError(
                f"This controller configuration can only read {readable} time slot(s) per day; nothing was changed"
            )
        try:
            writes = build_day_writes(slots, with_temperature, default_temperature)
        except TimerProgramError as exc:
            raise HomeAssistantError(str(exc)) from exc
        name = f"{self.prefix}_{day}"
        for value in writes:
            ok = await self.coordinator.async_write_register(
                self.circuit, name, value, strict_verify=False, refresh=False, require_discovered=False
            )
            if not ok:
                raise HomeAssistantError(f"ebusd did not accept writing {value!r} to {name}")
        stored, _ = await self.read_day(day)
        if not _same_slots(stored, sorted(slots), compare_temperature and with_temperature):
            raise HomeAssistantError(f"The controller did not store the new time slots for {day}")
        await self.coordinator.async_request_refresh()
        return stored

    # Read one register; a message this configuration does not define reads as no value.
    # Any other failure stops the change: a slot that could not be read would look free, and rewriting the day
    # would then drop it.
    async def _read(self, name: str, force: bool) -> str | None:
        value = await self.coordinator.async_read_register(self.circuit, name, force=force)
        if value is None or (value.startswith("ERR:") and "element not found" not in value.casefold()):
            # One retry: a single bus error (a read timeout on the owner's controller) should not block the change.
            value = await self.coordinator.async_read_register(self.circuit, name, force=True)
        if value is not None and "element not found" in value.casefold():
            return None
        if value is None or value.startswith("ERR:"):
            raise HomeAssistantError(f"Could not read {name} from the controller; nothing was changed")
        return value

    # Read the controller's slot count for a weekday, or None when this configuration has no count message.
    async def _slot_count(self, day: str, force: bool) -> int | None:
        for suffix in SLOT_COUNT_SUFFIXES:
            counts = parse_slot_counts(await self._read(f"{self.prefix}_{suffix}", force))
            if counts is not None:
                return counts[WEEKDAYS.index(day)]
        return None


# Compare stored and requested slots by their times and, when asked, by their temperatures.
def _same_slots(stored: list[TimeSlot], requested: list[TimeSlot], with_temperature: bool) -> bool:
    if with_temperature:
        return stored == requested
    return [(slot.start, slot.end) for slot in stored] == [(slot.start, slot.end) for slot in requested]
