# Live Dump Analysis: 2026-09-09

Source: local Home Assistant export `discovery_dump_2026-09-09_102624.yaml`, captured from the owner's bus with a five-second grab. The source dump is retained outside the repository because it contains live installation data; the relevant capture remains available in the deployment workspace for analysis.

## Strong Assumption: VWZIO Status01

Local unknown telegram:

```text
request: 1076b5110101
response: 092e2dfb0fff4c0000ff
master: 10
slave: 76
message: b511
sub-address: 0101
```

Upstream evidence:

- `john30/ebusd-configuration#598`, PR: https://github.com/john30/ebusd-configuration/pull/598
- The PR documents `b511 01` as `Status01` for VWZIO and gives the layout:
  flow temperature, unavailable return field, outside temperature, unavailable DHW field, storage temperature, pump state, and trailing padding.

Correlation:

- Local response has the same slave (`0x76`), message (`b511`), sub-address (`0101`), and nine-byte response shape.
- `0x2e` decodes as 46 °C flow using D1C.
- `0xfb0f` decodes as approximately 15.98 °C outside using D2B/256, matching local `Broadcast.Outsidetemp`.
- `0x4c` decodes as 76 °C storage using D1C.
- `0x00` matches pump off and final `0xff` matches the documented trailing padding.

Classification: `strong assumption`.

This is not yet a production entity mapping because the local ebusd configuration exposes the device under numeric circuit `76`, and the integration intentionally suppresses raw address circuits. The mapping should become production-ready only when the VWZIO circuit is exposed with a stable configured circuit name or when a safe scan-type-to-logical-circuit path is added and fixture-covered.

## Upstream Lead: VWZIO DHW Status

Upstream PR #598 also documents passive `b512 0f` as a unified VWZIO DHW status message (`StatusDhw`) with DHW temperature, supply temperature, pressure, and status fields. The local five-second dump contains unknown `b512` traffic, but not the exact `b512 0f` payload required to validate that layout on this bus. Keep discovery-only until a matching local response is captured.

## Discovery-only Candidates

- `76.VWZ_Status01b = 46`: likely an address-specific duplicate/status helper, but no upstream match for this exact name. Do not map from name alone.
- `ctlv2.YieldTotal = 29577`: plausible aggregate yield, but no local field/layout evidence tying it to the desired energy semantics. Search upstream issue #269 before mapping.
- `hmu.HcEnvYieldDay` and `hmu.HcEnvYieldTotal`: upstream energy-statistics discussions exist, but local names do not match a confirmed existing metadata entry. Do not alias until layout/unit semantics are correlated.
- Unknown `b504`, `b507`, `b511`, `b512`, and `b513` telegrams: no matching upstream issue/PR with a local layout correlation was found in this pass. Keep grouped in dump traffic for future captures.

## Quiet Mode Follow-up

Upstream PR #614 documents a useful Quiet-mode signal: `display_b5_noisereduction`
inside HMU `Status07` (`b511 07`) for `08.hmu.HW5103`:

- PR: https://github.com/john30/ebusd-configuration/pull/614
- Consolidation PR: https://github.com/john30/ebusd-configuration/pull/660
- The same `Status07` bit is described as `display_b5_noisereduction` and is
  correlated with Quiet mode in the upstream HW5103 work.

The three local Quiet captures do not contain a `b511 07` telegram. Their scan
identity is `HMUX0;SW=0406;HW=0504`, not `HMU00;...;HW=5103`, so the upstream
layout cannot be applied to this installation. The changing `b511 01` values
between Quiet on/off captures are general flow/outside/status data and do not
isolate Quiet mode.

Classification: upstream `confirmed` for HW5103, local hardware `speculative`.
Keep Quiet mode discovery-only for HMUX0 HW0504 until a local `b511 07` capture
or a matching upstream layout for that hardware is available. Do not actively
poll or define `Status07` on this bus without first confirming that the slave
supports the message and that the read is safe.

## Method Notes

- Unknown telegrams were searched by register/message name, message ID, sub-address, and payload fragments with `tools/search_upstream.sh --comments --all`.
- Promising upstream PRs were read in full with `gh pr view <number> --comments`.
- Upstream evidence is not treated as live verification; only the local capture establishes the local response correlation.
- No CSV, `--configpath`, or runtime register definition was changed from this analysis.
