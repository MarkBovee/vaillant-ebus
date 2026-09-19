# Release plan: v1.9.0

## Risk and release gate

This is a release-sensitive change. It combines Home Assistant entity contracts,
climate writes, community-provided eBUS captures, and a release branch. No release
claim is valid until the final branch has passed validation, independent review,
independent audit, and a release-gate decision.

Use a standard independent audit for the isolated datetime and Quick Veto changes.
Escalate the audit to deep if the energy-counter or Energy Manager State evidence
gate opens, because those change cross-cutting unit or state semantics.

## Scope

| Class | Item | Evidence and intended outcome |
| --- | --- | --- |
| Must | #143 date-only entities | Completed in #145: the supported `DateEntity` contract replaces the unsupported capability-attribute approach, with an approved config-entry migration that retires the six replaced `datetime.*` entries. |
| Must | #142 BASS3 Quick Veto capability | Completed: Boost, AUTO target writes, stale-veto updates, and cancellation require authoritative duration-register discovery on the resolved controller circuit. Unknown or absent capability yields a normal HA error without any `QuickVeto*` write. |
| Must | Release hygiene | Start from current `origin/main`, retain only active local branches, create `release/v1.9.0`, and keep the version sources consistent when the scope is implemented. |
| Must | Inbox and capture intake | Refresh `.gh-inbox-state.json` without duplicate replies, download complete new issue captures with provenance, and add fixture-load coverage before using any community data in production. |
| Should | #141 electrical-energy units | Upstream confirms one B516 `EXP / 1000 → kWh` layout for day and total counters, but #141's local ebusd values conflict with that representation and lack response bytes/scan identity. Defer only because evidence conflicts: obtain the reporter's B516 responses and active definition, then implement the resolved representation with statistic-safe migration behavior. |
| Should | #102 automatic DHW state | Analyze the downloaded automatic-DHW captures. Add state logic only if an active-period signal is repeatable, distinct from idle, and fixture-backed. |
| Could | #101 Quiet mode on HMUX0 SW0406/HW0504 | Keep discovery-only. Revisit only with a time-ordered raw capture containing repeatable loud-to-quiet and quiet-to-loud transitions, an upstream layout, and passive-cache evidence across startup. |
| Out | #129 and #138 source changes | Both BASS3 Zone 1/2 write fixes shipped and received hardware verification in v1.8.6. Close administratively only after the release scope is settled. |

## Stages

1. Sync and cleanup (light): fetch/prune, resolve the duplicate local `main` merge safely, preserve branches that back an open PR or a release, and create work from `origin/main`.
2. #143 date-platform migration (standard): completed in #145 and included in this branch. Keep its date-service, registry-retirement, discovery-gating, and delayed-discovery regressions green.
3. Quick Veto (#142, deep): completed with a tri-state discovery gate across every quick-veto write path. Regression coverage includes BASS3/no-duration, startup unknown state, placeholder-only support, CTLV3 resolution, stale boost updates, cancellation, and supported controllers.
4. Capture evidence (standard): download every issue attachment that is newer than the checked-in fixture inventory. Preserve raw data and provenance under `tests/fixtures/community/`; load-test each fixture and record candidate evidence before proposing a register/state change.
5. Evidence gates (#141 and #102, deep if opened): implement only confirmed or strong-assumption mappings with hardware scope, a safe absent path, and fixture-backed regressions. Otherwise record the specific missing evidence and keep the item deferred.
6. Release preparation (standard): version is now reserved as `1.9.0`; keep release notes current, run the complete test matrix, then request separate review, audit, and release-gate decisions before tagging.

## Plan check

- `DateEntity` is the supported HA contract for the two writable date-only controls. `EbusdQuickVetoEndEntity` remains a `DateTimeEntity` and stays read-only.
- A controller that lacks `QuickVetoDuration` cannot start a time-controlled quick veto. Hiding only the preset is insufficient because `async_set_temperature()` can otherwise issue the same unsupported write.
- Community captures are never treated as live verification. The full raw fixture, the discovered graph, owner-circuit resolution, and absent path are the proof gate.
- A global Wh-to-kWh change would corrupt displayed values or long-term statistics on variants with another scale. No such change may ship without scan-specific evidence and a migration decision.
- The automatic-DHW dump ends outside the active interval; it cannot justify a new state signal by itself.
- Branch cleanup must not remove the open PR head, the new release branch, `main`, or any remote branch with an open PR/release purpose.

## New capture inventory

All capture content below was preserved from public issue attachments. Git
normalizes the three raw #101 grab files from CRLF to LF line endings; telegram
content, line order, and counts are unchanged. They are community evidence,
never local live verification.

| Issue | Fixture or raw capture | Evidence and classification |
| --- | --- | --- |
| #101 | `arotherm_pro7_issue101_2026-09-15_203102_discovery.yaml` | HMUX0 quiet-switch discovery capture. It remains discovery-only: no confirmed Quiet register/layout appears. |
| #101 | `arotherm_pro7_issue101_2026-09-16_quiet_to_loud.ebusctl.txt`, `arotherm_pro7_issue101_2026-09-16_loud_to_quiet.ebusctl.txt`, `arotherm_pro7_issue101_2026-09-17_quiet_loud_quiet_loud.ebusctl.txt` | Raw B508/0209 correlation data. Keep as research evidence; it does not prove an entity layout or startup cache behavior. |
| #102 | `flexotherm_issue102_2026-09-12_161841_discovery.yaml`, `flexotherm_issue102_2026-09-16_103411_discovery.yaml`, `flexotherm_issue102_2026-09-17_090525_discovery.yaml` | HMU00/CTLV3 automatic-DHW captures. The active automatic-DHW signal remains unproven, so no new Energy Manager State mapping ships from these dumps. |

The duplicate #102 upload with attachment IDs `32323735` and `32324072` has the
same SHA-256 (`f24a5d76854b6c019a72548bf44ed75a467b9931d031d2de788a9a51a881c7ea`)
and is stored once.

## Required validation

Run the focused tests after each stage, then before merge/release run:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check custom_components/vaillant_ebus/datetime.py custom_components/vaillant_ebus/climate.py custom_components/vaillant_ebus/coordinator.py custom_components/vaillant_ebus/backend/mapping.py
.venv/bin/pytest -q
python3 tools/version.py check
python3 -m compileall -f custom_components/vaillant_ebus/
```

The final release gate also requires successful GitHub CI on the final release
branch, an independent review, an independent audit, and a clean branch inventory.
