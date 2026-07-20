# myPyllant Replacement Matrix

Status values:

- `live`: local replacement exists and was observed on the heat pump.
- `mapped`: local register is known; UI/entity work remains.
- `derived`: local replacement needs aggregation or calculation.
- `investigate`: ebusd register exists but semantics or writes are unproven.
- `unavailable`: no equivalent local eBUS register is currently known.

Source inventory: Home Assistant `mypyllant` config entry
`01JAN0KJEKXKANS8C1F65AR1BB`, captured 2026-07-19. All cloud entities were
unavailable during capture; eBUS values below come from direct local reads.

## Live Local Replacement Entities

| Purpose | Home Assistant entity |
|---|---|
| Whole-home climate | `climate.vaillant_ctlv2_heating_control_heating` |
| Domestic hot water | `water_heater.vaillant_ctlv2_heating_control_domestic_hot_water` |
| Zone schedule | `calendar.vaillant_ctlv2_heating_control_zone_program` |
| Heating schedule | `calendar.vaillant_ctlv2_heating_control_heating_program` |
| DHW schedule | `calendar.vaillant_ctlv2_heating_control_domestic_hot_water_program` |
| Holiday start/end | `date.vaillant_ctlv2_heating_control_holiday_start`, `date.vaillant_ctlv2_heating_control_holiday_end` |
| Quick veto | `number.vaillant_ctlv2_heating_control_quick_veto_duration`, `number.vaillant_ctlv2_heating_control_quick_veto_temperature` |
| Local online state | `binary_sensor.vaillant_hmu_heat_pump_unit_online` |
| Local trouble codes | `binary_sensor.vaillant_hmu_heat_pump_unit_trouble_codes` |

## Implemented Local Entities

| Purpose | Home Assistant entity |
|---|---|
| Whole-home climate | `climate.vaillant_ctlv2_heating_control_heating` |
| Domestic hot water | `water_heater.vaillant_ctlv2_heating_control_domestic_hot_water` |
| Zone schedule | `calendar.vaillant_ctlv2_heating_control_zone_program` |
| Heating schedule | `calendar.vaillant_ctlv2_heating_control_heating_program` |
| DHW schedule | `calendar.vaillant_ctlv2_heating_control_domestic_hot_water_program` |
| Holiday start/end | `date.vaillant_ctlv2_heating_control_holiday_start`, `date.vaillant_ctlv2_heating_control_holiday_end` |
| Quick veto | `number.vaillant_ctlv2_heating_control_quick_veto_duration`, `number.vaillant_ctlv2_heating_control_quick_veto_temperature` |
| Local online state | `binary_sensor.vaillant_hmu_heat_pump_unit_online` |
| Local trouble codes | `binary_sensor.vaillant_hmu_heat_pump_unit_trouble_codes` |

## Zone Climate And Circuit

| myPyllant entity | Local eBUS replacement | Status | Notes |
|---|---|---|---|
| `climate.our_home_zone_thuis_circuit_0_climate` | `climate.vaillant_ctlv2_heating_control_heating` | live | Current room temperature, day/night target, and off/heat/auto mode. |
| `sensor.our_home_zone_thuis_circuit_0_current_temperature` | `ctlv2.Z1RoomTemp` | live | 22.5375 C direct read. |
| `sensor.our_home_zone_thuis_circuit_0_desired_temperature` | Z1 active day/night target | derived | Depends on `Z1OpMode`. |
| `sensor.our_home_zone_thuis_circuit_0_desired_heating_temperature` | `ctlv2.Z1DayTemp` | live | 20 C direct read. |
| `sensor.our_home_zone_thuis_circuit_0_desired_cooling_temperature` | `ctlv2.Z1CoolingTemp` | mapped | 20 C direct read. |
| `sensor.our_home_zone_thuis_circuit_0_heating_operating_mode` | `ctlv2.Z1OpMode` | live | `day` direct read. |
| `sensor.our_home_zone_thuis_circuit_0_heating_state` | `hmu.RunDataStatuscode`, `hmu.Status01` | live | Compressor state and heating/DHW state. |
| `sensor.our_home_zone_thuis_circuit_0_current_special_function` | `ctlv2.Z1SFMode` | mapped | `auto` direct read; semantics pending. |
| `sensor.our_home_zone_thuis_circuit_0_cooling_operating_mode` | `ctlv2.Hc1MinCoolingTempDesired`, `ctlv2.Hc1AutoOffMode` | investigate | Registers exist; no cooling state/command proven. |
| `sensor.our_home_zone_thuis_circuit_0_humidity` | none | unavailable | `MaxRoomHumidity` is a limit, not measured room humidity. |
| `number.our_home_zone_thuis_circuit_0_quick_veto_duration` | `ctlv2.Z1QuickVetoDuration` | live | Native Number; no-op write accepted. |
| `binary_sensor.our_home_zone_thuis_circuit_0_manual_cooling_active` | none | unavailable | No local active-cooling register identified. |
| `switch.our_home_zone_thuis_circuit_0_ventilation_boost` | none | unavailable | No ventilation actuator is exposed on current eBUS scan. |
| `calendar.our_home_zone_thuis_circuit_0` | `calendar.vaillant_ctlv2_heating_control_zone_program` | live | Read-only eBUS slots decode as start;end;temperature. |
| `calendar.our_home_zone_thuis_circuit_0_2` | `calendar.vaillant_ctlv2_heating_control_heating_program` | live | Read-only eBUS slots decode as start;end. |

## Domestic Hot Water

| myPyllant entity | Local eBUS replacement | Status | Notes |
|---|---|---|---|
| `water_heater.our_home_domestic_hot_water_0` | `water_heater.vaillant_ctlv2_heating_control_domestic_hot_water` | live | Storage temp, target and operation mode. |
| `sensor.our_home_domestic_hot_water_0_tank_temperature` | `ctlv2.HwcStorageTemp` | live | 33 C direct read during DHW cycle. |
| `sensor.our_home_domestic_hot_water_0_setpoint` | `ctlv2.HwcTempDesired` | live | 35 C direct read. |
| `sensor.our_home_domestic_hot_water_0_operation_mode` | `ctlv2.HwcOpMode` | live | `day` direct read. |
| `sensor.our_home_domestic_hot_water_0_current_special_function` | `ctlv2.HwcSFMode` | mapped | `auto` direct read; semantics pending. |
| `switch.our_home_domestic_hot_water_0_boost` | none | investigate | No one-shot boost register confirmed. |
| `calendar.our_home_domestic_hot_water_0` | `calendar.vaillant_ctlv2_heating_control_domestic_hot_water_program` | live | Read-only eBUS slots decode as start;end;temperature. |
| `calendar.circulating_water_in_our_home_domestic_hot_water_0` | none | unavailable | No circulation-pump schedule register identified. |
| `datetime.our_home_domestic_hot_water_0_legionella_protection_temperature_reached` | none | unavailable | No local legionella completion timestamp identified. |

## Heating Curve, Cooling And Overrides

| myPyllant entity | Local eBUS replacement | Status | Notes |
|---|---|---|---|
| `number.our_home_circuit_0_heating_curve` | `ctlv2.Hc1HeatCurve` | live | 0.35 direct read. |
| `number.our_home_circuit_0_min_flow_temperature_setpoint` | `ctlv2.Hc1MinFlowTempDesired` | live | 20 C direct read. |
| `number.our_home_circuit_0_heat_demand_limited_by_outside_temperature` | `ctlv2.Hc1SummerTempLimit` | live | 19 C direct read. |
| `sensor.our_home_circuit_0_current_flow_temperature` | `ctlv2.Hc1FlowTemp` | live | 48.5 C direct read. |
| `sensor.home_our_home_circuit_0_flow_temperature_setpoint` | `ctlv2.Hc1ActualFlowTempDesired` | mapped | Currently 0 sentinel; use only when valid. |
| `sensor.our_home_circuit_0_heating_curve` | `ctlv2.Hc1HeatCurve` | live | Same local source as number control. |
| `sensor.our_home_circuit_0_state` | `ctlv2.Hc1Status` | mapped | Numeric status needs value mapping. |
| `binary_sensor.our_home_circuit_0_cooling_allowed` | `ctlv2.Hc1MinCoolingTempDesired` | investigate | Threshold exists, permission semantics do not. |
| `switch.our_home_manual_cooling` | none | unavailable | No safe local cooling-enable command identified. |
| `number.our_home_manual_cooling_duration` | none | unavailable | Depends on manual cooling command. |
| `datetime.our_home_manual_cooling_start_date` | none | unavailable | Depends on manual cooling command. |
| `datetime.our_home_manual_cooling_end_date` | none | unavailable | Depends on manual cooling command. |
| `switch.our_home_away_mode` | `ctlv2.Z1HolidayStartPeriod`, `ctlv2.Z1HolidayEndPeriod`, `ctlv2.Z1HolidayTemp` | investigate | Date and temperature registers exist; write format/activation semantics unproven. |
| `datetime.our_home_away_mode_start_date` | `ctlv2.Z1HolidayStartPeriod` | investigate | Current value 01.01.2015. |
| `datetime.our_home_away_mode_end_date` | `ctlv2.Z1HolidayEndPeriod` | investigate | Current value 01.01.2015. |
| `number.our_home_holiday_duration_remaining` | holiday period delta | derived | Requires validated holiday semantics. |

## System, Status And Diagnostics

| myPyllant entity | Local eBUS replacement | Status | Notes |
|---|---|---|---|
| `sensor.our_home_outdoor_temperature` | `Broadcast.Outsidetemp` | live | Local outside temperature. |
| `sensor.our_home_system_water_pressure` | `ctlv2.WaterPressure` | live | 1.6 bar direct read. |
| `sensor.our_home_energy_manager_state` | `hmu.SetMode` | mapped | Multi-field state; decode needed. |
| `sensor.our_home_firmware_version` | scan slave versions | mapped | Versions available in scan response, no entity yet. |
| `sensor.our_home_heating_energy_efficiency` | `hmu.CopHc` | mapped | COP is unavailable outside heating cycles. |
| `binary_sensor.our_home_online_status` | ebusd TCP connection | derived | Coordinator availability is local equivalent. |
| `binary_sensor.our_home_trouble_codes` | `hmu.Currenterror`, `ctlv2.Currenterror` | mapped | Current errors are `-`; expose problem state. |
| `binary_sensor.our_home_eebus_capable` | none | unavailable | Cloud/VR921 capability, not heat-pump eBUS telemetry. |
| `binary_sensor.our_home_eebus_enabled` | none | unavailable | Cloud/VR921 configuration. |
| `switch.our_home_eebus` | none | unavailable | Cloud/VR921 configuration. |
| `binary_sensor.our_home_firmware_update_enabled` | none | unavailable | Cloud update policy. |
| `binary_sensor.our_home_firmware_update_required` | none | unavailable | Cloud update status. |
| `sensor.vaillant_api_request_count` | none | unavailable | Cloud API diagnostic. |

## Energy And Efficiency

Cloud device 0/device 1 hydraulic-station and aroTHERM counters overlap and are
not semantically stable in the unavailable cloud inventory. They cannot be
claimed as one-to-one until values are available for a full operating cycle.

| myPyllant entity family | Local eBUS candidate | Status |
|---|---|---|
| `*_consumed_electrical_energy_*` | `hmu.TotalEnergyUsage`, `hmu.PowerConsumptionHmu` | investigate |
| `*_earned_environment_energy_*` | none | unavailable |
| `*_heat_generated_heating` | `hmu.YieldHc`, `hmu.YieldHcDay`, `hmu.YieldHcMonth` | mapped |
| `*_heat_generated_domestic_hot_water` | `hmu.YieldHwc`, `hmu.YieldHwcDay`, `hmu.YieldHwcMonth` | mapped |
| `*_heat_generated_cooling` | `hmu.YieldCooling`, `hmu.YieldCoolDay`, `hmu.YieldCoolingMonth` | mapped |
| `*_heating_energy_efficiency` | `hmu.CopHc`, `hmu.CopHwc`, `hmu.CopCooling` | mapped |

## Direct Register Evidence

Captured 2026-07-19 while DHW compressor was active:

| Register | Value |
|---|---|
| `hmu.RunDataStatuscode` | `hwc_compressor_active` |
| `hmu.CurrentConsumedPower` | 1.8 |
| `hmu.CurrentYieldPower` | 6.0 |
| `hmu.YieldHwc` | 6454 |
| `ctlv2.HwcStorageTemp` | 33 |
| `ctlv2.HwcTempDesired` | 35 |
| `ctlv2.HwcOpMode` | `day` |
| `ctlv2.Z1RoomTemp` | 22.5375 |
| `ctlv2.Z1DayTemp` | 20 before direct read; no data later in active scan |
| `ctlv2.Z1NightTemp` | 19 |
| `ctlv2.Z1OpMode` | `day` |
| `ctlv2.Z1Timer_Monday0` | `06:00;22:00;19.5` |
| `ctlv2.HwcTimer_Monday0` | `13:30;15:00;35.0` |
| `ctlv2.CcTimer_Monday0` | `08:30;22:00` |

## Write Evidence

No-op local writes returned `done` for:

- `ctlv2.Z1DayTemp = 20`
- `ctlv2.Z1NightTemp = 19`
- `ctlv2.Z1OpMode = day`
- `ctlv2.HwcTempDesired = 35`
- `ctlv2.HwcOpMode = day`

Changed-value-and-restore round trips:

| Register | Test | Readback |
|---|---|---|
| `ctlv2.Z1DayTemp` | 20 -> 20.5 -> 20 | 20.5, then 20 |
| `ctlv2.HwcTempDesired` | 35 -> 36 -> 35 | 36, then 35 |

All values were restored. eBUS day/night mode no-op writes were also accepted.

## Additional Validation 2026-07-19

No-op writes returned `done` for `Z1QuickVetoDuration`, `Z1QuickVetoTemp`,
`Z1HolidayStartPeriod`, `Z1HolidayEndPeriod`, `Z1HolidayTemp`, `Z1SFMode`,
`HwcSFMode`, `Hc1AutoOffMode`, `Hc1MinCoolingTempDesired`, and
`Hc1SummerTempLimit`.

Timer slots decode correctly but `write -c ctlv2 CcTimer_Monday0 08:30;22:00`
returns `ERR: element not found`. Local calendars are intentionally read-only.

## Explicit Replacement Blockers

| myPyllant capability | Local eBUS result | Required evidence before replacement |
|---|---|---|
| Away mode switch | Holiday date and temperature controls exist; no boolean activation semantics found. | State-changing holiday activation and restore test. |
| DHW boost | `HwcSFMode=auto`; no boost action/register found. | Capture a cloud/UI boost and inspect resulting eBUS messages. |
| Manual cooling and duration | Cooling setpoint/threshold registers exist; no enable action found. | Capture manual cooling and inspect resulting eBUS messages. |
| Timer editing | Readable schedule slots; direct write rejected. | Identify a supported writeable ebusd command/configuration. |
| Ventilation boost | No ventilation actuator/slave in current eBUS scan. | Additional hardware exposing a local actuator. |
| EEBUS and firmware controls | Cloud/VR921 configuration, not heat-pump eBUS data. | Retain cloud or accept removal. |
| Cloud API request count | Cloud diagnostic only. | Retain cloud or accept removal. |
| Room humidity | No room-humidity sensor on current eBUS scan. | External room humidity sensor. |
| Environment-energy counters | No like-for-like local counter. | Define accepted derived calculation or retain cloud. |

## Runtime Incident 2026-07-19

Adding every schedule slot to sequential `read` polling made one coordinator
cycle exceed the update interval. After restart, the coordinator had no complete
data payload and all eBUS entities showed `unknown`.

Fix: coordinator refresh now uses one ebusd `find` bulk response per interval,
then rebuilds the value map from that response. This covers schedules and
controls without serial per-register read latency.

Verified after deployment:

| Entity | Restored state |
|---|---|
| Outside temperature | 20.0 C |
| DHW storage temperature | 41.0 C |
| HMU flow temperature | 49.25 C |
| Home climate current temperature | 22.7 C |
| DHW water heater | `day`, current 41.0 C |

## Entity Continuity Fix 2026-07-19

Known mapped registers were previously excluded when they reported `no data
stored` during Home Assistant startup. HA then marked their existing entity
registry records as no longer provided, even though the same registers become
live during a compressor/DHW cycle.

Discovery now always provides every register present in `REGISTER_MAP`; unknown
empty registers remain hidden. Confirmed restored HMU values:

| Entity | Device | State |
|---|---|---|
| Compressor Speed | HMU | 78.3967 rpm |
| Air Inlet Temperature | HMU | 19.2308 C |
| Flow Temperature | HMU | 49.25 C |
| Flow Temperature (HC1) | CTLV2 | 54.5 C |
| DHW Storage Temperature | CTLV2 | 42.5 C |

Removed 15 legacy `sensor.*` controls that duplicated active `number.*` or
`select.*` controls with identical unique IDs. No live measurement entities
were removed.

## Dashboard Migration 2026-07-19

The default Lovelace dashboard now uses local eBUS entities for all proven
myPyllant measurements:

| Card | Replaced cloud entity | Local entity | Verified state |
|---|---|---|---|
| Living room | `sensor.our_home_zone_thuis_circuit_0_current_temperature` | `sensor.vaillant_ebus_ebusd_ctlv2_z1roomtemp` | 22.6625 C |
| Water | `sensor.our_home_circuit_0_current_flow_temperature` | `sensor.vaillant_ebus_ebusd_flow_temperature_hc1` | 57.0 C |
| Outside Temperature | `sensor.our_home_outdoor_temperature` | `sensor.vaillant_ebus_ebusd_outside_temperature` | 20.297 C |

The remaining cloud dashboard cards are humidity and away mode. Current eBUS
hardware exposes neither a room-humidity measurement nor proven holiday-mode
activation semantics, so those cards are intentionally unchanged.

Three automation conditions now use
`sensor.vaillant_ebus_ebusd_outside_temperature`; no cloud outdoor-temperature
references remain. Three away-mode conditions remain cloud-backed pending task
17.1.6.
