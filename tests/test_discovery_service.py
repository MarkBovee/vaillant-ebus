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


def test_parse_scan_metadata_hmu() -> None:
    result = DiscoveryService._parse_scan("scan.08  = Vaillant;HMU00;0522;5103")
    assert result is not None
    assert result[1] == "HMU00"
    assert result[2] == "0522"
    assert result[3] == "5103"


def test_parse_scan_metadata_ctlv2() -> None:
    result = DiscoveryService._parse_scan("scan.15  = Vaillant;CTLV2;0514;1104")
    assert result is not None
    assert result[1] == "CTLV2"
    assert result[2] == "0514"
    assert result[3] == "1104"


def test_parse_scan_metadata_vwz() -> None:
    result = DiscoveryService._parse_scan("scan.76  = Vaillant;VWZ00;0522;5103")
    assert result is not None
    assert result[1] == "VWZ00"


def test_parse_scan_metadata_current_ebusd_format() -> None:
    result = DiscoveryService._parse_scan("scan.76 = MF=Vaillant;ID=VWZ00;SW=0522;HW=5103")
    assert result is not None
    assert result[1:] == ("VWZ00", "0522", "5103")


def test_parse_scan_metadata_netx2() -> None:
    result = DiscoveryService._parse_scan("scan.04 = Vaillant;NETX2;4039;5703")
    assert result is not None
    assert result[1] == "NETX2"


def test_parse_scan_metadata_no_data() -> None:
    result = DiscoveryService._parse_scan("scan.f6 = no data stored")
    assert result is None


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


def test_categorize_hmu() -> None:
    result = DiscoveryService.categorize_circuit("hmu", [], "HMU00")
    assert result == DeviceType.HEAT_PUMP


def test_categorize_ctlv2() -> None:
    result = DiscoveryService.categorize_circuit("ctlv2", [], "CTLV2")
    assert result == DeviceType.HEATING_CONTROLLER


def test_categorize_basv() -> None:
    result = DiscoveryService.categorize_circuit("basv", [], "BASV2")
    assert result == DeviceType.HEATING_CONTROLLER


def test_categorize_vwz() -> None:
    result = DiscoveryService.categorize_circuit("vwz", [], "VWZ00")
    assert result == DeviceType.PASSIVE_COOLING


def test_categorize_vwz_no_scan() -> None:
    result = DiscoveryService.categorize_circuit("vwz", [], "")
    assert result == DeviceType.PASSIVE_COOLING


def test_categorize_v32() -> None:
    result = DiscoveryService.categorize_circuit("v32", [], "V32")
    assert result == DeviceType.VENTILATION


def test_categorize_v32_no_scan() -> None:
    result = DiscoveryService.categorize_circuit("v32", [], "")
    assert result == DeviceType.VENTILATION


def test_categorize_broadcast() -> None:
    result = DiscoveryService.categorize_circuit("Broadcast", [], "NETX2")
    assert result == DeviceType.BUS


def test_categorize_broadcast_by_prefix() -> None:
    result = DiscoveryService.categorize_circuit("Broadcast", [], "")
    assert result == DeviceType.BUS


def test_categorize_unknown_circuit() -> None:
    result = DiscoveryService.categorize_circuit("xyz", [], "")
    assert result == DeviceType.UNKNOWN


# Intent: retain scan metadata and entities for an unclassified ebusd device.
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


def test_categorize_by_register_z1opmode() -> None:
    result = DiscoveryService.categorize_circuit("unknown_ckt", ["unknown_ckt.Z1OpMode"], "")
    assert result == DeviceType.HEATING_CONTROLLER


def test_categorize_bai_by_scan() -> None:
    result = DiscoveryService.categorize_circuit("bai", [], "BAI")
    assert result == DeviceType.HEATING_CONTROLLER


# aroTHERM Pro uses HMUX0 as heat pump identifier (issue #56)
def test_categorize_hmux0_by_scan() -> None:
    result = DiscoveryService.categorize_circuit("hmux0", [], "HMUX0")
    assert result == DeviceType.HEAT_PUMP


# HMUX0 circuit without scan metadata still resolves via prefix
def test_categorize_hmux0_by_prefix() -> None:
    result = DiscoveryService.categorize_circuit("hmux0", [], "")
    assert result == DeviceType.HEAT_PUMP


# SOL00 solar-collector controller is recognized (issue #56)
def test_categorize_sol00_by_scan() -> None:
    result = DiscoveryService.categorize_circuit("sol00", [], "SOL00")
    assert result == DeviceType.SOLAR


# SOL00 circuit without scan metadata still resolves via prefix
def test_categorize_sol00_by_prefix() -> None:
    result = DiscoveryService.categorize_circuit("sol00", [], "")
    assert result == DeviceType.SOLAR


# =============================================================================
# C. Device graph construction (integration tests using fixture data)
# =============================================================================


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


def test_build_graph_categorization() -> None:
    graph = _arotherm_graph()
    for node in graph.nodes.values():
        assert isinstance(node.device_type, DeviceType)
        assert node.device_type != DeviceType.UNKNOWN, f"Circuit {node.circuit} is UNKNOWN"


def test_build_graph_has_data() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["hmu"].has_data is True
    assert graph.nodes["ctlv2"].has_data is True
    assert graph.nodes["z1"].has_data is True
    assert graph.nodes["dhw"].has_data is True
    assert graph.nodes["vwz"].has_data is False


def test_build_graph_zone_mapping() -> None:
    graph = _arotherm_graph()
    ctlv2 = graph.nodes["ctlv2"]
    assert "z1" in ctlv2.zone_circuits
    assert "hc1" in ctlv2.heating_circuits


def test_build_graph_raw_registers_count() -> None:
    graph = _arotherm_graph()
    assert len(graph.raw_registers) > 50
    assert "ctlv2.Z1DayTemp" in graph.raw_registers
    assert "hmu.RunDataStatuscode" in graph.raw_registers


def test_build_graph_placeholder_registers() -> None:
    graph = _arotherm_graph()
    assert len(graph.placeholder_registers) > 100
    assert "hmu.CopCooling" in graph.placeholder_registers


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



# =============================================================================
# D. Community fixture tests
# =============================================================================


def test_categorize_basv_from_community() -> None:
    graph = _basv_graph()
    assert "basv" in graph.nodes
    assert graph.nodes["basv"].device_type == DeviceType.HEATING_CONTROLLER


def test_categorize_vwzio_from_community() -> None:
    graph = _basv_graph()
    assert "vwzio" in graph.nodes
    assert graph.nodes["vwzio"].device_type == DeviceType.PASSIVE_COOLING


def test_categorize_v32_from_community() -> None:
    graph = _v32_graph()
    assert "v32" in graph.nodes
    assert graph.nodes["v32"].device_type == DeviceType.VENTILATION


def test_flexotherm_device_graph() -> None:
    graph = _flexotherm_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["ctlv3"].scan_type in ("CTLV3", "")
    assert "hmu.SourceTempOutput" in graph.raw_registers or "hmu.SourceTempOutput" in graph.placeholder_registers
    assert "hmu.SourceTempInput" not in graph.raw_registers
    assert "hmu.SourceTempInput" not in graph.placeholder_registers


def test_flexotherm_runtime_room_humidity() -> None:
    graph = _flexotherm_graph()
    assert graph.nodes["ctlv2"].device_type == DeviceType.HEATING_CONTROLLER
    assert "ctlv2.z1RoomHumidity" in graph.raw_registers


def test_flexotherm_energy_registers() -> None:
    graph = _flexotherm_graph()
    assert "ctlv3.PrEnergySumHc" in graph.raw_registers
    assert "ctlv3.PrEnergySumHwc" in graph.raw_registers
    assert "ctlv3.PrEnergySum" in graph.placeholder_registers


def test_flexotherm_vr71_mixing_module() -> None:
    graph = _flexotherm_graph()
    assert graph.nodes["vr_71"].device_type == DeviceType.MIXING_MODULE
    assert graph.nodes["vr_71"].scan_type == "VR_71"


def test_arotherm_plus_2zone_graph() -> None:
    graph = _arotherm_plus_2zone_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["ctlv3"].scan_type == "CTLV3"
    assert "hmu.Status01" in graph.raw_registers
    assert "hmu.PowerConsumptionHmu" in graph.raw_registers
    assert "hmu.BuildingCircuitFlow" in graph.placeholder_registers


def test_arotherm_plus_2zone_active_z2() -> None:
    graph = _arotherm_plus_2zone_graph()
    assert graph.nodes["z2"].has_data is True
    assert graph.nodes["z2"].device_type == DeviceType.ZONE
    assert graph.nodes["hc2"].has_data is True
    assert "ctlv3.Z2RoomTemp" in graph.raw_registers
    assert graph.nodes["z3"].has_data is False


def test_arotherm_plus_basv3_graph() -> None:
    graph = _arotherm_plus_basv3_graph()
    assert graph.nodes["basv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["basv3"].scan_type == "BASV3"
    assert graph.nodes["basv3"].scan_sw == "0708"
    assert graph.nodes["basv3"].scan_hw == "4304"
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["vwzio"].device_type == DeviceType.PASSIVE_COOLING


def test_arotherm_plus_basv3_status01_multifield() -> None:
    graph = _arotherm_plus_basv3_graph()
    assert graph.raw_registers["hmu.Status01"] == "39.5;40.5;-;-;-;off"
    assert "basv3.Hc1FlowTemp" in graph.raw_registers


def test_arotherm_plus_basv3_zones() -> None:
    graph = _arotherm_plus_basv3_graph()
    assert graph.nodes["z1"].has_data is True
    assert graph.nodes["z2"].has_data is False
    assert graph.nodes["z3"].has_data is False


def test_arotherm_pro7_graph() -> None:
    graph = _arotherm_pro7_graph()
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["ctlv3"].scan_type in ("CTLV3", "")
    assert graph.nodes["vwzio"].device_type == DeviceType.PASSIVE_COOLING
    assert "hmu" not in graph.nodes
    assert "ctlv3.Z1DayTemp" in graph.raw_registers
    assert "ctlv3.Z1OpMode" in graph.raw_registers


# Pro7 scan metadata (HMUX0) classifies as heat pump even without data
def test_arotherm_pro7_hmux0_scan_classification() -> None:
    result = DiscoveryService.categorize_circuit("hmux0", [], "HMUX0")
    assert result == DeviceType.HEAT_PUMP


# Pro7 scan metadata (SOL00) classifies as solar even without data
def test_arotherm_pro7_sol00_scan_classification() -> None:
    result = DiscoveryService.categorize_circuit("sol00", [], "SOL00")
    assert result == DeviceType.SOLAR


def test_arotherm_pro7_hmu_missing() -> None:
    graph = _arotherm_pro7_graph()
    assert "hmu" not in graph.nodes
    assert "hmu.Status01" not in graph.raw_registers
    assert "hmu.Status01" not in graph.placeholder_registers
    assert graph.nodes["ctlv3"].has_data is False
    assert graph.nodes["z1"].has_data is True


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


def test_flexocompact_hmu_registers() -> None:
    graph = _flexocompact_graph()
    assert "hmu.Status01" in graph.raw_registers
    assert "hmu.CurrentConsumedPower" in graph.raw_registers
    assert "hmu.CurrentYieldPower" in graph.raw_registers
    assert "ctlv2.Z1RoomHumidity" in graph.raw_registers
    assert "hmu.RunDataBuildingCPumpPower" in graph.placeholder_registers
    assert "hmu.RunDataElectricPowerConsumption" in graph.placeholder_registers


def test_community_unknown_circuits() -> None:
    for graph in (_basv_graph(), _v32_graph(), _flexotherm_graph(), _flexocompact_graph()):
        for node in graph.nodes.values():
            assert node.device_type in DeviceType, f"Invalid device type for {node.circuit}"


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


def test_arotherm_ecotec_hmu_registers() -> None:
    graph = _arotherm_ecotec_graph()
    assert "hmu.Status01" in graph.raw_registers
    assert "hmu.FlowTemp" in graph.raw_registers
    assert "hmu.BuildingCircuitFlow" in graph.raw_registers
    assert "ctlv2.Z1RoomHumidity" not in graph.raw_registers
    assert "ctlv2.Z1RoomHumidity" not in graph.placeholder_registers


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
def test_arotherm_plus_cooling_run_graph() -> None:
    graph = _arotherm_plus_cooling_run_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert graph.nodes["vr_71"].device_type == DeviceType.MIXING_MODULE
    assert "hmu.YieldHc" in graph.raw_registers


# aroTHERM Plus HWC-run dump: graph exposes heat pump + controller
def test_arotherm_plus_hwc_run_graph() -> None:
    graph = _arotherm_plus_hwc_run_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv3"].device_type == DeviceType.HEATING_CONTROLLER
    assert "hmu.YieldHwc" in graph.raw_registers
    assert "hmu.RunStatsHwcHours" in graph.raw_registers


# PrEnergySum* stays no-data in both run dumps — entities must still exist
# (enabled but unavailable), never dropped because of transient no-data values.
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


def test_arotherm_plus_ctlv2_cooling_graph() -> None:
    graph = _arotherm_plus_ctlv2_cooling_graph()
    assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
    assert graph.nodes["ctlv2"].device_type == DeviceType.HEATING_CONTROLLER
    assert "hmu.RunDataStatuscode" in graph.raw_registers
    assert "ctlv2.Z1CoolingTemp" in graph.raw_registers


# The ctlv2 cooling run must not invent cooling-program registers that ebusd
# does not expose (they only exist with a 720 room panel / Hc1CoolingEnabled=1).
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


def test_zone_hc_mapping_z2() -> None:
    graph = _arotherm_graph()
    assert "z2" in graph.nodes
    assert "hc2" in graph.nodes
    z2_regs = graph.nodes["z2"].registers
    assert all("Z2" in r for r in z2_regs)


def test_no_pair_when_no_data() -> None:
    graph = _arotherm_graph()
    assert "z2" in graph.nodes
    assert graph.nodes["z2"].has_data is False
    assert "hc2" in graph.nodes
    assert graph.nodes["hc2"].has_data is False


# Intent: retain active Z2 registers when both zones are owned by ctlv2.
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


def test_hidden_broadcast_registers() -> None:
    assert DiscoveryService._is_hidden("Broadcast.id") is True
    assert DiscoveryService._is_hidden("broadcast.signoflife") is True
    assert DiscoveryService._is_hidden("Broadcast.IdAnswer") is True
    assert DiscoveryService._is_hidden("Broadcast.Load") is True


def test_hidden_timer_registers() -> None:
    assert DiscoveryService._is_hidden("ctlv2.cctimer_Config") is True
    assert DiscoveryService._is_hidden("ctlv2.HwcTimer_Monday0") is True
    assert DiscoveryService._is_hidden("ctlv2.Z1Timer_Friday0") is True


def test_known_register_not_hidden() -> None:
    assert DiscoveryService._is_hidden("hmu.Status01") is False
    assert DiscoveryService._is_hidden("ctlv2.Z1DayTemp") is False
    assert DiscoveryService._is_hidden("ctlv2.HwcOpMode") is False


def test_hidden_specific_registers() -> None:
    assert DiscoveryService._is_hidden("hmu.FlowTemperature") is True
    assert DiscoveryService._is_hidden("Broadcast.FlowTemp") is True


def test_hidden_memory_circuit() -> None:
    assert DiscoveryService._is_hidden("memory.eeprom") is True
    assert DiscoveryService._is_hidden("Memory.Ram") is True


def test_hidden_general_circuit() -> None:
    assert DiscoveryService._is_hidden("general.whatever") is True


def test_hidden_scan_lines() -> None:
    assert DiscoveryService._is_hidden("scan.08.x") is True


def test_hidden_installer_registers() -> None:
    assert DiscoveryService._is_hidden("ctlv2.Installer1") is True
    assert DiscoveryService._is_hidden("ctlv2.PhoneNumber1") is True
    assert DiscoveryService._is_hidden("ctlv2.KeyCodeforConfigMenu") is True
    assert DiscoveryService._is_hidden("ctlv2.MaintenanceDate") is True


def test_hidden_prfuelsum() -> None:
    assert DiscoveryService._is_hidden("ctlv2.PrFuelSumHc") is True


def test_broadcast_not_hidden_outside_broadcast() -> None:
    assert DiscoveryService._is_hidden("ctlv2.id") is False


# =============================================================================
# G. Relationship determination
# =============================================================================


def test_relationships_controller_parent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["ctlv2"].parent == "hmu"


def test_relationships_zone_parent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["z1"].parent == "ctlv2"


def test_relationships_dhw_parent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["dhw"].parent == "ctlv2"


def test_relationships_hc_parent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["hc1"].parent == "ctlv2"


def test_relationships_vwz_independent() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["vwz"].parent is None


def test_relationships_broadcast_parent() -> None:
    graph = _arotherm_graph()
    assert "Broadcast" not in graph.nodes


def test_relationships_hmu_is_root() -> None:
    graph = _arotherm_graph()
    assert graph.nodes["hmu"].parent is None


def test_relationships_vwzio_independent() -> None:
    graph = _basv_graph()
    assert graph.nodes["vwzio"].parent is None


def test_relationships_v32_independent() -> None:
    graph = _v32_graph()
    assert graph.nodes["v32"].parent is None


# =============================================================================
# Additional edge case tests
# =============================================================================


def test_parse_register_simple() -> None:
    c, n, v = DiscoveryService._parse_register("hmu Status01 = 58.0")
    assert c == "hmu"
    assert n == "Status01"
    assert v == "58.0"


def test_parse_register_no_data() -> None:
    c, n, v = DiscoveryService._parse_register("hmu CopCooling = no data stored")
    assert c == "hmu"
    assert n == "CopCooling"
    assert v is None


def test_parse_register_empty_with_meta() -> None:
    c, n, v = DiscoveryService._parse_register(
        "ctlv2 HcStorageTempBottom =  (empty for f115b5240602000000a000 / 080000a000ffffff7f)"
    )
    assert v is None


def test_parse_register_partial_value_with_error_is_unavailable() -> None:
    _, _, value = DiscoveryService._parse_register(
        "sc YieldThisYear = 0;32768;13056;0 (ERR: invalid position)"
    )
    assert value is None


def test_scan_metadata_present_in_nodes() -> None:
    graph = _arotherm_graph()
    hmu = graph.nodes["hmu"]
    assert hmu.scan_type == "HMU00"
    assert hmu.scan_sw == "0522"
    assert hmu.scan_hw == "5103"
    ctlv2 = graph.nodes["ctlv2"]
    assert ctlv2.scan_type == "CTLV2"


def test_scan_metadata_in_basv_graph() -> None:
    graph = _basv_graph()
    assert graph.nodes["hmu"].scan_type == "HMU00"
    assert graph.nodes["basv"].scan_type == "BASV2"
    assert graph.nodes["vwzio"].scan_type == "VWZIO"


# =============================================================================
# H. Integration tests with FakeEbusdServer
# =============================================================================


async def test_integration_arotherm_discover_device_types() -> None:
    async with FakeEbusdServer("arotherm_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        graph = await svc.discover()
        await svc._ebus.disconnect()

        assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP
        assert graph.nodes["ctlv2"].device_type == DeviceType.HEATING_CONTROLLER
        assert "Broadcast" not in graph.nodes


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
        assert len(graph.raw_registers) == 77


async def test_integration_basv_controller_type() -> None:
    async with FakeEbusdServer("community/basv_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        graph = await svc.discover()
        await svc._ebus.disconnect()

        assert "basv" in graph.nodes
        assert graph.nodes["basv"].device_type == DeviceType.HEATING_CONTROLLER
        assert graph.nodes["hmu"].device_type == DeviceType.HEAT_PUMP


async def test_integration_v32_ventilation_type() -> None:
    async with FakeEbusdServer("community/v32_find.txt") as fake:
        svc = DiscoveryService(EbusService(host=fake.host, port=fake.port))
        await svc._ebus.connect()
        graph = await svc.discover()
        await svc._ebus.disconnect()

        assert "v32" in graph.nodes
        assert graph.nodes["v32"].device_type == DeviceType.VENTILATION
        assert graph.nodes["v32"].has_data is True


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
