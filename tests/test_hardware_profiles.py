"""Table-driven tests for the hardware profile gates and the scan-identity uniqueness check."""

from __future__ import annotations

import pytest

from tests.backend_loader import load_backend

MODELS = load_backend("models")
PROFILES = load_backend("hardware_profiles")


def _node(
    circuit: str = "hmux0",
    device_type: str = "HEAT_PUMP",
    scan_type: str = "HMUX0",
    sw: str = "0407",
    hw: str = "0504",
    address: str = "scan.08",
) -> object:
    return MODELS.DeviceNode(
        circuit=circuit,
        device_type=MODELS.DeviceType[device_type],
        scan_type=scan_type,
        scan_sw=sw,
        scan_hw=hw,
        scan_address=address,
    )


def _row(address: str = "scan.08", scan_type: str = "HMUX0", sw: str = "0407", hw: str = "0504", complete: bool = True):
    return MODELS.ScanIdentity(address=address, scan_type=scan_type, scan_sw=sw, scan_hw=hw, complete=complete)


def _graph(nodes: list, rows: list) -> object:
    return MODELS.DeviceGraph(
        nodes={n.circuit: n for n in nodes}, raw_registers={}, placeholder_registers=set(), scan_identities=tuple(rows)
    )


# Intent: the scan-identity check accepts only one complete, consistent, unique row that equals the node's metadata.
# Why: this check guards every hardware-specific define and read; each branch below is a way stale or conflicting
# scan evidence could otherwise authorise bus traffic.
@pytest.mark.parametrize(
    ("case", "node", "rows", "expected"),
    [
        ("unique match", _node(), [_row()], True),
        ("no scan address", _node(address=""), [_row()], False),
        ("no scan type", _node(scan_type=""), [_row()], False),
        ("no row at all", _node(), [], False),
        ("incomplete row same address", _node(), [_row(), _row(scan_type="OTHER", complete=False)], False),
        ("incomplete row same type", _node(), [_row(), _row(address="scan.09", complete=False)], False),
        ("incomplete row elsewhere is ignored", _node(), [_row(), _row("scan.15", "BASV3", "1", "2", False)], True),
        ("conflicting firmware", _node(), [_row(), _row(sw="0302")], False),
        ("conflicting firmware, node has the other value", _node(sw="0302"), [_row(), _row(sw="0302")], False),
        ("conflicting hardware", _node(), [_row(), _row(hw="0403")], False),
        ("conflicting hardware, node has the other value", _node(hw="0403"), [_row(), _row(hw="0403")], False),
        ("type present at two addresses", _node(), [_row(), _row(address="scan.09")], False),
        ("two types at one address", _node(), [_row(), _row(scan_type="OTHER")], False),
        ("node firmware differs from scan", _node(sw="0303"), [_row()], False),
        ("node hardware differs from scan", _node(hw="0403"), [_row()], False),
        ("case differences are ignored", _node(scan_type="hmux0", address="SCAN.08"), [_row()], True),
        ("unrelated device is fine", _node(), [_row(), _row("scan.15", "BASV3", "0708", "4304")], True),
    ],
)
def test_scan_identity_uniqueness_table(case: str, node: object, rows: list, expected: bool) -> None:
    graph = _graph([node], rows)

    assert PROFILES.has_current_unique_scan_identity(graph, node) is expected, case


# Intent: a profile owner is returned only for the right role, address, firmware and a unique node.
# Why: a firmware match on the wrong device role or a second matching node must not pick a circuit.
@pytest.mark.parametrize(
    ("case", "profile", "nodes", "expected"),
    [
        ("HMUX0 SW0407 match", PROFILES.HMUX0_SW0407, [_node()], "hmux0"),
        ("other firmware", PROFILES.HMUX0_SW0407, [_node(sw="0406")], None),
        ("other hardware", PROFILES.HMUX0_SW0407, [_node(hw="0403")], None),
        ("wrong device role", PROFILES.HMUX0_SW0407, [_node(device_type="HEATING_CONTROLLER")], None),
        ("two matching nodes", PROFILES.HMUX0_SW0407, [_node(), _node(circuit="hmu", address="scan.09")], None),
        (
            "VWZIO needs scan.76",
            PROFILES.VWZIO_SW0500,
            [_node("vwzio", "PASSIVE_COOLING", "VWZIO", "0500", address="scan.76")],
            "vwzio",
        ),
        (
            "VWZIO at other address",
            PROFILES.VWZIO_SW0500,
            [_node("vwzio", "PASSIVE_COOLING", "VWZIO", "0500", address="scan.75")],
            None,
        ),
        (
            "VWZ station prefix, any firmware",
            PROFILES.VWZ_STATION_76,
            [_node("vwz", "PASSIVE_COOLING", "VWZ00", "0303", "5103", "scan.76")],
            "vwz",
        ),
        (
            "VWZ station other address",
            PROFILES.VWZ_STATION_76,
            [_node("vwz", "PASSIVE_COOLING", "VWZ00", "0303", "5103", "scan.75")],
            None,
        ),
    ],
)
def test_profile_owner_table(case: str, profile: object, nodes: list, expected: str | None) -> None:
    rows = [_row(n.scan_address, n.scan_type, n.scan_sw, n.scan_hw) for n in nodes]
    graph = _graph(nodes, rows)

    assert PROFILES.profile_owner(graph, profile) == expected, case
    assert PROFILES.profile_owner(None, profile) is None


# Intent: firmware sets of the multi-revision profiles are exactly the evidenced revisions.
# Why: adding a revision needs a capture and a gate test; this pins the table so a silent edit fails here.
@pytest.mark.parametrize(
    ("profile", "accepted", "rejected"),
    [
        (PROFILES.HMUX0_PRECISE_TEMPERATURE, ["0303", "0406"], ["0302", "0407"]),
        (PROFILES.HMUX0_B509_MONITORING, ["0302", "0303"], ["0406", "0407"]),
        (PROFILES.HMUX0_SW0303, ["0303"], ["0302", "0406", "0407"]),
    ],
)
def test_hmux0_firmware_sets_are_pinned(profile: object, accepted: list[str], rejected: list[str]) -> None:
    for sw in accepted:
        assert profile.matches_scan("HMUX0", sw, "0504")
        assert not profile.matches_scan("HMUX0", sw, "0403")
    for sw in rejected:
        assert not profile.matches_scan("HMUX0", sw, "0504")
    assert not profile.matches_scan("HMU00", accepted[0], "0504")


# Intent: a scan row only authorises a profile when it is complete and in the profile's firmware set.
# Why: HMUX0 ownership comes from scan rows, and a partial row must fail closed.
def test_scan_matches_requires_complete_row() -> None:
    assert PROFILES.scan_matches(PROFILES.HMUX0_SW0303, _row(sw="0303"))
    assert not PROFILES.scan_matches(PROFILES.HMUX0_SW0303, _row(sw="0303", complete=False))
    assert not PROFILES.scan_matches(PROFILES.HMUX0_SW0303, _row(sw="0406"))
