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

ISSUE129_DUMP = "community/saunier_duval_f34_issue129_discovery.yaml"
ISSUE32_DUMP = "community/ctlv3_hmux0_vwzio_issue32_2026-09-22_134029_discovery.yaml"
NEW_CAPTURE_PROVENANCE = {
    "community/arotherm_pro7_issue101_2026-09-15_203102_discovery.yaml": (
        "https://github.com/user-attachments/files/32255148/discovery_dump_2026-09-15_203102Whisper.switch.no.heat.yaml",
        "5a1d38d2827be6c7ae64bf10579225462b24f688b6f966aa2503678ad78092fe",
    ),
    "community/flexotherm_issue102_2026-09-12_161841_discovery.yaml": (
        "https://github.com/user-attachments/files/32144671/discovery_dump_2026-09-12_161841.yaml",
        "f9066c18ac4dd667b70742c61f3fb28703c8057bf1b97571e8fe07a7909648a2",
    ),
    "community/flexotherm_issue102_2026-09-16_103411_discovery.yaml": (
        "https://github.com/user-attachments/files/32278895/discovery_dump_2026-09-16_103411.yaml",
        "52f02d20da8af282cea92a1c346a04880b511c0340821b1a7bacefa353a18e9c",
    ),
    "community/flexotherm_issue102_2026-09-17_090525_discovery.yaml": (
        "https://github.com/user-attachments/files/32323735/discovery_dump_2026-09-17_090525.yaml",
        "f24a5d76854b6c019a72548bf44ed75a467b9931d031d2de788a9a51a881c7ea",
    ),
}


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


# Intent: the issue #129 capture keeps the BASS3 Zone 2 ownership and unavailable day setpoint evidence.
# Why: the reasonable Zone 2 0x22 assumption must not survive if the source capture is reduced.
def test_issue129_dump_keeps_zone2_evidence() -> None:
    dump = load_discovery_dump(ISSUE129_DUMP)
    lines = dump.get("raw_find_lines") or []
    assert any("scan.15" in line and "BASS3;0708;4304" in line for line in lines)
    assert any(line.startswith("bass Z2OpMode =") for line in lines)
    assert any(line.startswith("bass Z2RoomTemp = 24.6875") for line in lines)
    assert any(line.startswith("bass Z2DayTemp = no data stored") for line in lines)


# Intent: the complete discussion #32 capture retains every section and candidate row used by the release plan.
# Why: a trimmed dump could hide missing B509/B516/B524 evidence or make the
#      HMUX0 SW0302 gate pass for the wrong reason.
def test_issue32_dump_keeps_complete_candidate_evidence() -> None:
    dump = load_discovery_dump(ISSUE32_DUMP)
    metadata = dump["metadata"]
    configs = metadata["ebusd_info"]["loaded_configs"]

    assert metadata["dump_version"] == 4
    assert metadata["source"].endswith("/32515826/Discovery.dump.for.vaillant_ebus.txt")
    assert metadata["source_sha256"] == "c891b30640b4c7ba0c8eefc6dc144efd6791e1bd3ba6673cbf9e5fca091a1c24"
    assert configs["08"]["scanned"] == "MF=Vaillant;ID=HMUX0;SW=0302;HW=0504"
    assert configs["15"]["scanned"] == "MF=Vaillant;ID=CTLV3;SW=0808;HW=8004"
    assert configs["76"]["scanned"] == "MF=Vaillant;ID=VWZIO;SW=0302;HW=0504"

    assert len(dump["raw_find_lines"]) == 578
    assert len(dump["raw_find_lines_after"]) == 578
    assert len(dump["before_registers"]) == 706
    assert len(dump["after_registers"]) == 706
    assert len(dump["grab"]) == 202
    assert len(dump["unknown_telegrams"]) == 68
    assert len(dump["labeled_telegrams"]) == 131
    assert any(item["request"] == "f108b509055402005b0d" for item in dump["unknown_telegrams"])
    assert any(item["request"] == "f108b509055402000d0a" for item in dump["unknown_telegrams"])
    assert any(item["request"] == "f108b50905540200c509" for item in dump["unknown_telegrams"])


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


# Intent: new issue captures retain their immutable attachment reference and original content digest.
# Why: dump_version describes the format, while source metadata proves which community capture justified the evidence.
@pytest.mark.parametrize(("fixture", "expected"), NEW_CAPTURE_PROVENANCE.items())
def test_new_capture_provenance_matches_downloaded_attachment(fixture: str, expected: tuple[str, str]) -> None:
    source, source_sha256 = expected
    metadata = load_discovery_dump(fixture)["metadata"]

    assert metadata["source"] == source
    assert metadata["source_sha256"] == source_sha256
