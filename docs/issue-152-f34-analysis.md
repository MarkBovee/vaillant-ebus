# Issue #152 — F34 cache and entity analysis

Source: community attachment `f34_ebus_dumps.zip` from issue #152, received
2026-09-22. The complete discovery dumps are preserved as:

- `tests/fixtures/community/f34_issue152_v190_before_cleanup_discovery.yaml`
- `tests/fixtures/community/f34_issue152_v190_after_cleanup_discovery.yaml`
- `tests/fixtures/community/f34_issue152_v192_before_cleanup_discovery.yaml`
- `tests/fixtures/community/f34_issue152_v192_after_cleanup_discovery.yaml`

The captures were made on `ebusd 26.1.26.1`. The bus reports:

- address `08`: `Vaillant;BAI00;0503;9602`
- address `15`: `Vaillant;BASS3;0708;4304`
- address `52`: `Vaillant;VR_70;0109;2903`

There are no `ctlv2` or `hmu` discovery lines in the raw find output. The
discovery register set is 778 entries in all four dumps; the before/after
cleanup pairs do not remove bus registers. The stale values are in the
integration register cache, not in the current discovery graph.

## Evidence table

| Candidate | Capture evidence | Classification | Action |
|---|---|---|---|
| `ctlv2.Hc1PumpHours`, `ctlv2.Hc2PumpHours` and matching `PumpStarts` | Cache contains `24384`, `26701`, `23871`, and `26182`; current bus exposes `bass.Hc1PumpHours`/`Hc2PumpHours` and `PumpStarts` as `ERR: invalid position`. | Confirmed stale logical-circuit cache | Remove stale alias entities and values when the discovered owner is another circuit. |
| `hmu.*ElecCons*`, `hmu.CoolEnvYield*`, `hmu.SourceTempInput` | Cache contains values, but the scan has a BAI boiler and BASS3 controller and no heat-pump `hmu` discovery. | Confirmed stale/unowned cache data | Remove cache entities when no discovered heat-pump owner exists. |
| `bai.StatFuelSum*` | Cache contains `134.274`, `104.609`, and `29.665`; current discovery returns `ERR: element not found` for the three fuel registers. | Confirmed unavailable register with stale cache | Do not reuse cache for explicit no-data placeholders; keep the entity unavailable. |
| `bass.Hc1/Hc2FlowTempCalc`, humidity, dew point, pump hours and starts | Current BASS3 responses return `ERR: invalid position`; no compatible layout is present in this capture. | Discovery-only / unsupported on this hardware | Do not add a runtime mapping or fabricate values. |
| `bass.PrFuelSum*`, solar totals, cooling program registers | Current discovery returns `no data stored` or `ERR: element not found`; no live value is correlated. | Unavailable or unsupported | Leave unavailable; investigate separately only with stronger evidence. |

## Implemented boundary fix

Initial discovery now removes cache-seeded entity descriptions when their
source circuit is a stale logical alias or has no discovered owner. Explicit
placeholder registers also stop accepting cached values during fallback reads.
This keeps optional mapped registers eligible for a later live read while
preventing old values from appearing as current measurements.

The regression tests cover the F34 topology, stale `ctlv2`/`hmu` cache
entities, an unavailable `bai.StatFuelSum`, and the no-cache-backfill path for
placeholder reads. Community captures remain evidence fixtures; they are not
owner-hardware live verification.
