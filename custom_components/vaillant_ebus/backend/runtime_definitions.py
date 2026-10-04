"""Build the list of runtime ``define`` strings for the discovered hardware.

Pure functions (no I/O): the coordinator sends the result to ebusd. Every definition is
evidence-backed (upstream or community capture) and resolved against the discovered
device graph, never against a guessed circuit.
"""

from __future__ import annotations

from datetime import datetime

from .hardware_profiles import HMU00_HW5103, HMUX0_B509_MONITORING, node_matches, scan_matches
from .mapping import (
    HMUX0_SW0407_ENVYIELD_REGISTERS,
    b516_date_bytes,
    hmux0_candidate_circuits,
    hmux0_owner_scan,
    hmux0_sw0303_owner,
    hmux0_sw0407_circuit,
    vwz_station_scan_76_circuit,
    vwzio_sw0500_circuit,
)
from .models import (
    DeviceGraph,
    ResolutionStatus,
    is_controller_circuit,
    is_heat_pump_circuit,
)

# VWZIO/VWZ Status01 field layout (upstream PR #598); reuses the HMU layout.
# Explicit types are required: the hcmode_inc template aliases (temp1/temp2/
# pumpstate) are not resolvable in a runtime `define`.
VWZ_STATUS01_FIELDS = (
    "temp,,D1C,,,,temp_1,,D1C,,,,temp_2,,D2B,,,,temp_3,,D1C,,,,temp_4,,D1C,,,,"
    "pumpstate,,UCH,0=off;1=on;2=overrun;4=hwc,,"
)

HMUX0_SW0407_STATUS_VALUES = (
    "34=frost_protection;100=standby;101=heat_compressor_off;102=heat_compressor_blocked;"
    "103=heat_pump_prerun;104=heat_compressor_active;107=heat_pump_postrun;111=cool_compressor_off;"
    "112=cool_compressor_blocked;113=cool_pump_prerun;114=cool_compressor_active;117=cool_pump_postrun;"
    "125=heating_immersion_heater_active;132=dhw_compressor_blocked;133=dhw_pump_prerun;"
    "134=hwc_compressor_active;135=hwc_immersion_heater_active;137=dhw_pump_postrun;"
    "141=heating_immersion_heater_off;142=heating_immersion_heater_blocked;"
    "151=dhw_immersion_heater_off;152=dhw_immersion_heater_blocked;516=defrost"
)
HMUX0_SW0407_PASSIVE_REGISTERS = (
    (
        "RunDataStatuscode",
        "B509",
        "5402008813",
        f"value,,IGN:4,,,,value,,UIN,{HMUX0_SW0407_STATUS_VALUES},,",
    ),
    (
        "RunDataCompressorSpeed",
        "B509",
        "5402000d0a",
        "value,,IGN:4,,,,value,,EXP,,rps,HMUX0 compressor speed",
    ),
    (
        "RunDataElPowerConsumption",
        "B509",
        "5402005b0d",
        "value,,IGN:4,,,,value,,EXP,,W,HMUX0 electrical power consumption",
    ),
    (
        "RunDataBuildingCPumpPower",
        "B509",
        "540200c509",
        "value,,IGN:4,,,,value,,EXP,,%,HMUX0 building circuit pump power",
    ),
    ("KmKreisVerflTemp", "B51A", "05ff3546", "value,,IGN:3,,,,value,,D2C,,°C,temperature"),
    ("UnterkuehlungSoll", "B51A", "05ff354a", "value,,IGN:3,,,,value,,D2C,,K,"),
    ("UnterkuehlungIst", "B51A", "05ff354b", "value,,IGN:3,,,,value,,D2C,,K,"),
    ("EEVAuslassTemp", "B51A", "05ff3702", "value,,IGN:3,,,,value,,D2C,,°C,temperature"),
    ("KmKreisKompEinlTemp", "B51A", "05ff3704", "value,,IGN:3,,,,value,,D2C,,°C,temperature"),
    ("KmKreisKompAuslTemp", "B51A", "05ff3705", "value,,IGN:3,,,,value,,D2C,,°C,temperature"),
    ("KmKreisHochdruck", "B51A", "05ff370b", "value,,IGN:3,,,,value,,UIN,10,bar,"),
    # B516/14 is the gateway's current-power frame; upstream issues #490, #610 and #638 document the layout
    # (status byte, then EXP) and the fixtures decode 35.92 W and 10.4 W standby values (issue #161).
    ("PowerConsumptionHmu", "B516", "14", "ign,,IGN:1,,,,value,,EXP,1000,kW,"),
    # B511 data 1801/1802 (the ebusd id excludes the length byte) are the compressor runtime and start counters
    # for heating and DHW: upstream 08.hmu.tsp defines the same layout and issue #522 reconciles the minutes
    # with RunStatsCompressorHours.
    ("CompressorHc", "B511", "1801", "ign,,IGN:1,,,,runtime,,ULG,,min,,cycles,,ULG"),
    ("CompressorHwc", "B511", "1802", "ign,,IGN:1,,,,runtime,,ULG,,min,,cycles,,ULG"),
)


# Intent: compile the full list of runtime define strings for the graph's hardware.
# Why: keeping this pure lets tests assert the exact definitions per capture without a coordinator.
def build_runtime_defines(graph: DeviceGraph, now: datetime) -> list[str]:
    date_bytes = b516_date_bytes(now)
    defines = [
        "r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800,value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity",
        # eloBLOCK B510 thermostat override. It is harmless on hardware
        # without BAI; ebusd reports it unavailable and filters it out.
        "wi,bai,SetModeOverride,Operation Mode,,08,B510,00"
        ",hcmode,,UCH,,,,flowtempdesired,,D1C,,,,hwctempdesired,,D1C"
        ",,,,hwcflowtempdesired,,UCH,,,,setmode1,,UCH,,,,disablehc,,BI0"
        ",,,,disablehwctapping,,BI1,,,,disablehwcload,,BI2,,,,setmode2,,UCH"
        ",,,,remoteControlHcPump,,BI0,,,,releaseBackup,,BI1,,,,releaseCooling,,BI2",
        # eloBLOCK/BAI boiler control: the generic BAI configuration exposes
        # HeatingSwitch/HwcSwitch read-only. Redefine them writable on B509
        # using the upstream product-specific convention: read id `0dF203` /
        # `0dF303`, write prefix byte `0e` (`0eF203`/`0eF303`), and a UCH
        # onoff field. The `onoff` template is not in the runtime define's
        # template scope, so `value,,onoff` fails element lookup with
        # `ERR: element not found`; UCH decodes identically. Only emitted
        # when a BAI controller is discovered.
        "wi,bai,HeatingSwitch,Heating Switch,,08,B509,0ef203,value,,UCH,0=off;1=on,,",
        "wi,bai,HwcSwitch,DHW Switch,,08,B509,0ef303,value,,UCH,0=off;1=on,,",
        # VWZIO/VWZ Hydraulikstation process telemetry (upstream PR #598).
        # Status01 (b511 01, 9 bytes) reuses the HMU layout: flow, return,
        # outside, DHW, storage, pump. Read actively like hmu.Status01 so it
        # populates immediately; emitted for whichever of vwz/vwzio the bus
        # exposes, and resolution drops the variant that is not discovered.
        "r,vwz,Status01,Status01,31,76,B511,01," + VWZ_STATUS01_FIELDS,
        "r,vwzio,Status01,Status01,31,76,B511,01," + VWZ_STATUS01_FIELDS,
        # SourceTempInput is absent from the shipped CSVs (upstream issue
        # #632, last compiled 2026-04-19). Layout verified live on brine
        # units in john30/ebusd-configuration PR #565 (flexoTHERM and
        # flexoCOMPACT ground-source); air/water units answer with a
        # 3-byte stub and stay unavailable, which the ERR filtering keeps
        # out of entity values.
        "r,hmu,SourceTempInput,SourceTempInput,31,8,B51A,05ff3222,value,,IGN:3,,,,value,,D2C,,°C,Source temp input",
        # HMUX0 HW0504 community capture: upstream issue #249 / PR #330
        # identifies B511/00 as the multi-field compressor status block.
        # Unsupported variants return an empty response and remain filtered.
        "r,hmu,Status00,Status00,31,8,B511,00"
        ",supplytemp,,D2C,,°C,,waterpressure,,UCH,10,bar,,"
        "compressormodulation,,UCH,,%,,compressorstate,,UCH,0=off;1=heating_prerun;"
        "4=heating;5=heating_overrun;24=hot_water;110=defrosting,,,"
        "heatingstate,,UCH,8=off;9=heating,,,field6,,UCH,,,,"
        "defrost,,UCH,0=inactive;32=active,,,compressorpower,,percent1,,%,HMUX0 Status00",
        # HMUX0 HW0504 community capture: upstream issue #522 identifies
        # B509/540200/5b0d as diagnostic electrical power in watts.
        # This is additive; absent hardware returns no data.
        "r,hmu,RunDataElPowerConsumption,RunDataElPowerConsumption,31,8,B509"
        ",5402005b0d,value,,IGN:4,,,,value,,EXP,,W,"
        "HMUX0 electrical power consumption",
        "r5,ctlv2,ManualCoolingStartDate,ManualCoolingStartDate,31,15,B524,02000000da00,value,,IGN:4,,,,value,,HDA:3",
        "r5,ctlv2,ManualCoolingEndDate,ManualCoolingEndDate,31,15,B524,02000000db00,value,,IGN:4,,,,value,,HDA:3",
        "w,ctlv2,ManualCoolingStartDate,ManualCoolingStartDate,31,15,B524,02010000da00,value,m,HDA:3",
        "w,ctlv2,ManualCoolingEndDate,ManualCoolingEndDate,31,15,B524,02010000db00,value,m,HDA:3",
        "r,hmu,CoolEnvYieldTotal,CoolEnvYieldTotal,31,08,B516"
        ",1000ffff02050000,value,,IGN:7,,,,value,,EXP,,Wh"
        ",hmu Cooling Env Yield Total",
        "r,hmu,CoolElecConsTotal,CoolElecConsTotal,31,08,B516"
        ",1000ffff03050000,value,,IGN:7,,,,value,,EXP,,Wh"
        ",hmu Cooling Electric Consumption",
        f"r,hmu,CoolEnvYieldDay,CoolEnvYieldDay,31,08,B516"
        f",1001ffff0205{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
        f",hmu Cooling Env Yield Today",
        f"r,hmu,CoolEnvYieldMonth,CoolEnvYieldMonth,31,08,B516"
        f",1002ffff0205{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
        f",hmu Cooling Env Yield This Month",
        # Daily electric consumption for cooling (issue #50 follow-up: the
        # integration only exposed the lifetime electric total, while the
        # myPyllant app shows a daily "Consumed Electrical Energy Cooling"
        # value). Same b516 API with the electric usage code (Y=3) and the
        # daily X=1 selector, so the layout matches the verified cooling
        # family; date payload rolls over like CoolEnvYieldDay.
        f"r,hmu,CoolElecConsDay,CoolElecConsDay,31,08,B516"
        f",1001ffff0305{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
        f",hmu Cooling Electric Consumption Today",
        # Lifetime and daily electric consumption for the heating (Z=3) and
        # hot-water (Z=4) domains, same b516 statistics API (upstream issue
        # #490). Conservative extension of the live-verified cooling layout
        # (Y=3 electric); absent hardware reports no data and stays hidden.
        "r,hmu,HcElecConsTotal,HcElecConsTotal,31,08,B516"
        ",1000ffff03030000,value,,IGN:7,,,,value,,EXP,,Wh"
        ",hmu Heating Electric Consumption",
        f"r,hmu,HcElecConsDay,HcElecConsDay,31,08,B516"
        f",1001ffff0303{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
        f",hmu Heating Electric Consumption Today",
        "r,hmu,HwcElecConsTotal,HwcElecConsTotal,31,08,B516"
        ",1000ffff03040000,value,,IGN:7,,,,value,,EXP,,Wh"
        ",hmu DHW Electric Consumption",
        f"r,hmu,HwcElecConsDay,HwcElecConsDay,31,08,B516"
        f",1001ffff0304{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
        f",hmu DHW Electric Consumption Today",
    ]

    heat_pump = graph.heat_pump_result().node if graph is not None else None
    hmux0_sw0407_owner = hmux0_sw0407_circuit(graph)
    if hmux0_sw0407_owner is not None:
        circuit = hmux0_sw0407_owner
        defines.extend(
            [
                f"r,{circuit},HcEnvYieldTotal,HcEnvYieldTotal,31,08,B516"
                ",1000ffff02030000,value,,IGN:7,,,,value,,EXP,,Wh"
                ",HMUX0 heating environmental yield total",
                f"r,{circuit},HcEnvYieldDay,HcEnvYieldDay,31,08,B516"
                f",1001ffff0203{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
                ",HMUX0 heating environmental yield today",
                f"r,{circuit},HcEnvYieldMonth,HcEnvYieldMonth,31,08,B516"
                f",1002ffff0203{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
                ",HMUX0 heating environmental yield this month",
                f"r,{circuit},HwcEnvYieldTotal,HwcEnvYieldTotal,31,08,B516"
                ",1000ffff02040000,value,,IGN:7,,,,value,,EXP,,Wh"
                ",HMUX0 DHW environmental yield total",
                f"r,{circuit},HwcEnvYieldDay,HwcEnvYieldDay,31,08,B516"
                f",1001ffff0204{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
                ",HMUX0 DHW environmental yield today",
                f"r,{circuit},HwcEnvYieldMonth,HwcEnvYieldMonth,31,08,B516"
                f",1002ffff0204{date_bytes},value,,IGN:7,,,,value,,EXP,,Wh"
                ",HMUX0 DHW environmental yield this month",
            ]
        )
    hmux0_owner = hmux0_owner_scan(graph)
    hmux0_sw0303_circuit = hmux0_sw0303_owner(graph)
    is_hmux0_0303_0504 = hmux0_sw0303_circuit is not None
    is_hmux0_b509_0504 = bool(hmux0_owner and scan_matches(HMUX0_B509_MONITORING, hmux0_owner[1]))
    vwzio_circuit = vwzio_sw0500_circuit(graph)
    vwzio = next(
        (node for node in graph.nodes.values() if node.circuit.casefold() == (vwzio_circuit or "").casefold()),
        None,
    )
    is_vwzio_0500_0504 = vwzio is not None
    # HMU-only layouts on HMUX0: the brine source-temperature probe is
    # always incompatible with air/water HMUX0. Status00 remains gated to
    # the confirmed 0303/0504 variant, while the B509 monitoring block is
    # evidence-gated for 0302/0504 and 0303/0504. Shared B516 statistics
    # remain available for every discovered HMUX0.
    if hmux0_owner is not None:
        hmu_only_layouts = {"SourceTempInput"}
        if not is_hmux0_0303_0504:
            hmu_only_layouts.add("Status00")
        if not is_hmux0_b509_0504:
            hmu_only_layouts.add("RunDataElPowerConsumption")
        defines = [
            definition
            for definition in defines
            if not (
                is_heat_pump_circuit(definition.split(",", 3)[1]) and definition.split(",", 3)[2] in hmu_only_layouts
            )
        ]

    # Intent: compile each logical runtime definition against its discovered owner.
    # Why: definitions must never be sent to a guessed physical circuit.
    def _resolve_definition_circuit(definition: str) -> str | None:
        parts = definition.split(",", 3)
        if len(parts) < 3 or not graph:
            return definition
        hmux0_candidates = {circuit.casefold() for circuit in hmux0_candidate_circuits(graph)}
        hmux0_owner = hmux0_owner_scan(graph)
        if is_heat_pump_circuit(parts[1]) and hmux0_candidates and (hmux0_owner is None or not hmux0_owner[1].complete):
            return None
        if (
            hmux0_sw0407_owner
            and parts[1].casefold() == hmux0_sw0407_owner.casefold()
            and parts[2] in HMUX0_SW0407_ENVYIELD_REGISTERS
        ):
            return definition
        resolution = (
            graph.heating_controller_result()
            if is_controller_circuit(parts[1])
            else graph.heat_pump_result()
            if is_heat_pump_circuit(parts[1])
            else graph.resolve_circuit_result(parts[1])
        )
        if resolution.status != ResolutionStatus.UNIQUE:
            return None
        resolved = resolution.circuit or parts[1]
        if (
            parts[0] == "r"
            and parts[2].casefold() == "status01"
            and parts[1].casefold() in {"vwz", "vwzio"}
            and (
                (station_circuit := vwz_station_scan_76_circuit(graph)) is None
                or resolved.casefold() != station_circuit.casefold()
            )
        ):
            return None
        if resolved == parts[1]:
            return definition
        parts[1] = resolved
        return ",".join(parts)

    # B524 Hc1/Hc2 state reads stay metadata-only until a hardware-scoped capture proves safe polling.
    controller_node = graph.heating_controller_result().node if graph is not None else None

    # BAS*/BASS* heating controllers (e.g. `Vaillant;BASS3;0708;4304`)
    # expose the zone-1 day setpoint at sub-address 0x22, not the 0x07 slot
    # the shipped `15.700`-lineage CSV poll uses. On this family the 0x07
    # read returns `ERR: invalid position` while 0x22 decodes a live value
    # (upstream issue #646 BASS0 live read, #522 "0700 -> 2200", #1063 root
    # cause; community fixtures for ctlv0/ctlv3 confirm 0x22). Both read and
    # write definitions are overridden because the shipped write path still
    # targets 0x07. Hardware-gated so ctlv2/ctlv3 (where 0x07 works) remain
    # unaffected.
    if controller_node and controller_node.scan_type.upper().startswith("BAS"):
        circuit = controller_node.circuit
        defines.append(
            f"r5,{circuit},Z1DayTemp,Z1DayTemp,31,15,B524,020003002200"
            ",ign,,IGN:4,,,,value,,EXP,,°C,day setpoint for zone 1"
        )
        defines.append(
            f"wi,{circuit},Z1DayTemp,Z1DayTemp,31,15,B524,020103002200,value,m,EXP,,°C,day setpoint for zone 1"
        )
        # Upstream issue #522 documents the same 0x07 -> 0x22 move for
        # Z1..Z3 on BASV3. Enable Zone 2 only when its room-temperature
        # register has a live value; inactive placeholder zones stay out
        # of active polling. This is a reasonable, fixture-backed
        # assumption for the BASS3 scope captured in issue #129.
        if any(key.casefold() == f"{circuit}.Z2RoomTemp".casefold() for key in graph.raw_registers):
            defines.extend(
                [
                    f"r5,{circuit},Z2DayTemp,Z2DayTemp,31,15,B524,020003012200"
                    ",ign,,IGN:4,,,,value,,EXP,,°C,day setpoint for zone 2",
                    f"wi,{circuit},Z2DayTemp,Z2DayTemp,31,15,B524,020103012200,value,m,EXP,,°C,day setpoint for zone 2",
                ]
            )

    defines = [definition for definition in (_resolve_definition_circuit(item) for item in defines) if definition]
    if is_hmux0_0303_0504:
        sw0303 = hmux0_sw0303_circuit
        assert sw0303 is not None
        defines.extend(
            [
                # Upstream ebusd-configuration PR #496 (merged) defines flow as ext 0xfc/0x08 next to
                # return (0x06/0x09); both decode as tempv (1/16 degC), confirmed live in issue #171.
                f"r,{sw0303},RunDataFlowTemp,RunDataFlowTemp,31,08,B509,540200fc08"
                ",value,,IGN:4,,,,value,,D2C,,°C,HMUX0 flow temperature",
                f"r,{sw0303},RunDataReturnTemp,RunDataReturnTemp,31,08,B509,5402000609"
                ",value,,IGN:4,,,,value,,D2C,,°C,HMUX0 return temperature",
                f"r,{sw0303},YieldHc,YieldHc,31,08,B51A,05ff3210,value,,IGN:3,,,,value,,UIN,,kWh,HMUX0 heating yield",
                f"r,{sw0303},YieldHcDay,YieldHcDay,31,08,B51A,05ff3200"
                ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 heating yield today",
                f"r,{sw0303},YieldHcMonth,YieldHcMonth,31,08,B51A,05ff320e"
                ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 heating yield this month",
                f"r,{sw0303},YieldHwc,YieldHwc,31,08,B51A,05ff3216,value,,IGN:3,,,,value,,UIN,,kWh,HMUX0 DHW yield",
                f"r,{sw0303},YieldHwcDay,YieldHwcDay,31,08,B51A,05ff3202"
                ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 DHW yield today",
                f"r,{sw0303},YieldHwcMonth,YieldHwcMonth,31,08,B51A,05ff3212"
                ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 DHW yield this month",
                f"r,{sw0303},CopHc,CopHc,31,08,B51A,05ff3211,value,,IGN:3,,,,value,,UIN,10,,HMUX0 heating COP",
                f"r,{sw0303},CopHcMonth,CopHcMonth,31,08,B51A,05ff320f"
                ",value,,IGN:3,,,,value,,UIN,10,,HMUX0 heating COP this month",
                f"r,{sw0303},CopHwc,CopHwc,31,08,B51A,05ff3217,value,,IGN:3,,,,value,,UIN,10,,HMUX0 DHW COP",
                f"r,{sw0303},CopHwcMonth,CopHwcMonth,31,08,B51A,05ff3213"
                ",value,,IGN:3,,,,value,,UIN,10,,HMUX0 DHW COP this month",
            ]
        )
    if is_hmux0_b509_0504:
        assert heat_pump is not None
        circuit = heat_pump.circuit
        defines.extend(
            [
                f"r,{circuit},RunDataCompressorSpeed,RunDataCompressorSpeed,31,08,B509,5402000d0a"
                ",value,,IGN:4,,,,value,,EXP,,rps,HMUX0 compressor speed",
                f"r,{circuit},RunDataBuildingCPumpPower,RunDataBuildingCPumpPower,31,08,B509,540200c509"
                ",value,,IGN:4,,,,value,,EXP,,%,HMUX0 building circuit pump power",
            ]
        )
    if hmux0_sw0407_owner is not None:
        defines.extend(
            f"u,{hmux0_sw0407_owner},{name},{name},f1,08,{message_id},{subaddress},{fields}"
            for name, message_id, subaddress, fields in HMUX0_SW0407_PASSIVE_REGISTERS
        )
    if is_vwzio_0500_0504 and vwzio is not None:
        # The dump captures the gateway's passive B516/14 station-power frame.
        # Unlike PR #598's later SW0901 active read, this definition only decodes observed traffic.
        defines.append(
            f"u,{vwzio.circuit},PowerConsumptionVwz,PowerConsumptionVwz,f1,76,B516,14"
            ",value,,IGN:1,,,,value,,EXP,1000,kW,Hydraulic station power consumption"
        )
        # Intent: decode the captured DHW backup-heater runtime/start counters without polling.
        # Why: issue #161 correlates the HW0504 delta to two runs; absent data must stay unavailable.
        defines.append(
            f"u,{vwzio.circuit},RunStatsImmersionHeaterHwc,RunStatsImmersionHeaterHwc,f1,76,B511,1802"
            ",ign,,IGN:1,,,,runtime,,ULG,,min,,cycles,,ULG"
        )
        # Intent: decode the captured backup-heater DHW heat total (B516 source 0x49, usage 04) without polling.
        # Why: strong assumption from the issue #161 capture (6487 Wh against 106 min of heater runtime);
        # the layout matches the Hwc counters, and the entity is disabled by default and unavailable when absent.
        defines.append(
            f"u,{vwzio.circuit},HeaterYieldHwcTotal,HeaterYieldHwcTotal,f1,76,B516,1000ffff49040000"
            ",ign,,IGN:7,,,,value,,EXP,,Wh,Backup heater DHW heat total (assumed)"
        )
        # Status01's active field layout is documented for VWZIO HW5103, not this HW0504 scan.
        defines = [
            definition
            for definition in defines
            if not (definition.startswith(("r,vwz,Status01,", "r,vwzio,Status01,")))
        ]
    if not is_hmux0_0303_0504:
        defines = [definition for definition in defines if ",Status00," not in definition]
    if not is_hmux0_b509_0504:
        defines = [
            definition
            for definition in defines
            if not (definition.split(",", 3)[0] == "r" and definition.split(",", 3)[2] == "RunDataElPowerConsumption")
        ]
    if heat_pump and node_matches(HMU00_HW5103, heat_pump):
        # Upstream ebusd-configuration PR #614, confirmed for HW5103.
        # Status07 is active-read because this HW5103 variant polls b511/07;
        # unsupported hardware returns ERR and remains absent from entities.
        defines.append(
            f"r,{heat_pump.circuit},Status07,Status07,31,08,B511,07"
            ",power,,UCH,,%,,dailyenvyield,,UIN,10,kWh,"
            ",display_b0_heaterenabled,,BI0,0=off;1=on,,"
            ",display_b1,,BI1,0=off;1=on,,"
            ",display_b2_backupheater,,BI2,0=off;1=on,,"
            ",display_b3,,BI3,0=off;1=on,,"
            ",display_b4,,BI4,0=off;1=on,,"
            ",display_b5_noisereduction,,BI5,0=off;1=on,,"
            ",display_b6_dhwecomode,,BI6,0=off;1=on,,"
            ",display_b7,,BI7,0=off;1=on,,"
            ",heatermain_b0,,BI0,0=off;1=on,,"
            ",heatermain_b1_error,,BI1,0=off;1=on,,"
            ",heatermain_b2,,BI2,0=off;1=on,,"
            ",heatermain_b3_heating,,BI3,0=off;1=on,,"
            ",heatermain_b4_cooling,,BI4,0=off;1=on,,"
            ",heatermain_b5_pressureloss,,BI5,0=off;1=on,,"
            ",heatermain_b6,,BI6,0=off;1=on,,"
            ",heatermain_b7_warmwater,,BI7,0=off;1=on,,"
            ",displaypressure,,UCH,30,bar,,"
            ",heaterbackup_b0,,BI0,0=off;1=on,,"
            ",heaterbackup_b1_error,,BI1,0=off;1=on,,"
            ",heaterbackup_b2,,BI2,0=off;1=on,,"
            ",heaterbackup_b3_heating,,BI3,0=off;1=on,,"
            ",heaterbackup_b4_cooling,,BI4,0=off;1=on,,"
            ",heaterbackup_b5_pressureloss,,BI5,0=off;1=on,,"
            ",heaterbackup_b6,,BI6,0=off;1=on,,"
            ",heaterbackup_b7_warmwater,,BI7,0=off;1=on,,"
        )
    return defines
