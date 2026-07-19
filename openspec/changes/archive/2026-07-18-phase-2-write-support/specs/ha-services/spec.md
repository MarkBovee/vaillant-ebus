# HA Services

## Scope

Home Assistant services and entities for setpoint and HVAC mode control.

## Requirements

### R1: set_dhw_target_temperature service
HA service accepting `temperature` (float, 35–65°C). Writes to DHW Setpoint server e[4]f18 via `VaillantClient.write_setpoint()`.

### R2: set_hvac_mode service
HA service accepting `mode` (string: heating/cooling/ventilation/standby/auto) and optional `entity_id` targeting specific HVAC server (DHW circuit or HVAC room). Writes via `VaillantClient.write_hvac_mode()`.

### R3: Number entity for DHW setpoint
Optional Number entity `dhw_target_temperature` in HA UI. Range 35–65°C, step 1°C. Write on value change.

### R4: Select entity for HVAC mode
Optional Select entity `hvac_mode` in HA UI. Options: heating, cooling, ventilation, standby, auto.

### R5: Error handling
Rejected writes (errorNumber != 0) log at WARNING level. No HA notification or persistent alert.

### R6: Configuration toggle
Write entities disabled by default. Users enable via integration options or services. Rationale: accidental write to HVAC in summer could cause heating activation.
