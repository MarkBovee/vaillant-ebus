# Proposal: Vaillant Heat Pump Local Integration

## What

A production-grade Home Assistant **custom integration** for Vaillant heat pumps. Uses the local eBUS interface (via ebusd) for full heat pump telemetry, with optional EEBUS (VR921) supplement for energy measurements.

## Why

Existing options:

| Approach | Problem |
|----------|---------|
| `mypyllant-component` (cloud API) | Quota limits, API incidents, internet required, lag, unstable |
| **EBUS via ebusd** | Extra hardware (€30 adapter), but gives COMPLETE heat pump data |
| **EEBUS (VR921) — our prototype** | Only 4 measurements — insufficient |

The EEBUS interface on the VR921 is an energy-management interface by design. It exposes only 4 live values (compressor power, 3 temperatures). Internal heat pump data (flow/return temp, pressures, valve positions, error codes) is only available via the internal eBUS.

**Decision pivot:** EEBUS → EBUS for comprehensive data. EEBUS code retained as optional supplement.

## How

### Architecture

```
Heat Pump
├── eBUS (2-wire serial) ──→ eBUS Adapter ──→ ebusd daemon ──TCP──→ HA built-in integration
└── EEBUS (VR921, optional) ──wss:12480────→ vaillant-eebus client ──→ custom component
```

### EBUS path (primary)
- ebusd daemon on HA server or Raspberry Pi
- €30 serial adapter (USB or GPIO)
- Built-in HA ebusd integration
- Full heat pump telemetry

### EEBUS path (supplement)
- Existing Python SHIP/SPINE implementation
- 4 energy measurements
- Optional, can be disabled if not needed

### Existing projects

| Project | Role |
|---------|------|
| **john30/ebusd** | Mature eBUS daemon, extensive Vaillant support |
| **markusschultheis/Vaillant-VR921** | Reference for VR921/EEBUS |
| **Our prototype (this repo)** | EEBUS SHIP/SPINE implementation, HA component |

### Current status

**EEBUS (proven, 4 measurements):**
- SHIP handshake, SPINE discovery, measurement subscriptions, poll fallback
- Live: `acPowerTotal`, `dhwTemperature`, `roomAirTemperature`, `outsideAirTemperature`
- Described but never live: 15 additional scopes (3-phase power/current/voltage, energy, frequency)
- Setpoint/HVAC write works (errorNumber: 0) but triggers no additional data
- ElectricalConnection: 16 parameters described, all scopeType=None, no values
- GitHub reference + Loxone investigation: same limitations confirmed

**EEBUS root cause:** The VR921 EEBUS interface is an energy-management gateway, not a heat pump diagnostic interface. It exposes only what the EEBUS HVAC UseCase defines. Internal heat pump parameters require the eBUS protocol.

### Next execution order (EBUS phase)

1. Purchase eBUS adapter (USB or GPIO)
2. Connect adapter to heat pump service port
3. Install and configure ebusd
4. Verify data via ebusd MQTT/HTTP
5. Integrate with Home Assistant (built-in integration)
6. Optionally: add EEBUS supplement for energy measurements
