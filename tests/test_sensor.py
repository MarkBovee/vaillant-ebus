"""Unit tests for the sensor platform — frozen-value and availability behavior."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

from tests import test_coordinator as tc  # noqa: F401 — installs shared HA/backend mocks

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus"

mock_homeassistant = sys.modules["homeassistant"]


class _MockCoordinatorEntity:
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls


mock_homeassistant.helpers.update_coordinator.CoordinatorEntity = _MockCoordinatorEntity


class _MockSensorEntity:
    pass


class _MockRestoreEntity:
    pass


sensor_pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("homeassistant.components.sensor", None))
sensor_pkg.SensorEntity = _MockSensorEntity
sys.modules["homeassistant.components.sensor"] = sensor_pkg

restore = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.helpers.restore_state", None)
)
restore.RestoreEntity = _MockRestoreEntity
sys.modules["homeassistant.helpers.restore_state"] = restore

entity_platform = importlib.util.module_from_spec(
    importlib.machinery.ModuleSpec("homeassistant.helpers.entity_platform", None)
)
entity_platform.AddEntitiesCallback = object
sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

SENSOR_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.sensor", COMPONENT_PATH / "sensor.py")
assert SENSOR_SPEC and SENSOR_SPEC.loader
SENSOR = importlib.util.module_from_spec(SENSOR_SPEC)
sys.modules["vaillant_ebus.sensor"] = SENSOR
SENSOR_SPEC.loader.exec_module(SENSOR)

from vaillant_ebus.backend.entity_factory import EntityDescription  # noqa: E402
from vaillant_ebus.backend.mapping import RegisterMeta  # noqa: E402
from vaillant_ebus.backend.models import EbusdRegister  # noqa: E402
from vaillant_ebus.sensor import EbusdSensor  # noqa: E402


def _coordinator(data: dict) -> MagicMock:
    c = MagicMock()
    c.data = {"ebusd": data}
    c.last_update_success = True
    c.get_device_info = MagicMock(return_value={})
    return c


def _desc(name: str = "OutsideTemp", unit: str = "°C") -> EntityDescription:
    meta = RegisterMeta(friendly_name="Outside Temp", unit=unit)
    reg = EbusdRegister(circuit="hmu", name=name, fields=["value"])
    return EntityDescription(circuit="hmu", name=name, field="value", meta=meta, register=reg)


def _sensor(c: MagicMock, desc: EntityDescription | None = None) -> EbusdSensor:
    return EbusdSensor(c, desc or _desc(), "entry-1_uid", MagicMock())


# Intent: a register with no live data must report unknown, never a stale cached
# value.
# Why: issue #99 - a register that stops being read (dead circuit after a
# resolution change) previously froze the entity on its last known value while
# remaining "available".
def test_sensor_missing_register_data_is_unknown() -> None:
    s = _sensor(_coordinator({}))
    assert s.native_value is None


# Intent: an idle register's "no data stored" sentinel reports unknown.
# Why: it must not fall back to a cached value either.
def test_sensor_no_data_stored_is_unknown() -> None:
    s = _sensor(_coordinator({"hmu.OutsideTemp.value": "no data stored"}))
    assert s.native_value is None


# Intent: a present numeric register still decodes to a float.
# Why: the frozen-value change must not break normal sensor decoding.
def test_sensor_present_value_decodes() -> None:
    s = _sensor(_coordinator({"hmu.OutsideTemp.value": "21.5"}))
    assert s.native_value == 21.5


# Intent: availability follows the coordinator, independent of per-register data.
# Why: idle "no data stored" registers must not flicker available on/off; a
# missing register surfaces as unknown (native_value None), not unavailable.
def test_sensor_availability_tracks_coordinator_not_register() -> None:
    c = _coordinator({})
    s = _sensor(c)
    assert s.available is True
    c.last_update_success = False
    assert s.available is False
