# Vaillant eBUS Project Instructions

## Language

- Communication with Mark: Dutch
- All code, commit messages, documentation, logs, UI strings, and technical names: **English**

## Project summary

- Project: `vaillant-ebus`
- Goal: local Home Assistant integration for Vaillant heat pumps via ebusd TCP
- ebusd runs as HA addon on 192.168.1.100, connected to aroTHERM via network eBUS adapter
- HA custom_component connects directly to ebusd TCP port 8888 — no MQTT, no cloud
- 357 registers auto-discovered, ~254 live (when compressor idle — many more when running)

## Current status

**EEBUS (archived):** Previous VR921 effort documented in `openspec/changes/archive/`. VR921 confirmed as energy-management gateway with only 4 live measurements — proved insufficient for heat pump diagnostics.

**EBUS (ebusd TCP backend — active):** Fully implemented. TCP backend connects to ebusd, runs `find` to discover all registers, generates HA entities dynamically. Tested against live ebusd (26.1.26.1, 4 Vaillant slaves: HMU00, CTLV2, VWZ00, NETX2).

## ebusd connectie details

- HA server: `192.168.1.100`, user `homeassistant`, via SSH bereikbaar
- ebusd device: `ens:192.168.1.101:9999` (netwerk eBUS adapter)
- ebusd addon config:
  ```yaml
  network_device: ens:192.168.1.101:9999
  seed_mqtt_cfg: false
  commandline_options:
    - "--accesslevel=*"
    - "--scanconfig"
    - "--port=8888"
    - "--enabledefine"
  ```
- Geen MQTT, geen `--mqttjson`, geen `--mqttint` — custom_component leest direct via TCP
- Credentials in `.env` (git-ignored)
- **TCP port:** 8888 (plain text, `\n`-delimited)
- **HTTP port:** 8889 (niet in gebruik)

## ebusd addon CSV beheer

De addon data directory (`/addon_configs/b4d7ad18_ebusd/`) wordt in de container gemount als `/etc/ebusd/`. CSV bestanden in `vaillant/` subdirectory worden door ebusd geladen bij startup.

Om CSV set te updaten:
1. Clone `https://github.com/john30/ebusd-configuration.git`
2. `npm install && npm run compile-en`
3. Upload `outcsv/@ebusd/ebus-typespec/vaillant/*.csv` naar `/addon_configs/b4d7ad18_ebusd/vaillant/`
4. Restart ebusd addon

**Belangrijk**: `--configpath=/config` OVERSCHRIJFT de default config path en breekt standaard CSV laden. Alleen gebruiken in combinatie met volledige CSV set op die locatie.

## Register discoverie

- `find` returned registers + metadata van ebusd
- `REGISTER_MAP` in mapping.py fungeert als fallback: entities worden aangemaakt voor registers die in de map staan, ook al zijn ze niet in `find`
- `_fallback_read` in coordinator probeert REGISTER_MAP entries die `find` miste alsnog te lezen via direct `read`
- Sommige registers zijn alleen leesbaar als de compressor draait (summer: veel "no data stored")
- Registers die `ERR: element not found` geven ondanks CSV definitie worden door de hardware niet ondersteund (firmware variant) — simpelweg accepteren

## SSH access

```bash
# Credentials in .env (git-ignored)
sshpass -p 'PASSWORD' ssh user@192.168.1.100
```

- `find` via ebusd TCP (port 8888) over SSH: `echo 'f' | timeout 15 nc 192.168.1.100 8888`
- HA Supervisor API (local on HA): `http://supervisor/core/api/...` met token uit `/run/s6/container_environment/SUPERVISOR_TOKEN`
- HA restart via SSH: `ssh user@192.168.1.100 "docker restart hassio_... || ha core restart"`

## Repository structure

### `custom_components/vaillant_ebus/`

Home Assistant integration.

- `__init__.py`: setup/unload, services (read_parameter, write_parameter, refresh, rediscover)
- `config_flow.py`: ebusd host/port config, TCP connect test
- `coordinator.py`: DataUpdateCoordinator, auto-discovery via `find`, poll loop
- `sensor.py`, `binary_sensor.py`, `number.py`, `select.py`, `switch.py`: entity platforms
- `diagnostics.py`: config entry diagnostics
- `const.py`, `manifest.json`, `strings.json`, `translations/`, `services.yaml`

### `backend/`

Pluggable transport layer.

- `base.py`: abstract `Backend` class
- `models.py`: dataclasses (`EbusdRegister`, `Circuit`, `RegisterMeta`, `WriteResult`)
- `tcp.py`: `EbusdTcpBackend` — asyncio TCP, connect/find/read/write/poll, reconnect backoff
- `entity_factory.py`: generate HA entity descriptions from discovered registers
- `mapping.py`: default metadata (friendly names, icons, units, device_classes) for all registers

### `openspec/changes/ebusd-tcp-backend/`

Active change record.

- `proposal.md` — why and what changes
- `design.md` — architecture, register inventory, entity strategy, poll strategy
- `tasks.md` — implementation checklist
- `specs/*` — requirements per capability

### `openspec/changes/archive/2026-07-18-phase-1-read-only/`

Archived EEBUS phase 1 (reference only — not active).

### `tests/`

- `test_model.py`: unit tests for backend models

## Validation commands

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
python3 -m compileall -f custom_components/vaillant_ebus/
```

Current state:

- `ruff`: passing
- `pytest`: passing
- `compileall`: passing

## Z1RoomHumidity (room humidity)

Room humidity is NOT discoverable via `find` — it's a temporary register defined at runtime via the `define` command. Works on CTLV2 (SW=0514, HW=1104).

**Working define:**
```bash
ebusctl define -r "r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800,value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity"
```

The custom_component auto-defines this on startup in `coordinator.py:_define_custom_registers()`. No CSV override needed.

Key details:
- Type `r5` (not `r`) — zone 1 read model
- QQ=31 (ebusd master), ZZ=15 (CTLV2 slave)
- Message B524, field ID `020003002800`
- First field `value,,IGN:4,,,,` (padding)
- Second field `value,,EXP,,%,z1 Room Humidity` (actual value)
- Value type: `EXP` (exponential) with unit `%`
- Register key in code: `ctlv2.z1RoomHumidity` (lowercase z)

No conditional or IGN:4 flag — the `ign,,IGN:4` in the original CSV is a 4-byte IGNORE field (padding), not a condition.

## CRITICAL: Do not remove or modify the following

### `coordinator.py:_define_custom_registers()`
- **Must stay.** Defines runtime registers at ebusd startup via `define` command.
- Currently defines `ctlv2.z1RoomHumidity` — NOT discoverable via `find` (r5 message type).
- Agents that refactor `coordinator.py` or rewrite the startup flow **must preserve this method and its call** at line 58 (`await self._define_custom_registers()`).
- Removing this will break room humidity until HA is restarted.

### `sensor.py:native_value` None-check
- Handles `"-"`, `"no data stored"`, `"empty"` from ebusd as `None` (unavailable) instead of passing them as string values to HA.
- **Must stay.** Without it, sensors with idle registers show garbage string values in HA.
- If you refactor `sensor.py`, preserve the `raw in ("-", "no data stored", "empty")` guard.

### `backend/tcp.py:async_send_raw()`
- Public method used by `_define_custom_registers()` to send raw `define` commands to ebusd.
- **Must stay** as long as `_define_custom_registers()` exists.

### Historical context
The shared session at https://opncd.ai/share/66JWAPw2 did this work. Another agent accidentally reverted it during a rename/docs rewrite. This AGENTS.md section exists to prevent repeat incidents. Do not remove these items — if you think they're obsolete, discuss with Mark first.

The shared session at https://opncd.ai/share/s6qu6no also did this work. Another agent reverted it again shortly after. The pattern is: an agent refactors coordinator.py, drops `_define_custom_registers()` and `async_send_raw()`, and humidity breaks silently. **Always check**: does `coordinator.py` have `_define_custom_registers()` and call it? Does `tcp.py` have `async_send_raw()`? If not, restore from commit `6848b97`.

## Known limitations

- Home Assistant runtime validation is still pending on the real server
- Most heat pump registers show "no data stored" when compressor is idle (summer)
- Entity classification (sensor vs number vs select) needs YAML overrides for best results
- Native unit inference for uncommon registers is incomplete

## File Upload (SSH)

**Nooit `tee` gebruiken met `echo "PWD" | sudo -S tee`** — het wachtwoord komt in het bestand terecht (zsh heredoc interactie).

Altijd base64 methode:
```bash
PAYLOAD=$(base64 -w0 /local/path/to/file)
sshpass -p 'PASSWORD' ssh user@host \
  'echo "PASSWORD" | sudo -S python3 -c "import sys,base64;open(\"/remote/path/file\",\"w\").write(base64.b64decode(sys.argv[1]).decode())" "'"${PAYLOAD}"'"
```

Voor grote bestanden (>40KB): splitten en append-en.

## Important constraints

- Never commit secrets from `.env`
- `.env` is git-ignored and may contain credentials
- Never print credential values in logs or responses
- TCP port 8888 is plain text — keep on trusted network
