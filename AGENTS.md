# Vaillant eBUS Project Instructions

## Language

- All code, commit messages, documentation, logs, UI strings, and technical names: **English**

## Commit message conventions

Format: `type(scope): short description` (subject ≤ 50 chars, lowercase after colon)

Types:
| Type | When to use |
|------|-------------|
| `feat` | New feature for the user (entity, service, integration) |
| `fix` | Bug fix |
| `chore` | Maintenance, tooling, deps, cleanup, refactoring |
| `docs` | Documentation only |
| `ci` | CI workflow changes |
| `release` | Version bump + release commit (matches tag) |
| `test` | Adding or updating tests |

Rules:
1. Subject line: ≤ 50 chars, lowercase after `type:`, no period at end
2. Body (optional): wrap at 72 chars, bullet points with `- ` prefix
3. Scope (optional but encouraged): `coordinator`, `tcp`, `sensor`, `config_flow`, `ci`, `deps`, etc.
4. Release commits: `release: vX.Y.Z` with tag `vX.Y.Z`
5. One logical change per commit — squash related WIP/fixup commits before push

Examples:
```
chore(deps): bump actions/checkout from v4 to v7
docs: add troubleshooting guide for connection issues
fix(sensor): handle empty register values as unavailable
release: v1.0.2
```

## Project summary

- Project: `vaillant-ebus`
- Goal: local Home Assistant integration for Vaillant heat pumps via ebusd TCP
- ebusd runs as HA addon, connected to aroTHERM via network eBUS adapter
- HA custom_component connects directly to ebusd TCP port 8888 — no MQTT, no cloud
- 350+ registers auto-discovered, entities generated dynamically

## ebusd addon CSV management

The addon data directory is mounted as `/etc/ebusd/` in the ebusd container. CSV files in `vaillant/` subdirectory are loaded at startup.

To update CSV set:
1. Clone `https://github.com/john30/ebusd-configuration.git`
2. `npm install && npm run compile-en`
3. Upload `outcsv/@ebusd/ebus-typespec/vaillant/*.csv` to the ebusd addon `vaillant/` directory
4. Restart ebusd addon

**Important**: `--configpath=/config` overrides default config path and breaks standard CSV loading. Only use with a complete CSV set at that location.

## Register discovery

- `find` returns registers + metadata from ebusd
- `REGISTER_MAP` in mapping.py serves as fallback: entities are created for registers in the map even if not in `find`
- `_fallback_read` in coordinator tries REGISTER_MAP entries that `find` missed, reading them directly
- Some registers only readable when compressor is running (summer: many "no data stored")
- Registers returning `ERR: element not found` despite CSV definition are not supported by the hardware — accept silently

## Entity filtering

- `_is_hidden_register()` in `entity_factory.py` filters registers by circuit/name:
  - `HIDDEN_CIRCUITS = {"vwz", "general"}` — ventilation and general circuits hidden (no useful data on single-zone systems)
  - `HIDDEN_BROADCAST = {"id", "idanswer", "load", "signoflife"}` — uninteresting broadcast registers
  - `hc2/hc3/z2/z3` prefixes — single-zone system assumption
  - Various installer/maintenance registers hidden
- Registers returning empty values (`"-"`, `"no data stored"`, `"empty"`) are created as **disabled by default** (`enabled_by_default=False` on `EntityDescription`)
- Known registers in `REGISTER_MAP` are always enabled even if empty — they have known useful metadata
- All 5 entity platforms (sensor, binary_sensor, number, select, switch) pass `desc.enabled_by_default` to HA via `_attr_entity_registry_enabled_default`

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

### `tests/`

- `test_model.py`: unit tests for backend models

## Validation commands

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
python3 -m compileall -f custom_components/vaillant_ebus/
```

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

## CRITICAL: Do not remove or modify the following

### `coordinator.py:_define_custom_registers()`
- **Must stay.** Defines runtime registers at ebusd startup via `define` command.
- Currently defines `ctlv2.z1RoomHumidity` — NOT discoverable via `find` (r5 message type).
- Agents refactoring `coordinator.py` or rewriting startup flow **must preserve this method and its call**.
- Removing this will break room humidity until HA is restarted.

### `coordinator.py:_fallback_read()` entity registration
- `_fallback_read()` reads registers from REGISTER_MAP that `find` missed (like `z1RoomHumidity`).
- When it finds a new register, it must also regenerate `self.entities` via `generate_entity_descriptions()`.
- **If you refactor `_fallback_read()`**, ensure newly added registers trigger entity regeneration.

### `sensor.py:native_value` None-check
- Handles `"-"`, `"no data stored"`, `"empty"` from ebusd as `None` (unavailable) instead of passing them as string values to HA.
- **Must stay.** Without it, sensors with idle registers show garbage string values in HA.

### `backend/tcp.py:async_send_raw()`
- Public method used by `_define_custom_registers()` to send raw `define` commands to ebusd.
- **Must stay** as long as `_define_custom_registers()` exists.

## Known limitations

- Most heat pump registers show "no data stored" when compressor is idle (summer) — these entities are disabled by default
- Entity classification (sensor vs number vs select) needs YAML overrides for best results
- Native unit inference for uncommon registers is incomplete

## File Upload (SSH)

For uploading files to a remote server via SSH:
```bash
PAYLOAD=$(base64 -w0 /local/path/to/file)
sshpass -p 'PASSWORD' ssh user@host \
  'echo "PASSWORD" | sudo -S python3 -c "import sys,base64;open(\"/remote/path/file\",\"w\").write(base64.b64decode(sys.argv[1]).decode())" "'"${PAYLOAD}"'"
```

For large files (>40KB): split and append.

## Branch workflow

- **`main`** — enige branch. Kleine fixes direct op `main`, grotere features op feature branch.
- **Feature branches:** `git checkout -b feat/description` → werk → PR → squash merge naar `main`.
- **Releases:** commit + tag direct op `main` (git push origin main --tags).

```
main ──feature branch──► PR (squash) ──► main ──tag──► release
```

Niet meer gebruiken: `pre-release` branch (verwijderd). Alles op `main`.

## Release workflow

**Process (CI/CD in `.github/workflows/ci.yml`):**

1. **Zorg dat `main` up-to-date is** — `git checkout main && git pull`
2. **Bump version + changelog — aparte commit:**
   - update `manifest.json` + `pyproject.toml`
   - update `CHANGELOG.md` — entry onder nieuwe versie
3. **Commit + tag + push:**

   ```bash
   git add -A
   git commit -m "release: vX.Y.Z"
   git tag vX.Y.Z
   git push origin main --tags
   ```

4. **CI/CD doet de rest:**
   - `release` job: lint + test + compile → bouwt zip → `gh release create`
   - Changelog-entry wordt automatisch uit `CHANGELOG.md` geplukt

### CRITICAL: zip structuur

De zip mag GEEN `custom_components/vaillant_ebus/` prefix hebben.  
HACS downloadt de zip en pakt uit naar `custom_components/vaillant_ebus/` — bestanden moeten direct in de zip root staan, niet in een submap.

**Juiste build (CI step in `.github/workflows/ci.yml`):**
```yaml
- name: Build release zip
  run: |
    git archive --format=tar HEAD custom_components/vaillant_ebus | tar xf - -C /tmp
    cd /tmp/custom_components/vaillant_ebus && zip -qr /tmp/vaillant_ebus.zip .
    rm -rf /tmp/custom_components
```

**Verkeerd (NIET doen):**
- `zip -qr ... custom_components/vaillant_ebus` — geeft prefix, HACS vindt niks ❌
- `git archive --prefix` met path filter — geeft double nesting ❌

**Verifiëren na build:**
```bash
unzip -l /tmp/vaillant_ebus.zip | head -5
# Moet tonen: __init__.py (direct in root, NIET in custom_components/ submap)
```

**Herstellen van verkeerde zip:** verwijder oude asset, bouw correcte zip, upload:
```bash
# Verwijder corrupte asset
gh release delete-asset vX.Y.Z vaillant_ebus.zip --yes

# Bouw correcte zip (zip vanuit de subdirectory, geen prefix)
cd $(mktemp -d)
git archive --format=tar HEAD custom_components/vaillant_ebus | tar xf -
cd custom_components/vaillant_ebus && zip -qr /tmp/vaillant_ebus.zip .
rm -rf /tmp/custom_components

# Upload met exact de naam vaillant_ebus.zip
gh release upload vX.Y.Z /tmp/vaillant_ebus.zip --clobber

# Verifieer
unzip -l /tmp/vaillant_ebus.zip | head -5
# Moet tonen: __init__.py (direct in root, NIET in submap!)
```

**Alternatief (geen `zip` tool, Python):**
```bash
gh release delete-asset vX.Y.Z vaillant_ebus.zip --yes
cd /tmp
git archive --format=tar HEAD custom_components/vaillant_ebus | tar xf -
cd custom_components/vaillant_ebus
python3 -c "
import zipfile, os
with zipfile.ZipFile('/tmp/vaillant_ebus.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk('.'):
        for fn in files:
            fp = os.path.join(root, fn)
            z.write(fp, os.path.relpath(fp, '.'))
"
cd /tmp && rm -rf custom_components
gh release upload vX.Y.Z /tmp/vaillant_ebus.zip --clobber
```

### Release mislukt

**Let op:** als de CI al een (corrupte) zip heeft geüpload, overschrijft een hernieuwde CI-run de asset niet — `gh release create` faalt omdat de release al bestaat, en `gh release upload` zonder `--clobber` overschrijft niet. Eerst handmatig verwijderen of opnieuw taggen:

**Optie A — asset vervangen (behoudt release + tag):**
```bash
# Verwijder corrupte asset
gh release delete-asset vX.Y.Z vaillant_ebus.zip --yes

# Bouw correcte zip (zie hierboven) en upload
gh release upload vX.Y.Z /tmp/vaillant_ebus.zip --clobber
```

**Optie B — volledig opnieuw (verwijdert release + tag):**
```bash
gh release delete vX.Y.Z --yes && git push --delete origin vX.Y.Z
git tag -d vX.Y.Z && git tag vX.Y.Z && git push origin main --tags
```

**Belangrijk:** branch protectie op `main` staat aan (`require PR`).  
Force-push alleen via `gh api repos/.../branches/main/protection --method DELETE` en later herstellen.

HACS `zip_release` mode verwacht GitHub release met tag `vX.Y.Z` en asset `vaillant_ebus.zip`. `hacs.json` heeft `zip_release: true` en `hide_default_branch: true`.

HA update via HACS: `HACS > integrations > Vaillant eBUS > download vX.Y.Z > herstart HA`.

## Local test workflow (push branch to HA)

Test een feature branch op de lokale HA installatie voordat je merged:

```bash
# 1. Valideer
.venv/bin/ruff check . && .venv/bin/pytest -q && python3 -m compileall -f custom_components/vaillant_ebus/

# 2. Bouw zip (zonder prefix, direct in root)
cd /tmp && rm -rf custom_components && \
git -C /pad/naar/vaillant-ebus archive --format=tar HEAD custom_components/vaillant_ebus | tar xf - && \
cd custom_components/vaillant_ebus && \
python3 -c "import zipfile, os; z=zipfile.ZipFile('/tmp/vaillant_ebus_branch.zip','w',zipfile.ZIP_DEFLATED);[z.write(os.path.join(r,f),os.path.relpath(os.path.join(r,f),'.')) for r,_,fs in os.walk('.') for f in fs]" && \
cd /tmp && rm -rf custom_components

# 3. Upload via SMB (credentials uit .env: HA_USER, HA_PASSWORD)
HA_USER=$(grep HA_USER /pad/naar/vaillant-ebus/.env | cut -d= -f2-)
HA_PASS=$(grep HA_PASSWORD /pad/naar/vaillant-ebus/.env | cut -d= -f2-)
smbclient //HA_IP/CONFIG -U "${HA_USER}%${HA_PASS}" -c "put /tmp/vaillant_ebus_branch.zip vaillant_ebus_branch.zip"

# 4. Unzip op HA (vervangt oude bestanden)
PASS=$(grep HA_SSH_PASSWORD /pad/naar/vaillant-ebus/.env | cut -d= -f2-)
ssh -o StrictHostKeyChecking=no "markbovee@HA_IP" \
  "printf '%s\n' '$PASS' | sudo -S bash -c 'cd /config/custom_components/vaillant_ebus && rm -f *.py *.json *.yaml && rm -rf backend brand translations && unzip -o /config/vaillant_ebus_branch.zip && rm -f /config/vaillant_ebus_branch.zip'"

# 5. HA herstarten
TOKEN=$(ssh -o StrictHostKeyChecking=no "markbovee@HA_IP" "printf '%s\n' '$PASS' | sudo -S cat /run/s6/container_environment/SUPERVISOR_TOKEN")
ssh -o StrictHostKeyChecking=no "markbovee@HA_IP" "curl -s -X POST http://supervisor/core/api/services/homeassistant/stop -H 'Authorization: Bearer $TOKEN'"
sleep 10
ssh -o StrictHostKeyChecking=no "markbovee@HA_IP" "curl -s -X POST http://supervisor/core/start -H 'Authorization: Bearer $TOKEN'"
sleep 15

# 6. Check of HA online is
curl -s -o /dev/null -w '%{http_code}' http://HA_IP:8123/
```

### Device registry opschonen

Als er stale apparaten of entities achterblijven na een update, stop HA en pas het registry bestand aan:

```bash
# Stop HA (zie stap 5), pas device_registry aan, start HA
ssh -o StrictHostKeyChecking=no "markbovee@HA_IP" \
  "printf '%s\n' '$PASS' | sudo -S python3 -c '
import json
with open(\"/config/.storage/core.device_registry\") as f:
    d = json.load(f)
d[\"data\"][\"devices\"] = [e for e in d[\"data\"][\"devices\"] if not any(
    isinstance(t, list) and len(t) == 2 and t[0] == \"vaillant_ebus\" and t[1] in (\"vwz\", \"General\")
    for t in e.get(\"identifiers\", [])
)]
with open(\"/config/.storage/core.device_registry\", \"w\") as f:
    json.dump(d, f, indent=2)
print(\"Cleaned up\")
'"
```

Hetzelfde patroon werkt voor `core.entity_registry` (entires met `vaillant_ebus` in `platform` of `unique_id`).

## Important constraints

- Never commit secrets from `.env`
- `.env` is git-ignored and may contain credentials
- Never print credential values in logs or responses
- TCP port 8888 is plain text — keep on trusted network
