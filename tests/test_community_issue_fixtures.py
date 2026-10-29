"""Regression coverage for the latest community captures from issues #99/#103."""

from __future__ import annotations

import struct

import pytest
import yaml
from vaillant_ebus.backend.models import valid_zone_owners  # noqa: E402

from tests.fake_ebusd import FIXTURES_DIR, load_discovery_dump, load_find_lines
from tests.test_entity_factory import MAPPING, DiscoveryService, EntityFactoryService


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

    graph = DiscoveryService.build_device_graph(load_find_lines("community/flexotherm_issue102_cooling_discovery.yaml"))
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


# Intent: the existing HMUX0 fixture keeps the B509 compressor-speed unit stable on the legacy gate.
# Why: extending the SW0302/SW0303 B509 definitions must not silently change the value contract for SW0303.
def test_hmux0_fixture_keeps_b509_compressor_speed_unit() -> None:
    lines = load_find_lines("community/hmux0_issue99_2026-09-10_173229.yaml", after=True)
    lines.append("hmux0 RunDataCompressorSpeed = 0")
    graph = DiscoveryService.build_device_graph(lines)
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert entities["hmux0.RunDataCompressorSpeed.value"].meta.unit == "rps"


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


# Intent: the issue #99 aroTHERM Pro 35 dump exposes HwcStorageTemp only as an
# unavailable (ERR) register, not as live find data.
# Why: issue #99 - a register that is no longer readable must not feed a frozen
# entity value; the sensor/coordinator changes report unknown instead.
def test_arotherm_pro35_hwcstoragetemp_not_live() -> None:
    graph = DiscoveryService.build_device_graph(
        load_find_lines("community/arotherm_pro35_issue99_2026-09-13_162416.yaml")
    )
    assert "ctlv2.HwcStorageTemp" not in graph.raw_registers
    assert graph.raw_registers["hmu.RunDataStatuscode"] == "standby"


# Intent: the issue #99 HMUX0/CTLV3 dump resolves the holiday period registers
# to the discovered controller circuit with live dates.
# Why: issue #99 - holiday date writes must target the discovered circuit
# (ctlv3), and the read side carries the real app-set dates.
def test_hmux0_issue99_holiday_registers_on_ctlv3() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/hmux0_issue99_2026-09-13_173740.yaml"))
    assert graph.raw_registers["ctlv3.HwcHolidayStartPeriod"] == "23.09.2026"
    assert graph.raw_registers["ctlv3.HwcHolidayEndPeriod"] == "31.10.2026"


# Intent: the issue #111 eloBLOCK VE 28 dump exposes the bai switch registers
# as unavailable, not as live values.
# Why: issue #111 - HeatingSwitch/HwcSwitch read back as unavailable until the
# integration redefines them writable at runtime on B509.
def test_eloblock_ve28_switches_unavailable_in_find() -> None:
    graph = DiscoveryService.build_device_graph(
        load_find_lines("community/eloblock_ve28_issue111_2026-09-11_193100.yaml")
    )
    assert "bai.HeatingSwitch" not in graph.raw_registers
    assert "bai.HwcSwitch" not in graph.raw_registers


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


# Intent: issue #161's CTLV3 yield and HMUX0 daily counters expose supported energy metadata.
# Why: the capture verifies the register owners and values; missing yield data must remain unavailable.
def test_issue161_energy_metadata_and_absent_yield_path() -> None:
    fixture = "community/hmux0_issue161_2026-09-28_154109_discovery.yaml"
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert graph.raw_registers["ctlv3.YieldTotal"] == "70"
    yield_total = entities["ctlv3.YieldTotal.value"]
    assert yield_total.meta.device_class == "energy"
    assert yield_total.meta.unit == "kWh"
    assert yield_total.meta.state_class == "total"
    assert yield_total.meta.fallback_read is False

    for key in ("hmux0.HcElecConsDay.value", "hmux0.HwcElecConsDay.value"):
        assert key in entities
        assert entities[key].meta.device_class == "energy"
        assert entities[key].meta.unit == "Wh"
        assert entities[key].meta.state_class == "total_increasing"

    absent_graph = DiscoveryService.build_device_graph(
        ["scan.15 = MF=Vaillant;ID=CTLV3;SW=0813;HW=8004", "ctlv3 YieldTotal = no data stored"]
    )
    assert "ctlv3.YieldTotal" in absent_graph.placeholder_registers
    assert "ctlv3.YieldTotal.value" not in {entity.key for entity in EntityFactoryService().generate(absent_graph)}


# Intent: issue #161's raw HMUX0 frames decode all six B516 environmental-yield values.
# Why: the fixture combines the exact-scan full dump with unmodified PR frames and guards their message layout.
def test_issue161_envyield_raw_frames_decode_and_absent_path() -> None:
    evidence = load_discovery_dump("community/hmux0_issue161_envyield_b516_2026-09-30.yaml")
    context_name = evidence["metadata"]["scan_context_fixture"]
    context = load_discovery_dump(context_name)
    scan = evidence["metadata"]["scan"]
    scan_config = context["metadata"]["ebusd_info"]["loaded_configs"][scan["address"]]
    assert scan_config["scanned"] == f"MF={scan['manufacturer']};ID={scan['id']};SW={scan['sw']};HW={scan['hw']}"
    assert evidence["metadata"]["ebusd_version"] == "26.1.26.1"
    assert len(evidence["registers"]) == 6

    register_lines = []
    values = {}
    for item in evidence["registers"]:
        assert len(item["log_lines"]) == 2
        assert f"sent read hmux0 {item['name']}: {item['displayed_value']}" in item["log_lines"][0]
        bus_line = item["log_lines"][1]
        wire_request, wire_response = (
            bus_line.split(">", 1)[1].split("<", 1)[0],
            bus_line.split("<", 1)[1].split(">", 1)[0],
        )
        assert wire_request[10:-2] == item["request_data"]
        response = bytes.fromhex(wire_response)
        assert response[0] == 0
        assert response[1] == len(response[2:-1])
        decoded_value = struct.unpack_from("<f", response, 2 + 7)[0]
        displayed_value = float(item["displayed_value"])
        decimal_places = len(item["displayed_value"].partition(".")[2])
        assert round(decoded_value, decimal_places) == displayed_value
        values[item["name"]] = decoded_value
        register_lines.append(f"hmux0 {item['name']} = {decoded_value}")

    assert "02033235" in evidence["registers"][2]["log_lines"][1]
    assert "02033e35" in evidence["registers"][2]["log_lines"][1]

    graph = DiscoveryService.build_device_graph(load_find_lines(context_name, after=True) + register_lines)
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}
    for name in values:
        meta = entities[f"hmux0.{name}.value"].meta
        assert meta.device_class == "energy"
        assert meta.unit == "Wh"
        assert meta.state_class == "total_increasing"

    for unavailable in ("no data stored", "(ERR: element not found)"):
        absent_graph = DiscoveryService.build_device_graph(
            load_find_lines(context_name, after=True)
            + [f"hmux0 {item['name']} = {unavailable}" for item in evidence["registers"]]
        )
        absent_entities = {entity.key for entity in EntityFactoryService().generate(absent_graph)}
        assert not any(f"hmux0.{item['name']}.value" in absent_entities for item in evidence["registers"])


# Intent: issue #161 retains scanned VWZIO identity even before a matching CSV exposes registers.
# Why: passive station telemetry must be gated to the physical scan, not a guessed address or virtual device.
def test_issue161_scan_only_vwzio_node_and_missing_scan_path() -> None:
    fixture = "community/hmux0_issue161_2026-09-28_154109_discovery.yaml"
    graph = DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))

    vwzio = graph.nodes["vwzio"]
    assert vwzio.device_type.name == "PASSIVE_COOLING"
    assert (vwzio.scan_type, vwzio.scan_sw, vwzio.scan_hw) == ("VWZIO", "0500", "0504")
    assert not vwzio.registers
    assert not any(entity.device_circuit == "vwzio" for entity in EntityFactoryService().generate(graph))

    without_vwzio_scan = [
        line for line in load_find_lines(fixture, after=True) if not line.strip().startswith("scan.76 ")
    ]
    absent_graph = DiscoveryService.build_device_graph(without_vwzio_scan)
    assert "vwzio" not in absent_graph.nodes

    nonmatching_scan = [
        line.replace("VWZIO;0500;0504", "VWZIO;0902;5103") if line.strip().startswith("scan.76 ") else line
        for line in load_find_lines(fixture, after=True)
    ]
    nonmatching_graph = DiscoveryService.build_device_graph(nonmatching_scan)
    assert "vwzio" not in nonmatching_graph.nodes


# Intent: the exact HW0504 B511/021802 frames decode to the correlated runtime/start deltas.
# Why: the upstream field layout is from HW5103, so this target variant needs capture-backed regression coverage.
def test_issue161_vwzio_hwc_runtime_frames_match_heater_cycles() -> None:
    from vaillant_ebus.backend.mapping import REGISTER_MAP

    baseline_name = "community/hmux0_issue161_2026-09-28_154109_discovery.yaml"
    later_name = "community/hmux0_issue161_2026-09-30_161313_discovery.yaml"
    baseline = load_discovery_dump(baseline_name)
    later = load_discovery_dump(later_name)

    decoded = []
    for dump, expected in ((baseline, (69, 2)), (later, (106, 4))):
        scan = dump["metadata"]["ebusd_info"]["loaded_configs"]["76"]["scanned"]
        assert scan == "MF=Vaillant;ID=VWZIO;SW=0500;HW=0504"
        row = next(item for item in dump["unknown_telegrams"] if item["request"] == "f176b511021802")
        response = bytes.fromhex(row["resp"])
        assert response[0] == 9
        assert len(response) == 10
        values = (
            int.from_bytes(response[2:6], "little"),
            int.from_bytes(response[6:10], "little"),
        )
        assert values == expected
        decoded.append(values)

    assert (decoded[1][0] - decoded[0][0], decoded[1][1] - decoded[0][1]) == (37, 2)

    graph = DiscoveryService.build_device_graph(
        load_find_lines(later_name, after=True) + ["vwzio RunStatsImmersionHeaterHwc = 106;4"]
    )
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}
    runtime = entities["vwzio.RunStatsImmersionHeaterHwc.runtime"].meta
    starts = entities["vwzio.RunStatsImmersionHeaterHwc.cycles"].meta
    assert runtime.device_class == "duration"
    assert runtime.unit == "min"
    assert runtime.state_class == "total_increasing"
    assert starts.state_class == "total_increasing"
    assert REGISTER_MAP["vwzio.RunStatsImmersionHeaterHwc"].fallback_read is False

    absent_graph = DiscoveryService.build_device_graph(load_find_lines(later_name, after=True))
    absent_keys = {entity.key for entity in EntityFactoryService().generate(absent_graph)}
    assert not any(key.startswith("vwzio.RunStatsImmersionHeaterHwc") for key in absent_keys)


# Intent: the shared HWC counter metadata applies to HW5103 only when its ebusd graph exposes the register.
# Why: upstream PR #598 confirms the same frame layout on HW5103, while absent graph data must create no entity.
def test_issue598_vwzio_hw5103_counter_metadata_is_graph_driven() -> None:
    from vaillant_ebus.backend.mapping import REGISTER_MAP

    evidence = yaml.safe_load((FIXTURES_DIR / "community/vwzio_hw5103_pr598_b511_stats.yaml").read_text())
    assert evidence["source"] == "https://github.com/john30/ebusd-configuration/pull/598"

    for system in evidence["systems"].values():
        for frame in system["frames"]:
            response = bytes.fromhex(frame["response"])
            assert frame["request"].startswith("f176b5110218")
            assert response[0] == 9
            assert int.from_bytes(response[2:6], "little") == frame["runtime_minutes"]
            assert int.from_bytes(response[6:10], "little") == frame["starts"]

    system = evidence["systems"]["pr_author_install"]
    graph = DiscoveryService.build_device_graph(
        [f"scan.76 = {system['scan']}", "vwzio RunStatsImmersionHeaterHwc = 2596;61"]
    )
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}
    assert entities["vwzio.RunStatsImmersionHeaterHwc.runtime"].raw_value == "2596"
    assert entities["vwzio.RunStatsImmersionHeaterHwc.cycles"].raw_value == "61"
    assert REGISTER_MAP["vwzio.RunStatsImmersionHeaterHwc"].fallback_read is False

    absent_graph = DiscoveryService.build_device_graph([f"scan.76 = {system['scan']}"])
    absent_keys = {entity.key for entity in EntityFactoryService().generate(absent_graph)}
    assert not any(key.startswith("vwzio.RunStatsImmersionHeaterHwc") for key in absent_keys)


# Intent: issue #161's passive VWZIO power readings track the reported active and idle station states.
# Why: the feature is hydraulic-station power, not a heater-only measurement or a plausible-value guess.
@pytest.mark.parametrize(
    ("fixture", "expected_kw", "expected_status"),
    (
        ("community/hmux0_issue161_2026-09-30_130640_discovery.yaml", 4.695, 2),
        ("community/hmux0_issue161_2026-09-30_132044_discovery.yaml", 0.005, 0),
        ("community/hmux0_issue161_2026-09-30_154054_discovery.yaml", 0.005, 0),
        ("community/hmux0_issue161_2026-09-30_161313_discovery.yaml", 0.005, 0),
    ),
)
def test_issue161_vwzio_station_power_tracks_captured_state(
    fixture: str, expected_kw: float, expected_status: int
) -> None:
    dump = load_discovery_dump(fixture)
    scan = dump["metadata"]["ebusd_info"]["loaded_configs"]["76"]["scanned"]
    assert scan == "MF=Vaillant;ID=VWZIO;SW=0500;HW=0504"
    row = next(item for item in dump["unknown_telegrams"] if item["request"] == "f176b5160114")
    response = bytes.fromhex(row["resp"])
    assert response[0] == 9
    assert response[1] == expected_status
    power_kw = struct.unpack_from("<f", response, 2)[0] / 1000
    assert power_kw == pytest.approx(expected_kw)

    graph = DiscoveryService.build_device_graph(
        load_find_lines(fixture, after=True) + [f"vwzio PowerConsumptionVwz = {power_kw}"]
    )
    entity = {item.key: item for item in EntityFactoryService().generate(graph)}["vwzio.PowerConsumptionVwz.value"]
    assert entity.meta.device_class == "power"
    assert entity.meta.unit == "kW"
    assert entity.meta.fallback_read is False


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


# Intent: the heat-pump product name and manufacturer derive from the scan
# metadata (VWZ module + heat-pump scan_hw), so a flexoTHERM is never labeled
# as an aroTHERM. Issue #134 (device display name).
# Why: the shared hmu circuit hosts flexoTHERM, aroTHERM and GeniaSet units;
# their names must track the discovered hardware, not a hardcoded marketing name.
def test_heat_pump_product_name_is_scan_aware() -> None:
    from vaillant_ebus.backend.models import heat_pump_product

    cases = [
        # (fixture, expected_name, expected_manufacturer)
        ("community/flexotherm_discovery.yaml", "Vaillant flexoTHERM heat pump", "Vaillant"),
        ("community/flexotherm_issue102_cooling_discovery.yaml", "Vaillant flexoTHERM heat pump", "Vaillant"),
        ("community/flexotherm_ctlv2_cooling_discovery.yaml", "Vaillant flexoTHERM heat pump", "Vaillant"),
        ("community/flexotherm_vwf1174_issue134_2026-09-15_162647.yaml", "Vaillant flexoTHERM heat pump", "Vaillant"),
        ("community/arotherm_plus_2zone_discovery.yaml", "Vaillant aroTHERM heat pump", "Vaillant"),
        ("community/arotherm_pro7_discovery.yaml", "Vaillant aroTHERM heat pump", "Vaillant"),
        ("community/geniaset_bass3_discovery.yaml", "Saunier Duval GeniaSet heat pump", "Saunier Duval"),
    ]
    for fixture, expected_name, expected_manufacturer in cases:
        graph = DiscoveryService.build_device_graph(load_find_lines(fixture))
        name, manufacturer = heat_pump_product(graph)
        assert name == expected_name, f"{fixture}: name {name!r} != {expected_name!r}"
        assert manufacturer == expected_manufacturer, f"{fixture}: manufacturer {manufacturer!r}"


# Intent: issue #137 VRC700 DHW registers become part of the controller graph.
# Why: the community dump proves ebusd exposes the controller as numeric circuit
# 700 with scan identity 70000.
def test_vrc700_fixture_discovers_numeric_controller_and_dhw() -> None:
    graph = DiscoveryService.build_device_graph(
        load_find_lines("community/flexotherm_vwf1174_issue134_2026-09-15_162647.yaml")
    )

    assert graph.nodes["700"].device_type.name == "HEATING_CONTROLLER"
    assert graph.nodes["700"].scan_type == "70000"
    assert graph.raw_registers["700.HwcOpMode"] == "auto"
    assert graph.raw_registers["700.HwcStorageTemp"] == "49.5"
    assert graph.heating_controller_result().circuit == "700"


# Intent: the full PR #164 CTLV0 capture supplies writable-control metadata and a safe absent path.
# Why: OffsetOutsideTemp has strict write/read-back evidence; Hc1SetbackMode relies on
# the owner's acceptance of the reporter's attestation.
def test_pr164_ctlv0_dump_exposes_controls_and_keeps_absent_path_safe() -> None:
    fixture = "community/ctlv0_pr164_2026-10-02_161025_discovery.yaml"
    dump = load_discovery_dump(fixture)
    assert dump["metadata"]["ebusd_info"]["loaded_configs"]["15"]["scanned"] == "MF=Vaillant;ID=CTLV0;SW=0313;HW=9103"
    assert any(line == "ctlv0 Hc1SetbackMode = normal" for line in dump["raw_find_lines"])
    assert any(line == "ctlv0 OffsetOutsideTemp = -1.5" for line in dump["raw_find_lines"])
    assert any(line == "ctlv0 OffsetOutsideTemp = -1" for line in dump["raw_find_lines_after"])
    assert len(dump["writes"]) == 1
    assert dump["writes"][0]["name"] == "OffsetOutsideTemp"
    assert dump["writes"][0]["value"] == "-1.0"
    assert dump["writes"][0]["success"] is True

    graph = DiscoveryService.build_device_graph(load_find_lines(fixture, after=True))
    assert graph.raw_registers["ctlv0.Hc1SetbackMode"] == "normal"
    assert graph.raw_registers["ctlv0.OffsetOutsideTemp"] == "-1"
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    setback = entities["ctlv0.Hc1SetbackMode.value"]
    assert setback.entity_type == "select"
    assert setback.meta.writable is True
    assert setback.meta.options == ["eco", "normal"]

    offset = entities["ctlv0.OffsetOutsideTemp.value"]
    assert offset.entity_type == "number"
    assert offset.meta.writable is True
    assert (offset.meta.min_value, offset.meta.max_value, offset.meta.step) == (-3, 3, 0.5)

    absent_graph = DiscoveryService.build_device_graph(
        ["scan.15 = MF=Vaillant;ID=CTLV0;SW=0313;HW=9103", "ctlv0 Z1OpMode = auto"]
    )
    absent_keys = {entity.key for entity in EntityFactoryService().generate(absent_graph)}
    assert "ctlv0.Hc1SetbackMode.value" not in absent_keys
    assert "ctlv0.OffsetOutsideTemp.value" not in absent_keys


# Intent: discussion #31 (aroTHERM split plus VWL 77/8.2, HMUX0 SW0303/HW0504, Modbus link) keeps its
# per-field hydraulic-station entities while the composite Status string is no longer enabled by default.
# Why: the "a;b;c;-;d;off" parent repeats the per-field values and flooded the recorder history.
def test_discussion31_hydraulic_station_composite_status_is_disabled_by_default() -> None:
    graph = DiscoveryService.build_device_graph(
        load_find_lines("community/hmux0_discussion31_vwl77_2026-10-02_205648_discovery.yaml")
    )
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert entities["vwzio.Status01.value"].raw_value == "27.0;24.5;16.867;-;67.0;off"
    assert entities["vwzio.Status01.value"].enabled_by_default is False
    assert entities["vwzio.Status01.temp"].enabled_by_default is True
    assert entities["vwzio.Status01.pumpstate"].enabled_by_default is True


# Intent: the same capture proves the implausible Modbus-split return temperature stays unavailable.
# Why: issue #171 adds a flow-temperature register that shares the layout, so both must be rejected here.
def test_discussion31_implausible_hmux0_return_temperature_stays_unavailable() -> None:
    graph = DiscoveryService.build_device_graph(
        load_find_lines("community/hmux0_discussion31_vwl77_2026-10-02_205648_discovery.yaml")
    )
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert "hmux0.RunDataReturnTemp" not in graph.raw_registers
    assert entities["hmux0.RunDataReturnTemp.value"].raw_value == ""


# Intent: F34 issue #152 capture (BAI/BASS3/VR_70): numeric counters that read 0 stay sensors.
# Why: value-based 0/1 detection turned YieldTotal and PumpPower into binary sensors that duplicate real ones.
def test_issue152_f34_zero_valued_counters_are_sensors_not_binary_sensors() -> None:
    graph = DiscoveryService.build_device_graph(
        load_find_lines("community/saunier_duval_f34_issue152_2026-10-02_194815_discovery.yaml")
    )
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    assert entities["bass.YieldTotal.value"].entity_type == "sensor"
    assert entities["bai.PumpPower.value"].entity_type == "sensor"
    assert entities["bai.StorageLoadPumpHours.value"].entity_type == "sensor"
    # The composite boiler Status string is hidden by default; per-field entities remain.
    assert entities["bai.Status01.value"].enabled_by_default is False


# Intent: issue #171 - a valid 1/16 degC HMUX0 flow temperature becomes an extra precise sensor.
# Why: the reporter's value must appear next to the existing 0.5 degC Status01 flow sensor, not replace it.
def test_issue171_hmux0_run_data_flow_temperature_becomes_precise_sensor() -> None:
    lines = [
        *load_find_lines("community/hmux0_discussion31_vwl77_2026-10-02_205648_discovery.yaml"),
        "hmux0 RunDataFlowTemp = 25.0625",
    ]
    graph = DiscoveryService.build_device_graph(lines)
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    flow = entities["hmux0.RunDataFlowTemp.value"]
    assert flow.raw_value == "25.0625"
    assert flow.meta.friendly_name == "Flow Temperature (precise)"
    assert flow.meta.unit == "°C"
    assert flow.enabled_by_default is True
    assert entities["vwzio.Status01.temp"].meta.friendly_name == "Flow Temperature"


# Intent: rebuild the find lines the coordinator seeds from the F34 issue #152 register cache.
# Why: the HC3 entities came from cache seeding, which keeps static defaults of unused circuits.
def _f34_cache_find_lines() -> list[str]:
    import json

    from tests.fake_ebusd import FIXTURES_DIR

    cache = json.loads((FIXTURES_DIR / "community/f34_issue152_2026-10-02_register_cache.json").read_text("utf-8"))
    lines = []
    for cache_key, value in cache.items():
        parts = cache_key.split(".")
        if len(parts) == 3 and parts[2] == "value":
            lines.append(f"{parts[0]} {parts[1]} = {value}")
    return lines


# Intent: heating circuits the controller reports as `inactive` create no entities except the circuit type itself.
# Why: issue #152 - the reporter has no HC3, but its static heat curve and min flow defaults created seven entities.
def test_issue152_inactive_heating_circuit_creates_no_entities_but_keeps_circuit_type() -> None:
    entities = {
        entity.key: entity
        for entity in EntityFactoryService().generate(DiscoveryService.build_device_graph(_f34_cache_find_lines()))
    }

    assert not [key for key in entities if ".Hc3" in key and not key.startswith("bass.Hc3CircuitType")]
    assert "bass.Hc3CircuitType.value" in entities
    assert "bass.Hc2HeatCurve.value" in entities
    assert "bass.Hc1FlowTemp.value" in entities


# Intent: without an `inactive` circuit type the same static HC3 registers are still exposed.
# Why: an unreadable or missing type (the F34 Hc1CircuitType returns an error) must never hide a circuit.
def test_issue152_heating_circuit_without_inactive_type_keeps_entities() -> None:
    lines = [line for line in _f34_cache_find_lines() if "Hc3CircuitType" not in line]
    entities = {entity.key for entity in EntityFactoryService().generate(DiscoveryService.build_device_graph(lines))}

    assert "bass.Hc3HeatCurve.value" in entities


# Intent: the F34 boiler stage-1 energy counters claim no kWh unit and are disabled by default.
# Why: issue #152 - 40960195 "kWh" is impossible; the unit is unproven, so it must not feed the Energy dashboard.
def test_issue152_boiler_stage_energy_counters_are_raw_and_disabled_by_default() -> None:
    entities = {
        entity.key: entity
        for entity in EntityFactoryService().generate(DiscoveryService.build_device_graph(_f34_cache_find_lines()))
    }

    for key in ("bai.PrEnergySumHc1.value", "bai.PrEnergySumHwc1.value"):
        entity = entities[key]
        assert (entity.meta.unit, entity.meta.device_class) == ("", "")
        assert entity.enabled_by_default is False
    assert entities["bai.PrEnergySumHc1.value"].raw_value == "40960195"


# Intent: an E7000 system manager without a loaded ebusd configuration yields no controller device or climate source.
# Why: discussion #31 - ebusd's `next` tree has no 15.e7000, so there are no zone registers for a climate entity.
def test_discussion31_e7000_without_config_creates_no_controller_entities() -> None:
    graph = DiscoveryService.build_device_graph(
        load_find_lines("community/hmu_e7000_discussion31_2026-10-04_113747_discovery.yaml")
    )
    entities = EntityFactoryService().generate(graph)

    assert not [entity for entity in entities if entity.name.lower().startswith(("z1", "hc1"))]
    assert graph.heating_controller_result().node is None


# Intent: F34 issue #152 - text-valued room-temperature thresholds carry no unit so the sensor shows the text.
# Why: `thermostat`/`modulating` with unit="°C" made the sensor return None, so it showed Unknown forever.
def test_issue152_room_temp_threshold_is_unitless_text_sensor() -> None:
    entities = {
        entity.key: entity
        for entity in EntityFactoryService().generate(DiscoveryService.build_device_graph(_f34_cache_find_lines()))
    }

    for key, expected in (
        ("bass.Hc1RoomTempSwitchOn.value", "thermostat"),
        ("bass.Hc2RoomTempSwitchOn.value", "modulating"),
    ):
        assert entities[key].meta.unit == ""
        assert entities[key].raw_value == expected


# Intent: F34 issue #152 - the boiler Status01 temperatures are named apart from the dedicated bai registers.
# Why: "Flow Temperature" and "Storage Temperature" appeared twice with different values and a `_2` suffix.
def test_issue152_boiler_status_temperatures_have_distinct_names() -> None:
    entities = {
        entity.key: entity
        for entity in EntityFactoryService().generate(DiscoveryService.build_device_graph(_f34_cache_find_lines()))
    }

    assert entities["bai.FlowTemp.value"].meta.friendly_name == "Flow Temperature"
    assert entities["bai.Status01.temp"].meta.friendly_name == "Flow Temperature (Status message)"
    assert entities["bai.Status01.temp_4"].meta.friendly_name == "Storage Temperature (Status message)"
    assert entities["bai.Status01.temp_1"].meta.friendly_name == "Return Temperature"


# Intent: the threshold is unitless even when its first reading is empty, because the unit is fixed at construction.
# Why: review finding on #152 - an idle controller that later reports `thermostat` would otherwise stay unknown.
def test_issue152_room_temp_threshold_is_unitless_before_the_first_text_reading() -> None:
    lines = [
        "bass Hc1RoomTempSwitchOn = no data stored" if "Hc1RoomTempSwitchOn" in line else line
        for line in _f34_cache_find_lines()
    ]
    entities = {e.key: e for e in EntityFactoryService().generate(DiscoveryService.build_device_graph(lines))}

    assert entities["bass.Hc1RoomTempSwitchOn.value"].meta.unit == ""


ISSUE186_FIXTURE = "community/hmux0_sw0406_issue186_2026-10-11_143454_discovery.yaml"


# Intent: build the entity descriptions of the issue #186 capture, optionally under the stock ebusd controller name.
# Why: the reporter's local ebusd config names the CTLV3 controller `ctlv2`; the stock config names it `ctlv3`.
def _issue186_entities(controller_circuit: str = "ctlv2") -> dict[str, object]:
    lines = [
        line.replace("ctlv2 ", f"{controller_circuit} ", 1) if line.startswith("ctlv2 ") else line
        for line in load_find_lines(ISSUE186_FIXTURE)
    ]
    graph = DiscoveryService.build_device_graph(lines)
    return {entity.key: entity for entity in EntityFactoryService().generate(graph)}


# Intent: the HcN auto-off select offers exactly the values ebusd accepts for the register.
# Why: issue #187 - ebusd defines `0=eco;1=night`; the offered `comfort` made every write fail with
#      "ERR: invalid numeric argument", and the captures only ever show `eco` and `night`.
@pytest.mark.parametrize("controller_circuit", ["ctlv2", "ctlv3"])
def test_issue187_auto_off_mode_offers_the_values_ebusd_accepts(controller_circuit: str) -> None:
    entities = _issue186_entities(controller_circuit)

    for circuit_number in (1, 2):
        entity = entities[f"{controller_circuit}.Hc{circuit_number}AutoOffMode.value"]
        assert entity.entity_type == "select"
        assert entity.meta.options == ["eco", "night"]
    # The metadata for the inactive third circuit follows the same value list.
    for circuit_number in (1, 2, 3):
        assert MAPPING.get_meta("ctlv2", f"Hc{circuit_number}AutoOffMode").options == ["eco", "night"]


# Intent: the live second zone exposes the same writable settings as the first zone.
# Why: issue #186 - Z2OpMode, Z2NightTemp, Z2QuickVeto* and Z2HolidayTemp had values but only read-only sensors.
@pytest.mark.parametrize("controller_circuit", ["ctlv2", "ctlv3"])
def test_issue186_zone2_settings_are_writable_entities(controller_circuit: str) -> None:
    entities = _issue186_entities(controller_circuit)
    prefix = f"{controller_circuit}.Z2"

    mode = entities[f"{prefix}OpMode.value"]
    assert (mode.entity_type, mode.meta.writable) == ("select", True)
    assert mode.meta.options == ["day", "night", "auto", "off"]
    for name in ("NightTemp", "QuickVetoTemp", "HolidayTemp"):
        number = entities[f"{prefix}{name}.value"]
        assert (number.entity_type, number.meta.writable, number.meta.unit) == ("number", True, "°C"), name
        assert (number.meta.min_value, number.meta.max_value, number.meta.step) == (5, 30, 0.5), name
    duration = entities[f"{prefix}QuickVetoDuration.value"]
    assert (duration.entity_type, duration.meta.writable) == ("number", True)
    for name in ("OpMode", "NightTemp", "QuickVetoTemp", "QuickVetoDuration", "HolidayTemp"):
        assert entities[f"{prefix}{name}.value"].device_circuit == "z2"


# Intent: the first zone keeps its existing writable settings next to the new second-zone ones.
# Why: generating zone metadata from the Z1 entries must not change what Z1 users already have.
def test_issue186_zone1_settings_keep_their_metadata() -> None:
    entities = _issue186_entities()

    assert entities["ctlv2.Z1OpMode.value"].meta.options == ["day", "night", "auto", "off"]
    assert entities["ctlv2.Z1NightTemp.value"].meta.friendly_name == "Night Temperature (Z1)"
    assert entities["ctlv2.Z2NightTemp.value"].meta.friendly_name == "Night Temperature (Z2)"
    assert entities["ctlv2.Z2OpMode.value"].meta.friendly_name == "Operation Mode (Z2)"


# Intent: a zone the controller declares unused gets neither settings nor read-only placeholder sensors.
# Why: issue #186 dump - Z3 is a placeholder (`Z3RoomTemp` empty, circuit type inactive). Release 1.11.2 kept its raw
#      read-only sensors; release 1.12.0 drops them because static defaults are not evidence of a zone.
def test_issue186_declared_unused_zone3_creates_no_entities() -> None:
    entities = _issue186_entities()

    assert not [key for key in entities if key.startswith("ctlv2.Z3")]
    assert "ctlv2.Hc3CircuitType.value" in entities


ISSUE197_FIXTURE = "community/geniaset_bass3_discovery.yaml"


# Intent: build the entity descriptions of the BASS3 capture, with chosen register lines replaced by live values.
# Why: the capture only holds `no data stored`; a live zone needs a room temperature, which gates its writable settings.
def _issue197_entities(replacements: dict[str, str] | None = None) -> dict[str, object]:
    values = replacements or {}
    lines = [
        f"{line.split(' = ', 1)[0]} = {values[line.split(' = ', 1)[0]]}" if line.split(" = ", 1)[0] in values else line
        for line in load_find_lines(ISSUE197_FIXTURE)
    ]
    graph = DiscoveryService.build_device_graph(lines)
    return {entity.key: entity for entity in EntityFactoryService().generate(graph)}


# Intent: the BASS3 cooling mode is a writable select with the values its ebusd CSV defines.
# Why: issue #197 - the CSV names the register `Z1OpModeCooling` (`0=off;1=auto;2=day;3=night`), so the
#      `Z1CoolingOpMode` entry never matched and the mode showed as a read-only sensor.
def test_issue197_bass3_cooling_mode_is_a_writable_select() -> None:
    entities = _issue197_entities({"bass Z1OpModeCooling": "off"})

    mode = entities["bass.Z1OpModeCooling.value"]
    assert (mode.entity_type, mode.meta.writable) == ("select", True)
    assert mode.meta.options == ["off", "auto", "day", "night"]
    assert mode.meta.friendly_name == "Cooling Operation Mode (Z1)"


# Intent: the TSP-named cooling mode keeps its own value list next to the CSV-named one.
# Why: both names address the same byte, but `manual` is only valid under the TSP name; sharing one list would offer
#      values that the other ebusd configuration rejects.
def test_issue197_tsp_cooling_mode_options_are_unchanged() -> None:
    assert MAPPING.get_meta("ctlv2", "Z1CoolingOpMode").options == ["off", "auto", "manual"]
    assert MAPPING.get_meta("bass", "Z1OpModeCooling").options == ["off", "auto", "day", "night"]


# Intent: a live second zone gets the same writable cooling mode, a placeholder zone stays a plain sensor.
# Why: issue #197 shows Z2/Z3 under the same CSV names; the room-temperature gate from #186 must still apply.
def test_issue197_second_zone_cooling_mode_follows_the_live_zone_gate() -> None:
    placeholder = _issue197_entities({"bass Z2OpModeCooling": "off"})
    live = _issue197_entities({"bass Z2OpModeCooling": "off", "bass Z2RoomTemp": "21.5"})

    assert placeholder["bass.Z2OpModeCooling.value"].entity_type != "select"
    zone2 = live["bass.Z2OpModeCooling.value"]
    assert (zone2.entity_type, zone2.meta.writable) == ("select", True)
    assert zone2.meta.options == ["off", "auto", "day", "night"]
    assert zone2.meta.friendly_name == "Cooling Operation Mode (Z2)"


# Intent: the new metadata creates no entity on a controller that does not report the CSV-named register.
# Why: discovery stays the source of truth; REGISTER_MAP entries must be safe when the register is absent.
def test_issue197_cooling_mode_entry_creates_nothing_when_register_is_absent() -> None:
    lines = [line for line in load_find_lines(ISSUE197_FIXTURE) if "OpModeCooling" not in line]
    graph = DiscoveryService.build_device_graph(lines)
    keys = {entity.key for entity in EntityFactoryService().generate(graph)}

    assert not [key for key in keys if "OpModeCooling" in key]


NAME_ONLY_FIXTURE = "community/hmux0_issue99_2026-09-10_170850.yaml"
NAME_ONLY_NAMES = {
    "hmux0.EnergyIntegral.value": "Energy Integral",
    "hmux0.FlowPressure.value": "Flow Pressure",
}


# Intent: registers that had only their raw name get a readable name once they return a live value.
# Why: the entity list showed `EnergyIntegral` and `FlowPressure` next to properly named entries (owner audit, 1.12.5).
def test_name_only_registers_with_live_values_have_readable_names() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(NAME_ONLY_FIXTURE))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    for key, expected_name in NAME_ONLY_NAMES.items():
        assert entities[key].meta.friendly_name == expected_name
        assert entities[key].enabled_by_default
        # Only a unit from an ebusd definition is claimed (issue #205: EnergyIntegral is `°min`); the rest stay bare.
        expected_unit = "°min" if key.endswith("EnergyIntegral.value") else ""
        assert (entities[key].meta.unit, entities[key].meta.device_class) == (expected_unit, "")


# Intent: a name-only register is exposed only after ebusd returns a value, and is never read actively.
# Why: the entries set fallback_read=False so a bus without the register gets no extra failing reads.
def test_name_only_registers_without_data_create_no_entity() -> None:
    emptied = (" EnergyIntegral = ", " FlowPressure = ")
    lines = [
        f"{line.split(' = ')[0]} = no data stored" if any(name in line for name in emptied) else line
        for line in load_find_lines(NAME_ONLY_FIXTURE)
    ]
    graph = DiscoveryService.build_device_graph(lines)
    keys = {entity.key for entity in EntityFactoryService().generate(graph)}

    assert not set(NAME_ONLY_NAMES) & keys
    assert all(not MAPPING.get_meta("hmux0", name).fallback_read for name in ("EnergyIntegral", "FlowPressure"))


# Intent: an unnamed multi-value status register (`auto;60;75.0;70;65.0`) creates no raw-string entity on a boiler.
# Why: mapping `Status02` with a friendly name would have added one (found with the differential tool, 1.12.5).
def test_boiler_multi_value_status02_creates_no_raw_string_entity() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/ecotec_vrt380_ctlv2_discovery.yaml"))
    keys = {entity.key for entity in EntityFactoryService().generate(graph)}

    assert not [key for key in keys if "Status02" in key]


DISCUSSION31_FIXTURE = "community/ecotec_b7v_discussion31_2026-10-21_205103_discovery.yaml"
FUEL_SUM_WITH_DATA = {
    "b7v.PrFuelSum.value": "20446",
    "b7v.PrFuelSumHc.value": "20434",
    "b7v.PrFuelSumHcThisMonth.value": "14",
}


# Intent: the gas counters of a VRC 720 (b7v) are kWh energy sensors, diagnostic and off by default.
# Why: discussion 31 - upstream ebusd declares them `energy4` (kWh), heating + DHW add up to the total in the capture,
#      and the reporter's app shows kWh; last month's value can fall, so only the rising counters get a state class.
def test_discussion31_fuel_sum_counters_are_kwh_disabled_diagnostics() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(DISCUSSION31_FIXTURE))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    for key, expected_value in FUEL_SUM_WITH_DATA.items():
        entity = entities[key]
        assert entity.raw_value == expected_value
        assert not entity.enabled_by_default
        assert (entity.meta.unit, entity.meta.device_class) == ("kWh", "energy")
        expected_state_class = "" if key.endswith("LastMonth.value") else "total_increasing"
        assert (entity.meta.state_class, entity.meta.entity_category) == (expected_state_class, "diagnostic")
        assert "raw counter" not in entity.meta.friendly_name


# Intent: a register without data on the same bus creates no entity, and none of the new entries is read actively.
# Why: discovery stays the source of truth; `PrFuelSumHwcLastMonth` reads `no data stored` in the capture.
def test_discussion31_fuel_sum_without_data_creates_no_entity() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(DISCUSSION31_FIXTURE))
    keys = {entity.key for entity in EntityFactoryService().generate(graph)}

    assert "b7v.PrFuelSumHwcLastMonth.value" not in keys
    assert not MAPPING.get_meta("b7v", "PrFuelSum").fallback_read
    assert not MAPPING.get_meta("ctlv3", "PrFuelSumHc").fallback_read


# Intent: with the gas counters absent from the bus, nothing is created for them.
# Why: REGISTER_MAP entries must be safe when the register is absent (hardware without a gas boiler).
def test_fuel_sum_entries_create_nothing_when_the_register_is_absent() -> None:
    lines = [line for line in load_find_lines(DISCUSSION31_FIXTURE) if "PrFuelSum" not in line]
    graph = DiscoveryService.build_device_graph(lines)
    keys = {entity.key for entity in EntityFactoryService().generate(graph)}

    assert not [key for key in keys if "PrFuelSum" in key]


DATE_DUPLICATE_FIXTURE = "community/flexotherm_discovery.yaml"


# Intent: holiday dates of the heating controller have a date control only; no sensor repeats them.
# Why: the owner's HA listed DHW and Z1 holiday start/end as a sensor and as a date (audit of 2026-10-26).
def test_holiday_dates_are_served_by_the_date_platform_only() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines(DATE_DUPLICATE_FIXTURE))
    before = [line for line in load_find_lines(DATE_DUPLICATE_FIXTURE) if "HolidayStartPeriod" in line]
    keys = {entity.key for entity in EntityFactoryService().generate(graph)}

    assert before, "fixture must list holiday registers"
    assert not [key for key in keys if "HolidayStartPeriod" in key or "HolidayEndPeriod" in key]


# Intent: the command and test-flag registers are no longer listed as sensors.
# Why: `Clearerrorhistory` and `EnableTest*` only mean a button press or a test switch (owner audit, 1.12.5).
def test_command_registers_create_no_sensor() -> None:
    from tests.test_entity_factory import DiscoveryService as Discovery

    for key in (
        "hmu.Clearerrorhistory",
        "vwz.EnableTestHwcTemp",
        "vwz.EnableTestOutdoorTemp",
        "vwz.EnableTestThreeWayValve",
    ):
        assert Discovery._is_hidden(key) is True
    assert Discovery._is_hidden("vwz.TestHwcTemp") is False
    # A map entry would also make the fallback planner read the command register actively.
    assert not [key for key in MAPPING.REGISTER_MAP if key.casefold().endswith(".clearerrorhistory")]


# Intent: a zone holiday keeps its sensor when the date platform would not create the date control.
# Why: review finding on 1.12.5 - on the geniaset capture Z1 is claimed by two circuits, so no zone is valid and no date
# control exists; dropping the sensors would have left the holiday dates without any entity.
def test_zone_holiday_sensors_stay_when_no_date_control_exists() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/geniaset_bass3_discovery.yaml"))
    keys = {entity.key for entity in EntityFactoryService().generate(graph)}

    assert valid_zone_owners(graph) == {}
    assert {"bass.Z1HolidayStartPeriod.value", "bass.Z1HolidayEndPeriod.value"} <= keys


# Intent: the circuit types of all heating circuits are listed together on the controller device, while the other HC1
# entities stay on the Zone 1 device.
# Why: the owner found HC1 under Zone 1 and the inactive HC2/HC3 elsewhere, three sensors of one kind on two devices.
def test_circuit_types_share_the_controller_device_and_other_hc1_entities_stay_on_zone_1() -> None:
    graph = DiscoveryService.build_device_graph(load_find_lines("community/arotherm_plus_2zone_discovery.yaml"))
    entities = {entity.key: entity for entity in EntityFactoryService().generate(graph)}

    circuit_types = {key: entity for key, entity in entities.items() if key.endswith("CircuitType.value")}
    assert {"ctlv3.Hc1CircuitType.value", "ctlv3.Hc2CircuitType.value"} <= circuit_types.keys()
    assert {entity.device_circuit for entity in circuit_types.values()} == {"ctlv3"}
    assert entities["ctlv3.Hc1FlowTemp.value"].device_circuit == "z1"


# Intent: a zone whose room temperature read fails keeps its climate zone, while a zone without data stays a ghost.
# Why: issue #191/#192 - on this capture `Z2RoomTemp` answered `ERR: invalid position`, Zone 2 lost its climate entity
#      and the stale-entities repair deleted the row; Zone 3 (`no data stored`, HC3 inactive) must not become a zone.
def test_unreadable_zone_room_temperature_keeps_the_zone_valid() -> None:
    graph = DiscoveryService.build_device_graph(
        load_find_lines("community/saunier_duval_f34_issue191_2026-10-20_094755_discovery.yaml")
    )

    assert "bass.Z2RoomTemp" in graph.error_registers
    assert valid_zone_owners(graph) == {"z1": "bass", "z2": "bass"}


# Intent: an unreadable zone stays a ghost when the controller declares its heating circuit inactive.
# Why: only the controller's own `HcNCircuitType = inactive` may overrule a read error; it must not revive zone 3.
def test_unreadable_zone_of_an_inactive_circuit_is_not_valid() -> None:
    lines = load_find_lines("community/saunier_duval_f34_issue191_2026-10-20_094755_discovery.yaml")
    graph = DiscoveryService.build_device_graph(lines)
    graph.error_registers.add("bass.Z3RoomTemp")

    assert "z3" not in valid_zone_owners(graph)


# Intent: the units from the issue #205 ebusd definitions apply to the heat pump and controller registers.
# Why: these registers showed as bare text without a graph; ebusd's own definitions give `°C` and `kWh`.
def test_issue205_registers_carry_the_unit_from_the_ebusd_definitions() -> None:
    expected = {
        ("hmux0", "RunDataCondensorOutletTemp"): ("°C", "temperature"),
        ("hmux0", "RunDataFlowTempDesired"): ("°C", "temperature"),
        ("hmux0", "TotalEnergyUsageImmersionHeater"): ("kWh", "energy"),
        ("ctlv3", "HcBivalencePoint"): ("°C", "temperature"),
        ("ctlv3", "HcEmergencyTemp"): ("°C", "temperature"),
        ("ctlv3", "Hc1FlowTempDesired"): ("°C", "temperature"),
        ("ctlv3", "Hc2HeatingFlowTempMax"): ("°C", "temperature"),
        ("ctlv3", "Hc1HeatingFlowTempMin"): ("°C", "temperature"),
    }
    for (circuit, name), unit_and_class in expected.items():
        meta = MAPPING.get_meta(circuit, name)
        assert (meta.unit, meta.device_class) == unit_and_class, name
        assert not meta.fallback_read, name


# Intent: the HW5103 Status07 fields have valid Home Assistant metadata now that the message decodes.
# Why: 1.13.1 made Status07 readable; `%` with the `power` class is invalid for HA, and the combined status text only
#      repeats the separate sensors.
def test_status07_fields_have_valid_metadata() -> None:
    assert MAPPING.get_meta("hmu", "Status07").enabled is False
    power = MAPPING.get_meta("hmu", "Status07.power")
    assert (power.unit, power.device_class, power.state_class) == ("%", "", "measurement")
    pressure = MAPPING.get_meta("hmu", "Status07.displaypressure")
    assert (pressure.unit, pressure.device_class) == ("bar", "pressure")
