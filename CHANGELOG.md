# Changelog

## 1.1.1 - 2026-07-28

### Fix: ebusd status suffix on register values

- Register values with ebusd status suffix (`;ok`, `;err`, `;inv`, `;too_small`,
  `;too_big`, `;nan`, `;unknown`) now strip the suffix at the TCP input boundary
  (`_parse_find_line`, `async_read`) before they reach entity data. Previously
  `float("23.50;ok")` would raise `ValueError`, causing all sensors with status
  suffixes to show as `unavailable`. Affects ebusd 26.x (found on v32 ventilation
  units by @szflo). Safety net in `_values_from_registers` handles cached values
  from previous versions.

### Refactor: dynamic circuit type detection (removes hardcoded circuit names)

- **Device type detection from eBUS scan metadata**: `_parse_find_line` now
  captures scan model lines (`scan.15 = Vaillant;BASV2;0507;1704`). The TYPE
  field (BASV2, CTLV2, HMU00, etc.) is extracted in `_parse_scan_metadata` and
  used to classify each circuit by function (`heating_controller`, `heat_pump`,
  `ventilation`, `diagnostic`, `zone`, `dhw`).
- **Three-priority fallback chain**: (1) scan TYPE → circuit via model prefix
  matching (any numeric variant: basv1-9, ctlv1-9, z1-9). (2) circuit name
  prefix heuristic. (3) Z1OpMode register detection (existing behavior).
- **New coordinator API**: `circuits_by_type("heating_controller")` returns all
  matching circuits. `heating_circuit` property preserved as backward-compat
  wrapper around the first result.
- **All platforms use `coordinator.heating_circuit`** instead of hardcoded
  `"ctlv2"`. Climate, water heater, switch, calendar, datetime, binary_sensor
  — zero hardcoded circuit names remaining.
- **`_infer_device_circuit`**: removed `circuit == "ctlv2"` guard. Name
  patterns (Hwc*, Z1*, Hc1*) are heating-controller-specific enough to work on
  any circuit.
- **`get_meta` fallback**: unknown circuits (e.g. `basv`) fall back to
  `ctlv2.*` REGISTER_MAP entries for metadata.
- **Services YAML**: circuit dropdowns replaced with text input (accepts any
  discovered circuit name).
- **`PARENT_CIRCUITS` and `CIRCUIT_TO_DEVICE_ID`**: `basv` added alongside
  `ctlv2` for device ID 15.
- **`CIRCUIT_NAMES`**: `"basv": "Vaillant BASV2 (Heating Control)"` added.

## 1.1.0 - 2026-07-28

### Config flow — major rewrite

- **Reliable auto-discovery**: probes ebusd via `s` command, checks for
  `"acquired"` substring. Supervisor API integration detects host IP from
  `http://supervisor/network/info` for HA OS compatibility.
- **Confirm step**: shows "Connected to host:port — signal acquired." before
  creating the entry.
- **Options flow with host/port**: edit ebusd host, port, scan interval, away
  duration, quick veto duration and temperature in one form. Host/port changes
  update the config entry data via `async_update_entry`.
- Remove stale `{host}:{port}` placeholders from error messages.
- Remove dead `_validate_info()` — `_probe_candidate` already checks for `"acquired"`.

### Device detection & circuit filtering

- **Scan metadata parsing**: extract MF/ID/SW/HW from `scan.XX` registers to
  detect which eBUS devices are present on the bus.
- **Dynamic circuit detection**: VWZ (ventilation) and v32 (passive cooling)
  modules auto-detected instead of hardcoded hidden circuits.
- **Data-based filtering**: circuits without actual data get zero entities —
  prevents ghost entities for missing hardware.
- **Immediate startup**: entities seeded from `REGISTER_MAP` + cache within
  milliseconds, before ebusd connects.
- **Background discovery**: connect, `find`, and `fallback_read` run in a
  background task without blocking HA startup.

### Entity improvements

- **Flow Temperature Range (NEW)**: `EbusdFlowTempRange` climate entity with
  `TARGET_TEMPERATURE_RANGE` support. Reads min/max flow temp desired, writes
  via `async_set_temperature`. Placed on z1 (Woonkamer) device.
- **DHW modes corrected**: `off`, `auto`, `manual`, `boost` (was `day`/`night`).
  Dead `_saved_op_mode` code removed — heat pump handles mode restoration.
- **Empty value handling**: registers returning `""`, `"-"`, `"no data stored"`,
  or `"empty"` excluded from coordinator data and shown as unavailable.
- **Known registers without data** (`Hc1CoolingEnabled`, etc.) disabled by
  default after discovery confirms no data.
- `Hc1ActualFlowTempDesired` made read-only — heat pump manages flow target
  automatically; use the range entity for min/max overrides.

### Fixes & cleanup

- Fix rediscover service crash: `async_start()` did not exist on
  `VaillantCoordinator` — now resets state and triggers background reconnect.
- Add intent comments to all Python functions per coding-standards rule 11.
- Remove `backend/base.py` (single-backend, no abstraction needed).
- Update `AGENTS.md`: repo structure, `HIDDEN_CIRCUITS`, priority rules.
- All validation commands pass.

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

