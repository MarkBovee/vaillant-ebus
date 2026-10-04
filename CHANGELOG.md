# Changelog

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
