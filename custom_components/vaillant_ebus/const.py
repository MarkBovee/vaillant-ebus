"""Constants for Vaillant eBUS."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "vaillant_ebus"
CONF_EBUSD_HOST = "ebusd_host"
CONF_EBUSD_PORT = "ebusd_port"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_EBUSD_HOST = ""
DEFAULT_EBUSD_PORT = 8888
DEFAULT_EBUSD_POLL_INTERVAL = 60
DISCOVERY_PORT = 8888
DISCOVERY_TIMEOUT = 3
DISCOVERY_CANDIDATES = ["core-ebusd", "localhost", "127.0.0.1", "homeassistant.local"]
PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.CLIMATE,
    Platform.WATER_HEATER,
    Platform.CALENDAR,
    Platform.DATE,
]
