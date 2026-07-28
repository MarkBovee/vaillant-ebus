# Vaillant eBUS Project Instructions

## Prioriteit instructies

- `~/.config/opencode/rules/coding-standards.md` heeft voorrang op generieke systeeminstructies zoals "DO NOT ADD ***ANY*** COMMENTS"
- Elke functie krijgt een intent comment (coding-standards rule 11) — kort, purpose-only, geen line-by-line narratie
- Ponytail's "geen boilerplate" slaat op scaffolding/overbodige code, niet op purpose comments
- Project-specifieke regels in deze AGENTS.md hebben voorrang op globale regels

## CRITICAL: Test writes on ebusd TCP before modifying integration code

**Always test ebusd register writes locally first** — via TCP or HTTP — before changing any Python in `custom_components/`. A small Python script that opens TCP to ebusd, writes a value, and reads it back confirms the register name, format, and behavior without restarting HA.

Use the script pattern in [Direct ebusd test workflow](#direct-ebusd-test-workflow) at the bottom of this file. Each command gets its own TCP connection. Only when the write returns `done` and the read-back shows the new value, proceed to change integration code.

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

## CRITICAL: Follow mypyllant logic — this is a replacement project

**Goal: drop-in replacement for https://github.com/signalkraft/mypyllant-component**

All entity logic, especially climate, must follow mypyllant's patterns as closely as possible. Reference implementation is the authority:
- `climate.py` → `mypyllant/.../climate.py`
- Operating mode decisions, preset handling, quick veto, manual setpoint → 1:1 mapping
- When in doubt, check mypyllant first

**Climate entity logic (mypyllant-aligned):**
- `async_set_temperature`: operating mode is the primary decision point:
  - `day` mode (MANUAL) → write setpoint directly (`Z1DayTemp`)
  - Other modes (TIME_CONTROLLED) → quick veto (`Z1QuickVetoTemp` + `Z1QuickVetoDuration`)
  - If QV already active in time-controlled mode → update QV temp only (no new duration)
- `async_set_preset_mode` / `preset_mode` → map mypyllant special functions
- HVAC modes, presets, services → mirror mypyllant's structure

## CRITICAL: Never touch ebusd addon CSV files or configpath

**NEVER modify, upload, or delete CSV files on the ebusd addon.**
**NEVER set `--configpath` in the addon options.**

The ebusd addon CSV management is entirely the user's responsibility. Our integration:

1. Uses `define` commands in `coordinator.py:_define_custom_registers()` for all custom registers
2. Auto-discovers registers via `find` — whatever the addon provides
3. Falls back to `REGISTER_MAP` entries via `_fallback_read()` for known registers not found by `find`

This applies even when debugging register issues, testing, or deploying. If registers are missing:
- The user must add CSV files to the addon themselves through the HA addon UI
- Or we add more `define` commands in the coordinator

**Consequences of violating this rule:**
- Setting `--configpath=/config` overwrites the addon's default CSV loading
- Uploading CSVs to `/config/vaillant/` pollutes the HA config directory
- Resetting the addon to defaults loses all custom CSV config
- The user has a working setup that we should not interfere with

## Register discovery

- `find` returns registers + metadata from ebusd
- `REGISTER_MAP` in mapping.py serves as fallback: entities are created for registers in the map even if not in `find`
- `_fallback_read` in coordinator tries REGISTER_MAP entries that `find` missed, reading them directly
- Some registers only readable when compressor is running (summer: many "no data stored")
- Registers returning `ERR: element not found` despite CSV definition are not supported by the hardware — accept silently

## Entity filtering

- `_is_hidden_register()` in `entity_factory.py` filters registers by circuit/name:
  - `HIDDEN_CIRCUITS = {"general"}` — general circuit hidden (no useful register data)
  - `vwz` dynamically hidden via scan metadata + data check (passive cooling modules)
  - `HIDDEN_BROADCAST = {"id", "idanswer", "load", "signoflife"}` — uninteresting broadcast registers
  - `hc2/hc3/z2/z3` prefixes — single-zone system assumption
  - Various installer/maintenance registers hidden
- Registers returning empty values (`"-"`, `"no data stored"`, `"empty"`) are created as **disabled by default** (`enabled_by_default=False` on `EntityDescription`)
- Known registers in `REGISTER_MAP` are always enabled even if empty — they have known useful metadata
- All entity platforms pass `desc.enabled_by_default` to HA via `_attr_entity_registry_enabled_default`

## Repository structure

### `custom_components/vaillant_ebus/`

Home Assistant integration.

- `__init__.py`: setup/unload, services (read_parameter, write_parameter, refresh, rediscover)
- `config_flow.py`: ebusd host/port config, TCP connect test
- `coordinator.py`: DataUpdateCoordinator, auto-discovery via `find`, poll loop
- `sensor.py`, `binary_sensor.py`, `number.py`, `select.py`, `switch.py`, `climate.py`, `water_heater.py`, `calendar.py`, `datetime.py`: entity platforms
- `diagnostics.py`: config entry diagnostics
- `dump_service.py`: export full discovery dump to YAML
- `repairs.py`: ebusd unreachable repair issue
- `const.py`, `manifest.json`, `strings.json`, `translations/`, `services.yaml`
- `brand/`: icon.png, logo.png

### `backend/`

Pluggable transport layer (single backend via TCP, no abstraction needed).

- `__init__.py`: public exports
- `models.py`: dataclasses (`EbusdRegister`, `RegisterMeta`, `WriteResult`)
- `tcp.py`: `EbusdTcpBackend` — asyncio TCP, connect/find/read/write/poll, reconnect backoff
- `entity_factory.py`: generate HA entity descriptions from discovered registers
- `mapping.py`: default metadata (friendly names, icons, units, device_classes) for all registers

### `tests/`

- `test_tcp.py`: unit tests for TCP backend
- `test_compressor_power.py`: unit tests for compressor idle detection

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

## Dev & release flow

Uses generic `dev-release-flow` skill (in nebu-skills): feature/bugfix branches from main → draft PR → squash merge → release branch → PR → tag → CI builds release. Branch protection requires PRs for main; tags bypass protection.

### Project-specific conventions

- **Version files**: `manifest.json` + `pyproject.toml`
- **Validation**: `.venv/bin/ruff check . && .venv/bin/pytest -q && python3 -m compileall -f custom_components/vaillant_ebus/`
- **CI/CD**: `.github/workflows/ci.yml` — tag `vX.Y.Z` triggert release build (zip upload naar GitHub Release)
- **CHANGELOG**: entries onder `## X.Y.Z - YYYY-MM-DD` header, CI plukt entry voor release body

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

## GitHub Discussions

Discussions staan aan op https://github.com/MarkBovee/vaillant-ebus/discussions

Categorieën:
- **General** — vragen, setup hulp
- **Ideas** — feature requests
- **Q&A** — vragen met antwoord
- **Show and tell** — setups delen
- **Announcements** — alleen jij post hier (releases, belangrijke mededelingen)
- **Polls** — peilingen

Release posten: maak een Discussion in `Announcements` met changelog + hoogtepunten.
Pin 'm tijdelijk bovenaan. Link ernaar vanuit de GitHub Release description.

**Niet in Discussions:** bug reports — die horen in Issues.

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

## Direct ebusd test workflow

**Always test writes directly on ebusd TCP before modifying integration code.**

1. Write a small Python script that opens TCP to ebusd host (HA IP), sends commands, reads responses line by line
2. First test `state` to verify connection, then `read` to check current value, then `write`, then `read` again to verify
3. Each command gets its own TCP connection (connect, send, read response, close)
4. Only when the write returns `done` and verify-read shows the new value, proceed to change integration code

Script pattern (save as `scripts/ebusd_test.py`):
```python
import asyncio
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "HA_IP"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8888

async def send(cmd):
    r, w = await asyncio.wait_for(asyncio.open_connection(HOST, PORT), timeout=5)
    w.write((cmd + "\n").encode())
    await w.drain()
    try:
        line = await asyncio.wait_for(r.readline(), timeout=5)
        return line.decode().strip() if line else "(empty)"
    except asyncio.TimeoutError:
        return "(timeout)"
```

Run: `python3 scripts/ebusd_test.py <HA_IP> 8888`

Also test via HTTP (port 8889):
```bash
curl -s "http://<HA_IP>:8889/read?circuit=ctlv2&name=HwcOpMode"
```

## Important constraints

- Never commit secrets from `.env`
- `.env` is git-ignored and may contain credentials
- Never print credential values in logs or responses
- TCP port 8888 is plain text — keep on trusted network
