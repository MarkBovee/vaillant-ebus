# Release 1.9.5 — New Community Data

Status: **RELEASE CANDIDATE READY — NOT PUBLISHED**
Date: 2026-09-23
Base: `v1.9.4` (`2ff45ff`)

## Risk class

Release-sensitive, compatibility-sensitive protocol work. The release combines
new community-derived register mappings, runtime definitions, fixture changes,
and agent-tool changes. All protocol additions must remain hardware-gated,
absent-safe, and compatible with the discovery graph.

## Goal

Ship the evidence-backed part of the new #32/#111/#152 research in `v1.9.5`,
without presenting discovery-only candidates or unverified writes as supported
features.

## Scope decision

“All research” means all candidates classified as `confirmed` or `strong
assumption` **where the implementation can preserve safe bus behavior and
absent-register handling**. It does not mean implementing every name in the
MQTT comparison.

The per-register implementation boundary is in
[`plan-1.9.5-candidate-matrix.md`](plan-1.9.5-candidate-matrix.md). The
matrix is authoritative when a broad research classification and a release
safety gate differ.

## Must

### Release foundation

- Bump the release consistently to `1.9.5` with `tools/version.py`.
- Add a matching top `CHANGELOG.md` section with hardware scope and deferred
  candidates stated plainly.
- Keep the release branch and final tag aligned with the repository release
  process.
- Include the research-backed fixture and regression tests in the release diff.
- Preserve the `search_upstream.sh` cache, refresh, retry, and focused tests for
  agent research.

### Discussion #32 fixture and graph coverage

- Add the complete v4 dump as a community fixture without trimming raw find,
  grab, unknown, labeled, or before/after sections.
- Add fixture-integrity and fixture-loading coverage.
- Protect `metadata`, `raw_find_lines`, `raw_find_lines_after`, `grab`,
  `unknown_telegrams`, `labeled_telegrams`, `before_registers`, and
  `after_registers`, including the 68 unknown-candidate count and the three
  scan identities.
- Assert scan identities and owner circuits:
  - HMUX0 `SW0302/HW0504` on `08`;
  - CTLV3 `SW0808/HW8004` on `15`;
  - VWZIO `SW0302/HW0504` on `76`.
- Assert absent-register behavior for every candidate that returns `ERR`,
  `no data stored`, or invalid-position data.

### HMUX0 B509 operational telemetry

- Implement the exact upstream-correlated B509 candidates observed on the
  target bus: `5402005b0d` (`RunDataElPowerConsumption`), `5402000d0a`
  (`RunDataCompressorSpeed`), and `540200c509` (`RunDataBuildingCPumpPower`).
- Add only the individual B509 runtime/start/pump/fan candidates listed as
  conditional `must`/`should` rows in the candidate matrix. Candidates without
  an exact name, layout, scale, and upstream source remain out of the release.
- Gate definitions by the discovered HMUX0 scan identity and resolve the actual
  discovered circuit, never by adding another literal `hmu` fallback.
- Decide explicitly whether each definition is update-only/passive or an active
  read. An observed telegram from another master is not proof that an `r`
  definition is passive.
- For every active candidate, record the expected read cadence, test fallback
  reads against the fake ebusd path, and document why the read is safe. If the
  cadence or bus impact cannot be established, defer the candidate instead of
  silently using `r`.
- The three shipped B509 candidates use the established B509 monitoring block.
  Upstream describes this block as intended for regular monitoring, and the
  integration already uses active B509 reads for the existing SW0303 path. The
  release keeps that behavior hardware-gated and validates the resolved
  `hmux0` socket path; owner-hardware live verification remains a documented
  residual limitation.
- Test positive decode, absent/ERR behavior, and no stale cache resurrection.

### HMUX0 B51A energy/current candidates

- Consider the researched `YieldHc`, `YieldHcDay`, `YieldHcMonth`, `YieldHwc`,
  `YieldHwcDay`, `YieldHwcMonth`, and current power candidates only if the
  implementation can prove safe polling behavior for the target hardware.
- Keep the existing `SW0303/HW0504` behavior unchanged while evaluating the
  `SW0302/HW0504` extension.
- Add exact scan gates, fixture-backed values where present, and safe absent
  paths. Do not alias B51A values to B509 or B516 names.

### CTLV3 candidates

- Evaluate `Hc1RoomTempModulation` and `HwcLegionellaDay/Time` using the exact
  B524 addresses and upstream field types.
- Keep parsed fields separate from parent registers.
- Do not add a write path without satisfying the project's direct-write and
  read-back safety gate; if owner-hardware testing is unavailable, ship only a
  safe read/passive part or defer the write explicitly.

## Should

- Evaluate the exact observed B509 `RunStats*` subset, but keep the counters
  deferred unless the matrix's runtime-datatype and decode gates pass.
- Add a fixture-backed evidence table link from the research report to the
  release changelog/implementation notes.
- Add a focused test proving HMUX0 `SW0302` does not receive definitions that
  belong only to `SW0303` or HW5103.
- Use the complete #32 fixture, not only a synthetic graph, to prove that
  address `08` resolves to the discovered `hmux0` owner, definitions land on
  `hmux0`, fallback reads use the same owner, and no stale `hmu` alias is
  resurrected.
- Add resolved-circuit tests for every multi-field parent used by new entities;
  parsed fields must be generated under the discovered circuit name.
- Verify the v1.9.4 F34 behavior remains intact; do not change #152 based only
  on the remaining post-purge unknowns.

## Could, with explicit trigger

- VWZIO immersion-heater metrics (`B51A 05ff3246/3249/324a/324c`) for the exact
  #32 `HW0504` target. **Deferred:** strongest upstream evidence is HW5103, not
  HW0504. Trigger: a target-HW0504 dump containing matching telegrams and a
  safe layout.
- BAI00 `FlowTempDesired` write support. **Deferred:** SW0107 has strong
  negative evidence for the tested path and SW0108 has no positive write
  evidence. Trigger: byte-for-byte write capture plus forced read-back/state
  transition on the target firmware.
- #152 remaining Electrical/Environment/Solar entities. **Deferred:** current
  post-purge registry state is unknown. Trigger: a v1.9.4+ dump or registry
  report after the user performs the purge.

## Explicitly out of scope

- Generic MQTT-name-to-register mappings without exact protocol evidence.
- Hardware-agnostic B51A or VWZIO definitions.
- `SetModeOverride` or `FlowTempDesired` write claims for BAI00 SW0107/SW0108.
- ebusd CSV edits, `--configpath`, remote registry edits, or live writes by the
  agent.
- Release tagging or publishing before the independent review, audit, and
  release gate pass.

## Implementation stages

1. **Plan-check — deep**
   - Reconcile the candidate matrix with exact inventory and current runtime
     defines.
   - Decide per-register active versus update-only behavior; unresolved rows are
     deferred, not implicitly made active.
   - Verify circuit ownership, scan gates, field layouts, units, and sentinels.

2. **Fixture and model — standard**
   - Add the complete #32 fixture and integrity/load tests.
   - Add RED tests for scan gates, candidate decoding, absent paths, and owner
     resolution.
   - Add a complete-dump integrity test covering all preserved sections, the 68
     unknown candidates, scan metadata, and raw/after register counts.

3. **Runtime definitions and metadata — deep**
   - Implement only candidates that pass the plan-check safety gates.
   - Keep definitions in the central data-driven paths.
   - Add entity metadata and conservative defaults.
   - Preserve the existing `SetModeOverride` compatibility path unchanged;
     this release adds no new BAI write.

4. **Validation — standard**
   - Run focused tests, the complete test suite, Ruff, compileall, and version
     checks from `AGENTS.md`.

5. **Review and independent audit — standard**
   - Review the final diff for requirements, compatibility, active polling,
     ownership, absent paths, and fixture provenance.
   - Re-audit the final diff from an independent context.

6. **Release gate — standard**
   - Confirm version/changelog/tag scope, clean intended tree, validation,
     review, audit, and unresolved deferred items.
   - Only then prepare the release branch, PR, merge, annotated tag, and GitHub
     release according to the repository process.

## Validation commands

```text
.venv/bin/ruff check .
.venv/bin/ruff format --check custom_components/vaillant_ebus/backend/grab_parser.py custom_components/vaillant_ebus/backend/dump_analysis.py custom_components/vaillant_ebus/backend/discovery_service.py custom_components/vaillant_ebus/backend/models.py custom_components/vaillant_ebus/backend/ebus_service.py custom_components/vaillant_ebus/backend/entity_factory.py custom_components/vaillant_ebus/backend/mapping.py custom_components/vaillant_ebus/coordinator.py custom_components/vaillant_ebus/dump_service.py
.venv/bin/pytest -q
python3 tools/version.py check
python3 -m compileall -f custom_components/vaillant_ebus/
bash -n tools/search_upstream.sh
.venv/bin/pytest -q tests/test_search_upstream.py
```

## Release gate

- No candidate is shipped above its research classification.
- Every shipped register has exact circuit/address/message/sub-address/layout
  evidence, a hardware gate, and a safe absent path.
- No write path ships without the direct-write/read-back evidence required by
  the project rules.
- Complete #32 fixture is preserved and tested.
- `1.9.5` matches `pyproject.toml`, `manifest.json`, and `CHANGELOG.md`.
- Full validation, code review, independent audit, and release-gate checks pass.
- Deferred candidates and their revisit triggers are documented in the release
  notes.

## Plan-check revision

The first independent plan-check blocked execution. This revision addresses its
findings by:

- making the candidate matrix authoritative per register, including exact
  layout evidence, hardware gate, polling mode, and must/should/could/out
  decision;
- deferring every active candidate whose cadence or bus impact is not proven,
  rather than treating an observed frame as passive;
- requiring a positive HMUX0 `SW0302/HW0504` scan gate alongside preservation of
  existing `SW0303/HW0504` behavior;
- requiring full-dump integrity checks, complete-fixture owner resolution, and
  resolved-circuit multi-field tests;
- stating that existing `SetModeOverride` remains unchanged compatibility
  behavior and that no new BAI write ships in this release.

The plan-check is complete for the three B509 EXP candidates. The fixture,
runtime definitions, positive/absent tests, fake-ebusd reads, version bump, and
changelog are implemented. Full validation is complete: 695 tests passed with
one existing deprecation warning, Ruff and format checks passed, compileall
passed, and independent review/audit passed. The candidate is ready for a
release PR/tag gate but has not been published; deferred matrix rows remain out
of the production diff.
