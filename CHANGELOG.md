# Changelog

## 1.12.5 - 2026-10-26

A tidy-up of the entity list, plus the gas counters of discussion 31. Several sensors that repeated each other or
carried a raw register name are cleaned up; nothing is deleted without a confirmation.

### Added

- **Gas consumption counters (`PrFuelSum*`, discussion 31).** An old rule hid every register whose name starts with
  `PrFuelSum`, so a gas boiler with a VRC 720 never got these sensors, even though ebusd showed values such as 20446
  in total and 14 this month. They are now available as raw counters on the controller circuits (`ctlv2` family) and
  on `b7v`. They are switched off by default, listed as diagnostics and have no unit: no capture shows whether the
  numbers are kWh, so they cannot go on the Energy dashboard yet. Compare one with your meter and tell us.
  On some heat pump controllers the same registers exist with the value 0; they show up there as switched-off
  counters as well.

### Changed

- **Readable names for registers that only had a raw name.** `Energy Integral`, `Flow Pressure`,
  `Compressor Block Time`, `Solar Yield Total`, `Pump Additional Time` and the DHW bank holiday dates no longer
  appear as `EnergyIntegral` and the like. No unit is added, because no capture proves one. Like other metadata-only
  registers they appear once ebusd returns a value, so a switched-off entry without data is no longer created.
- **The two flow temperatures of a heat pump have different names.** The one from the status message is now
  `Flow Temperature (Status message)`, as on the boilers, so it no longer shows up next to a second
  `Flow Temperature` with a `_2` suffix. Existing entity IDs do not change.

- **The circuit types of all heating circuits sit together.** `Circuit Type (HC1)` was listed under Zone 1, while the
  types of the unused HC2 and HC3 ended up on the controller device. All of them are now on the controller device,
  because the circuit type belongs to the controller, not to one zone. The other HC1 entities stay under Zone 1.
  Entity IDs do not change; the HC1 sensor moves to the other device after the update.

### Fixed

- **Holiday and manual cooling dates are no longer listed twice.** Every date of the heating controller existed as a
  text sensor and as a date control. The date control stays. A zone holiday keeps its sensor when no date control can
  exist for it (for example when two circuits claim the same zone), and so does a single manual cooling date. If you
  want the sensor back, set `enabled: true` for it in `entities.yaml`.
- **Command registers are no longer sensors and are no longer read.** `Clearerrorhistory` and the `EnableTest*` flags
  of the hydraulic station only stand for a button press or a test switch. The integration also stops asking ebusd
  to read `Clearerrorhistory` as a fallback.
- **A customised entity is not switched off by the first discovery.** When a register reports `no data stored` at the
  first discovery after a restart, the integration switches its entity off until data returns. That no longer happens
  to an entity you renamed, labelled or placed in an area.

### After the update

Old sensors that nothing provides any more (the duplicate dates, the command registers and some switched-off entries
without data) show up under **Repairs** as stale entities. Nothing changes until you confirm; entities you renamed or
customised are kept.

### Not changed on purpose

- Entity IDs. Several devices still carry two prefixes (for example `vaillant_ctlv2_heating_control_` and
  `vaillant_sensocomfort_control_`). Changing IDs breaks dashboards and automations, so it needs a separate,
  opt-in step.
- The Zone 2 state "Heating" follows the controller (`Hc2Status` and the circuit pump), as in mypyllant. It is not
  derived from the room temperature.

## 1.12.4 - 2026-10-20

A fix for the stuck adapter of issue #193. Version 1.12.0 added a pause for the active reads; this release makes that
pause start sooner and stay in place.

### Fixed

- **A stuck adapter now gets a handful of reads before the pause starts, not dozens (issue #193).** The pause waits
  for failed reads on two different circuits. The integration read its registers one circuit after another, so on
  a bus with a heat pump, a controller and a hydraulic station about 77 reads went to the heat pump before the
  controller was asked even once. The reads now take the circuits in turn. Nothing is added or left out, so a
  healthy bus gets the same reads as before.
- **A reconnect no longer cancels a running pause.** In the code, a read that ebusd answers too slowly drops the
  connection and reconnects, and that reconnect also reset the pause: it started again at 60 seconds and the whole
  read set went out again. The adapter hangs on ebusd, not on the integration, so a new connection tells us nothing
  about it. The pause now runs to its end. Only the active register reads stay paused; the runtime definitions are
  still sent after a reconnect. If you reset the adapter or restart ebusd while the pause runs, the integration can
  take up to ten minutes to read again; **Rediscover eBUS** ends the pause at once.

### Not solved yet

- On the reporter's hardware the adapter can still get stuck right after the first start, when the runtime
  definitions and the first request to the heat pump follow each other. Whether spacing them out helps needs a test
  on that hardware.
- ebusd polls the three `r5` definitions for the controller by itself, also while the integration pauses. The pause
  cannot stop that.

## 1.12.3 - 2026-10-20

A maintenance release without new features. It moves the last blocking file operations off the Home Assistant event
loop, which the HACS review asked for.

### Fixed

- **The register cache and the discovery dump no longer touch the disk on the event loop.** Creating the cache folder,
  replacing the cache file, publishing a discovery dump and deleting leftover staging files now all run in the
  executor. On slow storage such as an SD card, saving the cache or exporting a dump can no longer stall the rest of
  Home Assistant. The check that stops a late write after the integration is unloaded still runs right before the
  file is replaced, so an unload that starts while the write is queued still keeps the old file.

## 1.12.2 - 2026-10-19

A small fix for BASS3 controllers (for example the GeniaSet): the cooling mode can be changed from Home Assistant.

### Fixed

- **The cooling mode is a select on BASS3 controllers (issue #197).** The ebusd configuration that BASS3 controllers
  load calls this register `Z1OpModeCooling`, while the integration only knew it as `Z1CoolingOpMode`. The names never
  matched, so the cooling mode showed up as a plain read-only sensor. It is now a select with the values that
  configuration accepts: `off`, `auto`, `day` and `night`. Other controllers that load the same older configuration
  get it too. A second or third zone gets the same select, but only when that zone reports a real room temperature,
  the same rule that already applies to its other settings.
  The select for `Z1CoolingOpMode` on other controllers is unchanged and keeps `off`, `auto` and `manual`; the two
  names appear to address the same value on the bus, but each configuration only accepts its own words. The reporter
  confirmed a write of `day`; `auto` and `night` follow the configuration and were not tried on a real system.
  If you worked around this with an `entities.yaml` override, you can remove it after the update.

### Not changed on purpose

- The cooling temperature that a VRC720f remote shows is still missing on that BASS3. The register the integration
  calls "Zone Cooling Temperature" is a different one, and the configuration that BASS3 loads does not define the
  register that probably holds the remote's value. It needs a test on the real hardware first (issue #197).

## 1.12.1 - 2026-10-19

A small release that adds a hot water heating state for heat pumps and fixes two things that made evidence and units
wrong.

### New

- **"DHW Heating" binary sensor for heat pumps (issue #191).** It is on while the heat pump is in hot water mode:
  the compressor or the immersion heater charges the cylinder, including the pump pre- and overrun. It reuses the logic
  of the operating-state sensor, so units that keep the status code at 0 during hot water demand (HMU00 with CTLV3)
  report it through the valve position and the status bits. It is off in every other state, including a blocked or
  switched-off hot water heater, and `unknown` without data or with an undecoded numeric status. It appears on the hot water device only where the heat
  pump status is discovered, so a gas boiler such as a BASS3 gets no sensor; its charging state needs a register
  that nobody has captured yet. Only the compressor state has been compared with the sensor on a real system so far.
  The water heater entity carries the same state as a `heating` attribute (true or false), because Home Assistant
  gives a water heater no heating state of its own; it is left out where the sensor does not exist. The more-info
  dialog of a water heater shows no extra attributes, so read the attribute under Developer tools, in a template, or
  on a tile card (`state_content: [state, current_temperature, heating]`); the binary sensor works in any card.

### Fixed

- **The discovery dump hid more than it should.** The redaction matched short fragments inside register names, so
  `RunDataStatuscode` (the compressor mode), `Z<N>RoomZoneMapping` and `SourceTempInput` showed as `<redacted>` in
  every dump. Serial numbers, key codes, installer data, passwords and tokens are still hidden; short fragments such
  as `code` and `pin` now count only as whole words (`PinCode`).
- **Readable names for zone and clock registers.** `Z1Name1`, `Z1RoomZoneMapping`, `Z1ValveStatus`, the bank holiday
  periods and the controller `Time` showed their raw register names in the main entity list. They now have plain names
  ("Zone Name", "Room Zone Mapping", "Valve Status", "Controller Time") and sit in the diagnostic category, for every
  zone. The controller only sends its clock now and then, and ebusd shows the last value it saw, so "Controller Time"
  can be up to about half an hour behind; that is how the bus works, not a wrong clock. The controller `YieldTotal`
  gets a name and no unit, because the unit is not proven for that circuit.
- **Cleanup respects more of your own settings.** Besides name, icon, area, labels, aliases and hiding, a category,
  a device class or unit override, a display precision and an Assist exposure you set on an entity now count as your
  own choice, so the repair and the purge keep that entity.
- **The dump also hides phone numbers and contact names** (`PhoneNumber`, `ContactName`), which were never hidden.
- **EEV Position no longer claims `%`.** The register is a plain number in an unspecified scale upstream (values such
  as 195 and 250 are normal), so the unit is left out until the evidence gives one.
- **Developer tool:** `tools/fetch_attachments.py` no longer crashes on Windows when an issue contains emoji or
  umlauts.

### Not changed on purpose

- A zone climate keeps showing "heating" while the heat pump charges hot water. The heat pump interrupts the zone and
  returns to it afterwards, and the controller keeps the heating program active, so the state is correct (issue #192).

## 1.12.0 - 2026-10-19

This is a cleanup release. Home Assistant never forgets an entity on its own: after a zone, a register or a firmware
changes, the old entities stay behind as "unavailable", and older versions of this integration also created sensors for
hardware you do not have. 1.12.0 stops creating that clutter and gives you a safe way to clear what is already there.

### Fewer wrong zones, devices and sensors

- **Unused heating circuits get no entities.** When the controller itself reports a circuit as `inactive` (circuits 2
  and 3 on many systems), the integration no longer creates zone sensors, settings or controls for it. The controller
  answers fixed default values for zones that do not exist, such as a day temperature of 21.0 or holiday dates in
  2015, and those looked like real data. On one test system that was two extra zone devices with about 80 entities.
  The `Circuit Type` sensor of such a circuit now sits on the controller device, so you can still see why the zone is
  missing. Zone 1 is never hidden, a circuit whose type cannot be read is never hidden, and a zone that reports a room
  temperature is kept. To bring a hidden register back, set `enabled: true` for it in `entities.yaml`.
- **No phantom solar controller.** The controller also answers at the solar address. If none of those registers has a
  value and the firmware numbers equal those of the heating controller, the integration now treats it as an echo and
  creates nothing. A real solar module has its own numbers and answers its registers, so it keeps working.

### Clearing out what is already there

- **A new repair: "Stale Vaillant eBUS entities".** About fifteen minutes after start the integration compares Home
  Assistant's registry with what it finds on the bus. If something is left over, the repair shows the count and the
  first names. Nothing changes until you select **Submit**. It covers two kinds of leftovers:
  - Entities that nothing provides any more, for example from a zone or a register the controller no longer reports,
    or from an older release. Submit removes them, and any Vaillant eBUS device that is left without entities.
  - Enabled entities that have no data and that a new installation would not switch on, such as storage temperatures
    or solar yield on a system without them, and service or test registers. Older releases created these as enabled,
    and Home Assistant does not change an enabled entity by itself. Submit switches them off but does not delete them;
    each one switches on again when its register returns a value. Home Assistant then reloads the integration once,
    about 30 seconds after the last entity came back.
- **Your own choices are kept.** Entities you renamed, hid, labelled or put in an area are never removed or switched
  off, and neither are devices you renamed or labelled. Nothing is checked while ebusd is not connected or before the
  first discovery after a start has finished.
- **Sensors that fill slowly are left alone.** Sensors that only fill when the myVAILLANT gateway sends a frame, such
  as the compressor and heater counters, are never offered, because they stay empty for a long time. One limit
  remains: a sensor you switched on yourself that is not one of those, and that has no data, is still listed. The
  preview shows its name before you submit. To keep it, do not submit, or give it a name or an area first.
- **"Purge stale entities" in the options is safer.** It used to delete every entity whose state was `unknown`, which
  also removed live entities, for example a holiday date while no holiday is set. It now uses the same check and the
  same preview as the repair, and removes only entities that nothing provides any more.

**After you update:** restart Home Assistant. Entities of zones that are now hidden show as "unavailable" until you
confirm the repair; they are not switched off first. Open **Settings → Repairs**, read the list, and select Submit.
The same list is under **Settings → Devices & services → Vaillant eBUS → Configure → Purge Stale Entities**.

### Also new

- **Heat pump firmware SW0406:** the electrical power shows up as soon as the myVAILLANT gateway asks for it
  (issue #188). The integration only listens to that answer and sends nothing, so the value stays unavailable until
  the gateway has asked once.
- **A stuck eBUS adapter no longer gets hammered.** After four bus errors in a row (`arbitration lost` or
  `read timeout`) on at least two different circuits, the integration pauses its active reads for a minute. The next
  read is a test, and the pause doubles up to ten minutes while it keeps failing. One device that stops answering
  never pauses the others, and a reconnect or a rediscovery starts clean (issue #193). This was built from the report
  and has not been tried on a stuck adapter yet.

### Fixed

- **SW0406 flow and return temperature** were wrong or missing when ebusd has no configuration for the heat pump,
  because this firmware answers with a different number format than SW0303 (issue #188). SW0303 is not changed. If you
  ran 1.11.2 on SW0406, restart Home Assistant after the update; if the old values stay, restart ebusd once, because
  ebusd may keep the earlier definition until then.
- **Mixer movement** of the heating circuits now has the unit `%` and is recorded as a measurement, so Home Assistant
  draws a line instead of coloured bars (issue #190). The value is a signed percentage; -100 means the mixer is
  closed.

- **Cooling Electricity Today** now has a state class, like the heating and DHW counters, so you can pick it in
  the Energy dashboard (issue #194). Home Assistant starts its statistics for this sensor from the update on.

### Requirements

- The minimum Home Assistant version is now 2026.3 (the files said 2025.1 before). The integration is written for
  Python 3.14, and 2026.3 is the first Home Assistant release that runs on it. If you already run 2026.3 or newer,
  nothing changes for you.

### Under the hood

- The code is split into smaller modules (runtime definitions, fallback read planning, graph merging, a table of
  firmware gates, and the register map in themed files) with more tests around them. No change in behaviour is
  intended. Release checks now also require hassfest and HACS validation to be green before a tag publishes.

### Not changed

- The electricity totals that grow in steps of 1000 Wh (issue #194) come from the heat pump. Some units report whole
  kilowatt hours only, others report finer values; the integration passes on what ebusd gives. The "Electricity
  Today" sensors usually count finer; see the troubleshooting guide for how to use them.
- The heating state of the zone and the hot water (issues #191 and #192) is not changed in this release.
- The pause between the definitions the integration sends at startup (issue #193) is not changed yet; it needs a test
  with the reporter's setup.

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
