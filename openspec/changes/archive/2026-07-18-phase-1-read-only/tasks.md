# Tasks: Vaillant EEBUS Integration — Phase 1 (Pivot to EBUS)

## Status: PIVOT COMPLETE

After extensive testing, EEBUS (VR921) only provides 4 live measurements. The VR921 is an energy-management gateway, not a full heat pump diagnostic interface. Internal heat pump data requires the eBUS protocol.

**EEBUS codebase status:** Functional, tested, ready for optional use. The 4 EEBUS measurements can supplement the EBUS data path.

**New direction:** EBUS via ebusd + hardware adapter. This gives complete heat pump telemetry.

## EEBUS — Completed (retained as optional supplement)

### Protocol — SHIP/SPINE transport
- [x] Certificate generation with SKI reuse
- [x] SHIP handshake state machine
- [x] SPINE datagram read/write
- [x] mDNS discovery for `_ship._tcp.local.`
- [x] Reconnect with exponential backoff
- [x] Unit tests: certificate, SPINE parsing
- [ ] SHIP handshake unit tests (nice-to-have)

### Capability model + Recorder
- [x] Capability dataclass + CapabilityRegistry
- [x] UnknownFeatureRegistry
- [x] SessionRecorder + JSONL output
- [x] Full reference capture against live VR921
- [x] SessionReplay transport
- [x] Replay-based integration test

### Measurement reading
- [x] Entity tree discovery
- [x] Measurement subscription
- [x] Measurement description/value parsing
- [x] Scope type → HA name/unit mapping
- [x] Poll fallback
- [x] Integration test against real VR921
- [x] Local daemon with HTTP debug API

### Feature support (beyond reference project)
- [x] Setpoint server detection + subscribe + poll
- [x] HVAC mode server detection + subscribe + poll
- [x] SmartEnergy management detection
- [x] ElectricalConnection parameter descriptions (16 params, all scopeType=None)
- [x] Use case data parsing
- [x] Write: setpoint + HVAC mode (errorNumber: 0, no data triggered)
- [x] DeviceClassification reads (10 sent, responses unrecorded)

### HA integration
- [x] Config flow (mDNS + manual + connection test)
- [x] Coordinator (DataUpdateCoordinator wrapper)
- [x] Sensor platform (dynamic from capabilities)
- [x] Binary sensor (compressor running)
- [x] Diagnostics
- [x] Strings + translations

### Research
- [x] Read-back behaviour (design.md §1.1)
- [x] Feature ID stability (design.md §1.2)
- [x] Subscription lifecycle (design.md §1.3)
- [x] Unknown packet handling (design.md §1.4)
- [x] Setpoint write confirmation (design.md §1.5)
- [x] Empirical VR921 data availability (design.md §1.6) — **only 4/19 live**
- [x] Loxone alternative (design.md §1.7) — **same limitation, same protocol**
- [x] GitHub reference analysis (markusschultheis/Vaillant-VR921) — **same 4 values**
- [x] Write trigger test (setpoint 40°C + HVAC comfort, 120s capture) — **no new data**

## EBUS — Phase 1 (New)

### Hardware
- [ ] Research: choose eBUS adapter (USB vs GPIO vs ESP32)
- [ ] Research: pinout for aroTHERM plus / VWL series service port
- [ ] Purchase eBUS adapter
- [ ] Connect adapter to heat pump service port
- [ ] Verify connectivity (LED, serial)

### Software — ebusd
- [ ] Install ebusd (native or container)
- [ ] Configure ebusd for Vaillant heat pump
- [ ] Verify data via `ebusctl` / MQTT / HTTP
- [ ] Tune polling interval for desired sensors

### HA Integration — Built-in
- [ ] Configure HA built-in ebusd integration
- [ ] Map desired sensors/entities
- [ ] Verify data reliability

### HA Integration — Custom (if built-in is insufficient)
- [ ] Assess gaps in built-in ebusd integration
- [ ] Option: custom ebusd HA component for specific Vaillant telemetry

### EEBUS Supplement (optional, later)
- [ ] Integrate EEBUS 4 measurements alongside EBUS
- [ ] Unified dashboard with both sources

## Out of scope (Phase 2+)
- Write operations via EEBUS (setpoint, HVAC mode)
- Energy dashboard
- Cloud API reverse engineering (last resort)
