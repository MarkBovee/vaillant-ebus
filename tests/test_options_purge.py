"""Tests for the options-flow purge step: preview, confirmation, removal and switching off."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from tests import _component_loader
from tests.test_cleanup import (
    DOMAIN,
    DORMANT_ENTITIES,
    DORMANT_ROWS,
    DORMANT_STATES,
    ENTRY_ID,
    UNKNOWN,
    _coordinator,
    _registry,
    _row,
    _states,
)


# Intent: load config_flow.py with the Home Assistant pieces the unit-test loader does not stub.
# Why: the options flow had no test at all; the stubs are registered only where missing and the base classes restored.
def _load_config_flow() -> ModuleType:
    for name in ("aiohttp", "homeassistant.data_entry_flow", "homeassistant.helpers.config_validation"):
        sys.modules.setdefault(name, MagicMock())
    config_entries = sys.modules["homeassistant.config_entries"]
    saved = (config_entries.OptionsFlow, config_entries.ConfigFlow)
    config_entries.OptionsFlow = object
    config_entries.ConfigFlow = type("ConfigFlow", (), {"__init_subclass__": classmethod(lambda cls, **kw: None)})
    sys.modules["homeassistant.helpers"].config_validation = sys.modules["homeassistant.helpers.config_validation"]
    real_const = _component_loader._exec_source(
        "vaillant_ebus.const_real", _component_loader.COMPONENT_PATH / "const.py"
    )
    const_stub = sys.modules["vaillant_ebus.const"]
    for key, value in vars(real_const).items():
        if key.isupper() and not hasattr(const_stub, key):
            setattr(const_stub, key, value)
    try:
        return _component_loader._exec_source(
            "vaillant_ebus.config_flow_real", _component_loader.COMPONENT_PATH / "config_flow.py"
        )
    finally:
        config_entries.OptionsFlow, config_entries.ConfigFlow = saved


CONFIG_FLOW = _load_config_flow()


# Intent: wire an options flow with the registries and the coordinator it reads, returning the flow and its registry.
# Why: the base class is a stub in the unit tests, so the form and abort calls are mocks.
def _options_flow(
    rows: list[SimpleNamespace],
    states: dict[str, tuple[str, dict[str, object]]],
    entities: list[SimpleNamespace] | None = None,
    connected: bool = True,
) -> tuple[Any, MagicMock]:
    registry = _registry(rows)
    devices = MagicMock()
    devices.devices = []
    sys.modules["homeassistant.helpers.entity_registry"].async_get = MagicMock(return_value=registry)
    sys.modules["homeassistant.helpers.device_registry"].async_get = MagicMock(return_value=devices)
    flow = CONFIG_FLOW.VaillantOptionsFlow(SimpleNamespace(entry_id=ENTRY_ID))
    coordinator = _coordinator(connected=connected)
    if entities is not None:
        coordinator.entities = entities
    flow.hass = SimpleNamespace(data={DOMAIN: {ENTRY_ID: coordinator}}, states=_states(states))
    flow.async_show_form = MagicMock(return_value={"type": "form"})
    flow.async_abort = MagicMock(side_effect=lambda reason: {"type": "abort", "reason": reason})
    return flow, registry


# Intent: the purge step shows the count and names of both lists and changes nothing.
# Why: the user confirms what is true now; showing the preview must not touch the registry.
async def test_purge_step_shows_the_preview_with_both_lists() -> None:
    flow, registry = _options_flow(DORMANT_ROWS, DORMANT_STATES, DORMANT_ENTITIES)

    result = await flow.async_step_purge_entities()

    assert result == {"type": "form"}
    placeholders = flow.async_show_form.call_args.kwargs["description_placeholders"]
    assert placeholders["count"] == "1" and "sensor.gone" in placeholders["entities"]
    assert placeholders["dormant_count"] == "1" and "sensor.storage_top" in placeholders["dormant"]
    registry.async_remove.assert_not_called()
    registry.async_update_entity.assert_not_called()


# Intent: confirming removes the orphans, switches the dormant entities off and ends with the purged message.
# Why: one confirmation covers the whole preview, and the dormant rows are switched off, never deleted.
async def test_purge_step_confirm_removes_orphans_and_switches_dormant_off() -> None:
    flow, registry = _options_flow(DORMANT_ROWS, DORMANT_STATES, DORMANT_ENTITIES)

    result = await flow.async_step_purge_entities({"confirm": True})

    assert result == {"type": "abort", "reason": "entities_purged"}
    assert [call.args[0] for call in registry.async_remove.call_args_list] == ["sensor.gone"]
    registry.async_update_entity.assert_called_once_with("sensor.storage_top", disabled_by="integration")


# Intent: submitting without the confirmation changes nothing.
# Why: the checkbox is the confirmation; an unticked submit must not remove or switch off anything.
async def test_purge_step_without_confirmation_changes_nothing() -> None:
    flow, registry = _options_flow(DORMANT_ROWS, DORMANT_STATES, DORMANT_ENTITIES)

    result = await flow.async_step_purge_entities({"confirm": False})

    assert result == {"type": "abort", "reason": "purge_not_confirmed"}
    registry.async_remove.assert_not_called()
    registry.async_update_entity.assert_not_called()


# Intent: the step aborts with "nothing to purge" when there are no orphans and no dormant entities.
# Why: an empty confirmation form would ask the user to confirm nothing.
async def test_purge_step_aborts_when_there_is_nothing_to_do() -> None:
    flow, registry = _options_flow([_row("sensor.fine", "ebusd_hmu_generated0")], {"sensor.fine": ("5", {})})

    result = await flow.async_step_purge_entities()

    assert result == {"type": "abort", "reason": "nothing_to_purge"}
    registry.async_remove.assert_not_called()


# Intent: the step refuses to run while ebusd is not connected.
# Why: before discovery every row looks stale; acting then would delete live entities.
async def test_purge_step_is_refused_without_a_connection() -> None:
    flow, registry = _options_flow(DORMANT_ROWS, DORMANT_STATES, DORMANT_ENTITIES, connected=False)

    result = await flow.async_step_purge_entities({"confirm": True})

    assert result == {"type": "abort", "reason": "purge_unavailable"}
    registry.async_remove.assert_not_called()
    registry.async_update_entity.assert_not_called()


# Intent: a dormant-only report still offers the step and switches off without removing a row.
# Why: after the orphans are gone the 40 legacy rows are what is left, and they must not be reported as stale.
async def test_purge_step_with_only_dormant_entities_removes_no_row() -> None:
    flow, registry = _options_flow([DORMANT_ROWS[1]], {"sensor.storage_top": UNKNOWN}, DORMANT_ENTITIES)

    shown = await flow.async_step_purge_entities()
    done = await flow.async_step_purge_entities({"confirm": True})

    assert shown == {"type": "form"} and done == {"type": "abort", "reason": "entities_purged"}
    registry.async_remove.assert_not_called()
    registry.async_update_entity.assert_called_once_with("sensor.storage_top", disabled_by="integration")
