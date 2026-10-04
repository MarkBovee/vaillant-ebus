---
name: home-assistant
description: "Use when developing, testing, or deploying Home Assistant custom_components via SSH/SMB on a local HA instance. Covers SSH access, HA API, entity registry, supervisor ops, deploy workflow, and ebusd TCP interaction."
triggers:
  # HA-specific (no general programming terms)
  - home assistant
  - homeassistant
  - HASS
  - HA core
  - custom_component
  - manifest.json
  - hacs
  - HA restart
  - HA stop
  - HA start
  - HA update
  - HA logs
  - HA SSH
  - HA supervisor
  - HA API
  - supervisor token
  - SUPERVISOR_TOKEN
  - HA addon
  # Deploy to HA
  - deploy to HA
  - upload to HA
  - push branch to HA
  - test on HA
  - install integration
  - SMB upload
  - build zip
  - unzip HA
  # Registry
  - entity registry
  - device registry
  - stale entities
  - nuke entities
  - clean device registry
  - disable entities
  - core.entity_registry
  - core.device_registry
  - core.config_entries
  # Debug HA
  - debug HA
  - HA debug
  - debug integration
  # ebusd
  - ebusd
  - ebusd register
  - ebusd read
  - ebusd define
  - ebusd TCP
  - ebusd query
  - ebusd poll
  - ebusd find
  - ebusd CSV
  - ebusd monitor
  - ebusd power
  - ebusd addon
  - ebusd backend
  - ebusd connect
  - ebusd grab
  - ebusd decode
  - ebusd scan
  - ebus bericht
  - ebus uitlezen
  - ebus debugging
  - ebus bus
  # Vaillant / heat pump
  - compressor power
  - warmtepomp register
  - heat pump register
  - vaillant
  - aroTHERM
  - VWZ
  - CTLV2
  - HMU
  - NETX2
  - B516
  - B524
  - hwc
  - legionella
  - hwc_compressor_active
  - current consumed power
  - current yield power
  - power consumption hmu
  # HA config
  - api/states
  - configuration.yaml
  - config entry
  - energy dashboard
  - core-mosquitto
  - HA backup
  - options flow
  - HA issue
  - HA diagnostics
---

# Home Assistant Development & Debugging

## GitHub Communication

When reporting HA findings in GitHub issues or discussions, use clear English and clean Markdown.
Write complete sentences with correct punctuation, separate paragraphs with blank lines, and put
lists or distinct points on separate lines. Never post compressed or run-on prose.

SSH/SMB workflow for custom_components on a local HA instance. Includes ebusd TCP interaction for debugging the Vaillant heat pump.

## Deploy workflow

**ALWAYS use `tools/deploy_ha.sh` — never write ad-hoc SSH/SMB commands.**

```bash
# Full deploy: validate + build + upload + unzip + restart HA
./tools/deploy_ha.sh --restart

# Quick iteration (skip ruff/pytest/compileall):
./tools/deploy_ha.sh --restart --skip-validate
```

The script loads credentials from `.env`, builds a clean zip (excludes `__pycache__`), uploads via SMB, unzips on HA, and optionally restarts HA.

`tools/deploy_ha.sh` and `tools/deploy_ha.py` are checked in (without secrets). Windows setup (SSH add-on without SFTP, `/config` owned by root, `sudo -n`, backup in `/config/.deploy_backups/`): see docs/release-process.md "Deploying To The Owner's Home Assistant". Restart with HA-MCP `ha_restart`.

**If `tools/deploy_ha.sh` doesn't exist**, create it at `<repo>/tools/deploy_ha.sh` with:
1. Load HA_HOST/HA_USER/HA_PASSWORD/HA_SSH_PASSWORD from `.env`
2. Validate: `ruff check . && pytest -q && compileall`
3. Build zip from `custom_components/<domain>/` (no `__pycache__`, no dir prefix)
4. SMB upload to HA
5. SSH unzip (replace all files)
6. Restart HA via supervisor API

**CRITICAL: `__pycache__/`** — `rm -rf *` and `rm -f *.py` do not remove hidden dirs. Always use `rm -rf /config/custom_components/<domain>/` (the whole directory) instead of deleting selectively.

## Entity registry nuke (stop HA first!)

```python
import json
with open('/config/.storage/core.entity_registry') as f:
    d = json.load(f)
d['data']['entities'] = [e for e in d['data']['entities']
    if 'vaillant_ebus' not in e.get('platform','')]
with open('/config/.storage/core.entity_registry', 'w') as f:
    json.dump(d, f, indent=2)
```

**Sequence:** stop HA → nuke → delete `.before-*` / `.before_prune` backups → start HA.

## Debug pattern

`_LOGGER.warning("DEBUG: %s = %s", key, value)` in deployed code. Remove before merge.

Enable via `configuration.yaml`: `logger.logs.custom_components.<domain>: debug` or HA UI > Logs.

## Reading HA logs (HA 2026.7+)

**Use the HA-MCP first:** `ha_get_logs(source="error_log", search="vaillant")`. Reading the Supervisor token from the container is blocked and not needed. The following curl examples are only a fallback for the owner themselves.

HA 2026.7+ no longer writes `home-assistant.log` — logs go to container stdout/stderr. Only `.1`, `.old`, `.fault` exist in `/config/`.

**Core logs via supervisor API** (streaming endpoint, `--max-time` required):
```bash
TOKEN=$(ssh ... "cat /run/s6/container_environment/SUPERVISOR_TOKEN")
curl -s --max-time 5 http://supervisor/core/logs \
  -H "Authorization: Bearer $TOKEN" \
  | grep -i "vaillant\|ebus\|error\|traceback" | tail -40
```

**Filter on your domain** during development:
```bash
curl -s --max-time 10 http://supervisor/core/logs \
  -H "Authorization: Bearer $TOKEN" \
  | grep -i "vaillant_ebus\|coordinator\|entity_factory\|custom_components"
```

**Other endpoints that don't work** (404 in 2026.7+):
- `http://supervisor/core/api/logs` ✗
- `http://supervisor/core/api/error_log` ✗
- `journalctl` via SSH addon ✗ (protection mode blocked)
- `/config/home-assistant.log` ✗ (does not exist as an active log)

## Credentials (.env)

| Var | Purpose |
|-----|---------|
| `HA_HOST` | HA hostname/IP |
| `HA_SSH_USER/PASSWORD` | SSH user + password |
| `HA_USER/PASSWORD` | SMB share credentials |

## ebusd TCP Protocol

### Basics

ebusd runs as an HA addon, TCP port 8888 (mapped to the host). Use your own Python script via SSH for interaction.

**Connect + read** (Python):
```python
import socket, time
s = socket.socket()
s.settimeout(5)
s.connect(("127.0.0.1", 8888))
s.sendall(b"r -c hmu CurrentConsumedPower\n")
time.sleep(0.3)
data = s.recv(4096).decode().strip()
s.close()
```

**Inline via SSH**:
```bash
PASS="$HA_SSH_PASSWORD"  # from the git-ignored .env; never hardcode
sshpass -p "$PASS" ssh user@host 'python3' << 'PYEOF'
import socket, time
s = socket.socket(); s.settimeout(5)
s.connect(("127.0.0.1", 8888))
s.sendall(b"r -c hmu RunDataStatuscode\n")
time.sleep(0.3); print(s.recv(4096).decode().strip()); s.close()
PYEOF
```

### Register naming

CRITICAL: ebusd uses a **space** between circuit and name, NOT a dot.

| Correct | Wrong |
|---------|------|
| `r -c hmu CurrentConsumedPower` | `r hmu.CurrentConsumedPower` ✗ |
| `r -c hmu RunDataStatuscode` | `r hmu.RunDataStatuscode` ✗ |

The custom_component backend itself uses the correct syntax (`read -c {circuit} {name}`). The problem only occurs in manual ebusd queries.

### Key commands

| Command | Purpose | Example |
|---------|---------|---------|
| `r -c CIRCUIT NAME` | Read register | `r -c hmu FlowTemp` |
| `r -c CIRCUIT NAME FIELD` | Read specific field | `r -c hmu Status01 temp` |
| `f` / `find` | Discover all registers | `find -c hmu` |
| `find -v -c CIRCUIT` | Verbose with field names | `find -v -c hmu` |
| `i` | Info (version, CSV, slaves) | `i` |
| `s` / `state` | Bus state | `s` |
| `define -r "DEF"` | Define custom register | see Define section |
| `h` / `help` | Help | `h` |

### Poll loop

Monitor registers in real time:
```python
import socket, time

def read_reg(circuit, name):
    s = socket.socket(); s.settimeout(5)
    s.connect(("127.0.0.1", 8888))
    s.sendall(f"r -c {circuit} {name}\n".encode())
    time.sleep(0.3)
    data = s.recv(4096).decode().strip()
    s.close()
    return data

while True:
    ts = time.strftime("%H:%M:%S")
    pwr = read_reg("hmu", "CurrentConsumedPower")
    yield_p = read_reg("hmu", "CurrentYieldPower")
    status = read_reg("hmu", "RunDataStatuscode")
    speed = read_reg("hmu", "RunDataCompressorSpeed")
    util = read_reg("hmu", "CurrentCompressorUtil")
    print(f"{ts} ST={status} PWR={pwr} YLD={yield_p} SPD={speed} UT={util}")
    time.sleep(30)
```

Note: `%H:%M:%S` inside an f-string gives a SyntaxError. Use a separate variable or call `strftime` outside the f-string.

### Multi-field registers

`find -v` shows field names. Example `Status01`:
```
hmu Status01 = temp=58.5;temp_1=53.5;pumpstate=hwc
```

Read a specific field: `r -c hmu Status01 temp`

Known multi-field registers:
- `Status01` — temp (flow?), temp_1 (return?), temp_2..4, pumpstate (hwc/hc)
- `SetMode` — hcmode, flowtempdesired, hwctempdesired, hwcflowtempdesired, disablehc, etc.

### Define custom registers

`define -r "DEFINITION"` works because the addon has `--enabledefine`.

**r5 def for z1RoomHumidity** (works):
```
r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800
,value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity
```

Key: type `r5` (zone read), QQ=31 (ebusd), ZZ=15 (CTLV2), message B524, field ID `020003002800`.

**B516 sub 14 is the power (HMUX0 SW0407 and VWZIO SW0500, 1.10.5).** The gateway polls `f108b5160114` (slave 08) and `f176b5160114` (slave 76): reply = status byte + float32 W. Upstream ebusd-configuration #490, #610 and #638 document the same layout (`ign,IGN:1` + `EXP`). On older HMU firmware (HW5103 < SW0901) the active read returns nothing/`00`; therefore `PowerConsumptionHmu` is only a *passive* definition on HMUX0 SW0407. The older remark that B516 only has fields 10-13 applies to the PrEnergy statistic (`1000ffff...`), not to sub 14.

### Key registers (hmu circuit)

| Register | Unit | Description |
|----------|------|-------------|
| `CurrentConsumedPower` | kW | Compressor electrical power |
| `CurrentYieldPower` | kW | Thermal power |
| `RunDataBuildingCPumpPower` | W | Building pump power (65 W typical) |
| `RunDataStatuscode` | — | Status string (hwc_compressor_active, standby, etc.) |
| `RunDataCompressorSpeed` | rpm | Compressor speed |
| `CurrentCompressorUtil` | % | Compressor utilization |
| `FlowTemp` | °C | Flow temperature |
| `RunDataHighPressure` | bar | High pressure |
| `RunDataCompressorOutletTemp` | °C | Compressor outlet |
| `RunDataCompressorInletTemp` | °C | Compressor inlet |
| `RunDataEEVOutletTemp` | °C | EEV outlet |
| `RunDataAirInletTemp` | °C | Air inlet |
| `RunDataFan1Speed` | rpm | Fan 1 |
| `RunDataFan2Speed` | rpm | Fan 2 |
| `RunDataEEVPositionAbs` | steps | EEV position |
| `BuildingCircuitFlow` | l/h | Flow |
| `TotalEnergyUsage` | kWh | Total electrical energy (cumulative) |
| `SupplyTempWeighted` | °C | Weighted supply temp |
| `CopHc` | — | COP heating |
| `CopHwc` | — | COP hot water |
| `CopCooling` | — | COP cooling |

### Status codes

`RunDataStatuscode` values:
- `hwc_compressor_active` — compressor active for hot water
- `standby` — compressor idle
- Numeric: 104, 114, 134 = active

## CSV management

ebusd loads CSV from `/etc/ebusd/vaillant/` in the container. Always `08.hmu.HW5103.csv` for HMU (HW 5103). CSV files are not directly accessible via the host filesystem — they live in the container image.

Addon: `b4d7ad18_ebusd`, `--accesslevel=*`, `--enabledefine`. No `--configpath` override (default path).

## Use with

- `kaizen` for the steady-state development loop
- `debugging` for non-trivial HA integration bugs
- `verification` after deploy

## Avoid

- **Ad-hoc SSH/SMB deploy commands** — ALWAYS use `tools/deploy_ha.sh --restart`
- Reload as a replacement for restart after registry/external changes
- `git archive` without committing — archive builds from the committed tree, not the working tree
- Assuming that `state: None` in config_entries JSON means "not loaded" (HA 2026.7+ does not persist state)
- Dot notation `circuit.name` in manual ebusd queries — use `-c circuit name` with a space

## Reference

See [REFERENCE.md](./REFERENCE.md) for API calls, storage paths, MQTT, and HA 2026.7 breaking patterns.
