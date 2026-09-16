# Release v1.8.6 Plan

## Goal

Ship the next release with the confirmed BASS3 write fix and the strongest
follow-up work supported by the current user data. Keep unsupported hardware
paths safe and avoid guessing register layouts.

## Scope

### Must

- **Issue #138: BASS3 `Z1DayTemp` write path**
  - Reproduce the current write target on BASS-family controllers.
  - Align the write definition with the confirmed `0x22` read path where the
    hardware and scan metadata support it.
  - Preserve the existing `ctlv2`/`ctlv3` write path.
  - Add fixture-backed coverage for accepted writes, target circuit, and safe
    behavior when the register is absent.
  - Ask the reporter to verify Zone 1 after the fix.

### Should

- **Issue #102: automatic DHW operating state**
  - Compare the new automatic-DHW dump with the existing manual-boost dump.
  - Identify the signal that differs during automatic DHW operation.
  - The current capture ends in idle values and contains no active transition
    signal; leave mapping unchanged until a capture covers the active interval.
  - Add fixture coverage for manual DHW, automatic DHW, and non-DHW state.

- **Issue #129: Saunier-Duval F34 Zone 2**
  - Keep the regular ebusd configuration as the baseline; do not use the
    `/next` configuration as production evidence because it removes entities.
  - Compare BASS3 Zone 2 registers with the existing `15.700` fixture and the
    user's dump.
  - Separate missing Zone 2 discovery from invalid-position registers and stale
    Home Assistant entities.
  - The dump proves Zone 2 room temperature and operation mode, but not the
    `Z2DayTemp` read/write layout; leave it discovery-only until that evidence
    arrives. Do not add a guessed `0x22` mapping.

### Could

- **Issue #101: Quiet mode on aroTHERM Pro**
  - Continue only after the raw `ebusctl grab` requested from the user arrives.
  - Compare the loud-to-whisper write and read-back traffic with existing
    HMUX0 HW0504 fixtures.
  - The requested raw `ebusctl grab` is still missing; keep discovery-only
    status if no stable register or telegram appears.

- **Discussion #31 / BazsiDev eloBLOCK VE 28 data**
  - Review the new dump against issue #111 and the existing VE 28 fixture.
  - Extend coverage only if it adds a new confirmed hardware or firmware path.
  - Do not reopen the resolved read-support issue #103.

- **Issue #109: ecoTEC/VRT380 tank detection follow-up**
  - The main ecoTEC/VRT380 support is complete: controller mapping, writes,
    device naming, and stale-device handling are already released and verified.
  - Keep the issue out of the v1.8.6 implementation scope.
  - Revisit only when a capture with a real connected tank becomes available;
    tank detection is an optional follow-up, not a release blocker.

### Explicitly out

- Do not modify or upload ebusd CSV files.
- Do not add Quiet-mode entities from discovery dumps without a stable mapping.
- Do not treat `/next` configuration output as the default supported layout.
- Do not close #129, #101, #102, or #138 before the remaining user or fixture
  evidence is checked.

## Execution Order

1. **Stage 1, standard:** inspect #138 code path, existing BAS fixtures, and
   current runtime definitions. Define the failing write regression.
2. **Stage 2, deep:** implement #138 with native circuit resolution and fixture
   coverage. Validate focused tests before continuing.
3. **Stage 3, standard:** analyze #102's automatic-DHW dump against existing
   state fixtures. Implement only if the state signal is unambiguous.
4. **Stage 4, deep:** investigate #129 Zone 2 ownership, layouts, and absent
   paths. Keep this stage separate from #138 because both touch BAS-family
   resolution but have different evidence and failure modes.
5. **Stage 5, light:** review BazsiDev's VE 28 capture and #101 grab data when
   available. Add fixture work only for confirmed mappings.
6. **Stage 6, release gate:** run full validation, independent code review,
   independent audit, and final user-verification checks.

## Validation

- Focused regression tests for every changed register path.
- `.venv/bin/ruff check .`.
- Scoped `.venv/bin/ruff format --check` for changed Python files.
- `.venv/bin/pytest -q`.
- `python3 tools/version.py check`.
- `python3 -m compileall -f custom_components/vaillant_ebus/`.
- Independent review of final diff and counterexample audit of circuit/write
  resolution.
- Release branch, tag, changelog, CI, and user verification checked before
  merge.

## Release-Gate Cost

Use a standard independent audit for the focused #138 change. Escalate to a
deep audit if #102 or #129 changes shared state derivation, circuit ownership,
or multiple controller variants.
