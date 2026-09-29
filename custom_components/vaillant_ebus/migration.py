"""One-time migrations for breaking entity-platform changes."""

from __future__ import annotations

from typing import Any

LEGACY_DATE_REGISTER_NAMES = frozenset(
    (
        "Z1HolidayStartPeriod",
        "Z1HolidayEndPeriod",
        "HwcHolidayStartPeriod",
        "HwcHolidayEndPeriod",
        "ManualCoolingStartDate",
        "ManualCoolingEndDate",
    )
)


# Retire only the former datetime entities that the date platform replaces.
def remove_legacy_datetime_date_entities(registry: Any, entry_id: str, domain: str) -> None:
    legacy_unique_ids = {f"{entry_id}_{name.lower()}" for name in LEGACY_DATE_REGISTER_NAMES}
    for registry_entry in registry.entities.get_entries_for_config_entry_id(entry_id):
        if (
            registry_entry.platform == domain
            and registry_entry.unique_id in legacy_unique_ids
            and registry_entry.entity_id.startswith("datetime.")
        ):
            registry.async_remove(registry_entry.entity_id)


# Intent: remove legacy sensor registry rows when discovery replaces them with selects.
# Why: HA cannot safely retain two platform entities with the same unique ID.
def remove_legacy_room_temp_switch_sensor_entities(
    registry: Any,
    entry_id: str,
    domain: str,
    select_unique_ids: set[str],
) -> None:
    if not select_unique_ids:
        return
    for registry_entry in registry.entities.get_entries_for_config_entry_id(entry_id):
        if (
            registry_entry.platform == domain
            and registry_entry.unique_id in select_unique_ids
            and registry_entry.entity_id.startswith("sensor.")
        ):
            registry.async_remove(registry_entry.entity_id)


# Intent: restore the legacy CTLV2 sensor after an integration disable caused by no-data startup.
# Why: this register remains a supported CTLV2 sensor even when ebusd temporarily reports no value.
def enable_legacy_room_temp_switch_sensor_entities(
    registry: Any,
    entry_id: str,
    domain: str,
    sensor_unique_ids: set[str],
) -> None:
    if not sensor_unique_ids:
        return
    entries = getattr(registry.entities, "get_entries_for_config_entry_id", lambda _entry_id: [])(entry_id)
    for registry_entry in entries:
        if (
            registry_entry.platform == domain
            and registry_entry.unique_id in sensor_unique_ids
            and registry_entry.entity_id.startswith("sensor.")
            and registry_entry.disabled_by == "integration"
        ):
            registry.async_update_entity(registry_entry.entity_id, disabled_by=None)


# Intent: disable stale room-temperature sensor entries from another controller alias.
# Why: a CTLV3 select must not coexist with a restored CTLV2 sensor for the same logical control.
def disable_legacy_room_temp_switch_sensor_aliases(
    registry: Any,
    entry_id: str,
    domain: str,
    register_name: str,
) -> None:
    entries = getattr(registry.entities, "get_entries_for_config_entry_id", lambda _entry_id: [])(entry_id)
    suffix = f"_{register_name.casefold()}"
    for registry_entry in entries:
        if (
            registry_entry.platform == domain
            and registry_entry.entity_id.startswith("sensor.")
            and registry_entry.unique_id.casefold().endswith(suffix)
            and registry_entry.disabled_by != "user"
        ):
            registry.async_update_entity(registry_entry.entity_id, disabled_by="integration")
