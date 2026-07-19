# Proposal: Phase 2 - Write Support

## Why

Phase 1 achieved read-only access: 4 live measurements, electrical connection parameter mapping, and full VR921 discovery. But users cannot control their heat pump — set DHW target temperature, switch operating modes, or activate cooling. The VR921 exposes Setpoint and HVAC server features that accept SPINE call (write) commands but reject reads. Phase 2 adds write capability through those features.

## What Changes

- **SPINE call (write) sender** — `send_spine_call` with data payload instead of empty read
- **Setpoint write** — `setpointData` call to Setpoint server features (DHW at e[4]f18, room at e[5,1,1]f18)
- **HVAC mode change** — `hvacModeListData` call to HVAC server features (DHW circuit at e[4]f9, room at e[5,1,1]f9)
- **HA services** — `set_dhw_target_temperature`, `set_hvac_mode` services exposed to automations/UI
- **HA number entities** — optional Number entities for setpoints with direct write

## Capabilities

### New Capabilities
- `setpoint-write`: SPINE call-based write to Setpoint (f18) server features; supported for DHW circuit and HVAC room setpoints
- `hvac-modes`: Read and write HVAC operating modes via HVAC (f9) server features; supported for DHW circuit and HVAC room
- `ha-services`: Home Assistant services for set_dhw_target_temperature and set_hvac_mode, plus optional Number/Select entities for direct control

### Modified Capabilities
- *(none — Phase 1 had no write capability)*

## Impact

- `vaillant/client.py` — add call-based write methods for Setpoint and HVAC
- `vaillant/spine.py` — no changes (send_spine_call exists)
- `custom_components/vaillant_eebus/` — add services, optional Number/Select entities
- `scripts/daemon.py` — expose write endpoint for testing
