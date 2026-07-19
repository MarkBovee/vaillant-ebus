# Design: Vaillant EEBUS Integration

## 1. Protocol Research

### 1.1 Read-back behaviour

**Observation:** `write_setpoint()` sends SPINE call with `setpointData`. VR921 returns errorNumber=0 via result. The state is NOT immediately reflected in any stored value.

**Evidence:**
- `write_setpoint()` at `vaillant/client.py:795-821` — sends call, returns `{"errorNumber": 0}`
- `notify` handler for `setpointData` at `vaillant/client.py:656-657` — logs only, does NOT store
- No subscription to the Setpoint server for read-back notify exists on the measurement data path

**Hypothesis:** The VR921 processes the call, updates its internal state, then sends a delayed `notify` with the new setpoint value. The notify IS received but never captured into `_latest_measurements`.

**Investigation needed — code inspection findings:**
1. `_receive_loop` at line 683-693 subscribes to Setpoint features via `subscribe_remote_feature`
2. `notify` with `setpointData` arrives (log confirmed at line 656-657) but the handler only logs
3. No `setpointData` entry is written to `_latest_measurements` — the parser has no code path for it
4. The `Setpoint` feature is NOT in the poll fallback loop (line 776 explicitly skips it)

**Conclusion:** Likely. The VR921 does send setpoint value notifications after a write. The integration simply discards them. Fix: add a `setpointData` parser that stores the value.

**Confidence:** Likely

**Remaining questions:**
- Does the VR921 always notify after a write, or only on demand?
- Is there a measurable delay between call result and notify?
- Does the notify include only the changed value or the full set?

### 1.2 Feature ID stability

**Observation:** Feature IDs (entity addresses and feature numbers) are discovered dynamically via `nodeManagementDetailedDiscoveryData`. The current code already discovers all server features by type in `_extract_servers_by_types()`.

**Evidence:**
- `discovery.py:136-165` — dynamically builds `{featureType: [{entity, feature}, ...]}` from live discovery data
- VR921 returns consistent IDs across reconnects (observed empirically)

**Hypothesis:** Feature IDs are assigned by the VR921 firmware and are stable across sessions. They may change on firmware updates. The integration must always discover them dynamically.

**Conclusion:** Confirmed. The protocol layer already discovers dynamically. The problem is that the HA layer (`number.py`, `select.py`, `sensor.py`) hardcodes entity values like `[4]` (DHW) and `[5, 1, 1]` (HVAC room) instead of matching by entity type.

**Confidence:** Confirmed

**Remaining questions:**
- Can entity IDs change between VR921 reboots (without firmware change)?
- Is there a documented range of entity IDs per VR921 firmware version?

### 1.3 Subscription lifecycle

**Observation:** Subscriptions are created once after discovery. On reconnect, the entire lifecycle starts fresh.

**Evidence:**
- `_receive_loop` lines 666-717: subscribes after `peer_use_case_received` and measurements discovered
- Reconnect calls `_run()` fresh, so `_receive_loop` restarts with clean state
- No persistent subscription tracking across reconnects

**Hypothesis:** The VR921 does not persist subscriptions across WebSocket disconnects. Re-subscription after reconnect is always required. The current full re-discovery + re-subscribe flow is correct.

**Conclusion:** Likely. Current behaviour (re-subscribe on every connect) is the safe approach.

**Confidence:** Likely

**Remaining questions:**
- Are there NOTIFY-capable features we are NOT subscribing to that we should?
- Does the VR921 support subscription to all server features, or only Measurement?
- Subscription count limit on VR921?

### 1.4 Unknown packet handling

**Observation:** Unhandled reply/notify commands are logged at DEBUG level. No structured storage for unknown packets.

**Evidence:**
- `_receive_loop` line 626-627: `_LOGGER.debug("Unhandled reply cmd=%s: %s", cmd_name, str(cmd)[:200])`
- Same pattern for notify at line 663-664
- Raw packets are not stored for later analysis

**Conclusion:** Confirmed. Unknown packets are silently discarded. This is acceptable for production but blocks reverse engineering progress.

**Confidence:** Confirmed

**Remaining questions:**
- What commands are currently unknown?
- Are any unknown commands critical for write operations?

### 1.5 Setpoint/hvac write confirmation

**Observation:** `write_setpoint` and `write_hvac_mode` are implemented but the HA number/select platforms do NOT read back current values from the VR921.

**Evidence:**
- `number.py:50-52` — `native_value` returns `self._value` (locally stored, never synced from VR921)
- `select.py:50-51` — `current_option` returns `self._value` (locally stored)
- On coordinator refresh, number/select values are NOT updated from VR921 state
- The setpoint notify handler only logs (see 1.1)

**Conclusion:** Confirmed. The number and select platforms are write-only. They have no read-back path.

**Confidence:** Confirmed

**Remaining questions:**
- Can setpoint values be read via `setpointData` read request?
- Does the VR921 notify setpoint changes spontaneously?

### 1.6 Empirical VR921 data availability

**Observation:** Of 19 described measurement IDs, only 4 return live values through the standard EEBUS measurement path. 16 ElectricalConnection parameters are described but lack scopeType/unit, making them unusable.

**Evidence (live VR921 captures):**
- 19 measurement IDs described with scopeTypes: acCurrent(×3), acPower(×2), acPowerTotal, acEnergyConsumed, acEnergyProduced, acFrequency, acVoltage, dhwTemperature, roomAirTemperature, outsideAirTemperature
- Only 4 live: acPowerTotal (6W), dhwTemperature (31°C), roomAirTemperature (22.5°C), outsideAirTemperature (20.5°C)
- 15 remaining measurement IDs: never produce a value, always skipped (no parsable value)
- 16 EC parameters described: all lack scopeType AND unit — cannot be mapped to sensors
- `electricalConnectionParameterListData` read: returns no response (same as Setpoint/HVAC reads that are not subscribed)

**Hypothesis:** The VR921 only publishes values that are actively changing or that the connected heat pump pushes. Static/rarely-changing values (acCurrent, acVoltage, acFrequency, acEnergy) are never sent via EEBUS measurement notify. They may be accessible through a different EEBUS path or require a different subscription type.

**Conclusion:** Confirmed. The VR921's EEBUS interface is limited. Direct EEBUS measurement subscriptions yield only 4 live values from the specific VR921 + heat pump combination tested. Other heat pump models or VR921 firmware versions may expose more.

**Confidence:** Confirmed

**Remaining questions:**
- Do other heat pump models (different from the test unit) expose more measurements?
- Is there an alternative EEBUS data path (not measurementListData) for the missing values?
- Does the Loxone integration use a different subscription/setup to access these values?
- Would polling at a different frequency trigger value publication?

### 1.7 Loxone integration alternative path

**Observation:** The Loxone Vaillant integration uses the same EEBUS SHIP/SPINE protocol as our implementation. Loxone Config discovers the VR921 via mDNS (`_ship._tcp.local.`), connects via TLS WebSocket on port 12480, and uses the same SHIP handshake + SPINE datagram exchange.

Loxone supports the EEBUS HVAC UseCase which provides:
- Monitoring of Power Consumption (MPC) — `acPowerTotal`
- Monitoring of DHW Temperature (MDT) — `dhwTemperature`
- Monitoring of Room Temperature (MRT) — `roomAirTemperature`
- Monitoring of Outdoor Temperature (MOT) — `outsideAirTemperature`

**Conclusion:** Loxone receives the same limited measurement set. The EEBUS protocol over VR921 only exposes these 4 measurement values regardless of the client implementation. Loxone is not a viable alternative path for additional heat pump data.

**Confidence:** Confirmed (Loxone public documentation + community reports)

### 1.8 EEBUS Empirical Conclusion (end of Phase 1)

**Summary:** After extensive testing against a live VR921, the EEBUS SHIP/SPINE interface on the VR921 gateway provides exactly 4 live measurement values and 19 described measurement IDs. The remaining 15 described scopes (3-phase power, current, voltage, frequency, energy) never produce values — neither via subscription notify nor via poll fallback.

**Proven live measurements:**
| Scope | Entity | Feature | Value range |
|-------|--------|---------|-------------|
| `acPowerTotal` | Compressor [3,1] | Measurement f11 | 21–420 W |
| `dhwTemperature` | DHWCircuit [4] | Measurement f11 | 48°C |
| `roomAirTemperature` | HVACRoom [5,1,1] | Measurement f11 | 22°C |
| `outsideAirTemperature` | TemperatureSensor [6] | Measurement f11 | 20–21°C |

**Described but never live (confirmed after 120s capture with writes):**
- 3-phase `acCurrent` (IDs 0–2) — described with scopeType + unit, never notifies
- `acEnergyConsumed` (ID 3) — described, never notifies
- `acEnergyProduced` (ID 4) — described, never notifies
- `acFrequency` (ID 5) — described, never notifies
- 3-phase `acPower` (IDs 6–8) — described, never notifies
- 5-phase `acVoltage` (IDs 10–15) — described, never notifies

**What we tried that did NOT produce additional data:**
1. Subscription to all Measurement server features — only 4 notify
2. Poll fallback every 10s — same 4 values returned
3. Setpoint write (DHW 40°C + HVAC room 40°C) — accepted (errorNumber: 0), no new data triggered
4. HVAC mode write (comfort) — accepted, no new data triggered
5. ElectricalConnection subscribe + poll — 16 parameters described, all scopeType=None, no values
6. DeviceClassification read — 10 reads sent, responses unhandled
7. Generic features (entity [1] f1, [2] f1) — client role, no server to read
8. GitHub reference project (markusschultheis/Vaillant-VR921) — same 4 values
9. Loxone library research — same protocol, same 4 values

**Root cause:** The EEBUS interface on the VR921 is an energy-management interface by design. It exposes only what EEBUS defines for the HVAC UseCase (power, temperatures). Internal heat pump parameters (flow/return temperature, gas pressure, compressor frequency, valve positions, defrost status, etc.) are NOT available via EEBUS — they are accessible only through the heat pump's internal eBUS (a different protocol on a 2-wire serial bus).

**The myVaillant app** accesses additional data through the Vaillant cloud API (REST over internet), not through local EEBUS. The VR921 connects to Vaillant cloud servers; the app connects to the same cloud. The cloud API exposes far more parameters than the local EEBUS interface.

### 1.9 EBUS Alternative Path

**Observation:** Vaillant heat pumps have two independent communication buses:
- **EEBUS (VR921)** — network gateway, energy-management focused, 4 measurements
- **eBUS** — internal 2-wire serial bus, full heat pump telemetry

The eBUS carries all internal sensor data: flow temperature, return temperature, compressor frequency, fan speed, expansion valve position, pressure, gas usage, error codes, etc. This is the data we need.

**Existing solution:** ebusd (https://ebusd.eu) — open-source daemon that speaks the eBUS protocol via a €30 serial adapter. Supports Vaillant heat pumps extensively. Publishes data via MQTT.

**Project:** https://github.com/john30/ebusd

**HA integration:** Home Assistant has a built-in ebusd integration that connects over TCP/IP to a running ebusd instance. The ebusd daemon can run on the same machine as HA.

**Architecture:**
```
Heat Pump ←─eBUS 2-wire──→ eBUS Adapter ←─USB──→ ebusd (daemon) ←─TCP──→ HA (ebusd integration)
```

**Compared to EEBUS approach:**
| Aspect | EEBUS (current) | EBUS (proposed) |
|--------|-----------------|-----------------|
| Hardware | VR921 gateway (included) | eBUS adapter (€30) |
| Data | 4 measurements | Full heat pump telemetry |
| Protocol | TLS WebSocket, complex | Serial, mature |
| HA integration | Custom component | Built-in |
| Cloud dependency | No | No |
| Setup | Network config | USB/serial config |

**Decision:** Pivot from EEBUS to EBUS for comprehensive heat pump monitoring. The EEBUS protocol code continues to provide value for the 4 energy measurements; the EBUS path provides the full dataset.

**Remaining questions:**
- Which specific eBUS adapter to use (Raspberry Pi GPIO vs USB vs ESP32)?
- Does the eBUS need to share the heat pump's service port with the VR921?
- What is the exact pinout for the aroTHERM plus / VWL series?
- Can ebusd run on the same HA server, or does it need a dedicated device?

## 2. Repository structure

```
vaillant-eebus/
├── custom_components/
│   └── vaillant_eebus/
│       ├── __init__.py          # HA component setup, async_setup_entry
│       ├── manifest.json        # domain, version, requirements, dependencies
│       ├── config_flow.py       # ConfigFlow with mDNS discovery
│       ├── const.py             # DOMAIN, platform lists, defaults
│       ├── coordinator.py       # DataUpdateCoordinator + SHIP client
│       ├── device.py            # DeviceInfo helper
│       ├── sensor.py            # SensorEntity descriptions
│       ├── binary_sensor.py     # BinarySensorEntity descriptions
│       ├── diagnostics.py       # Diagnostics support
│       ├── strings.json         # Translations en
│       └── translations/        # Additional translations
├── vaillant/
│   ├── __init__.py
│   ├── const.py                 # EEBUS protocol constants
│   ├── certificate.py           # Self-signed cert generation, SKI extraction
│   ├── ship.py                  # SHIP transport: TLS WebSocket, handshake, frames
│   ├── spine.py                 # SPINE datagram: read, write, subscribe, notify
│   ├── discovery.py             # Entity tree discovery parsing
│   ├── measurement.py           # Measurement server subscription + parsing
│   ├── model.py                 # Capability dataclasses + registry (planned)
│   └── client.py                # Persistent VR921 client state machine
├── tools/
│   ├── recorder.py              # Session recorder (planned)
│   └── replay.py                # Session replay for testing (planned)
├── scripts/
│   ├── daemon.py                # Persistent local debug daemon + HTTP API
│   └── test_local.py            # HA lifecycle simulator / capture wrapper
├── docs/
│   ├── architecture.md
│   ├── developer.md
│   ├── troubleshooting.md
│   └── faq.md
├── examples/
│   └── basic_dashboard.yaml
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Fixtures, JSONL capture replay, optional mock
│   ├── test_coordinator.py
│   ├── test_discovery.py
│   ├── test_measurement.py
│   ├── test_certificate.py
│   ├── test_config_flow.py
│   └── test_sensor.py
├── .github/
│   └── workflows/
│       ├── ci.yml               # Ruff, pytest, mypy, coverage
│       └── hacs.yml             # HACS validation
├── hacs.json
├── pyproject.toml
├── requirements.txt             # Runtime deps
├── requirements_test.txt        # Test deps
├── README.md
├── LICENSE
└── .pre-commit-config.yaml
```

## 3. EEBUS / VR921 Protocol Details

### Discovery
- VR921 announces itself via mDNS as `_ship._tcp.local.`
- Contains SKI (Subject Key Identifier) in TXT record
- Port 443 (TLS WebSocket)

### Connection
1. Generate self-signed X.509 client certificate
2. Extract SKI from certificate (=local identity)
3. Connect via `wss://<vr921-ip>:443/ship/`
4. SHIP handshake: CMI Init → HELLO (pending/ready) → protocol negotiation → PIN=none → access methods
5. First pairing requires trust confirmation in myVaillant app (HELLO phase=pending)

### SPINE data model (VR921)

The VR921 exposes a tree of entities with features:

```
Device (VR921 Gateway)
├── entity=0  Device Information
├── entity=3  HeatPump Appliance
│   ├── entity=3,1  Compressor
│   │   └── feature=11  Measurement (power, energy)
│   │   └── feature=19  SmartEnergy (PV optimization)
├── entity=4  DHW Circuit
│   └── feature=11  Measurement (tank temp, setpoint)
│   └── feature=18  Setpoint (target temp)
├── entity=5,1,1  HVAC Room / Heating Circuit
│   └── feature=11  Measurement (room temp)
│   └── feature=18  Setpoint (target temp)
└── entity=6  Temp Sensor (outdoor)
    └── feature=11  Measurement (outdoor temp)
```

### Measurement flow
1. Discover remote entities via `nodeManagementDetailedDiscoveryData`
2. Find features with `featureType=11` (Measurement server)
3. Subscribe via `NodeManagementSubscriptionRequestCall`
4. Receive periodic `notify` datagrams with `measurementListData`
5. Optionally poll via `measurementDescriptionListData` + `measurementListData`

### Proven scope inventory (current capture state)

Live values observed:
- `acPowerTotal`
- `dhwTemperature`
- `roomAirTemperature`
- `outsideAirTemperature`

Described by VR921, but not yet observed with live value in current capture:
- `acCurrent`
- `acEnergyConsumed`
- `acEnergyProduced`
- `acFrequency`
- `acPower`
- `acVoltage`

Implication:
- The protocol path for discovery, descriptions, and subscriptions is working.
- Remaining work is mainly in poll fallback and broader HA entity mapping, not basic connectivity.
- The next meaningful validation step is a real Home Assistant installation against the live VR921.

## 4. HA Integration Pattern

### Config Flow
- Step 1: mDNS discovery (auto-detected VR921 gateways)
- Step 2: Manual IP/hostname fallback
- Step 3: Connection test (handshake + discovery)
- Step 4: Confirmation + install

### Coordinator
- `DataUpdateCoordinator[Vr921Client]`
- Holds the SHIP WebSocket connection
- Manages reconnect with exponential backoff
- Heartbeat to detect stale connection
- Subscribes to SPINE measurements
- Polls only for non-subscribable values
- Updates `async_add_listener` entities

### Development daemon
- Separate long-lived process for local development
- Keeps one EEBUS certificate/session alive to reduce repeated trust prompts
- Caches:
  - `device_info`
  - `measurement_descriptions`
  - `latest_measurements`
- Exposes local HTTP endpoints:
  - `/health`
  - `/state`
  - `/descriptions`
  - `/scopes`
- Lets wrappers and future UI/debug tools restart without reconnecting VR921 every edit
- Serves as the preferred local development target while the HA integration is still evolving

### Entities
- All entities use `CoordinatorEntity` pattern
- `EntityDescription` for type-safe configuration
- `unique_id` derived from VR921 SKI + entity/feature + measurement ID
- Device registry with VR921 as main device
- Entity registry for persistent identity

### Naming convention
- `sensor.vaillant_outdoor_temperature`
- `binary_sensor.vaillant_compressor_running`
- Domain prefix `vaillant_`

## 5. Error handling

| Scenario | Behavior |
|----------|----------|
| Gateway offline | Coordinator marks entities unavailable, retry with backoff |
| Connection reset | Auto-reconnect with exponential backoff (1s, 2s, 4s, … max 5min); daemon should preserve cached state during reconnect |
| Malformed packet | Log at DEBUG, discard, continue |
| Protocol version mismatch | Log error, raise ConfigEntryNotReady |
| Authentication failure | Re-pairing required, raise exception with repair suggestion |
| Certificate expiry | Generate new, trigger re-pairing |
| Timeout | Retry 3x, then disconnect + reconnect |

## 6. Test Strategy

### Approach
- **Real VR921** for development and E2E validation (local dev only)
- **JSONL captures** (`SHIP_JSONL=true`) as CI test fixtures — capture once, replay forever
- **Unit tests** for certificate, SPINE parsing, measurement mapping — no network needed
- **Mock server** optional, only if CI needs reproducible integration tests
- **Persistent daemon** for local dev — stable session, capture state via local HTTP without repeated pairing prompts

### Fixture pipeline
1. Run against real VR921 with `SHIP_JSONL=true`
2. Sanitize captures (redact certs, SKI, IPs)
3. Store as `tests/fixtures/*.jsonl`
4. Replay in CI tests

### Coverage target
- Unit: 95%+ for certificate, parsing, mapping
- Integration: full discovery → subscribe → read cycle
- No E2E in CI (requires physical hardware)

### Immediate implementation priorities
1. Real Home Assistant install validation
2. Fix runtime issues found during HA setup/config-entry flow
3. Tests for JSONL replay and coordinator behavior
4. Decide release scope for described-but-not-live measurements

## 7. Security
- All communication over TLS (wss://)
- Self-signed certificates (EEBUS standard)
- No cloud dependency — data stays local
- Diagnostics redacts: certificates, private keys, SKI, IPs
- Unique IDs are deterministic (based on SKI + measurement path), not random

## 7. Capability Model

### Problem statement

The current integration has no explicit capability model. Features are discovered dynamically at the protocol layer but the HA layer hardcodes specific entity addresses and scope types. This creates:

- Duplicate parsing logic between `vaillant.client` and `custom_components`
- Hardcoded feature IDs that break on different VR921 firmware or device types
- No single source of truth for what a device supports

### Proposed model

A `Capability` is the atomic unit of device interaction:

```python
@dataclass
class Capability:
    # Protocol address
    device_address: str
    entity: list[int]
    feature: int
    feature_type: str           # "Measurement", "Setpoint", "HVAC", etc.
    role: str                   # "server" | "client"

    # Function metadata
    supported_commands: list[str]  # ["measurementListData", "setpointData", ...]
    supported_use_cases: list[str] # from nodeManagementUseCaseData

    # Value metadata (populated from descriptions)
    scope_type: str | None = None
    unit: str | None = None
    measurement_type: str | None = None
    parameter_id: int | None = None

    # State
    value: Any = None
    last_updated: float = 0.0
```

### Capability Registry

A `CapabilityRegistry` collects all discovered capabilities at startup:

```
discovery → _extract_servers_by_types() → list of raw feature dicts
         ↓
CapabilityRegistry.register(feature)   → wraps each in Capability object
         ↓
CapabilityRegistry.load_descriptions() → enriches with measurement/electrical descriptions
         ↓
CapabilityRegistry.subscribe_all()     → subscribes to every NOTIFY-capable server
         ↓
CapabilityRegistry.update_value()      → pushes live values from notify/reply
```

### Why this becomes the single source of truth

- Feature discovery produces capabilities → HA entity generation reads from registry
- No hardcoded entity IDs — all matching is by `entityType` or `featureType`
- Unknown features get a `Capability` too (with `supported_commands=[]`) → visible in diagnostics
- Subscription decisions are data-driven: every server feature gets auto-subscribed
- Poll fallback operates on all measurement capabilities, not a hardcoded list

### Relationship to Home Assistant entities

```
CapabilityRegistry
  ├── scope_type="outsideAirTemperature" → sensor (temperature)
  ├── scope_type="roomAirTemperature"    → sensor (temperature) × entity [5,1,1]
  ├── feature_type="Setpoint"             → number entity
  ├── feature_type="HVAC"                 → select entity
  ├── compressor_running                  → binary_sensor (computed)
  └── unknown_feature                     → diagnostic entity
```

## 8. Recorder / Replay Framework

### 8.1 Recorder (`tools/recorder.py`)

Purpose: capture complete SHIP/SPINE sessions to file for later analysis and replay.

### Storage format

JSONL (one JSON object per line). Raw wire format preserved.

```jsonl
{"ts": 1234567890.123, "dir": "rx", "type": "ship_control", "payload": {"connectionHello": {...}}}
{"ts": 1234567890.456, "dir": "tx", "type": "ship_data", "payload": {"datagram": {...}}}
{"ts": 1234567890.789, "dir": "rx", "type": "ship_data", "payload": {"datagram": {...}}}
```

### Captured events

| Event | Type | Fields |
|-------|------|--------|
| SHIP control message | `ship_control` | direction, raw payload |
| SHIP data message | `ship_data` | direction, raw payload |
| Connection open | `connection_open` | host, port, timestamp |
| Connection close | `connection_close` | reason, code |
| Handshake phase | `handshake_phase` | phase name |
| Discovery result | `discovery` | parsed entities + features |
| Subscription request | `subscription` | feature address, type |
| Measurement notify | `measurement` | parsed scope/value |
| Write call | `write_call` | feature, command, value |
| Error | `error` | message, traceback |

### Implementation approach

Add a `SessionRecorder` class that hooks into `VaillantClient`:

```python
class SessionRecorder:
    def __init__(self, path: str): ...
    def record_rx(self, raw_bytes: bytes): ...   # before parsing
    def record_tx(self, raw_bytes: bytes): ...   # before sending
    def record_event(self, event_type: str, data: dict): ...
    def close(self): ...
```

Hooks in `VaillantClient`:

- `_run()` → `recorder.record_event("connection_open", ...)`
- WebSocket `recv()` → `recorder.record_rx(data)` before parsing
- `send_ship_json`/`send_ship_data` → `recorder.record_tx(bytes)` before sending
- Discovery parsed → `recorder.record_event("discovery", ...)`
- Measurement parsed → `recorder.record_event("measurement", ...)`

### 8.2 Replay (`tools/replay.py`)

Purpose: replay recorded sessions without a physical VR921. Enables deterministic testing and regression detection.

### Capabilities

- Play back discovery, notifications, writes, replies in correct order with original timing
- Simulate disconnects and reconnects at recorded timestamps
- Inject synthetic delays for timeout testing
- Validate that the integration produces the same state from the same input

### Architecture

```python
class SessionReplay:
    def __init__(self, path: str): ...
    def __aiter__(self): ...  # yields (timestamp, direction, type, payload)
    def reconnect_at(self, ts: float): ...  # schedule disconnect/reconnect
```

The replay replaces the WebSocket transport:

```
VaillantClient
  ws.recv()  →  SessionReplay.next_rx()
  ws.send()  →  SessionReplay.record_tx() + compare to expected
```

### Testing integration

Replay enables:

- **Parser tests**: feed raw capture to parser, verify output
- **Discovery tests**: feed discovery data, verify entity/feature tree
- **Subscription tests**: feed subscription flow, verify subscribe calls match expected
- **Write tests**: feed write + notify sequence, verify state updates
- **Regression tests**: compare integration state from capture to reference output

## 9. Testing Strategy

### 9.1 Replay-based tests (primary)

Replace unit-level mocking with full-session replay:

```python
async def test_full_session():
    async with SessionReplay("tests/fixtures/session-001.jsonl") as replay:
        client = VaillantClient()
        await client.run_with_transport(replay)
        assert client.latest_measurements["outsideAirTemperature"]["value"] == 8.5
```

Benefits:

- No mocking — real code path, recorded data
- Deterministic — same capture always produces same state
- Hardware-free — CI runs without VR921
- Regression detector — capture changes signal protocol changes

### 9.2 Parser tests

- `test_measurement_description_parser()` — feed raw `measurementDescriptionListData`, verify scope/unit extraction
- `test_measurement_list_parser()` — feed raw `measurementListData`, verify value extraction
- `test_electrical_connection_parser()` — feed EC parameter lists, verify parameter extraction
- `test_spine_datagram_parser()` — feed EEBUS JSON, verify header/cmd extraction

### 9.3 Discovery tests

- `test_discovery_entity_extraction()` — feed discovery payload, verify entity tree
- `test_discovery_feature_extraction()` — feed discovery payload, verify feature type grouping
- `test_discovery_measurement_servers()` — verify only Measurement servers selected
- `test_discovery_setpoint_servers()` — verify Setpoint servers selected

### 9.4 Capability generation tests

- `test_capability_from_discovery()` — verify `CapabilityRegistry` produces correct entries
- `test_capability_subscription_selection()` — verify NOTIFY-capable features identified
- `test_capability_value_update()` — verify value propagation through registry

### 9.5 Dynamic entity tests

- `test_entity_generation_from_capabilities()` — feed capabilities, verify correct HA entities created
- `test_unique_id_generation()` — verify deterministic unique_id from capability address
- `test_entity_deduplication()` — verify single entity per unique capability

### 9.6 Subscription tests

- `test_subscription_lifecycle()` — capture → replay → verify subscribe calls match expected
- `test_reconnect_resubscribe()` — replay with disconnect/reconnect, verify re-subscription
- `test_notify_processing()` — replay notifications, verify values stored

### 9.7 Regression tests

- Create reference captures from known-good sessions
- After any change, replay all captures, verify output matches reference
- Capture naming convention: `session-{date}-{description}.jsonl`
- Reference output: `tests/fixtures/session-{name}-expected.json`

### 9.8 Test infrastructure

```
tests/
├── conftest.py              # SessionReplay fixture, fixture loader
├── fixtures/
│   ├── session-001.jsonl    # Full discovery + measurement session
│   ├── session-002.jsonl    # Write setpoint + notify back
│   └── session-003.jsonl    # Reconnect scenario
├── test_discovery.py        # Discovery parsing tests
├── test_measurement.py      # Measurement parsing tests
├── test_capability.py       # Capability registry tests
├── test_sensor.py           # HA sensor entity tests
├── test_coordinator.py      # Coordinator lifecycle tests
├── test_replay.py           # Replay framework tests
└── test_regression.py       # Full-session regression tests
```

## 10. Dynamic Entity Generation

### Current state

Entities are created from hardcoded scope types (`SCOPE_TYPE_MAP` in `sensor.py`). Each known scope type produces exactly one sensor, regardless of which entity it belongs to.

```python
# Current: scope-to-entity mapping is implicit and lossy
for scope, meta in coordinator.measurement_scopes.items():
    if scope not in seen:
        entities.append(VaillantSensor(coordinator, scope, meta, entry))
```

Problems:
- Two rooms with `roomAirTemperature` → only one sensor created (dedup by scope name)
- Entity origin is lost — sensor can't distinguish "DHW temperature" from "Room temperature"
- New scope types require code change to `SCOPE_TYPE_MAP`
- Electrical connection parameters are not surfaced as sensors

### Proposed: capability-driven entity generation

```
CapabilityRegistry
  └── for each Capability:
       ├── scope_type + entity_address → unique_id
       ├── feature_type → platform (sensor/number/select)
       └── unit/scope_type → device_class

Capability → SensorEntityDescription
  ├── unique_id = f"{ski}_{entity}_{feature}_{measurement_id}"
  ├── name = f"{entity_type} {friendly_scope_name}"
  ├── device_class = guess from scope_type/unit
  └── native_unit_of_measurement = unit
```

### Benefits

- New VR921 firmware with new scope types → automatically appears in HA
- Multiple rooms with same scope type → separate entities per entity address
- Entity origin transparent in unique_id
- Electrical connection parameters become sensors automatically
- No code changes needed for new measurement types

### Migration strategy

1. Add `Capability` dataclass and `CapabilityRegistry` to `vaillant/`
2. Populate registry during discovery in `VaillantClient`
3. Add dynamic sensor generation in `coordinator.py`
4. Keep `SCOPE_TYPE_MAP` as fallback for friendly names + device class hints
5. Migrate `unique_id` format — HA entity registry handles renames
6. Remove hardcoded entity matching in `number.py` / `select.py` — match by entity type instead
7. Phase out `SCOPE_TYPE_MAP` in favor of generic metadata guesser

### Limitations

- Some scope types need human-friendly names — solved by lookup map with fallback
- Computed binary sensors (compressor_running) must still be manually defined
- Scope types without units/device class mapping get generic sensor type

## 11. Unknown Features Strategy

### Problem

New VR921 firmware versions or different heat pump models may expose features the integration has never seen. Unknown packets must never crash the integration.

### Design

**Protocol layer (`vaillant/`):**

```python
class UnknownFeatureRegistry:
    """Stores unknown features and packets for analysis."""
    features: dict[str, list[dict]]  # feature_type → raw discovery entries
    unknown_commands: list[dict]     # raw cmd payloads not handled
    last_unknown: str | None         # last unknown cmd name for logging
```

- Every unhandled command in the receive loop stores raw payload in `unknown_commands`
- Every feature from discovery that isn't in our known feature type list goes to `features`
- Stored with direction, timestamp, and parsed header context
- Capped at N entries to prevent memory leak

**HA layer:**

- Unknown features exposed as diagnostic sensor: `sensor.vaillant_unknown_feature_x`
- Unknown command count as a diagnostic entity for monitoring
- Configurable flag: `log_unknown_packets` (default: True in debug mode)

**Reverse engineering workflow:**

1. Connect with `log_unknown_packets=True`
2. Check `/state` or HA diagnostics for unknown feature list
3. Extract unknown packet payloads from diagnostics download
4. Add parser, update known feature types, re-test

### Implementation

```python
class VaillantClient:
    def __init__(self, ...):
        self.unknown_features = UnknownFeatureRegistry(capacity=100)

    # In _receive_loop:
    except KeyError:
        self.unknown_features.record(cmd_name, hdr, cmd, direction="rx")
```

## 12. Multi-device Architecture

### Protocol layer is already generic

The EEBUS SHIP/SPINE transport (`ship.py`, `spine.py`) has no Vaillant-specific code. These modules already handle any EEBUS device.

### Vaillant-specific layer

`discovery.py` and `measurement.py` have implicit Vaillant assumptions:

- Entity type names (`HeatPumpAppliance`, `DHWCircuit`, `HVACRoom`) are EEBUS standard types, not Vaillant-specific
- Measurement scope types (`acPowerTotal`, `dhwTemperature`) are EEBUS-standard scope type strings
- The entity tree structure (entity=3 = HeatPump, entity=4 = DHW, etc.) is VR921-specific

### Manufacturer abstraction

```
vaillant/                    # Manufacturer-independent protocol
├── ship.py                  # Generic SHIP transport
├── spine.py                 # Generic SPINE datagram
├── const.py                 # EEBUS constants (not Vaillant-specific)
├── client.py                # Generic EEBUS session manager
├── discovery.py             # Generic EEBUS discovery parser
├── measurement.py           # Generic measurement parser
├── certificate.py           # Generic cert generation
└── model.py                 # Capability dataclasses

vaillant/vendor/             # Manufacturer-specific
├── __init__.py
├── vaillant.py              # Vaillant entity type map, supported features
└── saunier_duval.py         # Saunier Duval overrides (if different)

custom_components/vaillant_eebus/     # HA for Vaillant
custom_components/saunier_duval_eebus/ # HA for Saunier Duval (future)
```

### What would need to change for another brand

- Entity type mapping (same EEBUS standard types, different device)
- Brand name, model strings
- Possibly different scope types (rare — EEBUS standardizes these)
- Different feature discovery patterns (if any)

The protocol layer stays unchanged. The HA layer adds a new integration pointing to the same protocol code. Saunier Duval uses the same VR921 hardware with different branding — likely identical protocol behavior.

## 13. Technical Debt — Current Implementation Issues

### Hardcoded Feature IDs

| Location | Issue | Fix |
|----------|-------|-----|
| `vaillant/client.py:49-57` | `FEATURE_READ_CMDS` hardcodes command names by feature type | Move to capability model |
| `custom_components/__init__.py:22-21` | Hardcoded entity `[4]` for DHW | Match by entity type "DHWCircuit" |
| `custom_components/__init__.py:31-32` | Hardcoded entity `[5,1,1]` for HVAC | Match by entity type "HVACRoom" |
| `custom_components/sensor.py:20-69` | `SCOPE_TYPE_MAP` hardcodes 12 scope types | Replace with dynamic generation |
| `custom_components/number.py:24` | Hardcoded entity `[4]` for DHW setpoint | Match by entity type |
| `custom_components/select.py:26` | Hardcoded entity `[5,1,1]` for HVAC mode | Match by entity type |
| `custom_components/binary_sensor.py:29-32` | Hardcoded scope name checks | Make generic |

### Feature-specific assumptions

| Location | Issue | Severity |
|----------|-------|----------|
| `sensor.py:124-127` | Dedup by scope name only — loses entity identity | High |
| `coordinator.py:96-113` | `measurement_scopes` loses entity/feature context | High |
| `binary_sensor.py:23-33` | Scans ALL measurements for specific scope names | Medium |
| `client.py:851-887` | `_process_measurement_updates` makes object_id from scope+address but HA ignores address | High |
| `client.py:119-132` | `_guess_ha_metadata` in protocol layer — should be in HA layer | Low |

### Tight coupling

| Location | Issue | Fix |
|----------|-------|-----|
| `coordinator.py:18` | Imports `_unit_to_ha` from `vaillant.client` | Move to shared helper or const |
| `client.py:119-132` | `_guess_ha_metadata` — protocol code knows about HA concepts | Move to HA layer |
| `__init__.py:49-53` | Certificate path hardcoded to cwd | Use HA config path |

### Missing abstractions

| Gap | Impact | Priority |
|-----|--------|----------|
| No `Capability` model | Every layer re-parses raw dicts | High |
| No `CapabilityRegistry` | Subscription, poll, and entity gen are ad-hoc | High |
| No feature address type | Entity+feature passed as raw dicts/tuples | Medium |
| No typed measurement value | Values are `Any` through entire chain | Medium |

### Scalability concerns

| Concern | Why |
|---------|-----|
| Single coordinator, single client | Cannot support multiple VR921s on one HA instance |
| `_latest_measurements` flat dict | Loses entity structure, hard to debug |
| No subscription state tracking | Cannot know if subscription is active |
| Poll loop in receive loop coroutine | Cannot manage poll independently from message processing |
