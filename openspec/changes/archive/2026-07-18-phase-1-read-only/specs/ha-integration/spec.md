# HA Integration

## Scope

Home Assistant custom component wrapping the vaillant/ library.

## Requirements

### R1: ConfigFlow
mDNS discovery step + manual IP fallback + connection test.

### R2: DataUpdateCoordinator
Holds SHIP WebSocket connection. Manages reconnect with backoff. Heartbeat.

### R3: Entities
SensorEntity (temperature, power, energy) and BinarySensorEntity (compressor running, alarm).

Entities MUST be generated dynamically from the capability model, not hardcoded scope types.
Each discovered capability with a measurable value produces a sensor entity.
Computed entities (compressor_running binary sensor) remain manually defined.

### R4: unique_id
Deterministic from VR921 SKI + entity address + feature ID + measurement ID (or parameter ID).
Scope type alone is NOT sufficient — multiple entities can share the same scope type.

Format: `{ski}_{entity}_{feature}_{measurementId}`
Electrical connection parameters: `{ski}_{entity}_{feature}_ec_{parameterId}`

### R5: Diagnostics
Full data dump from VR921. Redact certs, SKI, IPs.

### R6: HACS
`hacs.json` with domain `vaillant_eebus`. Zipped release.
