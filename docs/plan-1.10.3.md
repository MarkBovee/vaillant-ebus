# Release 1.10.3 Plan

Status: **PRE-MERGE CANDIDATE — local validation and HA smoke passed; PR/release gates pending**

Planning date: 2026-10-02

Base: `main` / `origin/main` at `48af49b`

Previous release: `v1.10.2` at `44f11a9083cd83da04139b690f0d117d96bc23b6`
Implementation branch: `release/1.10.3`

## Goal

Release the evidence-backed VWZIO DHW backup-heater runtime/start counters for
the reporter’s `SW0500/HW0504` scan. Preserve the v1.10.2 dump-export behavior
and discovery-readiness guard. Do not claim that the separate post-ebusd-crash
HTTP 500 is fixed, and do not restore the BASS3 calendars.

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
- Preserve the runtime definition’s exact scan gate: passive `u` only on the
  discovered VWZIO `SW0500/HW0504` circuit. Keep `fallback_read=False` on the
  mapping so a rejected definition cannot trigger a coordinator or dump-service
  active read. The HW5103 metadata remains graph-driven only for a register that
  ebusd actually discovers; PR #598 supplies separate HW5103 evidence.
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
  `custom_components/vaillant_ebus/backend/mapping.py`,
  `custom_components/vaillant_ebus/coordinator.py`,
  `docs/plan-1.10.3.md`,
  `docs/plan-issue-follow-up-152-161-165.md`,
  `tests/fake_ebusd.py`, `tests/fixtures/community/dumpvalues.yaml`,
  `tests/fixtures/community/hmux0_issue161_2026-09-30_130640_discovery.yaml`,
  `tests/fixtures/community/hmux0_issue161_2026-09-30_132044_discovery.yaml`,
  `tests/fixtures/community/hmux0_issue161_2026-09-30_154054_discovery.yaml`,
  `tests/fixtures/community/hmux0_issue161_2026-09-30_161313_discovery.yaml`,
  `tests/fixtures/community/vwzio_hw5103_pr598_b511_stats.yaml`,
  `tests/test_community_issue_fixtures.py`, `tests/test_coordinator.py`,
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
  change relevant to each issue. Keep all three open. Explain explicitly that
  #152 F34 mappings and #165 BASS3 calendars are unchanged; #161’s separate
  crash-recovery HTTP 500 remains unverified.

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

1. Does the included feature diff contain only the intended HW0504 passive
   counter mapping plus its evidence-backed metadata, tests and fixtures?
2. Are version files and changelog synchronized without exposing an unapproved
   release date or promising publication before the gates pass?
3. Does the deployment/smoke sequence use the required script and HA-MCP paths,
   deploy the exact committed candidate, serialize exports per endpoint, check
   required metadata, avoid registry/config changes and register writes, and
   preserve ebusd’s shared auto-grab state?
4. Do the release issue replies distinguish what v1.10.3 changes from the
   unresolved #152, #161 recovery and #165 behavior?
5. Are review, audit, release-gate, PR CI, merge, tag and artifact checks ordered
   against the exact candidate, with no user-owned file staged?

## Release gates

| Gate | Status | Evidence |
|---|---|---|
| Initial state | PASS | `main` equals `origin/main` at `48af49b`; `v1.10.2` is published; no remote `release/1.10.3`, tag or release exists |
| Plan-check | PASS | Independent plan-check accepted version order, stage allowlist, deployment identity, HA smoke evidence, CI/gate order, and auto-grab limitations |
| Candidate/version | COMPLETE | Release branch `release/1.10.3`; `pyproject.toml`, manifest and undated `CHANGELOG.md` heading are synchronized at `1.10.3` |
| Validation | PASS | Ruff check/format, strict configured mypy, YAML parsing, 943 pytest tests, version check, compileall and diff check passed; `scripts/deploy.sh --restart` repeated ruff/pytest/compile successfully |
| HA baseline | PASS | HA-MCP: Core 2026.9.4 running; `vaillant_ebus` entry loaded. One unrelated Govee restart-required repair and one generic loader warning were present; no `custom_components.vaillant_ebus` runtime error was found. |
| HA smoke | PASS | Deployed commit `77c696b` with `scripts/deploy.sh --restart` (HTTP 200). HA-MCP confirmed the entry loaded. Zero dump `/config/vaillant_ebus/discovery_dump_2026-10-02_135017.yaml`: YAML valid, required sections, 631 raw find lines, 728 before-registers, `not_requested`, captured duration `0`. Positive dump `/config/vaillant_ebus/discovery_dump_2026-10-02_135110.yaml`: YAML valid, required sections, 631 raw find lines, 728 before-registers, `continued`, `count_delta`, 1.000969 s, limitation present, 4 grab lines. Read-only `grab result all` returned 8,633 lines, not `grab disabled`; fresh filtered logs had zero entries. Owner scan is VWZ00 SW0522/HW5103, so this verifies export and unavailable-data safety, not positive HW0504 B511 reads. HA-MCP had no file reader; read-only SSH fetched both files. |
| Review | NOT STARTED | Independent standard-tier review after validation and HA smoke |
| Audit | NOT STARTED | Separate independent standard-tier audit after review |
| Release gate | NOT STARTED | Independent decision against exact final diff and all evidence |
| PR / merge | IN PROGRESS | Draft PR #168 is open at `https://github.com/MarkBovee/vaillant-ebus/pull/168`; PR-CI and independent gates are still pending |
| Tag / artifact | NOT STARTED | Annotated tag after merge; verify published zip and workflow |
| User communication | NOT STARTED | English issue updates only after publication |

## Review/audit cost

Plan a standard-tier independent review and a separate standard-tier audit, up
to five minutes each. The production delta is localized and hardware-gated; if a
pass finds cross-circuit, alias or fallback behavior outside that scope, stop
and escalate rather than broadening the release silently. Run a separate
standard-tier release gate after validation, HA smoke, review, audit and PR CI.
