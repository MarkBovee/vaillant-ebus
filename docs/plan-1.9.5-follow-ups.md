# Release 1.9.5 — Deferred Follow-up Plan

Status: **PLANNED**
Date: 2026-09-23
Parent release: `v1.9.5`
Source: `docs/research-new-data.md` and `docs/plan-1.9.5-candidate-matrix.md`

## Purpose

Track the evidence-backed items that were deliberately left out of v1.9.5.
These are not rejected ideas; each one needs a specific hardware, protocol, or
write-safety trigger before implementation starts.

No follow-up item may be enabled by copying a generic MQTT name, a register
family from another hardware variant, or a write layout that only returned
`done`. Community data is valid evidence, but it must be preserved as a
complete fixture and scoped to the hardware that produced it.

## Follow-up matrix

| Priority | Area | Current status | Minimum trigger | Protected boundary |
|---|---|---|---|---|
| 1 | HMUX0 B51A yield/current values | Strong family evidence; target `SW0302/HW0504` has no `B51A 05ff32xx` traffic in the #32 dump | A target-variant dump with `YieldHc*`, `YieldHwc*`, or `Current*Power` traffic, exact response bytes, and a safe polling decision | Keep B51A separate from B509/B516; do not widen the existing `SW0303` gate by alias |
| 2 | HMUX0 runtime counters | Exact upstream `hoursum2`/`cntstarts2` layouts exist, but runtime datatype support and decode behavior are not implemented | Add and test runtime datatype support, then use observed B509 IDs (`c40b`, `c50b`, `d70b`, `d80b`) with positive and absent fixtures | Do not decode counters as raw `UIN`; preserve units, scaling, and parsed fields |
| 3 | VWZIO immersion-heater metrics | Confirmed/strong evidence on HW5103 only; #32 target is VWZIO `HW0504` | Target `HW0504` capture containing `B51A 05ff3246/3249/324a/324c` or an exact replacement family, preferably idle and heater-active states | Never copy HW5103 layouts to HW0504 without byte and scope evidence |
| 4 | CTLV3 room-temperature modulation | Strong VRC720-family evidence; exact CTLV3 target telegram absent | Target CTLV3 read capture while changing room-temperature influence, with exact B524 request/response and field semantics | Do not equate `Hc1RoomTempModulation` with `Hc1RoomTempSwitchOn`; parent register owns polling |
| 5 | CTLV3 legionella schedule | Upstream B524 `HwcLegionellaTime/Day` mapping exists; #32 has no target transition | Target before/after capture for weekday/time plus direct write and forced read-back evidence | No new write path without hardware-level application/read-back proof |
| 6 | BAI00 `FlowTempDesired` | Read path confirmed; SW0107 `0e3900` write has strong negative evidence; SW0108 is unknown | Byte-for-byte SW0107/SW0108 write capture with forced read-back and an observable boiler state change | Do not route through `SetModeOverride`; do not treat ebusd `done` as hardware acceptance |
| 7 | Issue #152 remaining energy entities | Stale cache/fuel fix shipped; remaining Electrical/Environment/Solar entities were not confirmed after purge | User report or v1.9.5+ discovery/registry evidence after stale-entity purge, including source circuit and `disabled_by` state | Keep registry cleanup, mapping, and default enablement as separate concerns |

## Execution order

### Phase 1 — Evidence collection

- Obtain the smallest fresh capture described by the matrix trigger.
- Preserve the complete source capture under `tests/fixtures/community/`.
- Record scan identity, firmware, circuit owner, message ID, sub-address,
  request, response length, response bytes, state, and occurrence count.
- Search upstream issues and PRs with exact IDs and payload fragments, then read
  complete promising threads.

### Phase 2 — Candidate decision

- Classify each candidate as `confirmed`, `strong assumption`, `speculative`, or
  `discovery-only`.
- Decide `r`, update-only, or out-of-scope explicitly. An observed frame from
  another master is not proof that an integration `r` read is passive.
- Confirm owner-circuit resolution against the graph and raw register source.
- Define positive, absent, invalid-position, and stale-cache expectations before
  source changes.

### Phase 3 — Implementation and validation

- Add the smallest data-driven runtime/mapping change.
- Add fixture-backed positive and absent-path tests.
- For writes, require direct write acceptance, forced read-back, and a hardware
  state transition.
- Run the full repository validation and an independent review/audit before a
  release decision.

## Revisit rules

- A new user dump may promote only the matching hardware/firmware row; it does
  not generalize a layout to all Vaillant devices.
- A zero-result upstream search never closes a candidate by itself, especially
  when GitHub rate limiting affected the query.
- If a trigger arrives during another release, add it to that release's plan
  first; do not silently expand an open release branch.
- Deferred items remain unavailable rather than exposing guessed values or
  virtual entities.

## Explicitly out of scope until a trigger arrives

- Generic B51A enablement for every HMUX0 firmware.
- HW5103 VWZIO definitions on HW0504.
- BAI `FlowTempDesired` or `SetModeOverride` write changes.
- CTLV3 writes based only on upstream definitions without target read-back.
- #152 entity deletion, registry edits, or remote Home Assistant changes by the
  agent.
