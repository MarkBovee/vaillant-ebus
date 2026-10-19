"""Tests for the registry cleanup helpers."""

from __future__ import annotations

import enum
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
    registry.async_get.side_effect = by_id.get
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


class _ComputedName(enum.Enum):
    """Stand-in for Home Assistant's `COMPUTED_NAME` alias sentinel, which is a truthy enum member."""

    SINGLETON = 0


# Intent: the default alias Home Assistant gives every entity is not a user customisation; an alias the user typed is.
# Why: since Home Assistant 2026.10 each registry row holds the "use the entity name" alias as a sentinel (null on disk,
#      an enum member in memory). Counting it made every row look customised, so the live system offered nothing to
#      purge for its 127 restored rows. Only a non-blank alias text is user data.
def test_default_computed_name_alias_is_not_a_customisation() -> None:
    default = _ComputedName.SINGLETON
    rows = [
        _row("sensor.default_alias", "a", aliases=[default]),
        _row("sensor.null_alias", "b", aliases=[None]),
        _row("sensor.blank_alias", "c", aliases=["  "]),
        _row("sensor.typed_alias", "d", aliases=[default, "Zone two"]),
    ]
    states = _states({row.entity_id: RESTORED for row in rows})

    report = CLEANUP.find_orphans(_registry(rows), states, ENTRY_ID, DOMAIN, set())

    assert [item.entity_id for item in report.orphans] == [
        "sensor.default_alias",
        "sensor.null_alias",
        "sensor.blank_alias",
    ]
    assert [item.entity_id for item in report.kept_customized] == ["sensor.typed_alias"]


# Intent: the default options and categories of a live registry row are no customisation; a category, a user unit or
# display precision, a device class override or an Assist exposure the user switched on are.
# Why: since Home Assistant 2026.10 every row of the owner's system carries `options` with the integration's suggested
# display precision and `conversation.should_expose: False`; counting those would keep every row, while user choices in
# the same place (backlog C7) are user data that a cleanup must not delete.
def test_user_choices_in_options_and_categories_are_customisations_but_defaults_are_not() -> None:
    default_options = {"sensor": {"suggested_display_precision": 0}, "conversation": {"should_expose": False}}
    rows = [
        _row("sensor.default", "a", options=default_options, categories={}, device_class=None),
        _row("sensor.categorised", "b", options=default_options, categories={"scope": "cat1"}, device_class=None),
        _row("sensor.exposed", "c", options={"conversation": {"should_expose": True}}, categories={}),
        _row("sensor.precision", "d", options={"sensor": {"display_precision": 2}}, categories={}),
        _row("sensor.unit", "e", options={"sensor": {"unit_of_measurement": "kWh"}}, categories={}),
        _row("sensor.class", "f", options=default_options, categories={}, device_class="energy"),
    ]
    states = _states({row.entity_id: RESTORED for row in rows})

    report = CLEANUP.find_orphans(_registry(rows), states, ENTRY_ID, DOMAIN, set())

    assert [item.entity_id for item in report.orphans] == ["sensor.default"]
    assert {item.entity_id for item in report.kept_customized} == {
        "sensor.categorised",
        "sensor.exposed",
        "sensor.precision",
        "sensor.unit",
        "sensor.class",
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

    report = CLEANUP.find_orphans(_registry(rows), _states({"sensor.helper": ("unknown", {})}), ENTRY_ID, DOMAIN, set())

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
    device_registry = MagicMock()
    # The caller hands in the device entries of this config entry (Home Assistant's `async_entries_for_config_entry`),
    # because the registry's `devices` mapping and `DeviceEntry.config_entries` are deprecated or differ per version.
    # These stand-ins have no `config_entries` attribute on purpose.
    devices = [
        SimpleNamespace(id="dev-zone2", identifiers={(DOMAIN, "z2")}),
        SimpleNamespace(id="dev-zone1", identifiers={(DOMAIN, "z1")}),
        SimpleNamespace(id="dev-other-domain", identifiers={("other", "x")}),
    ]

    result = CLEANUP.remove_orphans(
        registry, device_registry, DOMAIN, ["sensor.zone_2_a", "sensor.zone_2_b", "sensor.zone_1_orphan"], devices
    )

    assert (result.entities, result.devices) == (3, 1)
    device_registry.async_remove_device.assert_called_once_with("dev-zone2")


# Intent: an empty device that the user renamed or labelled is kept when its entities are removed.
# Why: the audit of release 1.12.0 - the changelog promises to keep what the user customised, and a device name or
#      label is user data just like an entity name.
def test_remove_orphans_keeps_a_device_the_user_customised() -> None:
    rows = [_row("sensor.a", "a", device_id="dev-renamed"), _row("sensor.b", "b", device_id="dev-labelled")]
    registry = _registry(rows)
    device_registry = MagicMock()
    devices = [
        SimpleNamespace(id="dev-renamed", identifiers={(DOMAIN, "z2")}, name_by_user="Guest room", labels=set()),
        SimpleNamespace(id="dev-labelled", identifiers={(DOMAIN, "z3")}, name_by_user=None, labels={"keep"}),
    ]

    result = CLEANUP.remove_orphans(registry, device_registry, DOMAIN, ["sensor.a", "sensor.b"], devices)

    assert (result.entities, result.devices) == (2, 0)
    device_registry.async_remove_device.assert_not_called()


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


# Intent: build a coordinator stand-in with the attributes the report needs.
# Why: the stale-entity report is only trustworthy while ebusd is connected and entities have been generated.
def _coordinator(
    connected: bool = True, entities: int = 1, discovery_ready: bool = True, runtime_defined: set[str] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        ebus=SimpleNamespace(is_connected=connected),
        discovery_ready=discovery_ready,
        runtime_defined_key_folds=lambda: set(runtime_defined or ()),
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
def _flow(
    rows: list[SimpleNamespace],
    connected: bool = True,
    states: dict[str, tuple[str, dict[str, object]]] | None = None,
    entities: list[SimpleNamespace] | None = None,
) -> tuple[Any, MagicMock, MagicMock]:
    registry = _registry(rows)
    devices = MagicMock()
    sys.modules["homeassistant.helpers.entity_registry"].async_get = MagicMock(return_value=registry)
    sys.modules["homeassistant.helpers.device_registry"].async_get = MagicMock(return_value=devices)
    sys.modules["homeassistant.helpers.device_registry"].async_entries_for_config_entry = MagicMock(return_value=[])
    flow = REPAIRS.StaleEntitiesRepairFlow(ENTRY_ID)
    coordinator = _coordinator(connected=connected)
    if entities is not None:
        coordinator.entities = entities
    flow.hass = SimpleNamespace(
        data={DOMAIN: {ENTRY_ID: coordinator}},
        states=_states(states if states is not None else {row.entity_id: RESTORED for row in rows}),
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


# Intent: confirming also removes the device left empty, found through Home Assistant's per-entry device lookup.
# Why: the lookup works on every Home Assistant version, while iterating the registry returns ids on older ones and
#      reading `config_entries` is deprecated since 2026.10; a Zone 2 device without entities must not stay behind.
async def test_fix_flow_removes_the_device_that_is_left_empty() -> None:
    flow, _, devices = _flow([_row("sensor.gone", "ebusd_hmu_gone", device_id="dev-zone2")])
    lookup = sys.modules["homeassistant.helpers.device_registry"].async_entries_for_config_entry
    lookup.return_value = [SimpleNamespace(id="dev-zone2", identifiers={(DOMAIN, "z2")})]

    await flow.async_step_confirm({})

    lookup.assert_called_once_with(devices, ENTRY_ID)
    devices.async_remove_device.assert_called_once_with("dev-zone2")


# Intent: the flow aborts instead of removing anything when ebusd is not connected.
# Why: without discovery the report is unreliable, so the repair must not touch the registry.
async def test_fix_flow_aborts_without_a_connection() -> None:
    flow, registry, _ = _flow([_row("sensor.gone", "ebusd_hmu_gone")], connected=False)

    result = await flow.async_step_confirm({})

    assert result == {"type": "abort"}
    registry.async_remove.assert_not_called()


UNKNOWN = ("unknown", {"friendly_name": "Storage Temp (Top)"})


# Intent: build a generated entity description stand-in with the fields the dormant check reads.
# Why: the discovery's own "off by default" verdict and the live `unknown` state decide whether a row is dormant.
def _description(
    unique_id: str, enabled_by_default: bool = False, circuit: str = "", name: str = ""
) -> SimpleNamespace:
    return SimpleNamespace(unique_id=unique_id, enabled_by_default=enabled_by_default, circuit=circuit, name=name)


# Intent: an enabled row is dormant when its live entity has no value and the discovery would not switch it on.
# Why: older releases created sensors for hardware that is not there (storage temperatures) and for service registers
#      as enabled; Home Assistant never changes an enabled row, so the owner still saw 40 entities that stay unknown.
def test_find_dormant_lists_enabled_rows_without_data_that_discovery_switches_off() -> None:
    rows = [
        _row("sensor.storage_top", "ebusd_ctlv2_hwcstoragetemptop"),
        _row("sensor.storage_bottom", "ebusd_ctlv2_HwcStorageTempBottom"),
        _row("sensor.switched_on_by_user", "ebusd_hmu_compressorhc_runtime"),
        _row("sensor.default_on", "ebusd_hmu_flowtemp"),
        _row("date.holiday", "z1holidaystartperiod"),
        _row("sensor.already_off", "ebusd_ctlv2_systemflowtemp", disabled_by="integration"),
        _row("sensor.renamed", "ebusd_vwz_testhwctemp", name="My test sensor"),
        _row("sensor.restored", "ebusd_ctlv2_hcstoragetemptop"),
    ]
    states = _states(
        {
            "sensor.storage_top": UNKNOWN,
            "sensor.storage_bottom": UNKNOWN,
            "sensor.switched_on_by_user": ("12.0", {}),
            "sensor.default_on": UNKNOWN,
            "date.holiday": UNKNOWN,
            "sensor.renamed": UNKNOWN,
            "sensor.restored": RESTORED,
        }
    )
    switched_off = {
        f"{ENTRY_ID}_{name}".casefold()
        for name in (
            "ebusd_ctlv2_hwcstoragetemptop",
            "ebusd_ctlv2_hwcstoragetempbottom",
            "ebusd_hmu_compressorhc_runtime",
            "ebusd_ctlv2_systemflowtemp",
            "ebusd_vwz_testhwctemp",
            "ebusd_ctlv2_hcstoragetemptop",
        )
    }

    dormant, kept = CLEANUP.find_dormant(_registry(rows), states, ENTRY_ID, DOMAIN, switched_off)

    assert [item.entity_id for item in dormant] == ["sensor.storage_top", "sensor.storage_bottom"]
    assert [item.entity_id for item in kept] == ["sensor.renamed"]


# Intent: the report lists dormant entities next to the orphans, and leaves out entities that have a value or a default.
# Why: the repair and the options purge show one preview; a row with a value or an enabled default is live.
def test_stale_report_lists_dormant_entities_next_to_orphans() -> None:
    rows = [
        _row("sensor.gone", "ebusd_hmu_gone"),
        _row("sensor.storage_top", "ebusd_ctlv2_hwcstoragetemptop"),
        _row("sensor.flow", "ebusd_hmu_flowtemp"),
        _row("sensor.has_value", "ebusd_hmu_hasvalue"),  # switched on by the user and now reporting
        _row("sensor.renamed", "ebusd_vwz_testhwctemp", name="Mine"),
    ]
    states = _states(
        {
            "sensor.gone": RESTORED,
            "sensor.storage_top": UNKNOWN,
            "sensor.flow": UNKNOWN,
            "sensor.has_value": ("12.0", {}),
            "sensor.renamed": UNKNOWN,
        }
    )
    coordinator = _coordinator()
    coordinator.entities = [
        _description("ebusd_ctlv2_hwcstoragetemptop"),
        _description("ebusd_hmu_flowtemp", enabled_by_default=True),
        _description("ebusd_hmu_hasvalue"),
        _description("ebusd_vwz_testhwctemp"),
    ]

    report = CLEANUP.stale_report(_registry(rows), states, ENTRY_ID, DOMAIN, coordinator)

    assert [item.entity_id for item in report.orphans] == ["sensor.gone"]
    assert [item.entity_id for item in report.dormant] == ["sensor.storage_top"]
    assert [item.entity_id for item in report.kept_customized] == ["sensor.renamed"]


# Intent: switching the dormant rows off marks them as disabled by the integration and counts them.
# Why: only an integration-disabled row is switched on again by the analysis when its register returns a value.
def test_disable_dormant_switches_rows_off_by_the_integration() -> None:
    registry = MagicMock()
    rows = {"sensor.a": _row("sensor.a", "a"), "sensor.b": _row("sensor.b", "b")}
    registry.async_get.side_effect = rows.get

    count = CLEANUP.disable_dormant(registry, ["sensor.a", "sensor.b"], "integration")

    assert count == 2
    assert [(call.args, call.kwargs) for call in registry.async_update_entity.call_args_list] == [
        (("sensor.a",), {"disabled_by": "integration"}),
        (("sensor.b",), {"disabled_by": "integration"}),
    ]


# Intent: a row that changed between the report and the submit is left alone when the rows are switched off.
# Why: the user may rename, switch off or delete an entity while the confirmation is open; that choice wins.
def test_disable_dormant_skips_rows_that_changed_since_the_report() -> None:
    registry = MagicMock()
    rows = {
        "sensor.kept": _row("sensor.kept", "kept"),
        "sensor.renamed": _row("sensor.renamed", "renamed", name="Mine"),
        "sensor.user_off": _row("sensor.user_off", "user_off", disabled_by="user"),
    }
    registry.async_get.side_effect = rows.get

    count = CLEANUP.disable_dormant(
        registry, ["sensor.kept", "sensor.renamed", "sensor.user_off", "sensor.gone"], "integration"
    )

    assert count == 1
    registry.async_update_entity.assert_called_once_with("sensor.kept", disabled_by="integration")


# Intent: an entity of a register the integration defined itself is never offered as dormant, even without data.
# Why: a user may have switched on a passive default-off sensor such as a compressor counter on purpose; it stays
# `unknown` until the gateway sends the frame, so a one-click Submit would undo that choice (audit P1).
def test_stale_report_never_lists_runtime_defined_registers_as_dormant() -> None:
    rows = [
        _row("sensor.passive_counter", "ebusd_hmu_compressorhc"),
        _row("sensor.storage_top", "ebusd_ctlv2_hwcstoragetemptop"),
    ]
    states = _states({"sensor.passive_counter": UNKNOWN, "sensor.storage_top": UNKNOWN})
    coordinator = _coordinator(runtime_defined={"hmu.compressorhc"})
    coordinator.entities = [
        _description("ebusd_hmu_compressorhc", circuit="hmu", name="CompressorHc"),
        _description("ebusd_ctlv2_hwcstoragetemptop", circuit="ctlv2", name="HwcStorageTempTop"),
    ]

    report = CLEANUP.stale_report(_registry(rows), states, ENTRY_ID, DOMAIN, coordinator)

    assert [item.entity_id for item in report.dormant] == ["sensor.storage_top"]


# Intent: the report is refused until the live discovery has finished.
# Why: right after a start the entities come from the cache; a cached `unknown` state is not a register without data.
def test_stale_report_is_refused_before_the_live_discovery_finished() -> None:
    registry = _registry([_row("sensor.storage_top", "ebusd_ctlv2_hwcstoragetemptop")])
    states = _states({"sensor.storage_top": UNKNOWN})

    assert CLEANUP.stale_report(registry, states, ENTRY_ID, DOMAIN, _coordinator(discovery_ready=False)) is None


DORMANT_ROWS = [_row("sensor.gone", "ebusd_hmu_gone"), _row("sensor.storage_top", "ebusd_ctlv2_hwcstoragetemptop")]
DORMANT_STATES = {"sensor.gone": RESTORED, "sensor.storage_top": UNKNOWN}
DORMANT_ENTITIES = [_description("ebusd_ctlv2_hwcstoragetemptop"), _description("ebusd_hmu_generated0", True)]


# Intent: the first step of the fix flow shows both lists and changes nothing.
# Why: the user decides after seeing which entities go and which are switched off.
async def test_fix_flow_preview_lists_dormant_entities_too() -> None:
    flow, registry, _ = _flow(DORMANT_ROWS, states=DORMANT_STATES, entities=DORMANT_ENTITIES)

    result = await flow.async_step_init()

    assert result == {"type": "form"}
    placeholders = flow.async_show_form.call_args.kwargs["description_placeholders"]
    assert placeholders["count"] == "1" and "sensor.gone" in placeholders["entities"]
    assert placeholders["dormant_count"] == "1" and "sensor.storage_top" in placeholders["dormant"]
    registry.async_remove.assert_not_called()
    registry.async_update_entity.assert_not_called()


# Intent: confirming removes the orphans and switches the dormant entities off, then finishes the flow.
# Why: one confirmation covers the whole preview; the dormant rows are switched off, never deleted.
async def test_fix_flow_confirm_switches_dormant_off_and_removes_orphans() -> None:
    flow, registry, _ = _flow(DORMANT_ROWS, states=DORMANT_STATES, entities=DORMANT_ENTITIES)

    result = await flow.async_step_confirm({})

    assert result == {"type": "create_entry"}
    assert [call.args[0] for call in registry.async_remove.call_args_list] == ["sensor.gone"]
    registry.async_update_entity.assert_called_once_with("sensor.storage_top", disabled_by="integration")


# Intent: with dormant entities only, the flow still shows the preview and removes no registry row.
# Why: the repair must not close itself while something is left to switch off, and must not delete live rows.
async def test_fix_flow_with_only_dormant_entities_shows_the_form_and_removes_nothing() -> None:
    rows = [DORMANT_ROWS[1]]
    flow, registry, _ = _flow(rows, states={"sensor.storage_top": UNKNOWN}, entities=DORMANT_ENTITIES)

    shown = await flow.async_step_confirm()
    done = await flow.async_step_confirm({})

    assert shown == {"type": "form"} and done == {"type": "create_entry"}
    registry.async_remove.assert_not_called()
    registry.async_update_entity.assert_called_once_with("sensor.storage_top", disabled_by="integration")


# Intent: the flow finishes at once when nothing is stale and nothing is dormant.
# Why: the issue is cleared as soon as it has nothing left to show.
async def test_fix_flow_finishes_when_nothing_is_left() -> None:
    flow, registry, _ = _flow([_row("sensor.fine", "ebusd_hmu_generated0")], states={"sensor.fine": ("5", {})})

    result = await flow.async_step_confirm()

    assert result == {"type": "create_entry"}
    registry.async_remove.assert_not_called()
    registry.async_update_entity.assert_not_called()
