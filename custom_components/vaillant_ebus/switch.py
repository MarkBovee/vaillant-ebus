"""Switch platform for Vaillant EBUS."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backend.entity_factory import EntityDescription
from .backend.models import is_no_data_value
from .const import DOMAIN
from .coordinator import VaillantCoordinator, get_register_value

_LOGGER = logging.getLogger(__name__)

SWITCH_ON_VALUES = {"1", "on", "true", "yes"}
FAR_FUTURE = "01.01.2099"
UNSET_DATE = "01.01.2015"
UNSET_DATES = frozenset(("01.01.2015", "01.01.2019"))


# Create switch entities and away-mode switch
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaillantCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _build(descriptions: list[EntityDescription]) -> list[SwitchEntity]:
        entities: list[SwitchEntity] = []
        seen: set[str] = set()
        for desc in descriptions:
            if desc.entity_type != "switch":
                continue
            uid = f"{entry.entry_id}_{desc.unique_id}"
            if uid in seen:
                continue
            seen.add(uid)
            entities.append(EbusdSwitch(coordinator, desc, uid, entry))
        return entities

    async_add_entities(_build(coordinator.entities))
    fixed_added: set[str] = set()

    # Intent: add each fixed switch only when every register it writes is discovered.
    # Why: partial capability sets must not expose controls that can issue partial writes.
    def _ensure_fixed_entities() -> None:
        if not coordinator.discovery_ready:
            return
        entities: list[SwitchEntity] = []
        primary_zone = coordinator.primary_zone
        controller = coordinator.heating_circuit
        if (
            primary_zone
            and controller
            and all(
                coordinator.has_zone_register(controller, primary_zone, register)
                for register in ("HolidayStartPeriod", "HolidayEndPeriod", "HolidayTemp")
            )
            and all(
                coordinator.has_controller_register(register)
                for register in ("HwcHolidayStartPeriod", "HwcHolidayEndPeriod")
            )
            and "away" not in fixed_added
        ):
            entities.append(AwayModeSwitch(coordinator, entry, primary_zone))
            fixed_added.add("away")
        if coordinator.has_controller_register("HwcSFMode") and "boost" not in fixed_added:
            entities.append(HwcBoostSwitch(coordinator, entry))
            fixed_added.add("boost")
        if (
            all(
                coordinator.has_controller_register(register)
                for register in ("HwcHolidayStartPeriod", "HwcHolidayEndPeriod")
            )
            and "hwc_away" not in fixed_added
        ):
            entities.append(HwcAwayModeSwitch(coordinator, entry))
            fixed_added.add("hwc_away")
        if entities:
            async_add_entities(entities)

    _ensure_fixed_entities()
    coordinator.register_post_discovery_callback(_ensure_fixed_entities)
    coordinator.register_entity_adder("switch", lambda descriptions: async_add_entities(_build(descriptions)))


class EbusdSwitch(CoordinatorEntity[VaillantCoordinator], SwitchEntity):
    # Initialize switch entity from entity description
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        desc: EntityDescription,
        unique_id: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._desc = desc
        self._attr_unique_id = unique_id
        self._attr_has_entity_name = True
        self._attr_entity_registry_enabled_default = desc.enabled_by_default
        self._attr_device_info = coordinator.get_device_info(desc.device_circuit)
        self._attr_name = desc.meta.friendly_name or desc.name
        if desc.meta.icon:
            self._attr_icon = desc.meta.icon

    @property
    def is_on(self) -> bool | None:
        # Return boolean state; ebusd sentinels mean "unknown", not off.
        raw = get_register_value(self.coordinator, self._desc.circuit, self._desc.name, self._desc.field)
        if raw is None or is_no_data_value(str(raw)):
            return None
        return raw.strip().lower() in SWITCH_ON_VALUES

    # Turn switch on by writing "1" to ebusd
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write("1")

    # Turn switch off by writing "0" to ebusd
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write("0")

    # Write value to ebusd through the central write path
    async def _write(self, value: str) -> None:
        if not self.coordinator.ebus:
            return
        ok = await self.coordinator.async_write_register(self._desc.circuit, self._desc.name, value)
        if not ok:
            _LOGGER.warning("Write failed for %s", self._desc.key)
            return
        # Reflect the command immediately so the UI does not bounce back to the
        # previous state while ebusd has not yet refreshed its read cache. The
        # write is already confirmed by the read-back verification; the next
        # periodic poll still reconciles and a later external override wins.
        self.coordinator.data.setdefault("ebusd", {})[self._desc.key] = value
        self.coordinator.async_update_listeners()


# Parse Vaillant date string to date object
def _parse_date(raw: str | None) -> date | None:
    if not raw or "-" in raw or "no data" in raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%d.%m.%Y").date()
    except ValueError, TypeError:
        return None


# Check if today falls within holiday period
def _is_holiday_active(start_raw: str | None, end_raw: str | None) -> bool:
    if start_raw in UNSET_DATES or end_raw in UNSET_DATES:
        return False
    start = _parse_date(start_raw)
    end = _parse_date(end_raw)
    if start is None or end is None:
        return False
    today = date.today()
    return start <= today <= end


# Return today's date as DD.MM.YYYY string
def _today_str() -> str:
    return date.today().strftime("%d.%m.%Y")


AWAY_ZONE_REGISTERS = ("HolidayStartPeriod", "HolidayEndPeriod", "HolidayTemp")


# Intent: report whether a zone currently reports a real room temperature.
# Why: a placeholder zone keeps static defaults, so only a live room temperature proves the zone is installed.
def _zone_has_room_temperature(coordinator: VaillantCoordinator, controller: str, zone: str) -> bool:
    value = get_register_value(coordinator, controller, f"{zone.upper()}RoomTemp")
    return value is not None and not is_no_data_value(value)


# Intent: list the zones whose holiday period the away switch reads and writes, primary zone first.
# Why: issue #186 - away mode must cover every live zone, but never a placeholder zone or one whose holiday registers
# were not discovered; the primary zone stays unconditional so single-zone systems behave exactly as before.
def _away_zones(coordinator: VaillantCoordinator, primary_zone: str) -> list[str]:
    controller = coordinator.heating_circuit
    if controller is None:
        return []
    others = [
        zone
        for zone, circuit in coordinator.zone_circuits().items()
        if zone != primary_zone
        and circuit.casefold() == controller.casefold()
        and all(coordinator.has_zone_register(controller, zone, register) for register in AWAY_ZONE_REGISTERS)
        and _zone_has_room_temperature(coordinator, controller, zone)
    ]
    return [primary_zone, *sorted(others, key=lambda zone: int(zone[1:]) if zone[1:].isdigit() else 0)]


# Intent: report whether one zone is on holiday: True, False, or None when its dates cannot be read.
# Why: an explicit "unset" start date proves the zone is not away even when the end register is unreadable, but a
# missing or no-data register is unknown and must never be coerced into "not away" (issue #186 audit).
def _zone_away_state(coordinator: VaillantCoordinator, controller: str, zone: str) -> bool | None:
    start = get_register_value(coordinator, controller, f"{zone.upper()}HolidayStartPeriod")
    end = get_register_value(coordinator, controller, f"{zone.upper()}HolidayEndPeriod")
    if start in UNSET_DATES:
        return False
    if start is None or end is None or is_no_data_value(start) or is_no_data_value(end):
        return None
    return _is_holiday_active(start, end)


class AwayModeSwitch(CoordinatorEntity[VaillantCoordinator], SwitchEntity):
    # Initialize away mode switch with unique ID
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
        zone: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_away_mode"
        self._attr_has_entity_name = True
        self._attr_name = "Away Mode"
        self._attr_icon = "mdi:exit-run"
        self._zone = zone
        self._attr_device_info = coordinator.get_device_info(zone)

    @property
    def is_on(self) -> bool | None:
        # True when every live zone is on holiday; one zone that is provably not away makes it off, and unreadable
        # data stays unknown unless another zone already proves the system is not away.
        circuit = self.coordinator.heating_circuit
        zones = _away_zones(self.coordinator, self._zone)
        if circuit is None or not zones:
            return None
        states = [_zone_away_state(self.coordinator, circuit, zone) for zone in zones]
        if False in states:
            return False
        if None in states:
            return None
        return True

    # Set holiday dates from today to far future for every live zone and the DHW, enable away mode
    async def async_turn_on(self, **kwargs: Any) -> None:
        circuit = self.coordinator.heating_circuit
        zones = _away_zones(self.coordinator, self._zone)
        if not self.coordinator.ebus or circuit is None or not zones:
            return
        today = _today_str()
        writes: list[tuple[str, str, str]] = []
        for zone in zones:
            writes.append((circuit, f"{zone.upper()}HolidayStartPeriod", today))
            writes.append((circuit, f"{zone.upper()}HolidayEndPeriod", FAR_FUTURE))
        writes.append((circuit, "HwcHolidayStartPeriod", today))
        writes.append((circuit, "HwcHolidayEndPeriod", FAR_FUTURE))
        for zone in zones:
            # Each zone keeps its own configured holiday temperature; 15 only when the register has no value.
            holiday_temp = get_register_value(self.coordinator, circuit, f"{zone.upper()}HolidayTemp") or "15"
            writes.append((circuit, f"{zone.upper()}HolidayTemp", holiday_temp))
        await self.coordinator.async_write_registers(writes)

    # Reset holiday dates to unset for every live zone and the DHW, disable away mode
    async def async_turn_off(self, **kwargs: Any) -> None:
        circuit = self.coordinator.heating_circuit
        zones = _away_zones(self.coordinator, self._zone)
        if not self.coordinator.ebus or circuit is None or not zones:
            return
        writes: list[tuple[str, str, str]] = []
        for zone in zones:
            writes.append((circuit, f"{zone.upper()}HolidayStartPeriod", UNSET_DATE))
            writes.append((circuit, f"{zone.upper()}HolidayEndPeriod", UNSET_DATE))
        writes.append((circuit, "HwcHolidayStartPeriod", UNSET_DATE))
        writes.append((circuit, "HwcHolidayEndPeriod", UNSET_DATE))
        writes.extend((circuit, f"{zone.upper()}HolidayTemp", "15") for zone in zones)
        await self.coordinator.async_write_registers(writes)


class HwcBoostSwitch(CoordinatorEntity[VaillantCoordinator], SwitchEntity):
    """Toggle DHW boost mode via HwcSFMode register."""

    # Initialize DHW boost switch with unique ID and DHW device
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_hwc_boost"
        self._attr_has_entity_name = True
        self._attr_name = "DHW Boost"
        self._attr_icon = "mdi:water-boiler"
        self._attr_device_info = coordinator.get_device_info("dhw")

    # True when DHW boost was requested (desired state), falling back to the
    # raw HwcSFMode register on first load. The raw register reports "load"
    # while the cylinder charges even after boost is turned off, so the desired
    # state is the authoritative source once a toggle has happened.
    @property
    def is_on(self) -> bool | None:
        desired = self.coordinator.dhw_boost_desired
        if desired is not None:
            return desired
        circuit = self.coordinator.heating_circuit
        if circuit is None:
            return None
        raw = get_register_value(self.coordinator, circuit, "HwcSFMode")
        if raw is None:
            return None
        return raw.strip().lower() == "load"

    # Write "load" to HwcSFMode to start DHW boost
    async def async_turn_on(self, **kwargs: Any) -> None:
        circuit = self.coordinator.heating_circuit
        if circuit is None:
            return
        if await self.coordinator.async_write_register(
            circuit, "HwcSFMode", "load", strict_verify=False, refresh=False
        ):
            self.coordinator.dhw_boost_desired = True
            self.coordinator.async_update_listeners()
            await self.coordinator.async_request_refresh()

    # Write "auto" to HwcSFMode to stop DHW boost
    async def async_turn_off(self, **kwargs: Any) -> None:
        circuit = self.coordinator.heating_circuit
        if circuit is None:
            return
        if await self.coordinator.async_write_register(
            circuit, "HwcSFMode", "auto", strict_verify=False, refresh=False
        ):
            self.coordinator.dhw_boost_desired = False
            self.coordinator.async_update_listeners()
            await self.coordinator.async_request_refresh()


class HwcAwayModeSwitch(CoordinatorEntity[VaillantCoordinator], SwitchEntity):
    """Toggle DHW holiday mode by setting HwcHolidayStartPeriod/EndPeriod."""

    # Initialize DHW away mode switch with unique ID and DHW device
    def __init__(
        self,
        coordinator: VaillantCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_hwc_away_mode"
        self._attr_has_entity_name = True
        self._attr_name = "DHW Away Mode"
        self._attr_icon = "mdi:water-boiler-off"
        self._attr_device_info = coordinator.get_device_info("dhw")

    # True when HwcHolidayStartPeriod/EndPeriod contain today
    @property
    def is_on(self) -> bool | None:
        circuit = self.coordinator.heating_circuit
        if circuit is None:
            return None
        start = get_register_value(self.coordinator, circuit, "HwcHolidayStartPeriod")
        end = get_register_value(self.coordinator, circuit, "HwcHolidayEndPeriod")
        # An explicit "unset" start date already proves away mode is off, even when the end register is unreadable.
        if start in UNSET_DATES:
            return False
        if start is None or end is None:
            return None
        return _is_holiday_active(start, end)

    # Set DHW holiday from today to far future
    async def async_turn_on(self, **kwargs: Any) -> None:
        ckt = self.coordinator.heating_circuit
        if ckt is None:
            return
        await self.coordinator.async_write_registers(
            [
                (ckt, "HwcHolidayStartPeriod", _today_str()),
                (ckt, "HwcHolidayEndPeriod", FAR_FUTURE),
            ]
        )

    # Reset DHW holiday dates to unset value
    async def async_turn_off(self, **kwargs: Any) -> None:
        ckt = self.coordinator.heating_circuit
        if ckt is None:
            return
        await self.coordinator.async_write_registers(
            [
                (ckt, "HwcHolidayStartPeriod", UNSET_DATE),
                (ckt, "HwcHolidayEndPeriod", UNSET_DATE),
            ]
        )
