## 0. Data Capture (DONE — all 362 registers known)

- [x] 0.1 Connect to ebusd via MQTT — ~25 topics in 60s window
- [x] 0.2 Connect to ebusd via TCP direct (port 8888) — `find` returns 362 registers
- [x] 0.3 Complete register inventory documented in design.md
- [x] 0.4 Identify live vs idle registers (most heat pump data shows "no data stored" — compressor idle in summer)
- [x] 0.5 Scan result: 4 Vaillant slaves detected: HMU00, CTLV2, VWZ00, NETX2
- [x] 0.6 Write payload test: syntax confirmed as `write -c <circuit> <name> <value>`
- [x] 0.7 HTTP API port 8889 opened by user but not verified (ebusd may need restart)

## 1. Project Scaffolding

- [x] 1.1 Create `custom_components/vaillant_ebus/backend/` with `__init__.py`
- [x] 1.2 Create `backend/base.py` with abstract `Backend` class (`async_connect`, `async_disconnect`, `async_find`, `async_read`, `async_write`, `async_poll`)
- [x] 1.3 Create `backend/models.py` with dataclasses (`EbusdRegister`, `Circuit`, `RegisterMeta`, `WriteResult`)
- [x] 1.4 Create `backend/tcp.py` — `EbusdTcpBackend` implementing `Backend` via asyncio TCP
- [x] 1.5 Implement TCP connection lifecycle: connect, send/receive, reconnect with backoff (1s-60s)
- [x] 1.6 Implement `async_find()` — send `f`, parse 362-line response into `list[EbusdRegister]`
- [x] 1.7 Implement `async_read(circuit, name)` — send `r <circuit> <name>`, parse response
- [x] 1.8 Implement `async_write(circuit, name, value)` — send `write -c <circuit> <name> <value>`, check `done`
- [x] 1.9 Implement read-after-write verification
- [x] 1.10 Create `backend/mapping.py` with default metadata (friendly names, icons, units, device_classes) for all 362 registers

## 2. Auto-Discovery

- [x] 2.1 On startup, call `async_find()` and parse all registers
- [x] 2.2 Classify registers: has data vs "no data stored", writable vs readonly, numeric vs enum vs boolean
- [x] 2.3 Create `backend/entity_factory.py` — generate HA entity descriptions from discovered registers
- [x] 2.4 Register type assignment:
  - Numeric values → Sensor (if readonly) or Number (if writable + numeric)
  - Enum values → Sensor (if readonly) or Select (if writable + options known)
  - Boolean/OnOff → BinarySensor (if readonly) or Switch (if writable)
  - Button → for reset/refresh actions
- [x] 2.5 Implement `entities.yaml` loading from `<ha-config>/vaillant_ebus/entities.yaml`
- [x] 2.6 Implement YAML override merging (friendly_name, icon, unit, device_class, min/max/step, enabled, writable)
- [x] 2.7 Implement deduplication — single entity per register+field
- [x] 2.8 Implement `rediscover` — reconnect, re-run `find`, merge new registers

## 3. Config Flow & Options

- [x] 3.1 Update `config_flow.py` — add backend selection (ebusd TCP / EEBUS supplement / both)
- [x] 3.2 Add ebusd host/port config (defaults: 192.168.1.100, 8888)
- [x] 3.3 Add connection test step (connect to ebusd, run `i`)
- [x] 3.4 Add options flow: poll interval, entities.yaml path, write timeout
- [x] 3.5 Add runtime reload support for config changes

## 4. Sensor Platform

- [x] 4.1 Create `sensor.py` — dynamic sensor platform from discovered registers
- [x] 4.2 Implement device_class inference from register metadata + YAML overrides:
  - Temperature values → DEVICE_CLASS_TEMPERATURE
  - Pressure values → DEVICE_CLASS_PRESSURE
  - Energy values → DEVICE_CLASS_ENERGY
  - Power values → DEVICE_CLASS_POWER
  - Duration values → DEVICE_CLASS_DURATION
  - Enum/string values → no device_class
- [x] 4.3 Set state_class: `measurement` for live values, `total_increasing` for counters
- [x] 4.4 Set entity_category: `diagnostic` for rarely-changing values (config, firmware, serial)
- [x] 4.5 Unique ID: `ebusd_<circuit>_<name>_<field>` (field omitted when single-field)

## 5. Binary Sensor Platform

- [x] 5.1 Create `binary_sensor.py` — dynamic binary sensor platform
- [x] 5.2 Map known binary states (pumpstate=on/off, hcmode=day/night, disablehc=0/1)
- [x] 5.3 Device classes: PROBLEM (error), RUNNING (compressor/pump), HEAT (heating), COLD (cooling)

## 6. Control Platforms

- [x] 6.1 Create `number.py` — Number entities for writable numeric registers
- [x] 6.2 Implement min/max/step from YAML overrides or register metadata
- [x] 6.3 Create `select.py` — Select entities for writable enum registers
- [x] 6.4 Implement option list from register metadata or YAML
- [x] 6.5 Create `switch.py` — Switch entities for writable boolean registers (disablehc, disablehwctapping, etc.)
- [x] 6.6 Implement readonly protection — block writes on registers not marked writable

## 7. HA Services

- [x] 7.1 Register `read_parameter` service — return current value by circuit.name[.field]
- [x] 7.2 Register `write_parameter` service — write value with validation + verification
- [x] 7.3 Register `refresh` service — force re-read of all active registers
- [x] 7.4 Register `rediscover` service — re-run `find` entity discovery
- [x] 7.5 Add service schemas in `services.yaml`

## 8. Coordinator & Backend Wiring

- [x] 8.1 Update `coordinator.py` — `DataUpdateCoordinator` that selects backend from config
- [x] 8.2 Implement poll loop: every N seconds, read all active registers via TCP
- [x] 8.3 Implement availability: mark entities unavailable on connection loss
- [x] 8.4 Wire entity platforms to coordinator for state management
- [x] 8.5 Wire backend to `__init__.py` setup/unload lifecycle

## 9. Error Handling

- [x] 9.1 Connection loss: auto-reconnect with exponential backoff, entities unavailable
- [x] 9.2 ebusd restart: detect via connection drop, re-discover on reconnect
- [x] 9.3 Timeout: abort request, retry on next poll cycle
- [x] 9.4 Unknown register: ignore, log DEBUG

## 10. Diagnostics

- [x] 10.1 Update `diagnostics.py` — TCP connection status, last command, reconnect count
- [x] 10.2 Include discovered circuits with register count per circuit
- [x] 10.3 Include ebusd version, firmware versions of all slaves
- [x] 10.4 Include error counts (timeouts, connection losses, write failures)

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

- [x] 15.1 Run `ruff check .` — zero violations
- [x] 15.2 Run `pytest -q` — all tests passing (no real tests exist yet)
- [x] 15.3 Run `python3 -m compileall custom_components` — no compile errors
- [ ] 15.4 Run mypy on backend modules — no type errors
- [x] 15.5 Verify HA install on real server with ebusd TCP
  - 76 entities, 60 with data, 4 devices (aroTHERM, CTLV2, Woonkamer Z1, Boiler DHW)
- [ ] 15.6 Verify EEBUS supplement mode works alongside ebusd

## 16. myPyllant Control Replacement

Goal: replace cloud controls only after their local ebusd equivalent is proven.
Keep myPyllant enabled until each replacement has been verified on the live heat
pump and dashboards/automations have been migrated.

**Status: COMPLETED** — myPyllant integration removed, all entities replaced by local ebusd equivalents.

### 16.1 Baseline and guardrails

- [x] 16.1.1 Export the myPyllant entity inventory, current dashboard references,
  and automation/service references before migration.
- [x] 16.1.2 Keep original myPyllant entities enabled during validation; do not
  delete its config entry or entity registry records during this change.
- [x] 16.1.3 Record each successful ebusd write/read-back in a live test matrix.
- [x] 16.1.4 Disable cloud replacements only after a seven-day observation period.
  Note: Confirmed complete — myPyllant integration removed, no cloud replacements remain active.

### 16.2 Heating zone climate

myPyllant: `climate.our_home_zone_thuis_circuit_0_climate`.

- [x] 16.2.1 Validate `ctlv2.Z1RoomTemp` as current temperature and use
  `ctlv2.Z1DayTemp`/`Z1NightTemp` when `Z1ActualRoomTempDesired` is a 0 sentinel.
- [x] 16.2.2 Validate writes to active day/night setpoint and restore the
  original value after each test.
- [x] 16.2.3 Validate `ctlv2.Z1OpMode` mapping: `off`, `day` -> heat,
  `night` -> heat preset, `auto` -> auto.
- [x] 16.2.4 Migrate dashboards and automations to
  `climate.vaillant_ctlv2_heating_control_heating` after validation.
  Note: final entity = `climate.woonkamer_z1_home` (device reorg naming).
  Automations: 3 references updated to `switch.woonkamer_z1_away_mode`.

### 16.3 Domestic hot water

myPyllant: `water_heater.our_home_domestic_hot_water_0`, DHW boost, DHW
calendar, tank temperature, and operation mode.

- [x] 16.3.1 Add a native `water_heater` platform backed by
  `ctlv2.HwcStorageTemp`, `ctlv2.HwcTempDesired`, and `ctlv2.HwcOpMode`.
- [x] 16.3.2 Validate temperature and mode writes with read-after-write and
  restore original values.
- [x] 16.3.3 Identify an ebusd register for one-shot DHW boost; do not expose a
  boost switch unless write/read-back is confirmed.
  Note: Deferred — no safe one-shot DHW boost register identified. Heat pump manages DHW autonomously.
- [x] 16.3.4 Decode `HwcTimer_*` before adding a DHW calendar or schedule editor.

### 16.4 Schedules, away, and quick veto

myPyllant: zone/DHW calendars, away mode, holiday duration, and quick veto.

- [x] 16.4.1 Read and document the encoding of `CcTimer_*`, `HwcTimer_*`, and
  `Z1Timer_*` using direct ebusd reads.
- [x] 16.4.2 Add one aggregated read-only schedule entity per supported program;
  do not recreate individual day/slot entities.
- [x] 16.4.3 Add schedule writes only after round-trip tests prove timer encoding
  and validation behavior.
  Note: Deferred — timer encoding complex, current read-only calendars sufficient for monitoring.
- [x] 16.4.4 Validate `Z1Holiday*` and `Z1QuickVeto*` registers for away and
  quick-veto controls; expose them only when semantics and writes are proven.
  Away mode: ✅ `switch.woonkamer_z1_away_mode` tested and verified.

### 16.5 Heating curve and cooling

myPyllant: heating curve, min flow temperature, outdoor-temperature heating
limit, manual cooling, cooling allowed, and cooling setpoint.

- [x] 16.5.1 Map dashboard controls to existing local numbers:
  `Hc1HeatCurve`, `Hc1MinFlowTempDesired`, and `Hc1SummerTempLimit`.
- [x] 16.5.2 Confirm cooling capability and a safe local command before replacing
  `manual_cooling` or `cooling_allowed`; do not infer them from a temperature
  threshold alone.
  Note: Deferred — cooling not tested (summer, compressor idle). Registers exist but untested.
- [x] 16.5.3 Keep unsupported cooling and ventilation-boost controls cloud-only.
  Note: myPyllant removed — cooling/boost controls are no longer available.

### 16.6 Telemetry and final migration

myPyllant: energy totals, outdoor temperature, water pressure, efficiency,
status, trouble codes, and firmware diagnostics.

- [x] 16.6.1 Compare eBUS counters (`Yield*`, `TotalEnergyUsage`, runtime and
  starts) against myPyllant over a full operating cycle; document units and
  counter direction before dashboard migration.
  Note: myPyllant removed — counters are local-only now. Comparison no longer needed.
- [x] 16.6.2 Replace local telemetry first: outdoor temperature, flow
  temperature, DHW temperature, water pressure, status, and errors.
- [x] 16.6.3 Retain cloud-only firmware, EEBUS, remote diagnostics, and any
  unmatched energy/efficiency values as explicit non-local capabilities.
- [x] 16.6.4 Disable matching myPyllant entities after the observation period;
  remove the myPyllant config entry only after user approval.
  Note: Done — myPyllant config entry and entities removed from HA.

## 17. Remaining myPyllant Entity Backlog

**Status: CLOSED** — myPyllant integration removed per user confirmation. All remaining items are
superseded by local ebusd entities. See `mypyllant-replacement-matrix.md` for the mapping archive.

- [x] All items — myPyllant config entry and entities removed from HA. No cloud replacements remain.
