## 1. Protocol Layer

- [ ] 1.1 Add `write_setpoint()` method to VaillantClient — SPINE call with `setpointData` payload
- [ ] 1.2 Add `write_hvac_mode()` method to VaillantClient — SPINE call with `hvacModeListData` payload
- [ ] 1.3 Handle `resultData` reply in write path — log errorNumber != 0
- [ ] 1.4 Add daemon `POST /write` endpoint for local testing

## 2. Home Assistant Integration

- [ ] 2.1 Register `set_dhw_target_temperature` service in `__init__.py`
- [ ] 2.2 Register `set_hvac_mode` service in `__init__.py`
- [ ] 2.3 Add Number entity for DHW temperature setpoint (optional, default disabled)
- [ ] 2.4 Add Select entity for HVAC mode (optional, default disabled)
- [ ] 2.5 Add integration option flag to enable write entities

## 3. Validation

- [ ] 3.1 Test DHW setpoint write via daemon endpoint
- [ ] 3.2 Test HVAC mode write via daemon endpoint
- [ ] 3.3 Run ruff, pytest, compileall
- [ ] 3.4 Upload to HA and verify services appear
