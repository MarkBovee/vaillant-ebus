"""Repairs for Vaillant eBUS."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ISSUE_EBUSD_UNREACHABLE = "ebusd_unreachable"


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
