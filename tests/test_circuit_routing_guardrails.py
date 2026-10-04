"""Static guardrails against reintroducing physical circuit defaults."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
COMPONENT = PROJECT_ROOT / "custom_components" / "vaillant_ebus"


# Intent: prevent physical controller and zone defaults from returning to runtime routing.
# Why: a new ctlv2/hmu/z1 fallback can silently target the wrong hardware while tests remain green.
def test_runtime_routing_has_no_physical_startup_defaults() -> None:
    # The routing logic now lives in coordinator.py and the pure backend planners, so scan them together.
    coordinator = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (COMPONENT / "coordinator.py", *(COMPONENT / "backend").glob("*.py"))
    )
    climate = (COMPONENT / "climate.py").read_text(encoding="utf-8")
    platform_code = "\n".join(
        (COMPONENT / name).read_text(encoding="utf-8")
        for name in ("date.py", "datetime.py", "switch.py", "water_heater.py", "binary_sensor.py", "calendar.py")
    )

    assert 'self._heating_circuit = "ctlv2"' not in coordinator
    assert 'return "hmu"' not in coordinator
    assert 'zone_circuits = {"z1"' not in climate
    assert 'get_device_info("z1")' not in platform_code


# Intent: preserve the distinction between protocol register names and physical owners.
# Why: Z1/Hc1 names are valid ebusd fields and must not be treated as ctlv1 routing defaults.
def test_protocol_names_are_not_used_as_physical_owner_defaults() -> None:
    climate = (COMPONENT / "climate.py").read_text(encoding="utf-8")
    assert 'async_write_register("ctlv1"' not in climate
    assert 'async_write_register("ctlv2"' not in climate
    assert 'async_write_register("ctlv9"' not in climate
