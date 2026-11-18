"""Tests for the HMUX0 SW0406 active definitions of issue #205."""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.backend_loader import load_backend
from tests.fake_ebusd import load_find_lines

DISCOVERY = load_backend("discovery_service")
MAPPING = load_backend("mapping")
PLANNER = load_backend("fallback_planner")
REREAD = load_backend("reread_plan")
RUNTIME = load_backend("runtime_definitions")

# Two SW0406/HW0504 units on a stock ebusd configuration (issue #205 and discussion #31, 2026-11-17).
SW0406_STOCK = (
    "community/hmux0_sw0406_issue205_2026-11-17_155315_discovery.yaml",
    "community/hmux0_sw0406_discussion31_2026-11-17_153929_discovery.yaml",
)
# The telegrams both reporters sent with `ebusctl hex`, which answered plausible values while running and idle.
REPORTER_REQUESTS = {
    "BuildingCircuitFlow": "08b51a0405ff323c",
    "RunDataFlowTempDesired": "08b509055402004a0d",
    "RunDataCondensorOutletTemp": "08b50905540200b608",
    "EnergyIntegral": "08b51a0405ff3221",
}


# Intent: build the device graph and the runtime definitions of a fixture, keyed like the coordinator keys them.
# Why: every test looks at what the integration defines and then plans for that capture.
def _graph_and_defines(fixture: str) -> tuple[object, dict[str, str]]:
    graph = DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture))
    defines = RUNTIME.build_runtime_defines(graph, datetime(2026, 11, 17))
    return graph, {f"{d.split(',')[1]}.{d.split(',')[2]}": d for d in defines}


# Intent: run only the SW0406 rule of the re-read table.
# Why: the absent test must prove that this rule nominates nothing, separately from the SW0407 rule.
def _sw0406_rule_reads(graph: object, defines: dict[str, str]) -> list[tuple[str, str]]:
    rule = next(rule for rule in REREAD.REREAD_RULES if rule.issue == "#205 SW0406")
    return rule.nominate(graph, defines)

# Intent: on both SW0406 stock captures the four definitions target the HMUX0 circuit, and each id rebuilds exactly the
#         telegram the reporters sent (the id never holds the length byte).
# Why: issue #205 - the registers are only proven by those replies; a wrong id or circuit stays unavailable silently.
@pytest.mark.parametrize("fixture", SW0406_STOCK)
def test_sw0406_stock_capture_defines_the_issue205_registers(fixture: str) -> None:
    _graph, defines = _graph_and_defines(fixture)

    for name, request in REPORTER_REQUESTS.items():
        definition = defines[f"hmux0.{name}"]
        access, circuit, _, _, _, zz, pbsb, data = definition.split(",")[:8]
        assert (access, circuit) == ("r", "hmux0")
        assert f"{zz}{pbsb}{len(data) // 2:02x}{data}".casefold() == request
    assert ",SIN,,°min," in defines["hmux0.EnergyIntegral"]
    assert ",EXP,,°C," in defines["hmux0.RunDataFlowTempDesired"]


# Intent: the planner reads the four registers on every poll on the SW0406 owner, through the normal `_add` gate.
# Why: they are plain `r` definitions, so without a re-read they would freeze at the first value (the #213 lesson).
@pytest.mark.parametrize("fixture", SW0406_STOCK)
def test_sw0406_registers_are_read_every_poll(fixture: str) -> None:
    graph, defines = _graph_and_defines(fixture)
    find_keys = set(graph.raw_registers) | set(graph.placeholder_registers)

    # Intent: resolve a circuit name to the node the graph actually holds.
    # Why: it mirrors the coordinator's alias resolution, so the test never assumes a literal circuit.
    def resolve(circuit: str) -> str | None:
        return next((node for node in graph.nodes if node.casefold() == circuit.casefold()), None)

    plan = PLANNER.plan_fallback_reads(graph, find_keys, defines, resolve, MAPPING.REGISTER_MAP, include_energy=False)

    assert {("hmux0", name) for name in REPORTER_REQUESTS} <= set(plan)


# Intent: SW0406 with ebusd's own hmux0 CSV, SW0407 and SW0303 captures get none of the new SW0406 definitions
#         (SW0407 keeps only its own building circuit flow), and the planner nominates none of them there.
# Why: the layouts are proven on SW0406 stock buses only; a loaded CSV already defines its own names (#171).
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("community/hmux0_sw0406_issue186_2026-10-11_143454_discovery.yaml", set()),
        ("community/hmux0_sw0407_issue175_2026-10-09_115534_discovery.yaml", {"BuildingCircuitFlow"}),
        ("community/hmux0_issue171_2026-10-03_094933_discovery.yaml", set()),
    ],
)
def test_issue205_definitions_absent_on_other_revisions(fixture: str, expected: set[str]) -> None:
    graph, defines = _graph_and_defines(fixture)
    defined = {key.split(".", 1)[1] for key in defines if key.split(".", 1)[1] in REPORTER_REQUESTS}
    sw0406_reads = _sw0406_rule_reads(graph, defines)

    assert defined == expected
    assert sw0406_reads == []
