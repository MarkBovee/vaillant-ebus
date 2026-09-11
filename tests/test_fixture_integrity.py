"""Fixture-integrity guardrails for the RC3 test suite.

Fixtures are test inputs, not unquestionable truth. These tests protect the
authoritative real-world captures from silent stripping: the issue #99 HMUX0
captures must keep the spurious ``ctlv2`` records that reproduce the DHW
routing regression, and every discovery-dump fixture must keep provenance
metadata plus at least one raw find-line set.

A stripped fixture can still be technically valid while losing the input
condition a regression test depends on. That was the RC2 lesson: a sanitized
capture made the suite pass for the wrong reason.
"""

from __future__ import annotations

import pytest

from tests.fake_ebusd import FIXTURES_DIR, load_discovery_dump, load_find_lines
from tests.test_entity_factory import DiscoveryService

ISSUE99_DUMPS = (
    "community/hmux0_issue99_2026-09-10_170850.yaml",
    "community/hmux0_issue99_2026-09-10_173229.yaml",
)


# Intent: the real issue #99 captures keep the spurious ctlv2 records that reproduce the DHW routing bug.
# Why: a fixture stripped of the ctlv2 pollution silently loses the regression condition, so
#      the suite would pass even when logical ctlv2 wrongly resolves to ctlv3 at runtime.
@pytest.mark.parametrize("fixture", ISSUE99_DUMPS)
def test_issue99_dumps_keep_spurious_ctlv2_pollution(fixture: str) -> None:
    dump = load_discovery_dump(fixture)
    for label in ("raw_find_lines", "raw_find_lines_after"):
        lines = dump.get(label) or []
        ctlv2 = [line for line in lines if line.strip().startswith("ctlv2 ")]
        assert ctlv2, f"{fixture}: {label} lost the ctlv2 pollution records"
        # The runtime probe/cooling registers that create the bare node.
        assert any("ManualCoolingStartDate" in line for line in ctlv2)
        assert any("z1RoomHumidity" in line for line in ctlv2)
    # The post-definition probe leaves invalid-position errors on the spurious node.
    after_lines = dump.get("raw_find_lines_after") or []
    assert any("ERR: invalid position" in line for line in after_lines)


# Intent: the real issue #99 captures keep ctlv3 as the actual control/DHW register owner.
# Why: stripping ctlv3 ownership would let a wrong resolution pass for the wrong reason.
@pytest.mark.parametrize("fixture", ISSUE99_DUMPS)
def test_issue99_dumps_keep_ctlv3_control_ownership(fixture: str) -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    assert graph.nodes["ctlv3"].device_type.name == "HEATING_CONTROLLER"
    assert graph.raw_registers["ctlv3.HwcOpMode"] == "auto"
    assert graph.raw_registers["ctlv3.HwcSFMode"] == "auto"
    assert graph.heating_controller_result().circuit == "ctlv3"
    assert graph.resolve_circuit_result("ctlv2").circuit == "ctlv3"


# Intent: discovery exposes the bare ctlv2 node while resolution routes logical ctlv2 to ctlv3.
# Why: establishes both halves of the regression condition: the pollution exists AND the fix routes
#      DHW reads to the controller that owns the control registers.
@pytest.mark.parametrize("fixture", ISSUE99_DUMPS)
def test_issue99_dumps_expose_spurious_node_but_resolve_to_ctlv3(fixture: str) -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    assert "ctlv2" in graph.nodes
    assert "ctlv2.HwcOpMode" not in graph.raw_registers
    assert graph.raw_registers["ctlv3.HwcOpMode"] == "auto"
    assert graph.resolve_circuit_result("ctlv2").circuit == "ctlv3"


# Intent: the issue #99 captures retain the HMUX0 heat-pump topology that the bug depends on.
# Why: the routing regression only reproduces on the HMUX0/CTLV3 combination, so the topology
#      (scan identity and the rejected RunDataReturnTemp layout) must not be stripped.
@pytest.mark.parametrize("fixture", ISSUE99_DUMPS)
def test_issue99_dumps_keep_hmux0_topology(fixture: str) -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    assert graph.nodes["hmux0"].device_type.name == "HEAT_PUMP"
    assert graph.nodes["hmux0"].scan_type.upper() == "HMUX0"
    assert "hmux0.RunDataReturnTemp" in graph.placeholder_registers
    assert "hmux0.RunDataReturnTemp" not in graph.raw_registers


# Intent: every discovery-dump fixture carries provenance metadata and at least one find-line set.
# Why: a dump without metadata or raw lines cannot serve as compatibility evidence, and a capture
#      that was trimmed to nothing would otherwise slip through unnoticed.
def test_discovery_dump_fixtures_carry_provenance_and_lines() -> None:
    dumps = sorted((FIXTURES_DIR / "community").glob("*_discovery.yaml"))
    assert dumps, "expected community discovery fixtures"
    for path in dumps:
        dump = load_discovery_dump(str(path))
        raw = dump.get("raw_find_lines") or dump.get("raw_find_lines_after")
        assert raw, f"{path.name} has no raw find lines"
        metadata = dump.get("metadata") or {}
        assert metadata.get("dump_version") or metadata.get("source"), (
            f"{path.name} lacks provenance metadata (dump_version/source)"
        )
