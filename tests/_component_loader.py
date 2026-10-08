"""Shared, idempotent loader for the vaillant_ebus modules executed by the test suite.

Many test files need the same backend and component modules and the same
Home Assistant stub tree. Each file used to execute these modules itself and
overwrite the shared sys.modules entries, so a subset run could bind a test
to a module object another file had replaced. This loader executes every
module exactly once per process; all test files read the same sys.modules
entries and the same stub classes.
"""

from __future__ import annotations

import enum
import importlib.machinery
import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"
BACKEND_PATH = COMPONENT_PATH / "backend"

# Backend modules in dependency order: each entry may import only the modules above it.
BACKEND_MODULES = (
    "models",
    "mapping",
    "grab_parser",
    "ebus_service",
    "entity_factory",
    "discovery_service",
    "analysis_service",
    "dump_analysis",
)

_LOADED = False


class HVACMode(enum.StrEnum):
    """Climate HVAC modes as exposed by the stubbed Home Assistant climate platform."""

    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    AUTO = "auto"


class HVACAction(enum.StrEnum):
    """Climate HVAC actions as exposed by the stubbed Home Assistant climate platform."""

    OFF = "off"
    HEATING = "heating"
    COOLING = "cooling"
    IDLE = "idle"


class ClimateEntityFeature(enum.IntFlag):
    """Climate entity feature flags as exposed by the stubbed Home Assistant climate platform."""

    TARGET_TEMPERATURE = 1
    TARGET_TEMPERATURE_RANGE = 2
    PRESET_MODE = 4
    TURN_ON = 8
    TURN_OFF = 16


class _WaterHeaterEntityFeature(enum.IntFlag):
    """Water heater feature flags used by the stubbed water_heater platform."""

    TARGET_TEMPERATURE = 1
    OPERATION_MODE = 2
    AWAY_MODE = 4
    ON_OFF = 8


class _UnitOfTemperature:
    """Temperature unit constants used by the stubbed homeassistant.const module."""

    CELSIUS = "°C"


class MockHomeAssistantError(Exception):
    """Home Assistant service exception shared by every stubbed platform and the integration init."""


class CalendarEvent:
    """Minimal calendar event record matching the fields the calendar platform reads."""

    # Intent: store the event fields the calendar platform reads.
    # Why: the calendar tests compare these fields directly against parsed timer slots.
    def __init__(self, start, end, summary, description=None) -> None:
        self.start = start
        self.end = end
        self.summary = summary
        self.description = description


class _MockDataUpdateCoordinator:
    """Stand-in for Home Assistant's DataUpdateCoordinator with the pushed-update contract."""

    # Intent: initialize the published snapshot used by CoordinatorEntity lookups.
    # Why: tests for pushed updates must observe the same data contract as Home Assistant.
    def __init__(self, hass, logger, **kwargs) -> None:  # noqa: ARG002
        self.hass = hass
        self.name = kwargs.get("name", "")
        self.update_interval = kwargs.get("update_interval")
        self.data = None
        self.last_update_success = True
        self.listeners: list = []

    # Intent: notify listeners after the coordinator publishes new data.
    # Why: entities subscribe through this hook, so tests can observe state changes without Home Assistant.
    def async_update_listeners(self) -> None:
        pass

    # Intent: publish pushed data before notifying coordinator listeners.
    # Why: delayed discovery tests must observe cleared values in the same order as Home Assistant.
    def async_set_updated_data(self, data: dict[str, object]) -> None:
        self.data = data
        self.async_update_listeners()

    # Intent: let the stub be subscripted the way Home Assistant generic classes are.
    # Why: entity code writes DataUpdateCoordinator[T] in annotations and base-class lists.
    def __class_getitem__(cls, item):
        return cls

    # Intent: let a stub class be called like a factory and return itself.
    # Why: kept from the original per-file stub so any callable use of the coordinator base behaves as before.
    def __call__(self, *args, **kwargs):
        return self


class _MockBaseEntity:
    """Base entity stub with the unique_id, name and is_on accessors platform entities read."""

    # Intent: expose the unique_id attribute through the Home Assistant property name.
    # Why: entity classes set _attr_unique_id and the platform reads the property.
    @property
    def unique_id(self) -> str | None:
        return getattr(self, "_attr_unique_id", None)

    # Intent: expose the name attribute through the Home Assistant property name.
    # Why: entity classes set _attr_name and the platform reads the property.
    @property
    def name(self) -> str | None:
        return getattr(self, "_attr_name", None)

    # Intent: default is_on to None for entities that do not override it.
    # Why: only switch-like entities define a real on/off state.
    @property
    def is_on(self):  # pragma: no cover - overridden by real entities
        return None


class _MockCoordinatorEntity(_MockBaseEntity):
    """Coordinator entity stub for the switch, water heater and binary sensor platforms."""

    # Intent: keep the coordinator the entity reads from.
    # Why: entities read the published snapshot through self.coordinator.
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    # Intent: accept the Home Assistant state write without a running hass instance.
    # Why: tests assert on entity state, not on the state machine.
    def async_write_ha_state(self) -> None:
        pass

    # Intent: accept the coordinator update hook without a running hass instance.
    # Why: pushed-update code calls this hook and must not fail in tests.
    def _handle_coordinator_update(self) -> None:
        pass

    # Intent: accept the async update hook as a no-op.
    # Why: Home Assistant calls this during entity refresh; the tests drive state directly.
    async def async_update(self) -> None:
        pass

    # Intent: let the stub be subscripted like Home Assistant's generic entity classes.
    # Why: entity code writes CoordinatorEntity[T] in base-class lists.
    def __class_getitem__(cls, item):
        return cls


class _MockClimateEntity:
    """Climate entity stub with the unique_id, hvac_modes and preset_modes accessors."""

    # Intent: expose the unique_id attribute through the Home Assistant property name.
    # Why: the climate entity sets _attr_unique_id and the platform reads the property.
    @property
    def unique_id(self) -> str | None:
        return getattr(self, "_attr_unique_id", None)

    # Intent: expose the supported HVAC modes through the Home Assistant property name.
    # Why: the climate tests assert on the modes the entity advertises.
    @property
    def hvac_modes(self) -> list:
        return getattr(self, "_attr_hvac_modes", [])

    # Intent: expose the supported presets through the Home Assistant property name.
    # Why: the climate tests assert on the presets the entity advertises.
    @property
    def preset_modes(self) -> list:
        return getattr(self, "_attr_preset_modes", [])


class _MockClimateCoordinatorEntity(_MockClimateEntity):
    """Coordinator entity stub for the climate platform, combining climate and coordinator behavior."""

    # Intent: keep the coordinator the climate entity reads from.
    # Why: the climate entity reads the published snapshot through self.coordinator.
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    # Intent: accept the Home Assistant state write without a running hass instance.
    # Why: tests assert on entity state, not on the state machine.
    def async_write_ha_state(self) -> None:
        pass

    # Intent: accept the coordinator update hook without a running hass instance.
    # Why: pushed-update code calls this hook and must not fail in tests.
    def _handle_coordinator_update(self) -> None:
        pass

    # Intent: accept the async update hook as a no-op.
    # Why: Home Assistant calls this during entity refresh; the tests drive state directly.
    async def async_update(self) -> None:
        pass

    # Intent: let the stub be subscripted like Home Assistant's generic entity classes.
    # Why: entity code writes CoordinatorEntity[T] in base-class lists.
    def __class_getitem__(cls, item):
        return cls


class _MockCalendarEntity:
    """Calendar entity stub with the unique_id, name and event accessors."""

    # Intent: expose the unique_id attribute through the Home Assistant property name.
    # Why: the calendar entity sets _attr_unique_id and the platform reads the property.
    @property
    def unique_id(self) -> str | None:
        return getattr(self, "_attr_unique_id", None)

    # Intent: expose the name attribute through the Home Assistant property name.
    # Why: the calendar entity sets _attr_name and the platform reads the property.
    @property
    def name(self) -> str | None:
        return getattr(self, "_attr_name", None)

    # Intent: default the current event to None for the base calendar entity.
    # Why: the calendar entity overrides this with the next scheduled event.
    @property
    def event(self):
        return None


class _MockCalendarCoordinatorEntity(_MockCalendarEntity):
    """Coordinator entity stub for the calendar platform."""

    # Intent: keep the coordinator the calendar entity reads from.
    # Why: the calendar entity reads the published snapshot through self.coordinator.
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    # Intent: accept the Home Assistant state write without a running hass instance.
    # Why: tests assert on entity state, not on the state machine.
    def async_write_ha_state(self) -> None:
        pass

    # Intent: accept the coordinator update hook without a running hass instance.
    # Why: pushed-update code calls this hook and must not fail in tests.
    def _handle_coordinator_update(self) -> None:
        pass

    # Intent: accept the async update hook as a no-op.
    # Why: Home Assistant calls this during entity refresh; the tests drive state directly.
    async def async_update(self) -> None:
        pass

    # Intent: let the stub be subscripted like Home Assistant's generic entity classes.
    # Why: entity code writes CoordinatorEntity[T] in base-class lists.
    def __class_getitem__(cls, item):
        return cls


class _MockDateEntity:
    """Date entity stub: the write and update hooks only, without the base accessors other platforms use."""

    # Intent: accept the Home Assistant state write without a running hass instance.
    # Why: tests assert on entity state, not on the state machine.
    def async_write_ha_state(self) -> None:
        pass

    # Intent: accept the coordinator update hook without a running hass instance.
    # Why: pushed-update code calls this hook and must not fail in tests.
    def _handle_coordinator_update(self) -> None:
        pass

    # Intent: accept the async update hook as a no-op.
    # Why: Home Assistant calls this during entity refresh; the tests drive state directly.
    async def async_update(self) -> None:
        pass

    # Intent: let the stub be subscripted like Home Assistant's generic entity classes.
    # Why: entity code writes CoordinatorEntity[T] in base-class lists.
    def __class_getitem__(cls, item):
        return cls


class _MockDateCoordinatorEntity(_MockDateEntity):
    """Coordinator entity stub for the date platform."""

    # Intent: keep the coordinator the date entity reads from.
    # Why: the date entity reads the published snapshot through self.coordinator.
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator


class _MockSensorEntity:
    """Sensor entity stub used as the base of the sensor platform."""


class _MockRestoreEntity:
    """Restore entity stub used as the base of the sensor platform."""


class _MockSensorCoordinatorEntity:
    """Coordinator entity stub for the sensor platform."""

    # Intent: keep the coordinator the sensor entity reads from.
    # Why: the sensor entity reads the published snapshot through self.coordinator.
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    # Intent: let the stub be subscripted like Home Assistant's generic entity classes.
    # Why: entity code writes CoordinatorEntity[T] in base-class lists.
    def __class_getitem__(cls, item):
        return cls


# Intent: create a bare module object with no source file, for Home Assistant stub modules.
# Why: stubs must be importable by dotted name without executing any real code.
def _stub_module(name: str) -> ModuleType:
    return importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))


# Intent: execute a real source file once and register it in sys.modules under its dotted name.
# Why: the module must be registered before exec so that its own imports resolve to this single copy.
def _exec_source(dotted_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(dotted_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = module
    spec.loader.exec_module(module)
    return module


# Intent: build the root Home Assistant mock tree shared by every component test.
# Why: platform modules import names from this tree when they load, so it must exist first.
def _homeassistant_root() -> MagicMock:
    root = MagicMock()
    root.config_entries = MagicMock()
    root.core = MagicMock()
    root.helpers = MagicMock()
    root.helpers.device_registry = MagicMock()
    root.helpers.device_registry.DeviceInfo = dict
    root.helpers.event = MagicMock()
    root.helpers.update_coordinator = MagicMock()
    root.helpers.update_coordinator.DataUpdateCoordinator = _MockDataUpdateCoordinator
    root.helpers.entity_registry = MagicMock()
    root.helpers.entity_registry.RegistryEntryDisabler = MagicMock(INTEGRATION="integration")
    return root


# Intent: register the Home Assistant stub tree under the dotted names platform modules import.
# Why: `from homeassistant.x import y` resolves through sys.modules, so every level must be present.
def _register_homeassistant(root: MagicMock) -> None:
    sys.modules["homeassistant"] = root
    sys.modules["homeassistant.config_entries"] = root.config_entries
    sys.modules["homeassistant.core"] = root.core
    sys.modules["homeassistant.helpers"] = root.helpers
    sys.modules["homeassistant.helpers.device_registry"] = root.helpers.device_registry
    sys.modules["homeassistant.helpers.entity_registry"] = root.helpers.entity_registry
    sys.modules["homeassistant.helpers.event"] = root.helpers.event
    sys.modules["homeassistant.helpers.update_coordinator"] = root.helpers.update_coordinator
    sys.modules["homeassistant.const"] = MagicMock()
    root.config_entries.ConfigEntry = object
    root.core.HomeAssistant = object
    entity_platform = _stub_module("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform


# Intent: register the homeassistant.exceptions, homeassistant.components and repairs stubs.
# Why: the integration init and its repairs platform import from these packages at load time.
def _register_homeassistant_packages() -> None:
    exceptions_module = _stub_module("homeassistant.exceptions")
    exceptions_module.HomeAssistantError = MockHomeAssistantError
    sys.modules["homeassistant.exceptions"] = exceptions_module
    components_pkg = _stub_module("homeassistant.components")
    components_pkg.persistent_notification = MagicMock()
    sys.modules["homeassistant.components"] = components_pkg
    sys.modules["homeassistant.components.persistent_notification"] = components_pkg.persistent_notification
    repairs_pkg = _stub_module("homeassistant.components.repairs")
    repairs_pkg.ConfirmRepairFlow = object
    repairs_pkg.RepairsFlow = object
    sys.modules["homeassistant.components.repairs"] = repairs_pkg
    sys.modules.setdefault("voluptuous", MagicMock())


# Intent: publish the fake vaillant_ebus.const module with every constant the loaded modules read.
# Why: each module reads constants at load time, and a single shared object keeps all of them consistent.
def _register_const() -> None:
    const_module = _stub_module("vaillant_ebus.const")
    values = {
        "CONF_EBUSD_HOST": "ebusd_host",
        "CONF_EBUSD_PORT": "ebusd_port",
        "CONF_SCAN_INTERVAL": "scan_interval",
        "CONF_ENERGY_DIVISOR": "energy_counter_divisor",
        "CONF_COOLING_DURATION": "cooling_duration",
        "CONF_AWAY_DURATION": "away_duration",
        "DEFAULT_EBUSD_POLL_INTERVAL": 60,
        "DEFAULT_ENERGY_DIVISOR": 1.0,
        "DEFAULT_COOLING_DURATION": 3,
        "DEFAULT_AWAY_DURATION": 5,
        "DOMAIN": "vaillant_ebus",
        "EBUSD_TO_HA_HVAC": {
            "off": "off",
            "auto": "auto",
            "day": "heat",
            "night": "cool",
            "heat": "heat",
            "cool": "cool",
        },
        "HA_TO_EBUSD_HVAC": {"off": "off", "auto": "auto", "heat": "day"},
        "PLATFORMS": ("climate", "sensor", "select", "switch", "binary_sensor", "number", "button"),
        "SENSITIVE_FIELDS": frozenset(),
        "INTEGRATION_VERSION": "1.7.0",
    }
    for attr, value in values.items():
        setattr(const_module, attr, value)
    sys.modules["vaillant_ebus.const"] = const_module


# Intent: register the vaillant_ebus and vaillant_ebus.backend package stubs with their source paths.
# Why: relative and dotted imports inside the real sources resolve through these package objects.
def _register_packages() -> None:
    for name, path in (("vaillant_ebus", COMPONENT_PATH), ("vaillant_ebus.backend", BACKEND_PATH)):
        package = _stub_module(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package


# Intent: publish the repairs stub the coordinator imports for ebusd and detection repair issues.
# Why: the coordinator must not touch the real Home Assistant repairs platform in unit tests.
def _register_repairs() -> None:
    repairs_module = _stub_module("vaillant_ebus.repairs")
    repairs_module.async_dismiss_ebusd_unreachable = AsyncMock()
    repairs_module.async_create_ebusd_unreachable = AsyncMock()
    repairs_module.async_dismiss_detection_incomplete = AsyncMock()
    sys.modules["vaillant_ebus.repairs"] = repairs_module


# Intent: execute every backend module once, in dependency order.
# Why: backend modules are plain Python and shared by all backend and component tests.
def _load_backend() -> None:
    for name in BACKEND_MODULES:
        _exec_source(f"vaillant_ebus.backend.{name}", BACKEND_PATH / f"{name}.py")


# Intent: execute the coordinator once, after the backend, const, and repairs stubs exist.
# Why: the coordinator imports all three when it loads and is the base for every platform test.
def _load_coordinator() -> None:
    _exec_source("vaillant_ebus.coordinator", COMPONENT_PATH / "coordinator.py")


# Intent: execute the climate platform once with its climate-specific Home Assistant stubs.
# Why: EbusdClimate binds its base classes when the module executes, so the stubs must be set first.
def _load_climate(root: MagicMock) -> None:
    climate_pkg = _stub_module("homeassistant.components.climate")
    climate_pkg.ClimateEntity = _MockClimateEntity
    climate_pkg.ClimateEntityFeature = ClimateEntityFeature
    climate_const = _stub_module("homeassistant.components.climate.const")
    climate_const.PRESET_AWAY = "away"
    climate_const.PRESET_BOOST = "boost"
    climate_const.PRESET_NONE = "none"
    climate_const.HVACAction = HVACAction
    climate_const.HVACMode = HVACMode
    sys.modules["homeassistant.components.climate"] = climate_pkg
    sys.modules["homeassistant.components.climate.const"] = climate_const
    sys.modules["homeassistant.components"].climate = climate_pkg
    ha_const = sys.modules["homeassistant.const"]
    ha_const.ATTR_TEMPERATURE = "temperature"
    ha_const.UnitOfTemperature = _UnitOfTemperature
    root.helpers.update_coordinator.CoordinatorEntity = _MockClimateCoordinatorEntity
    _exec_source("vaillant_ebus.climate", COMPONENT_PATH / "climate.py")


# Intent: execute the switch, water heater and binary sensor platforms once with their shared stubs.
# Why: all three bind the same coordinator and base entity stubs, so they load as one group.
def _load_boost_platforms(root: MagicMock) -> None:
    switch_pkg = _stub_module("homeassistant.components.switch")
    switch_pkg.SwitchEntity = _MockBaseEntity
    binary_sensor_pkg = _stub_module("homeassistant.components.binary_sensor")
    binary_sensor_pkg.BinarySensorDeviceClass = enum.Enum("BinarySensorDeviceClass", "PROBLEM CONNECTIVITY HEAT")
    binary_sensor_pkg.BinarySensorEntity = _MockBaseEntity
    water_heater_pkg = _stub_module("homeassistant.components.water_heater")
    water_heater_pkg.WaterHeaterEntity = _MockBaseEntity
    water_heater_pkg.WaterHeaterEntityFeature = _WaterHeaterEntityFeature
    sys.modules["homeassistant.components.switch"] = switch_pkg
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor_pkg
    sys.modules["homeassistant.components.water_heater"] = water_heater_pkg
    sys.modules["homeassistant.const"].ATTR_TEMPERATURE = "temperature"
    sys.modules["homeassistant.const"].UnitOfTemperature = _UnitOfTemperature
    root.helpers.update_coordinator.CoordinatorEntity = _MockCoordinatorEntity
    for name in ("switch", "water_heater", "binary_sensor"):
        _exec_source(f"vaillant_ebus.{name}", COMPONENT_PATH / f"{name}.py")


# Intent: execute the calendar platform once with its calendar and util stubs.
# Why: the calendar tests pin timer-slot parsing against a fixed clock supplied by the util stub.
def _load_calendar(root: MagicMock) -> None:
    calendar_pkg = _stub_module("homeassistant.components.calendar")
    calendar_pkg.CalendarEntity = _MockCalendarEntity
    calendar_pkg.CalendarEvent = CalendarEvent
    sys.modules["homeassistant.components.calendar"] = calendar_pkg
    ha_util = _stub_module("homeassistant.util")
    ha_util.dt = MagicMock()
    ha_util.dt.as_local = _local_identity
    ha_util.dt.now = _fixed_now
    sys.modules["homeassistant.util"] = ha_util
    sys.modules["homeassistant.util.dt"] = ha_util.dt
    root.helpers.update_coordinator.CoordinatorEntity = _MockCalendarCoordinatorEntity
    _exec_source("vaillant_ebus.calendar", COMPONENT_PATH / "calendar.py")


# Intent: return a datetime unchanged as the local time.
# Why: tests run in naive local time, so the calendar must see the same value it was given.
def _local_identity(dt):
    return dt


# Intent: return the fixed clock the calendar tests expect for "now".
# Why: the timer tests depend on a stable current time to decide which slot is active.
def _fixed_now():
    return datetime(2026, 8, 27, 12, 0, 0)


# Intent: execute the date platform once with its date-entity stubs.
# Why: the holiday and manual-cooling date entities bind their base classes when the module executes.
def _load_date(root: MagicMock) -> None:
    date_pkg = _stub_module("homeassistant.components.date")
    date_pkg.DateEntity = _MockDateEntity
    sys.modules["homeassistant.components.date"] = date_pkg
    root.helpers.update_coordinator.CoordinatorEntity = _MockDateCoordinatorEntity
    _exec_source("vaillant_ebus.date", COMPONENT_PATH / "date.py")


# Intent: execute the sensor platform once with its sensor and restore-state stubs.
# Why: the sensor entities bind their base classes when the module executes.
def _load_sensor(root: MagicMock) -> None:
    sensor_pkg = _stub_module("homeassistant.components.sensor")
    sensor_pkg.SensorEntity = _MockSensorEntity
    sys.modules["homeassistant.components.sensor"] = sensor_pkg
    restore = _stub_module("homeassistant.helpers.restore_state")
    restore.RestoreEntity = _MockRestoreEntity
    sys.modules["homeassistant.helpers.restore_state"] = restore
    root.helpers.update_coordinator.CoordinatorEntity = _MockSensorCoordinatorEntity
    _exec_source("vaillant_ebus.sensor", COMPONENT_PATH / "sensor.py")


# Intent: execute the remaining component modules once: dump service, migration, and the integration init.
# Why: the integration init imports the coordinator, platforms and const, so it loads last.
def _load_remaining_components() -> None:
    _exec_source("vaillant_ebus.dump_service", COMPONENT_PATH / "dump_service.py")
    _exec_source("vaillant_ebus.migration", COMPONENT_PATH / "migration.py")
    _exec_source("vaillant_ebus.integration_init", COMPONENT_PATH / "__init__.py")


# Intent: execute every shared vaillant_ebus module exactly once per process and expose them through sys.modules.
# Why: repeated execution replaced shared entries, so a subset run bound tests to stale module objects.
def ensure_vaillant_modules() -> None:
    global _LOADED
    if _LOADED:
        return
    root = _homeassistant_root()
    _register_homeassistant(root)
    _register_homeassistant_packages()
    _register_const()
    _register_packages()
    _register_repairs()
    _load_backend()
    _load_coordinator()
    _load_climate(root)
    _load_boost_platforms(root)
    _load_calendar(root)
    _load_date(root)
    _load_sensor(root)
    _load_remaining_components()
    _LOADED = True


ensure_vaillant_modules()
