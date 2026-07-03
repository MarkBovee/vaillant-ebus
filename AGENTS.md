# Vaillant EEBUS Project Instructions

## Language

- Communication with Mark: Dutch
- All code, commit messages, documentation, logs, UI strings, and technical names: **English**

## Project summary

- Project: `vaillant-eebus`
- Goal: local Home Assistant integration for Vaillant heat pumps through the VR921 EEBUS interface
- Scope today: read-only Phase 1
- Transport: EEBUS SHIP over TLS WebSocket, SPINE datagrams inside SHIP data frames
- No cloud dependency, no extra hardware, no addon/container required

## Current status

- Real VR921 connection works end-to-end
- SHIP handshake works
- SPINE discovery works
- Measurement subscriptions work
- Poll fallback works
- Local development daemon works
- Home Assistant install path is prepared, but runtime validation on the real HA server is the next step

## Proven live measurements

- `acPowerTotal`
- `dhwTemperature`
- `roomAirTemperature`
- `outsideAirTemperature`

## Described by VR921, but not yet returning live values in current captures

- `acCurrent`
- `acEnergyConsumed`
- `acEnergyProduced`
- `acFrequency`
- `acPower`
- `acVoltage`

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

### `openspec/changes/phase-1-read-only/`

Primary change record. Read this first in a fresh session:

- `proposal.md`
- `design.md`
- `tasks.md`
- `specs/*`

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

1. validate install on the real HA server
2. fix any HA runtime issues found there
3. decide which described-but-not-live scopes belong in v0.1.0
4. add HA config/coordinator/entity tests
5. revisit mypy strict pass
