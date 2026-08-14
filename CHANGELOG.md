# Changelog

## 1.2.6 - 2026-08-14

### Added

- **Manual cooling start/end dates as read/write datetime entities.** The
  myVaillant-app "cool until [date]" period is exposed from the ebusd bus. The
  registers are runtime-defined (GitHub issue john30/ebusd-configuration#644,
  verified on CTLV2 SW0514/HW1104) using the same `value,,IGN:4,,,,value,,HDA:3`
  field layout as the holiday/away date registers, with a `value,m,HDA:3` write
  route on the `0201...` write-sub. Exposed as
  `datetime.vaillant_ebus_manual_cooling_start_date` and
  `datetime.vaillant_ebus_manual_cooling_end_date` (setting the end date writes
  the new manual cooling period).
- **Climate COOL mode starts a manual cooling period.** Selecting COOL on the
  climate entity now writes the manual cooling end date (today + `COOLING_DAYS`
  days) through the runtime write route and switches the zone to auto, instead
  of writing the ineffective `night` operation mode.

## 1.2.5 - 2026-08-14

### Added

- **Discovery dumps now include structured grab telegrams:** `labeled_telegrams`
  and `unknown_telegrams` entries next to the raw `grab` lines. Unknown telegrams
  (no register label in the ebusd CSV) are candidates for runtime `define -r`
  registers absent from the installed CSV files.

### Changed

- **Discovery dump export runs in the background:** long raw eBUS traffic grabs
  no longer block the options flow, so the Home Assistant frontend does not time
  out. The export step now reports that the dump is being written instead of the
  misleading "Options successfully saved" message, and a persistent notification
  appears when the YAML file is ready.
- **Dump export step ends with an abort message** instead of a create-entry result,
  so the frontend shows the "export started" message instead of "Options
  successfully saved".

## 1.2.4 - 2026-08-13

### Added

- **Diagnostic logging:** discovery now logs each detected device (type, scan,
  register count, data count) plus a device-type summary and an entity count
  broken down by platform (sensor/binary_sensor/number/select/switch). The
  fallback read reports how many registers returned data, and every poll cycle
  logs how many registers updated. Logger names are normalized so a single
  Home Assistant logger configuration covers all integration logs:
  ```yaml
  logger:
    logs:
      custom_components.vaillant_ebus: info
  ```
  Use `debug` instead of `info` for per-register detail.

### Fixed

- **`OutsideTemp` graphable measurement (#61):** `basv3.OutsideTemp` (and the
  `ctlv2.OutsideTemp` variant) now map to `device_class=temperature`,
  `state_class=measurement`, unit °C, so the entity renders as a line graph
  instead of a string state.
- **Per-mode compressor stats (#62):** `hmu.CompressorHc` / `hmu.CompressorHwc`
  are split into `runtime` (minutes) and `cycles` (start count) fields, exposed
  as separate sensors:
  - `Compressor Runtime (HC)` / `Compressor Starts (HC)`
  - `Compressor Runtime (DHW)` / `Compressor Starts (DHW)`

  The `RunStatsCompressorHc` / `RunStatsCompressorHwc` aliases (seen on
  flexoTHERM dumps) are covered too. The raw `187055;4327` string entity is
  kept but disabled by default.
- **Electrical energy consumption sensors (#53):** `PrEnergySum`,
  `PrEnergySumHc`, `PrEnergySumHwc` (plus This/Last Month variants) are now
  exposed as energy sensors (kWh, `state_class=total_increasing`) instead of
  plain string registers. They cover the `ctlv3` and `basv3` controller
  variants via the existing metadata fallback. Values appear once the heat
  pump reports data (registers return `no data stored` while idle).

## 1.2.3 - 2026-08-12

### Added

- **`hmu.Status01` field parsing (#51):** the raw Status01 string
  (`39.5;40.5;-;-;-;off`) is now split into named fields per the ebusd CSV
  definition: `temp` (flow temperature), `temp_1` (return temperature),
  `temp_2` (outside), `temp_3` (hot water), `temp_4` (storage), and
  `pumpstate`. Flow and return temperature are exposed as numeric sensors with
  °C units. The original Status01 string entity is preserved.
- **Background analysis:** a recurring task (every 15 minutes) inspects
  registers that became live since the previous tick and automatically
  discovers new devices and entities and enables them without a restart.
  Registers that are disabled by default (e.g. `PowerConsumptionHmu`) are
  enabled as soon as they carry real data, while user-disabled entities are
  respected. A new `analyze_registers` service runs the analysis on demand.

### Fixed

- **Status01 string entity regression:** splitting the register dropped the raw
  value, leaving `sensor.vaillant_arotherm_status` frozen on its last cached
  value. The raw value is kept under the `value` field, and split fields are
  refreshed on delayed rediscovery.
- **`PowerConsumptionHmu` unit (#52):** the ebusd value is in kW but the entity
  was declared with unit W. Now reported in kW, consistent with the other power
  registers.
- **COP and room-temperature history (#54):** COP and room-temperature sensors
  render as line graphs instead of bar charts by setting
  `state_class=measurement`. Added missing mappings for `CopHcMonth`,
  `CopHwcMonth`, and `Z2RoomTemp`.
- **`BuildingCircuitFlow` unit (#55):** corrected from `l/min` to `l/h` per user
  reports.
- **Duplicate entity IDs at startup:** ebusd can report the same register under
  different capitalisation (e.g. `HwcSfMode` vs `HwcSFMode`). The entity
  factory and cache seeding now dedupe register keys case-insensitively, and
  the entity platforms dedupe by unique ID, so Home Assistant no longer logs
  "does not generate unique IDs ... already exists" at startup.

### Test fixtures

- Added the aroTHERM + EcoTEC hybrid discovery dump (`arotherm_ecotec_discovery.yaml`)
  from issue #48 with graph and fixture-load regression tests.

## 1.2.2 - 2026-07-30

### Fixed

- **Placeholder value detection:** ebusd returns `"no data stored (message not
  available due to condition)"` for registers whose hardware condition is unmet
  (e.g. `FlowPressure` when the pump is idle). The integration now treats any
  value starting with `"no data stored"` as a placeholder — consistent across
  discovery, polling, fallback reads, and sensor/switch `native_value`.
- **Building circulation pump unit:** `RunDataBuildingCPumpPower` changed from
  Watts to Percent as the ebusd value represents pump speed, not power. Added
  `BuildingCircuitPumpSpeed` with Percent unit for systems that expose it.

## 1.2.1 - 2026-07-30

### Fixed

- **Blocking file I/O in event loop:** `open()` calls in `_load_cache` and
  `_save_cache` now run via `hass.async_add_executor_job` to avoid HA warnings
  about blocking the event loop during setup and poll cycles.
- **Multi-zone cache seeding (#41):** cached controller registers now use the
  same `DiscoveryService` graph builder as live ebusd output. Active `Z2*`
  and higher-zone registers therefore create their logical zone devices and
  entities before live discovery completes.
- **Ventilation startup discovery (#38):** discovery now uses `find -a`, which
  includes ebusd write and conditional messages, and performs one additional
  full discovery pass five minutes after startup. This recovers values that
  ebusd has not populated during the initial pass without continuous rescans.
- **Duplicate find output:** when ebusd returns a register both with live data
  and `no data stored`, discovery preserves the live value regardless of line
  order.

### Cleaned up

- Removed the unused `generate_entity_descriptions()` compatibility wrapper.
- Removed the obsolete `ebus_cli.py` script, which depended on the deleted
  `EbusdTcpBackend` transport.
- Updated the developer architecture and TCP command reference to the current
  service-based implementation.

## 1.2.0 - 2026-07-29

### Refactored to service architecture

Monolithic coordinator split into 5 independent services with dedicated
test fixtures from 3 real systems (aroTHERM, flexoCOMPACT/BASV2, recoVAIR/V32).

### Technical rationale and discovery contract

The previous coordinator coupled TCP I/O, raw-value parsing, register
existence, device topology, entity generation, and HA registry state. This
made an installation-specific assumption in any layer difficult to isolate or
test.

The 1.2.0 pipeline is:

```text
ebusd find + scan metadata
  -> DiscoveryService: DeviceGraph
  -> EntityFactoryService: EntityDescriptions
  -> Home Assistant platforms
```

- The graph is derived from discovered circuits and register names. There is no
  static inventory of entities, devices, zones, or registers.
- `REGISTER_MAP` supplies presentation metadata only (name, icon, unit, and
  platform hints); it cannot create an entity for a register absent from
  discovery.
- Scan metadata and generic register-prefix rules classify known hardware.
  An unrecognized type becomes an `UNKNOWN` graph node, but retains its ebusd
  circuit, scan type, SW/HW versions, and discovered entities. Home Assistant
  can therefore expose it as `Vaillant <scan type>` without an allowlist.
- `CIRCUIT_NAMES` remains the narrow exception: it contains display labels
  only, not topology or entity-existence decisions.

New hardware support now starts with a raw `find`/scan dump: add it as a
fixture, exercise the same discovery pipeline, and assert the resulting graph
before adding any special handling.

- **EbusService** — TCP transport only, no register semantics.
- **RegisterService** — value parsing (DATA1b, EXP, BCD, IGN, STR),
  sentinel detection ("Open", "no data stored"), writeability from
  ebusd CSV metadata, read-after-write verification.
- **DiscoveryService** — data-driven device graph from `find` output:
  scan TYPE → circuit prefix → register patterns → UNKNOWN. No static device
  inventory. Zone→heating-circuit mapping, device relationships.
- **EntityFactoryService** — pure mapper from DeviceGraph to HA
  EntityDescriptions. No inline discovery, no REGISTER_MAP fallback.
- **Coordinator** — thin orchestration (577 → 371 lines). No inline
  parsing, discovery, or categorization logic.

### Breaking changes

- `backend/tcp.py` removed — use `EbusService` instead.
- `generate_entity_descriptions()` removed — use
  `EntityFactoryService.generate(graph)`.
- No REGISTER_MAP fallback entities — entity existence from discovery only.
- YAML overrides API unchanged.

### Device management

- `HIDDEN_DEVICE_KEYWORDS` — circuits matching "broadcast", "scan",
  or "general" are not created as devices. Register data preserved
  for diagnostics.
- BUS type devices (Broadcast) grouped under parent (hmu).
- Orphan circuits (no data, no parent) fully suppressed.
- **Logical entity grouping restored**: controller-owned `Z<n>*` and
  `Hc<n>*` registers are assigned to active `z<n>` devices; `Dhw*`, `Hwc*`,
  cylinder, and solar registers are assigned to the DHW device. This prevents
  no-data child nodes from folding useful entities back onto the controller.
- **Inactive secondary zones suppressed**: `z2+`/`hc2+` entities are omitted
  when their matching zone has no data, preventing ghost devices and entities.
  Explicit YAML `device_circuit` overrides continue to take precedence, and
  entity unique IDs and data keys are unchanged.
- **Stable device names**: `hmu` is shown as "Vaillant aroTHERM heat pump",
  `z1` as "Zone 1", and every `ctlv0` through `ctlv9` controller as
  "Vaillant sensoCOMFORT Control". Fixed names take precedence over scan
  metadata so existing device identifiers retain a consistent display name.
- Fallback names remain dynamic for zones (`ZN` → "Zone N") and heating
  circuits (`HcN` → "Heating Circuit N").

### Tests

- 212 total (was 41) — 171 new tests
- Raw discovery-dump coverage from three real systems: aroTHERM, community
  flexoCOMPACT/BASV2 with vwzIO, and community recoVAIR/V32.
- FakeEbusdServer for integration tests
- Community fixtures verify BASV2 controller, passive-cooling, and ventilation
  classification; unknown circuits still produce safe `UNKNOWN` nodes.
- Synthetic unknown-scan coverage verifies that unclassified devices retain
  their ebusd scan type, SW/HW versions, entities, and HA DeviceInfo.
- All services tested with mocked dependencies
- Entity-routing tests cover single-zone, active/inactive secondary-zone,
  DHW, YAML override, and dynamic `ctlv0`/`ctlv2`/`ctlv9` naming behavior.

## 1.1.2 - 2026-07-28

### No more hardcoded circuit names

- **Device type detection from eBUS scan metadata**: `_parse_find_line` now
  captures scan model lines (`scan.15 = Vaillant;BASV2;0507;1704`). The TYPE
  field (BASV2, CTLV2, HMU00, etc.) is extracted in `_parse_scan_metadata` and
  used to classify each circuit by function (`heating_controller`, `heat_pump`,
  `ventilation`, `bus`, `zone`, `dhw`).
- **Dynamic circuit→type resolution**: `_resolve_type()` maps any scan TYPE
  (including numeric variants: ctlv1-9, basv1-9) to circuit type. Circuit
  detection uses three-priority fallback: (1) scan TYPE via known device
  mapping + TYPE prefix, (2) circuit name prefix heuristic, (3) Z1OpMode
  register detection.
- **`heating_circuit` prefers data-rich circuits**: selects circuits with
  actual HVAC register data (Z1OpMode, HwcOpMode) over no-data circuits.
- **Dynamic `CIRCUIT_TO_DEVICE_ID`**: `_build_circuit_to_device_id()` builds
  circuit→scan_device mapping from scan metadata — new circuits (basv, bai,
  etc.) automatically get SW/HW info in DeviceInfo without hardcoded entries.
- **`_infer_device_circuit`**: removed `circuit == "ctlv2"` guard — name
  patterns (Hwc*, Z1*, Hc1*) are heating-controller-specific enough.
- **`get_meta` fallback**: unknown circuits fall back to `ctlv2.*` REGISTER_MAP
  entries for metadata.
- **Services YAML**: circuit dropdowns replaced with text input.
- **All platforms use `coordinator.heating_circuit`**: climate, water heater,
  switch, calendar, datetime, binary_sensor — zero hardcoded circuit names
  remaining.

## 1.1.1 - 2026-07-28

### Fix: ebusd status suffix on register values

- Register values with ebusd status suffix (`;ok`, `;err`, `;inv`, `;too_small`,
  `;too_big`, `;nan`, `;unknown`) now strip the suffix at the TCP input boundary
  (`_parse_find_line`, `async_read`) before they reach entity data. Previously
  `float("23.50;ok")` would raise `ValueError`, causing all sensors with status
  suffixes to show as `unavailable`. Affects ebusd 26.x (found on v32 ventilation
  units by @szflo).
- **Initial BASV2 support**: added `basv` to `CIRCUIT_NAMES`, `PARENT_CIRCUITS`,
  `CIRCUIT_TO_DEVICE_ID`. `heating_circuit` detection via Z1OpMode register.
  Replaced hardcoded `"ctlv2"` with `coordinator.heating_circuit` in all
  platforms.

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
