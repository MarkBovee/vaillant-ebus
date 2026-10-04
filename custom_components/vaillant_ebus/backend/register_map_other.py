"""Register metadata for broadcast, vwz and v32 boiler registers."""

from __future__ import annotations

from .models import RegisterMeta

SYSTEM_AND_OTHER_REGISTERS: dict[str, RegisterMeta] = {
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
    "hmu.Status07": RegisterMeta(
        friendly_name="Display Status",
        icon="mdi:information",
        entity_category="diagnostic",
    ),
    "hmu.Status07.power": RegisterMeta(friendly_name="Display Compressor Power", device_class="power", unit="%"),
    "hmu.Status07.dailyenvyield": RegisterMeta(
        friendly_name="Display Environmental Yield Today", device_class="energy", unit="kWh"
    ),
    "hmu.Status07.display_b5_noisereduction": RegisterMeta(
        friendly_name="Quiet Mode", entity_type="binary_sensor", icon="mdi:volume-off"
    ),
    "hmu.Status07.display_b0_heaterenabled": RegisterMeta(
        friendly_name="Main Heater Enabled", entity_type="binary_sensor"
    ),
    "hmu.Status07.display_b2_backupheater": RegisterMeta(
        friendly_name="Backup Heater Active", entity_type="binary_sensor"
    ),
    "hmu.Status07.display_b6_dhwecomode": RegisterMeta(friendly_name="DHW Eco Mode", entity_type="binary_sensor"),
    "hmu.Status07.heatermain_b1_error": RegisterMeta(
        friendly_name="Comfort Protection Error", entity_type="binary_sensor", entity_category="diagnostic"
    ),
    "hmu.Status07.heatermain_b3_heating": RegisterMeta(friendly_name="Heating Active", entity_type="binary_sensor"),
    "hmu.Status07.heatermain_b4_cooling": RegisterMeta(friendly_name="Cooling Active", entity_type="binary_sensor"),
    "hmu.Status07.heatermain_b5_pressureloss": RegisterMeta(
        friendly_name="Pressure Loss", entity_type="binary_sensor", entity_category="diagnostic"
    ),
    "hmu.Status07.heatermain_b7_warmwater": RegisterMeta(friendly_name="DHW Active", entity_type="binary_sensor"),
    "hmu.Status07.displaypressure": RegisterMeta(
        friendly_name="Display System Pressure", device_class="pressure", unit="bar"
    ),
}
