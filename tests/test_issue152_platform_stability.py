"""Issue #152: an entity keeps its platform while its register (or its zone's room temperature) reads no data."""

from __future__ import annotations

import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests import _component_loader  # noqa: F401 - loads the shared modules once
from tests.fake_ebusd import load_find_lines
from tests.test_coordinator import _entry, _hass

MODELS = sys.modules["vaillant_ebus.backend.models"]
MAPPING = sys.modules["vaillant_ebus.backend.mapping"]
FACTORY = sys.modules["vaillant_ebus.backend.entity_factory"]
DISCOVERY = sys.modules["vaillant_ebus.backend.discovery_service"]
CLEANUP = sys.modules["vaillant_ebus.cleanup"]
COORDINATOR = sys.modules["vaillant_ebus.coordinator"]

ENTRY_ID = "entry-1"
REPORTER_FIXTURES = (
    "community/f34_issue152_v192_after_cleanup_discovery.yaml",
    "community/saunier_duval_f34_issue152_2026-10-02_194815_discovery.yaml",
)
# The zone 2 rows the reporter's 1.15.0 repair listed as "no longer provided" while the zone worked.
REPORTED_ZONE2_IDS = {
    "ebusd_bass_z2holidaytemp",
    "ebusd_bass_z2nighttemp",
    "ebusd_bass_z2opmode",
    "ebusd_bass_z2opmodecooling",
    "ebusd_bass_z2quickvetotemp",
}


# Intent: build the reporter's graph from the post-definition find lines, optionally with every value replaced.
# Why: the flip needs the same graph once with live values and once while ebusd reports `no data stored`.
def _graph(fixture: str, blank: bool = False) -> object:
    graph = DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    if blank:
        graph.raw_registers = {key: "no data stored" for key in graph.raw_registers}
    return graph


# Intent: map each generated unique id to its platform.
# Why: the assertions compare platforms of the same entities across two generations.
def _platforms(entities: list) -> dict[str, str]:
    return {entity.unique_id: entity.entity_type for entity in entities}


# Intent: classify one read-only or writable register with an optional platform hint.
# Why: the hint guard is decided per register shape, so the tests vary only shape and hint.
def _classify(name: str, raw: str | None, hint: str | None, writable: bool = False, **meta: object) -> str:
    register = MODELS.EbusdRegister(circuit="bai", name=name, fields=["value"], value={"value": raw}, writable=writable)
    return FACTORY._classify_register(register, "value", raw, MAPPING.RegisterMeta(writable=writable, **meta), hint)


# Intent: build one registry row in the live shape the cleanup helpers read.
# Why: AGENTS.md - registry fakes must mirror the live rows (prefixed unique id, `aliases`, config entry).
def _row(entity_id: str, unique_id: str, entry_id: str = ENTRY_ID) -> SimpleNamespace:
    return SimpleNamespace(
        entity_id=entity_id,
        unique_id=f"{entry_id}_{unique_id}",
        config_entry_id=entry_id,
        platform="vaillant_ebus",
        disabled_by=None,
        aliases=[None],
    )


# Intent: hold registry rows the way Home Assistant's registry exposes them to the coordinator.
# Why: the coordinator iterates `registry.entities.values()` like its other registry passes.
def _registry(rows: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(entities={row.entity_id: row for row in rows})


# Intent: with the reporter's capture, a second generation during `no data stored` keeps every platform the first one
#         chose once the factory gets the recorded platforms; without them the five reported zone 2 rows flip.
# Why: issue #152 - the zone 2 controls became sensors whenever Z2RoomTemp read no data, Home Assistant kept both rows
#      and the stale-entity repair listed the abandoned ones although the zone worked.
@pytest.mark.parametrize("fixture", REPORTER_FIXTURES)
def test_issue152_reporter_capture_keeps_platforms_while_values_read_no_data(fixture: str) -> None:
    factory = FACTORY.EntityFactoryService()
    live = factory.generate(_graph(fixture))
    before = _platforms(live)

    unhinted = _platforms(factory.generate(_graph(fixture, blank=True)))
    recorded = FACTORY.determined_platforms(live)
    hinted = _platforms(factory.generate(_graph(fixture, blank=True), known_platforms=recorded))

    flipped = {uid for uid, platform in unhinted.items() if uid in before and before[uid] != platform}
    assert flipped == REPORTED_ZONE2_IDS
    assert {uid: platform for uid, platform in hinted.items() if before.get(uid, platform) != platform} == {}


# Intent: a register without a value keeps the hinted binary_sensor; without a hint, and for every real value, the
#         platform is chosen exactly as before.
# Why: issue #152 - `bai Flame` reads `on`/`off` while the burner reports and `no data stored` otherwise, so it moved
#      between sensor and binary_sensor and left a stale row each time.
@pytest.mark.parametrize("raw", [None, "", "-", "no data stored", "ERR: invalid position"])
def test_issue152_shape_less_value_keeps_the_hinted_platform(raw: str | None) -> None:
    assert _classify("Flame", raw, "binary_sensor") == "binary_sensor"
    assert _classify("Flame", raw, None) == "sensor"
    assert _classify("Flame", "on", "sensor") == "binary_sensor"
    assert _classify("Flame", "12", "binary_sensor") == "sensor"
    assert _classify("Flame", raw, "binary_sensor", entity_type="sensor") == "sensor"


# Intent: a hint never creates a control the register cannot have, never makes a counter or a register with a unit a
#         binary_sensor, and ignores platforms the classifier does not produce.
# Why: write safety - a stale registry row must not turn a read-only register into a number or switch, and a counter
#      must stay a sensor (issue #216). Legacy FanSpeed-style rows are covered by the ambiguous registry seed below.
def test_issue152_hint_must_fit_the_register_shape() -> None:
    assert _classify("Flame", None, "number") == "sensor"
    assert _classify("Flame", None, "switch") == "sensor"
    assert _classify("CompressorStarts", None, "binary_sensor") == "sensor"
    assert _classify("YieldTotal", None, "binary_sensor") == "sensor"
    assert _classify("Flame", None, "binary_sensor", unit="°C") == "sensor"
    assert _classify("Flame", None, "binary_sensor", writable=True) == "sensor"
    assert _classify("Flame", None, "climate") == "sensor"
    assert _classify("Flame", None, "select") == "sensor"
    assert _classify("HwcSwitch", None, "switch", writable=True) == "switch"
    assert _classify("Temp", None, "number", writable=True) == "sensor"
    assert _classify("Temp", None, "number", writable=True, min_value=5, max_value=30) == "number"


# Intent: the recorded platforms hold evidence only: a value with a shape or the mapped entity type, never a guess
#         made from `no data stored`.
# Why: issue #152 - recording a guessed sensor would pin the wrong platform as firmly as a real one.
def test_issue152_determined_platforms_skip_guesses() -> None:
    graph = MODELS.DeviceGraph(
        nodes={"bai": MODELS.DeviceNode(circuit="bai", device_type=MODELS.DeviceType.UNKNOWN, has_data=True)},
        raw_registers={"bai.Flame": "no data stored", "bai.FanSpeed": "1200"},
        placeholder_registers=set(),
    )
    graph.nodes["bai"].registers = list(graph.raw_registers)

    recorded = FACTORY.determined_platforms(FACTORY.EntityFactoryService().generate(graph))

    assert "ebusd_bai_flame" not in recorded
    assert recorded.get("ebusd_bai_fanspeed") == "sensor"


# Intent: the registry seed takes one platform per unique id, drops ambiguous ids and reads only its own entry.
# Why: issue #152 - a legacy row on another platform (for example a binary_sensor from before #216 next to the sensor)
#      must not decide the platform, and another config entry's rows are not this entry's history.
def test_issue152_registry_platforms_seed_only_unambiguous_rows() -> None:
    registry = _registry(
        [
            _row("binary_sensor.boiler_flame", "ebusd_bai_flame"),
            _row("sensor.fan_speed", "ebusd_bai_FanSpeed"),
            _row("binary_sensor.fan_speed", "ebusd_bai_fanspeed"),
            _row("number.zone_2_night", "ebusd_bass_z2nighttemp"),
            _row("switch.other_entry", "ebusd_bai_other", entry_id="entry-2"),
        ]
    )

    seeds = CLEANUP.registry_platforms(registry, ENTRY_ID)

    assert seeds == {"ebusd_bai_flame": "binary_sensor", "ebusd_bass_z2nighttemp": "number"}


# Intent: the coordinator hands the registry platform to every generation, and a later real value replaces the seed.
# Why: issue #152 - the cache seed, the discovery and the fallback regeneration all generate entities; a missed caller
#      or a cached map would bring the flip back.
def test_issue152_coordinator_generation_uses_registry_and_recorded_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _registry([_row("binary_sensor.boiler_flame", "ebusd_bai_flame")])
    monkeypatch.setattr(COORDINATOR.entity_registry, "async_get", MagicMock(return_value=registry))
    node = MODELS.DeviceNode(circuit="bai", device_type=MODELS.DeviceType.UNKNOWN, has_data=True)

    # Intent: build a one-register graph with the given Flame value.
    # Why: each generation must see the register as ebusd reports it at that moment.
    def graph(raw: str) -> object:
        result = MODELS.DeviceGraph(nodes={"bai": node}, raw_registers={"bai.Flame": raw}, placeholder_registers=set())
        node.registers = ["bai.Flame"]
        return result

    with tempfile.TemporaryDirectory() as tmpdir:
        entry = _entry()
        entry.entry_id = ENTRY_ID
        coordinator = COORDINATOR.VaillantCoordinator(_hass(tmpdir), entry)

        # Intent: generate through the coordinator and return the Flame platform.
        # Why: the coordinator helper is the seam all three generation paths share.
        def flame(raw: str) -> str:
            return _platforms(coordinator._generate_entities(graph(raw), {}))["ebusd_bai_flame"]

        assert flame("no data stored") == "binary_sensor"
        assert flame("78") == "sensor"
        assert flame("no data stored") == "sensor"
        registry.entities.clear()
        assert flame("on") == "binary_sensor"
        assert flame("no data stored") == "binary_sensor"
