# Release 1.9.5 — Candidate Matrix

This matrix is the implementation boundary for `docs/plan-1.9.5.md`. A row
cannot enter production work without a complete protocol layout, an explicit
polling mode, a scan gate, and a positive/absent test plan.

| Candidate | Evidence class | Protocol/layout evidence | Hardware gate | Polling decision | 1.9.5 scope | Trigger or reason |
|---|---|---|---|---|---|---|
| `RunDataElPowerConsumption` | Strong assumption for target variant | B509 `5402005b0d`; upstream `EXP`, `W`; #32 request/response matches exactly | HMUX0 `SW0302`/`SW0303`, `HW0504` | Active `r`; upstream identifies B509 as the monitoring/diagnostic block intended for regular polling | Must candidate | Positive SW0302 fixture decode plus absent path |
| `RunDataCompressorSpeed` | Strong assumption for observed target frame | B509 `5402000d0a`; upstream `EXP`, `rps`; #32 response matches exactly | HMUX0 `SW0302`/`SW0303`, `HW0504` | Active `r` in the B509 monitoring block | Must candidate | Positive/absent fixture assertions |
| `RunDataBuildingCPumpPower` | Strong assumption for observed target frame | B509 `540200c509`; upstream `EXP`, `%`; #32 response matches exactly | HMUX0 `SW0302`/`SW0303`, `HW0504` | Active `r` in the B509 monitoring block | Must candidate | Positive/absent fixture assertions |
| B516 `0114` on HMUX0/VWZIO | Discovery-only | Exact #32 rows exist on slaves `08` and `76`, but circuit-specific semantics differ and the target VWZIO is HW0504 | HMUX0/VWZIO target scope | Do not poll | Out for 1.9.5 | Exact target-circuit semantics and safe layout evidence |
| B516 `081000ffff49050000` | Discovery-only | Exact HMUX0 row exists in #32, but no requested feature mapping or unit semantics is established | HMUX0 `SW0302/HW0504` | Do not poll | Out for 1.9.5 | Feature correlation plus exact upstream layout |
| `RunStatsBuildingPumpHours` | Strong assumption for observed ID | B509 `540200c40b`; upstream `hoursum2` | HMUX0 `SW0302`/`SW0303`, `HW0504` | Runtime `hoursum2` type is not validated in this integration's runtime-define path | Could, deferred | Add runtime datatype support and decode tests first |
| `RunStatsBuildingCPumpStarts` | Strong assumption for observed ID | B509 `540200c50b`; upstream `cntstarts2` | HMUX0 `SW0302`/`SW0303`, `HW0504` | Runtime `cntstarts2` type is not validated in this integration's runtime-define path | Could, deferred | Add runtime datatype support and decode tests first |
| `RunStatsFan1Hours` | Strong assumption for observed ID | B509 `540200d70b`; upstream `hoursum2` | HMUX0 `SW0302`/`SW0303`, `HW0504` | Runtime `hoursum2` type is not validated in this integration's runtime-define path | Could, deferred | Add runtime datatype support and decode tests first |
| `RunStatsFan1Starts` | Strong assumption for observed ID | B509 `540200d80b`; upstream `cntstarts2` | HMUX0 `SW0302`/`SW0303`, `HW0504` | Runtime `cntstarts2` type is not validated in this integration's runtime-define path | Could, deferred | Add runtime datatype support and decode tests first |
| Other observed B509 rows | Discovery-only or insufficiently correlated | Exact telegram rows exist, but no complete name/layout/unit mapping in the research handoff | HMUX0/VWZIO target scope | Do not poll | Out for 1.9.5 | Add only after individual byte-for-byte mapping evidence |
| HMUX0 `YieldHc*`/`YieldHwc*` | Strong assumption, target B51A traffic absent | B51A `05ff3200/02/0e/10/12/16`; `UIN`/10 or energy layouts from upstream | HMUX0 `SW0302`/`SW0303`, `HW0504` | Active polling safety unresolved | Could, deferred | Target capture or explicit safe polling evidence |
| HMUX0 current B51A power/yield | Strong assumption on related variants | B51A `05ff3223/3224`; `SCH`/10 from upstream | Exact target variant not proven | Active polling safety unresolved | Could, deferred | Target capture with active/idle correlation |
| VWZIO immersion metrics | Confirmed/strong assumption on HW5103 only | B51A `05ff3246/3249/324a/324c` | #32 is `HW0504`, not HW5103 | Do not poll | Out for 1.9.5 | Matching HW0504 traffic and layout evidence |
| `Hc1RoomTempModulation` | Strong assumption for VRC720 family | B524 `020002001500`, `rcmode2`; target CTLV3 response absent | CTLV3 `SW0808`/`HW8004` | Read/write safety unresolved | Could, deferred | Target read/write capture; do not alias `Hc1RoomTempSwitchOn` |
| `HwcLegionellaDay/Time` | Confirmed VRC720 / strong target-family assumption | B524 `0x2a`/`0x2b`; `HTI`/`daysel3` | CTLV3 target gate | Write safety unresolved | Could, deferred | Direct target write/read-back evidence |
| BAI `FlowTempDesired` write | Strong negative SW0107; unknown SW0108 | B509 read `0d3900`; tested write `0e3900` ineffective on SW0107 | BAI firmware-specific | Do not write | Out | Positive forced-read/state-transition evidence |
| #152 remaining energy entities | Unknown post-purge state | No new register layout; release behavior already fixed in v1.9.4 | F34 BAI00/BASS3/VR_70 | Not a runtime-definition task | Out | User purge result with registry/source-circuit evidence |

## Matrix rules

- `Active r` means the integration may issue a read; it is not passive merely
  because a community capture contains the same frame.
- `Update-only` is not used until the transport and discovery path prove that
  an update-only definition can populate and retain the entity without a
  fallback read.
- A multi-field parent must be mapped before any parsed field is exposed. Field
  names are never independent polling candidates.
- Existing `SetModeOverride` remains unchanged compatibility behavior. This
  release adds no new BAI write and makes no new claim about its effectiveness.
