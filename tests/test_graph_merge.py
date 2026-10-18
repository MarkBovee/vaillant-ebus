"""Tests for the pure graph/entity merge helpers (one scenario per documented rule)."""

from __future__ import annotations

import pytest

from tests.backend_loader import load_backend

MODELS = load_backend("models")
MERGE = load_backend("graph_merge")
FACTORY = load_backend("entity_factory")
DeviceType = MODELS.DeviceType


def _node(circuit: str, device_type=DeviceType.HEAT_PUMP, **kwargs) -> object:
    return MODELS.DeviceNode(circuit=circuit, device_type=device_type, **kwargs)


def _graph(nodes: list, raw: dict | None = None, placeholders=(), errors=(), scans=()) -> object:
    return MODELS.DeviceGraph(
        nodes={n.circuit: n for n in nodes},
        raw_registers=dict(raw or {}),
        placeholder_registers=set(placeholders),
        error_registers=set(errors),
        scan_identities=tuple(scans),
    )


# Intent: a logical alias is stale only when it is a known alias that the graph resolves to another circuit.
# Why: cache rows under a replaced alias are ghosts; rows under a still-valid or unrelated name must survive.
@pytest.mark.parametrize(
    ("circuit", "expected"),
    [
        ("ctlv2", True),  # alias of the discovered ctlv3 controller
        ("ctlv3", False),  # the discovered circuit itself
        ("z1", False),  # not a logical alias at all
        ("bai", False),  # alias with no unique target in this graph
    ],
)
def test_is_stale_legacy_alias(circuit: str, expected: bool) -> None:
    ctlv3 = _node("ctlv3", DeviceType.HEATING_CONTROLLER, registers=["ctlv3.Z1DayTemp"])
    graph = _graph([ctlv3], {"ctlv3.Z1DayTemp": "20"})

    assert MERGE.is_stale_legacy_alias(circuit, graph) is expected


# Intent: nodes merge field by field: known type wins over UNKNOWN, lists are unioned without duplicates,
# the newer parent/scan data wins, and scan fields fall back to the previous node when the new one has none.
# Why: a delayed partial find must add information without erasing what an earlier full find established.
def test_merge_nodes_field_rules() -> None:
    old = _node(
        "HMU",
        DeviceType.HEAT_PUMP,
        registers=["hmu.A", "hmu.B"],
        parent="p-old",
        zone_circuits=["z1"],
        heating_circuits=["hc1"],
        has_data=True,
        scan_type="HMU00",
        scan_sw="0303",
        scan_hw="0403",
        scan_address="scan.08",
    )
    new = _node(
        "hmu",
        DeviceType.UNKNOWN,
        registers=["hmu.B", "hmu.C"],
        parent="p-new",
        zone_circuits=["z1", "z2"],
        heating_circuits=["hc2"],
        scan_address="scan.09",
    )

    merged = MERGE.merge_device_graphs(_graph([old]), _graph([new])).nodes["HMU"]

    assert merged.circuit == "HMU"  # existing spelling is kept
    assert merged.device_type == DeviceType.HEAT_PUMP  # UNKNOWN never replaces a known type
    assert merged.registers == ["hmu.A", "hmu.B", "hmu.C"]
    assert merged.parent == "p-new"
    assert merged.zone_circuits == ["z1", "z2"]
    assert merged.heating_circuits == ["hc1", "hc2"]
    assert (merged.scan_type, merged.scan_sw, merged.scan_hw) == ("HMU00", "0303", "0403")
    assert merged.scan_address == "scan.09"  # the address always follows the latest scan


# Intent: a known device type from the new node replaces the previous type, and a missing new parent keeps the old.
# Why: the latest find is authoritative for the role; the parent is only replaced when the new find knows one.
def test_merge_nodes_prefers_known_new_type_and_keeps_parent() -> None:
    old = _node("x", DeviceType.UNKNOWN, parent="keep")
    new = _node("x", DeviceType.HEAT_PUMP)

    merged = MERGE.merge_device_graphs(_graph([old]), _graph([new])).nodes["x"]

    assert merged.device_type == DeviceType.HEAT_PUMP
    assert merged.parent == "keep"


# Intent: a new circuit is added, and vwz/vwzio nodes missing from the latest find lose their scan address.
# Why: a station that vanished must not keep authorising address-bound (0x76) definitions.
def test_merge_adds_new_nodes_and_drops_scan_address_of_missing_vwz() -> None:
    vwzio = _node("vwzio", DeviceType.PASSIVE_COOLING, scan_address="scan.76", scan_type="VWZIO")
    other = _node("hmu", scan_address="scan.08")

    merged = MERGE.merge_device_graphs(_graph([vwzio, other]), _graph([_node("bai", DeviceType.HEATING_CONTROLLER)]))

    assert set(merged.nodes) == {"vwzio", "hmu", "bai"}
    assert merged.nodes["vwzio"].scan_address == ""
    assert merged.nodes["hmu"].scan_address == "scan.08"  # only vwz-family nodes are cleared


# Intent: a vwzio node present in the latest find keeps its scan address.
# Why: the address is only cleared for stations that disappeared, never for current ones.
def test_merge_keeps_scan_address_of_present_vwzio() -> None:
    vwzio = _node("vwzio", DeviceType.PASSIVE_COOLING, scan_address="scan.76")

    merged = MERGE.merge_device_graphs(
        _graph([vwzio]), _graph([_node("vwzio", DeviceType.PASSIVE_COOLING, scan_address="scan.76")])
    )

    assert merged.nodes["vwzio"].scan_address == "scan.76"


# Intent: register maps merge case-insensitively: newer raw values replace old ones under the old spelling, a
# placeholder in the new find removes the stale raw value, raw data removes placeholders, errors and scans are replaced.
# Why: ebusd spelling varies between finds; no duplicate keys and no stale value may survive a newer find.
def test_merge_register_maps_rules() -> None:
    existing = _graph(
        [_node("hmu")],
        raw={"hmu.Flow": "10", "hmu.Stale": "1", "hmu.Keep": "5"},
        placeholders={"hmu.Gone", "hmu.Placeholder"},
        errors={"hmu.OldError"},
        scans=[MODELS.ScanIdentity("scan.08", "HMU00", "1", "2")],
    )
    discovered = _graph(
        [_node("hmu")],
        raw={"HMU.flow": "12", "hmu.Gone": "7"},
        placeholders={"hmu.stale", "HMU.PLACEHOLDER"},
        errors={"hmu.NewError"},
        scans=[MODELS.ScanIdentity("scan.09", "HMU00", "3", "4")],
    )

    merged = MERGE.merge_device_graphs(existing, discovered)

    assert merged.raw_registers == {"hmu.Flow": "12", "hmu.Keep": "5", "hmu.Gone": "7"}
    assert merged.placeholder_registers == {"hmu.Placeholder", "hmu.stale"}
    assert merged.error_registers == {"hmu.NewError"}
    assert [row.address for row in merged.scan_identities] == ["scan.09"]


# Intent: node data flags are recomputed from the merged raw registers, not copied from either side.
# Why: a node whose only value arrived in a delayed find must report data, and one whose value went away must not.
def test_merge_recomputes_node_has_data() -> None:
    existing = _graph([_node("hmu", has_data=True, registers=["hmu.Flow"])], raw={})
    discovered = _graph([_node("hmu", has_data=False, registers=["hmu.Flow"])], raw={"hmu.Flow": "21.5"})

    merged = MERGE.merge_device_graphs(existing, discovered)

    assert merged.nodes["hmu"].has_data is True
    assert (
        MERGE.merge_device_graphs(
            _graph([_node("hmu", has_data=True, registers=["hmu.Flow"])], raw={"hmu.Flow": "21.5"}),
            _graph([_node("hmu", registers=["hmu.Flow"])], placeholders={"hmu.Flow"}),
        )
        .nodes["hmu"]
        .has_data
        is False
    )


def _entity(unique_name: str, name: str = "n", circuit: str = "hmu") -> object:
    register = MODELS.EbusdRegister(circuit=circuit, name=unique_name, fields=["value"], value={"value": "1"})
    return FACTORY.EntityDescription(circuit, unique_name, "value", MODELS.RegisterMeta(), register)


# Intent: new entities are appended; an entity that already exists (case-insensitive) is updated in place, not added.
# Why: cache-seeded entities are already registered with HA; a live description must update them without duplicates.
def test_merge_entities_dedupes_case_insensitively_and_updates_in_place() -> None:
    existing_entity = _entity("Flow")
    live = _entity("FLOW")
    live.raw_value = "42"
    live.enabled_by_default = False
    extra = _entity("Other")

    merged = MERGE.merge_entities([existing_entity], [live, extra])

    assert merged == [existing_entity, extra]
    assert existing_entity.name == "FLOW"  # spelling of the latest description wins
    assert existing_entity.raw_value == "42"
    assert existing_entity.enabled_by_default is False
    assert MERGE.merge_entities([], [live, live]) == [live]  # duplicates inside additions collapse
