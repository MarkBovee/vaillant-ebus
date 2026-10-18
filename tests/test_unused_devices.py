"""Tests for the zones and devices the controller reports as unused (release 1.12.0)."""

from __future__ import annotations

import re

from tests.fake_ebusd import load_find_lines
from tests.test_entity_factory import DiscoveryService, EntityFactoryService

OWNER_FIXTURE = "community/flexotherm_ctlv2_cooling_discovery.yaml"
ECOTEC_FIXTURE = "community/arotherm_ecotec_discovery.yaml"
F34_FIXTURE = "community/saunier_duval_f34_issue129_discovery.yaml"

# Values the owner's live Home Assistant showed for the unused zones 2 and 3 on 2026-10-18 (release 1.11.2 running):
# the controller answers static defaults for zones it does not have, so the registers look like real data.
STATIC_ZONE_DEFAULTS = {
    "DayTemp": "21.0",
    "HolidayEndPeriod": "01.01.2015",
    "HolidayStartPeriod": "01.01.2015",
    "HolidayTemp": "15.0",
    "NightTemp": "15.0",
    "OpMode": "auto",
    "QuickVetoDuration": "3.0",
    "QuickVetoEndDate": "01.01.2019",
    "QuickVetoEndTime": "00:00:00",
    "QuickVetoTemp": "21.0",
    "SFMode": "auto",
}


# Intent: rebuild the owner's controller lines with the live static defaults for zones 2 and 3.
# Why: the stored capture predates the defaults (they read `no data stored`); the live system shows them as values,
#      and that is what created the extra zone devices. This variant is SYNTHETIC, derived from the observed states.
def _owner_live_lines(drop: tuple[str, ...] = (), add: tuple[str, ...] = ()) -> list[str]:
    lines = [
        line
        for line in load_find_lines(OWNER_FIXTURE, after=True)
        if not re.match(r"ctlv2 Z[23](?!RoomTemp|RoomZoneMapping)", line) and not any(item in line for item in drop)
    ]
    lines += [f"ctlv2 Z{zone}{name} = {value}" for zone in (2, 3) for name, value in STATIC_ZONE_DEFAULTS.items()]
    return [*lines, *add]


# Intent: generate entities from find lines, keyed by their register key.
# Why: every assertion looks at which registers become entities and which device they land on.
def _entities(lines: list[str], overrides: dict[str, dict] | None = None) -> dict:
    graph = DiscoveryService.build_device_graph(lines)
    return {entity.key: entity for entity in EntityFactoryService().generate(graph, yaml_overrides=overrides)}


# Intent: registers of a numbered zone or heating circuit, by key.
# Why: the assertions compare the whole set of a zone, not single names.
def _zone_keys(entities: dict, prefix: str) -> list[str]:
    return sorted(key for key, entity in entities.items() if re.match(rf"^{prefix}(?!\d)", entity.name, re.IGNORECASE))


# Intent: the controller says circuits 2 and 3 are inactive, so neither zone gets entities, only the circuit type.
# Why: the owner's HA lists about 80 entities for two zones that do not exist; static defaults are not evidence.
def test_declared_unused_zones_create_no_entities_but_keep_the_circuit_type() -> None:
    entities = _entities(_owner_live_lines())

    assert _zone_keys(entities, "Z2") == [] and _zone_keys(entities, "Z3") == []
    assert _zone_keys(entities, "Hc2") == ["ctlv2.Hc2CircuitType.value"]
    assert _zone_keys(entities, "Hc3") == ["ctlv2.Hc3CircuitType.value"]
    assert _zone_keys(entities, "Z1") and _zone_keys(entities, "Hc1")


# Intent: the circuit type of an unused zone lives on the controller device, so no zone device remains for it.
# Why: decision D3 - the sensor explains why the zone is missing; a zone device for one sensor is what users complained
#      about (issue #152 shows a Zone 3 device with only this sensor).
def test_circuit_type_of_an_unused_zone_moves_to_the_controller_device() -> None:
    entities = _entities(_owner_live_lines())

    assert {entities[key].device_circuit for key in ("ctlv2.Hc2CircuitType.value", "ctlv2.Hc3CircuitType.value")} == {
        "ctlv2"
    }
    assert not [key for key, entity in entities.items() if entity.device_circuit in {"z2", "z3", "hc2", "hc3"}]


# Intent: a zone that reports a room temperature is never treated as unused, whatever the circuit type says.
# Why: contradictory evidence must fail safe; hiding a zone that measures a room would remove real entities.
def test_zone_with_a_live_room_temperature_is_kept() -> None:
    entities = _entities(_owner_live_lines(add=("ctlv2 Z2RoomTemp = 21.3",)))

    assert "ctlv2.Z2OpMode.value" in entities
    assert _zone_keys(entities, "Z3") == []


# Intent: an unreadable circuit type hides nothing.
# Why: some controllers answer the type with an error (issue #152, F34); only the controller's own `inactive` counts.
def test_unreadable_circuit_type_hides_no_zone() -> None:
    lines = _owner_live_lines(drop=("Hc2CircuitType", "Hc3CircuitType"))
    entities = _entities(lines)

    assert "ctlv2.Z2OpMode.value" in entities and "ctlv2.Z3OpMode.value" in entities


# Intent: a user override with `enabled: true` brings a hidden register back.
# Why: the YAML override is the documented escape hatch when the controller's `inactive` is wrong for a user.
def test_override_enabled_keeps_a_register_of_an_unused_zone() -> None:
    entities = _entities(_owner_live_lines(), {"ctlv2.Z2OpMode": {"enabled": True}})

    assert "ctlv2.Z2OpMode.value" in entities
    assert "ctlv2.Z2DayTemp.value" not in entities


# Intent: in a mixed system only the zone the controller declares unused loses its entities.
# Why: the ecotec capture has zone 2 in use (VR91 mapping, mixer circuit) and zone 3 unused (mapping none, inactive).
def test_only_the_declared_unused_zone_loses_entities() -> None:
    entities = _entities(load_find_lines(ECOTEC_FIXTURE, after=True))

    assert _zone_keys(entities, "Z2") and _zone_keys(entities, "Hc2")
    assert _zone_keys(entities, "Z3") == []
    assert _zone_keys(entities, "Hc3") == ["ctlv2.Hc3CircuitType.value"]


# Intent: a solar controller that only mirrors the heating controller creates no entities.
# Why: in all 14 captures with a scan of address `ec` the identity equals the controller's and every `sc` row reads
#      `no data stored`; the owner's HA still lists a "solar controller" device and zone sensors from `sc` registers.
def test_mirrored_solar_controller_creates_no_entities() -> None:
    for fixture in (OWNER_FIXTURE, F34_FIXTURE):
        graph = DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
        entities = EntityFactoryService().generate(graph)

        assert not [entity.key for entity in entities if entity.circuit.casefold() == "sc"], fixture


# Intent: a solar controller with its own identity or with live data keeps its entities.
# Why: a real solar module differs from the heating controller in SW and HW, and a real one answers its registers.
def test_real_solar_controller_keeps_its_entities() -> None:
    lines = load_find_lines(OWNER_FIXTURE, after=True)
    other_identity = ["scan.ec  = Vaillant;SOL00;0100;0200" if line.startswith("scan.ec") else line for line in lines]
    with_data = [*lines, "sc Hc1PumpKol1PP1Port = 5"]

    assert any(
        e.circuit.casefold() == "sc"
        for e in EntityFactoryService().generate(DiscoveryService.build_device_graph(other_identity))
    )
    assert any(
        e.circuit.casefold() == "sc"
        for e in EntityFactoryService().generate(DiscoveryService.build_device_graph(with_data))
    )
