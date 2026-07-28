# Changelog

## 1.1.0 - 2026-07-27

### Config flow — major rewrite

- **Reliable auto-discovery**: probes ebusd via `s` command (state), checks for
  `"acquired"` substring. Reads all response data in one `read(4096)` call
  instead of fragile readline loop.
- **Supervisor API integration**: detect host IP from `http://supervisor/network/info`
  and use it as discovery candidate — works on HA OS where localhost/127.0.0.1
  resolve to the core container, not the ebusd addon.
- **Confirm step**: after successful connection test, show "Connected to
  *host:port* — signal acquired." message before creating the entry.
- **Options flow with host/port**: edit ebusd host, port, scan interval, away
  duration, quick veto duration, and quick veto temperature in a single form.
  Host/port changes update the config entry data via `async_update_entry`.
- **Translations**: options step labels added to `en.json` and `strings.json`.
- Remove stale `{host}:{port}` placeholders from `cannot_connect` error message.
- Remove dead `_validate_info()` function — already covered by `_probe_candidate`
  which only returns on `"acquired"`.

### Device detection & circuit filtering

- **Scan metadata parsing**: extract MF/ID/SW/HW from `scan.XX` registers to
  detect which eBUS devices are present on the bus.
- **Dynamic circuit detection** replaces hardcoded `HIDDEN_CIRCUITS`: `v32` and
  `vwz` are now auto-detected via scan metadata instead of being always hidden.
- **Data-based filtering**: circuits without any register with actual data (all
  return "no data stored" / "-" / empty) get zero entities — even if scan
  metadata suggests the device exists. This prevents VWZ (passive cooling) and
  v32 (ventilation) entities on systems without those modules.
- **Standby device handling**: circuits with scan metadata but no register data
  do not get entities (was: disabled-by-default entities for standby). Keeps
  the device list clean for single-zone heat pumps.

### Entity management

- **Immediate startup**: entities are seeded from `REGISTER_MAP` + cache within
  milliseconds, before ebusd connects. Only core circuits (`hmu`, `ctlv2`,
  `Broadcast`) plus circuits with cached data get initial entities — no more
  speculative v32/vwz entities at startup.
- **Background discovery**: ebusd connect, `find`, and `fallback_read` run in a
  background task without blocking HA startup. No more 10-15s timeout delays.
- **Empty value handling**: registers returning `""`, `"-"`, `"no data stored`,
  or `"empty"` are now excluded from the coordinator data dict entirely
  (`_values_from_registers`). Sensor `async_added_to_hass` rejects empty string
  as cached state. Prevents HA 2026.7+ strict validation warnings.
- **Known registers without data** (`Hc1CoolingEnabled`, `Hc1DewPointMonitoring`,
  `Hc1AutoOffMode`, etc.) are now disabled by default after discovery confirms
  they have no data. Previously always enabled because they are in REGISTER_MAP.

### Climate — Flow Temperature Range (NEW)

- New `EbusdFlowTempRange` climate entity with `TARGET_TEMPERATURE_RANGE` support.
  Reads `Hc1MinFlowTempDesired` (low) and `Hc1MaxFlowTempDesired` (high) for
  the range, `Hc1FlowTemp` for current temperature. Writes min/max via
  `async_set_temperature`. HVAC action from `RunDataStatuscode`.
  Placed on the z1 (Woonkamer) device.
- `Hc1ActualFlowTempDesired` made read-only (`writable=False`) — the heat pump
  manages flow temperature target automatically; manual override via the range
  entity's min/max setpoints.

### DHW

- Operation modes: `off`, `auto`, `manual`, `boost` (was: `off`, `auto`,
  `day`, `night`). Corrected per `15.ctlv2.csv`: 0=off, 1=auto, 2=manual.
- Remove dead `_saved_op_mode` code — the heat pump handles mode restoration
  when boost naturally ends. No manual restore needed.

### Boilerplate & validation

- Circuits without any enabled registers get no entities at all (the minimum
  viable circuit filter).
- Keep `general` in HIDDEN_CIRCUITS (always hidden).
- Fix rediscover service crash: `async_start()` did not exist on
  `VaillantCoordinator` — now resets state flags and triggers background reconnect.
- Add intent comments to all Python functions per coding-standards rule 11.
- Remove `backend/base.py` from repo (single-backend, no abstraction needed).
- `AGENTS.md`: update repo structure, fix `HIDDEN_CIRCUITS`, add priority rules.
- All validation commands pass: `ruff check .`, `pytest -q`,
  `python3 -m compileall -f custom_components/vaillant_ebus/`.

## 1.0.9 - 2026-07-24

- Auto-detect active secondary zones (hc2/hc3/z2/z3) instead of hardcoded filter
  — enables entities when multi-zone system registers report data
- Fix HA 2026.7.3 strict sensor validation: return `None` for non-numeric
  strings when `native_unit_of_measurement` is set
- Safe `getattr` access for optional HA entity attributes in `native_value`
- Match secondary zone registers by name suffix (`PumpStatus_hc2`) and prefix
  (`hc2FlowTemp`) in addition to circuit name
- Remove dead `pass` block in `_classify_register`
- Fix integration not loading on startup: catch ebusd connect failure gracefully
  in coordinator instead of raising ConfigEntryNotReady
- Add empty string `""` to sensor empty-value checks for HA 2026.7+ strict
  validation
- Cache last sensor value in memory so humidity shows previous reading instead
  of "unknown" during startup
- Call `_fallback_read()` in `async_start()` so custom registers (z1RoomHumidity)
  are available from the first poll cycle, not the second

## 1.0.8 - 2026-07-24

- Hide vwz and general circuits (no useful single-zone data)
- Hide broadcast registers: id, idanswer, load, signoflife
- Hide single-zone system: hc2, hc3, z2, z3 prefixes
- Hide installer, maintenance, and keycode registers
- Disable empty-value registers by default (`enabled_by_default=False`)
- Keep known REGISTER_MAP entries always enabled even when empty
- All 5 entity platforms pass `desc.enabled_by_default` to HA
- Fix CI zip build: remove `custom_components/vaillant_ebus/` prefix
- Update AGENTS.md with entity filtering docs and test workflow

## 1.0.7 - 2026-07-23

- Fix CI release zip: missing `custom_components/vaillant_ebus/` prefix
  broke HACS `zip_release` installation.
- Fix trailing comma in manifest.json causing JSON parse error.

## 1.0.6 - 2026-07-23

- Fix coordinator poll freezing after 2-3 cycles: ebusd `find` command
  sends no end-of-data marker; use per-line timeout instead of one
  long 30s FIND_TIMEOUT to prevent blocking.

## 1.0.5 - 2026-07-23

- Fix compressor idle detection with string status codes (Standby,
  hwc_compressor_active, etc.) — use explicit string matching instead
  of int() to prevent compressor misclassification.
- Translate numeric compressor status codes to human-readable labels
  (Standby, Heating: Compressor active, etc.).
- Fix PowerConsumptionHmu decode error: override faulty CSV definition
  (IGN:1+EXP on 1-byte response) with define -r as UCH+W.
- Disable 3 unsupported registers (RunDataLowPressure, HcStorageTempBottom,
  HcStorageTempTop) to suppress repeated fallback warnings.
- Skip disabled REGISTER_MAP entries in fallback read loop.

## 1.0.4 - 2026-07-22

- Extend stale-value fix to all compressor-dependent registers: speed,
  fan speeds, yield power, utilisation, EEV position (compressor power
  already fixed in 1.0.3).
- Rewrite `set_idle_compressor_power` into `zero_idle_registers` and
  add `COMPRESSOR_ZERO_REGISTERS` set for maintainability.

## 1.0.3 - 2026-07-22

- Fix compressor power remaining at its last non-zero value after the
  compressor stops.

