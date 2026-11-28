"""Build the list of runtime ``define`` strings for the discovered hardware.

Pure functions (no I/O): the coordinator sends the result to ebusd. Every definition is
evidence-backed (upstream or community capture) and resolved against the discovered
device graph, never against a guessed circuit.
"""

from __future__ import annotations

from datetime import datetime

from .hardware_profiles import (
    BASS3_SW0708,
    CTLV2_SW0514,
    CTLV3_SW0808,
    HMU00_B509_POWER,
    HMU00_HW5103,
    HMU00_SW0308,
    HMU00_SW0522,
    HMUX0_B509_MONITORING,
    HardwareProfile,
    node_matches,
    profile_owner,
    scan_matches,
)
from .mapping import (
    HMUX0_SW0407_ACTIVE_READ_REGISTERS,
    HMUX0_SW0407_ENVYIELD_REGISTERS,
    b516_date_bytes,
    hmux0_candidate_circuits,
    hmux0_owner_scan,
    hmux0_status_code_owner,
    hmux0_sw0303_owner,
    hmux0_sw0406_owner,
    hmux0_sw0407_circuit,
    vwz_station_scan_76_circuit,
    vwzio_sw0500_circuit,
)
from .models import (
    HMUX0_STATUS_CODE_VALUES,
    DeviceGraph,
    DeviceType,
    ResolutionStatus,
    is_controller_circuit,
    is_heat_pump_circuit,
)

# VWZIO/VWZ Status01 field layout (upstream PR #598); reuses the HMU layout. `8=venting` comes from the community CSV
# (R91g, upstream PR #707): without it a venting pump showed the bare number.
# Explicit types are required: the hcmode_inc template aliases (temp1/temp2/
# pumpstate) are not resolvable in a runtime `define`.
VWZ_STATUS01_FIELDS = (
    "temp,,D1C,,,,temp_1,,D1C,,,,temp_2,,D2B,,,,temp_3,,D1C,,,,temp_4,,D1C,,,,"
    "pumpstate,,UCH,0=off;1=on;2=overrun;4=hwc;8=venting,,"
)

# Field layout of the HMUX0 B511/00 compressor status block (upstream issues #249/#522/#687, PR #330).
# The active SW0303 read and the passive SW0407 decode share one layout so both fill the same entity fields.
# Modulation and power count in 0.5 % steps (community CSV R91g, display check by lars077): issue #254 read 200 raw at
# full load, and issue #252 shows 106 raw (53 %) at 67.8 rps. Both use an explicit `UCH,2`, the form issue #254 read
# live; the earlier `percent1` template is not proven to resolve in a runtime `define`.
HMUX0_STATUS00_FIELDS = (
    "supplytemp,,D2C,,°C,,waterpressure,,UCH,10,bar,,"
    "compressormodulation,,UCH,2,%,,compressorstate,,UCH,0=off;1=heating_prerun;"
    "4=heating;5=heating_overrun;24=hot_water;110=defrosting,,,"
    "heatingstate,,UCH,8=off;9=heating,,,field6,,UCH,,,,"
    "defrost,,UCH,0=inactive;32=active,,,compressorpower,,UCH,2,%,HMUX0 Status00"
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
    # Community CSV rows (R91g/arotherm-genia-ebusd, upstream PR #707) whose gateway frames our SW0407 captures decode.
    # Confirmed: compressor hours/starts equal the B511 1801+1802 sums in issue #161 (15 h vs 942 min, 28 = 12 + 16);
    # the fan counters run with the compressor (16 h, 29 starts). The rest are strong assumptions: plausible values,
    # no second source yet, so their entities start disabled.
    *(
        (name, "B509", f"540200{ext}", f"value,,IGN:4,,,,value,,UIN,,{unit},")
        for name, ext, unit in (
            ("RunStatsCompressorHours", "c20b", "h"),
            ("RunStatsCompressorStarts", "c30b", ""),
            ("RunStatsFan1Hours", "d70b", "h"),
            ("RunStatsFan1Starts", "d80b", ""),
            ("RunStatsFan2Hours", "d90b", "h"),
            ("RunStatsFan2Starts", "da0b", ""),
            ("RunStatsDeiceHours", "e30b", "h"),
            ("RunStatsDeiceStarts", "e40b", ""),
            ("RunStatsCoolingHours", "e10b", "h"),
            ("RunStatsCoolingStarts", "e20b", ""),
        )
    ),
    # Current error of the outdoor unit (`B503 0001`, the Vaillant error layout ebusd uses for every device; community
    # CSV row Currenterror). The first slot as SIN: an empty slot (`ffff`) reads -1, shown as `none`; F.22 reads 22.
    ("Currenterror", "B503", "0001", "error,,SIN,,,,ign,,IGN:8,,,"),
    ("RunDataEvaporationTemp", "B509", "540200d110", "value,,IGN:4,,,,value,,D2C,,°C,temperature"),
    ("RunDataCondensateTemp", "B509", "540200db10", "value,,IGN:4,,,,value,,D2C,,°C,temperature"),
    ("RunDataHeatOutput", "B509", "5402005e0d", "value,,IGN:4,,,,value,,EXP,,W,"),
)

# Installer settings of the heat pump (display D-codes), read over `B51A 05ff <id>`. The answer is three header bytes,
# the value, then minimum, maximum and step (owner live: `-60` with `9c ff e2 ff 05` = -100..-30 step 5). Names and
# D-codes follow the community CSV (R91g, display-checked); the owner's HMU00 SW0522 answered every row with the
# CSV's display values, and issue #218 read D.230 on HMU00 SW0308 (-119 degmin). The names appear in no ebusd CSV we
# know (ebusd's hmu CSV on other units has `CompressorHysteresisHc/Cooling`, which stay its own), so a definition never
# replaces a CSV message and the set does not depend on what ebusd lists. (name, id, value fields, profiles)
HEAT_PUMP_SETTING_LIMITS = "limits,,IGN:5,,,"
HEAT_PUMP_SETTINGS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("CompressorStartHeating", "05ff341e", "value,,SIN,,°min,", ("hmu00_sw0522", "hmux0_sw0407", "hmu00_sw0308")),
    ("CompressorStartCooling", "05ff3421", "value,,SIN,,°min,", ("hmu00_sw0522", "hmux0_sw0407")),
    ("CompressorHysteresisHeat", "05ff3443", "value,,SIN,16,K,", ("hmu00_sw0522", "hmux0_sw0407", "hmu00_sw0308")),
    ("CompressorHysteresisCool", "05ff353f", "value,,SIN,16,K,", ("hmu00_sw0522", "hmux0_sw0407")),
    ("MaxResidualHead", "05ff341f", "value,,UIN,,mbar,", ("hmu00_sw0522", "hmux0_sw0407", "hmu00_sw0308")),
    ("BrineFrostProtection", "05ff3429", "value,,SIN,16,°C,", ("hmu00_sw0308",)),
)
HEAT_PUMP_SETTING_NAMES = frozenset(name for name, *_ in HEAT_PUMP_SETTINGS)


# Build the installer setting reads for the heat pump owners with evidence (owner HMU00, HMUX0 SW0407 profile, and
# on HMU00 SW0308 D.230, D.267 and D.231, the three ids issue #218 read there; 3421 and 353f answer too short).
# Plain `r`: the energy poll re-reads them, nobody else asks for them.
def heat_pump_setting_definitions(graph: DeviceGraph | None) -> list[str]:
    if graph is None:
        return []
    owners = {
        "hmu00_sw0522": profile_owner(graph, HMU00_SW0522),
        "hmux0_sw0407": hmux0_sw0407_circuit(graph),
        "hmu00_sw0308": profile_owner(graph, HMU00_SW0308),
    }
    definitions: list[str] = []
    for name, ident, fields, profiles in HEAT_PUMP_SETTINGS:
        for profile in profiles:
            circuit = owners[profile]
            # No "already listed" check: ebusd lists our own definitions after the first define, and the settings
            # must survive the next discovery (their re-read depends on it).
            if circuit is not None:
                definitions.append(
                    f"r,{circuit},{name},{name},31,08,B51A,{ident},ign,,IGN:3,,,,{fields},{HEAT_PUMP_SETTING_LIMITS}"
                )
    return list(dict.fromkeys(definitions))


# Passive definition of the outdoor unit status code on the HMUX0 owner. Blank source: whichever master asks.
def hmux0_status_code_definition(circuit: str) -> str:
    return (
        f"u,{circuit},HMUStatusCode,HMUStatusCode,,08,B503,0003,value,,UIN,{HMUX0_STATUS_CODE_VALUES},,,ign,,IGN:8,,,"
    )


# HMUX0/HW0504 telegrams that the controller (0x10, about every 10 s) and the gateway (0xf1) poll.
# Issue #175 capture - a blank source address lets one passive definition decode either sender; the Status01
# layout matches five display values (flow, return, outside, storage, setpoint) and Status00 matches flow and state.
# SW0406 answers the controller's polls with the same 9-byte layouts (issue #254; #188 and discussion 31 captures:
# 33.6 degC/1.7 bar and 42.7 degC/1.9 bar while heating). The `ERR: invalid position` seen for SW0406 in #188 came
# from the longer HMU CSV layout, not from a missing answer.
HMUX0_ANY_MASTER_REGISTERS = (
    ("Status01", "B511", "01", VWZ_STATUS01_FIELDS),
    ("Status00", "B511", "00", HMUX0_STATUS00_FIELDS),
)

# VWZIO SW0500/HW0504 B512/030f0001 passive temperatures (strong assumption, single captured state).
# Issue #175 capture - D2C bytes 0-1 read 46.56 degC (display storage 46.5) and bytes 3-4 read 30.0 degC
# (display flow after the backup heater 30.0); the other bytes stay ignored until a second state explains them.
VWZIO_SW0500_ANY_MASTER_REGISTERS = (
    (
        "StationTemperatures",
        "B512",
        "0f0001",
        "storagetemp,,D2C,,°C,,ign1,,IGN:1,,,,flowtemp,,D2C,,°C,,ign2,,IGN:2,,,",
    ),
)

# HMUX0 compressor runtime/start counters that are defined as plain `r` messages on SW0406.
# ebusd never polls plain `r` messages and their entities are off by default, so the energy poll re-reads them.
HMUX0_COMPRESSOR_COUNTER_NAMES = frozenset({"CompressorHc", "CompressorHwc"})

# Controller registers defined as plain `r` that the integration reads itself on the energy interval.
# Issue #193 - as `r5` ebusd polled them on its own, about 76,000 bus errors a day on a stuck adapter, and the bus
# guard could not pause that. The integration's reads go through the guard.
INTEGRATION_POLLED_CONTROLLER_REGISTERS = frozenset(
    {"z1RoomHumidity", "ManualCoolingStartDate", "ManualCoolingEndDate"}
)

# Heat-pump registers that ebusd's own CSV defines as plain `r` (issue #227: `PowerConsumptionHmu`, `b516 14` in
# `08.hmu.HW5103.csv`). ebusd never polls them and `find` lists them, so the map-driven pass skips them; the energy
# poll re-reads them on the circuit where they were discovered.
DISCOVERED_PLAIN_READ_POLLED_REGISTERS = frozenset({"PowerConsumptionHmu"})
# Heat pump counters that ebusd's HMU CSV defines as plain `r` (issue #233), re-read on the energy interval. Only on
# the discovered heat pump: boilers and hydraulic stations list the same names with other layouts and costs.
HEAT_PUMP_PLAIN_READ_ENERGY_REGISTERS = frozenset(
    {"RunStatsCompressorStarts", "StatElectricEnergySum", "StatEnvironmentEnergySum"}
)
# Registers of `_hmux0_sw0406_active_definitions` (issue #205) and the power read (issue #255), re-read on every poll
# on the SW0406 owner.
HMUX0_SW0406_ACTIVE_READ_REGISTERS = frozenset(
    {
        "BuildingCircuitFlow",
        "RunDataFlowTempDesired",
        "RunDataCondensorOutletTemp",
        "EnergyIntegral",
        "RunDataElPowerConsumption",
        "RunDataFan1Speed",
        "RunDataFan2Speed",
    }
)
# Boiler fuel counters (B516 `StatFuelSum*`, upstream `b516_inc.tsp`) that ebusd defines as plain `r` (discussion
# #242): they froze for days and then jumped by the missed consumption. Re-read on the energy interval, only where the
# integration maps the register (the boiler); other devices list the same B516 names without a meaning we show.
BOILER_PLAIN_READ_ENERGY_REGISTERS = frozenset({"StatFuelSum", "StatFuelSumHc", "StatFuelSumHwc"})
# Heat pump source values that ebusd's HMU CSV defines as plain `r`, re-read on every poll: the temperatures of issue
# #233 and the brine pressure of issue #251. Air/water units answer the B51A source reads with a 3-byte stub; the failed
# read puts the register in the graph's error registers, so it is not read again.
HEAT_PUMP_PLAIN_READ_EVERY_POLL_REGISTERS = frozenset({"SourceTempInput", "SourceTempOutput", "SourcePressure"})
# Heat pump live values that ebusd's HMU CSV defines as plain `r` (`B51A 05ff32xx`, checked with `find -f` on the
# owner's HMU00): issue #259, they froze after the first read on an aroTHERM without a gateway. Power and yield
# follow the compressor, so they are read every poll; flow, weighted supply temperature and the energy integral change
# slowly and follow the energy interval. On a bus with a myVAILLANT gateway its reads keep them fresh as well. The
# decoding is ebusd's own; each read still passes the planner's gate (error, unreliable and withheld registers).
# Issue #259 (HMU00 SW0517 capture): the yields, COPs, compressor utilisation and block time and the total energy are
# the same plain `r` family (`B51A 05ff32xx`, upstream `08.hmu.HW5103.tsp`); the gateway never reads them, and the
# capture's `changes` show them frozen while power changed. Utilisation follows the compressor (every poll), the
# counters and averages follow the energy interval.
HEAT_PUMP_LIVE_EVERY_POLL_REGISTERS = frozenset({"CurrentConsumedPower", "CurrentYieldPower", "CurrentCompressorUtil"})
HEAT_PUMP_LIVE_ENERGY_REGISTERS = frozenset(
    {
        "SupplyTempWeighted",
        "BuildingCircuitFlow",
        "EnergyIntegral",
        "YieldHc",
        "YieldHcDay",
        "YieldHcMonth",
        "YieldHwc",
        "YieldHwcDay",
        "YieldHwcMonth",
        "YieldCooling",
        "YieldCoolingMonth",
        "YieldCoolDay",
        "CopHc",
        "CopHcMonth",
        "CopHwc",
        "CopHwcMonth",
        "CopCooling",
        "CopCoolingMonth",
        "TotalEnergyUsage",
        "CompressorBlocktime",
    }
)
# The boiler's flame state, a plain `r` message in ebusd's BAI configuration (issue #152): nobody re-read it, so it
# flipped between a stale value and unknown. Only boiler configurations define these names.
BOILER_FLAME_REGISTERS = frozenset({"Flame", "FlameSensingASIC"})
# Controller hot water circulation pump state, a plain `r` message in ebusd's CTLV2 configuration (issue #233).
HWC_CIRCULATION_PUMP_STATUS = "HwcCircPumpStatus"

# Hot water timer slots 1 and 2 per weekday, read with `B555 a5 00 02 <day> <slot>` (issue #208).
# The 7-byte answer is status, from HH MM, to HH MM and 2 bytes (probably the slot temperature). The status byte is
# ignored like in the shipped slot-0 message: a missing slot (status 02) answers 00:00-00:00, which reads as empty.
# The temperature is left out on purpose so slots 1 and 2 match slot 0 and the `index;count;from;to` write message.
HWC_TIMER_SLOT_FIELDS = "ign,,IGN:1,,,,from,,HTM,,,,to,,HTM,,,"
HWC_TIMER_EXTRA_SLOTS = (1, 2)
# Day byte order of the slot request. Tuesday = 01 is captured (issue #208); Monday = 00 follows the generic
# `HwcTimer_<Day>` read in flexocompact_find.txt (`a5000200` Monday ... `a5000203` Thursday).
TIMER_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# Slot reads of one weekly program over `B555 a5 00 <program> <day> <slot>`, named `<prefix>_<Day><slot>` like the
# messages the calendar and the time program services read. One builder for every controller that needs them.
def b555_slot_definitions(circuit: str, prefix: str, program: int, slots: tuple[int, ...], fields: str) -> list[str]:
    return [
        f"r,{circuit},{prefix}_{day}{slot},{prefix}_{day}{slot},31,15,B555,a500{program:02x}{index:02x}{slot:02x},"
        + fields
        for index, day in enumerate(TIMER_WEEKDAYS)
        for slot in slots
    ]


# Slot count read of one weekly program over `B555 a4 00 <program>`: a status byte, one count per weekday and a
# trailing byte (issue #256 capture `09 00 02 02 02 02 02 02 02 00`; issue #235 table).
def b555_slot_count_definition(circuit: str, prefix: str, program: int) -> str:
    days = ",".join(f"{day[:2].lower()},,UCH,,," for day in TIMER_WEEKDAYS)
    return (
        f"r,{circuit},{prefix}_Timeslots,{prefix}_Timeslots,31,15,B555,a400{program:02x}"
        f",ign,,IGN:1,,,,{days},end,,IGN:1,,,"
    )


# Return the heating controller circuit when it is the unique controller and matches the profile, else None.
def _controller_for_profile(graph: DeviceGraph, profile: HardwareProfile) -> str | None:
    controller = graph.heating_controller_result()
    owner = profile_owner(graph, profile)
    if (
        controller.status != ResolutionStatus.UNIQUE
        or controller.node is None
        or owner is None
        or owner.casefold() != controller.node.circuit.casefold()
    ):
        return None
    return controller.node.circuit


# Build the slot 1 and 2 reads of the hot water timer for a CTLV2 SW0514 whose configuration decodes only slot 0.
# Gated on the scan identity and on the `HwcTimer_Timeslots` layout; the `HwcTimer_Timeframes` layout (the owner's
# CTLV2) already ships slots 0-2 with a temperature, so nothing is defined there. Absent hardware gets nothing.
def hwc_timer_slot_definitions(graph: DeviceGraph | None) -> list[str]:
    if graph is None:
        return []
    circuit = _controller_for_profile(graph, CTLV2_SW0514)
    if circuit is None:
        return []
    keys = {key.casefold() for key in (*graph.raw_registers, *graph.placeholder_registers)}
    if f"{circuit}.hwctimer_timeslots".casefold() not in keys or f"{circuit}.hwctimer_timeframes".casefold() in keys:
        return []
    return b555_slot_definitions(circuit, "HwcTimer", 0x02, HWC_TIMER_EXTRA_SLOTS, HWC_TIMER_SLOT_FIELDS)


# Build the silent mode slot 1 and 2 reads for a CTLV3 SW0808 whose configuration decodes slot 0 only (issue #256).
# Gated on the scan identity and on ebusd listing its own `SilentTimer_Timeslots` and slot 0. The gate must not look
# at slot 1: after the first define ebusd lists our own slot 1, and the next discovery would drop the set (and with it
# the read-only guard).
def silent_timer_slot_definitions(graph: DeviceGraph | None) -> list[str]:
    if graph is None:
        return []
    circuit = _controller_for_profile(graph, CTLV3_SW0808)
    if circuit is None:
        return []
    keys = {key.casefold() for key in (*graph.raw_registers, *graph.placeholder_registers)}
    if not all(key in keys for key in (f"{circuit}.silenttimer_timeslots", f"{circuit}.silenttimer_monday0")):
        return []
    return b555_slot_definitions(circuit, "SilentTimer", 0x04, HWC_TIMER_EXTRA_SLOTS, HWC_TIMER_SLOT_FIELDS)


# BASS3 weekly programs and their `B555` program byte (issue #235). Each slot answer carries the slot temperature in
# 0.1 degC (`d2 00` = 21.0); the circulation program answers `ffff`, which reads as no temperature.
BASS3_B555_PROGRAMS = (("Z1Timer", 0x00), ("Z1CoolingTimer", 0x01), ("HwcTimer", 0x02), ("CcTimer", 0x03))
B555_SLOT_FIELDS_WITH_TEMPERATURE = HWC_TIMER_SLOT_FIELDS + ",temp,,UIN,10,°C,"
B555_ALL_SLOTS = (0, 1, 2)


# Build the B555 slot and count reads of the BASS3 weekly programs (issue #235), read-only.
# Gated on the scan identity and on ebusd listing the B524 day message `Z1Timer_Monday` that the BASS3 answers empty.
# The gate never looks at the slot names: ebusd lists ours after the first define, and the set (with the read-only
# guard) must survive the next discovery.
def bass3_timer_definitions(graph: DeviceGraph | None) -> list[str]:
    if graph is None:
        return []
    circuit = _controller_for_profile(graph, BASS3_SW0708)
    if circuit is None:
        return []
    keys = {key.casefold() for key in (*graph.raw_registers, *graph.placeholder_registers)}
    if f"{circuit}.z1timer_monday" not in keys:
        return []
    definitions: list[str] = []
    for prefix, program in BASS3_B555_PROGRAMS:
        definitions.extend(
            b555_slot_definitions(circuit, prefix, program, B555_ALL_SLOTS, B555_SLOT_FIELDS_WITH_TEMPERATURE)
        )
        definitions.append(b555_slot_count_definition(circuit, prefix, program))
    return definitions


# The `circuit.name` keys (casefolded) of registers the integration defines under a strong assumption, so their
# entities start disabled (docs/register-discovery.md); a YAML `enabled: true` override still wins. Only where the
# integration defines them: on a SW0406 bus whose ebusd loads its own hmux0 CSV the same names come from that CSV.
# SW0406 refrigerant temperatures (#205): floats on SW0406 (flow, condenser outlet) and on the owner's HMU00, but no
# SW0406 frame of these four ids exists yet.
def strong_assumption_register_keys(graph: DeviceGraph | None) -> frozenset[str]:
    if graph is None:
        return frozenset()
    if hmux0_sw0406_owner(graph) is None:
        return frozenset()
    # The full build decides, because the "own CSV" check needs every name the integration defines on the circuit.
    # The date only enters the B516 day/month ids, never a name.
    names = {name.casefold() for name in HMUX0_SW0406_ENERGY_READ_REGISTERS}
    return frozenset(
        ".".join(parts[1:3]).casefold()
        for definition in build_runtime_defines(graph, datetime(2026, 1, 1))
        if (parts := definition.split(",", 3))[0] == "r" and parts[2].casefold() in names
    )


# The `circuit.name` keys (casefolded) of the slot and count messages the integration defines for a calendar. The
# entity factory creates no sensors for them; ebusd's own slot messages are not in this set and keep their entities.
def calendar_slot_register_keys(graph: DeviceGraph | None) -> frozenset[str]:
    return frozenset(
        ".".join(definition.split(",", 3)[1:3]).casefold()
        for definition in (*silent_timer_slot_definitions(graph), *bass3_timer_definitions(graph))
    )


# Weekly programs that the integration reads over its own `B555` definitions but must not write: their write
# message was never tested on that controller (every BASS3 program: ebusd's `Z1Timer_<Day>` write is the B524 message
# the BASS3 answers empty). The CTLV3 SW0808 silent mode program is writable since issue #256: the reporter wrote
# ebusd's own `SilentTimer_<Day>` slot by slot in the integration's order, and read-back and display matched.
# `TimerProgramAccess` refuses a write to these before the first bus write. Returns (casefolded circuit, casefolded
# prefix) pairs.
def read_only_timer_programs(graph: DeviceGraph | None) -> frozenset[tuple[str, str]]:
    programs: set[tuple[str, str]] = set()
    for definition in bass3_timer_definitions(graph):
        circuit, name = definition.split(",", 3)[1:3]
        programs.add((circuit.casefold(), name.split("_", 1)[0].casefold()))
    # A silent mode program on any controller other than the tested CTLV3 SW0808 stays read-only, also when its
    # configuration lists all slots (which would create an editable calendar).
    if graph is not None and not silent_timer_slot_definitions(graph):
        for key in (*graph.raw_registers, *graph.placeholder_registers):
            circuit, _, name = key.partition(".")
            if name.casefold().startswith("silenttimer_"):
                programs.add((circuit.casefold(), "silenttimer"))
    return frozenset(programs)


# Runtime definitions of the HMUX0 precise flow/return temperatures and the yield/COP statistics.
# ebusd's own CSV lacks them for SW0303 (issue #171) and for a SW0406 bus without an hmux0 configuration (#185);
# upstream PR #496 defines flow as ext 0xfc/0x08 next to return (0x06/0x09). SW0303 answers tempv (1/16 degC, `D2C`),
# SW0406 answers the same ids with a 4-byte float (`EXP`, issue #188: `00 80 05 42` is 33.375 degC), so the caller
# picks the layout with `float_temperatures`.
def _hmux0_precise_and_yield_definitions(circuit: str, float_temperatures: bool = False) -> list[str]:
    temperature_type = "EXP" if float_temperatures else "D2C"
    return [
        f"r,{circuit},RunDataFlowTemp,RunDataFlowTemp,31,08,B509,540200fc08"
        f",value,,IGN:4,,,,value,,{temperature_type},,°C,HMUX0 flow temperature",
        f"r,{circuit},RunDataReturnTemp,RunDataReturnTemp,31,08,B509,5402000609"
        f",value,,IGN:4,,,,value,,{temperature_type},,°C,HMUX0 return temperature",
        f"r,{circuit},YieldHc,YieldHc,31,08,B51A,05ff3210,value,,IGN:3,,,,value,,UIN,,kWh,HMUX0 heating yield",
        f"r,{circuit},YieldHcDay,YieldHcDay,31,08,B51A,05ff3200"
        ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 heating yield today",
        f"r,{circuit},YieldHcMonth,YieldHcMonth,31,08,B51A,05ff320e"
        ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 heating yield this month",
        f"r,{circuit},YieldHwc,YieldHwc,31,08,B51A,05ff3216,value,,IGN:3,,,,value,,UIN,,kWh,HMUX0 DHW yield",
        f"r,{circuit},YieldHwcDay,YieldHwcDay,31,08,B51A,05ff3202"
        ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 DHW yield today",
        f"r,{circuit},YieldHwcMonth,YieldHwcMonth,31,08,B51A,05ff3212"
        ",value,,IGN:3,,,,value,,UIN,10,kWh,HMUX0 DHW yield this month",
        f"r,{circuit},CopHc,CopHc,31,08,B51A,05ff3211,value,,IGN:3,,,,value,,UIN,10,,HMUX0 heating COP",
        f"r,{circuit},CopHcMonth,CopHcMonth,31,08,B51A,05ff320f"
        ",value,,IGN:3,,,,value,,UIN,10,,HMUX0 heating COP this month",
        f"r,{circuit},CopHwc,CopHwc,31,08,B51A,05ff3217,value,,IGN:3,,,,value,,UIN,10,,HMUX0 DHW COP",
        f"r,{circuit},CopHwcMonth,CopHwcMonth,31,08,B51A,05ff3213"
        ",value,,IGN:3,,,,value,,UIN,10,,HMUX0 DHW COP this month",
    ]


# Runtime definitions of the HMUX0 B509 compressor speed and building-circuit pump power.
# Community captures (issues #99/#161/#185) read both on HW0504 firmware; the ids exclude the length byte.
def _hmux0_b509_monitor_definitions(circuit: str) -> list[str]:
    return [
        f"r,{circuit},RunDataCompressorSpeed,RunDataCompressorSpeed,31,08,B509,5402000d0a"
        ",value,,IGN:4,,,,value,,EXP,,rps,HMUX0 compressor speed",
        f"r,{circuit},RunDataBuildingCPumpPower,RunDataBuildingCPumpPower,31,08,B509,540200c509"
        ",value,,IGN:4,,,,value,,EXP,,%,HMUX0 building circuit pump power",
    ]


# Runtime definitions of the HMUX0 compressor runtime/start counters for heating and DHW.
# B511 data 1801/1802 carry the same layout the SW0407 captures show passively (upstream 08.hmu.tsp); on SW0406
# the #188 capture reads them as `RunStatsCompressorHc = 2880;126`. The ebusd id excludes the length byte.
def _hmux0_compressor_counter_definitions(circuit: str) -> list[str]:
    fields = "ign,,IGN:1,,,,runtime,,ULG,,min,,cycles,,ULG"
    return [
        f"r,{circuit},CompressorHc,CompressorHc,31,08,B511,1801,{fields}",
        f"r,{circuit},CompressorHwc,CompressorHwc,31,08,B511,1802,{fields}",
    ]


# Active definition of the HMUX0 building circuit flow (discussion #213 on SW0407, issue #205 on SW0406).
# The reply `0aff080e8502...` holds three header bytes and the flow as UIN l/h. The id excludes the length byte
# (telegram `08b51a04 05ff323c`).
def _hmux0_building_circuit_flow_definition(circuit: str) -> str:
    return (
        f"r,{circuit},BuildingCircuitFlow,BuildingCircuitFlow,31,08,B51A,05ff323c"
        ",value,,IGN:3,,,,value,,UIN,,l/h,HMUX0 building circuit flow"
    )


# Active SW0406 definitions of issue #205. Two SW0406/HW0504 units answered `ebusctl hex` while running and idle:
# flow 683/689 and 1275/1276 l/h; desired flow 28.0/24.5 and 45.0/0.0 degC; condenser outlet 24.25/18.25 and
# 39.69/27.38 degC (B509 floats after the 4-byte echo, like the other SW0406 B509 registers); energy integral -139/0 and
# -76/99 degmin (upstream `08.hmu.tsp` EnergyIntegral ext 0x21, type `integral` = SIN, after three header bytes).
# ebusd has no hmux0 configuration for them, and the gateway never asks for them, so they are read actively.
def _hmux0_sw0406_active_definitions(circuit: str) -> list[str]:
    return [
        _hmux0_building_circuit_flow_definition(circuit),
        f"r,{circuit},RunDataFlowTempDesired,RunDataFlowTempDesired,31,08,B509,5402004a0d"
        ",value,,IGN:4,,,,value,,EXP,,°C,HMUX0 desired flow temperature",
        f"r,{circuit},RunDataCondensorOutletTemp,RunDataCondensorOutletTemp,31,08,B509,540200b608"
        ",value,,IGN:4,,,,value,,EXP,,°C,HMUX0 condenser outlet temperature",
        f"r,{circuit},EnergyIntegral,EnergyIntegral,31,08,B51A,05ff3221"
        ",value,,IGN:3,,,,value,,SIN,,°min,HMUX0 energy integral",
        # Fan speeds (issue #205): ebusd's hmu configuration defines them as `B509 540200470a`/`490a`, a float in rpm;
        # Zapgla's SW0406 `hex` answer `0080fb43` is 503.0 (D.372 showed 50.3 %), the owner's HMU00 read 621.6. A
        # single-fan unit answers the second one with an error, which stops its reads.
        f"r,{circuit},RunDataFan1Speed,RunDataFan1Speed,31,08,B509,540200470a"
        ",value,,IGN:4,,,,value,,EXP,,rpm,HMUX0 fan 1 speed",
        f"r,{circuit},RunDataFan2Speed,RunDataFan2Speed,31,08,B509,540200490a"
        ",value,,IGN:4,,,,value,,EXP,,rpm,HMUX0 fan 2 speed",
    ]


# SW0406 refrigerant circuit temperatures (issue #205, strong assumption: see `STRONG_ASSUMPTION_REGISTERS`). B509
# type-08 ids answer a 4-byte float after the 4-byte echo on SW0406 and on the owner's HMU00. Read on the energy
# interval (`HMUX0_SW0406_ENERGY_READ_REGISTERS`): diagnostics, not worth four reads on every poll.
HMUX0_SW0406_REFRIGERANT_TEMPERATURES = (
    ("RunDataAirInletTemp", "de08"),
    ("RunDataCompressorInletTemp", "9808"),
    ("RunDataCompressorOutletTemp", "a208"),
    ("RunDataEEVOutletTemp", "ac08"),
)
HMUX0_SW0406_ENERGY_READ_REGISTERS = frozenset(name for name, _ in HMUX0_SW0406_REFRIGERANT_TEMPERATURES)


# Build the SW0406 refrigerant circuit temperature reads (issue #205).
def _hmux0_sw0406_refrigerant_definitions(circuit: str) -> list[str]:
    return [
        f"r,{circuit},{name},{name},31,08,B509,540200{ext},value,,IGN:4,,,,value,,EXP,,°C,temperature"
        for name, ext in HMUX0_SW0406_REFRIGERANT_TEMPERATURES
    ]


# Read definition of the SW0406 electrical power, with a blank source so it also decodes the gateway's frame.
# Issue #188 - the SW0406 answer to `B509 5402005b0d` is a 4-byte float in watts (33.2 idle, 1341.4 running,
# 961.27 in the gateway frame), the same layout the SW0407 passive set uses. Issue #255 - without a myVAILLANT
# gateway nobody sends that frame, so a passive definition stayed unknown; an active read gave 2537.48 W. The
# integration re-reads it on every poll (`HMUX0_SW0406_ACTIVE_READ_REGISTERS`).
def _hmux0_power_definition(circuit: str) -> str:
    name, message_id, subaddress, fields = next(
        item for item in HMUX0_SW0407_PASSIVE_REGISTERS if item[0] == "RunDataElPowerConsumption"
    )
    return f"r,{circuit},{name},{name},,08,{message_id},{subaddress},{fields}"


# Passive any-master definitions of the B511 status blocks the controller polls from a SW0406 heat pump (issue #254).
# They cost no bus traffic and give Status00 (compressor state, defrost) and Status01 (flow, return, outside, pump).
def _hmux0_sw0406_any_master_definitions(circuit: str) -> list[str]:
    return [
        f"u,{circuit},{name},{name},,08,{message_id},{subaddress},{fields}"
        for name, message_id, subaddress, fields in HMUX0_ANY_MASTER_REGISTERS
    ]


# Runtime definitions for a SW0406/HW0504 bus whose ebusd supplies no hmux0 registers of its own.
# Issues #185/#188 - a default ebusd config lists only the registers this integration defined itself, so the
# evidenced yield, COP, temperature and compressor-counter registers must be defined at runtime. When ebusd lists
# any other hmux0 register its CSV is loaded (issue #171), so defining the same names would duplicate them.
def _hmux0_sw0406_definitions(graph: DeviceGraph, circuit: str, defines: list[str]) -> list[str]:
    candidates = [
        *_hmux0_precise_and_yield_definitions(circuit, float_temperatures=True),
        *_hmux0_b509_monitor_definitions(circuit),
        *_hmux0_compressor_counter_definitions(circuit),
        _hmux0_power_definition(circuit),
        *_hmux0_sw0406_active_definitions(circuit),
        *_hmux0_sw0406_any_master_definitions(circuit),
        *_hmux0_sw0406_refrigerant_definitions(circuit),
    ]
    if _ebusd_supplies_heat_pump_config(graph, circuit, (*defines, *candidates)):
        return []
    return candidates


# Whether ebusd lists a heat pump register that none of the given definitions on `circuit` provides, which means its
# own hmux0 (or copied hmu) CSV is loaded. Definitions of ours under the same message id would then clash with it.
def _ebusd_supplies_heat_pump_config(graph: DeviceGraph, circuit: str, definitions: tuple[str, ...]) -> bool:
    own_names = {
        parts[2].casefold()
        for definition in definitions
        if len(parts := definition.split(",", 3)) >= 3 and parts[1].casefold() == circuit.casefold()
    }
    heat_pump_circuits = {
        node.circuit.casefold() for node in graph.nodes.values() if node.device_type == DeviceType.HEAT_PUMP
    }
    for key in (*graph.raw_registers, *graph.placeholder_registers):
        key_circuit, _, key_name = key.partition(".")
        # A copied hmu CSV (issue #188) lists its registers under `hmu`, not the scanned circuit: also counts.
        if key_circuit.casefold() in heat_pump_circuits and key_name.split(".")[0].casefold() not in own_names:
            return True
    return False


# Compile the full list of runtime define strings for the graph's hardware.
# Keeping this pure lets tests assert the exact definitions per capture without a coordinator. The optional
# `withheld` set collects the (circuit, register) pairs whose definition was left out because the owner cannot
# answer it, so the read planner can skip them too (issue #179).
def build_runtime_defines(graph: DeviceGraph, now: datetime, withheld: set[tuple[str, str]] | None = None) -> list[str]:
    withheld_registers = withheld if withheld is not None else set()
    date_bytes = b516_date_bytes(now)
    defines = [
        "r,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800,value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity",
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
        "r,hmu,Status00,Status00,31,8,B511,00," + HMUX0_STATUS00_FIELDS,
        # HMUX0 HW0504 community capture: upstream issue #522 identifies
        # B509/540200/5b0d as diagnostic electrical power in watts.
        # This is additive; absent hardware returns no data.
        "r,hmu,RunDataElPowerConsumption,RunDataElPowerConsumption,31,8,B509"
        ",5402005b0d,value,,IGN:4,,,,value,,EXP,,W,"
        "HMUX0 electrical power consumption",
        "r,ctlv2,ManualCoolingStartDate,ManualCoolingStartDate,31,15,B524,02000000da00,value,,IGN:4,,,,value,,HDA:3",
        "r,ctlv2,ManualCoolingEndDate,ManualCoolingEndDate,31,15,B524,02000000db00,value,,IGN:4,,,,value,,HDA:3",
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
                _hmux0_building_circuit_flow_definition(circuit),
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

    # Compile each logical runtime definition against its discovered owner.
    # Definitions must never be sent to a guessed physical circuit.
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
            and parts[2] in HMUX0_SW0407_ENVYIELD_REGISTERS | HMUX0_SW0407_ACTIVE_READ_REGISTERS
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
        # B524 belongs to the VRC700-family controllers, never to a BAI boiler interface.
        # A BAI that owns control registers is resolved as the heating controller when the real controller
        # (e.g. a VRC350 `35000`) is not typed as one; the `r5` poll definitions then spin on `invalid position`
        # (issue #179). The scan id says what the node is, so no per-model circuit name is needed; the real
        # controller answers B524 with `00`, so re-targeting these definitions would not help either.
        if (
            is_controller_circuit(parts[1])
            and definition.split(",")[6:7] == ["B524"]
            and resolution.node is not None
            and resolution.node.scan_type.upper().startswith("BAI")
        ):
            withheld_registers.add((resolution.node.circuit.casefold(), parts[2].casefold()))
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
    defines.extend(hwc_timer_slot_definitions(graph))
    defines.extend(silent_timer_slot_definitions(graph))
    defines.extend(bass3_timer_definitions(graph))
    defines.extend(heat_pump_setting_definitions(graph))
    if is_hmux0_0303_0504:
        sw0303 = hmux0_sw0303_circuit
        assert sw0303 is not None
        defines.extend(_hmux0_precise_and_yield_definitions(sw0303))
    if is_hmux0_b509_0504:
        assert heat_pump is not None
        defines.extend(_hmux0_b509_monitor_definitions(heat_pump.circuit))
    # Before the SW0406 set: its "ebusd has its own hmux0 CSV" check must see the status code as one of ours.
    # Only without such a CSV: the symlinked hmu CSV already holds `B503 0003` (as `EnableiveMonitorMain`, issue #31 and
    # #99 captures), and a second definition on that id would clash with it.
    status_code_owner = hmux0_status_code_owner(graph)
    if status_code_owner is not None:
        status_code = hmux0_status_code_definition(status_code_owner)
        if not _ebusd_supplies_heat_pump_config(graph, status_code_owner, (*defines, status_code)):
            defines.append(status_code)
    hmux0_sw0406_circuit = hmux0_sw0406_owner(graph)
    if hmux0_sw0406_circuit is not None:
        defines.extend(_hmux0_sw0406_definitions(graph, hmux0_sw0406_circuit, defines))
    if hmux0_sw0407_owner is not None:
        defines.extend(
            f"u,{hmux0_sw0407_owner},{name},{name},f1,08,{message_id},{subaddress},{fields}"
            for name, message_id, subaddress, fields in HMUX0_SW0407_PASSIVE_REGISTERS
        )
        defines.extend(
            f"u,{hmux0_sw0407_owner},{name},{name},,08,{message_id},{subaddress},{fields}"
            for name, message_id, subaddress, fields in HMUX0_ANY_MASTER_REGISTERS
        )
    if is_vwzio_0500_0504 and vwzio is not None:
        # The dump captures the gateway's passive B516/14 station-power frame.
        # Unlike PR #598's later SW0901 active read, this definition only decodes observed traffic.
        defines.append(
            f"u,{vwzio.circuit},PowerConsumptionVwz,PowerConsumptionVwz,f1,76,B516,14"
            ",value,,IGN:1,,,,value,,EXP,1000,kW,Hydraulic station power consumption"
        )
        # Decode the captured DHW backup-heater runtime/start counters without polling.
        # Issue #161 correlates the HW0504 delta to two runs; absent data must stay unavailable.
        defines.append(
            f"u,{vwzio.circuit},RunStatsImmersionHeaterHwc,RunStatsImmersionHeaterHwc,f1,76,B511,1802"
            ",ign,,IGN:1,,,,runtime,,ULG,,min,,cycles,,ULG"
        )
        # Decode the captured backup-heater DHW heat total (B516 source 0x49, usage 04) without polling.
        # Strong assumption from the issue #161 capture (6487 Wh against 106 min of heater runtime);
        # the layout matches the Hwc counters, and the entity is disabled by default and unavailable when absent.
        defines.append(
            f"u,{vwzio.circuit},HeaterYieldHwcTotal,HeaterYieldHwcTotal,f1,76,B516,1000ffff49040000"
            ",ign,,IGN:7,,,,value,,EXP,,Wh,Backup heater DHW heat total (assumed)"
        )
        defines.extend(
            f"u,{vwzio.circuit},{name},{name},,76,{message_id},{subaddress},{fields}"
            for name, message_id, subaddress, fields in VWZIO_SW0500_ANY_MASTER_REGISTERS
        )
        # Status01's active field layout is documented for VWZIO HW5103, not this HW0504 scan.
        defines = [
            definition
            for definition in defines
            if not (definition.startswith(("r,vwz,Status01,", "r,vwzio,Status01,")))
        ]
    if not is_hmux0_0303_0504:
        # Only the active SW0303 read is gated here; the passive SW0407 decode is added by its own firmware gate.
        defines = [
            definition for definition in defines if not (definition.startswith("r,") and ",Status00," in definition)
        ]
    if not is_hmux0_b509_0504:
        # The SW0406 owner's own power read (issue #255) carries its own firmware gate and stays.
        sw0406_owner = (hmux0_sw0406_circuit or "").casefold()
        defines = [
            definition
            for definition in defines
            if not (
                (parts := definition.split(",", 3))[0] == "r"
                and parts[2] == "RunDataElPowerConsumption"
                and parts[1].casefold() != sw0406_owner
            )
        ]
    # Electrical power in watts on the HMU00 HW5103 firmwares where `B509 5402005b0d` was decoded (issue #259); ebusd's
    # HW5103 configuration lacks it. Added after the HMUX0 layout filters above, which only concern HMUX0 owners. The
    # gate is the scan identity, never whether `find` lists the name (it does after the first define).
    b509_power_owner = profile_owner(graph, HMU00_B509_POWER)
    if b509_power_owner is not None:
        defines.append(_hmux0_power_definition(b509_power_owner))
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
            ",displaypressure,,UCH,30,bar,"
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
