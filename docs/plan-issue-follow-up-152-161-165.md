# Issue Follow-up Plan: #152, #161, #165

Date: 2026-10-02

Base: `main` / `origin/main` at `48af49b`

Released baseline: `v1.10.2` at `44f11a9083cd83da04139b690f0d117d96bc23b6`
Risk: **significant; hardware-scoped protocol and entity behavior**

## Goal and boundaries

Determine what evidence is still missing for the three open issues and only
implement the #161 register path supported by the exact HW0504 captures and
correlated operating states. The v1.10.2 discovery-dump export fix is already
released; this work must not reopen or duplicate it.

Do not change Home Assistant entity/device registries, ebusd configuration or
CSV files. Do not write to eBUS registers. Do not weaken the discovery-readiness
guard or claim that the post-crash HTTP 500 is fixed. Do not infer timer layouts
or register meanings from plausible values alone.

## Evidence and scope

### Must

- **#152 — evidence follow-up only; no mapping change.** The F34 user has not
  supplied the requested post-v1.10.2 entity list. The existing request already
  asks for HA entity IDs, current state, unit, enabled/disabled status, and the
  source circuit/register if visible. The complete v1.9.0/v1.9.2 dumps include
  two static snapshots for some values; they do not prove that a value is stuck,
  identify current entity-registry state, or establish a unit for the BAI
  energy total. Wait for the requested list and do not infer mappings from the
  snapshots.
- **#161 — keep recovery separate from features.** v1.10.2 shipped the
  auto-grab dump-export fix. The HTTP 500 after ebusd crashed remains
  unconfirmed on v1.10.2. Preserve the exporter’s authoritative-discovery
  readiness guard. A recovery change requires fresh logs from the reporter
  after the update and after ebusd has returned; the owner’s different HA
  instance cannot verify that failure.
- **#161 — add only the correlated VWZIO DHW runtime/start counters.** The
  reporter’s exact scan is `VWZIO SW0500/HW0504`. The existing 2026-09-28 dump
  records B511/021802 as `69 min / 2 starts`. The 2026-09-30 idle dump records
  `106 min / 4 starts`; the reporter documented two backup-heater runs of
  approximately 13 and 24 minutes between those observations. The 37-minute
  and two-start delta matches the reported events. Raw request/reply frames
  are `f176b511021802 / 09004500000002000000` and
  `f176b511021802 / 09006a00000004000000`.
- Upstream [PR #598](https://github.com/john30/ebusd-configuration/pull/598)
  documents the same B511/1802 message family as immersion-heater runtime and
  starts, with `IGN:1`, `minutes4`, and `cntstarts` fields (four bytes each).
  Its live-tested hardware is VWZIO SW0901/HW5103, not the reporter’s
  SW0500/HW0504. The HW0504 response body has the same nine-byte shape: one
  ignored byte, `69`/`106` little-endian minutes, and `2`/`4` little-endian
  starts. Together with the correlated before/after values, classify the HW0504
  mapping as a **strong assumption**, not local live verification.
- Add `RunStatsImmersionHeaterHwc` as a **passive `u` definition** only for the
  uniquely discovered VWZIO circuit at slave `0x76` with the exact
  `SW0500/HW0504` scan. Preserve the scan address in the device graph; a matching
  scan identity on another address or conflicting scans must not authorize this
  definition. Expose its
  captured runtime in minutes and starts as separate diagnostic sensors. Do
  not actively poll, probe, or write these registers. Keep the value unavailable
  when the frame/register is absent. Set `fallback_read=False` on the mapped
  parent register as well: `coordinator._fallback_read()` and the discovery
  dump's `_dump_registers()` can both actively probe a mapping entry if ebusd
  rejects the passive definition.
- **Metadata scope is graph-driven, not an extra scan gate.** The custom
  passive definition above is only injected for SW0500/HW0504. The entity
  metadata and field parser apply only when the discovery graph actually
  contains `RunStatsImmersionHeaterHwc`; with `fallback_read=False`, the mapping
  cannot create an entity or trigger a map probe by itself. Upstream PR #598
  also provides live, state-correlated support for the same fields on VWZIO
  SW0901/SW0902 HW5103, including runtime growth and start-count changes. Keep
  that known variant usable when its own ebusd discovery exposes the register;
  do not claim compatibility beyond these evidence-backed scans. Add a
  graph-driven regression using the exact HW5103 frames from
  `tests/fixtures/community/vwzio_hw5103_pr598_b511_stats.yaml`, plus an
  absent-register graph proving the mapping alone creates no entity. This is
  an excerpt of the raw PR evidence, not a complete discovery dump.
- Regression tests must load complete, untrimmed community captures, assert
  scan identity and the two exact decoded frame values, verify the entity
  metadata, verify that absent frames create no normal entity/value, and prove
  neither fallback reader actively reads the register if definition fails or
  the scan is missing/non-matching.

### Should

- **#161 already-shipped requests:** the six HMUX0 Hc/Hwc environmental-yield
  registers shipped in v1.10.1, and the reporter supplied plausible values on
  that hardware. Current tests and metadata define energy state classes for
  `YieldTotal`, the daily electricity counters, and those six counters. The
  `PowerConsumptionVwz` sensor is already passive and gated to VWZIO
  SW0500/HW0504. The four 2026-09-30 captures correlate it to 4.695 kW during
  the heater-active state and 0.005 kW while idle. Keep its meaning bounded to
  hydraulic-station power. The report that new entities disappeared or stayed
  unavailable was from v1.10.1; no post-v1.10.2 entity list confirms whether it
  persists, so do not claim that availability is fixed.
- Preserve the four complete 2026-09-30 #161 discovery dumps as community
  fixtures with source URLs and provenance, without trimming unrelated find or
  grab records. Use them to test the existing `PowerConsumptionVwz` passive
  mapping: B516/0114 is 4.695 kW during the reported heater-active capture and
  0.005 kW in the idle captures. Keep its meaning as **hydraulic station power**;
  the captures do not justify labelling it heater-only power.
- Add a regression for the existing station-power decode only if it can use the
  captured response bytes directly and does not change its current hardware gate
  or polling behavior.

### Could — deferred, with revisit trigger

- **#152 F34 values and enablement:** no source mapping/default changes until
  current entity IDs, states, units, enablement, and source registers arrive.
  Revisit when the reporter posts that list after v1.10.2. A fresh dump is only
  needed if the listed source/value cannot be traced against the existing dumps.
- **#161 VWZIO B511/021801 heating counters:** the current HW0504 capture shows
  only a zero value, with no correlated heating-mode backup-heater run. Revisit
  after a capture correlates a heating backup-heater cycle with a changed value.
- **#161 VWZIO B516/0x49 energy total:** one value (`6487`) and an approximate
  energy estimate do not establish register meaning or units. Revisit with
  before/during/after captures around a known heater interval and an independent
  energy reference.
- **#161 HMUX0 telemetry and zone-3 entity:** telemetry definitions are already
  present for the reported scan, but the available user report does not confirm
  their post-v1.10.2 states. A single HMUX0 B511 counter snapshot (`459/12` and
  `670/25`) does not correlate those counters to compressor state transitions.
  Revisit with current entity IDs/states and time-correlated running/idle
  captures from the exact scanned hardware.
- **#165 BASS3 calendars:** the reported `{prefix}_Monday` registers return
  `ERR: invalid position in decode`; `_Monday0` does not exist on this device.
  Upstream `--comments --all` searches covered `b524`, `b524 0301000200`,
  `b5240301000200`, `3115b5240301000200`, `31 15 b524 03 01 00 02 00`,
  `CcTimer_Monday`, `BASS3 timer invalid position`, `BASS3 CcTimer_Monday`,
  `B524 BASS3 0708 4304`, and `0301000200`. The exact `b524 0301000200`
  hit in PR #598 is a CTLV2/VRC700 `15.700.csv` timer with three `from`/`to`
  pairs; it is not a BASS3/HW4304 layout. The spaced full request also matched
  old VR65/B512 issue #31 and VRC430 PR #15, neither a BASS3 timer mapping. No
  query found a matching BASS3 layout. The existing restored calendar entries
  remain unavailable; registry cleanup is out of scope. Do not recreate
  calendars or invent a layout. Revisit only with a decodable BASS3 capture or
  strong upstream evidence matching the exact message and field layout.

## Plan-check questions

1. Do the captured B511 request, response length, field offsets, and state
   changes support decoding `021802` as minute runtime plus starts on the
   reporter’s exact SW0500/HW0504 variant?
2. Does the proposed `u` path remain passive, use the scanned physical VWZIO
   circuit, and stay unavailable when the register or matching scan is absent?
3. Are the existing export readiness guard, #152 mapping boundary, and BASS3
   calendar behavior explicitly outside the implementation diff?
4. Do fixture additions preserve full capture provenance and all raw find/grab
   records, and do planned tests cover both positive and absent paths, including
   failed passive definitions through both active fallback readers?
5. Is the station-power name bounded to the hydraulic station rather than
   overclaiming heater-only power?

## Validation and review gates

- Targeted issue #161 coordinator, fixture-integrity, multi-field, and entity
  factory tests.
- Repository validation: Ruff, configured format check, full pytest suite,
  version consistency, compileall, and `git diff --check`.
- Independent plan-check before implementation; independent review and audit
  against the exact diff after validation.
- HA-MCP inspection is read-only except for the release smoke exports authorized
  in `docs/plan-1.10.3.md`. The owner subsequently requested the v1.10.3 release;
  its separate gates govern deployment and publication. No HA registry/config
  changes, ebusd CSV changes, or eBUS register writes are in scope. Do not state
  release readiness or a release date before those gates pass.

## Gate ledger

| Gate | Status | Evidence |
|---|---|---|
| Initial state | PASS | `main` equals `origin/main` at `48af49b`; annotated `v1.10.2` points to published merge commit `44f11a9`; issue #152/#161/#165 are open |
| Plan-check | PASS | Independent re-check confirmed `fallback_read=False` covers coordinator and dump-service active fallbacks, verifies the strong-assumption HWC layout and state delta, and accepted the issue boundaries and BASS3 search inventory |
| Implementation | COMPLETE | Added the passive VWZIO SW0500/HW0504 HWC definition; metadata remains graph-driven for the separately upstream-confirmed HW5103 variant; added failed-definition fallback guards, four source-preserved captures, and frame/entity regressions |
| Validation | PASS | Ruff check/format, strict configured mypy, 943 pytest tests, version check, compileall, and `git diff --check` passed |
| Review | PASS | Independent review confirmed the scoped definition, graph-driven metadata, fixture coverage, and issue boundaries |
| Audit | PASS | Independent audit closed the HW5103 metadata concern using PR #598 hardware evidence and traced coordinator/dump fallback, entity creation, absent-data, and readiness paths |
| Release | IN SCOPE | Owner explicitly requested v1.10.3; candidate actions and gates are tracked in `docs/plan-1.10.3.md` |
