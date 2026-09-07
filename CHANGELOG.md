# Changelog

## 1.6.2 - 2026-09-08

### Added

- **eloBLOCK mode override service.** Added `set_mode_override` and
  `clear_mode_override` services for the B510 thermostat override, including a
  50-second keep-alive while enabled.
- **eloBLOCK gas-entity filtering.** Confirmed eloBLOCK hardware now disables
  gas and combustion-only BAI entities by default without hiding them from
  discovery.

## 1.6.1 - 2026-09-08

### Added

- **eloBLOCK VE 28 support coverage.** Added metadata and fixture-driven
  discovery coverage for observed BAI temperature, pressure, heating-stage,
  status, and energy registers from issue #103.
- **HMUX0 status coverage.** Added parsed flow/return temperatures for HMUX0
  `Status01` alongside the confirmed yield/COP fixture coverage from issue #99.

## 1.6.0 - 2026-09-06

### Added

- **HA-MCP-first inspection workflow.** Project guidance now requires HA-MCP
  as the primary read-only method for inspecting live Home Assistant state,
  diagnostics, devices, entities, and logs.
- **Rediscover eBUS from Options.** The Options Flow now exposes a confirmed
  **Rediscover eBUS** action that reconnects to ebusd and rebuilds the device
  and entity discovery graph.
- **Purge stale entities from Options.** The **Purge Stale Entities** action
  removes only Vaillant eBUS registry entries that are no longer present in
  the current discovery graph and requires explicit confirmation.

### Fixed

- **Stale device assignment.** `sc.HydraulicScheme` is assigned to the
  Vaillant sensoCOMFORT heating controller instead of creating a separate
  empty `Vaillant sc` device.
- **No-data entity lifecycle.** Unknown and unavailable registry entities are
  integration-disabled without depending on a state object already existing
  during setup. User-disabled entities remain untouched and live registers can
  be enabled again when data appears.
- **Invalid registry disabler value.** Entity registry updates now use
  Home Assistant's `RegistryEntryDisabler.INTEGRATION` enum.
- **Invalid `SourceTempInput` stubs.** Air/water B51A stub values such as
  `-1011.06` are filtered before discovery and remain unavailable.
- **Stale detection repair.** Successful discovery clears obsolete
  `detection_incomplete` repair issues.
- **Scan interval consistency.** Runtime coordinator setup now honors the
  configured Options Flow value before falling back to entry data.
- **Placeholder defaults.** Unknown registers without usable data no longer
  become enabled entities merely because their device has other live data;
  mapped hardware variants and live energy registers remain supported.
- **HMUX0 yield/COP coverage.** Added fixture-driven coverage for HMUX0
  `RunDataReturnTemp`, heating/DHW yield counters, and heating/DHW COP sensors
  reported in issue #99.

- **Solar controller placeholder device is suppressed.** Registers whose
  semicolon-separated fields are all no-data placeholders no longer make an
  otherwise empty circuit appear as a device. This removes the unsupported
  `sc` ghost device without hiding real live values.
- **Purge safety.** Entity purge refuses to run without an active ebusd
  connection and non-empty current discovery data.

- **Purge cannot remove all entities.** The purge action now refuses to run
  unless ebusd is connected and current discovery produced entities.

- **Unknown cache values no longer create entities.** Cache seeding ignores
  `unknown`, `unavailable`, `empty`, and `-` sentinel values instead of treating
  them as discovered register data.
- **Discovery dump failures are visible.** Export now raises a Home Assistant
  error and creates a persistent notification when ebusd is disconnected,
  instead of silently doing nothing.
- **aroTHERM Pro 7 return temperature metadata.** `hmux`/`hmux0`
  `RunDataReturnTemp` values now render as temperature sensors.

## 1.5.5 - 2026-09-05

### Fixed

- **Energy counters no longer require a reload (#53, #97).** Supported
  runtime-defined B516 energy counters are actively read every five minutes,
  rather than relying on ebusd's unpolled cache. Daily and monthly definitions
  refresh their date payload during operation, including across month boundaries.
  Cached counters recover after no-data discovery, and runtime definitions are
  restored after an ebusd transport reconnect.
- **Rediscovery adds newly found entities to Home Assistant (#96).** Initial,
  manual, and delayed discovery now publish additions to loaded platforms without
  duplicating existing entities. Newly readable fallback registers also generate
  entities. Discovery logs include the number of new entities; use
  `export_discovery_dump`, not `rediscover`, to export a capture.
- **Cached register name casing no longer creates duplicate entities.** Live
  discovery updates the existing entity's lookup key when ebusd uses different
  capitalization from the saved cache.
- **Discovery dumps include the ebusd version (#95).** Dump metadata now uses
  the connected transport's version instead of leaving it empty.

## 1.5.4 - 2026-08-27

### Added

- **Read-only cooling-program calendars (#92).** The bus carries separate
  per-day cooling schedules (`Z1CoolingTimer_*` / `Z2CoolingTimer_*`) alongside
  the heating (`CcTimer`), zone (`Z1Timer`), and DHW (`HwcTimer`) programs, which
  is what the Vaillant app uses for heating and cooling intervals independently.
  Adds additive **"Cooling Program"** and **"Cooling Program 2"** calendar
  entities that populate from those registers and stay empty on hardware that
  does not expose them. The write side (setting intervals from Home Assistant)
  remains a follow-up.

### Fixed

- **DHW boost switch/water-heater state (#31).** `HwcSFMode` reports "load"
  while the cylinder is actively charging even after boost is turned off, so a
  switch reading the raw register could never flip back to off until the charge
  finished. The boost switch and water heater now track the desired DHW boost
  state (falling back to the raw register on first load), so the switch reflects
  a toggle immediately. The `HwcSFMode` write is now verified non-strictly
  (ebusd answers "done" while the physical state lags the accepted write); all
  other writes keep strict read-back verification. MichaelLachmann's boost
  on/off discovery dumps were adopted as community fixtures with a regression
  test.

## 1.5.3 - 2026-08-27

### Added

- **Daily electric consumption for cooling, heating, and DHW (#50).** The b516
  statistics API now also defines daily electric counters (`CoolElecConsDay`,
  `HcElecConsDay`, `HwcElecConsDay`) alongside the existing lifetime totals,
  so the daily `Consumed Electrical Energy Cooling` value shown in the
  myPyllant app has a matching sensor. Lifetime electric totals for heating
  (`HcElecConsTotal`) and DHW (`HwcElecConsTotal`) are added as well, using
  the same live-verified layout (upstream issue john30/ebusd-configuration
  #490; X=0 total / X=1 day, Y=3 electric, Z=3 heating / Z=4 hot water /
  Z=5 cooling).
- **Additional electric registers from the standard `find` output (#50).**
  `hmu.ConsumptionTotal` (kWh), `hmu.RunDataElectricPowerConsumption` (W),
  `hmu.LiveMonitorCurrentConsumedPower` (kW), and the `hmu.StatSolarEnergySum*`
  family (kWh) now get proper metadata. These supplement the runtime-defined
  b516 counters and stay opt-in: entities appear only when the discovery graph
  carries the register with data.

### Fixed

- **v32 gas boiler (ecoTEC plus via VR32) register handling (#83).** Registers
  from the bai CSV now get proper metadata (temperatures in °C, hour counters
  as `duration` with `total_increasing`, pump power in W, water pressure in
  bar), multi-field values are split (`ReturnTemp` no longer shows
  `55.31;64650;ok`, `Status01`/`Status02` become individual sensors), and
  sensor-fault values (`;circuit`, `;cutoff`) are treated as no data instead
  of exposing bogus readings like `HwcTemp = 116.06;circuit`. Ventilation-only
  registers (e.g. `BypassPosition`, `ExhaustAirHumidity`) stay absent on
  boiler setups, guarded by a new community fixture test.

## 1.5.2 - 2026-08-25

### Added

- **`SourceTempInput` runtime definition restored with an upstream-verified
  layout (#49).** The register was attempted during v1.3.3 development but
  never shipped. The layout (`B51A` / `05ff3222`, `IGN:3 + D2C`) is verified
  live on brine units in `john30/ebusd-configuration` PR #565 (flexoTHERM and
  flexoCOMPACT ground-source). On air/water units the B51A reply is a 3-byte
  stub that cannot decode — the register correctly stays unavailable there,
  and the decode error is filtered as no-data so nothing broken appears in
  the UI.
- **Bare `ERR:` read replies count as no-data.** Direct ebusd reads return
  `ERR: ...` without parentheses; the shared no-data helper now recognizes
  that form alongside the parenthesized `(ERR ...)` find output.
- **B524 heating-circuit state sensors for HC1 and HC2 (discussion #60).**
  Twelve read-only registers absent from the shipped CSVs are defined at
  runtime from the Helianthus B524 register map: calculated flow temperature,
  mixer position, circuit humidity, dew point temperature, pump hours, and
  pump starts per circuit. Message layout (`OP=0x02 GG=0x02`, RR `0x20`–`0x25`)
  is verified against the upstream `15.ctlv2.tsp` and compiled eBUS CSVs, and
  the wire types (`EXP` f32, `ULG` u32) against ebusd `datatype.cpp`. The
  layout is fixture-gated; hardware without the registers stays no-data.

## 1.5.1 - 2026-08-25

### Added

- **Mode-aware target temperature, live-verified against ctlv2 hardware.**
  `async_set_temperature` now follows mypyllant semantics: time-controlled
  (auto) zones start a quick veto (`Z*QuickVetoTemp` + `Z*QuickVetoDuration`),
  manual/day zones write `Z*DayTemp` directly, and an active boost updates the
  veto temperature only. Previously every change wrote the day temp, which the
  controller ignores in auto mode.
- **Restart-proof BOOST detection.** The BOOST preset now combines the
  optimistic local timer with device-side truth: idle zones report
  `QuickVetoEndDate 01.01.2019`, active vetoes report a future date plus end
  time. A user-cancelled veto stays suppressed until the reported end changes,
  so a HA restart no longer resurrects or drops boost state.
- **Optimistic setpoint bridging the controller's apply latency.** Measured
  ~30–60 s between an accepted write and its appearance on the bus. Requested
  target temperatures show immediately and clear on device confirmation or
  after a settle window; one delayed confirm refresh pulls the confirming
  registers instead of waiting for the next poll.
- **Multi-entry service dispatch.** All integration services register once at
  integration scope and resolve their coordinator per call: an explicit
  `entry_id` wins, a single loaded entry is used automatically, and ambiguous
  calls fail loudly instead of silently targeting the last-loaded entry.
  `services.yaml` documents the optional selector.
- **Backend command validation.** Read/write/define reject empty identifiers
  and CR/LF injection at the transport boundary; values keep their ebusd syntax
  including spaces and semicolons.
- **Analysis auto-enables per-field entities.** When background analysis finds
  a live multi-field register, its per-field sensor entities are enabled along
  with the raw value, matching what the entity factory generates.

### Fixed

- **b516 day queries use the correct half-month block.** The date payload of
  the runtime-defined b516 statistics kept W on the month's even value for
  days 16–31, so `CoolEnvYieldDay` asked the device for a day in the first
  half of the month (Aug 24 was decoded as Aug 8) and roughly half of each
  month returned another day's counter. The encoder now flips to the month's
  odd W value with `V = day − 16` per the upstream issue #490 table, checked
  against the thread's worked examples (Feb 23 2025 → `5732`, Aug 24 2026 →
  `1835`) and verified live against an HMU across the day-15/day-16 boundary.
  Month totals accept either W value, so `CoolEnvYieldMonth` is unaffected.
- **Python 3.12/3.13 import crash.** Unparenthesized multi-except clauses
  (PEP 758, Python 3.14-only) are parenthesized throughout, restoring imports
  on every released Home Assistant version.
- **TCP response interleaving.** Write/read-back and multi-line `find`
  transactions hold the stream lock for their complete exchange; reconnect is
  single-flighted and re-dials even when a stale writer object survives a
  transport error, so self-healing can no longer be a silent no-op.
- **Discovery dump directory race.** Directory creation is now awaited before
  the YAML write lands; it previously ran fire-and-forget and could crash the
  dump when the directory did not exist yet.
- **Silent persistence failures are visible.** Cache save/load failures log
  path and reason without exposing values; a missing cache file on first run
  stays silent.
- **Partial entity writes stop early.** Multi-register sequences abort at the
  first failed write instead of stacking dependent writes on a broken
  assumption, and entities refresh only after full success.
- **Sentinel values no longer leak into entities.** `-`, `empty`,
  `no data stored`, `unknown`, and `unavailable` map to unavailable states in
  select, switch, and binary_sensor platforms.
- **Compressor idle handling follows the heat-pump circuit.** Idle detection
  and stale-value zeroing resolve the status and power/speed registers on the
  discovered heat-pump circuit instead of hardcoding `hmu`, so setups whose
  heat pump answers on another circuit no longer leak stale values while idle.
- **Options flow actually applies settings.** `scan_interval` changes take
  effect, connection edits reload the entry via an update listener, and an
  emptied host field keeps the stored value instead of disabling the
  connection.
- Typing corrections surfaced by a strict-mypy baseline pass (result dataclass
  fields, narrowed graph merge, honest sensor value types); remaining findings
  require a typed homeassistant environment in CI and are tracked separately.

### Removed

- The production-dead `RegisterService` and its test suite; discovery-service
  dead symbols. Entity creation runs through the shared factory path only.

## 1.5.0 - 2026-08-24

### Added

- **Cooling-energy registers via runtime-defined b516 statistics (#50).** The
  b516 energy-statistics API on the HMU supports a cooling usage code
  (`Z=5`, upstream `john30/ebusd-configuration` issue #490), but the shipped
  HW5103 CSV definitions omit the family (upstream issue #600), so heat pumps
  report `ERR: element not found` for every cooling total. Four registers are
  now injected at startup via the existing runtime-definition mechanism and
  verified live against ebusd:

  - `hmu.CoolEnvYieldTotal` — environmental yield used for cooling, lifetime
    (Wh, total increasing)
  - `hmu.CoolEnvYieldDay` — environmental yield for cooling today (Wh)
  - `hmu.CoolEnvYieldMonth` — environmental yield for cooling this month (Wh)
  - `hmu.CoolElecConsTotal` — electric consumption used for cooling, lifetime
    (Wh, total increasing)

  Unlike the compressor-based counters (`YieldCoolDay`, `HoursCool`), these
  measure the thermal energy exchanged with the building regardless of
  compressor operation, so they also cover passive brine cooling. The day and
  month variants carry a date payload that is re-encoded from the current
  date on every (re)connect; the encoding helper (`b516_date_bytes`) is unit
  tested against known dates including the live-verified 2026-08-24 case.

## 1.4.3 - 2026-08-24

### Fixed

- **DHW sub-device collision hid live hot-water registers (#50, #79).** When two
  source circuits mapped to the same logical device name — for example
  `ctlv3/dhw` with live registers and `hmu/dhw` without any data — the later,
  data-less sub-device overwrote the live node during discovery. The affected
  registers (`HwcStorageTemp`, `HwcTempDesired`, `HwcOpMode`) were silently
  dropped from the device graph, so no DHW sensor entities were generated and
  `water_heater` stayed without a current temperature. Sub-devices sharing a
  logical name are now merged instead of overwritten. Verified against three
  community fixtures: flexoTHERM (issue #50), GeniaSet BASS3 (issue #79), and
  aroTHERM Plus two-zone (no regression).
- **Corrected the cooling-context note for the flexoTHERM v1.3.3 dump (#50).**
  The dump was captured during an active passive (brine) cooling cycle — flow
  temperature around 19 °C at 31 °C outside, `releaseCooling` enabled — while
  the compressor never ran (`RunDataStatuscode = 0`). The compressor-based
  counters (`YieldCoolDay`, `HoursCool`) therefore stay at zero by design and
  cannot represent passive-cooling energy; regression test comments now record
  this context.

## 1.4.2 - 2026-08-21

### Fixed

- **flexoTHERM cooling-yield data backed by a community dump (#50).** A new
  discovery-dump fixture
  (`tests/fixtures/community/flexotherm_133_cooling_discovery.yaml`) confirms
  the flexoTHERM reports the daily cooling yield (`hmu.YieldCoolDay`, kWh) and
  cooling runtime (`hmu.HoursCool`, h) as live values, while the cumulative
  cooling totals (`StatElectricEnergySumCool`, `StatEnvironmentEnergySumCool`,
  `YieldCooling`, `YieldCoolingMonth`, `CopCooling`, `CopCoolingMonth`) return
  `ERR: element not found`. Regression tests assert the daily yield/runtime
  entities are generated and the element-not-found totals stay hidden. No
  production code change was required — the previous fixture simply had no live
  cooling data.

## 1.4.1 - 2026-08-21

### Fixed

- **GeniaSet BASS3 controller recognized as a heating controller (#79).** The
  `bass` / `bass3` circuits are now explicitly classified in the discovery
  device-type tables, so a GeniaSet BASS3 is deterministically treated as a
  heating controller instead of relying on register-based categorization alone.
  This is backed by a new community discovery-dump fixture
  (`tests/fixtures/community/geniaset_bass3_discovery.yaml`) with regression
  tests covering the device graph and DHW register discovery.

## 1.4.0 - 2026-08-19

### Added

- **Per-zone climate entities (#75).** One thermostat and flow-temperature-range
  entity is now created for every discovered heating zone (zone 1, 2, 3), with
  zone-scoped registers (`Z2DayTemp`, `Z2OpMode`, ...), unique ids, and devices.
  The `COOL` mode is only offered where the zone has a cooling register, and the
  `BOOST` preset only where quick-veto duration exists. Ghost zones (a zone that
  exists on the bus but is unused — `RoomZoneMapping = none` and no measured
  room temperature) are excluded so they never produce a permanently-unavailable
  climate entity; static set-point defaults like `Z2DayTemp = 21` do not count as
  live zone activity. Single-zone systems keep the existing `z1` entity ids
  unchanged.

### Fixed

- **Energy and yield sensors on aroTHERM Plus now populate from the correct
  circuit (#53, #76, #77).** The fallback read used to read `PrEnergySum*` and
  `StatElectricEnergySum*` / `StatEnvironmentEnergySum*` from the circuit where
  their metadata lives (`ctlv2` / `hmu`), but aroTHERM Plus exposes them on the
  `ctlv3` / `basv3` / `vwzio` controller circuit, so ebusd replied `ERR: element
  not found` and the sensors stayed unavailable. The fallback read now resolves
  the circuit where a register was actually discovered (mirroring the `get_meta`
  alias) and reads it there, including the periodic retry of no-data registers.
- **Missing yield day/month registers mapped.** `hmu.YieldHcMonth`,
  `hmu.YieldHwcDay`, and `hmu.YieldHwcMonth` are now registered as energy sensors
  (#77), so they are treated as enabled and picked up by the placeholder retry.

## 1.3.4 - 2026-08-17

### Fixed

- **`analyze_registers` no longer crashes on current Home Assistant (#72).** Entity
  registry access now uses the supported `entity_registry.async_get(hass)` API.
- **Energy and yield statistics are refreshed when ebusd initially reports no data
  (#71).** Enabled placeholder registers are retried through direct ebusd reads every
  15 minutes, allowing values that become available later to update normally without
  increasing the regular polling frequency.

## 1.3.3 - 2026-08-15

### Fixed

- **EcoTEC mixing module (`vr_71`) now exposed (#48).** Circuits detected under
  the `vr`-prefix (e.g. the VR 71 mixing/low-loss-header module that connects a
  gas boiler into a hybrid plant) are now categorized as `MIXING_MODULE` and
  their registers (`Mc1Operation`, `SetActorState`, `SensorData1/2`,
  `Currenterror`, `Errorhistory`, ...) generate entities. The scan-type match
  was also corrected so `VR_71`/`VR_92` (shared `vr` prefix) no longer
  overwrite each other and target the wrong circuit — each discovered circuit
  now gets the longest matching scan prefix instead of the last one winning.

### Changed

- **Runtime register definition logging.** Startup now reports how many
  generic runtime definitions were accepted or unavailable, while individual
  successful definitions remain debug-level and unsupported hardware does not
  flood normal logs.
- **Community-verified runtime registers are offered generically.** Proven
  `define -r` definitions are installed for every compatible connection, even
  when a register is not present on the local installation. Missing registers
  remain unavailable and do not create entities; hardware-specific or
  unverified candidates are not added automatically. This allows registers
  discovered on other Vaillant systems to work for those users without
  fabricating values on unsupported hardware.

## 1.3.2 - 2026-08-15

### Fixed

- **Energy statistics on aroTHERM Plus / basv3 controllers (#53).** The electric
  and environment energy statistics (`StatElectricEnergySum*`,
  `StatEnvironmentEnergySum*` — including the cooling variants) were defined in
  the register map under the `hmu` circuit, but these controllers expose them on
  the `basv3` circuit. The metadata fallback only mapped heating-controller
  variants onto `ctlv2`, so the sensors appeared without energy metadata.
  Register metadata now also falls back onto the `hmu` statistics keys, and the
  full `StatElectricEnergySum` / `StatEnvironmentEnergySum` family (blank, `Hc`,
  `Hwc`, `Cool`) is exposed as `kWh` energy sensors with `total_increasing` state
  class.

- **Cooling energy on actively-cooling air/water units (#50).** The flexoCOMPACT
  (air/water aroTHERM with active cooling) reports `StatElectricEnergySumCool`
  live on both `hmu` and `ctlv2`, but the register-metadata fallback skipped the
  `hmu` statistics keys when the circuit was already `ctlv2`, so the sensors lost
  their energy metadata. The fallback now consults the `hmu` keys for every
  non-`hmu` circuit (including `ctlv2`). The flexoTHERM (brine-water, no active
  cooling) never exposes this register — it returns "element not found" and
  correctly stays absent.

- **Register writes now trigger the expected refresh (#68):** the coordinator's
  central write path called `async_request_refresh()` without `await`, so the
  refresh coroutine was discarded and entity states only updated on the next
  poll cycle. After successful writes the coordinator now refreshes immediately.
- **aroTHERM Pro 7 recognized as heat pump (#56).** The Pro 7 reports its heat
  pump under the circuit `HMUX0` instead of `hmu`, so the compressor state and
  the connection/fault sensors read the wrong device. Circuit detection now
  classifies `hmux*` as a heat pump and `sol*` as a solar controller, and the
  coordinator resolves the heat pump circuit from the discovered graph instead of
  assuming `hmu`.

## 1.3.1 - 2026-08-14

### Fixed

- **Phantom devices are no longer created.** Raw eBUS address circuits such as
  `B504`, `B511`, and `76`, plus unsupported no-data circuits such as `sc`, are
  excluded from discovery instead of appearing as mostly-empty Vaillant devices.
- **Partially decoded ebusd errors are unavailable.** Values containing
  `(ERR: invalid position)` no longer create misleading sensor states.
- **Current ebusd scan metadata is parsed correctly.** The
  `MF=...;ID=...;SW=...;HW=...` format now maps device type and version data.
- **Discovery recovers and updates live entities.** A failed initial ebusd
  connection retries on the next poll; delayed discovery and successful fallback
  reads add their new entities to Home Assistant.

## 1.3.0 - 2026-08-14

> **Cooling works!** After a deep investigation (see below), this release exposes
> the manual cooling period on the eBUS bus — you can now read **and write** the
> "cool until [date]" period that the myVaillant app manages, and drive it from
> the Home Assistant climate entity.

### New & found registers

- **Manual cooling start/end date** (`ctlv2.ManualCoolingStartDate` /
  `ctlv2.ManualCoolingEndDate`) — previously absent from every ebusd CSV. The
  sub-addresses (`0xda` / `0xdb` on the `_720` r_1 base) were reverse-engineered
  and verified on a real CTLV2 `SW0514`/`HW1104`. The field layout is the
  holiday/away date type (`value,,IGN:4,,,,value,,HDA:3`, year byte =
  year−2000, no BCD), with a `value,m,HDA:3` write route on the `0201...`
  write-sub. Exposed as read/write datetime entities:
  - `datetime.vaillant_ebus_manual_cooling_start_date`
  - `datetime.vaillant_ebus_manual_cooling_end_date`
- **Climate COOL mode now starts a real cooling period.** Selecting COOL writes
  the manual cooling end date (today + configurable `cooling_duration`, default
  3 days) and switches the zone to auto. Selecting HEAT clears the end date and
  switches to day. The old `"cool": "night"` write was removed because `night`
  is not retained by this controller.
- **Configurable `cooling_duration`** option (days) in the integration settings.

### Investigation notes

A 300 s bus capture while cooling was turned on in the app showed zero write
telegrams (the app drives the outdoor unit via NETX2/cloud, not the controller
bus), and the old `15.700.csv` cooling sub-addresses returned `invalid position`.
The `_720`-conditional cooling-program registers (`Hc1CoolingEnabled`,
`Z1CoolingOpMode`, timers) are absent on this hardware, but the manual-cooling
period itself is readable and writable.

### Added

- **Structured grab telegrams in discovery dumps:** `labeled_telegrams` and
  `unknown_telegrams` entries next to the raw `grab` lines. Unknown telegrams
  (no register label in the ebusd CSV) are candidates for runtime `define -r`
  registers absent from the installed CSV files — the basis for the cooling
  register discovery above.

### Changed

- **Central register write path.** All entities now write through the
  coordinator `async_write_registers()` API, which bundles multiple writes and
  triggers a single refresh. Multi-register operations (holiday periods, DHW
  mode, manual cooling) are written atomically.
- **Climate COOL/HEAT is now symmetric.** Selecting COOL writes the manual
  cooling end date and switches to auto; selecting HEAT clears the manual
  cooling end date and switches to day, so a cooling period is properly
  cancelled instead of left running.
- **Discovery dump export runs in the background:** long raw eBUS traffic grabs
  no longer block the options flow, so the Home Assistant frontend does not time
  out. The export step now reports that the dump is being written instead of the
  misleading "Options successfully saved" message, and a persistent notification
  appears when the YAML file is ready.
- **Dump export step ends with an abort message** instead of a create-entry result,
  so the frontend shows the "export started" message instead of "Options
  successfully saved".

### Test it

- Set your climate to **COOL** and check `datetime.vaillant_ebus_manual_cooling_end_date`
  moves to today + `cooling_duration`. Switch back to **HEAT** and it resets.
- If your heat pump does not expose the manual-cooling registers (different
  firmware), the datetime entities simply stay unavailable — nothing breaks.
- Use **Settings → Export Discovery Dump** to capture registers + raw bus
  traffic, and share the YAML if a register is missing so it can be mapped.

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
