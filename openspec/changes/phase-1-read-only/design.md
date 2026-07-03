# Design: Vaillant EEBUS Integration

## 1. Repository structure

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
│   ├── const.py                 # Vaillant entity/feature IDs, measurement IDs
│   ├── certificate.py           # Self-signed cert generation, SKI extraction
│   ├── ship.py                  # SHIP transport: TLS WebSocket, handshake, frames
│   ├── spine.py                 # SPINE datagram: read, write, subscribe, notify
│   ├── discovery.py             # Entity tree discovery parsing
│   ├── measurement.py           # Measurement server subscription + parsing
│   └── client.py                # Persistent VR921 client state machine
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

## 2. EEBUS / VR921 Protocol Details

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

## 3. HA Integration Pattern

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

## 4. Error handling

| Scenario | Behavior |
|----------|----------|
| Gateway offline | Coordinator marks entities unavailable, retry with backoff |
| Connection reset | Auto-reconnect with exponential backoff (1s, 2s, 4s, … max 5min); daemon should preserve cached state during reconnect |
| Malformed packet | Log at DEBUG, discard, continue |
| Protocol version mismatch | Log error, raise ConfigEntryNotReady |
| Authentication failure | Re-pairing required, raise exception with repair suggestion |
| Certificate expiry | Generate new, trigger re-pairing |
| Timeout | Retry 3x, then disconnect + reconnect |

## 5. Test Strategy

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

## 6. Security
- All communication over TLS (wss://)
- Self-signed certificates (EEBUS standard)
- No cloud dependency — data stays local
- Diagnostics redacts: certificates, private keys, SKI, IPs
- Unique IDs are deterministic (based on SKI + measurement path), not random
