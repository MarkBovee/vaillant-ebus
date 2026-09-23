# New Community Data Research Plan

Status: **RESEARCH COMPLETE — HANDOFF CONSUMED BY RELEASE 1.9.5**
Date: 2026-09-23
Repository: `MarkBovee/vaillant-ebus`

## Goal

Turn the new evidence from issue #111, issue #152, and discussion #32 into an
evidence-backed implementation backlog. The research phase itself did not
change production code or ebusd CSV files; its handoff is now consumed by the
separate `docs/plan-1.9.5.md` release plan.

Discussion #31 is not in the active scope because its stored inbox state has no
new data.

## Risk class

Significant, compatibility-sensitive protocol research. The evidence spans
BAI00 boiler control, BASS3/VR_70 entity ownership, and HMUX0/CTLV3/VWZIO
registers. A wrong circuit, message layout, scale, or write assumption can
create incorrect Home Assistant entities or send unsafe eBUS writes.

## Research scope

### Must

- Preserve and inspect the complete community evidence already attached to the
  three active items.
- Build an evidence table for every relevant unknown or unmapped telegram in
  the discussion #32 dump, including master, slave, message ID, sub-address,
  exact request/response, response length, states, and occurrence count.
- Investigate the #32 candidates for:
  - CTLV3 room-temperature modulation control.
  - HMUX0 current electrical power and current heat output.
  - HMUX0 heating/DHW yield and runtime/start counters.
  - VWZIO immersion-heater power, energy, runtime, and starts.
  - CTLV3 legionella schedule data.
- Investigate the #111 BAI00 evidence for `FlowTempDesired`, including the
  difference between the confirmed `HeatingSwitch`/`HwcSwitch` writes and the
  unverified `FlowTempDesired` path across SW0107 and SW0108.
- Reconcile the #152 post-v1.9.4 report with the existing F34 fixtures and
  analysis: separate stale registry/cache entities from current discovered
  BASS3/BAI00 entities, including behavior after purge.
- Search upstream issues, pull requests, configuration history, and local code
  for exact protocol layouts. Classify each candidate as `confirmed`, `strong
  assumption`, `speculative`, or `discovery-only`.
- Produce a research report with citations, contradictions, hypotheses,
  minimum next evidence, and an implementation handoff.

### Should

- Compare the standard-config #32 dump with the integration's runtime defines,
  `REGISTER_MAP`, discovery graph, and existing community fixtures.
- Check whether the MQTT names cited by the reporter map to actual upstream
  register definitions or only to custom configuration aliases.
- Identify the smallest fixture additions and regression tests needed for each
  candidate that reaches `confirmed` or `strong assumption`.
- Re-check all circuit ownership assumptions against scan identities and raw
  register source circuits; do not use `hmu`/`ctlv2` as universal aliases.

### Could

- Prepare a release-sized implementation sequence after the research handoff.
- Draft issue splits for unrelated follow-up areas if the evidence shows that
  #32 or #152 contains more than one safe implementation boundary.

### Explicitly out of scope

- Production code, fixture, or test edits during this research phase.
- Uploading, editing, deleting, or overriding ebusd CSV files.
- Setting ebusd `--configpath`.
- Guessing layouts from register names, plausible values, or MQTT names alone.
- Live writes or active hex scans on the owner's bus.
- Claiming owner-hardware live verification for community captures.
- Release, merge, tag, or deployment work.

## Research tracks

1. **Local implementation and fixtures**
   - Trace discovery graph ownership, runtime definitions, fallback reads,
     entity filtering, and cache handling for all candidates.
   - Locate existing fixture coverage and regression gaps.

2. **Dump and protocol evidence**
   - Parse the complete #32 dump, deduplicate relevant unknown telegrams, and
     correlate labeled traffic with `before_registers` and `after_registers`.
   - Compare exact message IDs, sub-addresses, response lengths, field offsets,
     units, and sentinel behavior.

3. **Upstream and history**
   - Search `john30/ebusd-configuration` issues and pull requests using message
     IDs, sub-addresses, payload fragments, device identities, feature terms,
     and candidate names.
   - Read promising threads completely, including comments, and inspect local
     Git history for prior mappings and regressions.

4. **Issue-specific reconciliation**
   - Reconcile #111's BAI00 write evidence and #152's post-release purge result
     with the current release behavior and existing analysis documents.
   - Separate confirmed fixes from new follow-up requests.

5. **Agent-tool reliability**
   - Audit the upstream search wrapper used by research agents.
   - Add only evidence-backed improvements for rate-limit retries and reusable
     cached search output, with focused wrapper tests.

## Plan-check gate

Before any implementation is proposed, challenge:

- circuit alias resolution for HMUX0/HMUX0 variants and BASS3/BAI00 owners;
- field entries versus parent registers;
- stale cache values versus current discovery values;
- active polling and bus-load impact of any runtime definition;
- write safety, read-back validity, and firmware scope for BAI00;
- absent-register behavior and entity creation when a candidate returns `ERR`,
  `no data stored`, or an invalid-position response;
- fixture provenance and whether each conclusion is community evidence or live
  verification.

## Plan-check outcome

**Passed with one scope clarification.** The research must keep #152's
post-v1.9.4 report separate from a confirmed post-purge result: the remaining
entities are not yet proven to survive a stale-entity purge. The #111 follow-up
is evidence collection only because the original issue is closed and no
`FlowTempDesired` write path is verified. The #32 attachment is community data;
any implementation candidate must first receive fixture-backed coverage and a
safe absent-register path.

## Definition of done

- Every in-scope candidate has an evidence row or an explicit reason it is not
  relevant.
- Each candidate has a confidence classification and hardware/firmware scope.
- Counterevidence and blocked upstream searches are recorded instead of hidden.
- The report names the minimum next evidence for unresolved candidates.
- The implementation handoff identifies exact files, fixtures, tests, and
  safety gates without modifying them in this phase.
- No production or ebusd configuration files changed.

## Validation

- Parse the downloaded #32 dump with the repository's dump parser/YAML loader.
- Cross-check candidate rows against raw dump sections and normalized register
  sections.
- Re-run exact upstream search variants with cached output and inspect complete
  promising threads.
- Have an independent research/review pass challenge the evidence table before
  implementation starts.

## Historical research checkpoint 1 — local dump pass

- The #32 attachment is a v4 community dump from integration `1.9.3` and
  `ebusd 26.1.26.1`, with scan identities HMUX0 `SW0302/HW0504`, CTLV3
  `SW0808/HW8004`, and VWZIO `SW0302/HW0504`.
- The dump contains 706 normalized registers, 68 unknown telegram candidates,
  and 131 labeled telegrams. The relevant inventory is now preserved in the
  committed research appendix; the complete machine-readable inventory remains
  in the ignored research scratch area.
- HMUX0 B516 heating/DHW electricity registers return values, while the
  requested current power/yield, compressor-speed, yield, and runtime-counter
  probes return `ERR: element not found` in this standard-config capture.
- `ctlv3 Hc1RoomTempModulation` also returns `ERR: element not found`; the
  dump has no `B51A 05ff32xx` yield requests.
- At the time of this checkpoint, the coordinator gated HMUX0 yield/COP,
  `Status00`, and `RunDataElPowerConsumption` to HMUX0 `SW0303/HW0504`; the
  release plan later added the evidence-gated B509 `SW0302/HW0504` scope.

## Research completion checkpoint

- Local, upstream, and issue-history tracks completed.
- The agent-facing search wrapper was improved with opt-in caching and
  rate-limit retries; focused tests pass.
- Research is complete and its handoff is consumed by `docs/plan-1.9.5.md`.
  The release implements the three evidence-gated B509 EXP candidates and
  retains the observed-frame-versus-passive-read distinction.
