"""A primary value must not be suppressed together with redundant composite text."""

from __future__ import annotations

import pytest

from tests.backend_loader import load_backend

FACTORY = load_backend("entity_factory")
MAPPING = load_backend("mapping")
MODELS = load_backend("models")
KEY = "v32.ExampleTemp"


# Intent: provide a synthetic mapping, not production recoVAIR register support.
# Why: issue #237 is about the generic value-field contract, independent of hardware.
def _graph(monkeypatch: pytest.MonkeyPatch, fields: list[str], raw: str):
    monkeypatch.setitem(MAPPING.MULTI_FIELD_FIELDS, KEY, fields)
    monkeypatch.setitem(
        MAPPING.REGISTER_MAP,
        KEY,
        MODELS.RegisterMeta(
            friendly_name="Example Temperature",
            unit="°C",
            device_class="temperature",
            state_class="measurement",
            entity_type="sensor",
            enabled=True,
        ),
    )
    monkeypatch.setitem(
        MAPPING.REGISTER_MAP,
        KEY + ".sensor",
        MODELS.RegisterMeta(friendly_name="Example Sensor Status", entity_type="sensor", enabled=True),
    )
    node = MODELS.DeviceNode(circuit="v32", device_type=MODELS.DeviceType.VENTILATION, registers=[KEY], has_data=True)
    return MODELS.DeviceGraph(nodes={"v32": node}, raw_registers={KEY: raw}, placeholder_registers=set())


# Intent: retain the primary entity and separate status regardless of field order or temperature sign.
# Why: the field loop skips `value`, so suppressing the base entity loses the only measurement (#237).
@pytest.mark.parametrize("fields", [["value", "sensor"], ["sensor", "value"]])
@pytest.mark.parametrize("reading", ["11.25", "0", "-4.5"])
def test_primary_value_and_status_both_have_entities(monkeypatch: pytest.MonkeyPatch, fields, reading):
    raw = ";".join(reading if field == "value" else "ok" for field in fields)
    graph = _graph(monkeypatch, fields, raw)
    entities = {entity.key: entity for entity in FACTORY.EntityFactoryService().generate(graph)}

    primary = entities[KEY + ".value"]
    assert primary.unique_id == "ebusd_v32_exampletemp"
    assert primary.entity_type == "sensor"
    assert primary.meta.unit == "°C"
    assert primary.meta.state_class == "measurement"
    assert KEY + ".sensor" in entities
    assert MAPPING.split_multi_field(KEY, raw)["value"] == reading


# Intent: a mapping containing only `value` keeps its ordinary base sensor.
# Why: the composite fix must preserve existing single-field behavior.
def test_single_primary_value_keeps_base_entity(monkeypatch: pytest.MonkeyPatch):
    graph = _graph(monkeypatch, ["value"], "11.25")
    keys = {entity.key for entity in FACTORY.EntityFactoryService().generate(graph)}
    assert keys == {KEY + ".value"}


# Intent: redundant combined text stays suppressed unless explicitly enabled.
# Why: fixing #237 must not undo #215 or remove its supported YAML override.
@pytest.mark.parametrize("keep_composite", [False, True])
def test_named_fields_keep_composite_suppression_and_override(monkeypatch: pytest.MonkeyPatch, keep_composite):
    graph = _graph(monkeypatch, ["temperature", "sensor"], "11.25;ok")
    overrides = {KEY: {"enabled": True}} if keep_composite else None
    keys = {entity.key for entity in FACTORY.EntityFactoryService().generate(graph, yaml_overrides=overrides)}
    assert KEY + ".temperature" in keys
    assert KEY + ".sensor" in keys
    assert (KEY + ".value" in keys) is keep_composite
