# New Community Data Research

Status: **RESEARCH COMPLETE — IMPLEMENTATION HANDOFF CONSUMED**
Date: 2026-09-23
Plan: [`plan-new-data-research.md`](plan-new-data-research.md)

## Executive Summary

Research for issue #111, issue #152, and discussion #32 is complete. The
separate release plan consumed this handoff for the three hardware-gated B509
definitions; no ebusd configuration files were changed.

The first local dump pass confirms that discussion #32 contains a real
multi-device capture, not only an entity-name comparison. The standard
configuration exposes several B516 energy values on HMUX0 `SW0302/HW0504`,
while the requested current/yield and runtime paths return
`ERR: element not found`. Existing HMUX0 yield/COP and compressor-power
definitions are intentionally gated to `SW0303/HW0504`, so the new hardware
variant needs exact protocol evidence before that gate changes.

## Research Question

Which parts of the new #111, #152, and #32 evidence justify a safe,
fixture-backed implementation or follow-up issue, and which parts remain
discovery-only?

## Scope And Constraints

- Community captures are not owner-hardware live verification.
- Runtime definitions must match circuit, address, message ID, sub-address,
  response layout, field offsets, units, and hardware scope.
- `ERR`, `no data stored`, invalid-position responses, and empty values remain
  unavailable; they must not become fabricated entities.
- Circuit ownership follows scan metadata and the discovery graph, not the
  logical aliases `hmu` or `ctlv2`.
- No ebusd CSV edits, `--configpath` changes, writes, or production code edits
  are part of this research phase.

## Initial Local Evidence

| Finding | Classification | Evidence | Confidence |
|---|---|---|---|
| The #32 dump scans HMUX0 `SW0302/HW0504`, CTLV3 `SW0808/HW8004`, and VWZIO `SW0302/HW0504`. | FACT | Community dump metadata, timestamp `2026-09-22T13:40:29`, integration `1.9.3`, `ebusd 26.1.26.1`. | High |
| The dump has 706 normalized registers, 68 unknown telegram candidates, and 131 labeled telegrams. | FACT | Dump sections `before_registers`, `unknown_telegrams`, and `labeled_telegrams`; parser cross-check returns 199 parsed telegrams and the same 68 unknown keys. | High |
| HMUX0 B516 heating/DHW electricity values are present: `HcElecConsDay=82.8025`, `HcElecConsTotal=3.52247e+06`, `HwcElecConsDay=627.296`, and `HwcElecConsTotal=577819`. | OBSERVATION | Dump `before_registers` and labeled B516 telegrams for slave `08`. | High |
| HMUX0 current power/yield, compressor speed, yield, and runtime probes return `ERR: element not found`. | OBSERVATION | Dump `before_registers` for `hmux0` mapped probes. | High |
| `ctlv3 Hc1RoomTempModulation` returns `ERR: element not found`. | OBSERVATION | Dump `before_registers`. | High |
| No `B51A 05ff32xx` yield request occurs in the captured traffic. | OBSERVATION | Complete `unknown_telegrams` and `labeled_telegrams` inventory. | High |
| Existing yield/COP, `Status00`, and `RunDataElPowerConsumption` definitions are gated to HMUX0 `SW0303/HW0504`. | FACT | `coordinator.py:872-983`; tests in `tests/test_coordinator.py:1296-1371`. | High |
| The #111 fixture exposes `bai FlowTempDesired` as a read value from B509 `0d3900`; the current map does not mark it writable. | FACT | `tests/fixtures/community/eloblock_ve28_issue111_2026-09-11_193100.yaml:83`, raw grab at lines 4448 and 4583 onward, and `mapping.py:431-435`. | High |
| The current BAI runtime write path covers `HeatingSwitch` and `HwcSwitch` on B509 `0eF203`/`0eF303`, plus the unverified `SetModeOverride` path; it has no confirmed `FlowTempDesired` write definition. | FACT | `coordinator.py:756-772`; issue #111 fixture and current issue comments. | High |
| The #152 implementation and fixtures address stale cache ownership and unavailable fuel counters; the latest user report says those entities disappeared in v1.9.4, while other energy entities remain. | OBSERVATION | `docs/issue-152-f34-analysis.md:17-43`, commit `0af9a07`, issue #152 latest comment. | High |

## Candidate Inventory

The relevant exact request/response/count rows are committed in
[`research-discussion-32-telegram-inventory.md`](research-discussion-32-telegram-inventory.md).
The complete 68-row machine-readable inventory is also retained in
`.research-scratch/discussion-32-unknown-inventory.json` during research. Rows
outside the requested feature families remain in the raw attachment and are
explicitly excluded in the appendix.

| Candidate family | Local evidence | Initial status |
|---|---|---|
| HMUX0 electrical power | `08:B509/055402005B0D`, count 20, response `0802015b0d00001041`; existing code calls the related definition `RunDataElPowerConsumption`. | Open; upstream scope check required |
| HMUX0/VWZIO B516 `0114` | `08:B516/0114`, count 21, and `76:B516/0114`, count 20, both with 10-byte raw responses (9-byte payloads). | Open; exact field semantics required |
| HMUX0 yield/COP | No `B51A 05FF32xx` traffic; mapped probes return `ERR`. | Discovery-only pending stronger evidence |
| HMUX0 runtime/start counters | Multiple `08:B509/05540200...` candidates; no local labels or layout. | Open; systematic upstream search required |
| VWZIO immersion telemetry | No named register in normalized dump; VWZIO B509/B516 candidates exist. | Open; owner/layout correlation required |
| CTLV3 room-temperature modulation | Mapped probe returns `ERR: element not found`; no confirmed parent register yet. | Discovery-only pending layout evidence |
| CTLV3 legionella schedule | Named register is absent from normalized dump; no safe mapping yet. | Discovery-only pending exact register evidence |

## Hypotheses

| Hypothesis | Status | Evidence so far |
|---|---|---|
| H1: The #32 standard-config gaps are partly caused by hardware/firmware-specific runtime definitions rather than missing bus traffic. | OPEN | Some B516 traffic is present and labeled; several mapped probes are absent or return errors. |
| H2: The HMUX0 `SW0302/HW0504` variant shares at least part of the B516 statistics family with the supported HMUX0 variant. | SUPPORTED | Valid Hc/DHW B516 values and labeled responses in the capture; safe scope still needs upstream confirmation. |
| H3: The MQTT names alone do not prove that the standard configuration can safely expose the same registers. | CONFIRMED | Several MQTT-requested names are absent or erroring in the standard-config dump. |
| H4: The #152 remaining energy entities are a separate problem from the fixed stale-cache/fuel-counter path. | SUPPORTED | User reports the stale pump/Fuel entities disappeared after v1.9.4, while other energy entities remain. Post-purge state still needs confirmation. |

## Pending Tracks

- Local implementation and fixture review.
- Upstream protocol and hardware-scope search.
- #111/#152 issue and release reconciliation.
- Independent contradiction and safety review.

## Local implementation findings

- At the start of research there was no committed fixture for the discussion
  #32 attachment. The release handoff now includes the complete community
  fixture and fixture-integrity coverage; the scratch copy remains available
  for byte-level comparison.
- `Hc1RoomTempModulation` is mapped generically, but local CTLV3 fixtures show
  `Hc1RoomTempSwitchOn = modulating`. These names must not be treated as
  equivalent without exact #32 telegram evidence.
- Existing local HMUX0 support originally confirmed electrical power and
  yield/COP only for `SW0303/HW0504`; release 1.9.5 adds the separately
  evidence-gated B509 `SW0302/HW0504` candidates, while runtime counters and a
  separate current heat-output register remain outside the release.
- VWZIO runtime support currently covers `Status01`; no local live fixture
  covers immersion-heater power, energy, runtime, or starts.
- The BAI fixture proves `FlowTempDesired` is readable from B509 `0d3900`, but
  no local write definition, SW0108 fixture, or forced-read-back test exists.
- The #152 fix has regression coverage for stale aliases, placeholders, and
  failed cache backfill, but no end-to-end test proves the exact entity set
  after a real purge on the user's F34 installation.

## Upstream and issue reconciliation

| Candidate | Classification | Evidence | Decision |
|---|---|---|---|
| CTLV3 `Hc1RoomTempModulation` | Strong assumption for the VRC720/CTLV family; discovery-only for exact `CTLV3 SW0808/HW8004` | Upstream issue [#506](https://github.com/john30/ebusd-configuration/issues/506) and PR [#482](https://github.com/john30/ebusd-configuration/pull/482) identify the `rcmode2` field and B524 register `020002001500`. The #32 dump returns `ERR: element not found` and contains no matching labeled telegram. | Keep out of production until exact target-hardware read/write evidence or a safe passive mapping exists. Do not alias it to `Hc1RoomTempSwitchOn`. |
| HMUX0 `b509 5402005b0d` electrical power | Strong assumption for HMUX0 `SW0302/HW0504`; confirmed upstream on the related HMUX0 family | Upstream issue [#522](https://github.com/john30/ebusd-configuration/issues/522) gives `RunDataElPowerConsumption` as `B509 5402005b0d`, `EXP`, watts. The #32 unknown row matches the request byte-for-byte: `f108b509055402005b0d`, response `0802015b0d00001041`, count 20. The exact SW0302 semantic extension is not independently proven by that response alone. | Highest-value #32 candidate. Keep the scan-identity gate and require a complete fixture plus positive/absent tests before widening production scope. |
| HMUX0 current `b51a` power/yield | Strong assumption for related HMUX0 hardware; not confirmed for #32 `SW0302/HW0504` | PR [#604](https://github.com/john30/ebusd-configuration/pull/604) and issue [#609](https://github.com/john30/ebusd-configuration/issues/609) document `05ff3223/3224` and yield IDs, mainly with HW5103 evidence. The #32 capture has no `B51A 05ff32xx` requests. | Do not use as a fallback for the confirmed B509 electrical-power candidate. Require target-variant evidence and avoid adding active polling from a name match. |
| HMUX0 `YieldHc`/`YieldHwc` | Strong assumption for the HMUX0 family; target-variant polling remains open | Issue #522 reports plausible values on HMUX0 `SW0302/HW0504`; PR #604 gives the exact B51A IDs and scales. The #32 standard-config capture has no B51A yield traffic and all mapped probes return `ERR`. | Separate from B516 electric counters. Candidate for a later hardware-gated pass only after polling safety and fixture behavior are resolved. |
| HMUX0 `RunStats*` | Strong assumption for observed B509 IDs; discovery-only for unobserved IDs | PR #604 documents B509 layouts for hours, starts, pumps, fans, and valves. The #32 dump observes multiple matching `05540200...` rows, including `d70b` and `d80b`, but not every family member. | Add only byte-correlated, observed IDs first; do not enable the entire family from names alone. |
| VWZIO immersion-heater metrics | Confirmed/strong assumption on HW5103; discovery-only for #32 `HW0504` | PR [#598](https://github.com/john30/ebusd-configuration/pull/598) and issue #609 document `B51A 05ff3246/3249/324a/324c` on VWZIO HW5103. The #32 VWZIO is `SW0302/HW0504` and has no matching B51A traffic. | Obtain target-HW0504 evidence before adding these entities. Do not transplant the HW5103 layout. |
| CTLV3 `HwcLegionellaDay/Time` | Confirmed for VRC720 configuration; strong assumption for exact CTLV3 target | Issue [#556](https://github.com/john30/ebusd-configuration/issues/556) and PR #482 document B524 registers `0x2b`/`0x2a`, `daysel3`, and working writes (`off`, `Mo`, `daily`). The #32 dump has no matching register or transition. | Keep as a focused follow-up requiring target-hardware before/after evidence and write verification. |
| BAI `FlowTempDesired` write | Strong negative evidence for SW0107; discovery-only for SW0108 | Issue #111 and the Protherm follow-up show B509 `0e3900` accepted on SW0107/HW7503 without changing the forced read-back. SW0108 has only a failed raw write attempt and no successful integration-path test. | Do not add a write definition or claim `SetModeOverride` support. Keep hardware/firmware investigation separate. |

## Issue-specific conclusions

### Issue #111

The original issue is complete: `HeatingSwitch` and `HwcSwitch` work on BAI00
`SW0107/HW7503` through B509 writes `0eF203` and `0eF303`. The later
`FlowTempDesired` evidence is a new investigation, not a regression of that
fix. `b509 0d3900` is confirmed as the read path, but the tested `0e3900`
write has strong negative evidence on SW0107. SW0108 only proves live reads and
does not yet prove the same write path.

### Issue #152

The v1.9.4 release fixed stale logical-circuit/cache values and stale fuel
values. The remaining Electrical, Environment, and Solar Energy entities are a
separate mapping/default-enable question. The user has confirmed the first fix,
but has not yet confirmed the remaining entity set after a real purge. No new
register mapping should be mixed into the stale-cache fix.

### Discussion #32

The standard-config dump is a valid gap inventory with exact hardware scope,
not yet a production mapping specification. The strongest immediate candidate
is the observed HMUX0 B509 electrical-power candidate (`5b0d`). The B51A yield/current family,
VWZIO immersion metrics, CTLV3 modulation, and legionella schedule each need
separate hardware/safety boundaries.

## Hypothesis update

| Hypothesis | Status | Update |
|---|---|---|
| H1: The #32 standard-config gaps are partly caused by hardware/firmware-specific runtime definitions rather than missing bus traffic. | SUPPORTED | The capture has exact B509/B516 traffic for some missing functions, while B51A yield/current requests are absent; upstream scope differs by firmware. |
| H2: HMUX0 `SW0302/HW0504` shares at least part of the B516 statistics family with supported HMUX0 variants. | CONFIRMED | The capture contains valid Hc/DHW B516 values with exact request/response pairs. |
| H3: MQTT names alone do not prove that standard ebusd configuration can safely expose the same registers. | CONFIRMED | Several names return `ERR`, and the strongest upstream matches have hardware-specific scope. |
| H4: The #152 remaining energy entities are separate from the fixed stale-cache/fuel path. | SUPPORTED | The user confirmed the stale pump/Fuel entities disappeared, while other energy entities remained; post-purge registry state is still unknown. |

## Tool improvement applied

The agent-facing upstream search wrapper now supports:

- `--cache-dir DIR` or `UPSTREAM_SEARCH_CACHE_DIR` for reusable formatted search
  output keyed by repository, kind, query, match mode, limit, and output mode;
- `--refresh` to bypass an existing cache before treating a negative result as
  current;
- automatic retries for rate-limit failures (`403`, `rate limit`, and
  `secondary rate`) with `--retry` and `--retry-delay` controls;
- immediate failure for unrelated `gh` errors instead of retrying blindly.

Focused validation: `bash -n tools/search_upstream.sh` and
`.venv/bin/pytest -q tests/test_search_upstream.py` pass (`8 passed`).

## Independent audit outcome

The independent audit found and the research pass corrected these points:

- The HMUX0 B509 `5b0d` extension is now classified as a **strong assumption**
  for `SW0302/HW0504`, not confirmed solely by the matching telegram.
- The report no longer calls a new B509 `r` definition passive merely because
  the original frame came from another master; active-read cadence and bus
  impact remain implementation gates.
- Relevant exact telegram rows are now in the committed inventory appendix.
- `search_upstream.sh` now distinguishes rate-limit failures from unrelated
  authorization failures and supports `--refresh` for cache bypass.

The audit passed the #152 post-purge boundary unchanged: the remaining energy
entities are not confirmed until the user reports their state after a real
purge.

## Recommendations

1. Keep the research/implementation split. Do not add runtime definitions from
   the MQTT table alone.
2. Start implementation research with the byte-correlated HMUX0 B509
   candidates (`5b0d`, `0d0a`, and `c509`), using the complete #32 dump as a
   fixture and safe absent paths. The upstream B509 block is documented as the
   monitoring/diagnostic block intended for regular polling, but the observed
   frames alone are not proof that any new integration `r` definition is
   passive.
3. Treat B51A HMUX0 yield/current and B509 runtime counters as separate family
   work; define only observed IDs and document active-read impact.
4. Keep VWZIO immersion metrics gated by target hardware. HW5103 evidence does
   not establish HW0504 compatibility.
5. Keep #111 FlowTempDesired and #152 remaining energy entities as separate
   follow-up scopes.

## Implementation Handoff

```text
Problem:
  The new community data exposes multiple gaps across BAI00, BASS3/VR_70,
  HMUX0, CTLV3, and VWZIO. Some names map to existing protocol families;
  others have only MQTT or cross-hardware evidence.

Confirmed root cause / conclusion:
  #111 switch control is fixed; FlowTempDesired writes remain unverified.
  #152 stale cache/fuel handling is fixed in v1.9.4; remaining energy entities
  are a separate unresolved scope. #32 has one strong byte-correlated HMUX0
  B509 power candidate, while several other families remain hardware-gated.

Relevant files:
  custom_components/vaillant_ebus/coordinator.py
  custom_components/vaillant_ebus/backend/mapping.py
  custom_components/vaillant_ebus/backend/models.py
  custom_components/vaillant_ebus/backend/discovery_service.py
  custom_components/vaillant_ebus/backend/entity_factory.py
  tests/test_coordinator.py
  tests/test_community_issue_fixtures.py
  tests/fixtures/community/

Relevant upstream sources:
  ebusd-configuration issues #506, #522, #556, #600, #609 and PRs #482,
  #598, #604; full links and scope are recorded above.

Recommended change:
  This handoff was consumed by release 1.9.5. The complete #32 capture is now
  a community fixture and the three B509 EXP candidates have fixture-backed,
  hardware-gated definitions. Active `r` behavior is documented as B509
  monitoring-block behavior; it is not called passive merely because the
  original frame came from another master.

Scope and protected behavior:
  Preserve graph-driven circuit ownership, absent-register filtering, passive
  bus behavior, strict write verification, and stale-cache protections.

Tests required:
  Complete #32 fixture integrity, candidate decode/absent paths, exact scan
  gates, owner-circuit resolution, and no unsafe active polling. Separate tests
  are required for any BAI write or #152 purge behavior.

Risks:
  Cross-hardware B51A layouts, active polling side effects, BAI write acceptance
  without hardware application, and stale cache values being mistaken for live
  readings.

Remaining unknowns:
  Target-HW0504 VWZIO immersion layouts, exact #32 B51A support, CTLV3
  modulation/legionella target behavior, SW0108 BAI writes, and post-purge
  #152 entity registry state.
```

## Historical Checkpoint Continuation State

```text
Question: Which new community-data candidates can safely become implementation work?
Completed tracks: Initial #32 dump parse and local coordinator/test pass.
Sources/evidence: Discussion #32 attachment; coordinator.py; test_coordinator.py; issue #152 fixture analysis.
Hypotheses: H1-H4 above.
Confirmed conclusions: The #32 dump is valid evidence of a SW0302/HW0504 variant and contains both live B516 values and absent mapped paths.
Open questions: Exact layouts for B509/B516/B51A candidates; BAI00 FlowTempDesired write path; post-purge #152 scope.
Next step at this checkpoint: Reconcile independent upstream and issue-history research, then challenge classifications. This was completed below.
```

## Final Continuation State

```text
Question: Which new community-data candidates can safely become implementation work?
Completed tracks: Local implementation/fixture review; complete #32 dump parse; upstream protocol search; #111/#152 issue and release reconciliation; agent-tool reliability improvement.
Sources/evidence: Discussion #32 attachment; local coordinator, mapping, discovery, entity, and test files; F34 and eloBLOCK fixtures; upstream issues/PRs #482, #506, #522, #556, #598, #600, #604, #609; current GitHub issue comments.
Hypotheses: H1 supported, H2 confirmed, H3 confirmed, H4 supported.
Confirmed conclusions: #111 switch control is complete; #152 stale-cache/fuel handling is fixed; #32 B516 statistics and HMUX0 B509 5b0d traffic are real evidence; cross-hardware B51A/VWZIO mappings are not yet target-confirmed.
Open questions: post-purge #152 registry state; safe target-HW0504 definitions; exact CTLV3 modulation/legionella behavior; BAI SW0108 writes; active-polling safety for B51A candidates.
Next highest-value step: Continue validation and release-gate work for v1.9.5; deferred B51A, VWZIO, CTLV3-write, BAI-write, and #152 post-purge items retain their documented triggers.
```

ASK_WORKFLOW_PASS phase=RESEARCH
