# Changelog

## 1.0.10-pre - 2026-07-24

### First-time setup

- Auto-discover ebusd in config flow: probe core-ebusd, localhost,
  127.0.0.1, homeassistant.local — only show manual form if all fail
- Validate ebusd info response: check eBUS signal + Vaillant device
  presence with specific error messages
- Repairs integration: create HA repair issue when ebusd is unreachable,
  auto-dismiss on reconnect
- Better startup logging: connect status, ebusd version, circuit names
- Diagnostics: include circuit_names list
- Update README with C6 adapter setup guide, architecture diagram,
  and simplified install flow

### Cooling support (NEW)

- Climate entity now detects cooling mode (`cool_compressor_active`)
  and displays `COOL` HVAC mode + `COOLING` action automatically
- Set cooling from HA: selecting `COOL` mode writes to `Z1CoolingTemp`
- Add `Z1CoolingTemp` as writable number entity (range 17–30°C, step 0.5)
- Fix compressor status string matching: `cool_compressor_active` was
  not recognized as active, causing `zero_idle_registers` to clear all
  compressor values during cooling

### DHW

- Limit DHW target temperature range to 35–70°C (was 30–70)
- Sync water_heater entity `min_temp` to match (35°C)

### Other

- Improve secondary zone register matching (prefix and suffix)
- Add 127.0.0.1 to discovery candidates

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

