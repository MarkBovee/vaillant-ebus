"""Regression coverage for the latest community captures from issues #99/#103."""

from __future__ import annotations

import pytest

from tests.fake_ebusd import load_discovery_dump, load_find_lines
from tests.test_entity_factory import DiscoveryService, EntityFactoryService


# Intent: the derived Energy Manager State honours a real cooling capture.
# Why: issue #102 - the state must be derived from the actual compressor status,
# not assumed from the register presence.
def test_cooling_capture_derives_cooling_operating_state() -> None:
    from tests.test_compressor_power import derive_operating_state

    graph = DiscoveryService.build_device_graph(load_find_lines("community/arotherm_plus_cooling_run_discovery.yaml"))
    values = {f"{key}.value": value for key, value in graph.raw_registers.items()}

    assert graph.raw_registers["hmu.RunDataStatuscode"] == "cool_compressor_active"
    assert derive_operating_state(values, "hmu") == "Cooling"


# Intent: issue #102 capture (HMU00/CTLV3) keeps RunDataStatuscode at 0 while a
# cooling period is active; the Energy Manager State must derive Cooling from
# the only available signal, SetMode.releaseCooling.
# Why: on these units Status00/Status07 are absent, so without the request flag
# the sensor would report Standby during active cooling.
def test_issue102_cooling_capture_derives_cooling_state() -> None:
    from tests.test_compressor_power import derive_operating_state

    graph = DiscoveryService.build_device_graph(
        load_find_lines("community/arotherm_plus_issue102_cooling_discovery.yaml")
    )
    values = {f"{key}.value": value for key, value in graph.raw_registers.items()}

    assert graph.raw_registers["hmu.RunDataStatuscode"] == "0"
    assert graph.raw_registers["hmu.SetMode"].split(";")[9] == "1"
    assert derive_operating_state(values, "hmu") == "Cooling"


# Intent: the derived Energy Manager State honours a real DHW-active capture.
# Why: issue #102 - DHW demand must map to the DHW state from live compressor data.
def test_dhw_capture_derives_dhw_operating_state() -> None:
    from tests.test_compressor_power import derive_operating_state

    graph = DiscoveryService.build_device_graph(load_find_lines("community/arotherm_basv_boost_on_discovery.yaml"))
    values = {f"{key}.value": value for key, value in graph.raw_registers.items()}

    assert graph.raw_registers["hmu.RunDataStatuscode"] == "hwc_compressor_active"
    assert derive_operating_state(values, "hmu") == "DHW"


# Intent: the eloblock VE28 fixture exposes observed bai registers with metadata.
# Why: community boiler captures must produce typed, correctly-labeled entities.
def test_eloblock_ve28_exposes_observed_bai_registers() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/eloblock_ve28_discovery.yaml"))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert graph.nodes["bai"].device_type.name == "HEATING_CONTROLLER"
    for register in ("FlowTemp", "FlowTempDesired", "StorageTemp", "StorageTempDesired", "WaterPressure"):
        assert f"bai.{register}.value" in entities

    assert entities["bai.FlowTemp.value"].meta.device_class == "temperature"
    assert entities["bai.FlowTemp.value"].meta.unit == "°C"
    assert entities["bai.WaterPressure.value"].meta.device_class == "pressure"
    assert entities["bai.WaterPressure.value"].meta.unit == "bar"
    assert entities["bai.Status01.temp"].meta.device_class == "temperature"
    assert entities["bai.Status01.temp_1"].meta.device_class == "temperature"
    assert entities["bai.Gasvalve.value"].enabled_by_default is False
    assert entities["bai.FanSpeed.value"].enabled_by_default is False
    assert entities["bai.Flame.value"].enabled_by_default is False


# Intent: VWZIO/VWZ Status01 is parsed into the six shared status fields.
# Why: upstream PR #598 - the Hydraulikstation reuses the HMU Status01 layout,
# so its flow/storage/outside/pump values must reach HA as typed sensors.
def test_vwz_status01_fields_are_parsed() -> None:
    graph = DiscoveryService.build_device_graph(["vwz Status01 = 23.0;22.5;15.98;-;38.0;off"])
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    for field, expected in (
        ("temp", "23.0"),
        ("temp_1", "22.5"),
        ("temp_2", "15.98"),
        ("temp_3", "-"),
        ("temp_4", "38.0"),
        ("pumpstate", "off"),
    ):
        key = f"vwz.Status01.{field}"
        assert key in entities
        assert entities[key].raw_value == expected

    assert entities["vwz.Status01.temp"].meta.device_class == "temperature"
    # Outside and storage are enabled for the Hydraulikstation, unlike the
    # shared HMU mapping where they are disabled (exposed elsewhere).
    assert entities["vwz.Status01.temp_2"].enabled_by_default is True
    assert entities["vwz.Status01.temp_4"].enabled_by_default is True


# Intent: BAI HeatingSwitch/HwcSwitch become writable switch entities.
# Why: issue #111 - the eloBLOCK VE 28 exposes these registers and they are the
# reliable on/off control, unlike the absent SetModeOverride.
def test_bai_heating_and_hwc_switches_are_switch_entities() -> None:
    graph = DiscoveryService.build_device_graph(["bai HeatingSwitch = on", "bai HwcSwitch = off"])
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert entities["bai.HeatingSwitch.value"].meta.entity_type == "switch"
    assert entities["bai.HwcSwitch.value"].meta.entity_type == "switch"
    assert entities["bai.HeatingSwitch.value"].meta.friendly_name == "Heating Switch"
    assert entities["bai.HeatingSwitch.value"].enabled_by_default is True


# Intent: the latest issue #99 HMUX0 values keep entity metadata and raw values.
# Why: issue #99 - HMUX0 telemetry entities must stay available and typed.
def test_hmux0_latest_issue99_values_keep_entity_metadata() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/hmux0_issue99_latest_find.txt"))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    for register in (
        "RunDataReturnTemp",
        "YieldHc",
        "YieldHcDay",
        "YieldHcMonth",
        "YieldHwc",
        "YieldHwcDay",
        "YieldHwcMonth",
        "CopHc",
        "CopHcMonth",
        "CopHwc",
        "CopHwcMonth",
    ):
        assert f"hmux0.{register}.value" in entities

    assert entities["hmux0.RunDataReturnTemp.value"].raw_value == "28.2184"
    assert entities["hmux0.RunDataReturnTemp.value"].meta.device_class == "temperature"
    assert entities["hmux0.YieldHc.value"].meta.device_class == "energy"
    assert entities["hmux0.Status01.temp"].meta.device_class == "temperature"


# Intent: issue #99 dumps keep ctlv3 DHW values and reject invalid HMUX0 return temperature.
# Why: issue #99 - spurious hmux0 readings must not overwrite valid controller data.
@pytest.mark.parametrize(
    ("fixture", "invalid_return_temperature"),
    (
        ("community/hmux0_issue99_2026-09-10_170850.yaml", "1082.88"),
        ("community/hmux0_issue99_2026-09-10_173229.yaml", "-423.75"),
    ),
)
def test_latest_issue99_dumps_keep_ctlv3_dhw_and_reject_invalid_hmux0_temperature(
    fixture: str, invalid_return_temperature: str
) -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert graph.nodes["hmux0"].device_type.name == "HEAT_PUMP"
    assert graph.nodes["ctlv3"].device_type.name == "HEATING_CONTROLLER"
    assert graph.raw_registers["ctlv3.HwcOpMode"] == "auto"
    assert graph.raw_registers["ctlv3.HwcSFMode"] == "auto"
    assert graph.raw_registers["ctlv3.HwcStorageTemp"] == "45"
    assert graph.raw_registers["ctlv3.HwcTempDesired"] == "48"
    assert graph.raw_registers["ctlv3.HwcHolidayStartPeriod"] == "01.01.2015"
    assert graph.raw_registers["ctlv3.HwcHolidayEndPeriod"] == "01.01.2015"
    assert "hmux0.RunDataReturnTemp" not in graph.raw_registers
    assert "hmux0.RunDataReturnTemp" in graph.placeholder_registers
    assert entities["hmux0.RunDataReturnTemp.value"].raw_value == ""
    assert entities["hmux0.RunDataReturnTemp.value"].raw_value != invalid_return_temperature

    for register in ("YieldHc", "YieldHwc", "CopHc", "CopHwc"):
        assert graph.raw_registers[f"hmux0.{register}"]


# Intent: Pro7 quiet-mode captures load but expose no NoiseReduction/DeicingActive entities.
# Why: absent quiet registers must not be fabricated from captures.
@pytest.mark.parametrize(
    "fixture",
    (
        "community/arotherm_pro7_quiet_off_idle_discovery.yaml",
        "community/arotherm_pro7_quiet_off_heating_discovery.yaml",
        "community/arotherm_pro7_quiet_on_heating_discovery.yaml",
    ),
)
def test_arotherm_pro7_quiet_captures_load_without_quiet_registers(fixture: str) -> None:
    dump = load_discovery_dump(fixture)
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture))
    names = {f"{node.circuit}.{register}" for node in graph.nodes.values() for register in node.registers}

    assert dump["raw_find_lines"]
    assert any("scan.08" in line for line in dump["raw_find_lines"])
    assert graph.nodes["hmu"].device_type.name == "HEAT_PUMP"
    assert not any("NoiseReduction" in name or "DeicingActive" in name for name in names)


# Intent: the HMUX0 DHW holiday capture keeps ctlv3 values and treats invalid HMUX0 telemetry as placeholder.
# Why: issues #99/#103 - controller values and sentinel handling must survive the capture.
def test_hmux0_dhw_holiday_capture_keeps_controller_values_and_sentinels_unavailable() -> None:
    dump = load_discovery_dump("community/arotherm_hmux0_dhw_holiday_discovery.yaml")
    graph = DiscoveryService.build_device_graph(load_find_lines("community/arotherm_hmux0_dhw_holiday_discovery.yaml"))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert dump["raw_find_lines"]
    assert graph.nodes["hmux0"].device_type.name == "HEAT_PUMP"
    assert graph.nodes["ctlv3"].device_type.name == "HEATING_CONTROLLER"

    # DHW and controller values are on ctlv3
    assert graph.raw_registers["ctlv3.HwcStorageTemp"] == "42"
    assert graph.raw_registers["ctlv3.HwcTempDesired"] == "50"
    assert graph.raw_registers["ctlv3.HwcOpMode"] == "auto"
    assert graph.raw_registers["ctlv3.HwcSFMode"] == "auto"
    assert graph.raw_registers["ctlv3.HwcHolidayStartPeriod"] == "01.01.2015"
    assert graph.raw_registers["ctlv3.HwcHolidayEndPeriod"] == "01.01.2015"
    assert graph.raw_registers["ctlv3.PrEnergySumHwc"] == "327"

    assert "ctlv3.HwcStorageTemp.value" in entities
    assert entities["ctlv3.HwcStorageTemp.value"].meta.device_class == "temperature"
    assert entities["ctlv3.HwcStorageTemp.value"].meta.unit == "°C"
    assert "ctlv3.HwcTempDesired.value" in entities
    assert "ctlv3.HwcOpMode.value" in entities
    assert "ctlv3.PrEnergySumHwc.value" in entities

    # HMUX0 heat pump telemetry
    assert "hmux0.CopHc.value" in entities
    assert "hmux0.CopHwc.value" in entities
    assert "hmux0.BuildingCircuitFlow.value" in entities

    # Invalid position registers in discovery must have no data and be classified as placeholder
    assert "hmux0.ConsumptionTotal" in graph.placeholder_registers
    assert "hmux0.ConsumptionTotal" not in graph.raw_registers


# Intent: future Z1 holiday dates survive discovery as ctlv3 values.
# Why: holiday scheduling must not be lost or defaulted to a sentinel.
def test_hmux0_holiday_capture_keeps_future_zone_holiday_values() -> None:
    """Controller holiday dates must survive discovery as ctlv3 values."""
    dump = load_discovery_dump("community/arotherm_hmux0_dhw_holiday_discovery.yaml")
    graph = DiscoveryService.build_device_graph(load_find_lines("community/arotherm_hmux0_dhw_holiday_discovery.yaml"))

    assert dump["metadata"]["dump_version"] == 3
    assert graph.raw_registers["ctlv3.Z1HolidayStartPeriod"] == "26.09.2026"
    assert graph.raw_registers["ctlv3.Z1HolidayEndPeriod"] == "09.10.2027"


# Intent: ecoTEC VRT380 captures expose bai entities and a controller graph.
# Why: boiler hardware must be discoverable with its observed register set.
@pytest.mark.parametrize(
    "fixture",
    (
        "community/ecotec_vrt380_15700_discovery.yaml",
        "community/ecotec_vrt380_ctlv2_discovery.yaml",
    ),
)
def test_ecotec_vrt380_captures_expose_bai_and_controller_graph(fixture: str) -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert graph.nodes["bai"].device_type.name == "HEATING_CONTROLLER"
    assert "bai.FlowTemp.value" in entities
    assert "bai.StorageTemp.value" in entities


# Issue #109: the boiler bus exposes both a BAI burner interface and a CTLV0
# controller. Both list a DHW setpoint register, which previously left the
# controller AMBIGUOUS and let the bare runtime `ctlv2` probe alias become the
# resolved heating circuit, so HA writes targeted a circuit that does not exist.
# Intent: the real ctlv0 controller wins over bai and the bare ctlv2 alias.
# Why: issue #109 - HA writes must target the discovered controller circuit.
@pytest.mark.parametrize(
    "fixture",
    (
        "community/ecotec_vrt380_15700_discovery.yaml",
        "community/ecotec_vrt380_ctlv2_discovery.yaml",
    ),
)
def test_ecotec_vrt380_resolves_real_controller_not_bare_probe(fixture: str) -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture))

    result = graph.heating_controller_result()
    assert result.status.name == "UNIQUE"
    assert result.circuit == "ctlv0"
    # The logical ctlv2 metadata alias must route to the discovered ctlv0.
    assert graph.resolve_circuit_result("ctlv2").circuit == "ctlv0"


# Issue #109: a boiler-only bus reports only runtime-defined b516 `hmu` energy
# probes (created by the integration's generic define pass), which used to
# surface as a phantom aroTHERM heat-pump device.
# Intent: a BAI bus with no heat-pump scan exposes no hmu heat-pump node.
# Why: issue #109 - no phantom heat-pump device on boiler-only hardware.
def test_ecotec_vrt380_boiler_bus_has_no_phantom_heat_pump() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/ecotec_vrt380_15700_discovery.yaml"))

    assert "hmu" not in graph.nodes
    assert graph.heat_pump_result().status.name == "MISSING"
    entities = EntityFactoryService().generate(graph)
    assert not any(entity.device_circuit == "hmu" for entity in entities)


# Intent: a real HMU00 heat pump scan keeps its hmu node and is not suppressed.
# Why: the boiler-only suppression must not affect genuine heat-pump buses.
def test_ecotec_heat_pump_bus_keeps_hmu_node() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/arotherm_ecotec_discovery.yaml"))

    assert graph.nodes["hmu"].device_type.name == "HEAT_PUMP"
    assert graph.heat_pump_result().circuit == "hmu"


# Intent: ecoTEC BAI flow and fuel registers expose Home Assistant metadata.
# Why: these registers are present in the discovery graph even when the boiler
# reports no data, so their metadata must remain covered independently of value availability.
def test_ecotec_vrt380_bai_flow_and_fuel_metadata() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/ecotec_vrt380_15700_discovery.yaml"))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    for register in (
        "HwcWaterflow",
        "PrimaryCircuitFlowrate",
        "StatFuelSum",
        "StatFuelSumHc",
        "StatFuelSumHwc",
    ):
        assert f"bai.{register}.value" in entities

    for register in ("HwcWaterflow", "PrimaryCircuitFlowrate"):
        meta = entities[f"bai.{register}.value"].meta
        assert meta.device_class == "volume_flow_rate"
        assert meta.unit == "L/min"
        assert meta.state_class == "measurement"

    for register in ("StatFuelSum", "StatFuelSumHc", "StatFuelSumHwc"):
        meta = entities[f"bai.{register}.value"].meta
        assert meta.device_class == "energy"
        assert meta.unit == "kWh"
        assert meta.state_class == "total_increasing"
