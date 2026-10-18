"""Tests for the registry cleanup helpers."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from tests import _component_loader

CLEANUP = sys.modules["vaillant_ebus.cleanup"]

ENTRY_ID = "entry-1"
DOMAIN = "vaillant_ebus"


# Intent: build one entity registry row with the fields the cleanup reads.
# Why: the helpers only touch these attributes, so a namespace stands in for the real registry entry.
def _row(entity_id: str, unique_id: str, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "entity_id": entity_id,
        "unique_id": f"{ENTRY_ID}_{unique_id}",
        "platform": DOMAIN,
        "device_id": None,
        "disabled_by": None,
        "hidden_by": None,
        "name": None,
        "icon": None,
        "area_id": None,
        "labels": set(),
        "aliases": set(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# Intent: build a registry stand-in that lists rows by config entry and drops removed rows.
# Why: the removal step reads the remaining rows to decide which devices are empty.
def _registry(rows: list[SimpleNamespace]) -> MagicMock:
    registry = MagicMock()
    by_id = {row.entity_id: row for row in rows}
    registry.entities.get_entries_for_config_entry_id.side_effect = lambda entry_id: list(by_id.values())
    registry.entities.values.side_effect = lambda: list(by_id.values())
    registry.async_remove.side_effect = lambda entity_id: by_id.pop(entity_id)
    return registry


# Intent: build a state-machine stand-in from a mapping of entity id to (state, attributes).
# Why: `restored: true` on an unavailable state is the signal that no entity provides the registry row.
def _states(values: dict[str, tuple[str, dict[str, object]]]) -> MagicMock:
    states = MagicMock()
    states.get.side_effect = lambda entity_id: (
        SimpleNamespace(state=values[entity_id][0], attributes=values[entity_id][1]) if entity_id in values else None
    )
    return states


RESTORED = ("unavailable", {"restored": True, "friendly_name": "Zone 2 Hc2zPort"})


# Intent: only a restored placeholder state marks an enabled registry row as an orphan.
# Why: the owner's 86 unavailable entities are rows that the running release no longer provides, while a live entity
#      that is unknown (no holiday set) or unavailable (ebusd down) must survive; the old purge deleted the former kind.
def test_only_restored_placeholders_are_orphans() -> None:
    rows = [
        _row("sensor.zone_2_hc2zport", "ebusd_sc_hc2zport"),
        _row("date.zone_1_holiday_start", "ebusd_ctlv2_z1holidaystartperiod"),
        _row("sensor.flow_temperature", "ebusd_hmu_flowtemp"),
        _row("sensor.gone_entity", "ebusd_hmu_gone"),
    ]
    states = _states(
        {
            "sensor.zone_2_hc2zport": RESTORED,
            "date.zone_1_holiday_start": ("unknown", {"friendly_name": "Zone 1 Holiday Start"}),
            "sensor.flow_temperature": ("unavailable", {"friendly_name": "Flow Temperature"}),
        }
    )

    report = CLEANUP.find_orphans(_registry(rows), states, ENTRY_ID, DOMAIN, set())

    assert [item.entity_id for item in report.orphans] == ["sensor.zone_2_hc2zport"]
    assert report.orphans[0].label == "Zone 2 Hc2zPort"
    assert report.kept_customized == ()


# Intent: rows of other config entries and other integrations are never listed.
# Why: the registry is shared; the cleanup may only touch this integration's own rows.
def test_other_platforms_are_ignored() -> None:
    rows = [_row("sensor.other", "x", platform="other_integration")]

    report = CLEANUP.find_orphans(_registry(rows), _states({"sensor.other": RESTORED}), ENTRY_ID, DOMAIN, set())

    assert report.orphans == () and report.kept_customized == ()


# Intent: an orphan the user renamed, labelled, hid or assigned to an area is kept and reported separately.
# Why: those changes are user data that a cleanup must not delete without the user asking for exactly that row.
def test_customized_orphans_are_kept_and_reported() -> None:
    rows = [
        _row("sensor.renamed", "a", name="My sensor"),
        _row("sensor.in_area", "b", area_id="kitchen"),
        _row("sensor.labelled", "c", labels={"important"}),
        _row("sensor.hidden", "d", hidden_by="user"),
        _row("sensor.plain", "e"),
    ]
    states = _states({row.entity_id: RESTORED for row in rows})

    report = CLEANUP.find_orphans(_registry(rows), states, ENTRY_ID, DOMAIN, set())

    assert [item.entity_id for item in report.orphans] == ["sensor.plain"]
    assert {item.entity_id for item in report.kept_customized} == {
        "sensor.renamed",
        "sensor.in_area",
        "sensor.labelled",
        "sensor.hidden",
    }


# Intent: rows the integration disabled are orphans only when the current discovery does not generate them.
# Why: entities disabled by default (compressor counters) are generated and must stay; stale alias rows are not.
# Rows the user disabled are never touched.
def test_integration_disabled_rows_follow_the_generated_set() -> None:
    rows = [
        _row("sensor.counter", "ebusd_hmux0_compressorhc", disabled_by="integration"),
        _row("sensor.stale_alias", "ebusd_ctlv2_hc1pumphours", disabled_by="integration"),
        _row("sensor.user_off", "ebusd_ctlv2_userthing", disabled_by="user"),
    ]
    generated = {f"{ENTRY_ID}_ebusd_hmux0_compressorhc"}

    report = CLEANUP.find_orphans(_registry(rows), _states({}), ENTRY_ID, DOMAIN, generated)

    assert [item.entity_id for item in report.orphans] == ["sensor.stale_alias"]


# Intent: hand-built entities that default to disabled are never reported; only generated description ids are checked.
# Why: the quick veto end entity registers as disabled by the integration and has no entity description, so a naive
#      "not generated" test would flag it again after every removal.
def test_disabled_hand_built_entities_are_not_orphans() -> None:
    rows = [
        _row("datetime.quick_veto_end", "quick_veto_end", disabled_by="integration"),
        _row("binary_sensor.online", "ebusd_online", disabled_by="integration"),
        _row("sensor.stale_alias", "ebusd_ctlv2_hc1pumphours", disabled_by="integration"),
        _row("sensor.vr71_alias", "ebusd_vr_71_oldthing", disabled_by="integration"),
    ]

    report = CLEANUP.find_orphans(_registry(rows), _states({}), ENTRY_ID, DOMAIN, set())

    assert [item.entity_id for item in report.orphans] == ["sensor.stale_alias", "sensor.vr71_alias"]


# Intent: the legacy internal helper rows are removed whatever their state is.
# Why: earlier releases created `tmpb516montheven` helpers that nothing provides any more.
def test_legacy_helper_rows_are_always_orphans() -> None:
    rows = [_row("sensor.helper", "ebusd_hmu_tmpb516montheven")]

    report = CLEANUP.find_orphans(
        _registry(rows), _states({"sensor.helper": ("unknown", {})}), ENTRY_ID, DOMAIN, set()
    )

    assert [item.entity_id for item in report.orphans] == ["sensor.helper"]


# Intent: removing orphans takes the entities out, then only the devices that have no entity left.
# Why: an empty Zone 2 device should disappear with its entities, while a device that still has entities stays.
def test_remove_orphans_removes_empty_devices_only() -> None:
    rows = [
        _row("sensor.zone_2_a", "a", device_id="dev-zone2"),
        _row("sensor.zone_2_b", "b", device_id="dev-zone2"),
        _row("sensor.zone_1_a", "c", device_id="dev-zone1"),
        _row("sensor.zone_1_orphan", "d", device_id="dev-zone1"),
    ]
    registry = _registry(rows)
    devices = MagicMock()
    devices.devices = {
        "dev-zone2": SimpleNamespace(config_entries={ENTRY_ID}, identifiers={(DOMAIN, "z2")}),
        "dev-zone1": SimpleNamespace(config_entries={ENTRY_ID}, identifiers={(DOMAIN, "z1")}),
        "dev-foreign": SimpleNamespace(config_entries={"entry-2"}, identifiers={(DOMAIN, "z9")}),
        "dev-other-domain": SimpleNamespace(config_entries={ENTRY_ID}, identifiers={("other", "x")}),
    }

    result = CLEANUP.remove_orphans(
        registry, devices, ENTRY_ID, DOMAIN, ["sensor.zone_2_a", "sensor.zone_2_b", "sensor.zone_1_orphan"]
    )

    assert (result.entities, result.devices) == (3, 1)
    devices.async_remove_device.assert_called_once_with("dev-zone2")


# Intent: the confirmation text names the first orphans and counts the rest.
# Why: a user can only confirm a removal after seeing what goes; a list of eighty rows would not fit a dialog.
def test_preview_text_names_the_first_orphans_and_counts_the_rest() -> None:
    orphans = [CLEANUP.OrphanEntity(f"sensor.x{number}", f"u{number}", f"Entity {number}") for number in range(20)]

    text = CLEANUP.preview_text(orphans, limit=3)

    assert text.splitlines() == [
        "- Entity 0 (sensor.x0)",
        "- Entity 1 (sensor.x1)",
        "- Entity 2 (sensor.x2)",
        "- ... and 17 more",
    ]


# Intent: build a coordinator stand-in with the three attributes the report needs.
# Why: the stale-entity report is only trustworthy while ebusd is connected and entities have been generated.
def _coordinator(connected: bool = True, entities: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        ebus=SimpleNamespace(is_connected=connected),
        entities=[SimpleNamespace(unique_id=f"ebusd_hmu_generated{number}") for number in range(entities)],
    )


# Intent: the report is refused without a connection or without generated entities.
# Why: before discovery finishes every row looks orphaned; removing them then would delete live entities.
def test_stale_report_needs_a_connected_coordinator_with_entities() -> None:
    registry = _registry([_row("sensor.gone", "ebusd_hmu_gone")])
    states = _states({"sensor.gone": RESTORED})

    assert CLEANUP.stale_report(registry, states, ENTRY_ID, DOMAIN, None) is None
    assert CLEANUP.stale_report(registry, states, ENTRY_ID, DOMAIN, _coordinator(connected=False)) is None
    assert CLEANUP.stale_report(registry, states, ENTRY_ID, DOMAIN, _coordinator(entities=0)) is None
    report = CLEANUP.stale_report(registry, states, ENTRY_ID, DOMAIN, _coordinator())
    assert [item.entity_id for item in report.orphans] == ["sensor.gone"]


# Intent: the generated unique ids come from the coordinator entity descriptions with the config entry prefix.
# Why: a disabled-by-default entity that discovery still generates must not be reported as stale.
def test_stale_report_keeps_disabled_entities_that_discovery_generates() -> None:
    rows = [
        _row("sensor.counter", "ebusd_hmu_generated0", disabled_by="integration"),
        _row("sensor.stale", "ebusd_hmu_stale", disabled_by="integration"),
    ]

    report = CLEANUP.stale_report(_registry(rows), _states({}), ENTRY_ID, DOMAIN, _coordinator())

    assert [item.entity_id for item in report.orphans] == ["sensor.stale"]


REPAIRS = _component_loader._exec_source("vaillant_ebus.repairs_real", _component_loader.COMPONENT_PATH / "repairs.py")


# Intent: wire a repairs flow with the Home Assistant calls it makes, returning the registries it should use.
# Why: the base class is a stub in the unit tests, so the flow show-form, create-entry and abort calls are mocks.
def _flow(rows: list[SimpleNamespace], connected: bool = True) -> tuple[Any, MagicMock, MagicMock]:
    registry = _registry(rows)
    devices = MagicMock()
    devices.devices = {}
    sys.modules["homeassistant.helpers.entity_registry"].async_get = MagicMock(return_value=registry)
    sys.modules["homeassistant.helpers.device_registry"].async_get = MagicMock(return_value=devices)
    flow = REPAIRS.StaleEntitiesRepairFlow(ENTRY_ID)
    flow.hass = SimpleNamespace(
        data={DOMAIN: {ENTRY_ID: _coordinator(connected=connected)}},
        states=_states({row.entity_id: RESTORED for row in rows}),
    )
    flow.async_show_form = MagicMock(return_value={"type": "form"})
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    flow.async_abort = MagicMock(return_value={"type": "abort"})
    return flow, registry, devices


# Intent: the fix flow routes the stale-entities issue to its own flow and every other issue to the plain confirm.
# Why: Home Assistant asks the platform for one flow per issue id; the ebusd repair keeps its confirm-only flow.
async def test_fix_flow_is_chosen_by_issue_id() -> None:
    stale = await REPAIRS.async_create_fix_flow(MagicMock(), REPAIRS.ISSUE_STALE_ENTITIES, {"entry_id": ENTRY_ID})
    other = await REPAIRS.async_create_fix_flow(MagicMock(), REPAIRS.ISSUE_EBUSD_UNREACHABLE, None)

    assert isinstance(stale, REPAIRS.StaleEntitiesRepairFlow)
    assert not isinstance(other, REPAIRS.StaleEntitiesRepairFlow)


# Intent: the first step shows the count and the names, and removes nothing.
# Why: the user decides after seeing which entities go; showing the list must not change the registry.
async def test_fix_flow_shows_the_preview_without_removing() -> None:
    flow, registry, _ = _flow([_row("sensor.gone", "ebusd_hmu_gone")])

    result = await flow.async_step_init()

    assert result == {"type": "form"}
    placeholders = flow.async_show_form.call_args.kwargs["description_placeholders"]
    assert placeholders["count"] == "1" and "sensor.gone" in placeholders["entities"]
    registry.async_remove.assert_not_called()


# Intent: confirming removes the listed orphans and finishes the flow, which clears the issue.
# Why: Home Assistant deletes the issue when a repairs flow ends with an entry; the removal must happen first.
async def test_fix_flow_removes_the_orphans_on_confirm() -> None:
    flow, registry, _ = _flow([_row("sensor.gone", "ebusd_hmu_gone"), _row("sensor.gone2", "ebusd_hmu_gone2")])

    result = await flow.async_step_confirm({})

    assert result == {"type": "create_entry"}
    assert [call.args[0] for call in registry.async_remove.call_args_list] == ["sensor.gone", "sensor.gone2"]


# Intent: the flow aborts instead of removing anything when ebusd is not connected.
# Why: without discovery the report is unreliable, so the repair must not touch the registry.
async def test_fix_flow_aborts_without_a_connection() -> None:
    flow, registry, _ = _flow([_row("sensor.gone", "ebusd_hmu_gone")], connected=False)

    result = await flow.async_step_confirm({})

    assert result == {"type": "abort"}
    registry.async_remove.assert_not_called()
