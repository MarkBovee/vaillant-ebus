# Release 1.10.3 Plan

Status: **BLOCKED — HMUX0 fallback safety correction and final release gates remain**

Planning date: 2026-10-02

Base: `main` / `origin/main` at `48af49b`

Previous release: `v1.10.2` at `44f11a9083cd83da04139b690f0d117d96bc23b6`
Implementation branch: `release/1.10.3`

## Goal

Release the evidence-backed VWZIO DHW backup-heater runtime/start counters for
the reporter’s `SW0500/HW0504` scan and the owner-requested PR #164 metadata
using the attached setup dump and the reporter’s write-test statement accepted
by the owner. Preserve the
v1.10.2 dump-export behavior and discovery-readiness guard. Do not claim that
the separate post-ebusd-crash HTTP 500 is fixed, and do not restore the BASS3
calendars.

This is **significant and release-sensitive**. It adds HA entities and a
hardware-scoped eBUS definition based on community data. The initial code
candidate passed its full local suite, independent review and audit; this plan
opens the separate version, Home Assistant smoke, PR, merge, tag and publication
gates for v1.10.3. No public release date or promise is made until every gate
passes.

## Release scope

### Must

- Create `release/1.10.3` from the verified current `main`. Carry the reviewed
  feature diff and its tests/fixtures; do not include the pre-existing local
  change in `docs/issue-152-f34-analysis.md`.
- The initial plan-check preceded release-branch, metadata, and draft-PR
  creation. After any later scope or acceptance change, repeat plan-check before
  further implementation or release actions; do not stage, commit, push, deploy,
  or open/update a PR while the revised plan-check is pending.
- Do not edit HA entity/device registries or HA configuration, ebusd CSV files
  or `--configpath`, and do not write to eBUS registers.
- Preserve the runtime definition’s exact scan gate: passive `u` only for one
  discovered VWZIO `SW0500/HW0504` scan at slave address `0x76`. Preserve the
  complete current scan snapshot in `DeviceGraph`, including address-qualified
  `scan.xx` rows that map to no node and have incomplete metadata. Do not treat
  `no data stored`, arbitrary text, or rows without an address-qualified scan
  key as scan identities. An incomplete row at the target address invalidates
  address authority. An incomplete row of the same scan type at another address
  also makes that type's physical owner ambiguous; “unrelated” here means a
  different scan type at another address and must not suppress a unique target.
  Carry the uniquely mapped address through
  `ScanMetadata` and `DeviceNode`. Repeated identical scan rows at one address
  stay deterministic. A same-type scan at multiple addresses may retain identity
  metadata for classification, but its address ownership is ambiguous and must
  not authorize fixed-address reads; conflicting identities at one address are
  unmatched. Conflicts unrelated to the target scan/address must not suppress a
  uniquely identified VWZIO at `0x76`.
  `_merge_device_graphs()` must replace the prior scan snapshot with the latest
  one, even if the new graph has no VWZIO node, and clear prior station-address
  authorization when current evidence is missing or ambiguous. Authorization
  must depend only on this current scan snapshot, never a retained node.
  Every usable live poll `find` must refresh the coordinator graph's scan
  snapshot before runtime definitions or fallback reads, even when discovery is
  already ready. Dump-service fallback eligibility must be recomputed from the
  same raw `find` response used for that map probe, not the coordinator's stale
  graph or precomputed circuit aliases. Rebuild dump-side device metadata and
  aliases from that current find so hardware-specific blocklists and circuit
  routing reflect changed scan identities. Error-only/malformed find responses must not replace current graph
  evidence or proceed to active fallback reads. When a poll adds new runtime
  definitions, run a follow-up find in the same poll and refresh the graph from
  that usable response before fallback reads; if that response is unusable, skip
  active fallback reads for the poll and retain the last usable scan snapshot.
  During initial setup, apply the same rule to the post-definition find: merge a
  usable node-empty snapshot into the initial graph before entity/fallback
  processing. Initial runtime definitions already sent against the first usable
  graph are not retroactively suppressed; no fallback read may use that old
  owner after the follow-up conflict. If the follow-up find is unusable, retain
  topology only for presentation and skip active fallback reads.
  A same-firmware VWZIO at another address must not authorize B511/021802 to
  `0x76`.
- Gate generic VWZIO/VWZ `Status01` runtime definitions and coordinator/dump
  fallback reads against the physical station node actually mapped to slave
  `0x76`. In the reported counterexample (VWZ00 at `0x76`, target VWZIO at
  `0x77`), never issue the target VWZIO definition/read to `0x76`; explicitly
  assert no target `Status01` definition/read is sent to that address. Preserve
  definitions only when their resolved circuit owns a current scan at that
  address, including the supported HW5103-at-`0x76` path. Keep
  `fallback_read=False` for B511/021802 so rejected or absent passive
  definitions cannot trigger coordinator or dump-service active reads. HW5103
  metadata remains graph-driven only when ebusd actually discovers the
  register; PR #598 supplies separate HW5103 evidence.
- Add graph regressions for a unique VWZIO SW0500/HW0504 at `0x76`, the
  cross-address VWZ00@`0x76` + VWZIO@`0x77` topology, repeated identical same-
  address scan rows, conflicting identities/addresses, unrelated scan conflicts
  that must not suppress the valid VWZIO owner, partial conflicting scans at
  the target address that must block definitions and both fallback paths, and
  merges from valid
  `0x76` evidence to missing/ambiguous current evidence, including a new graph
  where the old VWZIO node is absent entirely. Assert coordinator and dump paths
  issue neither the target B511 definition/read nor the target Status01 read to
  `0x76`; preserve Status01 definition/read behavior for the supported HW5103
  station actually scanned at `0x76`. The positive HW5103 test must independently
  assert that both coordinator fallback and dump-service map-probe paths read
  Status01 on the correct physical owner at `0x76`. Explicitly test a complete
  VWZIO row at `scan.76` plus a partial VWZ00 row at that address: no station
  owner, no Status01 runtime definition, and no coordinator or dump Status01
  fallback read to `0x76`, both from direct graph creation and from a previously
  ready coordinator graph receiving the new usable live find. The dump test must
  pass a valid/stale coordinator graph with the current conflicting rows only in
  ebusd's find response and still issue no map probe to `0x76`. Also test that an
  unrelated partial scan elsewhere does not disable the valid owner. In dump
  tests, also switch a discovered HMUX0 from SW0303 to SW0407 and require the
  current SW0407 fallback blocklist to apply; switch CTLV2 to CTLV3 and require
  logical map aliases to route only to the currently discovered circuit. With an
  already-ready coordinator, test error-only/malformed first and follow-up finds:
  retain the last usable scan snapshot and issue no active fallback reads.
  For HMUX0, a stale SW0303 graph followed by incomplete current scan identity
  must not authorize a fallback read in the SW0407 blocklist. Apply the same
  current-identity decision to coordinator fallback and dump-service map probes.
  A fresh graph whose incomplete HMUX0 identity leaves the node without a
  `scan_type` must fail closed too; multiple HMUX0 scan addresses must not
  authorize a fixed-circuit probe. Preserve active fallback for a complete
  SW0303 scan and blocklist reads for a complete SW0407 scan.
  Add one initial-setup regression covering both post-definition outcomes: a
  usable, node-empty find with an incomplete same-address row must merge the
  latest snapshot and block Status01 fallback; an unusable follow-up must retain
  the last usable snapshot and skip active fallback. Verify initial definitions
  were generated only from the first complete, usable snapshot.
  Preserve the existing B511 positive frame decode/entity values and absent or
  `no data stored` path, including failed passive-definition behavior without an
  active read or fabricated entity.
- **Must — include PR #164's `Hc1SetbackMode` and `OffsetOutsideTemp` metadata.**
  The reporter supplied
  [a discovery dump](https://github.com/user-attachments/files/32965931/discovery_dump_2026-10-02_161025.yaml)
  from `Vaillant;CTLV0;SW0313;HW9103` at scan address `0x15`. It shows
  `ctlv0.Hc1SetbackMode = normal` and `ctlv0.OffsetOutsideTemp = -1.5` before
  the captured offset write and `-1` afterward. The integration's `writes`
  section records `OffsetOutsideTemp=-1.0` with `success: true`; its strict
  write path succeeds only after ebusd acknowledges and the read-back matches.
  The capture contains no write record for `Hc1SetbackMode`. The PR author states
  in PR #164 that this control was tested with the proposed mapping and behaves
  like `Hc1AutoOffMode`, using the `normal`/`comfort` terminology; the owner
  explicitly accepts that attestation for release inclusion. Record this as
  reporter-verified/owner-accepted evidence, not local live verification. Do
  not perform register writes. The BASV3 fixture and owner CTLV2 dump still do
  not expose these registers, so their entities remain discovery-driven and
  unavailable on hardware that does not report them.
- **Must — keep the reporter's full PR #164 dump as a community fixture.**
  Preserve every section and raw find row, add its attachment URL and original
  SHA-256 as provenance, include it in the fixture-load sweep, and add one
  focused regression that checks the discovered CTLV0 values, writable select
  `normal`/`comfort` options and offset range, plus the absent-register path. Do not add hardware
  writes to tests.
- Add the human-written `1.10.3` changelog section with heading `## 1.10.3`
  but no date while the candidate is under review. Then run
  `python3 tools/version.py bump 1.10.3` so the required heading exists, and
  finish with `python3 tools/version.py check`. Only after the candidate has
  passed HA smoke, PR-CI, independent review, audit and release gate, replace
  the heading with `## 1.10.3 - YYYY-MM-DD` using the actual publication date.
  Rerun validation, PR-CI, review, audit and release gate against this final
  dated diff before merge/tag. Do not communicate a date or promise before the
  final dated diff's gates pass.
- Retain the four complete #161 HW0504 discovery dumps byte-for-byte, plus the
  explicitly identified PR #598 evidence excerpt. Do not trim raw find/grab
  sections or present the PR excerpt as a complete discovery dump.
- Run the complete CI-equivalent validation from `.github/workflows/ci.yml` and
  `AGENTS.md`: Ruff, format check, strict configured mypy, YAML parsing, full
  pytest, version consistency, compileall, and diff check.
- Deploy only through `scripts/deploy.sh --restart` after local validation.
  Commit and record the candidate SHA first. Because this script packages the
  current working tree, verify the deployed component files match that commit
  and that no code changes occur after smoke; any deployed-file change requires
  a repeat deploy and smoke. Through HA-MCP, confirm the integration is loaded;
  export one zero-duration dump, then one one-second dump. Run no other export
  for the same ebusd endpoint during either call, including from another HA
  instance. Parse both files and require `metadata`, `raw_find_lines`,
  `before_registers`, and `registers`. Check metadata: zero
  duration must report `grab_status: not_requested` and
  `grab_captured_duration: 0`; the positive capture must report a positive
  captured duration and limitation, plus `grab_status: continued`,
  `grab_capture_method: count_delta` and `grab_capture_limitation` on the
  current ebusd version (or the documented older owned `captured` variant).
  Continued capture retains only the latest payload per message key, sums counts
  for identical visible rows, and cannot detect an external grab stop/restart
  followed by a count refill; do not claim that it preserves every state
  transition. After the positive-duration
  export, verify `grab result all` is not `grab disabled`; do not start/stop grab
  or restart ebusd during the test. Check fresh HA logs. Use the file-read tool
  through HA-MCP when available; use the documented read-only SSH path only
  when HA-MCP cannot expose the required file or command.
- State the hardware limit in release and issue text: the owner’s HA system is
  not the reporter’s `VWZIO SW0500/HW0504`, so its smoke covers service and
  unavailable-data safety, not positive live reads of the counters.
- Stage only this explicit allowlist: `CHANGELOG.md`, `pyproject.toml`,
  `custom_components/vaillant_ebus/manifest.json`,
  `custom_components/vaillant_ebus/backend/models.py`,
  `custom_components/vaillant_ebus/backend/discovery_service.py`,
  `custom_components/vaillant_ebus/backend/mapping.py`,
  `custom_components/vaillant_ebus/coordinator.py`,
  `custom_components/vaillant_ebus/dump_service.py`,
  `docs/plan-1.10.3.md`,
  `docs/plan-issue-follow-up-152-161-165.md`,
  `tests/fake_ebusd.py`, `tests/fixtures/community/dumpvalues.yaml`,
  `tests/fixtures/community/hmux0_issue161_2026-09-30_130640_discovery.yaml`,
  `tests/fixtures/community/hmux0_issue161_2026-09-30_132044_discovery.yaml`,
  `tests/fixtures/community/hmux0_issue161_2026-09-30_154054_discovery.yaml`,
  `tests/fixtures/community/hmux0_issue161_2026-09-30_161313_discovery.yaml`,
  `tests/fixtures/community/ctlv0_pr164_2026-10-02_161025_discovery.yaml`,
  `tests/fixtures/community/vwzio_hw5103_pr598_b511_stats.yaml`,
  `tests/test_community_issue_fixtures.py`, `tests/test_fake_ebusd.py`,
  `tests/test_coordinator.py`,
  `tests/test_discovery_service.py`,
  `tests/test_fixture_integrity.py`, and `tests/test_hardening_fixes.py`.
  Before each release commit, inspect `git diff --cached --name-only` and the
  staged diff; reject any path outside this list.
- Run full repository validation, deploy and smoke-test the committed candidate,
  then run independent standard-tier final review followed by final audit on
  that exact candidate. Only after both pass, push the release branch and update
  draft PR #168. Wait for PR-CI to pass, then run an independent release-gate
  decision that consumes PR-CI and HA-smoke evidence for the exact PR diff.
  Merge only after all gates pass. Wait for main-CI on the merge commit
  before creating and pushing annotated `v1.10.3`. Verify the tag workflow, zip
  version and published asset.
- After publication, update issues #152, #161 and #165 in English with only the
  change relevant to each issue. Keep #152 and #161 open for the user's
  requested evidence. Close #165 at the owner's explicit request, with a clear
  note that BASS3 calendars remain unavailable and can be revisited if valid
  layout evidence arrives. Close PR #164 only after its evidence-backed changes
  are included and merged; PR #168 closes through merge.

### Should

- Record both dump paths, YAML checks, `grab result all` result, HA entry state
  and fresh logs in this plan after the owner-server smoke test.
- Record the release workflow run, merged commit, annotated tag target, release
  URL, zip manifest version and SHA-256 after publication.

### Could — deferred with revisit trigger

- Add no F34 energy mapping/default changes until the reporter provides the
  requested entity IDs, state, unit, enabled status and source register.
- Make no #161 recovery change unless the reporter reproduces the 500 on
  v1.10.2 or later and provides fresh logs from after ebusd reconnects.
- Make no BASS3 timer/calendar change until a decodable capture or matching
  upstream BASS3/HW4304 field-layout evidence exists.
- Do not add B511/021801 heating counters, VWZIO B516/0x49 energy meaning, or
  HMUX0 counter semantics; those still lack matching state-correlated evidence.

## Plan-check questions

1. Does the graph retain the exact physical scan address, and does merge clear
   prior address authorization on missing or ambiguous current scan evidence?
2. Does a scan at `0x77` prevent the HW0504 B511 definition, generic B511
   Status01 definitions, and fallbacks from targeting a different slave at
   `0x76`, while preserving the supported HW5103 scan at `0x76`?
3. Are repeated same-address scans deterministic and same-type/multi-address or
   same-address/conflicting identities ambiguous, including after graph merges
   where the latest scan snapshot no longer has a VWZIO node?
4. Are version files and changelog synchronized without exposing an unapproved
   release date or promising publication before the gates pass?
5. Does the deployment/smoke sequence use the required script and HA-MCP paths,
   deploy the exact committed candidate, serialize exports per endpoint, check
   required metadata, avoid registry/config changes and register writes, and
   preserve ebusd’s shared auto-grab state?
6. Does the release describe PR #164 evidence accurately: OffsetOutsideTemp's
   captured write/read-back, Hc1SetbackMode's reporter attestation accepted by
   the owner, and no local live verification or extra eBUS write?
7. Do the release issue replies distinguish what v1.10.3 changes from the
   unresolved #152, #161 recovery and #165 behavior?
8. Are review, audit, release-gate, PR CI, merge, tag and artifact checks ordered
   against the exact candidate, with no user-owned file staged?

## Release gates

| Gate | Status | Evidence |
|---|---|---|
| Initial state | PASS | `main` equals `origin/main` at `48af49b`; `v1.10.2` is published; remote `release/1.10.3` backs draft PR #168; no release tag/publication exists |
| Plan revision | APPROVED | After independent review and audit found fresh-graph and dump-service HMUX0 fallback bypasses on candidate `94f23f3`, Mark approved correcting both before release. This is a fail-closed routing fix; it adds no register semantics or hardware support. |
| Plan-check | PASS | Independent recheck accepted retained and fresh incomplete HMUX0 graphs in coordinator and dump-service fallback paths, multiple scan addresses, and preservation of complete SW0303/SW0407 behavior. |
| Candidate/version | COMPLETE | Release branch `release/1.10.3`; `pyproject.toml`, manifest and undated `CHANGELOG.md` heading are synchronized at `1.10.3` |
| Implementation | PASS | Shared HMUX0 fallback authorization now blocks confirmed SW0407 and incomplete/ambiguous current scan identity in coordinator polling and dump-service map probes. Fresh incomplete graphs and multiple HMUX0 addresses fail closed; confirmed SW0303 fallback remains active. |
| Validation | FOCUSED PASS | Focused coordinator and dump-service HMUX0 regressions, adjacent SW0302/SW0303 and firmware-gate tests, Ruff, format check, and diff check pass. Run the full CI-equivalent suite after delta review/audit. |
| HA baseline | PASS | HA-MCP: Core 2026.9.4 running; `vaillant_ebus` entry loaded. One unrelated Govee restart-required repair and one generic loader warning were present; no `custom_components.vaillant_ebus` runtime error was found. |
| HA smoke | STALE AFTER CODE DELTA | The previous scope-limited smoke passed on `345dba2`; repeat deploy and both exports after the approved correction. The owner's VWZ00 SW0522/HW5103 hardware cannot prove positive HW0504 B511 reads. |
| Review | PENDING DELTA REVIEW | Independent review found a P1 fresh-graph bypass on `94f23f3`; run delta review against the corrected candidate. |
| Audit | PENDING DELTA AUDIT | Independent audit found a P1 dump-service map-probe bypass on `94f23f3`; run delta audit against the corrected candidate. |
| Release gate | BLOCKED | Complete the revised plan-check and safety correction, then rerun validation, HA smoke, independent review/audit, PR-CI and release gate before merge/tag/publication. |
| PR / merge | BLOCKED | The corrected HMUX0 candidate is local and unpushed; draft PR #168 remains at remote head `d6612ae`. Push after validation, fresh smoke, delta review and audit, then wait for PR-CI and release gate. |
| Tag / artifact | NOT STARTED | Annotated tag after merge; verify published zip and workflow |
| User communication | IN PROGRESS | PR #164 dump arrived and is assessed; post the precise evidence summary after publication, close #165 only then, and leave #152/#161 open |

## Review/audit cost

Plan a standard-tier independent review and a separate standard-tier audit, up
to five minutes each. The production delta is localized and hardware-gated; if a
pass finds cross-circuit, alias or fallback behavior outside that scope, stop
and escalate rather than broadening the release silently. Run a separate
standard-tier release gate after validation, HA smoke, review, audit and PR CI.
