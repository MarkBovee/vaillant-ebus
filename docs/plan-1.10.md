# Release 1.10 — Follow-up Plan

Status: **PLANNED**
Date: 2026-09-24
Parent release: `v1.9.5`
Source: `docs/research-new-data.md`, discussion #32, and issues #111, #152,
#158.

## Goal

Resolve the evidence-backed follow-ups from v1.9.5 without adding guessed
registers, unsafe polling, or unverified writes. Every candidate needs an
explicit hardware gate, protocol layout, polling mode, and positive/absent
test path before implementation.

Community data remains valid evidence only when the complete capture is
preserved and the mapping stays scoped to the hardware that produced it.

## Candidate matrix

| Priority | Candidate or area | Evidence and scope | Polling/write boundary | Minimum trigger |
|---|---|---|---|---|
| 0 | HMUX0 B509 active reads | #32 target HMUX0 `SW0302/HW0504` discovers the three v1.9.5 entities, but integration reads return `ERR: invalid position` while normal `f108` traffic returns full frames | Do not treat discovery or ebusd `done` as a valid value; compare request paths before choosing active reads or update-only definitions | Corrected read or safe update-only proof with positive and absent fixtures |
| 0 | BASS3 injected `Hc1/Hc2` state registers | #158 target BASS3 `SW0708/HW4304` returns one-byte `00` for absent B524 sub-addresses, causing `EXP`/`ULG` decode errors and poll churn | Do not poll unconfirmed `r5` definitions; preserve valid CTLV/BASS variants | Reproduction fixture, capability/probe gate, and absent-path regression |
| 1 | HMUX0 B51A yield/current values | Strong family evidence, but #32 target `SW0302/HW0504` has no matching B51A traffic | Keep B51A separate from B509/B516; active polling safety is unresolved | Target dump with exact frames, values, and safe polling decision |
| 2 | HMUX0 runtime counters | Upstream `hoursum2`/`cntstarts2` layouts match B509 IDs `c40b`, `c50b`, `d70b`, and `d80b`; runtime datatypes are not implemented | Do not decode as raw `UIN`; preserve units and parsed fields | Runtime datatype support plus positive and absent fixtures |
| 3 | VWZIO immersion metrics | Evidence exists for HW5103, while #32 is VWZIO `HW0504` | Never copy HW5103 layouts to HW0504 | Matching HW0504 traffic and byte-compatible layout |
| 4 | CTLV3 `Hc1RoomTempSwitchOn` | #32 proves B524 `020002001500` on CTLV3 `SW0808/HW8004`; writing `thermostat` changes the heating setting to `expanded` | Add a `select` only with forced read-back; do not alias `Hc1RoomTempModulation` | Read/write coverage for `off`, `modulating`, and `thermostat` |
| 5 | CTLV3 `HwcLegionellaDay/Time` | Upstream B524 `0x2a`/`0x2b` mapping exists; target transition is absent | No write path from upstream evidence alone | Target before/after capture and direct write/read-back proof |
| 6 | BAI00 `FlowTempDesired` | Read path works; SW0107 `0e3900` write has strong negative evidence and SW0108 is unknown | Do not route through `SetModeOverride` or treat `done` as acceptance | Byte-for-byte write capture, forced read-back, and boiler state transition |
| 7 | #152 remaining energy entities | v1.9.4 removed stale pump/fuel values, but F34 still shows Electrical, Environment, and Solar entities after purge | Do not delete entities or change defaults from symptoms alone | Entity IDs, source circuits, raw names, values, and `disabled_by` state |
| 8 | #111 `SetModeOverride` | Closed; read-side VE28 support works, but target BAI00 SW0107/SW0108 hardware effect remains unproven | Keep the compatibility definition unchanged | Reopen only with target write, read-back, and observable mode-transition evidence |

## Evidence incorporated

- **Discussion #32:** The complete dump identifies HMUX0 `SW0302/HW0504`,
  CTLV3 `SW0808/HW8004`, and VWZIO `SW0302/HW0504`. It supports the three
  B509 candidates, but the v1.9.5 active-read path does not decode on the
  target. It also proves `Hc1RoomTempSwitchOn`; it does not prove a separate
  `Hc1RoomTempModulation` register.
- **Issue #152:** The v1.9.4 stale-cache and fuel-counter fix was verified.
  The remaining energy entities need registry and source-circuit evidence
  before default-enable or deletion changes.
- **Issue #111:** The issue is closed. Its remaining value is a write-safety
  boundary, not a new feature claim.
- **Issue #158:** The BASS3 one-byte response is a real invalid-position
  regression, not ordinary unavailable data. Stop the unconfirmed polls before
  broadening filtering.

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
