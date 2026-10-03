---
name: home-assistant
description: "Use when developing, testing, or deploying Home Assistant custom_components via SSH/SMB on a local HA instance. Covers SSH access, HA API, entity registry, supervisor ops, deploy workflow, and ebusd TCP interaction."
triggers:
  # HA specifiek (geen algemene programmeertermen)
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
  # Deploy naar HA
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
  # Vaillant / warmtepomp
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

SSH/SMB workflow voor custom_components op lokale HA instance. Inclusief ebusd TCP interactie voor Vaillant warmtepomp debuggen.

## Deploy workflow

**ALWAYS use `scripts/deploy.sh` — never write ad-hoc SSH/SMB commands.**

```bash
# Full deploy: validate + build + upload + unzip + restart HA
./scripts/deploy.sh --restart

# Quick iteration (skip ruff/pytest/compileall):
./scripts/deploy.sh --restart --skip-validate
```

The script loads credentials from `.env`, builds a clean zip (excludes `__pycache__`), uploads via SMB, unzips on HA, and optionally restarts HA.

**If `scripts/deploy.sh` doesn't exist**, create it at `<repo>/scripts/deploy.sh` with:
1. Load HA_HOST/HA_USER/HA_PASSWORD/HA_SSH_PASSWORD from `.env`
2. Validate: `ruff check . && pytest -q && compileall`
3. Build zip from `custom_components/<domain>/` (no `__pycache__`, no dir prefix)
4. SMB upload to HA
5. SSH unzip (replace all files)
6. Restart HA via supervisor API

**CRITICAL: `__pycache__/`** — `rm -rf *` en `rm -f *.py` verwijderen hidden dirs niet. Altijd `rm -rf /config/custom_components/<domain>/` (de hele directory) gebruiken ipv selectief verwijderen.

## Entity registry nuke (stop HA eerst!)

```python
import json
with open('/config/.storage/core.entity_registry') as f:
    d = json.load(f)
d['data']['entities'] = [e for e in d['data']['entities']
    if 'vaillant_ebus' not in e.get('platform','')]
with open('/config/.storage/core.entity_registry', 'w') as f:
    json.dump(d, f, indent=2)
```

**Sequence:** stop HA → nuke → verwijder `.before-*` / `.before_prune` backups → start HA.

## Debug pattern

`_LOGGER.warning("DEBUG: %s = %s", key, value)` in deployed code. Verwijder voor merge.

Enable via `configuration.yaml`: `logger.logs.custom_components.<domain>: debug` of HA UI > Logs.

## HA Logs lezen (HA 2026.7+)

HA 2026.7+ schrijft geen `home-assistant.log` meer — logs gaan naar container stdout/stderr. Alleen `.1`, `.old`, `.fault` bestaan in `/config/`.

**Core logs via supervisor API** (streaming endpoint, `--max-time` verplicht):
```bash
TOKEN=$(ssh ... "cat /run/s6/container_environment/SUPERVISOR_TOKEN")
curl -s --max-time 5 http://supervisor/core/logs \
  -H "Authorization: Bearer $TOKEN" \
  | grep -i "vaillant\|ebus\|error\|traceback" | tail -40
```

**Filter op jouw domain** tijdens development:
```bash
curl -s --max-time 10 http://supervisor/core/logs \
  -H "Authorization: Bearer $TOKEN" \
  | grep -i "vaillant_ebus\|coordinator\|entity_factory\|custom_components"
```

**Andere endpoints die niet werken** (404 in 2026.7+):
- `http://supervisor/core/api/logs` ✗
- `http://supervisor/core/api/error_log` ✗
- `journalctl` via SSH addon ✗ (protection mode blocked)
- `/config/home-assistant.log` ✗ (bestaat niet als actief log)

## Credentials (.env)

| Var | Purpose |
|-----|---------|
| `HA_HOST` | HA hostname/IP |
| `HA_SSH_USER/PASSWORD` | SSH user + password |
| `HA_USER/PASSWORD` | SMB share credentials |

## ebusd TCP Protocol

### Basics

ebusd draait als HA addon, TCP poort 8888 (gemapped naar host). Eigen Python script via SSH voor interactie.

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
PASS="M@rkB0v33"
sshpass -p "$PASS" ssh user@host 'python3' << 'PYEOF'
import socket, time
s = socket.socket(); s.settimeout(5)
s.connect(("127.0.0.1", 8888))
s.sendall(b"r -c hmu RunDataStatuscode\n")
time.sleep(0.3); print(s.recv(4096).decode().strip()); s.close()
PYEOF
```

### Register naming

CRITICAL: ebusd gebruikt **spatie** tussen circuit en naam, NIET punt.

| Correct | Fout |
|---------|------|
| `r -c hmu CurrentConsumedPower` | `r hmu.CurrentConsumedPower` ✗ |
| `r -c hmu RunDataStatuscode` | `r hmu.RunDataStatuscode` ✗ |

De custom_component backend gebruikt zelf de juiste syntax (`read -c {circuit} {name}`). Het probleem zit alleen in handmatige ebusd queries.

### Key commands

| Command | Purpose | Example |
|---------|---------|---------|
| `r -c CIRCUIT NAME` | Read register | `r -c hmu FlowTemp` |
| `r -c CIRCUIT NAME FIELD` | Read specific field | `r -c hmu Status01 temp` |
| `f` / `find` | Discover all registers | `find -c hmu` |
| `find -v -c CIRCUIT` | Verbose with field names | `find -v -c hmu` |
| `i` | Info (version, CSV, slaves) | `i` |
| `s` / `state` | Bus state | `s` |
| `define -r "DEF"` | Define custom register | zie Define section |
| `h` / `help` | Help | `h` |

### Poll loop

Monitor registers in real-time:
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

Let op: `%H:%M:%S` in f-string geeft SyntaxError. Gebruik losse variable of `strftime` buiten de f-string.

### Multi-field registers

`find -v` toont veldnamen. Voorbeeld `Status01`:
```
hmu Status01 = temp=58.5;temp_1=53.5;pumpstate=hwc
```

Lees specifiek veld: `r -c hmu Status01 temp`

Bekende multi-field registers:
- `Status01` — temp (flow?), temp_1 (return?), temp_2..4, pumpstate (hwc/hc)
- `SetMode` — hcmode, flowtempdesired, hwctempdesired, hwcflowtempdesired, disablehc, etc.

### Define custom registers

`define -r "DEFINITION"` werkt omdat addon `--enabledefine` heeft.

**r5 def voor z1RoomHumidity** (werkt):
```
r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800
,value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity
```

Key: type `r5` (zone read), QQ=31 (ebusd), ZZ=15 (CTLV2), message B524, field ID `020003002800`.

**B516 werkt NIET voor power** — heeft alleen fields 10-13 (UCH):
- Field 10: varieert (UCH, mogelijk flow gerelateerd)
- Field 11: ~2 (UCH), 258 (UIN) — constant
- Field 12: ~1 (UCH) — constant
- Field 13: ~32 (UCH), ~800 (UIN) — varieert, mogelijk sub-id

`PowerConsumptionHmu` met B516,14 is **fout** — B516 heeft geen field 14+ voor HMU.

### Key registers (hmu circuit)

| Register | Eenheid | Beschrijving |
|----------|---------|-------------|
| `CurrentConsumedPower` | kW | Compressor elektrisch vermogen |
| `CurrentYieldPower` | kW | Thermisch vermogen |
| `RunDataBuildingCPumpPower` | W | Bouwpomp vermogen (65 W typisch) |
| `RunDataStatuscode` | — | Status string (hwc_compressor_active, standby, etc.) |
| `RunDataCompressorSpeed` | rpm | Compressortoeren |
| `CurrentCompressorUtil` | % | Compressor benutting |
| `FlowTemp` | °C | Aanvoertemperatuur |
| `RunDataHighPressure` | bar | Hoge druk |
| `RunDataCompressorOutletTemp` | °C | Compressor uitlaat |
| `RunDataCompressorInletTemp` | °C | Compressor inlaat |
| `RunDataEEVOutletTemp` | °C | EEV uitlaat |
| `RunDataAirInletTemp` | °C | Luchtinlaat |
| `RunDataFan1Speed` | rpm | Ventilator 1 |
| `RunDataFan2Speed` | rpm | Ventilator 2 |
| `RunDataEEVPositionAbs` | stappen | EEV positie |
| `BuildingCircuitFlow` | l/h | Flow |
| `TotalEnergyUsage` | kWh | Totale elektrische energie (cumulatief) |
| `SupplyTempWeighted` | °C | Gewogen aanvoertemp |
| `CopHc` | — | COP verwarmen |
| `CopHwc` | — | COP warm water |
| `CopCooling` | — | COP koelen |

### Status codes

`RunDataStatuscode` waarden:
- `hwc_compressor_active` — compressor actief voor warm water
- `standby` — compressor idle
- Numeriek: 104, 114, 134 = actief

## CSV management

ebusd laadt CSV uit `/etc/ebusd/vaillant/` in de container. Telkens `08.hmu.HW5103.csv` voor HMU (HW 5103). CSV bestanden zijn niet direct toegankelijk via host filesystem — zitten in container image.

Addon: `b4d7ad18_ebusd`, `--accesslevel=*`, `--enabledefine`. Geen `--configpath` override (standaard pad).

## Use with

- `kaizen` voor de steady-state development loop
- `debugging` voor niet-triviale HA-integratie bugs
- `verification` na deploy

## Avoid

- **Ad-hoc SSH/SMB deploy commands** — ALWAYS use `scripts/deploy.sh --restart`
- Reload als vervanging voor restart na registry/externe changes
- `git archive` zonder te committen — archive bouwt van committed tree, niet working tree
- Aannemen dat `state: None` in config_entries JSON betekent "niet geladen" (HA 2026.7+ persisted state niet)
- Puntnotatie `circuit.name` in handmatige ebusd queries — gebruik `-c circuit name` met spatie

## Reference

Zie [REFERENCE.md](./REFERENCE.md) voor API calls, storage paths, MQTT, en HA 2026.7 breaking patterns.
