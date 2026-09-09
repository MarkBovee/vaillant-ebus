"""Constants for Vaillant eBUS."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.const import Platform

DOMAIN = "vaillant_ebus"


def _read_manifest_version() -> str:
    """Read version from manifest so dump metadata cannot drift."""
    try:
        manifest = json.loads(Path(__file__).with_name("manifest.json").read_text())
        return str(manifest["version"])
    except (OSError, KeyError, TypeError, ValueError):
        return "unknown"


INTEGRATION_VERSION = _read_manifest_version()
CONF_EBUSD_HOST = "ebusd_host"
CONF_EBUSD_PORT = "ebusd_port"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_AWAY_DURATION = "away_duration"
CONF_QUICK_VETO_DURATION = "quick_veto_duration"
CONF_QUICK_VETO_TEMP = "quick_veto_temp"
CONF_COOLING_DURATION = "cooling_duration"
DEFAULT_EBUSD_HOST = ""
DEFAULT_EBUSD_PORT = 8888
DEFAULT_EBUSD_POLL_INTERVAL = 30
DEFAULT_AWAY_DURATION = 7
DEFAULT_QUICK_VETO_DURATION = 3
DEFAULT_QUICK_VETO_TEMP = 21.0
DEFAULT_COOLING_DURATION = 3
DISCOVERY_PORT = 8888
DISCOVERY_TIMEOUT = 3
DISCOVERY_CANDIDATES = ["core-ebusd", "localhost", "127.0.0.1", "homeassistant.local"]
SENSITIVE_FIELDS: set[str] = {
    "serial",
    "keycode",
    "installer",
    "bc",
    "code",
    "password",
    "secret",
    "token",
    "pin",
}

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.CLIMATE,
    Platform.WATER_HEATER,
    Platform.CALENDAR,
    Platform.DATETIME,
]

EBUSD_TO_HA_HVAC = {
    "off": "off",
    "auto": "auto",
    "day": "heat",
    "night": "cool",
    "heat": "heat",
    "cool": "cool",
}

HA_TO_EBUSD_HVAC = {
    "off": "off",
    "auto": "auto",
    "heat": "day",
}
