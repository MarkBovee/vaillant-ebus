# Release 1.10.3 Plan

Status: **BLOCKED — PR #164 write evidence is outstanding; final validation, HA smoke and release gates remain**

Planning date: 2026-10-02

Base: `main` / `origin/main` at `48af49b`

Previous release: `v1.10.2` at `44f11a9083cd83da04139b690f0d117d96bc23b6`
Implementation branch: `release/1.10.3`

## Goal

Release the evidence-backed VWZIO DHW backup-heater runtime/start counters for
the reporter’s `SW0500/HW0504` scan and the owner-requested PR #164 metadata
only after its hardware and write/read-back evidence is available. Preserve the
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
- Do not create the release branch, edit release metadata, stage, commit, push,
  deploy, or open a PR before the independent plan-check passes.
- Do not edit HA entity/device registries or HA configuration, ebusd CSV files
  or `--configpath`, and do not write to eBUS registers.
- Preserve the runtime definition’s exact scan gate: passive `u` only for one
  discovered VWZIO `SW0500/HW0504` scan at slave address `0x76`. Preserve the
  complete current scan snapshot in `DeviceGraph`, including address-qualified
  scan rows that map to no node, and carry the uniquely mapped address through
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
  that must not suppress the valid VWZIO owner, and merges from valid
  `0x76` evidence to missing/ambiguous current evidence, including a new graph
  where the old VWZIO node is absent entirely. Assert coordinator and dump paths
  issue neither the target B511 definition/read nor the target Status01 read to
  `0x76`; preserve Status01 definition/read behavior for the supported HW5103
  station actually scanned at `0x76`. The positive HW5103 test must independently
  assert that both coordinator fallback and dump-service map-probe paths read
  Status01 on the correct physical owner at `0x76`.
- **Must — PR #164 is evidence-gated.** Its diff adds writable `Hc1SetbackMode`
  and `OffsetOutsideTemp` mappings. The open PR has no capture or test results;
  the available BASV3 capture returns `no data stored` for both registers, and
  the owner's CTLV2 SW0514/HW1104 dump contains neither. Evidence was requested
  on PR #164 in comment
  https://github.com/MarkBovee/vaillant-ebus/pull/164#issuecomment-5952466752:
  complete dump/scan identity and current values, plus the prior tests' `done`
  write responses and read-back values for both controls. A read-only dump alone
  does not clear the writable-mapping gate. Do not include/merge those writable
  mappings or publish v1.10.3 until both read and write/read-back evidence is
  available and supports the entries. If it is absent or contradicts the PR,
  stop and ask the owner before changing release scope. Do not run register
  writes without separate explicit authorization and read-back proof.
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
  `tests/fixtures/community/vwzio_hw5103_pr598_b511_stats.yaml`,
  `tests/test_community_issue_fixtures.py`, `tests/test_coordinator.py`,
  `tests/test_discovery_service.py`,
  `tests/test_fixture_integrity.py`, and `tests/test_hardening_fixes.py`.
  Before each release commit, inspect `git diff --cached --name-only` and the
  staged diff; reject any path outside this list.
- Deploy and smoke-test the validated release branch before publication. Then
  push the release branch and open its PR. Wait for PR-CI to pass, then run
  independent standard-tier review and audit followed by an independent
  release-gate decision that consumes PR-CI and HA-smoke evidence for the exact
  PR diff. Merge only after all gates pass. Wait for main-CI on the merge commit
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
6. Does PR #164 remain blocked on dump and write/read-back evidence without
   introducing unwarranted live writes?
7. Do the release issue replies distinguish what v1.10.3 changes from the
   unresolved #152, #161 recovery and #165 behavior?
8. Are review, audit, release-gate, PR CI, merge, tag and artifact checks ordered
   against the exact candidate, with no user-owned file staged?

## Release gates

| Gate | Status | Evidence |
|---|---|---|
| Initial state | PASS | `main` equals `origin/main` at `48af49b`; `v1.10.2` is published; remote `release/1.10.3` backs draft PR #168; no release tag/publication exists |
| Plan-check | PASS | Independent plan-check accepted complete scan-snapshot semantics, merge invalidation, coordinator/dump fallback tests, the PR #164 evidence gate, exact allowlist and issue closure boundaries. |
| Candidate/version | COMPLETE | Release branch `release/1.10.3`; `pyproject.toml`, manifest and undated `CHANGELOG.md` heading are synchronized at `1.10.3` |
| Validation | PASS | Final candidate: 951 pytest tests passed; Ruff check and configured format check passed; configured strict mypy passed; compileall, version check, and diff check passed. The deploy script repeated Ruff/pytest/compileall successfully. One pre-existing deprecation warning remains in `test_legacy_resolve_circuit_keeps_string_contract_without_ownership_authority`. |
| HA baseline | PASS | HA-MCP: Core 2026.9.4 running; `vaillant_ebus` entry loaded. One unrelated Govee restart-required repair and one generic loader warning were present; no `custom_components.vaillant_ebus` runtime error was found. |
| HA smoke | PASS (scope-limited) | Deployed the committed address-safe component with `scripts/deploy.sh --restart` (HA returned HTTP 200); HA-MCP confirmed `vaillant_ebus` loaded. Zero dump `/config/vaillant_ebus/discovery_dump_2026-10-02_152145.yaml`: valid YAML and required sections, 631 raw find rows, 728 before-registers, `grab_status: not_requested`, captured duration 0. Positive dump `/config/vaillant_ebus/discovery_dump_2026-10-02_152205.yaml`: valid YAML and required sections, 631 raw find rows, 728 before-registers, `continued`/`count_delta`, 1.00098856 s, capture limitation present, 5 grab rows. Read-only `grab result all` returned data, not `grab disabled`; filtered post-restart HA error logs had zero `custom_components.vaillant_ebus` errors. Both dumps show the owner's `VWZ00 SW0522/HW5103`, not the reporter's VWZIO SW0500/HW0504, so this smoke does not verify positive HW0504 B511 values. Files were fetched using read-only SSH because HA-MCP exposed no file reader. |
| Review | PENDING FINAL | Independent review of the complete post-smoke release candidate is required; earlier review and delta review are historical. |
| Audit | PENDING FINAL | Independent production-path audit of the complete post-smoke candidate is required; earlier audit and delta audit are historical. |
| Release gate | BLOCKED | Address-safety audit finding is closed by `c2d7a5b`; publication remains blocked until PR #164 evidence supports the writable mappings and all final validation/release gates pass |
| PR / merge | BLOCKED | Draft PR #168 is still at remote head `d6612ae`; local address-safe commits are not pushed yet. Push only after final review/audit; wait for PR-CI and all independent gates. Do not merge before PR #164 evidence decision. |
| Tag / artifact | NOT STARTED | Annotated tag after merge; verify published zip and workflow |
| User communication | IN PROGRESS | Posted an English evidence request on PR #164; release issue notices and #165 closure wait until publication |

## Review/audit cost

Plan a standard-tier independent review and a separate standard-tier audit, up
to five minutes each. The production delta is localized and hardware-gated; if a
pass finds cross-circuit, alias or fallback behavior outside that scope, stop
and escalate rather than broadening the release silently. Run a separate
standard-tier release gate after validation, HA smoke, review, audit and PR CI.
