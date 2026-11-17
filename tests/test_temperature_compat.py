"""Tests for the bridge between the old and the native climate and water heater temperature API."""

from __future__ import annotations

from custom_components.vaillant_ebus.temperature_compat import temperature_aliases_for

_OLD_NAMES = (
    "temperature_unit",
    "current_temperature",
    "target_temperature",
    "target_temperature_high",
    "target_temperature_low",
)


class _NativeBase:
    """Stand-in for a Home Assistant 2026.11+ entity base class with the native temperature API."""

    native_current_temperature = None


class _OldBase:
    """Stand-in for a Home Assistant entity base class before the native temperature API."""


# Intent: on a base class with the native API the mixin adds none of the deprecated temperature names.
# Why: Home Assistant 2026.11 warns (and 2027.11 breaks) when a subclass defines the old names.
def test_native_base_gets_no_deprecated_temperature_members() -> None:
    mixin = temperature_aliases_for(_NativeBase)

    class Entity(mixin, _NativeBase):  # type: ignore[misc, valid-type]
        _attr_native_temperature_unit = "°C"

        @property
        def native_current_temperature(self) -> float | None:  # type: ignore[override]
            return 21.5

    defined_by_integration = {name for cls in Entity.__mro__[:-2] for name in vars(cls)}
    assert defined_by_integration.isdisjoint(_OLD_NAMES)


# Intent: on an old base class the old names return the native values, including the range targets and the unit.
# Why: the integration still supports Home Assistant 2026.3, whose base classes only read the old names.
def test_old_base_reads_native_values_through_old_names() -> None:
    mixin = temperature_aliases_for(_OldBase)

    class Entity(mixin, _OldBase):  # type: ignore[misc, valid-type]
        _attr_native_temperature_unit = "°C"
        native_current_temperature = 45.0
        native_target_temperature = 48.0
        native_target_temperature_low = 25.0
        native_target_temperature_high = 55.0

    class Single(mixin, _OldBase):  # type: ignore[misc, valid-type]
        _attr_native_temperature_unit = "°C"
        native_current_temperature = 20.0

    entity, single = Entity(), Single()
    assert (entity.temperature_unit, entity.current_temperature, entity.target_temperature) == ("°C", 45.0, 48.0)
    assert (entity.target_temperature_low, entity.target_temperature_high) == (25.0, 55.0)
    assert (single.target_temperature, single.target_temperature_low, single.target_temperature_high) == (None,) * 3
