"""Default mapping metadata for all ebusd registers."""

from __future__ import annotations

from datetime import datetime

from .models import RegisterMeta

# Multi-field registers: register key -> field names in semicolon order of the
# raw ebusd value. Field names follow the ebusd CSV definitions.
# Source: ebusd vaillant CSV (08.hmu.csv) + community dumps.
MULTI_FIELD_FIELDS: dict[str, list[str]] = {
    "hmu.Status01": ["temp", "temp_1", "temp_2", "temp_3", "temp_4", "pumpstate"],
    "hmu.CompressorHc": ["runtime", "cycles"],
    "hmu.CompressorHwc": ["runtime", "cycles"],
    "hmu.RunStatsCompressorHc": ["runtime", "cycles"],
    "hmu.RunStatsCompressorHwc": ["runtime", "cycles"],
    # v32 gas boiler (ecoTEC plus via VR32, bai.308523.inc + hcmode.inc).
    # Status01/Status02 share the hmu Status01 layout (hcmode.inc B511).
    # Single-field sensor registers expose only the first field; the trailing
    # fields are tempmirror/status values (see _templates.tsp models).
    "v32.Status01": ["temp", "temp_1", "temp_2", "temp_3", "temp_4", "pumpstate"],
    "v32.Status02": ["hwcmode", "temp0", "temp1", "temp0_1", "temp1_1"],
    "v32.FlowTemp": ["value"],
    "v32.ReturnTemp": ["value"],
    "v32.StorageTemp": ["value"],
    "v32.WaterPressure": ["value"],
    "v32.HwcTemp": ["value"],
    "v32.OutdoorstempSensor": ["value"],
}


def multi_field_fields(register_key: str) -> list[str] | None:
    """Return the field names for a multi-field register, or None."""
    return MULTI_FIELD_FIELDS.get(register_key)


def split_multi_field(register_key: str, raw: str | None) -> dict[str, str | None]:
    """Split a raw register value into named fields; keep the raw value under "value"."""
    fields = MULTI_FIELD_FIELDS.get(register_key)
    values: dict[str, str | None] = {"value": raw}
    if not fields or raw is None:
        return values
    parts = raw.split(";")
    values.update(
        {field: parts[i] if i < len(parts) else None for i, field in enumerate(fields)}
    )
    return values


REGISTER_MAP: dict[str, RegisterMeta] = {
    # hmu (Heat Pump)
    "hmu.Status01": RegisterMeta(
        friendly_name="Status",
        icon="mdi:information",
        entity_category="diagnostic",
    ),
    "hmu.Status01.temp": RegisterMeta(
        friendly_name="Flow Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.Status01.temp_1": RegisterMeta(
        friendly_name="Return Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.Status01.temp_2": RegisterMeta(
        friendly_name="Outside Temperature",
        device_class="temperature",
        unit="°C",
        enabled=False,
    ),
    "hmu.Status01.temp_3": RegisterMeta(
        friendly_name="Hot Water Temperature",
        device_class="temperature",
        unit="°C",
        enabled=False,
    ),
    "hmu.Status01.temp_4": RegisterMeta(
        friendly_name="Storage Temperature",
        device_class="temperature",
        unit="°C",
        enabled=False,
    ),
    "hmu.Status01.pumpstate": RegisterMeta(
        friendly_name="Pump State",
        entity_type="binary_sensor",
        entity_category="diagnostic",
    ),
    "hmu.StatusCirPump": RegisterMeta(
        friendly_name="Circulation Pump",
        entity_type="binary_sensor",
        entity_category="diagnostic",
    ),
    "hmu.Currenterror": RegisterMeta(
        friendly_name="Error",
        icon="mdi:alert",
        entity_category="diagnostic",
    ),
    "hmu.FlowTemp": RegisterMeta(
        friendly_name="Flow Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.FlowTemperature": RegisterMeta(
        friendly_name="Flow Temperature (alt)",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.RunDataCompressorSpeed": RegisterMeta(
        friendly_name="Compressor Speed",
        icon="mdi:speedometer",
        unit="rpm",
    ),
    "hmu.RunDataHighPressure": RegisterMeta(
        friendly_name="High Pressure",
        device_class="pressure",
        unit="bar",
    ),
    "hmu.RunDataLowPressure": RegisterMeta(
        friendly_name="Low Pressure",
        device_class="pressure",
        unit="bar",
        enabled=False,
    ),
    "hmu.RunDataCompressorInletTemp": RegisterMeta(
        friendly_name="Compressor Inlet Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.RunDataCompressorOutletTemp": RegisterMeta(
        friendly_name="Compressor Outlet Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.RunDataEEVOutletTemp": RegisterMeta(
        friendly_name="EEV Outlet Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.RunDataEEVPositionAbs": RegisterMeta(
        friendly_name="EEV Position",
        icon="mdi:valve",
        unit="%",
    ),
    "hmu.RunDataFan1Speed": RegisterMeta(
        friendly_name="Fan 1 Speed",
        icon="mdi:fan",
        unit="rpm",
    ),
    "hmu.RunDataFan2Speed": RegisterMeta(
        friendly_name="Fan 2 Speed",
        icon="mdi:fan",
        unit="rpm",
    ),
    "hmu.RunDataStatuscode": RegisterMeta(
        friendly_name="Compressor Status",
        icon="mdi:information",
    ),
    "hmu.RunDataAirInletTemp": RegisterMeta(
        friendly_name="Air Inlet Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.RunDataReturnTemp": RegisterMeta(
        friendly_name="Return Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.RunDataBuildingCPumpPower": RegisterMeta(
        friendly_name="Building Circulation Pump Speed",
        unit="%",
    ),
    "hmu.BuildingCircuitPumpSpeed": RegisterMeta(
        friendly_name="Building Circuit Pump Speed",
        unit="%",
    ),
    "hmu.CurrentConsumedPower": RegisterMeta(
        friendly_name="Compressor Power",
        device_class="power",
        unit="kW",
    ),
    "hmu.CurrentYieldPower": RegisterMeta(
        friendly_name="Thermal Output",
        device_class="power",
        unit="kW",
    ),
    "hmu.CurrentCompressorUtil": RegisterMeta(
        friendly_name="Compressor Utilisation",
        icon="mdi:percent",
        unit="%",
    ),
    "hmu.SupplyTempWeighted": RegisterMeta(
        friendly_name="Supply Temperature (weighted)",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.SourceTempInput": RegisterMeta(
        friendly_name="Source Temp Input",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.SourceTempOutput": RegisterMeta(
        friendly_name="Source Temp Output",
        device_class="temperature",
        unit="°C",
    ),
    "hmu.TotalEnergyUsage": RegisterMeta(
        friendly_name="Total Energy",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.CopHc": RegisterMeta(
        friendly_name="COP Heating",
        icon="mdi:lightning-bolt",
        state_class="measurement",
    ),
    "hmu.CopHcMonth": RegisterMeta(
        friendly_name="COP Heating Month",
        icon="mdi:lightning-bolt",
        state_class="measurement",
    ),
    "hmu.CopHwc": RegisterMeta(
        friendly_name="COP DHW",
        icon="mdi:lightning-bolt",
        state_class="measurement",
    ),
    "hmu.CopHwcMonth": RegisterMeta(
        friendly_name="COP DHW Month",
        icon="mdi:lightning-bolt",
        state_class="measurement",
    ),
    "hmu.CopCooling": RegisterMeta(
        friendly_name="COP Cooling",
        icon="mdi:lightning-bolt",
        state_class="measurement",
    ),
    "hmu.CopCoolingMonth": RegisterMeta(
        friendly_name="COP Cooling Month",
        icon="mdi:lightning-bolt",
        state_class="measurement",
    ),
    "hmu.YieldHc": RegisterMeta(
        friendly_name="Yield Heating",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.YieldHcDay": RegisterMeta(
        friendly_name="Yield Heating Today",
        device_class="energy",
        unit="kWh",
    ),
    "hmu.YieldHcMonth": RegisterMeta(
        friendly_name="Yield Heating Month",
        device_class="energy",
        unit="kWh",
    ),
    "hmu.YieldHwc": RegisterMeta(
        friendly_name="Yield DHW",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.YieldHwcDay": RegisterMeta(
        friendly_name="Yield DHW Today",
        device_class="energy",
        unit="kWh",
    ),
    "hmu.YieldHwcMonth": RegisterMeta(
        friendly_name="Yield DHW Month",
        device_class="energy",
        unit="kWh",
    ),
    "hmu.YieldCoolDay": RegisterMeta(
        friendly_name="Yield Cooling Today",
        device_class="energy",
        unit="kWh",
    ),
    # Runtime-defined b516 cooling-energy registers (issue #50). The bus
    # reports Wh; the unit stays Wh because ebusd returns the raw EXP value.
    "hmu.CoolEnvYieldTotal": RegisterMeta(
        friendly_name="Cooling Energy Total",
        device_class="energy",
        unit="Wh",
        state_class="total_increasing",
        icon="mdi:snowflake",
    ),
    "hmu.CoolEnvYieldDay": RegisterMeta(
        friendly_name="Cooling Energy Today",
        device_class="energy",
        unit="Wh",
        icon="mdi:snowflake",
    ),
    "hmu.CoolEnvYieldMonth": RegisterMeta(
        friendly_name="Cooling Energy Month",
        device_class="energy",
        unit="Wh",
        icon="mdi:snowflake",
    ),
    "hmu.CoolElecConsTotal": RegisterMeta(
        friendly_name="Cooling Electricity Total",
        device_class="energy",
        unit="Wh",
        state_class="total_increasing",
        icon="mdi:snowflake",
    ),
    "hmu.CoolElecConsDay": RegisterMeta(
        friendly_name="Cooling Electricity Today",
        device_class="energy",
        unit="Wh",
        icon="mdi:snowflake",
    ),
    "hmu.HcElecConsTotal": RegisterMeta(
        friendly_name="Heating Electricity Total",
        device_class="energy",
        unit="Wh",
        state_class="total_increasing",
        icon="mdi:radiator",
    ),
    "hmu.HcElecConsDay": RegisterMeta(
        friendly_name="Heating Electricity Today",
        device_class="energy",
        unit="Wh",
        icon="mdi:radiator",
    ),
    "hmu.HwcElecConsTotal": RegisterMeta(
        friendly_name="DHW Electricity Total",
        device_class="energy",
        unit="Wh",
        state_class="total_increasing",
        icon="mdi:water-boiler",
    ),
    "hmu.HwcElecConsDay": RegisterMeta(
        friendly_name="DHW Electricity Today",
        device_class="energy",
        unit="Wh",
        icon="mdi:water-boiler",
    ),
    # CSV/find-based electric registers that supplement the runtime-defined
    # b516 counters above (issue #50). Units follow the upstream 08.hmu.tsp
    # definitions: energy is UIN kWh, RunDataElectricPowerConsumption is EXP W,
    # LiveMonitorCurrentConsumedPower is UIN kW with a divisor of 10, and the
    # StatSolar* sums are EXP kWh. All are opt-in: entities only appear when
    # the discovery graph carries them with data.
    "hmu.ConsumptionTotal": RegisterMeta(
        friendly_name="Electrical Energy Consumption",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.RunDataElectricPowerConsumption": RegisterMeta(
        friendly_name="Electric Power Consumption",
        device_class="power",
        unit="W",
    ),
    "hmu.LiveMonitorCurrentConsumedPower": RegisterMeta(
        friendly_name="Live Power Consumption",
        device_class="power",
        unit="kW",
    ),
    "hmu.StatSolarEnergySum": RegisterMeta(
        friendly_name="Solar Energy Sum",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.StatSolarEnergySumHc": RegisterMeta(
        friendly_name="Solar Energy Sum (Heating)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.StatSolarEnergySumHwc": RegisterMeta(
        friendly_name="Solar Energy Sum (DHW)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.YieldCooling": RegisterMeta(
        friendly_name="Yield Cooling",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.YieldCoolingMonth": RegisterMeta(
        friendly_name="Yield Cooling Month",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.HoursCool": RegisterMeta(
        friendly_name="Cooling Runtime",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
        entity_category="diagnostic",
    ),
    "hmu.StatElectricEnergySumCool": RegisterMeta(
        friendly_name="Electric Energy Cooling",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.StatEnvironmentEnergySumCool": RegisterMeta(
        friendly_name="Environment Energy Cooling",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.StatElectricEnergySum": RegisterMeta(
        friendly_name="Electric Energy",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.StatElectricEnergySumHc": RegisterMeta(
        friendly_name="Electric Energy (Heating)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.StatElectricEnergySumHwc": RegisterMeta(
        friendly_name="Electric Energy (DHW)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.StatEnvironmentEnergySum": RegisterMeta(
        friendly_name="Environment Energy",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.StatEnvironmentEnergySumHc": RegisterMeta(
        friendly_name="Environment Energy (Heating)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.StatEnvironmentEnergySumHwc": RegisterMeta(
        friendly_name="Environment Energy (DHW)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "hmu.RunStatsCompressorHours": RegisterMeta(
        friendly_name="Compressor Runtime",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsCompressorStarts": RegisterMeta(
        friendly_name="Compressor Starts",
        icon="mdi:counter",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsFan1Hours": RegisterMeta(
        friendly_name="Fan 1 Runtime",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsFan2Hours": RegisterMeta(
        friendly_name="Fan 2 Runtime",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsBuildingCPumpStarts": RegisterMeta(
        friendly_name="Building Pump Starts",
        icon="mdi:counter",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsBuildingPumpHours": RegisterMeta(
        friendly_name="Building Pump Runtime",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.CompressorHc": RegisterMeta(
        friendly_name="Compressor HC",
        icon="mdi:information",
        entity_category="diagnostic",
        enabled=False,
    ),
    "hmu.CompressorHc.runtime": RegisterMeta(
        friendly_name="Compressor Runtime (HC)",
        device_class="duration",
        unit="min",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.CompressorHc.cycles": RegisterMeta(
        friendly_name="Compressor Starts (HC)",
        icon="mdi:counter",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.CompressorHwc": RegisterMeta(
        friendly_name="Compressor DHW",
        icon="mdi:information",
        entity_category="diagnostic",
        enabled=False,
    ),
    "hmu.CompressorHwc.runtime": RegisterMeta(
        friendly_name="Compressor Runtime (DHW)",
        device_class="duration",
        unit="min",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.CompressorHwc.cycles": RegisterMeta(
        friendly_name="Compressor Starts (DHW)",
        icon="mdi:counter",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsCompressorHc": RegisterMeta(
        friendly_name="Compressor HC Stats",
        icon="mdi:information",
        entity_category="diagnostic",
        enabled=False,
    ),
    "hmu.RunStatsCompressorHc.runtime": RegisterMeta(
        friendly_name="Compressor Runtime (HC)",
        device_class="duration",
        unit="min",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsCompressorHc.cycles": RegisterMeta(
        friendly_name="Compressor Starts (HC)",
        icon="mdi:counter",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsCompressorHwc": RegisterMeta(
        friendly_name="Compressor DHW Stats",
        icon="mdi:information",
        entity_category="diagnostic",
        enabled=False,
    ),
    "hmu.RunStatsCompressorHwc.runtime": RegisterMeta(
        friendly_name="Compressor Runtime (DHW)",
        device_class="duration",
        unit="min",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsCompressorHwc.cycles": RegisterMeta(
        friendly_name="Compressor Starts (DHW)",
        icon="mdi:counter",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsFan1Starts": RegisterMeta(
        friendly_name="Fan 1 Starts",
        icon="mdi:counter",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsFan2Starts": RegisterMeta(
        friendly_name="Fan 2 Starts",
        icon="mdi:counter",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsHcHours": RegisterMeta(
        friendly_name="Heating Runtime",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsHMUHours": RegisterMeta(
        friendly_name="HMU Runtime",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStatsHwcHours": RegisterMeta(
        friendly_name="DHW Runtime",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStats4PortValveHours": RegisterMeta(
        friendly_name="4-Port Valve Runtime",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.RunStats4PortValveSwitches": RegisterMeta(
        friendly_name="4-Port Valve Switches",
        icon="mdi:counter",
        state_class="total_increasing",
        entity_category="diagnostic",
        entity_type="sensor",
    ),
    "hmu.PowerConsumptionHmu": RegisterMeta(
        friendly_name="Power Consumption (HMU)",
        device_class="power",
        unit="kW",
        state_class="measurement",
        enabled=False,
    ),
    "hmu.BuildingCircuitFlow": RegisterMeta(
        friendly_name="Building Circuit Flow",
        icon="mdi:water",
        unit="l/h",
        entity_type="sensor",
    ),
    "hmu.DateTime": RegisterMeta(
        friendly_name="Date/Time",
        icon="mdi:clock",
        entity_category="diagnostic",
    ),
    # ctlv2 (Heating Control)
    "ctlv2.Hc1ActualFlowTempDesired": RegisterMeta(
        friendly_name="Flow Temperature Target (HC1)",
        device_class="temperature",
        unit="°C",
        writable=False,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc1PumpStatus": RegisterMeta(
        friendly_name="Pump Status (HC1)",
        entity_type="binary_sensor",
    ),
    # Runtime-defined B524 heating-circuit state registers (Helianthus B524
    # register map, community capture via discussion #60). Absent from the
    # shipped CSVs; wire types EXP (f32) / ULG (u32) and message layout
    # verified against ebusd datatype.cpp and the compiled eBUS CSVs.
    "ctlv2.Hc1FlowTempCalc": RegisterMeta(
        friendly_name="Calculated Flow Temperature (HC1)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Hc1MixerPosition": RegisterMeta(
        friendly_name="Mixer Position (HC1)",
        unit="%",
        icon="mdi:valve",
    ),
    "ctlv2.Hc1Humidity": RegisterMeta(
        friendly_name="Humidity (HC1)",
        device_class="humidity",
        unit="%",
        icon="mdi:water-percent",
    ),
    "ctlv2.Hc1DewPointTemp": RegisterMeta(
        friendly_name="Dew Point Temperature (HC1)",
        device_class="temperature",
        unit="°C",
        icon="mdi:thermometer-water",
    ),
    "ctlv2.Hc1PumpHours": RegisterMeta(
        friendly_name="Pump Hours (HC1)",
        unit="h",
        state_class="total_increasing",
        icon="mdi:clock-outline",
        entity_category="diagnostic",
    ),
    "ctlv2.Hc1PumpStarts": RegisterMeta(
        friendly_name="Pump Starts (HC1)",
        state_class="total_increasing",
        icon="mdi:counter",
        entity_category="diagnostic",
    ),
    "ctlv2.Hc2FlowTempCalc": RegisterMeta(
        friendly_name="Calculated Flow Temperature (HC2)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Hc2MixerPosition": RegisterMeta(
        friendly_name="Mixer Position (HC2)",
        unit="%",
        icon="mdi:valve",
    ),
    "ctlv2.Hc2Humidity": RegisterMeta(
        friendly_name="Humidity (HC2)",
        device_class="humidity",
        unit="%",
        icon="mdi:water-percent",
    ),
    "ctlv2.Hc2DewPointTemp": RegisterMeta(
        friendly_name="Dew Point Temperature (HC2)",
        device_class="temperature",
        unit="°C",
        icon="mdi:thermometer-water",
    ),
    "ctlv2.Hc2PumpHours": RegisterMeta(
        friendly_name="Pump Hours (HC2)",
        unit="h",
        state_class="total_increasing",
        icon="mdi:clock-outline",
        entity_category="diagnostic",
    ),
    "ctlv2.Hc2PumpStarts": RegisterMeta(
        friendly_name="Pump Starts (HC2)",
        state_class="total_increasing",
        icon="mdi:counter",
        entity_category="diagnostic",
    ),
    "ctlv2.Z1ActualRoomTempDesired": RegisterMeta(
        friendly_name="Room Temperature Target (Z1)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=30,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Z1DayTemp": RegisterMeta(
        friendly_name="Day Temperature (Z1)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=30,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Z1NightTemp": RegisterMeta(
        friendly_name="Night Temperature (Z1)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=30,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Z1OpMode": RegisterMeta(
        friendly_name="Operation Mode (Z1)",
        writable=True,
        options=["day", "night", "auto", "off"],
        entity_type="select",
        entity_category="config",
    ),
    "ctlv2.Hc1FlowTemp": RegisterMeta(
        friendly_name="Flow Temperature (HC1)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Hc1HeatCurve": RegisterMeta(
        friendly_name="Heat Curve (HC1)",
        writable=True,
        min_value=0.1,
        max_value=4.0,
        step=0.05,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc1MaxFlowTempDesired": RegisterMeta(
        friendly_name="Max Flow Temperature (HC1)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=20,
        max_value=75,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc1MinFlowTempDesired": RegisterMeta(
        friendly_name="Min Flow Temperature (HC1)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=40,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc1SummerTempLimit": RegisterMeta(
        friendly_name="Summer Temp Limit (HC1)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=10,
        max_value=30,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc1MinCoolingTempDesired": RegisterMeta(
        friendly_name="Min Cooling Temp (HC1)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=30,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc1CoolingEnabled": RegisterMeta(
        friendly_name="Cooling Enabled (HC1)",
        icon="mdi:snowflake",
        writable=True,
        options=["off", "on"],
        entity_type="select",
        entity_category="config",
    ),
    "ctlv2.Hc1CoolingFlowTempMin": RegisterMeta(
        friendly_name="Min Flow Temp Cooling (HC1)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=30,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc1DewPointMonitoring": RegisterMeta(
        friendly_name="Dew Point Monitoring (HC1)",
        icon="mdi:water-percent",
        writable=True,
        options=["off", "on"],
        entity_type="select",
        entity_category="config",
    ),
    "ctlv2.Hc1DewPointOffset": RegisterMeta(
        friendly_name="Dew Point Offset (HC1)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=0,
        max_value=10,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc1RoomTempModulation": RegisterMeta(
        friendly_name="Room Temp Modulation (HC1)",
        icon="mdi:thermostat",
        entity_category="diagnostic",
    ),
    "ctlv2.Hc1AutoOffMode": RegisterMeta(
        friendly_name="Auto Off Mode (HC1)",
        icon="mdi:thermostat-auto",
        writable=True,
        options=["eco", "comfort"],
        entity_type="select",
        entity_category="config",
    ),
    "ctlv2.Hc1RoomTempSwitchOn": RegisterMeta(
        friendly_name="Room Temp Threshold (HC1)",
        unit="°C",
    ),
    "ctlv2.Hc1Status": RegisterMeta(
        friendly_name="Status (HC1)",
        entity_type="sensor",
        icon="mdi:information",
    ),
    "ctlv2.Hc1CircuitType": RegisterMeta(
        friendly_name="Circuit Type (HC1)",
        icon="mdi:information",
        entity_category="diagnostic",
    ),
    "ctlv2.Hc1ExcessTemp": RegisterMeta(
        friendly_name="Excess Temp (HC1)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Hc1HeatCurveAdaption": RegisterMeta(
        friendly_name="Heat Curve Adaption (HC1)",
        icon="mdi:chart-bell-curve-cumulative",
    ),
    "ctlv2.Hc1MixerMovement": RegisterMeta(
        friendly_name="Mixer Movement (HC1)",
        icon="mdi:valve",
    ),
    # HC2
    "ctlv2.Hc2ActualFlowTempDesired": RegisterMeta(
        friendly_name="Flow Temperature Target (HC2)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=75,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc2FlowTemp": RegisterMeta(
        friendly_name="Flow Temperature (HC2)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Hc2HeatCurve": RegisterMeta(
        friendly_name="Heat Curve (HC2)",
        writable=True,
        min_value=0.1,
        max_value=4.0,
        step=0.05,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc2MaxFlowTempDesired": RegisterMeta(
        friendly_name="Max Flow Temperature (HC2)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=20,
        max_value=75,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc2MinFlowTempDesired": RegisterMeta(
        friendly_name="Min Flow Temperature (HC2)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=40,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc2SummerTempLimit": RegisterMeta(
        friendly_name="Summer Temp Limit (HC2)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=10,
        max_value=30,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc2MinCoolingTempDesired": RegisterMeta(
        friendly_name="Min Cooling Temp (HC2)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=30,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc2AutoOffMode": RegisterMeta(
        friendly_name="Auto Off Mode (HC2)",
        icon="mdi:thermostat-auto",
        writable=True,
        options=["eco", "comfort"],
        entity_type="select",
        entity_category="config",
    ),
    "ctlv2.Hc2PumpStatus": RegisterMeta(
        friendly_name="Pump Status (HC2)",
        entity_type="binary_sensor",
    ),
    "ctlv2.Hc2Status": RegisterMeta(
        friendly_name="Status (HC2)",
        entity_type="sensor",
        icon="mdi:information",
    ),
    "ctlv2.Hc2CircuitType": RegisterMeta(
        friendly_name="Circuit Type (HC2)",
        icon="mdi:information",
        entity_category="diagnostic",
    ),
    "ctlv2.Hc2ExcessTemp": RegisterMeta(
        friendly_name="Excess Temp (HC2)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Hc2HeatCurveAdaption": RegisterMeta(
        friendly_name="Heat Curve Adaption (HC2)",
        icon="mdi:chart-bell-curve-cumulative",
    ),
    "ctlv2.Hc2RoomTempSwitchOn": RegisterMeta(
        friendly_name="Room Temp Threshold (HC2)",
        unit="°C",
    ),
    "ctlv2.Hc2MixerMovement": RegisterMeta(
        friendly_name="Mixer Movement (HC2)",
        icon="mdi:valve",
    ),
    # HC3
    "ctlv2.Hc3ActualFlowTempDesired": RegisterMeta(
        friendly_name="Flow Temperature Target (HC3)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=75,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc3FlowTemp": RegisterMeta(
        friendly_name="Flow Temperature (HC3)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Hc3HeatCurve": RegisterMeta(
        friendly_name="Heat Curve (HC3)",
        writable=True,
        min_value=0.1,
        max_value=4.0,
        step=0.05,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc3MaxFlowTempDesired": RegisterMeta(
        friendly_name="Max Flow Temperature (HC3)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=20,
        max_value=75,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc3MinFlowTempDesired": RegisterMeta(
        friendly_name="Min Flow Temperature (HC3)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=40,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc3SummerTempLimit": RegisterMeta(
        friendly_name="Summer Temp Limit (HC3)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=10,
        max_value=30,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc3MinCoolingTempDesired": RegisterMeta(
        friendly_name="Min Cooling Temp (HC3)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=30,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Hc3AutoOffMode": RegisterMeta(
        friendly_name="Auto Off Mode (HC3)",
        icon="mdi:thermostat-auto",
        writable=True,
        options=["eco", "comfort"],
        entity_type="select",
        entity_category="config",
    ),
    "ctlv2.Hc3PumpStatus": RegisterMeta(
        friendly_name="Pump Status (HC3)",
        entity_type="binary_sensor",
    ),
    "ctlv2.Hc3Status": RegisterMeta(
        friendly_name="Status (HC3)",
        entity_type="sensor",
        icon="mdi:information",
    ),
    "ctlv2.Hc3CircuitType": RegisterMeta(
        friendly_name="Circuit Type (HC3)",
        icon="mdi:information",
        entity_category="diagnostic",
    ),
    "ctlv2.Hc3ExcessTemp": RegisterMeta(
        friendly_name="Excess Temp (HC3)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Hc3HeatCurveAdaption": RegisterMeta(
        friendly_name="Heat Curve Adaption (HC3)",
        icon="mdi:chart-bell-curve-cumulative",
    ),
    "ctlv2.Hc3RoomTempSwitchOn": RegisterMeta(
        friendly_name="Room Temp Threshold (HC3)",
        unit="°C",
    ),
    "ctlv2.Hc3MixerMovement": RegisterMeta(
        friendly_name="Mixer Movement (HC3)",
        icon="mdi:valve",
    ),
    # DHW
    "ctlv2.HwcTempDesired": RegisterMeta(
        friendly_name="DHW Target Temperature",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=35,
        max_value=70,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.HwcStorageTemp": RegisterMeta(
        friendly_name="DHW Storage Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.HwcOpMode": RegisterMeta(
        friendly_name="DHW Operation Mode",
        writable=True,
        options=["off", "day", "night", "auto"],
        entity_type="select",
        entity_category="config",
    ),
    "ctlv2.HwcMaxFlowTempDesired": RegisterMeta(
        friendly_name="Max Flow Temperature (DHW)",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=20,
        max_value=75,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.HwcFlowTemp": RegisterMeta(
        friendly_name="DHW Flow Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.HwcLockTime": RegisterMeta(
        friendly_name="DHW Lock Time",
        icon="mdi:clock-outline",
        unit="min",
        entity_category="config",
    ),
    "ctlv2.CylinderChargeHyst": RegisterMeta(
        friendly_name="Cylinder Charge Hysteresis",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=1,
        max_value=20,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.CylinderChargeOffset": RegisterMeta(
        friendly_name="Cylinder Charge Offset",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=1,
        max_value=20,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.HwcParallelLoading": RegisterMeta(
        friendly_name="DHW Parallel Loading",
        entity_type="binary_sensor",
        icon="mdi:water-boiler",
    ),
    "ctlv2.HwcSfMode": RegisterMeta(
        friendly_name="DHW SF Mode",
        icon="mdi:information",
    ),
    "ctlv2.HwcStorageTempBottom": RegisterMeta(
        friendly_name="DHW Storage Temp (Bottom)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.HwcStorageTempTop": RegisterMeta(
        friendly_name="DHW Storage Temp (Top)",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.HwcHolidayStartPeriod": RegisterMeta(
        friendly_name="DHW Holiday Start",
        icon="mdi:calendar-start",
    ),
    "ctlv2.HwcHolidayEndPeriod": RegisterMeta(
        friendly_name="DHW Holiday End",
        icon="mdi:calendar-end",
    ),
    "ctlv2.HwcSFMode": RegisterMeta(
        friendly_name="DHW Special Function",
        icon="mdi:water-boiler",
    ),
    # Zones
    "ctlv2.DisplayedOutsideTemp": RegisterMeta(
        friendly_name="Displayed Outside Temp",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.OutsideTemp": RegisterMeta(
        friendly_name="Outside Temperature",
        device_class="temperature",
        unit="°C",
        state_class="measurement",
    ),
    "ctlv2.SystemFlowTemp": RegisterMeta(
        friendly_name="System Flow Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.WaterPressure": RegisterMeta(
        friendly_name="Water Pressure",
        device_class="pressure",
        unit="bar",
    ),
    "ctlv2.Currenterror": RegisterMeta(
        friendly_name="Error",
        icon="mdi:alert",
        entity_category="diagnostic",
    ),
    "ctlv2.PrEnergySum": RegisterMeta(
        friendly_name="Electrical Energy Consumption",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
        entity_type="sensor",
    ),
    "ctlv2.PrEnergySumHc": RegisterMeta(
        friendly_name="Electrical Energy Consumption (Heating)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
        entity_type="sensor",
    ),
    "ctlv2.PrEnergySumHwc": RegisterMeta(
        friendly_name="Electrical Energy Consumption (DHW)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
        entity_type="sensor",
    ),
    "ctlv2.PrEnergySumHcThisMonth": RegisterMeta(
        friendly_name="Electrical Energy Consumption Heating (This Month)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
        entity_type="sensor",
    ),
    "ctlv2.PrEnergySumHcLastMonth": RegisterMeta(
        friendly_name="Electrical Energy Consumption Heating (Last Month)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
        entity_type="sensor",
    ),
    "ctlv2.PrEnergySumHwcThisMonth": RegisterMeta(
        friendly_name="Electrical Energy Consumption DHW (This Month)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
        entity_type="sensor",
    ),
    "ctlv2.PrEnergySumHwcLastMonth": RegisterMeta(
        friendly_name="Electrical Energy Consumption DHW (Last Month)",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
        entity_type="sensor",
    ),
    "ctlv2.AdaptHeatCurve": RegisterMeta(
        friendly_name="Adapt Heat Curve",
        writable=True,
        options=["no", "yes"],
        entity_type="select",
        entity_category="config",
    ),
    "ctlv2.ContinuousHeating": RegisterMeta(
        friendly_name="Continuous Heating",
        icon="mdi:radiator",
        entity_category="diagnostic",
    ),
    "ctlv2.HcStorageTempBottom": RegisterMeta(
        friendly_name="Heating Storage Temp (Bottom)",
        device_class="temperature",
        unit="°C",
        enabled=False,
    ),
    "ctlv2.HcStorageTempTop": RegisterMeta(
        friendly_name="Heating Storage Temp (Top)",
        device_class="temperature",
        unit="°C",
        enabled=False,
    ),
    "ctlv2.HydraulicScheme": RegisterMeta(
        friendly_name="Hydraulic Scheme",
        icon="mdi:pipe-valve",
        entity_category="diagnostic",
    ),
    "ctlv2.MaxCylinderChargeTime": RegisterMeta(
        friendly_name="Maximum Cylinder Charge Time",
        icon="mdi:timer-outline",
        unit="min",
        entity_category="diagnostic",
    ),
    "ctlv2.MultiRelaySetting": RegisterMeta(
        friendly_name="Multi Relay Setting",
        icon="mdi:relay",
        entity_category="diagnostic",
    ),
    "ctlv2.OutsideTempAvg": RegisterMeta(
        friendly_name="Average Outside Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Z1CoolingTemp": RegisterMeta(
        friendly_name="Zone Cooling Temperature",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=17,
        max_value=30,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Z1CoolingOpMode": RegisterMeta(
        friendly_name="Zone Cooling Mode",
        icon="mdi:snowflake",
        writable=True,
        options=["off", "auto", "manual"],
        entity_type="select",
        entity_category="config",
    ),
    "ctlv2.Z1CoolingManualTemp": RegisterMeta(
        friendly_name="Zone Cooling Manual Temp",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=17,
        max_value=30,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Z1CoolingSetbackTemp": RegisterMeta(
        friendly_name="Zone Cooling Setback Temp",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=17,
        max_value=30,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Z1CoolingTempDesired": RegisterMeta(
        friendly_name="Zone Cooling Temp Desired",
        device_class="temperature",
        unit="°C",
    ),
    "ctlv2.Z1HolidayStartPeriod": RegisterMeta(
        friendly_name="Holiday Start",
        icon="mdi:calendar-start",
    ),
    "ctlv2.Z1HolidayEndPeriod": RegisterMeta(
        friendly_name="Holiday End",
        icon="mdi:calendar-end",
    ),
    "ctlv2.Z1QuickVetoEndDate": RegisterMeta(
        friendly_name="Quick Veto End Date",
        icon="mdi:calendar-clock",
    ),
    "ctlv2.Z1QuickVetoEndTime": RegisterMeta(
        friendly_name="Quick Veto End Time",
        icon="mdi:clock-outline",
    ),
    "ctlv2.Z1RoomTemp": RegisterMeta(
        friendly_name="Room Temperature",
        device_class="temperature",
        unit="°C",
        state_class="measurement",
    ),
    "ctlv2.Z2RoomTemp": RegisterMeta(
        friendly_name="Room Temperature Zone 2",
        device_class="temperature",
        unit="°C",
        state_class="measurement",
    ),
    "ctlv2.Z1QuickVetoDuration": RegisterMeta(
        friendly_name="Quick Veto Duration",
        icon="mdi:timer-outline",
        writable=True,
        min_value=0,
        max_value=24,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Z1QuickVetoTemp": RegisterMeta(
        friendly_name="Quick Veto Temperature",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=30,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Z1HolidayTemp": RegisterMeta(
        friendly_name="Holiday Temperature",
        device_class="temperature",
        unit="°C",
        writable=True,
        min_value=5,
        max_value=30,
        step=0.5,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.Z1SFMode": RegisterMeta(
        friendly_name="Zone Special Function",
        icon="mdi:home-thermometer",
        entity_category="diagnostic",
    ),
    "ctlv2.MaxRoomHumidity": RegisterMeta(
        friendly_name="Max Room Humidity",
        icon="mdi:water-percent",
        unit="%",
        writable=True,
        min_value=0,
        max_value=100,
        step=1,
        entity_type="number",
        entity_category="config",
    ),
    "ctlv2.z1RoomHumidity": RegisterMeta(
        friendly_name="Room Humidity",
        device_class="humidity",
        unit="%",
        icon="mdi:water-percent",
    ),
    "ctlv2.ManualCoolingStartDate": RegisterMeta(
        friendly_name="Manual Cooling Start Date",
        icon="mdi:snowflake",
        entity_category="diagnostic",
    ),
    "ctlv2.ManualCoolingEndDate": RegisterMeta(
        friendly_name="Manual Cooling End Date",
        icon="mdi:snowflake",
        entity_category="diagnostic",
    ),
    "ctlv2.Date": RegisterMeta(
        friendly_name="Date",
        icon="mdi:calendar",
        entity_category="diagnostic",
    ),
    "ctlv2.FrostOverRideTime": RegisterMeta(
        friendly_name="Frost Override Time",
        icon="mdi:snowflake",
        entity_category="diagnostic",
    ),
    "ctlv2.Errorhistory": RegisterMeta(
        friendly_name="Error History",
        icon="mdi:alert-circle-outline",
        entity_category="diagnostic",
    ),
    # cctimer (Schedule) — mark as diagnostic for now
    "ctlv2.CcTimer_Config": RegisterMeta(
        friendly_name="Schedule Config",
        icon="mdi:calendar-clock",
        entity_category="diagnostic",
    ),
    "ctlv2.CcTimer_Timeframes": RegisterMeta(
        friendly_name="Schedule Timeframes",
        icon="mdi:calendar-clock",
        entity_category="diagnostic",
    ),
    # Broadcast (System)
    "Broadcast.Outsidetemp": RegisterMeta(
        friendly_name="Outside Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "Broadcast.Vdatetime": RegisterMeta(
        friendly_name="Date/Time",
        icon="mdi:clock",
        entity_category="diagnostic",
    ),
    "Broadcast.Datetime": RegisterMeta(
        friendly_name="Date/Time (alt)",
        icon="mdi:clock",
        entity_category="diagnostic",
    ),
    "Broadcast.Error": RegisterMeta(
        friendly_name="System Error",
        icon="mdi:alert",
        entity_category="diagnostic",
    ),
    "Broadcast.HwcStatus": RegisterMeta(
        friendly_name="DHW Status",
        entity_type="binary_sensor",
        entity_category="diagnostic",
    ),
    "Broadcast.WaterPressure": RegisterMeta(
        friendly_name="Water Pressure",
        device_class="pressure",
        unit="bar",
    ),
    "Broadcast.FlowTemp": RegisterMeta(
        friendly_name="Flow Temperature",
        device_class="temperature",
        unit="°C",
    ),
    # vwz (Valve) — test registers, disabled
    "vwz.TestHwcTemp": RegisterMeta(
        friendly_name="DHW Temperature (test)",
        device_class="temperature",
        unit="°C",
        entity_category="diagnostic",
        enabled=False,
    ),
    "vwz.TestOutdoorTemp": RegisterMeta(
        friendly_name="Outdoor Temperature (test)",
        device_class="temperature",
        unit="°C",
        entity_category="diagnostic",
        enabled=False,
    ),
    "vwz.TestThreeWayValve": RegisterMeta(
        friendly_name="Three-Way Valve (test)",
        entity_category="diagnostic",
        enabled=False,
    ),
    # v32 (recoVAIR ventilation) — from szflo's dump, discussion #31
    "v32.ExhaustAirHumidity": RegisterMeta(
        friendly_name="Exhaust Air Humidity",
        icon="mdi:water-percent",
        unit="%",
    ),
    "v32.SupplyAirTemp": RegisterMeta(
        friendly_name="Supply Air Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "v32.ExhaustAirTemp": RegisterMeta(
        friendly_name="Exhaust Air Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "v32.OutsideAirTemp": RegisterMeta(
        friendly_name="Outside Air Temperature (Ventilation)",
        device_class="temperature",
        unit="°C",
    ),
    "v32.VentilationLevelDay": RegisterMeta(
        friendly_name="Ventilation Level Day",
        icon="mdi:fan",
    ),
    "v32.VentilationLevelNight": RegisterMeta(
        friendly_name="Ventilation Level Night",
        icon="mdi:fan",
    ),
    "v32.BypassPosition": RegisterMeta(
        friendly_name="Bypass Position",
        icon="mdi:valve",
        unit="%",
    ),
    "v32.YieldMonth": RegisterMeta(
        friendly_name="Yield Month",
        device_class="energy",
        unit="kWh",
    ),
    "v32.YieldToday": RegisterMeta(
        friendly_name="Yield Today",
        device_class="energy",
        unit="kWh",
    ),
    "v32.YieldYear": RegisterMeta(
        friendly_name="Yield Year",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "v32.YieldTotal": RegisterMeta(
        friendly_name="Yield Total",
        device_class="energy",
        unit="kWh",
        state_class="total_increasing",
    ),
    "v32.MinAirHumidity": RegisterMeta(
        friendly_name="Min Air Humidity",
        icon="mdi:water-percent",
        unit="%",
        entity_category="diagnostic",
    ),
    "v32.MaxAirHumidity": RegisterMeta(
        friendly_name="Max Air Humidity",
        icon="mdi:water-percent",
        unit="%",
        entity_category="diagnostic",
    ),
    # v32 gas boiler (ecoTEC plus via VR32 board, bai.308523.inc) — from the
    # community discovery dump in issue #83. Layouts follow the upstream
    # tempsensor/tempmirrorsensor/presssensor models.
    "v32.ReturnTemp": RegisterMeta(
        friendly_name="Return Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "v32.StorageTemp": RegisterMeta(
        friendly_name="Storage Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "v32.StorageTempDesired": RegisterMeta(
        friendly_name="Storage Temperature Desired",
        device_class="temperature",
        unit="°C",
    ),
    "v32.FlowTempDesired": RegisterMeta(
        friendly_name="Flow Temperature Desired",
        device_class="temperature",
        unit="°C",
    ),
    "v32.FlowTempMax": RegisterMeta(
        friendly_name="Maximum Flow Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "v32.ReturnTempMax": RegisterMeta(
        friendly_name="Maximum Return Temperature",
        device_class="temperature",
        unit="°C",
    ),
    "v32.FanHours": RegisterMeta(
        friendly_name="Fan Hours",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
    ),
    "v32.HcHours": RegisterMeta(
        friendly_name="Heating Hours",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
    ),
    "v32.HwcHours": RegisterMeta(
        friendly_name="Hot Water Hours",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
    ),
    "v32.PumpHours": RegisterMeta(
        friendly_name="Pump Hours",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
    ),
    "v32.StorageLoadPumpHours": RegisterMeta(
        friendly_name="Storage Load Pump Hours",
        device_class="duration",
        unit="h",
        state_class="total_increasing",
    ),
    "v32.HoursTillService": RegisterMeta(
        friendly_name="Hours Until Service",
        device_class="duration",
        unit="h",
    ),
    "v32.PumpPower": RegisterMeta(
        friendly_name="Pump Power",
        device_class="power",
        unit="W",
    ),
    # Faulty-sensor registers: the physical sensors are absent on this system
    # (sensor status "circuit"/"cutoff"), so they stay disabled by default and
    # the fault values are filtered as no-data.
    "v32.HwcTemp": RegisterMeta(
        friendly_name="Hot Water Temperature",
        device_class="temperature",
        unit="°C",
        enabled=False,
    ),
    "v32.OutdoorstempSensor": RegisterMeta(
        friendly_name="Outside Temperature Sensor",
        device_class="temperature",
        unit="°C",
        enabled=False,
    ),
    "v32.Maintenancedata_HwcTempMax": RegisterMeta(
        friendly_name="Max Hot Water Temperature (Maintenance)",
        device_class="temperature",
        unit="°C",
        entity_category="diagnostic",
        enabled=False,
    ),
    # v32.Status02 fields (hcmode.inc B511). Names follow the CSV comment
    # ("Betriebsart/Maximaltemperatur/ReglerCurrentTEMP/..."); the reporter was
    # asked to confirm their meaning live (issue #83).
    "v32.Status02.hwcmode": RegisterMeta(
        friendly_name="Operating Mode",
        entity_category="diagnostic",
    ),
    "v32.Status02.temp0": RegisterMeta(
        friendly_name="Max Temperature",
        device_class="temperature",
        unit="°C",
        entity_category="diagnostic",
    ),
    "v32.Status02.temp1": RegisterMeta(
        friendly_name="Current Temperature",
        device_class="temperature",
        unit="°C",
        entity_category="diagnostic",
    ),
    "v32.Status02.temp0_1": RegisterMeta(
        friendly_name="Max Temperature 2",
        device_class="temperature",
        unit="°C",
        entity_category="diagnostic",
    ),
    "v32.Status02.temp1_1": RegisterMeta(
        friendly_name="Current Temperature 2",
        device_class="temperature",
        unit="°C",
        entity_category="diagnostic",
    ),
    "vr_71.SetActorState": RegisterMeta(
        friendly_name="Mixer Actuator State",
        icon="mdi:tune-variant",
        entity_category="diagnostic",
    ),
    "vr_71.Mc1Operation": RegisterMeta(
        friendly_name="Mixing Circuit 1",
        icon="mdi:water-pump",
        entity_category="diagnostic",
    ),
    "vr_71.Mc2Operation": RegisterMeta(
        friendly_name="Mixing Circuit 2",
        icon="mdi:water-pump",
        entity_category="diagnostic",
    ),
    "vr_71.Mc3Operation": RegisterMeta(
        friendly_name="Mixing Circuit 3",
        icon="mdi:water-pump",
        entity_category="diagnostic",
    ),
    "vr_71.SensorData1": RegisterMeta(
        friendly_name="Mixer Sensors 1-7",
        icon="mdi:thermometer",
        entity_category="diagnostic",
    ),
    "vr_71.SensorData2": RegisterMeta(
        friendly_name="Mixer Sensors 8-12",
        icon="mdi:thermometer",
        entity_category="diagnostic",
    ),
    "vr_71.Currenterror": RegisterMeta(
        friendly_name="Error",
        icon="mdi:alert",
        entity_category="diagnostic",
    ),
    "vr_71.Errorhistory": RegisterMeta(
        friendly_name="Error History",
        icon="mdi:history",
        entity_category="diagnostic",
    ),
    "vr_71.Clearerrorhistory": RegisterMeta(
        friendly_name="Clear Error History",
        icon="mdi:delete",
        entity_category="diagnostic",
    ),
}


# Encode the W/V/QQ date bytes of the b516 energy-statistics API (upstream
# john30/ebusd-configuration issue #490). W is a month nibble that restarts at
# 0 for the last five months of the year, V a day nibble, and QQ counts
# half-years since 2000 plus one from August onwards. Each month owns two W
# values: days 1-15 stay on the even value (V=day), days 16-31 flip to the
# odd value with V=day-16. Worked examples from the thread: Feb 23 2025 ->
# "5732", Aug 24 2026 -> "1835".
def b516_date_bytes(now: datetime) -> str:
    qq = (now.year - 2000) * 2
    if now.month >= 8:
        qq += 1
        w = (now.month - 8) * 2
    else:
        w = now.month * 2
    if now.day > 15:
        w += 1
        v = now.day - 16
    else:
        v = now.day
    return f"{(w << 4) | v:02x}{qq:02x}"


# Look up RegisterMeta by circuit.name, return empty meta if unknown
def get_meta(circuit: str, name: str, field: str = "value") -> RegisterMeta:
    key = f"{circuit}.{name}"
    if field != "value":
        key += f".{field}"
    meta = REGISTER_MAP.get(key)
    # Fallbacks for hardware variants that expose the same register under a
    # different circuit. The ctlv2 variant can appear as its own circuit (do not
    # self-alias), and heat-pump statistics (Stat* energy, etc.) map onto the hmu
    # keys across controller circuits.
    if meta is None:
        for alt_circuit in ("ctlv2", "hmu"):
            if alt_circuit == circuit:
                continue
            alt = f"{alt_circuit}.{name}"
            if field != "value":
                alt += f".{field}"
            meta = REGISTER_MAP.get(alt)
            if meta is not None:
                break
    return meta or RegisterMeta()
