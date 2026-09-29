# Release 1.10 — Follow-up Plan

Status: **IN PROGRESS**
Date: 2026-09-25
Parent release: `v1.9.5`
Plan origin: `a6f5c2e`; execution base: `89b5e4c` on `release/1.10.0`.
The current candidate contains the reconciled implementation through the #161 telemetry work. The #160 report and new V32 freshness reports from discussion #31 remain evidence-gated and are not included; the earlier BASV3 capture from #31 remains part of the #158 B524 polling work.
Source: `docs/research-new-data.md`, discussion #32, and issues #111, #152,
#158.

## Goal

Resolve the evidence-backed follow-ups from v1.9.5 without adding guessed
registers, unsafe polling, or unverified writes. Every candidate needs an
explicit hardware gate, protocol layout, polling mode, and positive/absent
test path before implementation.

Community data remains valid evidence only when the complete capture is
preserved and the mapping stays scoped to the hardware that produced it.

## Release decision

Issue #158 is in the mandatory 1.10.0 scope. The BASS3 `0708/4304` invalid
position polling regression must be fixed and regression-tested before optional
telemetry or control additions are considered. It is a scheduler and bus-load
bug, not a cosmetic unavailable-state issue.

Implementation decision for #158: remove all twelve active Hc1/Hc2 B524
  `r5` definitions and suppress map-driven, placeholder, and discovery-dump
  fallback reads until a positive capture establishes a safe hardware scope.
The #158 BASS3 capture, discussion #31 BASV3 capture, discussion #32 CTLV3
capture, and the owner's live CTLV2-circuit ebusd logs all show invalid-position
poll replies. The Helianthus register-map fixture contains positive values but
no scan identity or raw hardware capture, so it does not justify active polling
on CTLV2. Keep metadata for registers ebusd discovers independently, preserve
BAS-specific setpoint overrides, and leave graph-based circuit resolution
unchanged.

Historical upgrade note for versions before the #158 fix: ebusd keeps runtime
definitions in memory until its daemon restarts, so an upgrade from a version
that injected the Hc1/Hc2 B524 definitions required one ebusd restart to remove
their old `r5` entries. The current HA reports integration version 1.10.0; for
this release smoke test restart HA only, and restart ebusd only if stale
pre-1.10.0 definitions are found or suspected and the owner explicitly approves.

## Fresh inbox scope (2026-09-25)

## Circuit-resolution hardening (2026-09-26)

The release must not assume that `ctlv2`, `hmu`, `z1`, `hc1`, `hc2`, or `hc3`
are the physical owners available on the bus. `ctlv1` through `ctlv9`, dynamic
`zN`/`hcN` nodes, and controller variants such as `ctlv0`, `ctlv3`, `basv3`,
and `bass3` must route through the discovered `DeviceGraph`.

- **Must — no physical startup defaults:** remove `ctlv2`/`hmu` as pre-discovery
  read/write targets and remove the `z1` climate fallback. Before an authoritative
  graph exists, expose no owner-dependent service read/write or climate entity.
- **Must — role-based ownership:** centralize controller, heat-pump, DHW, and
  primary-zone resolution in `DeviceGraph`. Platform modules, date entities,
  quick-veto, away mode, fallback reads, dump probes, and runtime definitions
  must consume roles or discovered source circuits, not literal aliases.
- **Must — dynamic zones:** replace fixed `hc2`/`hc3` and `z2`/`z3` assumptions
  with numeric circuit helpers and graph capabilities. Cover `ctlv1`, `ctlv4`,
  `ctlv7`, and `ctlv9` owner-routing fixtures, plus `z4`/`hc4` and `z9`/`hc9`
  graph cases.
- **Must — preserve protocol names:** `Z1*`, `Hc1*`, and `Hwc*` register names
  remain valid ebusd protocol names. They must not be renamed to physical
  circuit IDs. Resolve their owner separately from the register name.
- **Must — current CTLV2 compatibility:** the existing CTLV2
  `Hc1RoomTempSwitchOn` sensor remains enabled with unknown state when its value
  is temporarily unavailable. Only the verified CTLV3 `SW0808/HW8004` path
  becomes a select; other CTLV3 firmware remains a sensor.
- **Should — metadata namespace:** keep current `REGISTER_MAP` keys and unique
  IDs for this release, but replace `ctlv2`/`hmu` alias loops with logical owner
  resolution. A full `controller.*`/`heat_pump.*` metadata namespace migration
  is deferred because it would require cache, YAML override, and entity-ID
  compatibility handling.
- **Must — static guardrail:** keep a test that rejects new physical alias
  defaults in runtime routing while allowing protocol metadata, fixtures, and
  explicit hardware gates. This is now covered by
  `tests/test_circuit_routing_guardrails.py`.

### Current implementation status

The first implementation stage is in progress in the release worktree:

- pre-discovery `heating_circuit` and `heat_pump_circuit` now remain unresolved;
- climate setup no longer creates a synthetic `z1` entity;
- controller alias resolution accepts numbered controller circuits through the
  discovered controller role;
- numeric `zN`/`hcN` filtering covers circuits beyond 2 and 3;
- metadata fallback is centralized through circuit families instead of direct
  alias loops;
- CTLV2 room-temperature sensor compatibility remains covered.
- hand-built water heater, datetime, calendar, tank, fixed switch, and derived
  energy-state entities wait for discovered capabilities and late discovery;
- active zone/date/schedule grouping uses discovered `zN`/`hcN` nodes.

Remaining before this stage is complete: run the full release validation and
repeat independent review plus audit on the resulting diff. The full metadata
namespace migration remains explicitly outside this release.

- **Must — issue #158 plus discussion #31/#32 and owner HA logs:** stop
  injecting or fallback-reading these twelve active B524 state registers:
  Hc1/Hc2 FlowTempCalc, MixerPosition, Humidity, DewPointTemp, PumpHours, and
  PumpStarts. BASS3, BASV3, CTLV3, and the owner's CTLV2 circuit all show
  invalid-position polls. Prune cache-only values, keep fallback reads disabled,
  preserve metadata for registers ebusd discovers live, and retain BAS-specific
  setpoint overrides. `Hc1RoomTempSwitchOn` (`RR=0x15`) is separate and is not
  part of this removal. Error-shaped B524 rows must not become placeholder
  entities on otherwise working circuits; a genuine live-discovered B524 value
  must still generate its mapped entity. Cache-seeded B524 placeholders from
  earlier releases must be removed or integration-disabled if no live value
  exists, even when the current factory omits that unsupported entity.
- **Must — HA deployment:** use the workspace's ignored `scripts/deploy.sh`,
  which now replaces the whole integration directory and excludes bytecode.
  That local deployment helper is not part of the release artifacts.
- **Must — connection recovery:** a test-deploy restart briefly failed while
  ebusd fetched its configuration, then the app started and HA reconnected.
  Clear `ebusd_unreachable` only after a non-empty authoritative graph is
  applied successfully; after a transport reconnect, discard the old client and
  require a fresh setup/discovery before clearing it. A
  failed reconnect must return to initial setup retries instead of leaving the
  coordinator on a disconnected client. A successful TCP reconnect invalidates
  service readiness until a fresh graph is applied. Transport EOF and timeout
  errors from `find`, including EOF after a partial response, enter recovery;
  write/drain failures close the socket. A completed empty or error-only `find`
  is not a transport failure, but it is not authoritative: do not build nodes
  from error-shaped rows, apply an empty graph, or clear the repair. Empty
  initial/recovery discovery creates or retains the repair and returns to setup
  retry, even if the in-memory repair flag began false; the delayed path gets
  one bounded retry. An empty post-definition find during recovery also keeps
  the repair and retries setup. Polls receiving an empty/error-only response
  skip fallback reads and keep any pending repair active. Initial discovery
  with no graph nodes leaves the coordinator in setup retry; a later successful
  setup must apply a graph before reads/writes resume. A completed poll clears
  a pending repair only if discovery is ready and all fallback transport reads
  completed. A completed empty/no-usable find or graph-application failure on
  the delayed path receives one bounded delayed retry; a transport failure
  closes the client and returns to fresh setup/discovery instead. Initial,
  post-definition, and graph-application setup failures are retried by the next
  coordinator update. Register-level no-data/unsupported responses leave TCP
  connected and do not create a transport repair by themselves. Recovery polls
  clear the repair only after graph application and all poll fallback reads
  finish; a later fallback transport error keeps the repair active.
  Per-register unsupported replies alongside valid scan/find lines remain
  tolerated.
  Transport exceptions from fallback reads enter recovery; register-level
  no-data or unsupported values remain unavailable and do not alone count as
  transport failure. Polling and public register reads/writes stay gated until
  the discovered graph is authoritative, not just until TCP connects; an empty
  graph is not ready for service reads, writes, or dump export, while scan-only
  nodes retain ownership. Cache pruning must prefer a live raw value over a
  duplicate no-data placeholder for the same register. Tests cover failed
  initial/post-definition discovery (including empty post-definition find) and
  graph-application failure followed by setup retry, delayed
  transport, empty-find, and graph-application retries, duplicate live/no-data
  graph rows, cached B524 placeholder entity retirement, register-level no-data
  without transport repair, recovery-poll fallback failure before repair
  clearance, reconnect false/exception, service
  gating with cache-seeded graphs, and the setup/poll race.
  Cache seeding may retain read-only unavailable sensors, but must not expose
  writable number/select/switch descriptions before authoritative discovery.
- Every entity write path must be capability-complete: quick veto requires
  duration, temperature, and end date/time; away requires its complete zone and
  DHW holiday set; water heater requires operation, target, storage, boost, and
  DHW holiday registers; flow-range climate requires both min/max flow targets.
  Generic user register services remain owner-gated but intentionally accept
  explicit advanced register names.
- **Should — discussion #32:** expose discovered `Hc1RoomTempSwitchOn` as a
  CTLV3 select with `off`, `modulating`, and `thermostat` options. The reporter
  used `vaillant_ebus.write_parameter` to write `thermostat`; the controller
  changed to Expanded, and subsequent direct `read` plus forced `read -f`
  returned `thermostat`. The reporter also correlates `modulating` with Active.
  Gate that conversion to the verified CTLV3 `SW0808/HW8004`; preserve the
  existing sensor metadata for other CTLV3 firmware. For CTLV2, retain the
  sensor registry entry even when its discovered value is temporarily absent;
  it stays enabled with an unknown state rather than being integration-disabled.
  The fixture records Hc1=`thermostat` and Hc2/Hc3=`off`. Keep HC2/HC3 on
  existing metadata until a capture verifies their mode changes and forced
  write/read-back; their `off` values alone do not prove safe write behavior.
  Require tests to assert the existing strict-verification write route and
  expected read-back value, with separate tests for mismatched SW and HW so
  either scan identifier alone cannot admit an unverified variant.
- **Could — discussion #32 HC2/HC3 controls:** defer both selects because the
  current mapping is discovery-only: the capture records only `off` and no
  write transition. Revisit when the owner hardware exposes all enum states
  and forced write/read-back is confirmed for each circuit.
- **Could — B524 Hc1/Hc2 state telemetry:** defer runtime active reads because
  all available hardware captures/logs in scope show invalid-position replies.
  Revisit after a complete capture proves valid response lengths, values, and
  exact scan identity, alongside a safe absent-register path. The Helianthus
  map alone has no such hardware identity.
- **Could — issue #152:** defer the remaining F34 energy entities because the
  inbox contains no entity IDs, source circuits, registry state, or live values
  to classify. Revisit when the requested post-purge registry and source data
  is supplied.
- **Could — issue #101:** defer Quiet mode for HMUX0 SW0406/HW0504. Existing
  `grab result all` output is deduplicated and does not establish both
  B508/0209 payloads in transition order; the entity mapping remains
  speculative/discovery-only. Revisit with an ordered
  loud→quiet→loud raw capture correlated to before/after discovery state,
  exact telegram bytes, and a safe passive layout/absent path.
- **Could — issue #102:** defer Heating state until a standby-to-heating
  capture records the active interval, observed status values, and their exact
  telegrams; Heating remains discovery-only while DHW is confirmed and released.
  Revisit with a fixture proving the mapping and absent path.
- **Could — discussion #32 B509 follow-up:** keep the HMUX0 B509 active-read
  issue deferred because v1.9.5 reads still return invalid-position stubs while
  passive frames have full responses. Revisit after a corrected read or safe
  update-only path is proven against positive and absent fixtures.
- **Must — publish v1.10.0 (owner-authorized 2026-09-29):** create a current HA
  snapshot, deploy the current worktree with `scripts/deploy.sh --restart`,
  complete the HA smoke test, and stop on any regression. Implement and
  independently re-review all three approved dump-safety fixes before deploy.
  Only after a clean
  smoke test, commit and push `release/1.10.0`, open a release PR to `main`,
  wait for branch and PR CI, merge it, create the annotated `v1.10.0` tag on
  the merged commit, and verify the tag CI release ZIP and GitHub release. Do
  not change entity registries, ebusd CSVs, or addon configuration. No
  push/merge/tag occurs before the HA check.
- **Full-candidate gate:** the earlier #161 review/audit covered only the
  worktree delta over `89b5e4c`. The recorded lifecycle review/audit on the
  release branch were not repeated (`docs/plan-1.10.md` lines 539–544), so a
  fresh independent review and audit of the complete `main` → release candidate
  are required before deploy/publication. Use one immutable diff reference.
  Standard-tier review/audit budget: five minutes each; focus on release-scope
  compatibility and existing #158 lifecycle guarantees. Re-review/re-audit any
  changed diff before the final HA/release gate.
- **Owner-approved release blocker fixes (2026-09-29):** the full-candidate
  review/audit found discovery-dump safety gaps; the owner authorized the fixes
  and directly related edge cases. Require exactly one fixture-backed
  `grab started` / `grab stopped` acknowledgement; reject extra lines and
  arbitrary `ok`, `done`, or `grab not running`. Record ownership as soon as the
  exact start ACK is read, before socket cleanup can be cancelled; send global
  `grab stop` only after that ACK. Retain cleanup after a confirmed start is
  cancelled or result retrieval fails. Reject `ERR:` and
  `usage:` and malformed non-telegram text from `grab result all` but allow an
  empty successful result and valid raw telegram lines. A find is usable only
  when the discovery parser accepts a register row (including a no-data
  placeholder) or scan metadata. For unusable `find`, retain raw lines and
  `from_map` metadata while performing zero map probes; preserve permitted
  fallback reads for usable `find`. Read
  grab responses to the protocol's blank-line terminator with a 30-second
  overall deadline and 10,000-line ceiling. Fail explicitly on timeout, EOF
  before the terminator, or the line ceiling; never silently truncate. The
  normal `find`/`info` multiline path also needs a 60-second overall bound and
  10,000-line ceiling in addition to its quiet terminator; malformed/overlong
  lines must close the unusable socket. Classify `find` from the same accepted
  register/scan rows as discovery. Error-only rows do not make a find usable;
  a mixed response remains usable only because it contains another valid row.
  Error-shaped register rows are diagnostic placeholders, not transport syntax
  failures or evidence of a value.
  Empty/malformed LHSs, malformed scan metadata, and unrecognized non-error
  records are protocol-invalid: close the connection and do not apply a partial
  graph. `scan.* = no data stored` is unavailable, not malformed or usable; a
  parseable no-data register placeholder and valid scan metadata are usable.
  Keep the grammar open to unknown circuits/register names and both positional
  and keyed scan metadata; only malformed syntax is invalid. This classifier
  consumes raw ebusd TCP response lines, not terminal transcripts.
  Block coordinator fallback polls when the latest find is unusable even if an
  older graph remains cached. Keep error-shaped register placeholders for
  diagnostics while tracking them separately in `DeviceGraph` and refreshing
  that set after every usable find. Skip them during initial graph application,
  map/placeholder fallback, and active energy fallback, while allowing ordinary
  no-data placeholders to retain their existing fallback behavior. Reject
  incomplete scan identity fields; unknown nonempty IDs remain allowed. Never
  discover, dump, or poll field-shaped keys such as `Status01.temp` as bus
  registers. Exclude field keys from find usability and live-cache updates as
  well as graph/dump/fallback paths. The info command must propagate its initial
  transport timeout so dump export cannot persist a success-shaped incomplete
  dump. Count the full
  multiline transaction from before the first response line and record duration
  through its quiet terminator or failure. An error-only find must clear current
  register values explicitly reported unavailable without replacing the graph
  or clearing its repair. When delayed discovery reports a placeholder/error for
  a key that had raw data, the new unavailable state supersedes the old value in
  the merged graph, immediately clears its live register fields, and recomputes
  the affected node's `has_data` from the merged raw graph instead of OR-ing
  stale flags or ignoring retained raw rows. Before listeners run, publish the
  refreshed coordinator snapshot and
  persist its cache so neither an entity update nor a restart can restore the
  old value. Serialize exports by connected peer/resolved socket
  addresses so a DNS name and its IP alias share the same grab lock. If DNS
  resolution fails and no peer address is available, use a shared per-port lock
  rather than an unsafe host-string fallback. The
  #161 fixture has exactly 200 grab-data lines, equal to the old implementation
  cap. Serialize full dump exports per ebusd endpoint on the Home Assistant
  event loop, and document that manual `ebusctl grab` must not run concurrently;
  external TCP clients cannot share the integration's lock. No unrelated release
  work is approved.
- **Additional row-12 audit regressions:** bound the first response line within the
  same total deadline and record full multiline duration through completion or
  failure; propagate initial `info` transport timeouts. Reject incomplete
  positional/keyed scan identity while allowing unknown nonempty IDs. Preserve
  error placeholders for diagnostics but suppress active reads, including during
  initial graph application and active energy fallback; a mixed valid/error find
  test must assert that the error placeholder remains diagnostic but receives no
  fallback read. Refresh error keys on every usable find, and prove polling can
  resume when a later find returns a normal no-data placeholder. Normal no-data
  placeholders remain pollable. Field-shaped keys such as `Status01.temp` must
  be excluded from find usability, graph registers, raw dump register output,
  live-cache updates, live polling, and fallback reads. Cover delayed initial
  lines, duration logging, incomplete scans, initial-info timeout, error-key
  refresh, and field-key exclusions. Also cover an error-only find clearing a
  previous reading while retaining graph/repair state, delayed graph merge
  replacing old raw data and immediately clearing the live register/node data
  state in coordinator registers, published data, and cache before listeners,
  recomputing node activity from the merged raw graph on partial delayed finds,
  same-endpoint DNS/IP aliases sharing the dump lock, and the shared
  per-port fallback after resolver failure. SW0407 passive definitions must
  resolve from their unique exact scan even if another heat-pump node makes the
  global heat-pump result ambiguous; test setup with both nodes.
- **Owner-approved inbox expansion (2026-09-29):** after the test-suite runtime
  work, investigate issue #160, issue #161, and the new discussion #31 reports
  as possible v1.10.0 candidates. This overrides the previous “No other new
  release candidate” boundary for these three report groups only; it does not
  pre-approve every requested behavior. Implement only candidates classified as
  confirmed or strong assumption with exact hardware/firmware scope, complete
  fixture evidence, and a safe absent path. Keep the other requests deferred
  with evidence and revisit triggers. The owner later authorized deploying the
  candidate to HA, then pushing, merging, tagging, and publishing v1.10.0 after
  the release gate succeeds.

## Authorized HA smoke test and release sequence (2026-09-29)

- The owner authorized the current worktree deployment and release operations.
  `scripts/deploy.sh --restart` replaces `/config/custom_components/vaillant_ebus`
  and restarts HA; it is the only allowed deploy path.
- The only listed full backup is from 2025-08-21 (575 MB, HA 2025.8.2, database
  included). Create a current pre-deploy snapshot through `ha_manage_backup`
  before replacing the integration. If deploy or startup fails, stop; don't
  restore the full snapshot without a new confirmation because that would also
  roll back unrelated HA state.
- Pre-deploy HA-MCP evidence: Core 2026.9.4 is running, the `vaillant_ebus`
  entry is loaded, its error-log search is empty, and the device graph contains
  `hmu`, `ctlv2`, and `vwz`. The heat-pump device reports HW5103, not the
  HMUX0 SW0407 / VWZIO SW0500 target. This smoke test can verify startup,
  existing entity preservation, and absent/nonmatching scan safety, but cannot
  live-verify the new target-specific definitions. Fixture tests remain the
  positive behavior proof.
- Before deployment, record the existing integration entity/device counts and
  selected sensor states. After the restart, verify the config entry is loaded,
  no new `vaillant_ebus` errors appeared, the existing HMU/VWZ entities remain,
  and no HMUX0/VWZIO-target entities were invented on this nonmatching bus.
  `deploy.sh` prints but does not fail on a non-200 HTTP status; the HA-MCP
  post-check is the authoritative startup test.
- **2026-09-29 HA smoke result: PASS.** Deployed via `scripts/deploy.sh --restart`;
  HTTP status 200. HA-MCP confirms Core 2026.9.4, entry `01KYPWHN6AZZKBTPQJYWYT242K`
  loaded, ebusd connected at 26.1.26.1, 188 registers, 176 entities, eight existing
  devices on `hmu`/`ctlv2`/`vwz` topology, and no integration error-log entries.
  Selected flow/return/compressor/DHW/zone values are present. No `hmux0` or
  `vwzio` device was created; target hardware remains unverified live. The entity
  count is 14 lower than the pre-deploy count after field-shaped pseudo-registers
  were excluded; no registry edits were made. A final pre-deploy snapshot was
  requested through `ha_manage_backup`: `2b1c08e7`, 347,760,640 bytes, reported
  successful before the final deployment. The subsequent backup list still only
  showed the 2025 archive, so snapshot-list visibility remains an HA-MCP mismatch.
- **Review evidence (2026-09-29):** independent code review and audit passed on
  executable candidate hash `236d74d3ccdbd61afa78bfa99543838b21a4bbb3536daa87c51574243013c191`
  after the delayed-graph node activity fix. Full validation later passed with
  897 tests and one existing deprecation warning; Ruff, mypy, YAML, version,
  compile, and diff checks passed. This plan records smoke/backup details after
  those gates; the final release gate must consume the complete current patch.
- After a clean HA smoke test: commit the reviewed candidate, push the release
  branch, open a release PR to `main`, wait for branch and PR CI (including
  Ruff, mypy, YAML, pytest, compile, and Hassfest), merge it, tag the merged
  commit with annotated `v1.10.0`, push the tag, then verify the release
  workflow and published asset. Recheck remotes, branch protection, PRs, and
  tags immediately before pushing; never force-push. Any source edit after
  this plan-check requires focused validation, a fresh full suite, review,
  audit, and release-gate evidence for the new diff.

## Candidate matrix

| Investigation priority | Candidate or area | Evidence and scope | Polling/write boundary | Minimum trigger |
|---|---|---|---|---|
| 0 | HMUX0 B509 active reads | **Confirmed family mapping; unsafe active path on target.** #32 HMUX0 `SW0302/HW0504` discovers the three v1.9.5 entities, but integration reads return `ERR: invalid position` while normal `f108` traffic returns full frames | Do not treat discovery or ebusd `done` as a valid value; compare request paths before choosing active reads or update-only definitions | Corrected read or safe update-only proof with positive and absent fixtures |
| 0 | Hc1/Hc2 B524 active state reads | **Invalid-position response confirmed on listed hardware; positive scope remains discovery-only.** #158 BASS3, discussion #31 BASV3, discussion #32 CTLV3, and owner HA CTLV2-circuit logs show invalid-position polls; only the Helianthus map fixture has positive values and it lacks scan/raw hardware provenance | Remove active `r5` definitions; disable coordinator map/placeholder, dump-service and cache-only fallback paths; retain metadata for live ebusd discovery and preserve BAS setpoint overrides | Revisit after a complete capture ties successful full-length responses and plausible values to an exact scan identity, with tested absent definition and fallback paths |
| 1 | HMUX0 B51A yield/current values | **Strong assumption at family level; discovery-only for #32 target.** Upstream family evidence exists, but HMUX0 `SW0302/HW0504` has no matching B51A traffic | Keep B51A separate from B509/B516; active polling safety is unresolved | Target dump with exact frames, values, and safe polling decision |
| 2 | HMUX0 runtime counters | **Confirmed upstream layouts; target decode remains discovery-only.** `hoursum2`/`cntstarts2` layouts match B509 IDs `c40b`, `c50b`, `d70b`, and `d80b`, but runtime datatypes are not implemented | Do not decode as raw `UIN`; preserve units and parsed fields | Runtime datatype support plus positive and absent fixtures |
| 3 | VWZIO immersion metrics | **Confirmed only for HW5103; discovery-only for #32's HW0504.** | Never copy HW5103 layouts to HW0504 | Matching HW0504 traffic and byte-compatible layout |
| 4 | CTLV3 `Hc1RoomTempSwitchOn` | **Confirmed for CTLV3 `SW0808/HW8004`, Hc1 only.** #32 proves B524 `020002001500`, enum values, and write behavior; HC2/HC3 currently show only `off` | Add a select only for the resolved CTLV3 controller on `SW0808/HW8004` when Hc1 is discovered; retain sensor metadata on CTLV2 and unverified CTLV3 firmware, and remove matching legacy sensor registry/cache entries only on the verified hardware | Fixture coverage for all three options, write resolution, CTLV2 and other CTLV3 firmware sensor preservation, and old sensor-to-select migration |
| 5 | CTLV3 `HwcLegionellaDay/Time` | **Confirmed upstream mapping; target writable behavior is discovery-only.** B524 `0x2a`/`0x2b` mapping exists, but the target transition is absent | No write path from upstream evidence alone | Target before/after capture and direct write/read-back proof |
| 6 | BAI00 `FlowTempDesired` | **Read path confirmed; write unproven for SW0108 and disproven for SW0107.** `0e3900` has negative write evidence on SW0107 | Do not route through `SetModeOverride` or treat `done` as acceptance | Byte-for-byte write capture, forced read-back, and boiler state transition |
| 7 | #152 remaining energy entities | **Discovery-only.** v1.9.4 removed stale pump/fuel values, but F34 still shows Electrical, Environment, and Solar entities after purge | Do not delete entities or change defaults from symptoms alone | Entity IDs, source circuits, raw names, values, and `disabled_by` state |
| 8 | #111 `SetModeOverride` | **Read support confirmed; write effect disproven on BAI00 SW0107 and unknown on SW0108.** Issue is closed | Keep the compatibility definition unchanged | Reopen only with target write, read-back, and observable mode-transition evidence |
| 9 | #160 VCC ecoCOMPACT / VRC 700 climate | **Evidence pending.** Existing report lacks a discovery dump and does not show whether live coordinator values match the disk cache | Do not change `_zone_is_valid()` based on `0.0`; ask for a fresh dump and the minimum runtime detail only if it remains ambiguous | Review a v1.9.5 dump with `700` scan identity and `Z1*`/`Hc1*` values; distinguish current-temperature absence from target-temperature data flow |
| 10 | #161 HMUX0 `SW0407/HW0504` and VWZIO `SW0500/HW0504` | **Implementation and local validation complete; #161 delta review/audit passed. Executable candidate code review/audit and HA smoke passed. The full-patch release gate must consume the current plan/evidence record before publication.** Preserve exact scans; #32 `SW0302/HW0504`, #102, and PR #598 HW5103 evidence do not silently generalize. Daily Wh counters `HcElecConsDay`/`HwcElecConsDay` use `total_increasing`; CTLV3 `YieldTotal` uses energy/kWh/`total` per upstream B524 `0x3e` `energy4` definition and metadata only (no fallback read). | Add a scan-only physical `vwzio` node only for exact observed SW0500/HW0504 (no entity until data is discovered) so passive `B516/14` can be gated to its owner; suppress generic active VWZIO `Status01` on that scan because its layout is only sourced from HW5103. New observed B509/B51A/VWZIO definitions are passive `u`; do not active-poll B51A; keep D-code and `PowerConsumptionVwz` metadata `fallback_read=False`; preserve existing B509 paths on SW0302/SW0303 and active B516 day-counter reads; on SW0407 suppress coordinator and dump-service map/placeholder fallbacks for the exact status + 26-name set and all passive-only names, even when ebusd rejects a definition. `RunDataStatuscode=100` is Standby, not Heating. VWZIO B511 `/021801/02` heater-counter semantics remain discovery-only for HW0504; VWZIO B516 `14` is station power, not heater-only power. | Fixture the complete capture; positive, absent/no-data, scan-only, nonmatching scan, passive-definition failure, and SW0302/SW0303 counter-fallback tests; assert no duplicate messages or active fallback; keep #102's Heating-transition proof pending |
| 11 | Discussion #31 recoVAIR / V32 freshness | **No change to the reported symptoms established.** Skyler's dump has V32 scans but no loaded config/find values; szflo's graph already creates V32 entities, but a 10-second snapshot cannot prove update cadence. Upstream #320 supports B509/03298803 as a FanLevelDay write/update; it does not establish sensor freshness | Do not create a virtual ventilation node or change poll intervals from one snapshot; don't fold a control/update message into this freshness fix | For Skyler, identify the correct address/config assignment; for szflo, obtain timestamped ebusd and HA values for named registers |
| 12 | Discovery-dump capture and fallback validation | **Implementation and full validation complete (897 tests); independent code review/audit passed on the executable candidate. The release gate must consume the exact full patch, including this plan/evidence record, before publication.** `grab` acknowledgements, global stop ownership, response validation/completion, timeouts, overlapping exports, 200-line truncation, and unusable-find map/coordinator reads need fail-closed handling | Require exactly one fixture-backed start/stop acknowledgement; record ownership immediately when the start ACK arrives, before socket cleanup; issue stop only after ownership. Serialize integration dump exports to the same ebusd endpoint on HA's core event loop and warn against overlapping manual grabs. Validate each result line as a raw hex telegram/count record or accept an empty result; reject malformed text and `ERR:`/`usage:`. Read to the blank-line terminator with a 30-second total deadline and 10,000-line cap; timeout, EOF, or cap are explicit failures. Bound normal `find`/`info` responses to 60 seconds and 10,000 lines; preserve the quiet terminator and disconnect on total timeout, EOF, invalid UTF-8, or overlong lines. A `find` is usable only for syntactically accepted rows (unknown circuit/register names remain allowed): register rows including no-data placeholders, or valid positional/keyed scan metadata. Reject both `ERR:` and `(ERR:` rows; a no-data scan is unusable. Malformed syntax such as `= value`, invalid scan metadata, or unknown non-error row shapes is protocol-invalid: close the connection and do not apply a partial graph. Preserve raw lines/`from_map` metadata but skip dump probes and coordinator fallback reads, even with a retained older graph. | Tests for extra ack lines, rejected/error/ambiguous start with no global stop, cancellation during start socket cleanup and after confirmed start, cleanup on result failure, same-endpoint concurrent exports, TCP response over 200 lines, >2-second gap within total deadline, cap/EOF/timeout, malformed/result errors/empty result, `find`/`info` total trickle timeout and 10,000-line cap, invalid UTF-8/overlong-line socket cleanup, `= value` and malformed register/scan rows with connection cleanup, error-only find and no-data scan as unusable, no-data register and valid positional/keyed scans as usable, stale-graph coordinator with zero reads and no partial graph, dump diagnostics preserved with zero probes, usable-find allowed probes |

For #161 HMUX0 `SW0407/HW0504`, suppress active map/placeholder fallback in both coordinator polling and discovery-dump map probes for B511 `Status00`, `Status01`, and `Status07`, plus these 26 B51A-oriented map-probe names: `BuildingCircuitFlow`, `CopCooling`, `CopCoolingMonth`, `CopHc`, `CopHcMonth`, `CopHwc`, `CopHwcMonth`, `CurrentCompressorUtil`, `CurrentConsumedPower`, `CurrentYieldPower`, `FlowTemp`, `FlowTemperature`, `HoursCool`, `LiveMonitorCurrentConsumedPower`, `SourceTempInput`, `SourceTempOutput`, `TotalEnergyUsage`, `YieldCoolDay`, `YieldCooling`, `YieldCoolingMonth`, `YieldHc`, `YieldHcDay`, `YieldHcMonth`, `YieldHwc`, `YieldHwcDay`, and `YieldHwcMonth`. Never actively fall back for a passive-only definition on the matching scan, even if ebusd rejects the definition. `SourceTempInput` is included because the repository documents a 3-byte air/water stub response for that read, although the #161 dump redacts its result. Preserve existing active B509 paths on SW0302/SW0303 and active B516 day-counter reads; tests cover all 29 map-probe pairs, passive-definition failure, and daily counter reads against the complete #161 fixture.

## Prepared execution tracks

These tracks are independent until implementation and validation:

1. **#158 polling removal:** update coordinator and dump-service tests first,
   then remove the twelve active Hc1/Hc2 definitions and disable coordinator
   map/placeholder and dump-export fallback reads for their metadata. Verify
   BASS3, BASV3, CTLV3, and CTLV2 graphs do not poll them, stale cache-only
   values are pruned, and live `find` values still generate mapped entities.
   Preserve BAS setpoint definitions and `Hc1RoomTempSwitchOn`.
2. **CTLV3 room-temperature select:** update mapping/entity tests and write
   resolution tests for Hc1 only; remove matching cached sensor descriptions
   before forwarding the new select; defer HC2/HC3 controls until write
   evidence exists, and do not touch `Hc1RoomTempModulation`.
3. **#152 evidence intake:** classify the remaining F34 entities from registry
   and source-circuit data; no production edit until that evidence exists.
4. **BAI00 write boundary:** preserve current compatibility behavior and add
   no write support without target hardware proof.
5. **HMUX0 B509 investigation:** keep the three active definitions unchanged
   until ebusd-level request/response evidence proves a safe active or
   update-only mode.
6. **Transport recovery:** propagate socket resets through single- and
   multi-line ebusd commands, reject partial find responses, gate reads/writes
   and dump export on a non-empty authoritative graph, and make setup retryable
   after initial/post-definition discovery failures. Bound delayed discovery
   retries and keep repairs active until a verified recovery cycle completes.

## Evidence incorporated

- **Discussion #31:** The complete BASV3 capture identifies controller
  `SW0708/HW4304` and shows all twelve Hc1/Hc2 B524 runtime state definitions
  returning `ERR: invalid position`; retain the full capture as fixture evidence.
- **Discussion #32:** The complete dump identifies HMUX0 `SW0302/HW0504`,
  CTLV3 `SW0808/HW8004`, and VWZIO `SW0302/HW0504`. It supports the three
  B509 candidates, but the v1.9.5 active-read path does not decode on the
  target. Its Hc1/Hc2 B524 state probes return invalid-position errors. It
  explicitly confirms the Hc1 Room Temperature Influence enum and write
  behavior; HC2/HC3 slots only show `off`, so their writable behavior remains
  unverified. The entity change is therefore CTLV3-only; CTLV2 retains the
  existing sensor classification.
- **Issue #152:** The v1.9.4 stale-cache and fuel-counter fix was verified.
  The remaining energy entities need registry and source-circuit evidence
  before default-enable or deletion changes.
- **Issue #111:** The issue is closed. Its remaining value is a write-safety
  boundary, not a new feature claim.
- **Issue #158:** The BASS3 one-byte response is a real invalid-position
  regression, not ordinary unavailable data. Stop the unconfirmed polls before
  broadening filtering.
- **Owner HA ebusd logs:** repeated `ctlv2 Hc1FlowTempCalc` poll attempts on
  2026-09-25 return `ERR: invalid position` (and occasional read timeouts),
  confirming the same active-poll problem on the connected installation.
- **Owner HA recovery:** after ebusd recovered from a transient startup timeout,
  the integration connected and loaded but the old `ebusd_unreachable` repair
  remained active. The successful initial connect/discovery path now clears it.
- **Owner HA test deployment:** an earlier 1.10.0 worktree version was deployed
  before the final retry/repair fixes. HA loaded that version, ebusd returned to
  `started`, diagnostics reported `connected: true`, the CTLV2 sensor remained
  registered, and no removed B524 polls appeared after the successful ebusd
  restart. Its stale `ebusd_unreachable` repair remained, so the final current
  candidate still needs a confirmed redeploy and HA-MCP verification.

## Implementation stages

### 1. Evidence

- Preserve complete captures under `tests/fixtures/community/`.
- Record scan identity, firmware, owner circuit, message ID, sub-address,
  request, response length, response bytes, state, and occurrence count.
- Search upstream issues and pull requests by exact IDs and payload fragments.

### 2. Candidate decision

- Classify each row as `confirmed`, `strong assumption`, `speculative`, or
  `discovery-only`.
- Decide `r`, update-only, or out-of-scope explicitly.
- Resolve the owner circuit through the discovery graph and raw register source.
- Define positive, absent, invalid-position, and stale-cache expectations.

### 3. Implementation

- Use the existing data-driven runtime, mapping, discovery, and entity paths.
- Add only hardware-gated definitions with safe absent behavior.
- Add fixture-backed positive and absent tests.
- For writes, require direct acceptance, forced read-back, and a hardware state
  transition.

### 4. Validation and release gate

- Run focused tests, the full test suite, Ruff, format checks, compileall, and
  version checks.
- Review active polling, circuit ownership, field parsing, sentinels, fixture
  provenance, and compatibility.
- Require independent review and audit before the 1.10 release decision.
- Require independent standard-tier code review and audit for this release
  scope; record both outcomes and references before HA deployment.
- The 2026-09-25 review/audit PASS was for an earlier snapshot based on
  `a6f5c2e`; it is historical and does not clear the current worktree.
- Current worktree validation on 2026-09-26: `.venv/bin/pytest -q` **778
  passed, 1 warning** (the existing `resolve_circuit()` deprecation warning at
  `tests/test_coordinator.py:541`); Ruff check and format check passed,
  `python3 tools/version.py check` reports `1.10.0` in sync, compileall,
  `git diff --check`, and `bash -n scripts/deploy.sh` passed.
- The pre-deployment review/audit requirement was completed on executable
  candidate `236d74d3ccdbd61afa78bfa99543838b21a4bbb3536daa87c51574243013c191`
  before the HA smoke test. Later plan/evidence edits receive their own exact-
  diff check before publication.
- Deploy the release candidate to the owner's HA system only with
  `scripts/deploy.sh --restart`, after the pre-deploy snapshot. The script
  restarts Home Assistant. Do not restart ebusd for this delta: HA-MCP reports
  the installed integration is already 1.10.0 and this candidate adds no active
  B524 definitions. If stale pre-1.10.0 `r5` definitions are found or suspected,
  stop and request explicit approval before an ebusd app restart.

  Verify through HA-MCP:

  ```python
  ha_get_app(slug="b4d7ad18_ebusd")
  ha_get_integration(
      entry_id="01KYPWHN6AZZKBTPQJYWYT242K",
      include_diagnostics=True,
      diagnostics_data_path="data.ebusd",
  )
  ha_get_system_health(include="repairs,config_check")
  ha_get_entity(entity_id="sensor.home_woonkamer_z1_room_temp_threshold_hc1")
  ha_get_logs(source="supervisor", slug="b4d7ad18_ebusd", limit=500, order="newest")
  ```

  Confirm ebusd is `started`, the integration entry is `loaded` on `1.10.0`,
  and `diagnostics.data.connected` is `true`. The repair list must not contain
  `ebusd_unreachable`, the config check must pass, and the CTLV2 entity registry
  entry must remain enabled. Inspect ebusd log lines after its latest successful
  startup and confirm none of the twelve removed Hc1/Hc2 registers are actively
  polled. Allow normal setup retries to complete: a successful reconnect still
  requires a fresh non-empty graph and successful graph application before
  readiness or repair clearance. Home Assistant diagnostics expose the local
  controller circuit as `ctlv2`, but not its scan identity; the current logs
  already show invalid-position polls. This local system cannot live-test the
  CTLV3-only select or BAS absent paths, so fixture regressions remain the
  correctness proof for those hardware variants.
- Publish under the owner's explicit 2026-09-29 authorization only after HA
  smoke, full-candidate review/audit, and release-gate approval. Push the release
  branch and open a PR to `main`; require CI, HACS, and Hassfest checks to pass
  before merging. Tag the merged commit with annotated `v1.10.0`, push the tag,
  then verify tag CI and the published release ZIP.

## Rules

- A new dump promotes only the matching hardware and firmware row.
- A zero-result upstream search does not prove that a mapping is absent.
- Field entries are not independent registers; map and poll their parent.
- Do not modify ebusd CSV files or set `--configpath`.
- Do not treat observed traffic from another master as proof that an active
  integration read is safe.
- Deferred candidates remain unavailable instead of exposing guessed values.

## Explicitly out of scope

- Generic MQTT-name-to-register mappings.
- Hardware-agnostic B51A or VWZIO definitions.
- BAI `FlowTempDesired` or `SetModeOverride` write claims without target proof.
- Remote Home Assistant registry edits or live writes by the agent.

## Lifecycle gate follow-up before HA test deployment (2026-09-28)

Risk: significant and release-sensitive. Keep publication blocked until the
lifecycle findings are fixed and independently re-audited. The owner may authorize
a test deployment to personal HA separately. No commit, push, tag, entity-registry
edit, or live register write is in scope.

Initial audit reference: base `a6f5c2e2c08d58283f402c995d8b729db60b750a`,
worktree SHA-256 `46b35e6136edd11c1f98de173d29d00cc6a04677b66dc94e566090f350af902e`.

### Must

- Stop dump map probes immediately after unload is requested, including when
  `find` or an earlier map read was already awaited.
- Stop fallback-read mutations after unload, including register/cache updates,
  graph additions, entity regeneration, and registry enabling.
- Keep connect/discovery single-flight when a failed platform unload is
  cancelled while an existing setup task is still active; preserve retry after
  that task completes.
- Add event-controlled regressions for each race, then run the full documented
  validation suite and separate independent review and audit of the changed
  lifecycle paths.
- Test-deploy only with explicit owner authorization: replace
  `/config/custom_components/vaillant_ebus/` from this worktree and restart HA.
  Restart ebusd only if stale pre-1.10.0 runtime definitions are found or
  suspected and the owner explicitly approves that separate app restart. Verify
  the entry, diagnostics, repair state, CTLV2 entity, configuration check, and
  ebusd startup logs through HA-MCP. Full-candidate review/audit and the release
  gate remain mandatory before publication.

### Plan-check

- The audit findings affect direct lifecycle invariants in `dump_service.py`
  and `coordinator.py`; they do not justify unrelated release cleanup.
- The map-probe helper must receive a lifecycle check so it can stop within its
  probe loop, rather than waiting for the outer exporter to regain control.
- Fallback state must not be mutated from a transport value returned after the
  unload flag changes. Any subsequent await before graph/entity updates needs a
  fresh gate.
- `_started` must still reset immediately on unload as requested. Single-flight
  setup tracking must therefore be independent of `_started`, and must not
  prevent a fresh retry after the active task exits.
- Historical 2026-09-28 lifecycle test deployment replaced
  `/config/custom_components/vaillant_ebus/`, restarted HA, and restarted the
  `b4d7ad18_ebusd` add-on. That was a separate, earlier test; the current
  2026-09-29 release plan restarts HA only unless stale pre-1.10.0 definitions
  are found or suspected and the owner explicitly approves an ebusd restart.
  No other remote files or HA registries are changed.

### Could / explicitly out

- Could: no additional lifecycle refactor beyond the three audit findings;
  revisit only if testing exposes another bypass of the same unload invariant.
- Explicitly out during the 2026-09-28 lifecycle-fix stage: publish, commit,
  push, tag, remote registry edits, and protocol/register writes. The owner
  authorized a separate 1.10.0 release sequence on 2026-09-29; see the current
  release plan and HA gate above.

### Execution evidence

- The first independent audit found three medium lifecycle races in dump map
  probes, fallback-read state mutation, and concurrent setup after unload
  cancellation. All three now have event-controlled regression tests.
- Targeted coordinator and hardening tests: **203 passed, 1 existing warning**.
- Full validation after the fixes: **790 passed, 1 existing warning**; Ruff
  check, the documented format check, version check (`1.10.0`), compileall,
  `git diff --check`, and `bash -n scripts/deploy.sh` passed.
- Separate standard-tier delta review and audit of the lifecycle implementation
  remain required before release publication.
- Validation cadence per owner direction: run focused regression tests for each
  audit-fix batch; hold the full suite until all known lifecycle findings are
  closed, then run it once before final review/audit and release publication.
  The 797-test run above predates the latest audit findings and is not final proof.
  A standard `git diff --binary <base> -- <four lifecycle files> | sha256sum`
  fingerprint is used for subsequent review/audit handoffs.
- Prior full validation on lifecycle diff `58ddb429d78c1824eb6fb5c4740aa0a8f70b3e88f7b7d1adb27b3578cc3564e2`:
  **801 passed, 1 existing deprecation warning**; Ruff check and format check,
  version `1.10.0`, compileall, `git diff --check`, and deploy-script syntax pass.
  Fresh independent final review, audit, and release-gate decision remain before publication.
- The delta review found a missing intent comment on `async_stop()`. The separate
  delta audit found three additional lifecycle races in cache seeding, cancelled
  setup retry, and dump persistence. User approved expanding the must-scope on
  2026-09-28; add regressions, rerun full validation, then repeat independent
  review and audit on the new exact implementation diff.
- Previous expanded lifecycle implementation diff reference (base
  `a6f5c2e2c08d58283f402c995d8b729db60b750a`, lifecycle-file patch SHA-256
  `58ddb429d78c1824eb6fb5c4740aa0a8f70b3e88f7b7d1adb27b3578cc3564e2`).
- Expanded lifecycle validation: **797 passed, 1 existing deprecation warning**;
  Ruff check and documented format check passed; version check reports `1.10.0`;
  compileall, `git diff --check`, and deploy-script syntax check passed.
- Independent standard-tier review and audit on the expanded exact diff are
  required; the earlier delta findings are addressed but do not count as passes.
- The expanded delta audit/review found three further lifecycle cases: setup
  cancellation after transport promotion leaks the active client; the stopped
  polling return path can persist cache values; dump output can be finalized if
  unload starts during YAML I/O. User approved this second scope expansion on
  2026-09-28. Add event-controlled regressions and revalidate. Publication/release
  remains blocked until fresh independent review and audit pass.

- Final lifecycle diff after the last audit findings: canonical SHA-256
  `99eb8c38e12adabded50e41e965aedfdb546d99bb9be240fa5b25ac1db68f650`. Full
  validation: **816 passed, 1 existing deprecation warning**; Ruff, documented
  format checks, version `1.10.0`, compileall, diff-check, and deploy-script syntax
  passed. Independent final review/audit were not repeated at the owner's request;
  this does not clear publication/release readiness.

- Historical record: the owner requested a lifecycle-fix test deployment on
  2026-09-28, distinct from publishing. It deployed that earlier worktree and
  restarted HA and ebusd; the evidence follows. This does not substitute for
  the current #161 candidate's post-deploy smoke test or authorize its release.

### HA test deployment evidence (2026-09-28)

- Installed the uncommitted `release/1.10.0` worktree with
  `scripts/deploy.sh --restart --skip-validate`, then restarted the
  `b4d7ad18_ebusd` add-on through HA-MCP. No registry or HA configuration files
  were changed.
- HA 2026.9.3 is `RUNNING`; the `vaillant_ebus` entry is `loaded`, diagnostics
  report integration version `1.10.0`, ebusd connected, ebusd `26.1.26.1`,
  19 discovered registers, and 176 entity descriptions.
- System health reports no repairs and a valid config check. The existing CTLV2
  Room Temp Threshold entity remains enabled and currently reports `unknown`.
- ebusd add-on `b4d7ad18_ebusd` is `started` on `26.1.8`. No active poll of the
  twelve removed Hc1/Hc2 B524 registers appeared in the newest 300 add-on log
  lines after its restart.
- This is a test deployment only. The worktree remains uncommitted and unpushed;
  no release/tag was created. Fresh independent final review/audit were not run
  after the owner asked to stop those passes, so publication readiness remains
  uncleared under the release policy.
