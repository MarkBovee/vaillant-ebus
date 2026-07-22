# Vaillant eBUS Project Instructions

## Language

- All code, commit messages, documentation, logs, UI strings, and technical names: **English**

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

- Most heat pump registers show "no data stored" when compressor is idle (summer)
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

## Release workflow

```bash
# Bump version in manifest.json + pyproject.toml
# Commit: "chore: bump version to X.Y.Z"
git tag vX.Y.Z
git push origin vX.Y.Z

# Create release zip and GitHub release
git archive --format=zip -o /tmp/vaillant_ebus.zip vX.Y.Z custom_components/vaillant_ebus/
gh release create vX.Y.Z /tmp/vaillant_ebus.zip \
  --title "vX.Y.Z" --notes "Release notes." \
  --repo MarkBovee/vaillant-ebus
rm /tmp/vaillant_ebus.zip
```

HACS `zip_release` mode expects a GitHub release with tag `vX.Y.Z` and asset `vaillant_ebus.zip`. The `hacs.json` has `zip_release: true` and `hide_default_branch: true`.

## Important constraints

- Never commit secrets from `.env`
- `.env` is git-ignored and may contain credentials
- Never print credential values in logs or responses
- TCP port 8888 is plain text — keep on trusted network
