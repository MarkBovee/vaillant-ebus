## Context

Phase 1 confirmed VR921 Setpoint features (e[4]f18, e[5,1,1]f18) and HVAC features (e[4]f9, e[5,1,1]f9) accept SPINE subscription requests but do NOT respond to `setpointData` or `hvacModeListData` reads. Only the Measurement subscription path returns live data.

EEBUS SPINE differentiates between `read` (request current value) and `call` (invoke operation / write value). Setpoint and HVAC features expose write operations via `call` — the VR921 expects a `setpointData` or `hvacModeListData` payload inside a `cmdClassifier: "call"` datagram rather than `"read"`.

## Goals / Non-Goals

**Goals:**
- Send SPINE `call` to Setpoint server features with `setpointData` payload to set DHW target temperature
- Send SPINE `call` to HVAC server features with `hvacModeListData` payload to change operating mode
- Expose as HA services (`set_dhw_target_temperature`, `set_hvac_mode`)
- Expose optional Number and Select entities for UI-based control
- Support local testing via daemon HTTP endpoint

**Non-Goals:**
- No scheduling or automation logic — pure passthrough to VR921
- No energy dashboard integration
- No multi-zone coordination — each Setpoint/HVAC feature addressed individually

## Decisions

1. **SPINE `call` with data payload** — reuse existing `send_spine_call()` from `vaillant/spine.py`; no protocol changes needed
2. **Separate write methods in `VaillantClient`** — `write_setpoint(entity, feature, value)` and `write_hvac_mode(entity, feature, mode)` methods; keeps concerns separate from read path
3. **HA services over entities as primary path** — services (`set_dhw_target_temperature`, `set_hvac_mode`) are the minimal viable write interface; Number/Select entities are secondary for users who prefer UI control
4. **No HA coordinator integration** — writes are fire-and-forget calls; the coordinator continues polling measurements independently
5. **Daemon HTTP endpoint** — `POST /write` accepts `{"entity": [...], "feature": N, "cmd": "...", "value": ...}` for testing without HA

## Risks / Trade-offs

- **No read-back confirmation** — VR921 does not support reading current setpoints; write confirmation is limited to successful SPINE `result` (errorNumber=0)
- **Subscription gap** — VR921 accepts Setpoint/HVAC subscriptions but sends no notifications; cannot detect when VR921 or app overrides locally
- **DHW heating lock** — setpoint write may be rejected if DHW is currently heating; VR921 returns errorNumber
- **No validation** — temperature range or mode availability is not probed; VR921 rejects invalid values with SPINE error
