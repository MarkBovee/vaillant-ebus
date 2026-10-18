# Changelog

## 1.12.0 - 2026-10-18

### Added

- Leftover entities can now be cleaned up. Home Assistant keeps the entities of a zone, a register or an older release
  after the integration stopped providing them; they show as "unavailable" and never go away by themselves. About
  fifteen minutes after start the integration checks for them and, if it finds any, shows a repair called "Stale
  Vaillant eBUS entities". Open it to see the first names and the count; nothing is removed until you select Submit.
  Devices left without entities are removed with them. Entities you renamed, hid, labelled or put in an area are kept,
  and so are devices you renamed or labelled. Nothing is checked while ebusd is not connected.
- "Purge stale entities" in the integration options uses the same check and the same preview.

### Changed

- "Purge stale entities" used to delete every entity whose state was `unknown`. That also removed live entities, such as
  a holiday date while no holiday is set, and it did not find the leftovers described above. It now removes only
  entities that nothing provides any more.
- A heating circuit that the controller itself reports as `inactive` (circuits 2 and 3 on many systems) no longer gets
  zone sensors, settings or controls. The controller answers fixed default values for zones that do not exist, such as
  a day temperature of 21.0 or holiday dates in 2015, and those looked like real data. On one test system that made two
  extra zone devices with about 80 entities. The `Circuit Type` sensor of such a circuit now sits on the controller
  device, so you can still see why the zone is missing. This rule does not apply to zone 1, a circuit whose type cannot
  be read is never hidden, and a zone that reports a room temperature is kept. To bring a hidden register back, set
  `enabled: true` for it in `entities.yaml`.
- The "solar controller" that the controller answers for at the solar address no longer creates entities when none of its
  registers has a value and its firmware numbers equal those of the heating controller. A real solar module has its own
  numbers and answers its registers, so it keeps working. Its remaining entities from older releases show up in the
  repair described above.
- When the eBUS adapter stops carrying requests, the integration now pauses its active reads. Four bus errors in a row
  (`arbitration lost` or `read timeout`) on at least two different circuits pause them for a minute; the next read is a
  test, and the pause doubles up to ten minutes while it keeps failing. One device that stops answering never pauses
  the others. Before this, a stuck adapter got the whole read set again every cycle (issue #193). A reconnect or a
  rediscovery starts clean. This was built from the report and has not been tried on a stuck adapter yet.
- Heat pump firmware SW0406: the electrical power now shows up as soon as the myVAILLANT gateway asks for it
  (issue #188). The integration only listens to that answer and sends nothing. It stays unavailable until the
  gateway has asked once.

### Fixed

- Heat pump firmware SW0406 without an ebusd configuration for the heat pump: the flow and return temperature were wrong
  or missing, because this firmware answers with a different number format than SW0303 (issue #188). SW0303 is not
  changed. If you ran 1.11.2 on SW0406, restart Home Assistant after the update; if the old values stay, restart ebusd
  once, because ebusd may keep the earlier definition until then.
- Mixer movement of the heating circuits now has the unit `%` and is recorded as a measurement, so Home Assistant draws
  a line instead of coloured bars (issue #190). The value is a signed percentage; -100 means the mixer is closed.

### Not changed

- The electricity totals that grow in steps of 1000 Wh (issue #194) come from the heat pump. Some units report whole
  kilowatt hours only, others report finer values; the integration passes on what ebusd gives.
- The heating state of the zone and the hot water (issues #191 and #192) is not changed in this release.
- The pause between the definitions the integration sends at startup (issue #193) is not changed yet; it needs a test
  with the reporter's setup.
- Existing entities of unused zones are not switched off first. After the update and a restart they show as
  "unavailable" until you confirm the repair.

## 1.11.2 - 2026-10-12

### Fixed

- Writing the HC1/HC2/HC3 auto-off mode failed with `ERR: invalid numeric argument`. The select offered `eco` and
  `comfort`, but ebusd only knows `0=eco;1=night`, and every capture so far shows `eco` or `night`. The select now
  offers `eco` and `night` (issue #187, thanks to the reporter for the log and the working override).
- The settings of the second and third zone were read-only sensors with raw names (issue #186). Zone 2 and 3 now get
  the same controls as zone 1 when ebusd reports them: operation mode, night temperature, quick veto temperature and
  duration, holiday temperature, and the holiday and quick veto dates. A zone only gets these controls while it
  reports a room temperature, so a placeholder zone (for example an unused zone 3) keeps its read-only values and
  gets no controls. The old read-only sensors of an existing installation become unavailable once the controls
  appear; remove them with "Purge stale entities" in the integration options.
- Heat pump with firmware SW0406 on a default ebusd configuration (issues #185 and #188). When ebusd has no
  `08.hmux0.csv` that lists registers for this unit, only the nine energy counters were visible. The integration now
  defines the registers that the captures show this unit answers: yield and COP (day, month, total, heating and hot
  water), the precise flow and return temperature, compressor speed, building pump speed and the compressor runtime
  and starts for heating and hot water. The compressor counters are off by default. If ebusd already lists other
  heat pump registers of its own (a full `08.hmux0.csv`), nothing is defined, so nothing is duplicated.

### Changed

- The Away Mode switch now covers every zone that reports a room temperature, not only the first zone (issue #186).
  Turning it on writes the holiday period of each of those zones and of the hot water; turning it off resets all of
  them. It reads `on` only when every such zone is on holiday, so a zone that you set to holiday in the myVAILLANT app
  alone does not make the whole system look away. Holiday dates that cannot be read keep the switch `unknown`
  (a zone with an explicit "not set" date still makes it `off`). A system with one zone behaves as before.
- HMUX0 firmware SW0407 (issue #175): the integration now decodes the controller status telegrams `B511/01`
  (flow, return, outside, hot water and storage temperature, pump state) and `B511/00` (flow temperature, compressor
  and heating state, defrost) from the bus traffic. This adds no bus traffic. In the capture, five values match the
  display of the unit (flow 29.6, return 28.3, outside 13.4, storage 46.5, setpoint 29.0).
- The hydraulic station VWZIO SW0500 gets "Station Storage Temperature (assumed)" and "Flow Temperature After Backup
  Heater (assumed)" from the telegram `B512/030f0001`. They are off by default, because the capture shows one state
  only (46.56 and 30.0 against 46.5 and 30.0 on the display).
- Documentation: override keys must use the circuit name ebusd reports (`ctlv3` or `ctlv2`), a changed `options`
  list needs a Home Assistant restart, the yield sensors are environmental yield, and the myVAILLANT app can
  overwrite settings that you wrote through this integration.

### Not changed

- E7000 and E7Z00 controllers (discussion 31): the two local CSV files load, but they define no messages, so ebusd
  gives the integration nothing to build zones from. Upstream pull request 623 is the route for that.
- `hmu` against `hmux0` energy values and `LiveMonitorCurrentConsumedPower = 0.0` in issue #188 come from a local
  ebusd configuration that copies the generic heat pump CSV. They are not integration bugs.
- The electrical power register of HMUX0 SW0406 is not defined: the value in the capture (27.0) does not match the
  846 W that the reporter compared with the cloud, so the unit is unclear.
- The status "compressor modulation" and "compressor power" that SW0407 now decodes read 12 where the display shows
  6.4 %. Both come from the shared Status00 layout and are unverified for this firmware; please compare once more.
- Zone 2 entities that became unavailable on a BASS3 system (issue #152) need a fresh discovery dump from 1.11.2.

## 1.11.1 - 2026-10-07

### Fixed

- Remove the frozen energy sensors on a gas boiler with a BASS3 (issue #152). The integration kept old cached
  `Stat*EnergySum*` values (electric, environment, solar) for the boiler interface and the controller, although the
  bus does not list them and there is no heat pump to read them from. They showed 0 or odd values. When the bus has a
  boiler scan and no heat-pump scan, these cached values are now dropped at start, and their entities are switched
  off in the registry. Registers that the bus lists, and systems with a heat pump, are not touched.
- Show the room temperature threshold (`Hc1/2/3RoomTempSwitchOn`) as text without a unit. It is an enum with the
  values `off`, `modulating` and `thermostat`, but the sensor had a temperature unit, so it stayed `unknown`.
- Stop the `prepare message part 0: ERR: end of input reached` errors on the bus (issue #182). The integration read
  `Errorhistory` about every 40 seconds, but ebusd needs an `index` for that message, so every read failed and ebusd
  logged a bus error. `Errorhistory` is no longer read. An "Error History" entity that never had a value is removed
  with this change. Thanks to the reporter for the clear trace and the test.
- The DHW away switch and the zone away switch show `off` when the holiday start date is the "not set" date, even if
  the end date cannot be read. Before, they stayed `unknown`. Missing data still gives `unknown`.

### Changed

- The boiler status message temperatures are named "Flow Temperature (Status message)" and "Storage Temperature
  (Status message)", so they are no longer confused with the separate flow and storage temperature sensors. Entity
  ids of existing installations do not change. The storage variant is off by default.
- The climate entity of extra zones is named "Climate" and the flow range "Flow Temperature Range". The zone device
  already carries the zone name, which gave ids such as `climate.zone_2_zone_2` on new installations. Existing entity
  ids do not change.
- Fix the options of the HC1 setback mode select to `eco` and `normal` (pull request #174, thanks to Alokin90).

### Not changed

- Holiday date entities stay `unknown` while no holiday is set; Home Assistant date entities cannot show "not set".
- Flow, return and outside temperature sensors that the boiler interface does not answer stay unavailable.
- VR_70 values, cooling dates on a gas boiler and the broadcast outside temperature need more evidence first.

## 1.11.0 - 2026-10-06

### Fixed

- Stop the repeated reloads of the integration on systems with a VWZIO SW0500. The hydraulic station power sensor
  (`PowerConsumptionVwz`) was removed as stale at every start, switched on again a moment later by the fallback
  read, and Home Assistant reloads the whole integration after each such change. Every entity then went unavailable
  for a few seconds, sometimes every minute or two (issues #171 and #175). Registers that the integration defines
  itself are no longer treated as stale, are no longer switched off while they have no value, and do not show an
  old value from the previous session.
- Keep the raw traffic of a discovery dump with a positive `grab_duration`. Two real dumps lost it because ebusd had
  replaced the latest payload of a message between the two snapshots, and the dump then reported `skipped_active`.
  The capture is now kept. Rows whose counts had to be estimated are listed under `grab_approximate_rows` in the
  dump metadata. A counter that goes down (an ebusd restart) still discards the capture.
- Stop the endless `ERR: invalid position` polling on a VRC350 (`35000`) system. On that bus the only circuit typed
  as a controller is the BAI boiler interface, so the CTLV2 B524 definitions (`z1RoomHumidity`,
  `ManualCoolingStartDate`, `ManualCoolingEndDate`) were defined on the boiler, which answers `00` to them, and
  ebusd kept polling them (issue #179). B524 definitions are no longer defined on a BAI boiler interface; real
  VRC700-family controllers are not affected. ebusd keeps runtime definitions until it restarts, so restart ebusd
  once after updating to stop the polling that already runs. The one-off fallback reads of these registers are
  skipped as well.

### Not changed

- The slow passive values on HMUX0 SW0407 (status code, compressor speed, building pump power and the compressor
  counters) have no code change of their own. The gateway sends them about every five minutes, and every reload
  wipes them, so the reload fix above is the expected cure. Please confirm on 1.11.0.
- A discovery dump with a very long `grab_duration` (300 seconds) that produced no file at all. The cause is not
  known yet; a Home Assistant log of the failing call would help.

## 1.10.5 - 2026-10-04

### Fixed

- Keep the precise flow and return temperature (`RunDataFlowTemp`, `RunDataReturnTemp`) up to date on HMUX0
  SW0406/HW0504 units. Since v1.10.3 the integration only asked ebusd for these values on SW0303, so on SW0406
  they stayed at whatever ebusd had cached (issue #171). SW0303 and SW0406 are now read; other firmware versions
  stay excluded because earlier captures returned impossible values.
- Fix the ids of the passive HMUX0 SW0407 definitions. The ebusd id does not include the length byte, but the four
  B509 definitions (status code, compressor speed, electrical power, building pump power) and the VWZIO backup-heater
  counters started with it, so they could never match a telegram on the bus. This is why those entities stayed
  `unknown` (issue #175, issue #161). A new test checks every passive id against the telegrams in the captures. The active B509 definitions for
  SW0302/SW0303 (electrical power, compressor speed, building pump power) had the same problem and are fixed too;
  they were unavailable before.
- Keep entities for registers that the integration defines itself. After a restart ebusd can list them as "no data"
  for a moment, and the integration then removed or disabled them, even when you had enabled them
  (issue #175, environmental yield sensors).
- Remove the `Invalid repairs platform` error at startup. The repairs module now offers the confirm step that Home
  Assistant expects (issue #161).
- Do not create entities for a heating circuit that the controller itself reports as `inactive`. The circuit type
  sensor stays. A circuit whose type cannot be read is never hidden (issue #152, the unused HC3 on a BASS3).
- Remove a stale cached zone register when the same register is live under another circuit, such as the second
  room humidity sensor on a BASS3 system (issue #152).
- The boiler stage-1 energy counters (`PrEnergySumHc1`, `PrEnergySumHwc1`) no longer claim kWh. Their values grow
  far too fast for kWh, so the unit is unknown. They are now diagnostic raw counters and disabled by default
  (issue #152). Existing entities keep their current setting.

- Let the discovery dump read a longer `grab result all` response (limit raised from 10,000 to 100,000 lines). ebusd
  2.1 and newer grabs all the time, so on a long-running system the result grew past the old limit and the dump fell
  back to a register-only file (`grab_status: skipped_active`).

### Added

- Add the electrical power of the HMUX0 SW0407/HW0504 heat pump from the gateway's `B516/14` frame, plus the
  heating and hot-water compressor runtime and start counters from `B511/1801` and `B511/1802`. The layouts match
  upstream ebusd-configuration issues #490, #522, #610 and #638 and the captures in issue #161. These are read
  passively and are disabled by default; when the gateway does not send the telegram they stay unavailable.
- Add the backup-heater hot-water heat total (`B516` source `0x49`, usage `04`) for VWZIO SW0500/HW0504. This is a
  strong assumption from the issue #161 capture: 6487 Wh against 106 minutes of heater runtime. The entity is
  disabled by default and unavailable without data.

### Notes

- Not changed: Quiet mode (the `B508/0209` direction is not proven), the BASS3 calendars, the E7000 controller
  without an ebusd configuration (discussion #31, upstream PR #623 in ebusd-configuration), and the default
  enablement of rarely used registers.

## 1.10.4 - 2026-10-03

### Added

- Add a "Flow Temperature (precise)" sensor for HMUX0 SW0303/HW0504 units
  (issue #171). It reads `RunDataFlowTemp` with the same 1/16 °C resolution as
  the existing return temperature. The existing flow sensor stays as it is.
  The layout comes from upstream ebusd-configuration PR #496 and the reporter
  confirmed values on an aroTHERM Plus. Units that do not answer, or that
  return an implausible value, keep the sensor unavailable.

### Fixed

- The combined "Status" sensor (for example `26.0;26.0;16.613;-;67.0;off`) is
  now disabled by default. It repeated values that the separate flow, return,
  outside, storage and pump entities already show, and it changed on almost
  every poll. This affects newly created entities only; existing entities keep
  their current setting (discussion #31, issue #152). The same applies to the
  other combined status sensors (`Status00`, `Status02` and `Status07`). A YAML
  override with `enabled: true` still turns any of them back on.
- Registers that count or measure something, such as `YieldTotal` and
  `PumpPower`, no longer turn into on/off sensors when their value happens to be
  `0` or `1`. They stay normal sensors (issue #152).

## 1.10.3 - 2026-10-02

### Added

- Add `Hc1SetbackMode` and `OffsetOutsideTemp` controls for the captured CTLV0
  SW0313/HW9103 controller. The reporter tested the setback-mode mapping; the
  community dump records the offset value before and after a successful
  write/read-back.
- Add passive VWZIO DHW backup-heater runtime and start-count decoding for
  B511/021802. The SW0500/HW0504 definition uses existing gateway telegrams and
  does not issue active reads; the captures show the counter advancing across
  two known heater runs. The shared field layout is also documented on
  SW0901/SW0902 HW5103 in upstream PR #598.

### Fixed

- Apply the HMUX0 SW0407 fallback blocklist when the current scan identity is
  incomplete or ambiguous, in both coordinator polling and dump map probes.
- Keep SW0303-only runtime definitions and `RunDataReturnTemp` fallback behind
  a current unique SW0303/HW0504 owner, while preserving non-HMUX0 `hmu`
  fallback behavior.
- Do not reuse retained HMUX0 scan metadata after a scan-less or ambiguous
  refresh when deciding runtime definitions or active fallback reads.

### Notes

- The separate HTTP 500 after an ebusd crash is not fixed by this release. Dump
  export still requires an authoritative discovery graph.
- BASS3 calendars remain unavailable while timer reads return
  `ERR: invalid position in decode`.
- No F34 energy-mapping changes are included.

## 1.10.2 - 2026-10-02

### Fixed

- Keep a discovery dump when another client already owns ebusd's global raw
  capture. On ebusd versions with automatic grab, the export compares before
  and after counts without stopping the daemon-wide session; if it cannot
  isolate the interval or parse a complete snapshot, it saves a marked
  register-only dump instead.
- Record requested and captured duration, capture method and status in the dump
  metadata. Continued captures retain only the last payload per message key and
  sum counts for identical visible rows. ebusd does not expose an
  epoch to detect an external stop/restart followed by a count refill during
  the interval. Do not run external grab commands or restart ebusd while the
  export runs; if ebusd accepts a start command but its acknowledgement is lost,
  the service will not send an unowned stop and grabbing may remain enabled.

## 1.10.1 - 2026-09-30

### Added

- Add heating and DHW environmental-yield sensors for HMUX0 `SW0407/HW0504`.
  The six B516 counters are exposed in Wh with energy statistics metadata.
  Other HMUX0 firmware variants are not actively probed for these registers.

## 1.10.0 - 2026-09-25

### Fixed

- Stopped actively reading the twelve B524 Hc1/Hc2 state registers through
  runtime definitions, coordinator fallbacks, and discovery-dump probes.
  BASS3, BASV3, CTLV3, and the owner's live ebusd logs showed repeated
  `invalid position` replies. Registers that ebusd discovers itself remain
  available through normal discovery, and BAS-specific setpoint definitions
  are unchanged.
- Retry failed ebusd transport reconnections through the normal setup path and
  distinguish TCP EOF, timeouts, and write failures from a valid empty `find`
  result. Rebuild the discovery graph after reconnect, and gate register
  services and dump probes until a non-empty graph is applied. Keep the
  `ebusd_unreachable` repair active until that recovery completes, so a
  temporary connection failure cannot strand the coordinator or leave a stale
  warning.
- Prevent cache fallback from restoring a previous value when the current find
  explicitly reports that register as unavailable.
- Keep invalid-position B524 placeholders unavailable without creating entities
  when ebusd reports an error row on an otherwise active controller, and retire
  cached placeholder entities from earlier versions.
- Harden discovery dumps and ebusd discovery: require exact `grab` acknowledgements,
  bound responses, reject malformed discovery rows, and skip active fallback reads
  for unusable finds, error placeholders, and parsed field keys. An incomplete `info`
  response now fails the dump instead of saving empty metadata.

### Upgrade

- When upgrading from a version that loaded the pre-#158 Hc1/Hc2 B524 runtime
  definitions, restart ebusd once after installing the integration. A Home
  Assistant restart alone does not clear those daemon-memory entries. No ebusd
  restart is needed when the fixed integration was already in use.

### Added

- Add passive HMUX0 `SW0407/HW0504` telemetry for compressor status, electrical
  power, compressor speed, building-circuit pump power, and the seven observed
  refrigerant diagnostics. The runtime definitions decode only gateway telegrams;
  unsupported B51A map probes no longer trigger active fallback reads on this scan.
- Add passive VWZIO `PowerConsumptionVwz` from B516/14 for the captured
  `SW0500/HW0504` station. The integration reports station power, not heater-only
  power, and does not poll the B511 heater-counter messages.
- Expose `Hc1RoomTempSwitchOn` as a select with `off`, `modulating`, and
  `thermostat` options on verified CTLV3 `SW0808/HW8004` hardware. The migration
  retires the old sensor registry entry and cached description, so the entity
  ID changes from `sensor.*` to `select.*`; CTLV2 and unverified CTLV3 firmware
  keep their sensor metadata. A no-data CTLV2 value remains an enabled sensor
  with an unknown state instead of disabling the existing entity.
- Added the complete BASV3 discussion #31 capture as a regression fixture for
  the invalid-position B524 responses.
- Added the full issue #161 discovery capture as a community regression fixture,
  including its original find lines, provenance, and unknown-telegram payloads.

### Changed

- Mark daily heating and DHW electricity counters as `total_increasing` and
  expose a discovered CTLV3 `YieldTotal` as energy in kWh with state class `total`.

### Deferred

- VWZIO B511 `/021801` and `/021802` remain discovery-only on `SW0500/HW0504`;
  PR #598 verifies their counter meaning on HW5103, but the issue #161 capture
  does not correlate those counters with a heater run on HW0504.

Older releases (1.9.5 and earlier) are in [docs/changelog-archive.md](docs/changelog-archive.md).
