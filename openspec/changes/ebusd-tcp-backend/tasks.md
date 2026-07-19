## 0. Data Capture (DONE — all 362 registers known)

- [x] 0.1 Connect to ebusd via MQTT — ~25 topics in 60s window
- [x] 0.2 Connect to ebusd via TCP direct (port 8888) — `find` returns 362 registers
- [x] 0.3 Complete register inventory documented in design.md
- [x] 0.4 Identify live vs idle registers (most heat pump data shows "no data stored" — compressor idle in summer)
- [x] 0.5 Scan result: 4 Vaillant slaves detected: HMU00, CTLV2, VWZ00, NETX2
- [x] 0.6 Write payload test: syntax confirmed as `write -c <circuit> <name> <value>`
- [x] 0.7 HTTP API port 8889 opened by user but not verified (ebusd may need restart)

## 1. Project Scaffolding

- [ ] 1.1 Create `custom_components/vaillant_eebus/backend/` with `__init__.py`
- [ ] 1.2 Create `backend/base.py` with abstract `Backend` class (`async_connect`, `async_disconnect`, `async_find`, `async_read`, `async_write`, `async_poll`)
- [ ] 1.3 Create `backend/models.py` with dataclasses (`EbusdRegister`, `Circuit`, `RegisterMeta`, `WriteResult`)
- [ ] 1.4 Create `backend/tcp.py` — `EbusdTcpBackend` implementing `Backend` via asyncio TCP
- [ ] 1.5 Implement TCP connection lifecycle: connect, send/receive, reconnect with backoff (1s-60s)
- [ ] 1.6 Implement `async_find()` — send `f`, parse 362-line response into `list[EbusdRegister]`
- [ ] 1.7 Implement `async_read(circuit, name)` — send `r <circuit> <name>`, parse response
- [ ] 1.8 Implement `async_write(circuit, name, value)` — send `write -c <circuit> <name> <value>`, check `done`
- [ ] 1.9 Implement read-after-write verification
- [ ] 1.10 Create `backend/mapping.py` with default metadata (friendly names, icons, units, device_classes) for all 362 registers

## 2. Auto-Discovery

- [ ] 2.1 On startup, call `async_find()` and parse all registers
- [ ] 2.2 Classify registers: has data vs "no data stored", writable vs readonly, numeric vs enum vs boolean
- [ ] 2.3 Create `backend/entity_factory.py` — generate HA entity descriptions from discovered registers
- [ ] 2.4 Register type assignment:
  - Numeric values → Sensor (if readonly) or Number (if writable + numeric)
  - Enum values → Sensor (if readonly) or Select (if writable + options known)
  - Boolean/OnOff → BinarySensor (if readonly) or Switch (if writable)
  - Button → for reset/refresh actions
- [ ] 2.5 Implement `entities.yaml` loading from `<ha-config>/vaillant_eebus/entities.yaml`
- [ ] 2.6 Implement YAML override merging (friendly_name, icon, unit, device_class, min/max/step, enabled, writable)
- [ ] 2.7 Implement deduplication — single entity per register+field
- [ ] 2.8 Implement `rediscover` — reconnect, re-run `find`, merge new registers

## 3. Config Flow & Options

- [ ] 3.1 Update `config_flow.py` — add backend selection (ebusd TCP / EEBUS supplement / both)
- [ ] 3.2 Add ebusd host/port config (defaults: 192.168.1.100, 8888)
- [ ] 3.3 Add connection test step (connect to ebusd, run `i`)
- [ ] 3.4 Add options flow: poll interval, entities.yaml path, write timeout
- [ ] 3.5 Add runtime reload support for config changes

## 4. Sensor Platform

- [ ] 4.1 Create `sensor.py` — dynamic sensor platform from discovered registers
- [ ] 4.2 Implement device_class inference from register metadata + YAML overrides:
  - Temperature values → DEVICE_CLASS_TEMPERATURE
  - Pressure values → DEVICE_CLASS_PRESSURE
  - Energy values → DEVICE_CLASS_ENERGY
  - Power values → DEVICE_CLASS_POWER
  - Duration values → DEVICE_CLASS_DURATION
  - Enum/string values → no device_class
- [ ] 4.3 Set state_class: `measurement` for live values, `total_increasing` for counters
- [ ] 4.4 Set entity_category: `diagnostic` for rarely-changing values (config, firmware, serial)
- [ ] 4.5 Unique ID: `ebusd_<circuit>_<name>_<field>` (field omitted when single-field)

## 5. Binary Sensor Platform

- [ ] 5.1 Create `binary_sensor.py` — dynamic binary sensor platform
- [ ] 5.2 Map known binary states (pumpstate=on/off, hcmode=day/night, disablehc=0/1)
- [ ] 5.3 Device classes: PROBLEM (error), RUNNING (compressor/pump), HEAT (heating), COLD (cooling)

## 6. Control Platforms

- [ ] 6.1 Create `number.py` — Number entities for writable numeric registers
- [ ] 6.2 Implement min/max/step from YAML overrides or register metadata
- [ ] 6.3 Create `select.py` — Select entities for writable enum registers
- [ ] 6.4 Implement option list from register metadata or YAML
- [ ] 6.5 Create `switch.py` — Switch entities for writable boolean registers (disablehc, disablehwctapping, etc.)
- [ ] 6.6 Implement readonly protection — block writes on registers not marked writable

## 7. HA Services

- [ ] 7.1 Register `read_parameter` service — return current value by circuit.name[.field]
- [ ] 7.2 Register `write_parameter` service — write value with validation + verification
- [ ] 7.3 Register `refresh` service — force re-read of all active registers
- [ ] 7.4 Register `rediscover` service — re-run `find` entity discovery
- [ ] 7.5 Add service schemas in `services.yaml`

## 8. Coordinator & Backend Wiring

- [ ] 8.1 Update `coordinator.py` — `DataUpdateCoordinator` that selects backend from config
- [ ] 8.2 Implement poll loop: every N seconds, read all active registers via TCP
- [ ] 8.3 Implement availability: mark entities unavailable on connection loss
- [ ] 8.4 Wire entity platforms to coordinator for state management
- [ ] 8.5 Wire backend to `__init__.py` setup/unload lifecycle

## 9. Error Handling

- [ ] 9.1 Connection loss: auto-reconnect with exponential backoff, entities unavailable
- [ ] 9.2 ebusd restart: detect via connection drop, re-discover on reconnect
- [ ] 9.3 Timeout: abort request, retry on next poll cycle
- [ ] 9.4 Unknown register: ignore, log DEBUG

## 10. Diagnostics

- [ ] 10.1 Update `diagnostics.py` — TCP connection status, last command, reconnect count
- [ ] 10.2 Include discovered circuits with register count per circuit
- [ ] 10.3 Include ebusd version, firmware versions of all slaves
- [ ] 10.4 Include error counts (timeouts, connection losses, write failures)

## 11. EEBUS Supplement Integration

- [ ] 11.1 Verify EEBUS backend still works after abstraction changes
- [ ] 11.2 Add EEBUS supplement toggle in config flow
- [ ] 11.3 Merge entity lists from both backends when supplement enabled
- [ ] 11.4 Test dual-backend mode (4 EEBUS energy measurements + ebusd telemetry)

## 12. Testing

- [ ] 12.1 Unit tests: `models.py`, `mapping.py`, `entity_factory.py`
- [ ] 12.2 Unit tests: `tcp.py` command encoding/decoding, parse `find` output
- [ ] 12.3 Integration tests: fake ebusd TCP server, verify connect/find/read/write
- [ ] 12.4 Integration tests: full discovery → entity creation cycle
- [ ] 12.5 Write verification tests: success, timeout, mismatch rollback
- [ ] 12.6 Error handling tests: connection loss, ebusd restart, timeout, malformed responses
- [ ] 12.7 Config flow tests: TCP host/port config, backend selection, options
- [ ] 12.8 EEBUS supplement tests: dual-backend entity merging

## 13. CI/CD

- [ ] 13.1 Add GitHub Actions: ruff, mypy, pytest, compileall
- [ ] 13.2 Add HACS validation step in CI
- [ ] 13.3 Configure mypy for HA type stubs and backend modules

## 14. Documentation

- [ ] 14.1 Write setup guide — ebusd addon config, TCP port, entity discovery
- [ ] 14.2 Write entities.yaml reference — all override options + examples
- [ ] 14.3 Write developer guide — adding register mappings, testing with fake ebusd
- [ ] 14.4 Write troubleshooting guide — connection issues, empty registers, write failures

## 15. Validation

- [ ] 15.1 Run `ruff check .` — zero violations
- [ ] 15.2 Run `pytest -q` — all tests passing
- [ ] 15.3 Run `python3 -m compileall custom_components` — no compile errors
- [ ] 15.4 Run mypy on backend modules — no type errors
- [ ] 15.5 Verify HA install on real server with ebusd TCP
- [ ] 15.6 Verify EEBUS supplement mode works alongside ebusd
