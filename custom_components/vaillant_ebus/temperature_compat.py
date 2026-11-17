"""Bridge between the old and the native temperature API of climate and water heater entities.

Home Assistant 2026.11 moved climate and water heater entities to `native_*` temperature members and logs a
deprecation warning for the old names (`temperature_unit`, `current_temperature`, `target_temperature`, ...), which
stop working in 2027.11. The integration still supports Home Assistant 2026.3 (`hacs.json`), whose base classes only
read the old names. The entities implement the native names; on an older base class this mixin maps the old names to
them, and on a newer one it adds nothing, so Home Assistant sees no deprecated member.
"""

from __future__ import annotations


class _LegacyTemperatureAliases:
    """Old temperature names served from the native members, for base classes without the native API."""

    # Unit the old base class reads; the entities declare it as _attr_native_temperature_unit.
    @property
    def temperature_unit(self) -> str:
        unit: str = getattr(self, "_attr_native_temperature_unit")
        return unit

    # Current temperature the old base class reads.
    @property
    def current_temperature(self) -> float | None:
        return getattr(self, "native_current_temperature", None)

    # Single target temperature the old base class reads.
    @property
    def target_temperature(self) -> float | None:
        return getattr(self, "native_target_temperature", None)

    # Upper target of a temperature range the old base class reads.
    @property
    def target_temperature_high(self) -> float | None:
        return getattr(self, "native_target_temperature_high", None)

    # Lower target of a temperature range the old base class reads.
    @property
    def target_temperature_low(self) -> float | None:
        return getattr(self, "native_target_temperature_low", None)


class _NoTemperatureAliases:
    """Empty mixin for base classes that already have the native temperature API."""


# Pick the mixin for an entity base class: aliases only when the base class predates the native temperature API.
# Why: defining the old names on a newer base class is exactly what triggers Home Assistant's deprecation warning.
def temperature_aliases_for(entity_base: type) -> type:
    if hasattr(entity_base, "native_current_temperature"):
        return _NoTemperatureAliases
    return _LegacyTemperatureAliases
