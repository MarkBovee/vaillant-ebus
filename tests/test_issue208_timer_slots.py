"""Issue #208: hot water timer slots 1 and 2 on the CTLV2 SW0514 configuration that decodes only slot 0.

Driven by the reporter's capture (`flexocompact_find.txt`, same scan identity and `HwcTimer_Timeslots` layout) and the
raw slot grab posted in the issue (`ctlv2_issue208_timeslot_grab.txt`).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

import pytest

from tests.backend_loader import load_backend
from tests.fake_ebusd import load_find_lines

DISCOVERY = load_backend("discovery_service")
RUNTIME = load_backend("runtime_definitions")
MAPPING = load_backend("mapping")
PLANNER = load_backend("fallback_planner")

REPORTER_FIND = "community/flexocompact_find.txt"
OWNER_LAYOUT = "community/flexotherm_discovery.yaml"
GRAB = Path(__file__).parent / "fixtures" / "community" / "ctlv2_issue208_timeslot_grab.txt"


# Intent: build the device graph of a capture from its find lines.
# Why: the slot definitions are decided on the discovered graph, never on a literal circuit.
def _graph(fixture: str) -> object:
    return DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture))


# Intent: read the request/response pairs of the issue grab, keyed by request.
# Why: the define id must rebuild exactly the request the controller answered.
def _grab() -> dict[str, list[str]]:
    pairs: dict[str, list[str]] = {}
    for line in GRAB.read_text().splitlines():
        if " / " not in line or line.startswith("#"):
            continue
        request, _, rest = line.partition(" / ")
        pairs.setdefault(request.strip(), []).append(rest.split()[0])
    return pairs


# Intent: decode one slot answer the way the definition's fields do: skip NN and status, then two HTM times.
# Why: ties the field layout to the captured bytes (03 14 03 1e is 03:20-03:30) without a running ebusd.
def _decode(response: str) -> str:
    data = bytes.fromhex(response)[1:]
    return f"{data[1]:02d}:{data[2]:02d};{data[3]:02d}:{data[4]:02d}"


# Intent: the reporter's CTLV2 gets slots 1 and 2 of every weekday, and each define id rebuilds a captured request.
# Why: issue #208 - only slot 0 decodes there; an id with the length byte would never match (AGENTS.md define rule).
def test_reporter_ctlv2_gets_slot_reads_matching_the_grab() -> None:
    definitions = RUNTIME.hwc_timer_slot_definitions(_graph(REPORTER_FIND))

    assert len(definitions) == 14
    assert {item.split(",")[2] for item in definitions} == {
        f"HwcTimer_{day}{slot}" for day in RUNTIME.TIMER_WEEKDAYS for slot in (1, 2)
    }
    grab = _grab()
    tuesday = [item for item in definitions if ",HwcTimer_Tuesday" in item]
    for definition in tuesday:
        parts = definition.split(",")
        message_id = parts[7]
        request = f"{parts[4]}{parts[5]}{parts[6].lower()}{len(message_id) // 2:02x}{message_id}"
        assert request in grab
        assert not message_id.startswith("05")
    assert all(item in RUNTIME.build_runtime_defines(_graph(REPORTER_FIND), datetime(2026, 1, 15)) for item in tuesday)


# Intent: the field layout decodes the captured answers to the written times, and a missing slot to the empty marker.
# Why: the calendar treats `00:00;00:00` as a free slot; status 02 must never look like a real slot.
def test_slot_layout_decodes_the_captured_answers() -> None:
    answers = _grab()["3115b55505a500020101"]

    assert [_decode(answer) for answer in answers] == ["00:00;00:00", "03:20;03:30", "00:00;00:00"]
    assert RUNTIME.HWC_TIMER_SLOT_FIELDS.startswith("ign,,IGN:1,")
    assert "temp" not in RUNTIME.HWC_TIMER_SLOT_FIELDS


# Intent: no slot definition where the configuration already ships slots 0-2 (`Timeframes`), or on other firmware.
# Why: the owner's CTLV2 has its own slot messages with a temperature; the request is only evidenced for SW0514.
@pytest.mark.parametrize("sw", ["0514", "0515"])
def test_slot_reads_are_absent_on_other_layouts_and_firmware(sw: str) -> None:
    assert RUNTIME.hwc_timer_slot_definitions(_graph(OWNER_LAYOUT)) == []
    assert RUNTIME.hwc_timer_slot_definitions(None) == []
    graph = _graph(REPORTER_FIND)
    nodes = dict(graph.nodes)
    nodes["ctlv2"] = dataclasses.replace(nodes["ctlv2"], scan_sw=sw)
    rows = tuple(
        dataclasses.replace(row, scan_sw=sw) if row.scan_type.casefold() == "ctlv2" else row
        for row in graph.scan_identities
    )
    changed = dataclasses.replace(graph, nodes=nodes, scan_identities=rows)
    assert bool(RUNTIME.hwc_timer_slot_definitions(changed)) is (sw == "0514")


# Intent: the slot reads are re-read on the energy interval only, and only when their definition was accepted.
# Why: plain `r` messages are not polled by ebusd, so the calendar would otherwise show the first read forever.
def test_slot_reads_follow_the_energy_interval() -> None:
    graph = _graph(REPORTER_FIND)
    definitions = {f"r.ctlv2.{item.split(',')[2]}": item for item in RUNTIME.hwc_timer_slot_definitions(graph)}
    find_keys = set(graph.raw_registers) | set(graph.placeholder_registers)

    # Intent: resolve a logical circuit to the node the graph really has.
    # Why: mirrors the coordinator without assuming a literal circuit.
    def resolve(circuit: str) -> str | None:
        return next((node for node in graph.nodes if node.casefold() == circuit.casefold()), None)

    plan = PLANNER.plan_fallback_reads
    with_flag = plan(graph, find_keys, definitions, resolve, MAPPING.REGISTER_MAP, include_energy=True)
    without_flag = plan(graph, find_keys, definitions, resolve, MAPPING.REGISTER_MAP)
    absent = plan(graph, find_keys, {}, resolve, MAPPING.REGISTER_MAP, include_energy=True)

    slots = {("ctlv2", f"HwcTimer_{day}{slot}") for day in RUNTIME.TIMER_WEEKDAYS for slot in (1, 2)}
    assert slots <= set(with_flag)
    assert not slots & set(without_flag)
    assert not slots & set(absent)
