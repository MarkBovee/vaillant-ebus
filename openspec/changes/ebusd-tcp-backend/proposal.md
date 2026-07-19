## Why

EEBUS (VR921) only exposes 4 live measurements — insufficient. EBUS (via ebusd) provides full heat pump telemetry: 362 registers including compressor speed, flow/return temp, pressures, fan speeds, EEV position, error codes, yields, COP, energy totals.

ebusd runs as HA addon, accessible via TCP port 8888. Build a direct TCP backend — no MQTT broker needed.

## What Changes

- **TCP backend** under `custom_components/vaillant_eebus/backend/`: `base.py`, `tcp.py`, `models.py`, `entity_factory.py`, `mapping.py`
- **Backend switch** — integration selects ebusd TCP as primary; EEBUS for energy supplement
- **Discovery via `find`** — single TCP command returns all 362 registers + current values
- **Poll via `read`** — DataUpdateCoordinator polls active registers at configurable interval
- **Write via `write -c`** — direct TCP command, verified by read-after-write
- **Entity types**: sensors (all readable), binary sensors (heating/cooling/compressor/defrost/alarm), numbers (writable numerics), selects (enums), switches (booleans)
- **HA services**: `read_parameter`, `write_parameter`, `refresh`, `rediscover`
- **No MQTT dependency** — direct TCP to ebusd, no broker
- **Diagnostics**: firmware, adapter status, discovered circuits, register count
- **EEBUS supplement**: optional, adds 4 energy measurements

## Capabilities

- `ebusd-tcp-transport`: TCP connection lifecycle, send/receive commands, reconnect with backoff
- `auto-discovery`: Self-discovery from `find` output, no config needed
- `sensor-reading`: All register types mapped to HA sensor entities
- `binary-sensor-reading`: Binary/comparison sensors from register values
- `entity-control`: Number/Select/Switch entities for writable parameters
- `ha-services`: read_parameter, write_parameter, refresh, rediscover
- `write-verification`: Read-after-write with rollback on rejection
- `error-handling`: Connection loss, ebusd restart, timeout, unknown register
- `diagnostics`: Full system status in HA diagnostics endpoint

## Impact

- New: `custom_components/vaillant_eebus/backend/` (base.py, tcp.py, models.py, entity_factory.py, mapping.py)
- Modified: `__init__.py`, `config_flow.py`, `const.py`, `coordinator.py`, `manifest.json`
- EEBUS code untouched (optional supplement)
- No new external dependencies (asyncio built-in)
- Test additions: unit tests, integration tests with fake ebusd TCP server
- Documentation: setup guide, entities.yaml reference, developer guide
