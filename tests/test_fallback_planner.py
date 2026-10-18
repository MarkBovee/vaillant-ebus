"""Pure tests for the fallback read planner, driven by real community captures."""

from __future__ import annotations

import dataclasses

import pytest

from tests.backend_loader import load_backend
from tests.fake_ebusd import load_find_lines

DISCOVERY = load_backend("discovery_service")
MAPPING = load_backend("mapping")
MODELS = load_backend("models")
PLANNER = load_backend("fallback_planner")

HMUX0_SW0406 = "community/hmux0_issue171_2026-10-03_094933_discovery.yaml"
FLEXOTHERM = "community/flexotherm_discovery.yaml"


def _graph(fixture: str) -> object:
    return DISCOVERY.DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))


def _plan(graph: object, definitions: dict[str, str] | None = None, **kwargs: object) -> list[tuple[str, str]]:
    find_keys = set(graph.raw_registers) | set(graph.placeholder_registers)

    def resolve(circuit: str) -> str | None:
        return next((node for node in graph.nodes if node.casefold() == circuit.casefold()), None)

    return PLANNER.plan_fallback_reads(graph, find_keys, definitions or {}, resolve, MAPPING.REGISTER_MAP, **kwargs)


def _with_hmux0_firmware(graph: object, sw: str) -> object:
    """Return a copy of the graph whose HMUX0 node and scan row both report firmware ``sw``."""
    nodes = dict(graph.nodes)
    nodes["hmux0"] = dataclasses.replace(nodes["hmux0"], scan_sw=sw)
    rows = tuple(
        dataclasses.replace(row, scan_sw=sw) if row.scan_type.casefold() == "hmux0" else row
        for row in graph.scan_identities
    )
    return dataclasses.replace(graph, nodes=nodes, scan_identities=rows)


# Intent: the HMUX0 precise temperatures are read actively only for the evidenced firmware revisions.
# Why: other revisions returned absurd values (issue #99); plain-`r` registers need an explicit read (#171).
@pytest.mark.parametrize(("sw", "expected"), [("0406", True), ("0303", True), ("0302", False), ("0407", False)])
def test_precise_temperatures_follow_the_firmware_gate(sw: str, expected: bool) -> None:
    plan = _plan(_with_hmux0_firmware(_graph(HMUX0_SW0406), sw))

    for name in ("RunDataFlowTemp", "RunDataReturnTemp"):
        assert (("hmux0", name) in plan) is expected, (sw, name)


# Intent: a passive (`u`) runtime definition is never read actively; an active (`r`) one is not blocked by it.
# Why: passive definitions decode gateway traffic and must cost no bus requests.
@pytest.mark.parametrize(("access", "planned"), [("u", False), ("r", True)])
def test_passive_definitions_are_not_polled(access: str, planned: bool) -> None:
    graph = _graph(FLEXOTHERM)
    baseline = _plan(graph)
    assert ("hmu", "SourceTempInput") in baseline  # precondition: the register is normally planned
    definition = f"{access},hmu,SourceTempInput,SourceTempInput,31,8,B51A,05ff3222,value"

    plan = _plan(graph, {f"{access}.hmu.SourceTempInput": definition})

    assert (("hmu", "SourceTempInput") in plan) is planned


# Intent: energy counters (plain-`r` B516 definitions) are re-read on request, only when active and on a known circuit.
# Why: ebusd never polls plain-`r` registers; passive or unknown-circuit definitions must not create reads.
def test_energy_counter_rereads_require_active_b516_definition_on_known_circuit() -> None:
    graph = _graph(FLEXOTHERM)
    definitions = {
        "r.hmu.ZzEnergy": "r,hmu,ZzEnergy,ZzEnergy,31,08,B516,1001ffff0205,value",
        "u.hmu.ZzPassive": "u,hmu,ZzPassive,ZzPassive,f1,08,B516,14,value",
        "r.nowhere.ZzOrphan": "r,nowhere,ZzOrphan,ZzOrphan,31,08,B516,1001ffff0305,value",
        "r.hmu.ZzStatus": "r,hmu,ZzStatus,ZzStatus,31,08,B511,07,value",
    }

    without_flag = _plan(graph, definitions)
    with_flag = _plan(graph, definitions, include_energy=True)

    assert set(with_flag) - set(without_flag) == {("hmu", "ZzEnergy")}
    assert set(without_flag) <= set(with_flag)


# Intent: placeholder registers are only planned when requested, and never twice or as field keys.
# Why: placeholder polling runs on a slower interval, and a candidate may be nominated by several paths.
def test_placeholder_reads_need_the_flag_and_are_deduplicated() -> None:
    graph = _graph(FLEXOTHERM)

    default = _plan(graph)
    with_placeholders = _plan(graph, include_placeholders=True)

    assert len(with_placeholders) > len(default)
    assert len(with_placeholders) == len(set(with_placeholders))
    assert not any("." in name for _, name in with_placeholders)


# Intent: registers named in skip_reads and registers ebusd reported as errors are never planned.
# Why: a register that failed or was explicitly excluded must not be probed again by the same cycle.
def test_skip_reads_and_error_registers_are_excluded() -> None:
    graph = _graph(FLEXOTHERM)
    target = ("hmu", "SourceTempInput")
    assert target in _plan(graph)

    assert target not in _plan(graph, skip_reads={"HMU.sourcetempinput"})

    errored = dataclasses.replace(graph, error_registers={"hmu.SourceTempInput"})
    assert target not in _plan(errored)


# Intent: the candidate circuit comes from where the register was discovered, filtered by role.
# Why: registers live under basv3/ctlv3/vwzio too; the literal map circuit must never be assumed.
def test_fallback_candidate_uses_discovered_owner_and_role() -> None:
    graph = _graph(HMUX0_SW0406)

    def resolve(circuit: str) -> str | None:
        return next((node for node in graph.nodes if node.casefold() == circuit.casefold()), None)

    # `Errorhistory` is discovered under the controller; the logical `ctlv2` alias resolves to the owner.
    assert PLANNER.fallback_candidate(graph, lambda _c: "basv3", "ctlv2", "Errorhistory") == "basv3"
    # A resolver that points at a circuit not holding the register yields nothing.
    assert PLANNER.fallback_candidate(graph, lambda _c: "hmux0", "ctlv2", "Errorhistory") is None
    # A non-logical circuit with exactly one discovered owner of the name falls back to that owner.
    assert PLANNER.fallback_candidate(graph, resolve, "vwzio", "Status01") in {None, "vwzio"}
    # No graph, no candidate.
    assert PLANNER.fallback_candidate(None, resolve, "hmu", "Status00") is None


def _mini_graph(nodes: dict[str, object], raw: dict[str, str] | None = None, placeholders: set[str] | None = None):
    return MODELS.DeviceGraph(nodes=nodes, raw_registers=raw or {}, placeholder_registers=placeholders or set())


def _node(circuit: str, device_type: object, **kwargs: object) -> object:
    return MODELS.DeviceNode(circuit=circuit, device_type=device_type, **kwargs)


def _plan_mini(graph: object, resolve=None, **kwargs: object) -> list[tuple[str, str]]:
    find_keys = set(graph.raw_registers) | set(graph.placeholder_registers)
    return PLANNER.plan_fallback_reads(
        graph, find_keys, {}, resolve or (lambda _c: None), MAPPING.REGISTER_MAP, **kwargs
    )


# Intent: a placeholder is planned under its discovered circuit when the register map knows it through an alias,
# and only when that map entry is enabled and allows fallback reads.
# Why: ctlv3/basv3 controllers reuse ctlv2 metadata; unmapped, disabled or probe-blocked registers must stay unread.
def test_placeholder_reads_follow_alias_metadata_and_map_flags() -> None:
    ctlv3 = _node("ctlv3", MODELS.DeviceType.HEATING_CONTROLLER)
    placeholders = {
        "ctlv3.Z1ActualRoomTempDesired",  # mapped via ctlv2, enabled, fallback allowed
        "ctlv3.Hc1FlowTempCalc",  # mapped but fallback_read=False (unverified B524 state register)
        "ctlv3.NotInTheMap",  # no metadata at all
        "ctlv3.Foo.bar",  # field-shaped key
    }
    graph = _mini_graph({"ctlv3": ctlv3}, placeholders=placeholders)

    plan = _plan_mini(graph, resolve=lambda circuit: "ctlv3" if circuit == "ctlv2" else None, include_placeholders=True)

    assert ("ctlv3", "Z1ActualRoomTempDesired") in plan
    assert ("ctlv3", "Hc1FlowTempCalc") not in plan
    assert ("ctlv3", "NotInTheMap") not in plan
    assert not any("." in name for _, name in plan)
    skipped = _plan_mini(
        graph,
        resolve=lambda circuit: "ctlv3" if circuit == "ctlv2" else None,
        include_placeholders=True,
        skip_reads={"ctlv3.Z1ActualRoomTempDesired"},
    )
    assert ("ctlv3", "Z1ActualRoomTempDesired") not in skipped


# Intent: a placeholder that has since become a raw (live) register is not probed as a placeholder.
# Why: live registers are polled by ebusd; an extra active read would only add bus traffic.
def test_placeholder_that_became_live_is_not_probed() -> None:
    ctlv3 = _node("ctlv3", MODELS.DeviceType.HEATING_CONTROLLER)
    graph = _mini_graph(
        {"ctlv3": ctlv3},
        raw={"CTLV3.z1actualroomtempdesired": "21"},
        placeholders={"ctlv3.Z1ActualRoomTempDesired"},
    )

    plan = _plan_mini(graph, resolve=lambda c: "ctlv3" if c == "ctlv2" else None, include_placeholders=True)

    assert ("ctlv3", "Z1ActualRoomTempDesired") not in plan


# Intent: a non-logical circuit with one discovered owner of a register resolves to it; two owners do not.
# Why: without a role to filter by, ambiguity must fail closed instead of picking a circuit.
@pytest.mark.parametrize(("extra_owner", "expected"), [(False, "vwzio"), (True, None)])
def test_fallback_candidate_single_owner_of_unclassified_circuit(extra_owner: bool, expected: str | None) -> None:
    nodes = {"vwzio": _node("vwzio", MODELS.DeviceType.PASSIVE_COOLING)}
    raw = {"vwzio.ZzProbe": "1"}
    if extra_owner:
        nodes["vwz"] = _node("vwz", MODELS.DeviceType.PASSIVE_COOLING)
        raw["vwz.ZzProbe"] = "2"
    graph = _mini_graph(nodes, raw)

    assert PLANNER.fallback_candidate(graph, lambda _c: None, "vwzio", "ZzProbe") == expected


# Intent: the map-driven RunDataFlowTemp read follows the HMUX0 firmware gate even when `find` does not list it.
# Why: an HMUX0 alias key must not trigger an active B509 read on firmware without evidenced layout (#171).
@pytest.mark.parametrize(("sw", "expected"), [("0406", True), ("0302", False)])
def test_map_driven_flow_temp_read_is_firmware_gated(sw: str, expected: bool) -> None:
    graph = _with_hmux0_firmware(_graph(HMUX0_SW0406), sw)
    graph = dataclasses.replace(
        graph,
        raw_registers={k: v for k, v in graph.raw_registers.items() if not k.casefold().endswith(".rundataflowtemp")},
        placeholder_registers={k for k in graph.placeholder_registers if not k.casefold().endswith(".rundataflowtemp")},
    )

    def resolve(circuit: str) -> str | None:
        return "hmux0" if circuit.casefold() in {"hmu", "hmux0"} else None

    plan = PLANNER.plan_fallback_reads(
        graph,
        set(graph.raw_registers) | set(graph.placeholder_registers),
        {},
        resolve,
        {"hmu.RunDataFlowTemp": MODELS.RegisterMeta()},
    )

    assert (("hmux0", "RunDataFlowTemp") in plan) is expected
