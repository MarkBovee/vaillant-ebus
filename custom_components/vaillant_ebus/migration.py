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
