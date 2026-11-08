"""Tests for the re-read table of plain-`r` registers that ebusd never polls."""

from __future__ import annotations

from tests.backend_loader import load_backend

REREAD = load_backend("reread_plan")
MODELS = load_backend("models")


# Intent: build a mini graph with one heat pump that lists `PowerConsumptionHmu`, plus an empty graph.
# Why: the table tests need a graph where exactly one energy-interval rule nominates a read.
def _graphs() -> tuple[object, object]:
    hmu = MODELS.DeviceNode(circuit="hmu", device_type=MODELS.DeviceType.HEAT_PUMP)
    full = MODELS.DeviceGraph(
        nodes={"hmu": hmu}, raw_registers={"hmu.PowerConsumptionHmu": "0.45"}, placeholder_registers=set()
    )
    empty = MODELS.DeviceGraph(nodes={}, raw_registers={}, placeholder_registers=set())
    return full, empty


# Intent: energy-interval rules run only when the energy poll is due, and an empty graph nominates nothing.
# Why: a re-read on every poll would cost bus time the energy counters do not need (#53/#97, #227).
def test_energy_interval_rules_run_only_on_the_energy_poll() -> None:
    full, empty = _graphs()

    assert ("hmu", "PowerConsumptionHmu") in REREAD.plan_rereads(full, {}, include_energy=True)
    assert REREAD.plan_rereads(full, {}, include_energy=False) == []
    assert REREAD.plan_rereads(empty, {}, include_energy=True) == []


# Intent: every rule names the issue that proved it, and the table keeps its planning order.
# Why: the order decides which nomination the planner keeps and the order of reads per circuit; a reordered table
#      would change the plan without any rule changing.
def test_rules_name_their_issue_and_keep_planning_order() -> None:
    issues = [rule.issue for rule in REREAD.REREAD_RULES]

    assert all(issue.startswith("#") for issue in issues)
    assert issues == ["#53/#97/#193/#208", "#227", "#171", "#213", "#207"]
    cadences = [rule.cadence for rule in REREAD.REREAD_RULES]
    assert cadences[:2] == [REREAD.Cadence.ENERGY_INTERVAL] * 2
    assert set(cadences[2:]) == {REREAD.Cadence.EVERY_POLL}


# Intent: only the listed B511/B524/B555 definitions are re-read; other plain-`r` definitions of the same messages and
#         every non-`r` definition are not.
# Why: the mutation check showed the name filters could be dropped without a failing test; dropping them would poll
#      every B524 controller define on the energy interval and cost bus time (#193).
def test_energy_polled_definitions_follow_the_name_filters() -> None:
    polled = REREAD._is_energy_polled_definition
    slot = "r,ctlv2,HwcTimer_Monday1,x,,15,B555,a50002000001," + REREAD.HWC_TIMER_SLOT_FIELDS

    assert polled("r", "z1RoomHumidity", "B524", "")
    assert not polled("r", "Z1DayTemp", "B524", "")
    assert polled("r", "CompressorHc", "B511", "")
    assert not polled("r", "Status01", "B511", "")
    assert polled("r", "HwcTimer_Monday1", "B555", slot)
    assert not polled("r", "HwcTimer_Monday", "B555", "r,ctlv2,HwcTimer_Monday,x,,15,B555,a500,other,,HTM")
    assert not polled("u", "PowerConsumptionHmu", "B516", "")
