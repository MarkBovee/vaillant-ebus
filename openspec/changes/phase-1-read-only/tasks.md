# Tasks: Vaillant EEBUS Integration — Phase 1 (Read-Only)

## Milestone 1: Repository scaffolding

- [x] Initialize Python project (`pyproject.toml`, `requirements.txt`, `requirements_test.txt`)
- [x] Create `hacs.json` with domain `vaillant_eebus`
- [x] Create `custom_components/vaillant_eebus/manifest.json` (domain, version, deps)
- [x] Create `LICENSE` (Apache 2.0)
- [x] Create `README.md` with badges, install instructions, feature overview
- [x] Set up CI: Ruff, mypy, pytest, coverage, HACS validation
- [x] Set up `pre-commit-config.yaml`
- [x] Initialize test structure (`tests/conftest.py`, `tests/__init__.py`)

## Milestone 2: Protocol — SHIP/SPINE transport

- [x] Capture real VR921 traffic (`SHIP_JSONL=true`) → test fixtures
- [x] Implement `vaillant/certificate.py` — self-signed X.509 cert generation, SKI extraction
- [x] Implement `vaillant/ship.py` — TLS WebSocket connection, SHIP handshake state machine, frame encoding
- [x] Implement `vaillant/spine.py` — SPINE datagram read/write, EEBUS JSON conversion
- [x] Implement `vaillant/discovery.py` — mDNS listener for `_ship._tcp.local.`, VR921 candidate tracking
- [x] Implement reconnect with exponential backoff
- [x] Unit tests for certificate generation
- [x] Unit tests for SPINE datagram parsing (from JSONL fixtures)
- [ ] Unit tests for SHIP handshake

## Milestone 3: Protocol — VR921 measurement reading

- [x] Implement VR921 entity tree discovery (nodeManagementDetailedDiscoveryData)
- [x] Identify Measurement server features per entity
- [x] Implement subscription (NodeManagementSubscriptionRequestCall)
- [x] Implement measurement parsing (measurementDescriptionListData + measurementListData)
- [x] Map SPINE measurement IDs to HA-friendly names + units
- [x] Implement poll fallback for non-subscribable measurements
- [x] Unit tests with JSONL capture fixtures
- [x] Integration test (local): full discovery → subscribe → read cycle tegen echte VR921
- [x] Build local daemon wrapper to keep one persistent VR921 session alive during development
- [x] Expose local debug API for cached state/descriptions/scopes

### Current proven scope coverage

- [x] Live: `acPowerTotal`
- [x] Live: `dhwTemperature`
- [x] Live: `roomAirTemperature`
- [x] Live: `outsideAirTemperature`
- [x] Described: `acCurrent`
- [x] Described: `acEnergyConsumed`
- [x] Described: `acEnergyProduced`
- [x] Described: `acFrequency`
- [x] Described: `acPower`
- [x] Described: `acVoltage`

### Next priority order

1. [ ] Install on real Home Assistant server and validate entities end-to-end
2. [ ] Add parsing/mapping/coordinator tests
3. [ ] Decide release scope for described-but-not-live measurements

## Milestone 4: HA Integration — Setup

- [x] Implement `__init__.py` — async_setup_entry, async_unload_entry
- [x] Implement `const.py` — DOMAIN, platform lists, defaults
- [x] Implement `config_flow.py`:
  - [x] mDNS discovery step
  - [x] Manual IP fallback step
  - [x] Connection test step
  - [ ] Options flow (update interval)
- [x] Implement `coordinator.py`:
  - [x] DataUpdateCoordinator wrapping VR921 client
  - [x] Heartbeat + reconnect
  - [x] State management (online/offline)
  - [ ] CoordinatorEntity base class
- [x] Implement `device.py` — DeviceInfo from VR921 discovery data (in coordinator.py)
- [ ] Test config flow with mock
- [ ] Test coordinator reconnect
- [ ] Test coordinator entity lifecycle

## Milestone 5: HA Integration — Entities

- [x] Implement `sensor.py`:
  - [x] AC current
  - [x] AC energy consumed
  - [x] AC energy produced
  - [x] AC frequency
  - [x] AC power
  - [x] AC voltage
  - [x] Outdoor temperature
  - [ ] Flow temperature
  - [ ] Return temperature
  - [x] DHW tank temperature
  - [x] Room temperature
  - [ ] Heating curve
  - [x] Compressor frequency
  - [ ] Compressor runtime
  - [x] Power consumption
  - [ ] Thermal output
  - [ ] COP
  - [ ] Energy today / total
  - [x] Water pressure
  - [ ] Error code
  - [ ] Firmware version
- [x] Implement `binary_sensor.py`:
  - [x] Compressor running
  - [ ] Heating active
  - [ ] Cooling active
  - [ ] Defrost active
  - [ ] Hot water active
  - [ ] Alarm
  - [ ] Internet connected
- [x] Implement `diagnostics.py`:
  - [x] Full data dump
  - [x] Redact sensitive info (certs, SKI, IPs)
- [x] Implement `strings.json` + `translations/` (English)
- [ ] Entity tests for each sensor type
- [ ] Snapshot test for diagnostics output

## Milestone 6: Polish

- [x] Create `docs/architecture.md` with C4 diagram
- [x] Create `docs/developer.md` — setup, testing, contributing
- [x] Create `docs/troubleshooting.md` — common issues
- [x] Create `docs/faq.md`
- [x] Create `examples/basic_dashboard.yaml`
- [x] Final README polish
- [x] Full Ruff compliance pass
- [ ] Full mypy strict pass
- [ ] Coverage report — target 90%+
- [ ] Tag v0.1.0 release

## Out of scope (Phase 2+)

- Subscriptions → real-time updates
- Climate platform → target temperature, quick veto
- Number platform → flow temperature, max compressor power
- Switch platform → hot water boost, holiday mode
- Select platform → operating modes
- Services → set_quick_veto, set_holiday, etc.
- Energy dashboard integration
