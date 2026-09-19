"""Tests for entity-platform migrations."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"

for name in ("vaillant_ebus",):
    package = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    package.__path__ = [str(COMPONENT_PATH)]
    sys.modules[name] = package

MIGRATION_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.migration", COMPONENT_PATH / "migration.py")
assert MIGRATION_SPEC and MIGRATION_SPEC.loader
MIGRATION = importlib.util.module_from_spec(MIGRATION_SPEC)
sys.modules["vaillant_ebus.migration"] = MIGRATION
MIGRATION_SPEC.loader.exec_module(MIGRATION)


# Legacy datetime entries are removed so their date-platform replacements do not create stale duplicates.
# Intent: retire exactly the six old date-only datetime entities for the migrating config entry.
# Why: entity domains cannot be renamed in Home Assistant's registry and stale datetime entries restore unavailable.
def test_removes_only_legacy_date_only_datetime_entities() -> None:
    entry_id = "entry-1"
    legacy = SimpleNamespace(
        entity_id="datetime.boiler_dhw_dhw_holiday_start",
        platform="vaillant_ebus",
        unique_id=f"{entry_id}_hwcholidaystartperiod",
    )
    unrelated = SimpleNamespace(
        entity_id="datetime.quick_veto_end",
        platform="vaillant_ebus",
        unique_id=f"{entry_id}_quick_veto_end",
    )
    other_entry = SimpleNamespace(
        entity_id="datetime.zone_1_z1_holiday_start",
        platform="vaillant_ebus",
        unique_id="entry-2_z1holidaystartperiod",
    )
    date_replacement = SimpleNamespace(
        entity_id="date.boiler_dhw_dhw_holiday_start",
        platform="vaillant_ebus",
        unique_id=f"{entry_id}_hwcholidaystartperiod",
    )
    registry = MagicMock()
    registry.entities.get_entries_for_config_entry_id.return_value = [legacy, unrelated, other_entry, date_replacement]

    MIGRATION.remove_legacy_datetime_date_entities(registry, entry_id, "vaillant_ebus")

    registry.async_remove.assert_called_once_with(legacy.entity_id)
