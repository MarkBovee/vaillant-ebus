# RC3 Test Suite Rationalization & Fixture Integrity Audit

Scope: `vaillant-ebus` 1.8.0 RC3. This document records the audit of the test
suite and its fixtures, the fixture trust model, the issues found, and the
changes made. It is the reference for the RC3 quality gate.

## 1. Summary

RC2 fixed a real DHW regression where runtime-defined registers left a spurious
bare `ctlv2` node on an HMUX0/CTLV3 bus, so logical `ctlv2` resolved to the
wrong circuit and the water heater reported `unknown`. RC2 already replaced the
stripped issue #99 fixtures with the full captures.

RC3 verified that fix, audited the whole suite, established a fixture trust
model, added a permanent fixture-integrity guard, and gave every retained test
an explicit `Intent:` and `Why:` description.

Key results:

- 487 test functions (532 parametrized cases) across 21 files, all described.
- The `ctlv2` pollution regression is covered by golden fixtures and proven to
  fail against the pre-fix implementation.
- A new `tests/test_fixture_integrity.py` fails if the golden captures lose the
  spurious `ctlv2` records or another discovery dump loses provenance.
- Three tautological assertions were fixed and two exact duplicate tests were
  removed. No coverage was dropped.

## 2. Fixture trust model

Every fixture is evidence, not truth. A fixture that is technically valid but
missing the records needed to trigger a bug is not a valid regression fixture.

| Trust | Meaning | Use |
| --- | --- | --- |
| GOLDEN | Complete, faithfully preserved real-world dump (metadata + full find lines). | Compatibility and regression contracts. |
| REDUCED-FAITHFUL | Reduced from a real capture, proven to preserve the relevant behavior. | Only for validated reductions. |
| SYNTHETIC | Artificially constructed input. | Focused unit and boundary tests. |
| LEGACY/UNKNOWN | Provenance or completeness uncertain. | Fixture input only; never sole real-world compatibility evidence. |

Policy for full dump vs reduced fixture:

- Use a full dump when discovery, circuit ownership, graph resolution, register
  ownership, runtime-defined registers, aliases/redefinitions, multi-circuit
  coexistence, or an unexpected-register regression is under test.
- A reduced fixture is acceptable only for a pure parser, one isolated
  transformation, or a deterministic algorithm with explicitly controlled
  input, and only when the omitted data is proven irrelevant.
- Never strip a fixture merely to shrink the repository when it changes the
  semantics of the test input.
- A minimal reproducer is valid only if it preserves every input condition
  required to reproduce the bug. If removing data makes the bug disappear, the
  reduction is invalid.

## 3. Fixture inventory

Provenance is taken from `docs/community-dump-plan.md`, fixture metadata, and the
issue references in the tests. Where it is not documented it is marked unknown
rather than invented.

| Fixture | Type | Provenance | Complete? | Purpose | Tests | Trust |
| --- | --- | --- | --- | --- | --- | --- |
| `hmux0_issue99_2026-09-10_170850.yaml` | discovery dump | issue #99 | yes (780 lines, v4) | ctlv2 pollution + ctlv3 DHW routing regression | `test_fixture_integrity`, `test_boost_switch`, `test_community_issue_fixtures` | GOLDEN |
| `hmux0_issue99_2026-09-10_173229.yaml` | discovery dump | issue #99 | yes (589 lines, v4) | same, without symlink | same | GOLDEN |
| `arotherm_hmux0_dhw_holiday_discovery.yaml` | discovery dump | issue #99 | yes (780 lines) | HMUX0 DHW/holiday values + sentinels | `test_community_issue_fixtures` | GOLDEN |
| `arotherm_pro7_quiet_off_idle_discovery.yaml` | discovery dump | issue #101 | yes (504 lines) | quiet registers absent | `test_community_issue_fixtures` | GOLDEN |
| `arotherm_pro7_quiet_off_heating_discovery.yaml` | discovery dump | issue #101 | yes | quiet registers absent | `test_community_issue_fixtures` | GOLDEN |
| `arotherm_pro7_quiet_on_heating_discovery.yaml` | discovery dump | issue #101 | yes | quiet registers absent | `test_community_issue_fixtures` | GOLDEN |
| `ecotec_vrt380_15700_discovery.yaml` | discovery dump | discussion #33 | yes (818 lines) | ecoTEC/VRT380 BAI + controller graph | `test_community_issue_fixtures` | GOLDEN |
| `ecotec_vrt380_ctlv2_discovery.yaml` | discovery dump | discussion #33 | before set complete (795); `raw_find_lines_after` empty | ecoTEC/VRT380 ctlv2 variant | `test_community_issue_fixtures` | GOLDEN (before set) |
| `arotherm_plus_2zone_discovery.yaml` | discovery dump | community (issue unknown) | yes (552 lines) | two-zone topology | `test_discovery_service` | GOLDEN |
| `arotherm_plus_basv3_discovery.yaml` | discovery dump | community (issue unknown) | yes (761 lines) | BASV3 topology | `test_discovery_service`, `test_entity_factory` | GOLDEN |
| `arotherm_plus_cooling_run_discovery.yaml` | discovery dump | community (issue unknown) | yes (553 lines) | cooling run | `test_discovery_service` | GOLDEN |
| `arotherm_plus_ctlv2_cooling_discovery.yaml` | discovery dump | community (issue unknown) | yes (614 lines) | ctlv2 cooling | `test_discovery_service` | GOLDEN |
| `arotherm_plus_hwc_run_discovery.yaml` | discovery dump | community (issue unknown) | yes (553 lines) | DHW run | `test_discovery_service` | GOLDEN |
| `arotherm_plus_prenergy_discovery.yaml` | discovery dump | community (issue unknown) | yes (553 lines) | PrEnergy registers | `test_discovery_service` | GOLDEN |
| `arotherm_basv_boost_on_discovery.yaml` | discovery dump | community (issue unknown) | yes (582 lines) | boost behavior | `test_boost_fixture` | GOLDEN |
| `arotherm_basv_boost_off_discovery.yaml` | discovery dump | community (issue unknown) | yes (582 lines) | boost behavior | `test_boost_fixture` | GOLDEN |
| `arotherm_ecotec_discovery.yaml` | discovery dump | community (issue unknown) | yes (554 lines) | ecoTEC graph | `test_discovery_service` | GOLDEN |
| `flexotherm_discovery.yaml` | discovery dump | community (issue unknown) | yes (688 lines) | Flexotherm topology | `test_discovery_service` | GOLDEN |
| `flexotherm_133_cooling_discovery.yaml` | discovery dump | community (issue unknown) | before set complete (691); `raw_find_lines_after` truncated to 2 lines | Flexotherm cooling entities | `test_fake_ebusd`, `test_entity_factory` | GOLDEN (see 5.3) |
| `geniaset_bass3_discovery.yaml` | discovery dump | community (issue unknown) | yes (704 lines) | geniaSet/BASS3 | `test_geniaset_bass3` | GOLDEN |
| `v32_boiler_discovery.yaml` | discovery dump | community (issue unknown) | yes (767 lines) | V32 boiler | `test_v32_boiler` | GOLDEN |
| `arotherm_pro7_discovery.yaml` | discovery dump | community (issue unknown) | yes (475 lines) | Pro7 topology | `test_community_issue_fixtures` | GOLDEN |
| `eloblock_ve28_discovery.yaml` | discovery dump | issue #103 (`source` metadata) | reduced (15 lines, opt-in) | BAI register metadata | `test_community_issue_fixtures` | REDUCED-FAITHFUL |
| `helianthus_b524_circuit_registers.yaml` | discovery dump | community (issue unknown) | reduced (20 lines) | b524 circuit routing | `test_entity_factory` | REDUCED-FAITHFUL |
| `dumpvalues.yaml` | field reference | community | n/a | multi-field name reference | `test_fake_ebusd` | REDUCED-FAITHFUL |
| `arotherm_find.txt` | find output | owner/community (unknown) | find-only, no metadata | broad discovery/entity smoke | many | LEGACY/UNKNOWN |
| `basv_find.txt`, `v32_find.txt`, `flexocompact_find.txt` | find output | community (issue unknown) | find-only | per-family discovery | `test_discovery_service`, `test_entity_factory` | LEGACY/UNKNOWN |
| `multizone_single_circuit_find.txt`, `hmux0_yield_cop_find.txt`, `hmux0_issue99_latest_find.txt` | find output | community (issue unknown) | find-only | focused register cases | `test_discovery_service`, `test_entity_factory` | LEGACY/UNKNOWN |

Trusted fixtures: all GOLDEN dumps. The two issue #99 captures are the
authoritative real-world evidence for the `ctlv2` pollution regression.

Questionable fixtures: `arotherm_find.txt` and the other find-only captures lack
provenance metadata; `eloblock_ve28_discovery.yaml` and
`helianthus_b524_circuit_registers.yaml` are reduced. None of these should be the
sole proof of real-world compatibility for discovery or circuit ownership.

Invalid regression fixtures: none found. The synthetic graphs used for the graph
resolution tests are valid for the resolution logic but are not real-world
compatibility evidence; the real-dump regression is the golden fixture test in
`test_boost_switch.py`.

New authoritative fixtures: none added in RC3. RC2 added the two issue #99
captures. RC3 adds no new captures because none were required, and adds a guard
so future reductions of the existing golden fixtures are caught.

Removed in RC3 as unused (no test, script, or production reference):
`tests/fixtures/arotherm_registers.json`,
`tests/fixtures/community/szflo_ebusctl_info.txt`, and
`tests/fixtures/community/second_ebusctl_info.txt`. The v32 register provenance
that mentioned szflo remains documented in `mapping.py` via discussion #31.

## 4. Stripped-fixture audit

The RC2 stripped issue #99 fixtures were already replaced by full captures in
commit `85eb22f` (780 and 589 raw lines). RC3 confirmed this by asserting the
specific records are present (section 5).

For every fixture that is reduced or lacks provenance, evaluated against the
questions "could the removed data change discovery / graph resolution / entity
generation / register ownership / reads or writes":

- `eloblock_ve28_discovery.yaml` (15 lines): YES, removed data could influence
  discovery in general, but the fixture is scoped to confirmed BAI registers for
  a focused metadata test. Kept REDUCED-FAITHFUL and opt-in; not used as
  topology evidence.
- `helianthus_b524_circuit_registers.yaml` (20 lines): YES in general; used only
  for b524 circuit routing unit tests. Kept REDUCED-FAITHFUL.
- find-only captures: cannot answer for discovery ownership because they carry
  no scan/metadata; treated as LEGACY/UNKNOWN inputs only.

## 5. Fixture-integrity guard

New file `tests/test_fixture_integrity.py` (9 cases):

1. The issue #99 dumps keep the spurious `ctlv2` records
   (`ManualCoolingStartDate`, `z1RoomHumidity`, invalid-position `ERR` lines) in
   both before and after find-line sets.
2. The issue #99 dumps keep `ctlv3` as the control/DHW owner
   (`HwcOpMode`, `HwcSFMode`).
3. Discovery exposes the bare `ctlv2` node while resolution routes
   `resolve_circuit_result("ctlv2")` to `ctlv3`.
4. The HMUX0 topology (scan identity, rejected `RunDataReturnTemp`) survives.
5. Every `*_discovery.yaml` fixture keeps raw find lines and provenance metadata.

Mutation proof: deleting the 34 `ctlv2` lines from
`hmux0_issue99_2026-09-10_170850.yaml` makes the guard fail; restoring the file
makes it pass.

### 5.3 Fixture hygiene finding

`flexotherm_133_cooling_discovery.yaml` has a `raw_find_lines_after` of only two
lines (a dump-service artifact), while the complete before set (691 lines) is
present. Current tests load the before set, so no test is affected, but any
future test using `after=True` on this fixture would silently see almost no
registers. Tracked here as a fixture-hygiene follow-up.

## 6. Regression validation

`ctlv2` pollution / DHW routing:

1. Known bug: runtime-defined `ctlv2` registers create a bare node; logical
   `ctlv2` resolved to it while `ctlv3` owned the DHW registers.
2. Real input: both issue #99 golden captures.
3. Test reproduces the condition: `test_latest_dump_dhw_entity_state_is_auto_not_unknown` and
   `test_latest_dump_dhw_writes_target_resolved_controller`.
4. Fails against buggy implementation: reverted `models.py` to `85eb22f^` and ran
   them, confirmed FAIL (read routed to `ctlv2`, writes targeted `ctlv2`).
5. Fix applied: `resolve_circuit_result` prefers the control-register owner.
6. Passes: green with the fix.

Mutation checks performed: reinstating exact-node short-circuiting and disabling
control-owner detection both make the regression tests fail. The synthetic
resolution tests (`test_heating_controller_prefers_control_register_owner_over_bare_ctlv2`,
`test_heating_controller_keeps_real_ctl2_when_it_owns_control_registers`,
`test_heating_controller_two_control_owners_stay_ambiguous`) also fail against the
buggy implementation.

Reads and writes are both covered: read state (`current_operation`), read
temperature, and writes (`HwcSFMode`, holiday reset) all assert the resolved
`ctlv3` circuit.

## 7. Test-suite audit

Before RC3: 19 test files, 524 collected cases, 483 test functions, 65 with an
`Intent:` description.

After RC3: 21 test files, 532 collected cases, 487 test functions, 487/487 with
`Intent:` + `Why:`.

Changes:

- Descriptions added to 421 tests; `Why:` added to the 65 that had `Intent:` only.
- Removed 2 exact duplicate tests (`test_arotherm_pro7_hmux0_scan_classification`,
  `test_arotherm_pro7_sol00_scan_classification`; identical to
  `test_categorize_hmux0_by_scan` / `test_categorize_sol00_by_scan`).
- Fixed 3 tautological assertions (never-failing `or True`, a self-comparison, and
  a parameter restatement) and strengthened the invalid-temperature assertion to
  check the absurd decode is not exposed.
- Added 9 fixture-integrity cases and 1 release-version consistency case
  (`tests/test_version_consistency.py`, backed by `tools/version.py`).
- No production code changed in RC3.

Classification (per test function, one category each; approximate):

| Category | Count |
| --- | --- |
| Core behavior | ~171 |
| Regression | ~70 |
| Protocol/fixture | ~83 |
| Integration contract | ~21 |
| Boundary/error | ~113 |
| Implementation detail | ~28 |

### 7.1 Largest test files

| File | Functions | Observation |
| --- | --- | --- |
| `test_coordinator.py` | 94 | Broadest file; mostly real lifecycle/cache/reconciliation coverage, with several boundary tests. Highest priority; reviewed in detail. |
| `test_discovery_service.py` | 130 | Most fixture-driven; many protocol/fixture tests plus graph resolution. |
| `test_entity_factory.py` | 78 | Highest regression density (33); mostly issue-specific entity mapping. |
| `test_ebus_service.py` | 43 | Transport-level, many boundary/error cases. |
| `test_hardening_fixes.py` | 22 | Regression hardening; overlaps coordinator write-failure coverage. |

### 7.2 Duplicates, weak and stale tests

Removed (exact duplicates):

- `test_arotherm_pro7_hmux0_scan_classification`
- `test_arotherm_pro7_sol00_scan_classification`

Strengthened (dead assertions replaced with real checks):

- `test_coordinator.py::test_apply_discovery_logs_entity_platform_breakdown`
- `test_community_issue_fixtures.py::test_latest_issue99_dumps_...`
- `test_discovery_service.py::test_scan_matching_duplicate_identical_entries_are_deterministic`

Retained with rationale (candidates that add unique signal or are cheap contracts):

- `test_connect_failure_no_crash` / `test_connect_failure_repair_issue`: the first
  asserts no crash, the second asserts the repair issue is raised.
- `test_hardening_fixes.py::test_write_registers_stop_on_first_failure_without_refresh`
  vs `test_coordinator.py`: different module ownership of the same invariant; cheap
  and independent, kept.
- `test_entity_factory.py` empty-graph and YAML-override pairs: one exercises the
  synthetic path, the other a fixture graph; documented as intentionally separate.
- `test_compressor_power.py`, `test_analysis_service.py`, `test_grab_parser.py`
  overlaps: small and fast, retained.
- Property-style assertions in `test_ebus_service.py` (`is_connected`, `version`):
  trivial but cheap contracts, retained.

Fixture-dependent tests and their trust are captured in section 3. No test was
found that claims to protect a bug its fixture cannot reproduce.

### 7.3 Implementation-detail assertions

Several tests assert exact mock kwargs (`strict_verify`, `refresh`, listener call
counts). These are retained where the contract is the coordinator/entity API
boundary and they make the write path explicit; flagged here so future
refactors do not mistake them for behavioral truth.

## 8. Mandatory test description

Every retained test now carries:

```python
# Intent: <the behavior under test>
# Why: <why it matters / what regression it protects>
```

Regression tests identify the issue where the number is discoverable (#99, #101,
#103, and the entity-factory issue references).

## 9. Quality gate

- Fixture trust model and inventory documented.
- Stripped/reduced fixtures audited and classified.
- `ctlv2` pollution regression permanently covered by golden fixtures.
- Regression tests proven to fail against the buggy implementation.
- Reads and writes both covered.
- Every retained test explains what and why.
- Full suite green: `524 → 532` collected, 532 passed.
- `ruff check .` clean.
- `python3 -m compileall -f custom_components/vaillant_ebus/` clean.
- No unrelated production behavior changed.

## 10. Final principle

If a real Vaillant installation breaks because of an unexpected eBUS topology,
register definition, missing value, alias, or controller arrangement, the tests
must catch it. That requires realistic fixtures, behavioral contracts, focused
unit tests, and explicit regressions. Trust the behavior, not the test count;
trust the real dump, not an accidentally sanitized fixture.
