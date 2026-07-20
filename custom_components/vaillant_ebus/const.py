"""Constants for Vaillant eBUS."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "vaillant_ebus"
CONF_EBUSD_HOST = "ebusd_host"
CONF_EBUSD_PORT = "ebusd_port"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_EBUSD_HOST = "192.168.1.100"
DEFAULT_EBUSD_PORT = 8888
DEFAULT_EBUSD_POLL_INTERVAL = 30
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
