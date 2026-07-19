# Vaillant EEBUS Project Instructions

## Language

- Communication with Mark: Dutch
- All code, commit messages, documentation, logs, UI strings, and technical names: **English**

## Project summary

- Project: `vaillant-eebus`
- Goal: local Home Assistant integration for Vaillant heat pumps
- Phase 1: EEBUS via VR921 — proven, but only 4 measurements
- Phase 2 (new): EBUS via ebusd + hardware adapter — full heat pump telemetry
- The EEBUS code remains as optional supplement for energy measurements

## Current status

**EEBUS (completed):** Real VR921 connection works end-to-end. SHIP handshake, SPINE discovery, measurement subscriptions, poll fallback, local daemon, and HA install path are all proven. **Only 4 live measurements available from the VR921** — confirmed after exhaustive testing (subscription, poll, setpoint write trigger, 120s capture, Loxone investigation, GitHub reference analysis). The VR921 is an energy-management gateway, not a full diagnostic interface.

**EBUS (ebusd TCP backend):** ebusd draait als HA addon op 192.168.1.100, verbonden met aroTHERM via eBUS adapter. Custom_component praat direct via TCP (port 8888) — geen MQTT broker nodig. OpenSpec change `ebusd-tcp-backend`. 362 registers bekend, grouping/writes/translations als meerwaarde boven ebusd's ingebouwde HA integratie.

### ebusd connectie details

- HA server: `192.168.1.100`, user `homeassistant`, via SSH bereikbaar
- MQTT broker: `core-mosquitto` op HA server, port 1883, user `mark`, pass `bovee`
- ebusd device: `ens:192.168.1.101:9999` (netwerk eBUS adapter)
- ebusd config: `--scanconfig --accesslevel=* --mqttjson --mqttint=/etc/ebusd/mqtt-hassio.cfg --mqtttopic=ebusd`
- JSON format: `{"field": {"value": X}}` (niet `--mqttjson=short`)
- Writable test: via `ebusctl write <circuit> <name> <value>` op HA server, of MQTT publish naar `ebusd/<circuit>/<name>/set`
- Credentials in `.env` (git-ignored)
- **TCP direct port:** 8888 (binary protocol, commands: `f`, `r`, `write -c`)
- **HTTP port:** 8889 (ingeschakeld maar addon moet herstart voor actief)

## Proven EEBUS measurements

- `acPowerTotal`
- `dhwTemperature`
- `roomAirTemperature`
- `outsideAirTemperature`

## Described but never live (EEBUS)

- `acCurrent` (3-phase)
- `acEnergyConsumed`
- `acEnergyProduced`
- `acFrequency`
- `acPower` (3-phase)
- `acVoltage` (5-phase)
- 16 ElectricalConnection parameters (all scopeType=None)
- Setpoint/HVAC/SmartEnergy features (write-only, no data notify)

## Repository structure

### `vaillant/`

Protocol and Vaillant-specific core logic.

- `certificate.py`: self-signed certificate generation and SKI reuse
- `ship.py`: SHIP handshake, SHIP control/data frame helpers
- `spine.py`: SPINE read/call/result helpers
- `discovery.py`: entity tree and feature discovery
- `measurement.py`: measurement description/value parsing and subscription helpers
- `client.py`: persistent VR921 session lifecycle, discovery, subscribe, poll fallback, cached state
- `const.py`: protocol constants, reconnect and polling intervals

### `custom_components/vaillant_eebus/`

Home Assistant integration layer.

- `__init__.py`: config entry setup/unload
- `config_flow.py`: manual host flow, mDNS-prefill, TCP connect test
- `coordinator.py`: DataUpdateCoordinator wrapper around `VaillantClient`
- `sensor.py`: mapped HA sensors
- `binary_sensor.py`: compressor-running binary sensor
- `diagnostics.py`: config entry diagnostics
- `const.py`, `manifest.json`, `strings.json`, `translations/`

### `scripts/`

Developer tooling.

- `daemon.py`: persistent local daemon exposing `/health`, `/state`, `/descriptions`, `/scopes`
- `test_local.py`: HA lifecycle simulator and capture tool
- `standalone.py`: older diagnostic script; useful reference, not main path

### `tests/`

- `test_certificate.py`: cert reuse test
- `test_measurement.py`: parser tests and fixture presence checks
- `fixtures/measurements.jsonl`: real captured live measurements

### `openspec/changes/ebusd-tcp-backend/`

Active change record (ebusd+MQTT backend). Read this first in a fresh session:

- `proposal.md` — why and what changes
- `design.md` — architecture, MQTT reference, entity strategy, live setup details
- `tasks.md` — implementation checklist (start at task 0: data capture)
- `specs/*` — requirements per capability

### `openspec/changes/archive/2026-07-18-phase-1-read-only/`

Archived EEBUS phase 1 (reference only — not active). Contains full EEBUS protocol research, VR921 capabilities, and the pivot decision.

## External references

- [markusschultheis/Vaillant-VR921](https://github.com/markusschultheis/Vaillant-VR921) — diagnostic SHIP/SPINE client (single 88KB script). Confirms our entity/feature tree. Our implementation is more complete (Setpoint, ElectricalConnection, SmartEnergy, use case parsing) but the reference is useful for protocol exploration and independently confirms VR921 behaviour.

## Preferred development workflow

### 1. Keep one live session open

Use the daemon during development so VR921 trust is not renegotiated on every edit.

```bash
.venv/bin/python scripts/daemon.py \
  --host 192.168.1.130 \
  --http-port 8125 \
  --state-file /tmp/vaillant-state.json \
  --event-log /tmp/vaillant-events.jsonl
```

### 2. Inspect live state

```bash
curl http://127.0.0.1:8125/health
curl http://127.0.0.1:8125/scopes
curl http://127.0.0.1:8125/state | jq
```

### 3. Capture a full local session

```bash
.venv/bin/python scripts/test_local.py \
  --host 192.168.1.130 \
  --capture-seconds 60 \
  --summary-file /tmp/opencode/vaillant-summary.json
```

## Home Assistant install path

The integration was copied to the HA SMB config share:

- `CONFIG/custom_components/vaillant_eebus/`
- `CONFIG/vaillant/`

Expected next manual step:

1. restart Home Assistant
2. add integration `Vaillant EEBUS`
3. use host `192.168.1.130`, port `12480`
4. inspect entity creation and runtime logs

## Validation commands

Run these before claiming completion:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
python3 -m compileall custom_components vaillant scripts tests
```

Current state:

- `ruff`: passing
- `pytest`: passing
- `compileall`: passing
- `mypy`: not yet passing; missing HA typings/deps and many strict annotations still remain

## Known limitations

- Home Assistant runtime validation is still pending on the real server
- Full mypy strict pass is not complete
- HA-specific tests are still incomplete
- Several described electrical scopes still do not produce live values through the current measurement path
- `scripts/standalone.py` is legacy and excluded from Ruff checks

## Important constraints

- Never commit secrets from `.env`
- `.env` is git-ignored and may contain SMB credentials
- Never print credential values in logs or responses
- Reuse `cert.pem` / `key.pem` to keep SKI stable
- Avoid running multiple live VR921 sessions at once; VR921 may close one with `4201 Double connection`

## Next priorities

1. **Execute openspec change `ebusd-tcp-backend`** — taak 1 eerst: scaffolding (backend dir, TCP transport, find parser)
2. Build auto-discovery + entity factory
3. Build sensor/binary_sensor/control entities
4. Build HA services + write verification
5. Validate on real HA server (EEBUS supplement optional)
6. Revisit mypy strict pass

### Eerste taak bij nieuwe sessie: open `/opsx-apply ebusd-tcp-backend` en begin bij taak 1.1 (scaffolding).
