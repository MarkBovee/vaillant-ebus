"""Tests for entity-platform migrations."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from tests import _component_loader  # noqa: F401 — loads the shared modules once

MIGRATION = sys.modules["vaillant_ebus.migration"]


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


# Intent: retire the old sensor entry only when its CTLV register becomes a select.
# Why: Home Assistant cannot change an entity's domain in place.
def test_removes_only_sensor_entities_replaced_by_selects() -> None:
    entry_id = "entry-1"
    unique_id = f"{entry_id}_ebusd_ctlv3_hc1roomtempswitchon"
    legacy = SimpleNamespace(
        entity_id="sensor.hc1_room_temp_switch_on",
        platform="vaillant_ebus",
        unique_id=unique_id,
    )
    same_unique_id_other_domain = SimpleNamespace(
        entity_id="select.hc1_room_temp_switch_on",
        platform="vaillant_ebus",
        unique_id=unique_id,
    )
    other_entry = SimpleNamespace(
        entity_id="sensor.hc1_room_temp_switch_on_2",
        platform="vaillant_ebus",
        unique_id="entry-2_ebusd_ctlv3_hc1roomtempswitchon",
    )
    other_entity = SimpleNamespace(
        entity_id="sensor.hc1_room_temp_modulation",
        platform="vaillant_ebus",
        unique_id=f"{entry_id}_ebusd_ctlv3_hc1roomtempmodulation",
    )
    registry = MagicMock()
    registry.entities.get_entries_for_config_entry_id.return_value = [
        legacy,
        same_unique_id_other_domain,
        other_entry,
        other_entity,
    ]

    MIGRATION.remove_legacy_room_temp_switch_sensor_entities(registry, entry_id, "vaillant_ebus", {unique_id})

    registry.async_remove.assert_called_once_with(legacy.entity_id)


# Intent: re-enable only an integration-disabled CTLV2 sensor after discovery confirms its owner.
# Why: previous no-data startup must not permanently hide the supported legacy entity.
def test_enables_only_integration_disabled_legacy_sensor() -> None:
    entry_id = "entry-1"
    unique_id = f"{entry_id}_ebusd_ctlv2_hc1roomtempswitchon"
    disabled = SimpleNamespace(
        entity_id="sensor.hc1_room_temp_switch_on",
        platform="vaillant_ebus",
        unique_id=unique_id,
        disabled_by="integration",
    )
    user_disabled = SimpleNamespace(
        entity_id="sensor.user_disabled_hc1_room_temp_switch_on",
        platform="vaillant_ebus",
        unique_id=unique_id,
        disabled_by="user",
    )
    registry = MagicMock()
    registry.entities.get_entries_for_config_entry_id.return_value = [disabled, user_disabled]

    MIGRATION.enable_legacy_room_temp_switch_sensor_entities(registry, entry_id, "vaillant_ebus", {unique_id})

    registry.async_update_entity.assert_called_once_with(disabled.entity_id, disabled_by=None)
