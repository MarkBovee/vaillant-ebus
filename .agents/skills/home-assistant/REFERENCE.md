# Home Assistant Reference

## ebusd TCP API

### Connectie

```bash
python3 -c "
import socket, time
s = socket.socket(); s.settimeout(5)
s.connect(('127.0.0.1', 8888))
s.sendall(b'r -c hmu CurrentConsumedPower\n')
time.sleep(0.3)
print(s.recv(4096).decode().strip())
s.close()
"
```

### Register naming: SPATIE, geen punt

ebusd gebruikt `-c CIRCUIT NAME` (spatie). Puntnotatie `circuit.name` werkt NIET voor `read`.

| Syntax | Werkt? |
|--------|--------|
| `r -c hmu CurrentConsumedPower` | ✅ |
| `r hmu.CurrentConsumedPower` | ❌ `ERR: element not found` |
| `find -c hmu` | ✅ filter op circuit |

### Multi-field registers

`find -v -c hmu` toont veldnamen. Lezen specifiek veld: `r -c hmu Status01 temp`

### Define syntax

```
define -r "r,circuit,name,label,qq,zz,msg,field,fieldname,,type,divisor,unit,comment"
```

- `r` = read type (of `r5` voor zone read)
- `qq` = master address (31 = ebusd)
- `zz` = slave address (08 = HMU, 15 = CTLV2)
- `msg` = hex message ID (B516, B524)
- `field` = field ID in de message

### B516 message fields (HMU)

Getest op HW 5103. Alleen fields 10-13 bestaan:

| Field | Type | Waarde (HWC actief) | Betekenis |
|-------|------|---------------------|-----------|
| 10 | UCH | 25-31 | Varieert |
| 11 | UCH | 2 | Constant |
| 12 | UCH | 1 | Constant |
| 13 | UIN/UCH | 800/32 | Varieert |

B516 heeft GEEN power consumption field. `PowerConsumptionHmu` met B516,14 is onmogelijk.

### Logging ebusd verkeer

`grab` commando vangt bus verkeer:
```bash
s.sendall(b"grab\n")  # start capture
s.sendall(b"grab result\n")  # get captured data
s.sendall(b"grab stop\n")  # stop capture
```

`log` commando voor debug logging:
```bash
s.sendall(b"log all debug\n")  # enable debug
s.sendall(b"log all none\n")   # disable
```

### Addon details

| Eigenschap | Waarde |
|------------|--------|
| Slug | `b4d7ad18_ebusd` |
| Versie | 26.1.8 |
| Ports | 8888 (TCP), 8889 (HTTP) |
| Toegang | `--accesslevel=*` |
| Define | `--enabledefine` |
| Device | `ens:192.168.1.131:9999` (eBUS adapter IP) |
| CSV | `vaillant/08.hmu.HW5103.csv` voor HMU |
| Protected | Ja (geen docker exec via host) |

# Home Assistant Reference

## HA API (supervisor proxy)

```bash
TOKEN=$(echo "PASSWORD" | sudo -S cat /run/s6/container_environment/SUPERVISOR_TOKEN | tr -d '\n')
```

**Token heeft trailing newline** — altijd `tr -d '\n'`.

| Action | Method + Endpoint |
|--------|------------------|
| Stop HA | `POST /api/services/homeassistant/stop` |
| Start HA (HA down) | `POST http://supervisor/homeassistant/start` |
| Start HA (HA up) | `POST /api/services/homeassistant/restart` |
| Config | `GET /api/config` |
| All states | `GET /api/states` |
| Single state | `GET /api/states/<entity_id>` |
| Reload config entry | `POST .../config_entries/entry/<entry_id>/reload` |
| Supervisor ping | `GET http://supervisor/supervisor/ping` |

**`POST http://supervisor/core/start` werkt NIET als HA down is** — core proxy offline. Gebruik `/homeassistant/start`.

Supervisor hostname resolutie faalt soms na restart. Workarounds:
```bash
curl -s --resolve supervisor:80:172.30.32.2 http://supervisor/... -H "Authorization: Bearer $TOKEN"
curl -s http://172.30.32.2/... -H "Authorization: Bearer $TOKEN"
```

## SSH

```bash
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$USER@$HOST" 'cmd'
```

**sudo**: `echo "PASSWORD" | sudo -S <cmd>` (pipe, niet heredoc).

Write files: `echo "PASS" | sudo -S tee /path/to/file > /dev/null << 'EOF'`

Python via base64 (veilige quoting):
```bash
cat > /tmp/script.py << 'PYEOF'
... python code ...
PYEOF
BASE64=$(base64 -w0 /tmp/script.py)
sshpass -p "$PASS" ssh user@host \
  "printf '%s\n' '$PASS' | sudo -S python3 -c \"import base64;exec(base64.b64decode('$BASE64').decode())\""
```

## Config Entry State

Bestand: `/config/.storage/core.config_entries` (key: `data.entries[]`)

In HA 2026.7+ wordt `state` NIET meer naar JSON geschreven. `state: None` is NORMAL. Check via states API of entities geladen zijn:
```bash
curl -s http://supervisor/core/api/states -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; s=json.load(sys.stdin); print(sum(1 for x in s if 'vaillant' in x['entity_id'].lower()))"
```

## Device Registry

Bestand: `/config/.storage/core.device_registry` (key: `data.devices[]`)

Remove by identifier:
```python
d['data']['devices'] = [e for e in d['data']['devices'] if not any(
    isinstance(t, list) and len(t) == 2 and t[0] == 'vaillant_ebus'
    for t in e.get('identifiers', [])
)]
```

## Storage Paths

| Data | Path |
|------|------|
| Config entries | `/config/.storage/core.config_entries` |
| Entity registry | `/config/.storage/core.entity_registry` |
| Device registry | `/config/.storage/core.device_registry` |
| Area registry | `/config/.storage/core.area_registry` |
| Automations | `/config/automations.yaml` |
| Scripts | `/config/scripts.yaml` |
| Dashboards | `/config/.storage/lovelace.*` of `/config/dashboards/` |
| Custom integrations | `/config/custom_components/` |
| Custom themes | `/config/themes/` |

## MQTT (core-mosquitto)

| Action | Command |
|--------|---------|
| Test | `mosquitto_sub -h core-mosquitto -u homeassistant -P 'PASSWORD' -t "topic" -v` |
| Clear retained | `mosquitto_pub -h core-mosquitto -u homeassistant -P 'PASSWORD' -t "topic" -r -n` |

Broker: Docker `core-mosquitto`, port 1883. Credentials in `/config/.storage/core.config_entries` (domain=mqtt).

## HA 2026.7 Breaking Patterns

### Sensor non-numeric value + unit

HA valideert: als `native_unit_of_measurement` gezet is, moet `native_value` numeric zijn. `"modulating"` met `°C` → ValueError.

Fix: return `None` i.p.v. string wanneer unit gezet is:
```python
@property
def native_value(self) -> float | str | None:
    raw = data.get(self._desc.key)
    if raw is None or raw in ("-", "no data stored", "empty", ""):
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        if getattr(self, '_attr_native_unit_of_measurement', None):
            return None
        return str(raw)
```

Gebruik `getattr` — niet alle entities zetten het attribute.

### Coordinator ConfigEntryNotReady loop

`async_start()` die raise't op connect failure → HA retries oneindig. Fix: catch, log, return graceful. Poll loop reconnect zelf.

### AttributeError voor optional attrs

Attributes zoals `_attr_native_unit_of_measurement` conditioneel gezet in `__init__` → gebruik `getattr` in andere methods.

### Bytecode cache

Altijd `__pycache__/` verwijderen bij deploy. Python vergelijkt `.pyc` mtime met `.py` — oude bytecode kan blijven hangen.
