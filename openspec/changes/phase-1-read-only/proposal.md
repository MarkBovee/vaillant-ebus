# Proposal: Vaillant EEBUS Local Integration

## What

A production-grade Home Assistant **custom integration** (HACS) for Vaillant heat pumps using the local EEBUS interface on the VR921 (sensoNET) gateway. Read-only in Phase 1, write support in later phases.

No cloud dependency. No addon/bridge container.

## Why

Existing options:

| Approach | Problem |
|----------|---------|
| `mypyllant-component` (cloud API) | Quota limits, API incidents, internet required, lag |
| `ebusd` + hardware adapter | Extra hardware, eBUS (different protocol), serial |
| `CoreTex/homeassistant-eebus` (Go addon) | HAOS-only, 2 components to maintain, overkill |

A pure Python EEBUS integration solves all of these: local, low-latency, no extra infra, works on all HA install types.

## How

### Architecture

```
┌──────────┐  EEBUS/SHIP    ┌──────────────────┐
│ VR921    │◄────wss:──────►│  vaillant/        │  ← SHIP/SPINE transport
│ Gateway  │   mDNS/_ship   │  ship.py,spine.py │     mDNS, TLS, certs
└──────────┘                └────────┬─────────┘
                                     │
                            ┌────────▼─────────┐
                            │  vaillant-eebus   │  ← Vaillant-specific
                            │  vaillant/        │     entity/feature discovery
                            │                   │     measurement parsing
                            └────────┬─────────┘
                                     │
                            ┌────────▼─────────┐
                            │  custom_components│  ← HA integration
                            │  /vaillant_eebus/ │     DataUpdateCoordinator
                            │                   │     CoordinatorEntity
                            │                   │     ConfigFlow, platforms
                            └──────────────────┘
```

### Existing projects to build on

| Project | Role |
|---------|------|
| **markusschultheis/Vaillant-VR921** (Python, no license) | Reference for VR921 entity/feature structure, SPINE datagram format |

### Dependency strategy

**SDK:** Eigen SHIP/SPINE implementatie — geen externe SDK dependency.
**Reference:** `markusschultheis/Vaillant-VR921` als inspiratie (geen license → rewrite, geen copy).

### Key decisions

- **Pure integration, no addon** — Docker container adds complexity with zero benefit here
- **3-layer separation** — protocol (`vaillant/ship.py` + `spine.py`), Vaillant domain (`vaillant/`), HA (`custom_components/`)
- **Async from day 1** — HA requires it, EEBUS is inherently async
- **ConfigFlow with mDNS discovery** — automatic VR921 detection, fallback to manual IP
- **DataUpdateCoordinator** — standard HA pattern for polling + subscriptions
- **SHIP identity/certificate** — generated once, reused for stable SKI
- **Pairing via myVaillant app** — first connect requires trust confirmation, then certificate-based
- **Persistent local daemon for development** — keeps one trusted session alive while wrappers and debug tools hot-reload around it

### Scope

**Phase 1 (this change):** Read-only integration
- mDNS discovery + config flow
- Connect to VR921 via SHIP/SPINE
- Read all measurement entities (temperatures, power, energy, status)
- Binary sensors (compressor running, alarm, etc.)
- Device info + diagnostics
- Tests at >90% coverage
- CI (Ruff, mypy, pytest, pre-commit)
- Documentation (README, architecture, troubleshooting)

### Current status

Implemented and proven against a real VR921:
- SHIP handshake end-to-end
- SPINE detailed discovery
- Measurement subscriptions
- Poll fallback for measurement servers that do not continuously push values
- Local development daemon with cached state and HTTP debug API
- HA lifecycle simulator for local capture/debug
- Home Assistant install path prepared: config flow connection test, coordinator startup, basic sensor mapping

Currently proven live values:
- `acPowerTotal`
- `dhwTemperature`
- `roomAirTemperature`
- `outsideAirTemperature`

Currently proven measurement descriptions without live values yet in capture:
- `acCurrent`
- `acEnergyConsumed`
- `acEnergyProduced`
- `acFrequency`
- `acPower`
- `acVoltage`

### Next execution order

1. Install on real Home Assistant server and validate config entry + entities
2. Fix install-time issues found in HA runtime
3. Add missing HA tests (config flow, coordinator, entity lifecycle)
4. Decide which remaining non-live scopes are publishable in v0.1.0
5. Finish release/tagging

### Install readiness

Current status is good enough for a first real Home Assistant installation test, but not yet archive-ready.
Main remaining gaps are HA-specific tests and full mypy coverage, not protocol connectivity.

**Not in scope (later phases):**
- Write operations (climate, switch, number)
- Subscriptions (event-based updates)
- Energy dashboard
- Advanced automation support
