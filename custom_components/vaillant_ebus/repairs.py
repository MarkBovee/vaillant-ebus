"""Repairs for Vaillant eBUS."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers import issue_registry as ir

from . import cleanup
from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)

ISSUE_EBUSD_UNREACHABLE = "ebusd_unreachable"
ISSUE_DETECTION_INCOMPLETE = "detection_incomplete"
ISSUE_STALE_ENTITIES = "stale_entities"


# Intent: provide the fix flow Home Assistant requires of every repairs platform module.
# Why: without `async_create_fix_flow` HA logs "Invalid repairs platform" and the fixable issue cannot be resolved.
async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Return the flow for one issue: a preview and removal for stale entities, a plain confirm otherwise.

    The ebusd repair stays confirm-only; the coordinator re-checks ebusd and recreates the issue if it is still down.
    """
    if issue_id == ISSUE_STALE_ENTITIES and data and data.get("entry_id"):
        return StaleEntitiesRepairFlow(str(data["entry_id"]))
    return ConfirmRepairFlow()


# Intent: show the registry entities that nothing provides any more and remove them after one confirmation.
# Why: the owner's 86 restored entities stayed invisible; the list is recomputed at each step so the user confirms what
# is true now, and nothing is removed while ebusd is disconnected or before the user submits.
class StaleEntitiesRepairFlow(RepairsFlow):
    """Preview and remove the stale Vaillant eBUS registry entities."""

    # Intent: remember which config entry the issue belongs to.
    # Why: the flow recomputes the stale entities of exactly that entry at each step.
    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    # Intent: start at the confirmation step, which shows the preview.
    # Why: the repair has one decision only, so there is no separate first screen.
    async def async_step_init(self, user_input: dict[str, str] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    # Intent: show the preview; on submit remove the listed orphans and finish, which clears the issue.
    # Why: nothing may be removed before the user submits, and the list must be true at that moment.
    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> FlowResult:
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        registry = entity_registry.async_get(self.hass)
        report = cleanup.stale_report(registry, self.hass.states, self._entry_id, DOMAIN, coordinator)
        if report is None:
            return self.async_abort(reason="cleanup_unavailable")
        if not report.orphans:
            return self.async_create_entry(data={})
        if user_input is not None:
            result = cleanup.remove_orphans(
                registry,
                device_registry.async_get(self.hass),
                self._entry_id,
                DOMAIN,
                [item.entity_id for item in report.orphans],
            )
            _LOGGER.info(
                "Removed %d stale Vaillant eBUS entities and %d empty devices (%d customised entities kept)",
                result.entities,
                result.devices,
                len(report.kept_customized),
            )
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "count": str(len(report.orphans)),
                "entities": cleanup.preview_text(report.orphans),
                "kept": str(len(report.kept_customized)),
            },
        )


async def async_create_ebusd_unreachable(hass: HomeAssistant) -> None:
    """Create or update a repair issue for ebusd being unreachable."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_EBUSD_UNREACHABLE,
        is_fixable=True,
        severity=ir.IssueSeverity.CRITICAL,
        translation_key=ISSUE_EBUSD_UNREACHABLE,
        learn_more_url="https://github.com/MarkBovee/vaillant-ebus#troubleshooting",
    )


async def async_dismiss_ebusd_unreachable(hass: HomeAssistant) -> None:
    """Dismiss the ebusd unreachable repair issue."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_EBUSD_UNREACHABLE)


async def async_dismiss_detection_incomplete(hass: HomeAssistant) -> None:
    """Remove stale detection issues after a successful discovery."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_DETECTION_INCOMPLETE)


# Intent: create or update the repair issue that lists the stale entities.
# Why: the issue carries the entry id for the fix flow and the count and names for the text.
async def async_create_stale_entities(hass: HomeAssistant, entry_id: str, count: int, preview: str, kept: int) -> None:
    """Create or update the repair issue that lists stale entities for removal."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_STALE_ENTITIES,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_STALE_ENTITIES,
        translation_placeholders={"count": str(count), "entities": preview, "kept": str(kept)},
        data={"entry_id": entry_id},
    )


# Intent: remove the stale entities repair issue.
# Why: once nothing is stale the repair must not stay open.
async def async_dismiss_stale_entities(hass: HomeAssistant) -> None:
    """Remove the stale entities repair issue once nothing is stale."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_STALE_ENTITIES)
