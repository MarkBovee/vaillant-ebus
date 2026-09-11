"""Tests for DiscoveryService — device graph construction from ebusd find output."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

from tests.fake_ebusd import FakeEbusdServer, load_find_lines

BACKEND_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend"
COMPONENT_PATH = BACKEND_PATH.parent

for name in ("vaillant_ebus", "vaillant_ebus.backend"):
    pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    pkg.__path__ = [str(COMPONENT_PATH)] if name == "vaillant_ebus" else [str(BACKEND_PATH)]
    sys.modules[name] = pkg

MODELS_SPEC = importlib.util.spec_from_file_location("vaillant_ebus.backend.models", BACKEND_PATH / "models.py")
assert MODELS_SPEC and MODELS_SPEC.loader
MODELS = importlib.util.module_from_spec(MODELS_SPEC)
sys.modules["vaillant_ebus.backend.models"] = MODELS
MODELS_SPEC.loader.exec_module(MODELS)

EBUS_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.ebus_service", BACKEND_PATH / "ebus_service.py"
)
assert EBUS_SPEC and EBUS_SPEC.loader
EBUS_MOD = importlib.util.module_from_spec(EBUS_SPEC)
sys.modules["vaillant_ebus.backend.ebus_service"] = EBUS_MOD
EBUS_SPEC.loader.exec_module(EBUS_MOD)
EbusService = EBUS_MOD.EbusService

DISCOVERY_SPEC = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.discovery_service", BACKEND_PATH / "discovery_service.py"
)
assert DISCOVERY_SPEC and DISCOVERY_SPEC.loader
DISCOVERY = importlib.util.module_from_spec(DISCOVERY_SPEC)
sys.modules["vaillant_ebus.backend.discovery_service"] = DISCOVERY
DISCOVERY_SPEC.loader.exec_module(DISCOVERY)

DiscoveryService = DISCOVERY.DiscoveryService
DeviceGraph = DISCOVERY.DeviceGraph
DeviceNode = DISCOVERY.DeviceNode
DeviceType = DISCOVERY.DeviceType
match_scan_to_circuits = DISCOVERY._match_scan_to_circuits

AROTHERM_LINES = load_find_lines("arotherm_find.txt")
COMMUNITY_BASV = load_find_lines("community/basv_find.txt")
COMMUNITY_V32 = load_find_lines("community/v32_find.txt")
COMMUNITY_MULTIZONE_SINGLE_CIRCUIT = load_find_lines("community/multizone_single_circuit_find.txt")
FLEXOTHERM_LINES = load_find_lines("community/flexotherm_discovery.yaml")
AROTHERM_PLUS_2ZONE_LINES = load_find_lines("community/arotherm_plus_2zone_discovery.yaml")
AROTHERM_PLUS_BASV3_LINES = load_find_lines("community/arotherm_plus_basv3_discovery.yaml")
AROTHERM_PRO7_LINES = load_find_lines("community/arotherm_pro7_discovery.yaml")
FLEXOCOMPACT_LINES = load_find_lines("community/flexocompact_find.txt")
AROTHERM_ECOTEC_LINES = load_find_lines("community/arotherm_ecotec_discovery.yaml")


# Intent: scan type VR71 binds to the vr_71 circuit despite the underscore.
# Why: circuit names use underscores while scan IDs do not, so normalization must not drop the pairing.
def test_scan_matching_normalizes_prefix_underscores() -> None:
    result = match_scan_to_circuits(
        [("26", "VR71", "0100", "5904")],
        {"vr_71": ["vr_71.Mc1Operation"]},
    )
    assert result["vr_71"] == ("VR71", "0100", "5904")


# =============================================================================
# A2. Scan metadata ↔ circuit matching (unit tests)
# =============================================================================


# Intent: each supported controller/heat-pump family binds its exact scan name.
# Why: a normalization regression would detach scan metadata from a whole device family.
@pytest.mark.parametrize(
    ("circuit", "scan_type"),
    [
        ("hmux0", "HMUX0"),
        ("ctlv3", "CTLV3"),
        ("hmu", "HMU"),
        ("basv", "BASV"),
        ("ctlv2", "CTLV2"),
        ("basv2", "BASV2"),
        ("bass3", "BASS3"),
    ],
)
def test_scan_matching_exact_normalized_names(circuit: str, scan_type: str) -> None:
    result = match_scan_to_circuits(
        [("08", scan_type, "0102", "0304")],
        {circuit: [f"{circuit}.SomeRegister"]},
    )
    assert result[circuit] == (scan_type, "0102", "0304")


# Intent: a CTLV3 scan binds to the ctl_v3 circuit through normalization.
# Why: mixed-separator circuit names must still receive their scan identity.
def test_scan_matching_underscore_normalization() -> None:
    result = match_scan_to_circuits(
        [("15", "CTLV3", "0808", "8004")],
        {"ctl_v3": ["ctl_v3.Z1OpMode"]},
    )
    assert result["ctl_v3"] == ("CTLV3", "0808", "8004")


# Intent: a numbered scan variant matches its base circuit name.
# Why: ebusd appends a hardware revision to the scan type; the base circuit must still bind.
@pytest.mark.parametrize(
    ("circuit", "scan_type"),
    [
        ("hmu", "HMU00"),
        ("basv", "BASV2"),
        ("vwz", "VWZ00"),
        ("bai", "BAI00"),
        ("sol00", "SOL00"),
    ],
)
def test_scan_matching_family_variant_number_on_scan_only(circuit: str, scan_type: str) -> None:
    result = match_scan_to_circuits(
        [("08", scan_type, "0101", "0202")],
        {circuit: [f"{circuit}.SomeRegister"]},
    )
    assert result[circuit] == (scan_type, "0101", "0202")


# Intent: a bare scan type matches a circuit that carries the variant number.
# Why: the revision suffix may appear on either side and must still pair.
def test_scan_matching_family_variant_number_on_circuit_only() -> None:
    result = match_scan_to_circuits(
        [("15", "BASV", "0507", "1704")],
        {"basv2": ["basv2.HwcTempDesired"]},
    )
    assert result["basv2"] == ("BASV", "0507", "1704")


# Intent: two sibling circuits of one scan family stay unmatched.
# Why: guessing metadata for basv/basv2 would mis-attribute registers to the wrong device.
def test_scan_matching_rejects_ambiguous_family_circuits() -> None:
    """Two sibling circuits of one scan family must not receive guessed metadata."""
    result = match_scan_to_circuits(
        [("15", "BASV3", "0708", "4304")],
        {
            "basv": ["basv.HwcTempDesired"],
            "basv2": ["basv2.HwcTempDesired"],
        },
    )
    assert "basv" not in result
    assert "basv2" not in result


# Intent: one circuit facing two same-family scans stays unmatched.
# Why: ambiguous scan variants must not be resolved by line order.
def test_scan_matching_rejects_ambiguous_family_scans() -> None:
    """One circuit with two same-family scan variants stays unmatched."""
    result = match_scan_to_circuits(
        [("15", "CTLV2", "0514", "1104"), ("16", "CTLV3", "0808", "8004")],
        {"ctlv": ["ctlv.Z1OpMode"]},
    )
    assert "ctlv" not in result


# Intent: a scan bound to hmu does not also bind to sibling hmux0.
# Why: sharing metadata would make the wrong device inherit scan identity.
def test_scan_matching_does_not_reuse_claimed_scan_for_sibling_circuit() -> None:
    """A scan exactly/family-bound to one circuit must not leak to a sibling."""
    result = match_scan_to_circuits(
        [("08", "HMU00", "0901", "5103")],
        {
            "hmu": ["hmu.FlowTemp"],
            "hmux0": ["hmux0.RunDataReturnTemp"],
        },
    )
    assert result["hmu"] == ("HMU00", "0901", "5103")
    assert "hmux0" not in result


# Intent: HMUX0 scan metadata never binds to the differently named hmu circuit.
# Why: hmux0 and hmu are distinct hardware variants and must not cross-match.
def test_scan_matching_does_not_cross_hmu_hmux_families() -> None:
    """HMUX0 scan metadata must not bind to the differently-named hmu circuit."""
    result = match_scan_to_circuits(
        [("08", "HMUX0", "0303", "0504")],
        {"hmu": ["hmu.FlowTemp"]},
    )
    assert "hmu" not in result


# Intent: a scan-only HMUX0 line creates an empty heat-pump node.
# Why: runtime-defined registers need the HMUX0 node before find returns registers.
def test_scan_only_hmux0_creates_heat_pump_node_for_runtime_bootstrap() -> None:
    graph = DiscoveryService.build_device_graph(["scan.08 = Vaillant;HMUX0;0303;0504", "ctlv3 HwcOpMode = auto"])

    hmux0 = graph.nodes["hmux0"]
    assert hmux0.device_type == DeviceType.HEAT_PUMP
    assert hmux0.registers == []
    assert (hmux0.scan_type, hmux0.scan_sw, hmux0.scan_hw) == ("HMUX0", "0303", "0504")


# Intent: conflicting HMUX0 scan identities produce no node.
# Why: two hardware revisions on one address must not be silently merged.
def test_scan_only_hmux0_rejects_conflicting_identity() -> None:
    graph = DiscoveryService.build_device_graph(
        [
            "scan.08 = Vaillant;HMUX0;0303;0504",
            "scan.08 = Vaillant;HMUX0;0406;0504",
            "ctlv3 HwcOpMode = auto",
        ]
    )

    assert "hmux0" not in graph.nodes


# Intent: an HMUX0 scan classifies the node as heat pump despite a generic hmu alias.
# Why: the real hardware variant must win over a stale generic alias.
def test_scan_only_hmux0_overrides_generic_hmu_alias_circuit() -> None:
    graph = DiscoveryService.build_device_graph(
        [
            "scan.08 = Vaillant;HMUX0;0303;0504",
            "hmu YieldTotal =  (ERR: invalid position)",
            "ctlv3 HwcOpMode = auto",
        ]
    )

    assert graph.nodes["hmux0"].device_type == DeviceType.HEAT_PUMP


# Intent: generic hmu alias registers are dropped and ctlv3 is reparented to hmux0.
# Why: stray hmu records would create a phantom heat-pump device.
def test_scan_only_hmux0_suppresses_generic_hmu_alias_records() -> None:
    graph = DiscoveryService.build_device_graph(
        [
            "scan.08 = Vaillant;HMUX0;0303;0504",
            "hmu YieldTotal = 1234",
            "ctlv3 HwcOpMode = auto",
        ]
    )

    assert "hmu" not in graph.nodes
    assert "hmu.YieldTotal" not in graph.raw_registers
    assert graph.nodes["ctlv3"].parent == "hmux0"


# Intent: a separately scanned HMU00 keeps its own heat-pump node.
# Why: legitimately present hmu hardware must not be suppressed by HMUX0.
def test_scan_only_hmux0_keeps_separately_scanned_hmu() -> None:
    graph = DiscoveryService.build_device_graph(
        [
            "scan.08 = Vaillant;HMUX0;0303;0504",
            "scan.09 = Vaillant;HMU00;0901;5103",
            "hmu YieldTotal = 1234",
        ]
    )

    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP


# Intent: two sibling circuits each bind to their own distinct scan.
# Why: HMU00 and HMUX0 can coexist and must not steal each other's metadata.
def test_scan_matching_sibling_circuits_each_get_own_scan() -> None:
    result = match_scan_to_circuits(
        [("08", "HMU00", "0901", "5103"), ("08", "HMUX0", "0303", "0504")],
        {
            "hmu": ["hmu.FlowTemp"],
            "hmux0": ["hmux0.RunDataReturnTemp"],
        },
    )
    assert result["hmu"] == ("HMU00", "0901", "5103")
    assert result["hmux0"] == ("HMUX0", "0303", "0504")


# Intent: an unknown scan type binds to no known circuit.
# Why: unknown hardware must not inherit metadata from hmu or ctlv2.
def test_scan_matching_unknown_scan_type_does_not_leak() -> None:
    result = match_scan_to_circuits(
        [("01", "XYZ01", "1234", "5678")],
        {
            "hmu": ["hmu.FlowTemp"],
            "ctlv2": ["ctlv2.Z1OpMode"],
        },
    )
    assert result == {}


# Intent: an unknown scan type still binds to a circuit named after its family.
# Why: genuinely new hardware stays discoverable without code changes.
def test_scan_matching_unknown_scan_type_matches_own_circuit() -> None:
    result = match_scan_to_circuits(
        [("01", "XYZ01", "1234", "5678")],
        {"xyz": ["xyz.Status"]},
    )
    assert result["xyz"] == ("XYZ01", "1234", "5678")


# Intent: duplicate identical scan entries resolve deterministically.
# Why: repeated find output must not change metadata resolution.
def test_scan_matching_duplicate_identical_entries_are_deterministic() -> None:
    entries = [
        ("15", "CTLV3", "0808", "8004"),
        ("15", "CTLV3", "0808", "8004"),
        ("08", "HMUX0", "0303", "0504"),
        ("08", "HMUX0", "0303", "0504"),
    ]
    circuits = {"hmux0": ["hmux0.Status01"], "ctlv3": ["ctlv3.Z1OpMode"]}
    result = match_scan_to_circuits(entries, circuits)
    assert result["ctlv3"] == ("CTLV3", "0808", "8004")
    assert result["hmux0"] == ("HMUX0", "0303", "0504")


# Intent: conflicting duplicate metadata stays unmatched in either order.
# Why: conflicting hardware revisions must not be resolved by line order.
def test_scan_matching_conflicting_duplicate_metadata_is_unmatched_in_any_order() -> None:
    entries = [("08", "HMUX0", "0303", "0504"), ("08", "HMUX0", "0406", "0504")]
    circuits = {"hmux0": ["hmux0.Status01"]}

    first = match_scan_to_circuits(entries, circuits)
    second = match_scan_to_circuits(list(reversed(entries)), circuits)

    assert first == {}
    assert second == {}


# Intent: compatible duplicate entries merge their missing SW/HW fields.
# Why: a partially reported scan line must not discard a complete one.
def test_scan_matching_compatible_duplicate_metadata_merges_missing_fields() -> None:
    result = match_scan_to_circuits(
        [("08", "HMUX0", "", "0504"), ("08", "HMUX0", "0303", "0504")],
        {"hmux0": ["hmux0.Status01"]},
    )

    assert result["hmux0"] == ("HMUX0", "0303", "0504")


# Intent: ambiguous devices get no parent regardless of node order.
# Why: order-dependent parenting would attach a controller to the wrong device.
def test_relationships_do_not_select_first_parent_for_ambiguous_devices() -> None:
    first = DiscoveryService.build_device_graph(
        ["hmu FlowTemp = 35", "hmux0 FlowTemp = 36", "ctlv3 Z1OpMode = day", "ctlv4 Z1OpMode = day"]
    )
    second = DiscoveryService.build_device_graph(
        ["ctlv4 Z1OpMode = day", "ctlv3 Z1OpMode = day", "hmux0 FlowTemp = 36", "hmu FlowTemp = 35"]
    )

    assert first.nodes["ctlv3"].parent is None
    assert first.nodes["ctlv4"].parent is None
    assert second.nodes["ctlv3"].parent is None
    assert second.nodes["ctlv4"].parent is None


# Intent: heat_pump() returns None when two heat-pump candidates exist.
# Why: an ambiguous heat pump must not be chosen by dict order.
def test_heat_pump_resolution_does_not_depend_on_node_order() -> None:
    first = DeviceGraph(
        nodes={
            "hmux0": DeviceNode("hmux0", DeviceType.HEAT_PUMP, scan_type="HMUX0"),
            "hmu": DeviceNode("hmu", DeviceType.HEAT_PUMP, scan_type="HMU00"),
        },
        raw_registers={},
        placeholder_registers=set(),
    )
    second = DeviceGraph(
        nodes=dict(reversed(list(first.nodes.items()))),
        raw_registers={},
        placeholder_registers=set(),
    )

    assert first.heat_pump() is None
    assert second.heat_pump() is None


# Issue #99: runtime-defined registers can expose a bare ctlv2 circuit while
# the real DHW/heating controller is ctlv3. The controller that owns the
# control registers must win so DHW entities read ctlv3 values.
# Intent: the controller owning Hwc* control registers wins over a bare ctlv2 node.
# Why: issue #99 - DHW entities must read ctlv3 values, not a stale runtime ctlv2 alias.
def test_heating_controller_prefers_control_register_owner_over_bare_ctlv2() -> None:
    graph = DiscoveryService.build_device_graph(
        [
            "scan.15 = Vaillant;CTLV3;0808;8004",
            "ctlv3 HwcOpMode = auto",
            "ctlv3 HwcTempDesired = 48",
            "ctlv3 HwcStorageTemp = 45",
            "ctlv2 z1RoomHumidity = 53",
            "ctlv2 ManualCoolingStartDate = 01.01.2019",
        ]
    )

    assert graph.heating_controller_result().circuit == "ctlv3"
    assert graph.resolve_circuit_result("ctlv2").circuit == "ctlv3"


# A genuine ctlv2 that owns the control registers must still resolve to itself.
# Intent: a ctlv2 that owns the control registers stays the resolved controller.
# Why: the override must not break genuine ctlv2 hardware.
def test_heating_controller_keeps_real_ctl2_when_it_owns_control_registers() -> None:
    graph = DiscoveryService.build_device_graph(
        ["scan.15 = Vaillant;CTLV2;0808;8004", "ctlv2 HwcOpMode = auto", "ctlv3 z1RoomHumidity = 53"]
    )

    assert graph.heating_controller_result().circuit == "ctlv2"
    assert graph.resolve_circuit_result("ctlv2").circuit == "ctlv2"


# Two controllers that each own a control register stay ambiguous instead of
# picking one by insertion order; the exact ctlv2 node is the safe fallback.
# Intent: two control-owning controllers resolve as AMBIGUOUS with the exact node as fallback.
# Why: ambiguity must not be resolved by insertion order.
def test_heating_controller_two_control_owners_stay_ambiguous() -> None:
    graph = DiscoveryService.build_device_graph(["ctlv2 HwcOpMode = auto", "ctlv3 HwcTempDesired = 48"])

    assert graph.heating_controller_result().status.name == "AMBIGUOUS"
    assert graph.resolve_circuit_result("ctlv2").circuit == "ctlv2"


# Intent: unrelated scans bind only to their own circuits, NETX2 to Broadcast.
# Why: a shared scan table must keep devices isolated.
def test_scan_matching_multiple_unrelated_scans_stay_isolated() -> None:
    result = match_scan_to_circuits(
        [
            ("08", "HMUX0", "0303", "0504"),
            ("15", "CTLV3", "0808", "8004"),
            ("15", "CTLV3", "0808", "8004"),
            ("76", "VWZIO", "0303", "0504"),
            ("f6", "NETX2", "4039", "5703"),
        ],
        {
            "hmux0": ["hmux0.Status01"],
            "ctlv3": ["ctlv3.Z1OpMode"],
            "vwzio": ["vwzio.TestHwcTemp"],
            "Broadcast": ["Broadcast.Outsidetemp"],
        },
    )
    assert result["hmux0"] == ("HMUX0", "0303", "0504")
    assert result["ctlv3"] == ("CTLV3", "0808", "8004")
    assert result["vwzio"] == ("VWZIO", "0303", "0504")
    assert result["Broadcast"] == ("NETX2", "4039", "5703")


# Intent: NETX3 does not bind to Broadcast while NETX2 does.
# Why: only the supported bus gateway may receive Broadcast metadata.
def test_scan_matching_netx2_broadcast_and_netx3_ignored() -> None:
    result = match_scan_to_circuits(
        [("f6", "NETX3", "0129", "0404")],
        {"Broadcast": ["Broadcast.Outsidetemp"]},
    )
    assert result == {}


def _arotherm_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(AROTHERM_LINES)


def _basv_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(COMMUNITY_BASV)


def _v32_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(COMMUNITY_V32)


def _multizone_single_circuit_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(COMMUNITY_MULTIZONE_SINGLE_CIRCUIT)


def _flexotherm_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(FLEXOTHERM_LINES)


def _arotherm_plus_2zone_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(AROTHERM_PLUS_2ZONE_LINES)


def _arotherm_plus_basv3_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(AROTHERM_PLUS_BASV3_LINES)


def _arotherm_pro7_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(AROTHERM_PRO7_LINES)


def _flexocompact_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(FLEXOCOMPACT_LINES)


def _arotherm_ecotec_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(AROTHERM_ECOTEC_LINES)


# =============================================================================
# A. Scan metadata parsing (unit tests, no ebusd needed)
# =============================================================================


# Intent: a classic HMU00 scan line parses into type/SW/HW.
# Why: scan parsing is the entry point for device classification.
def test_parse_scan_metadata_hmu() -> None:
    result = DiscoveryService._parse_scan("scan.08  = Vaillant;HMU00;0522;5103")
    assert result is not None
    assert result[1] == "HMU00"
    assert result[2] == "0522"
    assert result[3] == "5103"


# Intent: a classic CTLV2 scan line parses into type/SW/HW.
# Why: controller scan identity drives heating-controller classification.
def test_parse_scan_metadata_ctlv2() -> None:
    result = DiscoveryService._parse_scan("scan.15  = Vaillant;CTLV2;0514;1104")
    assert result is not None
    assert result[1] == "CTLV2"
    assert result[2] == "0514"
    assert result[3] == "1104"


# Intent: a VWZ00 scan line parses and exposes its scan type.
# Why: passive-cooling modules rely on this parse.
def test_parse_scan_metadata_vwz() -> None:
    result = DiscoveryService._parse_scan("scan.76  = Vaillant;VWZ00;0522;5103")
    assert result is not None
    assert result[1] == "VWZ00"


# Intent: the newer MF=/ID=/SW=/HW= scan format parses.
# Why: ebusd format changes must not break discovery.
def test_parse_scan_metadata_current_ebusd_format() -> None:
    result = DiscoveryService._parse_scan("scan.76 = MF=Vaillant;ID=VWZ00;SW=0522;HW=5103")
    assert result is not None
    assert result[1:] == ("VWZ00", "0522", "5103")


# Intent: a NETX2 scan line parses and exposes its scan type.
# Why: the NETX2 gateway identifies the Broadcast bus.
def test_parse_scan_metadata_netx2() -> None:
    result = DiscoveryService._parse_scan("scan.04 = Vaillant;NETX2;4039;5703")
    assert result is not None
    assert result[1] == "NETX2"


# Intent: a 'no data stored' scan line parses to None.
# Why: absent scan data must not fabricate a device.
def test_parse_scan_metadata_no_data() -> None:
    result = DiscoveryService._parse_scan("scan.f6 = no data stored")
    assert result is None


# Intent: the VWZIO scan line in the basv fixture yields its SW/HW.
# Why: real captures must parse to VWZIO metadata.
def test_parse_scan_metadata_vwzio() -> None:
    for line in COMMUNITY_BASV:
        result = DiscoveryService._parse_scan(line)
        if result and result[1] == "VWZIO":
            assert result[2] == "0902"
            assert result[3] == "5103"
            return
    pytest.fail("VWZIO scan line not found in basv fixture")


# =============================================================================
# B. Device categorization (unit tests)
# =============================================================================


# Intent: hmu with scan HMU00 categorizes as heat pump.
# Why: device type drives which platform creates entities.
def test_categorize_hmu() -> None:
    result = DiscoveryService.categorize_circuit("hmu", [], "HMU00")
    assert result == DeviceType.HEAT_PUMP


# Intent: ctlv2 with scan CTLV2 categorizes as heating controller.
# Why: controller classification routes control entities correctly.
def test_categorize_ctlv2() -> None:
    result = DiscoveryService.categorize_circuit("ctlv2", [], "CTLV2")
    assert result == DeviceType.HEATING_CONTROLLER


# Intent: basv with scan BASV2 categorizes as heating controller.
# Why: BASV controllers must expose heating/controller entities.
def test_categorize_basv() -> None:
    result = DiscoveryService.categorize_circuit("basv", [], "BASV2")
    assert result == DeviceType.HEATING_CONTROLLER


# Intent: bass3 with scan BASS3 categorizes as heating controller.
# Why: BASS3 controllers must not fall through to unknown.
def test_categorize_bass3() -> None:
    result = DiscoveryService.categorize_circuit("bass", [], "BASS3")
    assert result == DeviceType.HEATING_CONTROLLER


# Intent: vwz with scan VWZ00 categorizes as passive cooling.
# Why: passive-cooling modules are a distinct device type.
def test_categorize_vwz() -> None:
    result = DiscoveryService.categorize_circuit("vwz", [], "VWZ00")
    assert result == DeviceType.PASSIVE_COOLING


# Intent: vwz with no scan still categorizes as passive cooling by name.
# Why: circuits absent from scan must still classify by prefix.
def test_categorize_vwz_no_scan() -> None:
    result = DiscoveryService.categorize_circuit("vwz", [], "")
    assert result == DeviceType.PASSIVE_COOLING


# Intent: v32 with scan V32 categorizes as ventilation.
# Why: ventilation units must get their own device type.
def test_categorize_v32() -> None:
    result = DiscoveryService.categorize_circuit("v32", [], "V32")
    assert result == DeviceType.VENTILATION


# Intent: v32 with no scan still categorizes as ventilation by name.
# Why: ventilation classification must not depend on scan metadata.
def test_categorize_v32_no_scan() -> None:
    result = DiscoveryService.categorize_circuit("v32", [], "")
    assert result == DeviceType.VENTILATION


# Intent: Broadcast with scan NETX2 categorizes as bus.
# Why: the bus gateway is treated as an infrastructure device.
def test_categorize_broadcast() -> None:
    result = DiscoveryService.categorize_circuit("Broadcast", [], "NETX2")
    assert result == DeviceType.BUS


# Intent: Broadcast with no scan categorizes as bus by prefix.
# Why: the Broadcast circuit must classify without scan metadata.
def test_categorize_broadcast_by_prefix() -> None:
    result = DiscoveryService.categorize_circuit("Broadcast", [], "")
    assert result == DeviceType.BUS


# Intent: an unrecognized circuit categorizes as unknown.
# Why: unknown hardware is retained rather than misclassified.
def test_categorize_unknown_circuit() -> None:
    result = DiscoveryService.categorize_circuit("xyz", [], "")
    assert result == DeviceType.UNKNOWN


# Intent: retain scan metadata and entities for an unclassified ebusd device.
# Why: unknown hardware must still expose its registers instead of being dropped.
def test_unknown_scan_type_retains_ebusd_metadata() -> None:
    graph = DiscoveryService.build_device_graph(
        [
            "scan.01 = Vaillant;XYZ01;1234;5678",
            "xyz Status = ready",
        ]
    )
    node = graph.nodes["xyz"]
    assert node.device_type == DeviceType.UNKNOWN
    assert node.scan_type == "XYZ01"
    assert node.scan_sw == "1234"
    assert node.scan_hw == "5678"
    assert node.registers == ["xyz.Status"]


# Intent: a circuit is classified as heating controller by its Z1OpMode register.
# Why: register-shape fallback classifies controllers lacking scan metadata.
def test_categorize_by_register_z1opmode() -> None:
    result = DiscoveryService.categorize_circuit("unknown_ckt", ["unknown_ckt.Z1OpMode"], "")
    assert result == DeviceType.HEATING_CONTROLLER


# Intent: bai with scan BAI categorizes as heating controller.
# Why: boiler interfaces expose controller entities.
def test_categorize_bai_by_scan() -> None:
    result = DiscoveryService.categorize_circuit("bai", [], "BAI")
    assert result == DeviceType.HEATING_CONTROLLER


# aroTHERM Pro uses HMUX0 as heat pump identifier (issue #56)
# Intent: hmux0 with scan HMUX0 categorizes as heat pump.
# Why: issue #56 - aroTHERM Pro identifies its heat pump as HMUX0.
def test_categorize_hmux0_by_scan() -> None:
    result = DiscoveryService.categorize_circuit("hmux0", [], "HMUX0")
    assert result == DeviceType.HEAT_PUMP


# HMUX0 circuit without scan metadata still resolves via prefix
# Intent: hmux0 without scan still categorizes as heat pump by prefix.
# Why: HMUX0 classification must not depend on scan metadata.
def test_categorize_hmux0_by_prefix() -> None:
    result = DiscoveryService.categorize_circuit("hmux0", [], "")
    assert result == DeviceType.HEAT_PUMP


# SOL00 solar-collector controller is recognized (issue #56)
# Intent: sol00 with scan SOL00 categorizes as solar.
# Why: issue #56 - solar controllers must be recognized.
def test_categorize_sol00_by_scan() -> None:
    result = DiscoveryService.categorize_circuit("sol00", [], "SOL00")
    assert result == DeviceType.SOLAR


# SOL00 circuit without scan metadata still resolves via prefix
# Intent: sol00 without scan still categorizes as solar by prefix.
# Why: SOL00 classification must not depend on scan metadata.
def test_categorize_sol00_by_prefix() -> None:
    result = DiscoveryService.categorize_circuit("sol00", [], "")
    assert result == DeviceType.SOLAR


# =============================================================================
# C. Device graph construction (integration tests using fixture data)
# =============================================================================


# Intent: the aroTHERM fixture builds the expected device nodes and types.
# Why: the fixture graph is the baseline for entity generation.
def test_build_graph_arotherm() -> None:
    graph = _arotherm_graph()
    circuits = {n: node.device_type for n, node in graph.nodes.items()}
    assert "hmu" in circuits
    assert "ctlv2" in circuits
    assert "hc1" in circuits
    assert "z1" in circuits
    assert "dhw" in circuits
    assert circuits["hmu"] == DeviceType.HEAT_PUMP
    assert circuits["ctlv2"] == DeviceType.HEATING_CONTROLLER
    assert circuits["z1"] == DeviceType.ZONE
    assert circuits["dhw"] == DeviceType.DHW


# Intent: no node in the aroTHERM graph is left UNKNOWN.
# Why: every real fixture circuit must be classified.
def test_build_graph_categorization() -> None:
    graph = _arotherm_graph()
    for node in graph.nodes.values():
        assert isinstance(node.device_type, DeviceType)
        assert node.device_type != DeviceType.UNKNOWN, f"Circuit {node.circuit} is UNKNOWN"


# Intent: has_data is set per node from live register values.
# Why: data-less circuits must not be treated as active.
def test_build_graph_has_data() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["hmu"].has_data is True
    assert graph.nodes["ctlv2"].has_data is True
    assert graph.nodes["z1"].has_data is True
    assert graph.nodes["dhw"].has_data is True
    assert graph.nodes["vwz"].has_data is False


# Intent: ctlv2 maps its zone and heating circuits.
# Why: zone/heating circuit mapping drives per-zone entities.
def test_build_graph_zone_mapping() -> None:
    graph = _arotherm_graph()
    ctlv2 = graph.nodes["ctlv2"]
    assert "z1" in ctlv2.zone_circuits
    assert "hc1" in ctlv2.heating_circuits


# Intent: the aroTHERM graph carries the expected raw register set.
# Why: discovery must expose enough registers for entities.
def test_build_graph_raw_registers_count() -> None:
    graph = _arotherm_graph()
    assert len(graph.raw_registers) > 50
    assert "ctlv2.Z1DayTemp" in graph.raw_registers
    assert "hmu.RunDataStatuscode" in graph.raw_registers


# Intent: the aroTHERM graph carries the expected placeholder registers.
# Why: no-data registers stay placeholders, not dropped.
def test_build_graph_placeholder_registers() -> None:
    graph = _arotherm_graph()
    assert len(graph.placeholder_registers) > 100
    assert "hmu.CopCooling" in graph.placeholder_registers


# Intent: a live value wins over a duplicate no-data line in any order.
# Why: ebusd line ordering must not erase a real value.
@pytest.mark.parametrize(
    "find_lines",
    [
        ["v32 SupplyAirTemp = 20.75;ok", "v32 SupplyAirTemp = no data stored"],
        ["v32 SupplyAirTemp = no data stored", "v32 SupplyAirTemp = 20.75;ok"],
    ],
)
def test_duplicate_find_lines_preserve_live_value_regardless_of_order(
    find_lines: list[str],
) -> None:
    graph = DiscoveryService.build_device_graph(find_lines)
    assert graph.raw_registers["v32.SupplyAirTemp"] == "20.75;ok"
    assert graph.nodes["v32"].has_data is True


# Intent: numeric/address-like and empty unknown circuits are suppressed.
# Why: stray find noise must not become devices.
def test_address_and_empty_unknown_circuits_are_suppressed() -> None:
    graph = DiscoveryService.build_device_graph(
        [
            "scan.76 = MF=Vaillant;ID=VWZ00;SW=0522;HW=5103",
            "76 VWZ_Status01b = 42",
            "B504 VWZ_Status_0100 =  (ERR: invalid position)",
            "B512 VWZ_Status_030f0101 =  (ERR: invalid position)",
            "sc Col = no data stored",
            "vwz TestHwcTemp = no data stored",
        ]
    )
    assert "76" not in graph.nodes
    assert "B504" not in graph.nodes
    assert "B512" not in graph.nodes
    assert "sc" not in graph.nodes
    assert graph.nodes["vwz"].device_type == DeviceType.PASSIVE_COOLING


# Intent: TmpB516MonthEven stays in raw registers but not node registers.
# Why: internal helper registers are hidden from entities.
def test_internal_b516_helper_register_is_hidden() -> None:
    graph = DiscoveryService.build_device_graph(["hmu TmpB516MonthEven = 139818"])
    assert "hmu.TmpB516MonthEven" in graph.raw_registers
    assert "hmu.TmpB516MonthEven" not in graph.nodes["hmu"].registers


# =============================================================================
# D. Community fixture tests
# =============================================================================


# Intent: the basv community fixture classifies basv as heating controller.
# Why: community hardware must classify like local hardware.
def test_categorize_basv_from_community() -> None:
    graph = _basv_graph()
    assert "basv" in graph.nodes
    assert graph.nodes["basv"].device_type == DeviceType.HEATING_CONTROLLER


# Intent: the basv community fixture classifies vwzio as passive cooling.
# Why: community hardware must classify like local hardware.
def test_categorize_vwzio_from_community() -> None:
    graph = _basv_graph()
    assert "vwzio" in graph.nodes
    assert graph.nodes["vwzio"].device_type == DeviceType.PASSIVE_COOLING


# Intent: the v32 community fixture classifies v32 as ventilation.
# Why: community hardware must classify like local hardware.
def test_categorize_v32_from_community() -> None:
    graph = _v32_graph()
    assert "v32" in graph.nodes
    assert graph.nodes["v32"].device_type == DeviceType.VENTILATION


# Intent: the flexotherm fixture builds hmu/ctlv3 with SourceTempOutput present.
# Why: community controller layout must be discovered.
def test_flexotherm_device_graph() -> None:
    graph = _flexotherm_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["ctlv3"].scan_type in ("CTLV3", "")
    assert "hmu.SourceTempOutput" in graph.raw_registers or "hmu.SourceTempOutput" in graph.placeholder_registers
    assert "hmu.SourceTempInput" not in graph.raw_registers
    assert "hmu.SourceTempInput" not in graph.placeholder_registers


# Intent: an invalid SourceTempInput stub is dropped while FlowTemp is kept.
# Why: a bad brine temperature must not pollute the graph.
def test_invalid_source_temperature_stub_is_suppressed() -> None:
    graph = DiscoveryService.build_device_graph(["hmu SourceTempInput = -1011.06", "hmu FlowTemp = 35.0"])

    assert "hmu.SourceTempInput" not in graph.raw_registers
    assert "hmu.SourceTempInput" not in graph.placeholder_registers


# Intent: the flexotherm fixture exposes runtime-defined ctlv2.z1RoomHumidity.
# Why: runtime register definitions must appear after discovery.
def test_flexotherm_runtime_room_humidity() -> None:
    graph = _flexotherm_graph()
    assert graph.nodes["ctlv2"].device_type == DeviceType.HEATING_CONTROLLER
    assert "ctlv2.z1RoomHumidity" in graph.raw_registers


# Intent: the flexotherm fixture exposes PrEnergySum registers.
# Why: energy counters must be discovered where supported.
def test_flexotherm_energy_registers() -> None:
    graph = _flexotherm_graph()
    assert "ctlv3.PrEnergySumHc" in graph.raw_registers
    assert "ctlv3.PrEnergySumHwc" in graph.raw_registers
    assert "ctlv3.PrEnergySum" in graph.placeholder_registers


# Intent: the flexotherm fixture classifies vr_71 as a mixing module.
# Why: VR71 modules must be recognized.
def test_flexotherm_vr71_mixing_module() -> None:
    graph = _flexotherm_graph()
    assert graph.nodes["vr_71"].device_type == DeviceType.MIXING_MODULE
    assert graph.nodes["vr_71"].scan_type == "VR_71"


# Intent: the aroTHERM Plus 2-zone fixture builds hmu/ctlv3 with expected registers.
# Why: 2-zone hardware must be discovered correctly.
def test_arotherm_plus_2zone_graph() -> None:
    graph = _arotherm_plus_2zone_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["ctlv3"].scan_type == "CTLV3"
    assert "hmu.Status01" in graph.raw_registers
    assert "hmu.PowerConsumptionHmu" in graph.raw_registers
    assert "hmu.BuildingCircuitFlow" in graph.placeholder_registers


# Intent: the 2-zone fixture exposes active z2/hc2 and inactive z3.
# Why: secondary zone activity must be derived correctly.
def test_arotherm_plus_2zone_active_z2() -> None:
    graph = _arotherm_plus_2zone_graph()
    assert graph.nodes["z2"].has_data is True
    assert graph.nodes["z2"].device_type == DeviceType.ZONE
    assert graph.nodes["hc2"].has_data is True
    assert "ctlv3.Z2RoomTemp" in graph.raw_registers
    assert graph.nodes["z3"].has_data is False


# Intent: the BASV3 fixture builds basv3/hmu/vwzio with scan identity.
# Why: BASV3 hardware must be recognized.
def test_arotherm_plus_basv3_graph() -> None:
    graph = _arotherm_plus_basv3_graph()
    assert graph.nodes["basv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["basv3"].scan_type == "BASV3"
    assert graph.nodes["basv3"].scan_sw == "0708"
    assert graph.nodes["basv3"].scan_hw == "4304"
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["vwzio"].device_type == DeviceType.PASSIVE_COOLING


# Intent: BASV3 Status01 is decoded as a multi-field value.
# Why: multi-field registers must preserve their decoded fields.
def test_arotherm_plus_basv3_status01_multifield() -> None:
    graph = _arotherm_plus_basv3_graph()
    assert graph.raw_registers["hmu.Status01"] == "39.5;40.5;-;-;-;off"
    assert "basv3.Hc1FlowTemp" in graph.raw_registers


# Intent: the BASV3 fixture exposes active z1 and inactive z2/z3.
# Why: zone activity must be derived correctly.
def test_arotherm_plus_basv3_zones() -> None:
    graph = _arotherm_plus_basv3_graph()
    assert graph.nodes["z1"].has_data is True
    assert graph.nodes["z2"].has_data is False
    assert graph.nodes["z3"].has_data is False


# Helianthus B524 register map fixture (community capture via discussion #60):
# the heating-circuit state registers (GG=0x02 RR=0x20..0x25) must appear on
# the discovered graph once the runtime defines are in place.
# Intent: the Helianthus B524 fixture exposes the circuit state registers.
# Why: discussion #60 - runtime B524 defines must surface on the graph.
def test_helianthus_b524_circuit_registers_graph() -> None:
    lines = load_find_lines("community/helianthus_b524_circuit_registers.yaml")
    graph = DiscoveryService.build_device_graph(lines)
    assert graph.nodes["ctlv2"].device_type == DeviceType.HEATING_CONTROLLER
    for register in (
        "ctlv2.Hc1FlowTempCalc",
        "ctlv2.Hc1MixerPosition",
        "ctlv2.Hc1Humidity",
        "ctlv2.Hc1DewPointTemp",
        "ctlv2.Hc1PumpHours",
        "ctlv2.Hc1PumpStarts",
        "ctlv2.Hc2FlowTempCalc",
        "ctlv2.Hc2MixerPosition",
        "ctlv2.Hc2Humidity",
        "ctlv2.Hc2DewPointTemp",
        "ctlv2.Hc2PumpHours",
        "ctlv2.Hc2PumpStarts",
    ):
        assert register in graph.raw_registers, f"Missing {register}"
    assert graph.raw_registers["ctlv2.Hc1FlowTempCalc"] == "40.1"
    assert graph.raw_registers["ctlv2.Hc1PumpHours"] == "1234"
    assert graph.raw_registers["ctlv2.Hc2PumpStarts"] == "234"


# Intent: the aroTHERM Pro7 fixture classifies ctlv3 and vwzio.
# Why: Pro7 hardware must be recognized.
def test_arotherm_pro7_graph() -> None:
    graph = _arotherm_pro7_graph()
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["ctlv3"].scan_type in ("CTLV3", "")
    assert graph.nodes["vwzio"].device_type == DeviceType.PASSIVE_COOLING
    assert "hmu" not in graph.nodes
    assert "ctlv3.Z1DayTemp" in graph.raw_registers
    assert "ctlv3.Z1OpMode" in graph.raw_registers


# Intent: the Pro7 fixture has no hmu node and data-less ctlv3 with active z1.
# Why: Pro7 uses HMUX0, so a phantom hmu must not appear.
def test_arotherm_pro7_hmu_missing() -> None:
    graph = _arotherm_pro7_graph()
    assert "hmu" not in graph.nodes
    assert "hmu.Status01" not in graph.raw_registers
    assert "hmu.Status01" not in graph.placeholder_registers
    assert graph.nodes["ctlv3"].has_data is False
    assert graph.nodes["z1"].has_data is True


# Intent: the flexocompact fixture builds hmu/ctlv2/v32/vwz with scan identity.
# Why: mixed hardware must be discovered correctly.
def test_flexocompact_device_graph() -> None:
    graph = _flexocompact_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["ctlv2"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["ctlv2"].scan_type == "CTLV2"
    assert graph.nodes["v32"].device_type == DeviceType.VENTILATION
    assert graph.nodes["vwz"].device_type == DeviceType.PASSIVE_COOLING
    assert graph.nodes["vwz"].scan_type == "VWZ00"
    assert graph.nodes["v32"].has_data is True
    assert graph.nodes["vwz"].has_data is False


# Intent: the flexocompact fixture exposes active z1/z2/z3 and room registers.
# Why: multi-zone mixed hardware must map zones.
def test_flexocompact_multi_zone() -> None:
    graph = _flexocompact_graph()
    for zone in ("z1", "z2", "z3"):
        assert graph.nodes[zone].has_data is True
        assert graph.nodes[zone].device_type == DeviceType.ZONE
    assert "ctlv2.Z1RoomTemp" in graph.raw_registers
    assert "ctlv2.Z1RoomHumidity" in graph.raw_registers
    assert "ctlv2.Z2RoomTemp" in graph.placeholder_registers
    assert "ctlv2.Z3RoomTemp" in graph.placeholder_registers
    assert "ctlv2.RoomTemp" in graph.raw_registers
    assert "ctlv2.RoomHumidity" in graph.raw_registers


# Intent: the flexocompact fixture exposes hmu/ctlv2 registers and placeholders.
# Why: mixed hardware registers must be discovered.
def test_flexocompact_hmu_registers() -> None:
    graph = _flexocompact_graph()
    assert "hmu.Status01" in graph.raw_registers
    assert "hmu.CurrentConsumedPower" in graph.raw_registers
    assert "hmu.CurrentYieldPower" in graph.raw_registers
    assert "ctlv2.Z1RoomHumidity" in graph.raw_registers
    assert "hmu.RunDataBuildingCPumpPower" in graph.placeholder_registers
    assert "hmu.RunDataElectricPowerConsumption" in graph.placeholder_registers


# Intent: every node in several community graphs has a valid device type.
# Why: community captures must never yield an invalid type.
def test_community_unknown_circuits() -> None:
    for graph in (_basv_graph(), _v32_graph(), _flexotherm_graph(), _flexocompact_graph()):
        for node in graph.nodes.values():
            assert node.device_type in DeviceType, f"Invalid device type for {node.circuit}"


# Intent: the ecotec fixture builds hmu/ctlv2/vr_71 with scan identity.
# Why: ecoTEC hardware must be recognized.
def test_arotherm_ecotec_device_graph() -> None:
    graph = _arotherm_ecotec_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["ctlv2"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["ctlv2"].scan_type == "CTLV2"
    assert graph.nodes["vr_71"].device_type == DeviceType.MIXING_MODULE
    assert graph.nodes["vr_71"].scan_type == "VR_71"
    assert graph.nodes["vr_71"].has_data is True
    assert graph.nodes["vwzio"].has_data is False


# Intent: the ecotec fixture exposes hmu registers and omits ctlv2.Z1RoomHumidity.
# Why: ecoTEC hardware must not invent unsupported registers.
def test_arotherm_ecotec_hmu_registers() -> None:
    graph = _arotherm_ecotec_graph()
    assert "hmu.Status01" in graph.raw_registers
    assert "hmu.FlowTemp" in graph.raw_registers
    assert "hmu.BuildingCircuitFlow" in graph.raw_registers
    assert "ctlv2.Z1RoomHumidity" not in graph.raw_registers
    assert "ctlv2.Z1RoomHumidity" not in graph.placeholder_registers


# Intent: the ecotec fixture exposes an active z1 zone.
# Why: ecoTEC zone mapping must work.
def test_arotherm_ecotec_zones() -> None:
    graph = _arotherm_ecotec_graph()
    assert "z1" in graph.nodes
    assert graph.nodes["z1"].has_data is True
    assert graph.nodes["z1"].device_type == DeviceType.ZONE


# =============================================================================
# D. aroTHERM Plus cooling/HWC run dumps (issue #53 follow-up dumps)
# =============================================================================

AROTHERM_PLUS_COOLING_RUN_LINES = load_find_lines("community/arotherm_plus_cooling_run_discovery.yaml")
AROTHERM_PLUS_HWC_RUN_LINES = load_find_lines("community/arotherm_plus_hwc_run_discovery.yaml")


def _arotherm_plus_cooling_run_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(AROTHERM_PLUS_COOLING_RUN_LINES)


def _arotherm_plus_hwc_run_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(AROTHERM_PLUS_HWC_RUN_LINES)


# aroTHERM Plus cooling-run dump: graph exposes heat pump + controller
# Intent: the aroTHERM Plus cooling-run fixture builds hmu/ctlv3/vr_71.
# Why: issue #53 follow-up - cooling-run dumps must discover.
def test_arotherm_plus_cooling_run_graph() -> None:
    graph = _arotherm_plus_cooling_run_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["vr_71"].device_type == DeviceType.MIXING_MODULE
    assert "hmu.YieldHc" in graph.raw_registers


# aroTHERM Plus HWC-run dump: graph exposes heat pump + controller
# Intent: the aroTHERM Plus HWC-run fixture builds hmu/ctlv3 with HWC yield.
# Why: issue #53 follow-up - DHW-run dumps must discover.
def test_arotherm_plus_hwc_run_graph() -> None:
    graph = _arotherm_plus_hwc_run_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert "hmu.YieldHwc" in graph.raw_registers
    assert "hmu.RunStatsHwcHours" in graph.raw_registers


# PrEnergySum* stays no-data in both run dumps — entities must still exist
# (enabled but unavailable), never dropped because of transient no-data values.
# Intent: PrEnergySum registers stay present (enabled) despite no-data.
# Why: transient no-data must not drop energy entities.
def test_arotherm_plus_runs_keep_prenergy_registers() -> None:
    for graph in (_arotherm_plus_cooling_run_graph(), _arotherm_plus_hwc_run_graph()):
        for reg in ("ctlv3.PrEnergySum", "ctlv3.PrEnergySumHc", "ctlv3.PrEnergySumHwc"):
            assert reg in graph.placeholder_registers or reg in graph.raw_registers, reg


# ctlv2-cooling fixture: Mark's own aroTHERM Plus while cooling is active
# (status cool_compressor_active). Same heat pump + controller shape as the
# ctlv3 run dumps, but on a ctlv2 controller without the cooling-program
# registers (Hc1CoolingEnabled, Z1CoolingOpMode, ... — absent from find).
AROTHERM_PLUS_CTLV2_COOLING_LINES = load_find_lines("community/arotherm_plus_ctlv2_cooling_discovery.yaml")


def _arotherm_plus_ctlv2_cooling_graph() -> DeviceGraph:
    return DiscoveryService.build_device_graph(AROTHERM_PLUS_CTLV2_COOLING_LINES)


# Intent: the ctlv2 cooling fixture builds hmu/ctlv2 with cooling temperature.
# Why: Mark's ctlv2 cooling hardware must be discovered.
def test_arotherm_plus_ctlv2_cooling_graph() -> None:
    graph = _arotherm_plus_ctlv2_cooling_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv2"].device_type == DeviceType.HEATING_CONTROLLER
    assert "hmu.RunDataStatuscode" in graph.raw_registers
    assert "ctlv2.Z1CoolingTemp" in graph.raw_registers


# The ctlv2 cooling run must not invent cooling-program registers that ebusd
# does not expose (they only exist with a 720 room panel / Hc1CoolingEnabled=1).
# Intent: the ctlv2 cooling fixture invents no cooling-program registers.
# Why: absent registers must not be fabricated from a cooling capture.
def test_arotherm_plus_ctlv2_cooling_no_program_registers() -> None:
    graph = _arotherm_plus_ctlv2_cooling_graph()
    for reg in (
        "ctlv2.Hc1CoolingEnabled",
        "ctlv2.Hc1CoolingFlowTempMin",
        "ctlv2.Z1CoolingOpMode",
        "ctlv2.Z1CoolingManualTemp",
        "ctlv2.Z1CoolingSetbackTemp",
        "ctlv2.Z1CoolingTempDesired",
    ):
        assert reg not in graph.raw_registers, reg
        assert reg not in graph.placeholder_registers, reg


# =============================================================================
# E. Zone-to-circuit mapping
# =============================================================================


# Intent: z1 registers carry Z1 names and map to hc1 on ctlv2.
# Why: zone/heating-circuit separation must hold.
def test_zone_hc_mapping_z1() -> None:
    graph = _arotherm_graph()
    assert "z1" in graph.nodes
    assert "hc1" in graph.nodes
    z1_regs = graph.nodes["z1"].registers
    hc1_regs = graph.nodes["hc1"].registers
    assert any("Z1" in r for r in z1_regs)
    assert all("Hc1" in r for r in hc1_regs)
    assert "z1" in graph.nodes["ctlv2"].zone_circuits
    assert "hc1" in graph.nodes["ctlv2"].heating_circuits


# Intent: z2 registers all carry Z2 names.
# Why: zone registers must not leak across zones.
def test_zone_hc_mapping_z2() -> None:
    graph = _arotherm_graph()
    assert "z2" in graph.nodes
    assert "hc2" in graph.nodes
    z2_regs = graph.nodes["z2"].registers
    assert all("Z2" in r for r in z2_regs)


# Intent: inactive z2/hc2 nodes are retained with has_data False.
# Why: empty zones must remain visible but inactive.
def test_no_pair_when_no_data() -> None:
    graph = _arotherm_graph()
    assert "z2" in graph.nodes
    assert graph.nodes["z2"].has_data is False
    assert "hc2" in graph.nodes
    assert graph.nodes["hc2"].has_data is False


# Intent: retain active Z2 registers when both zones are owned by ctlv2.
# Why: multiple zones under one ctlv2 controller must each get an active node.
def test_multizone_single_circuit_creates_active_z2_node() -> None:
    graph = _multizone_single_circuit_graph()
    z2 = graph.nodes["z2"]
    assert z2.device_type == DeviceType.ZONE
    assert z2.has_data is True
    assert set(z2.registers) == {
        "ctlv2.Z2RoomTemp",
        "ctlv2.Z2DayTemp",
        "ctlv2.Z2OpMode",
        "ctlv2.Z2ActualRoomTempDesired",
    }
    assert "z2" in graph.nodes["ctlv2"].zone_circuits


# =============================================================================
# F. Hidden register filtering
# =============================================================================


# Intent: Broadcast id/signoflife/IdAnswer/Load registers are hidden.
# Why: internal bus identity registers must not surface as entities.
def test_hidden_broadcast_registers() -> None:
    assert DiscoveryService._is_hidden("Broadcast.id") is True
    assert DiscoveryService._is_hidden("broadcast.signoflife") is True
    assert DiscoveryService._is_hidden("Broadcast.IdAnswer") is True
    assert DiscoveryService._is_hidden("Broadcast.Load") is True


# Intent: timer config registers (cctimer, HwcTimer, Z1Timer) are hidden.
# Why: schedule timers are noise for the UI and must stay hidden.
def test_hidden_timer_registers() -> None:
    assert DiscoveryService._is_hidden("ctlv2.cctimer_Config") is True
    assert DiscoveryService._is_hidden("ctlv2.HwcTimer_Monday0") is True
    assert DiscoveryService._is_hidden("ctlv2.Z1Timer_Friday0") is True


# Intent: real control/telemetry registers pass the hidden filter.
# Why: over-broad filtering would remove legitimate entities.
def test_known_register_not_hidden() -> None:
    assert DiscoveryService._is_hidden("hmu.Status01") is False
    assert DiscoveryService._is_hidden("ctlv2.Z1DayTemp") is False
    assert DiscoveryService._is_hidden("ctlv2.HwcOpMode") is False


# Intent: FlowTemperature and Broadcast.FlowTemp are hidden.
# Why: specific noisy or duplicate registers must be excluded.
def test_hidden_specific_registers() -> None:
    assert DiscoveryService._is_hidden("hmu.FlowTemperature") is True
    assert DiscoveryService._is_hidden("Broadcast.FlowTemp") is True


# Intent: memory.*/Memory.* circuits are hidden.
# Why: EEPROM/RAM pseudo-registers are not device entities.
def test_hidden_memory_circuit() -> None:
    assert DiscoveryService._is_hidden("memory.eeprom") is True
    assert DiscoveryService._is_hidden("Memory.Ram") is True


# Intent: the general.* circuit is hidden.
# Why: the general pseudo-circuit must not create entities.
def test_hidden_general_circuit() -> None:
    assert DiscoveryService._is_hidden("general.whatever") is True


# Intent: scan.* pseudo-registers are hidden.
# Why: scan discovery lines are metadata, not entities.
def test_hidden_scan_lines() -> None:
    assert DiscoveryService._is_hidden("scan.08.x") is True


# Intent: installer-only registers (Installer1, PhoneNumber1, KeyCode...) are hidden.
# Why: installer/service data must not be exposed to normal users.
def test_hidden_installer_registers() -> None:
    assert DiscoveryService._is_hidden("ctlv2.Installer1") is True
    assert DiscoveryService._is_hidden("ctlv2.PhoneNumber1") is True
    assert DiscoveryService._is_hidden("ctlv2.KeyCodeforConfigMenu") is True
    assert DiscoveryService._is_hidden("ctlv2.MaintenanceDate") is True


# Intent: PrFuelSumHc is hidden.
# Why: legacy fuel-summary registers are excluded by name.
def test_hidden_prfuelsum() -> None:
    assert DiscoveryService._is_hidden("ctlv2.PrFuelSumHc") is True


# Intent: ctlv2.id is not hidden even though Broadcast.id is.
# Why: the hidden filter must be scoped to the Broadcast circuit.
def test_broadcast_not_hidden_outside_broadcast() -> None:
    assert DiscoveryService._is_hidden("ctlv2.id") is False


# =============================================================================
# G. Relationship determination
# =============================================================================


# Intent: ctlv2 is parented to hmu.
# Why: controller hierarchy drives device relationships in the UI.
def test_relationships_controller_parent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["ctlv2"].parent == "hmu"


# Intent: z1 is parented to ctlv2.
# Why: zones must hang off their controller.
def test_relationships_zone_parent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["z1"].parent == "ctlv2"


# Intent: dhw is parented to ctlv2.
# Why: DHW must hang off the controller that owns its registers.
def test_relationships_dhw_parent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["dhw"].parent == "ctlv2"


# Intent: hc1 is parented to ctlv2.
# Why: heating circuits must hang off their controller.
def test_relationships_hc_parent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["hc1"].parent == "ctlv2"


# Intent: vwz has no parent.
# Why: passive-cooling modules are standalone devices.
def test_relationships_vwz_independent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["vwz"].parent is None


# Intent: no Broadcast node exists in the aroTHERM graph.
# Why: the Broadcast circuit is filtered from the device graph.
def test_relationships_broadcast_parent() -> None:
    graph = _arotherm_graph()
    assert "Broadcast" not in graph.nodes


# Intent: hmu has no parent.
# Why: the heat pump is the graph root.
def test_relationships_hmu_is_root() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["hmu"].parent is None


# Intent: vwzio has no parent in the basv graph.
# Why: community passive-cooling modules are standalone.
def test_relationships_vwzio_independent() -> None:
    graph = _basv_graph()
    assert graph.nodes["vwzio"].parent is None


# Intent: v32 has no parent in the v32 graph.
# Why: ventilation units are standalone devices.
def test_relationships_v32_independent() -> None:
    graph = _v32_graph()
    assert graph.nodes["v32"].parent is None


# =============================================================================
# Additional edge case tests
# =============================================================================


# Intent: a simple find line parses into circuit, name, and value.
# Why: register parsing feeds every downstream mapping.
def test_parse_register_simple() -> None:
    c, n, v = DiscoveryService._parse_register("hmu Status01 = 58.0")
    assert c == "hmu"
    assert n == "Status01"
    assert v == "58.0"


# Intent: 'no data stored' parses to a None value.
# Why: unavailable registers must not be given a value.
def test_parse_register_no_data() -> None:
    c, n, v = DiscoveryService._parse_register("hmu CopCooling = no data stored")
    assert c == "hmu"
    assert n == "CopCooling"
    assert v is None


# Intent: unknown/unavailable/-/empty all parse to no-data.
# Why: every unavailable sentinel must be handled by the shared helper.
def test_parse_register_sentinel_values() -> None:
    # unknown/unavailable/bare-empty must be no-data everywhere (shared helper).
    for raw in ("unknown", "unavailable", "-", "empty"):
        _, _, value = DiscoveryService._parse_register(f"hmu SomeRegister = {raw}")
        assert value is None, f"{raw!r} should parse as no-data"


# Intent: an empty value with trailing metadata parses to None.
# Why: ebusd's empty-value annotations must not become data.
def test_parse_register_empty_with_meta() -> None:
    c, n, v = DiscoveryService._parse_register(
        "ctlv2 HcStorageTempBottom =  (empty for f115b5240602000000a000 / 080000a000ffffff7f)"
    )
    assert v is None


# Intent: a value carrying an ERR suffix parses to None.
# Why: partially decoded error replies must not be trusted.
def test_parse_register_partial_value_with_error_is_unavailable() -> None:
    _, _, value = DiscoveryService._parse_register("sc YieldThisYear = 0;32768;13056;0 (ERR: invalid position)")
    assert value is None


# Intent: implausible HMUX0 return temperatures are rejected.
# Why: out-of-range decodes must become unavailable, not displayed.
@pytest.mark.parametrize("raw", ("1082.88", "-423.75"))
def test_parse_register_rejects_invalid_hmux0_return_temperature(raw: str) -> None:
    _, _, value = DiscoveryService._parse_register(f"hmux0 RunDataReturnTemp = {raw}")

    assert value is None


# Intent: plausible HMUX0 return temperatures are preserved verbatim.
# Why: valid data must not be dropped by the range guard.
@pytest.mark.parametrize("raw", ("28.0172", "28.2184"))
def test_parse_register_keeps_valid_hmux0_return_temperature(raw: str) -> None:
    _, _, value = DiscoveryService._parse_register(f"hmux0 RunDataReturnTemp = {raw}")

    assert value == raw


# Intent: the aroTHERM nodes carry their parsed scan type/SW/HW.
# Why: entity generation relies on scan identity.
def test_scan_metadata_present_in_nodes() -> None:
    graph = _arotherm_graph()
    hmu = graph.nodes["hmu"]
    assert hmu.scan_type == "HMU00"
    assert hmu.scan_sw == "0522"
    assert hmu.scan_hw == "5103"
    ctlv2 = graph.nodes["ctlv2"]
    assert ctlv2.scan_type == "CTLV2"


# Intent: the basv graph nodes carry their parsed scan metadata.
# Why: community graphs must retain scan identity.
def test_scan_metadata_in_basv_graph() -> None:
    graph = _basv_graph()
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["basv"].scan_type == "BASV2"
    assert graph.nodes["vwzio"].scan_type == "VWZIO"


# =============================================================================
# H. Integration tests with FakeEbusdServer
# =============================================================================


# Intent: discovery over FakeEbusdServer yields the expected device types.
# Why: end-to-end discovery must match unit behavior.
async def test_integration_arotherm_discover_device_types() -> None:
    async with FakeEbusdServer("arotherm_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        graph = await svc.discover()
        await svc._ebus.disconnect()

        assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
        assert graph.nodes["ctlv2"].device_type == DeviceType.HEATING_CONTROLLER
        assert "Broadcast" not in graph.nodes


# Intent: end-to-end discovery yields the expected parent relationships.
# Why: the device hierarchy must survive the network path.
async def test_integration_arotherm_parent_relationships() -> None:
    async with FakeEbusdServer("arotherm_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        graph = await svc.discover()
        await svc._ebus.disconnect()

        assert graph.nodes["ctlv2"].parent == "hmu"
        assert graph.nodes["z1"].parent == "ctlv2"
        assert graph.nodes["hc1"].parent == "ctlv2"
        assert graph.nodes["dhw"].parent == "ctlv2"
        assert "Broadcast" not in graph.nodes


# Intent: end-to-end discovery yields the expected has_data flags and raw count.
# Why: the live discovery output is pinned against regression.
async def test_integration_arotherm_has_data() -> None:
    async with FakeEbusdServer("arotherm_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        graph = await svc.discover()
        await svc._ebus.disconnect()

        assert graph.nodes["hmu"].has_data is True
        assert graph.nodes["ctlv2"].has_data is True
        assert graph.nodes["z1"].has_data is True
        assert graph.nodes["dhw"].has_data is True
        assert graph.nodes["vwz"].has_data is False
        assert graph.nodes["z2"].has_data is False
        assert graph.nodes["z3"].has_data is False
        assert graph.nodes["hc2"].has_data is False
        assert graph.nodes["hc3"].has_data is False
        assert len(graph.raw_registers) == 75


# Intent: basv discovery over the socket yields controller and heat-pump types.
# Why: community controller discovery works end to end.
async def test_integration_basv_controller_type() -> None:
    async with FakeEbusdServer("community/basv_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        graph = await svc.discover()
        await svc._ebus.disconnect()

        assert "basv" in graph.nodes
        assert graph.nodes["basv"].device_type == DeviceType.HEATING_CONTROLLER
        assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP


# Intent: v32 discovery over the socket yields ventilation with data.
# Why: community ventilation discovery works end to end.
async def test_integration_v32_ventilation_type() -> None:
    async with FakeEbusdServer("community/v32_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        graph = await svc.discover()
        await svc._ebus.disconnect()

        assert "v32" in graph.nodes
        assert graph.nodes["v32"].device_type == DeviceType.VENTILATION
        assert graph.nodes["v32"].has_data is True


# Intent: end-to-end discovery maps z1 to ctlv2 with Z1 registers.
# Why: zone mapping must survive the network path.
async def test_integration_arotherm_zone_mapping() -> None:
    async with FakeEbusdServer("arotherm_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        graph = await svc.discover()
        await svc._ebus.disconnect()

        ctlv2 = graph.nodes["ctlv2"]
        assert "z1" in ctlv2.zone_circuits
        assert "hc1" in ctlv2.heating_circuits
        z1_node = graph.nodes["z1"]
        assert any("Z1" in r for r in z1_node.registers)


# Intent: discovery logs each device and a device-graph summary.
# Why: operators rely on discovery logging for diagnosis.
async def test_discover_logs_per_device_and_type_summary(caplog) -> None:
    async with FakeEbusdServer("arotherm_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        with caplog.at_level("INFO", logger="vaillant_ebus.backend.discovery_service"):
            graph = await svc.discover()
        await svc._ebus.disconnect()

    messages = caplog.text
    assert "Starting device discovery" in messages
    assert "Discovered device hmu" in messages
    assert "Discovered device ctlv2" in messages
    assert "Device graph:" in messages
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
