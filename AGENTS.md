# Vaillant eBUS Project

## Scope

- This repository contains a Home Assistant custom integration for Vaillant heat pumps.
- The integration connects directly to the local ebusd TCP interface on port `8888`; it does not use MQTT or cloud services.
- Registers and devices are discovered from ebusd at runtime. The project is intended as a drop-in replacement for `mypyllant-component`.

## Agent Workflow & Skills

- Load the matching skill with the `skill` tool before working; do not rely on AGENTS.md alone.
  - `ebusd-expert` for register reverse-engineering, `define` strings, and ebusd TCP-level debugging.
  - `home-assistant` for deploy, entity/device registry, HA API, and live HA verification.
  - `intake`, `develop`, `agent-workflows`, `verification`, `code-review`, `debugging`, `improve`, `session-review` for the risk-based lifecycle.
  - `text-writing` is mandatory before writing user-facing text, including GitHub replies,
    issue bodies, release notes, documentation, and final responses. Use simple, human
    language that non-experts can understand. Keep code, identifiers, commands, and
    technical protocol values exact; do not simplify those.
- This repository is release-sensitive. Follow the lifecycle in the global AGENTS.md "Skills & Workflow": `intake → plan → plan-check → execute → validate → review & audit → release-gate`, delegate independent research to subagents, and never self-declare release readiness.
- For protocol research, prefer the upstream search and dump mining sections below over guessing from register names.
- **Use the repository tools instead of ad-hoc commands** (details in "Developer Helper Tools"): `tools/validate.py` for every validation run, `tools/fetch_attachments.py` for issue and discussion dumps, `tools/check_translations.py` after touching `translations/`/`strings.json`, `tools/gh_reply.py` for approved GitHub replies, `tools/deploy_ha.sh` for deploys, `tools/search_upstream.sh` for upstream searches. Write a new helper into `tools/` (with tests) when a manual step is repeated a third time.

## Home Assistant Inspection

- Use the connected HA-MCP server as the primary method for inspecting the live Home Assistant instance. Start with `ha_get_overview`, `ha_search`, `ha_get_integration`, `ha_get_device`, `ha_get_logs`, and `ha_get_system_health` as appropriate.
- Inspect the `vaillant_ebus` config entry, devices, entities, diagnostics, and logs through HA-MCP before using SSH, REST, or direct storage access.
- Treat HA-MCP reads as the default verification path after code changes and deployments. Use SSH only when HA-MCP cannot expose the required detail, or for the documented deployment and registry-maintenance workflows.
- Prefer read-only HA-MCP tools for diagnosis. Do not use HA-MCP write/delete tools unless the user explicitly requests the state or registry change.

## Architecture

- `custom_components/vaillant_ebus/coordinator.py` owns connection lifecycle, discovery, polling, caching, and runtime register definitions.
- `custom_components/vaillant_ebus/backend/ebus_service.py` provides the ebusd transport and handles register reads and writes (writes are verified by read-back).
- `backend/entity_factory.py` maps the discovered graph to Home Assistant entity descriptions.
- `backend/mapping.py` contains register metadata such as names, icons, units, and limits.
- Platform modules in `custom_components/vaillant_ebus/` expose the generated entities to Home Assistant.

## Discovery And Entities

- The discovery graph is the source of truth for entity existence. Do not hardcode device types, circuit lists, or register lists in entity platforms.
- `REGISTER_MAP` supplies metadata and enabled defaults. It must not cause `EntityFactoryService` to create entities that are absent from the discovery graph.
- The coordinator may explicitly read enabled `REGISTER_MAP` entries as a fallback and must regenerate entity descriptions when that adds registers.
- `CIRCUIT_NAMES` is the only place for hardcoded circuit-to-label descriptions used by the Home Assistant UI.
- Values such as `-`, `no data stored`, and `empty` represent unavailable ebusd data. They must not be exposed as normal sensor values.
- Keep filtering for unsupported circuits, secondary zones, broadcast registers, and no-data devices consistent with the existing discovery and entity-factory logic. Do not create virtual entities for unsupported hardware.
- **Discovered-circuit resolution is mandatory.** Runtime fallback reads, runtime
  definitions, dump `REGISTER_MAP` probes, writes, and entity data lookup must
  target the circuit actually discovered on the bus. Resolve logical metadata
  aliases through the `DeviceGraph` and scan identity (for example `ctlv1`,
  `ctlv3`, `basv3`, or another controller), never by assuming `ctlv2`, `hmu`,
  `bai`, or a numeric circuit. This must work for every supported controller and
  heat-pump variant.
- **Field entries are not ebusd registers.** Mapping keys such as
  `Status01.temp`, `Status01.pumpstate`, or `Status07.displaypressure` are
  parsed fields of a parent register, not independent registers to poll or
  include in discovery dumps. Strip field suffixes before fallback reads and
  dump probes; resolve and read only parent register names.
- **No hardcoded hardware workaround for circuit aliases.** A new device or
  firmware variant must be supported by scan metadata and graph-driven alias
  resolution, with fixture coverage for the discovered circuit and absent-path
  coverage. Do not add another literal `ctlvN`, `hmu`, or `bai` fallback for one
  user's hardware.
- **A discovered node is not proof of device role.** Runtime-defined fallback
  registers can leave a stale alias node (for example a bare `ctlv2`) on a bus
  whose real controller is a different variant (`ctlv3`). Resolve the controller
  from the circuit that owns the control/DHW registers, and treat an exact node
  as authoritative only when it is that owner. An exact node must never
  short-circuit a unique, control-owning controller.
- **A register's owner is its source circuit, not the node that lists it.**
  Logical sub-devices aggregate registers under a parent (the `dhw` node owns
  `ctlv3.HwcOpMode` while the `ctlv3` node lists no `Hwc*` registers). Identify
  the owning circuit from each register's source circuit in
  `DeviceGraph.raw_registers`.
- **Never collapse "unavailable" into a default.** Sentinel/`no data stored`
  means unavailable; a valid value looked up under the wrong circuit is a
  resolution bug, not a data problem. Coercing `None` to a default hides it.
  Likewise an explicit "unset" sentinel (for example holiday reset dates) is a
  legitimate absent/false state, not `unknown`; only genuinely missing data is
  unknown.

## Runtime-Defined Registers

Some supported registers are not returned by ebusd `find` and must be defined or probed at runtime. `ctlv2.z1RoomHumidity` and `hmu.SourceTempInput` are confirmed examples, not an exhaustive list. `SourceTempInput`'s layout is verified upstream on brine units (john30/ebusd-configuration PR #565); on air/water units the B51A reply is a 3-byte stub, so the read fails and the register correctly stays unavailable.

When functionality is missing, inspect the raw `find` output, discovery dump, ebusd metadata, and unmapped registers before adding a one-off implementation. Test each candidate directly against ebusd, confirm its message format and read-back value, and add only registers supported by the connected hardware.

Keep all runtime definitions in `VaillantCoordinator._define_custom_registers()` and execute them after connecting to ebusd and before discovery. Use one data-driven collection for additional definitions instead of separate register-specific code paths.

The confirmed `z1RoomHumidity` definition is:

```text
r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800,value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity
```

Use `EbusService.define_register()` for runtime definitions. Do not replace them with CSV uploads or an addon `--configpath` override.

When changing `_fallback_read()`, preserve entity regeneration after newly readable registers are added.

When a hardware variant's upstream CSV is absent or only partially compatible,
define a minimal, evidence-backed runtime set instead of aliasing a generic CSV
(the `08.hmux0.csv -> 08.hmu.csv` symlink for HMUX0 is the documented example).
Keep the shared register families that the capture proves work, and drop only the
layouts the capture proves incompatible. Never blanket-drop a whole family, and
never copy a generic CSV wholesale.

## Climate Compatibility

Climate behavior must follow the corresponding `mypyllant` implementation.

- In `day` / manual mode, `async_set_temperature` writes `Z1DayTemp` directly.
- In time-controlled modes, it uses quick veto with `Z1QuickVetoTemp` and `Z1QuickVetoDuration`.
- If quick veto is already active in a time-controlled mode, update its temperature without writing a new duration.
- Preset mapping, HVAC modes, and climate services should remain aligned with `mypyllant`.

## ebusd Safety

- Never modify, upload, or delete ebusd addon CSV files.
- Never set the ebusd addon `--configpath`.
- Before changing integration code for a register write, test the register directly against ebusd over TCP or HTTP, verify a `done` response, and read the value back.
- Treat registers that return `ERR: element not found` or `no data stored` as unsupported or temporarily unavailable; do not fabricate values or entities.

## Discovering Registers Absent From CSV

The installed ebusd CSV files only cover what `find` returns. The bus carries more
telegrams; capture them with `grab` and mine the unknown ones for new registers.

- Live grab: `grab` → wait N seconds → `grab result all` → `grab stop`. Do **not**
  use `grab -m ...` (invalid syntax). A grab that runs while the user changes a
  setting in the myVaillant app shows the write telegram that carries the new
  register (app → cloud → NETX2 → bus).
- Unknown telegrams have no register label after the count: `.../ 09410111... = 3`.
  Labeled ones look like `... = 19: hmu SetMode`. Parse them with
  `backend/grab_parser.py` (`parse_grab_lines`, `unknown_telegrams`).
- Dumps capture them as `unknown_telegrams` (and `labeled_telegrams`) next to the
  raw `grab` lines. When a dump exists, prefer mining its `unknown_telegrams` over
  a fresh grab.
- Register candidates found this way must have message format and layout evidence
  before adding a `define -r` to `_define_custom_registers()`; owner hardware live
  verification is preferred but not mandatory when upstream/community evidence is
  strong and the hardware scope is explicit.
- A register with a strong upstream/community layout match may be added through
  `_define_custom_registers()` even when the installed ebusd CSV does not expose it.
  This is the preferred path for community-supported opt-in registers; never modify
  or upload addon CSV files. The definition must hardcode the verified circuit/address
  and message layout, be additive, and tolerate an absent or `ERR` response without
  creating a normal entity.
- Before adding a runtime definition, confirm all of the following: the evidence
  telegram master/slave and message/sub-address match the candidate; the response
  byte length and field offsets match; the value has plausible units/range; hardware
  and firmware scope is explicit; and the definition does not introduce active polling
  that can alter bus behaviour unless active reads are explicitly required and safe.
  Prefer passive `u` definitions for passively observed telegrams. Add the definition
  only after a fixture-backed test covers both the decoded value and absent-register
  path.
- **Live verification applies only to the owner's own hardware.** A single grab on the
  owner's own bus can be tested live. Data that comes from others (dumps, gists, issue
  snippets, upstream threads) can **never** be tested live — treat it as community data
  (see "Community Data" below), not as owner-live verification.
- During dump analysis, search every useful unknown telegram and unmapped live register
  in `john30/ebusd-configuration` issues and pull requests before classifying it as
  unsupported. Search by register name, message ID, sub-address, and distinctive payload
  fragments where useful. Use `tools/search_upstream.sh`, including `--comments` and
  `--all` when appropriate; do not limit the search to the repository's CSV/TSP files.
- **Unknown-telegram investigation is mandatory, not optional.** For every unknown
  telegram that is relevant to the user request, create a candidate row before drawing
  a conclusion. At minimum record: local dump(s), master, slave, message ID, sub-address,
  request bytes, response length, response bytes, observed state(s), and occurrence
  count. Deduplicate identical `(slave, message ID, sub-address)` candidates, but retain
  state-specific payloads and counts.
- Search each candidate systematically, not only by a guessed register name. Run
  `tools/search_upstream.sh --comments --all` for: the complete message ID (`b511`),
  message ID plus sub-address (`b511 0101`), request/payload fragments with and without
  spaces, slave/device identifiers (`HMUX0`, `HW0504`), and any candidate name found in
  search results. Also search relevant hardware terms and feature terms separately (for
  example `Quiet mode`, `NoiseReduction`, `DeicingActive`). A zero-result search is
  evidence only for that query, never proof that no mapping exists.
- Search result handling must survive GitHub search rate limits. Cache command output,
  reduce parallel requests, wait and retry when GitHub returns HTTP 403, and use direct
  `gh issue view <number> --comments` / `gh pr view <number> --comments` for promising
  threads. If search remains blocked, report the blocked queries and do not classify the
  candidate as unsupported solely because of the failure.
- Inspect every promising issue and PR in full, including comments. Extract exact CSV,
  TSP, `define -r`, message/sub-address, field layout, hardware, firmware, and live-test
  evidence. Then compare those fields with the local candidate byte-for-byte: master/slave,
  message ID, sub-address, response length, field offsets, encoding, and plausible values.
- Before concluding that no mapping exists, explicitly report the candidate inventory,
  all upstream query variants attempted, matching threads (or confirmed no matches), and
  why each candidate is `confirmed`, `strong assumption`, `speculative`, or remains
  `discovery-only`. Never summarize this as merely “no unknown registers found” when the
  dump contains unknown telegrams.
- Treat upstream matches as evidence, not local live verification. Upstream/community
  evidence is sufficient for production when classified `confirmed` or `strong
  assumption`, hardware scope is explicit, and absent-register behavior is safe. Do not
  require owner-hardware live verification or wait for 100% certainty once those gates
  are met; treat the mapping as an in-scope production candidate. Open
  promising issues or PRs
  with `gh issue view <number> --comments` and read the complete conversation before using
  a snippet. Record the upstream URL, hardware context, and whether the mapping is
  `confirmed`, `strong assumption`, or `speculative`.
- For a local live dump, correlate upstream candidates against the local telegram's master,
  slave, message ID, sub-address, response layout, and observed value. A name match alone
  is insufficient for production code.
- Add the relevant upstream evidence and local capture as fixture-backed analysis notes when
  a candidate moves toward production. Keep candidates without a matching layout or safe
  absent-register behavior discovery-only until evidence improves.

## Upstream Issues/PRs as a Register Source

The shipped CSVs in `john30/ebusd-configuration` and the compiled CDN copies run far
behind the bus (see `john30/ebusd-configuration#632`). Do **not** expect unknown
register definitions, field layouts, or message IDs to exist in the `.tsp`/CSV source.
The working knowledge lives in that repo's **issues and pull requests** — people post
CSV snippets, `define` strings, `find` output, and per-hardware field layouts there.

- Search issues and PRs with `tools/search_upstream.sh`, which wraps `gh search`
  against `john30/ebusd-configuration`:
  - `tools/search_upstream.sh "PrEnergySum"` — issues matching title/body.
  - `tools/search_upstream.sh --comments "YieldHwcDay"` — also match comment bodies
    (most CSV snippets and layouts are pasted in comments).
  - `tools/search_upstream.sh --all "SourceTempInput"` — issues and PRs.
  - `tools/search_upstream.sh "query" "john30/ebusd"` — search another repo.
  - Add `--compact` when passing search output into agent context; it keeps
    issue/PR markers while omitting decorative headings and blank separators.
- The ebusd-configuration repo has discussions **disabled**; search issues and PRs only.
- When a promising thread is found, open it (`gh issue view <n> --comments`) and read
  the full conversation before trusting a snippet. Prefer definitions that the reporter
  verified against a live device.
- Never modify or upload ebusd CSV files and never set `--configpath`; that is addon-side.

## Community Data (user/upstream dumps)

Data from users and upstream threads (discovery dumps, gists, `find` output, CSV or
`define` snippets) can **never** be live-tested — the hardware is not ours. Strong
evidence from captures may still justify a conservative production assumption when
that assumption is isolated, fixture-covered, and safe when the register is absent
or returns no data.

### Strong-assumption production rule

`Strong assumption` is a production-evidence class, not a reason to defer work until
someone supplies perfect or owner-hardware proof. Implement a strong-assumption mapping
when the available community/upstream evidence consistently establishes the message
family, layout or value semantics, hardware scope, and safe absent path. Hardware-gate
it, preserve complete source fixtures, add positive and absent-path regressions, and
record the uncertainty. Defer only when evidence conflicts, cannot be scoped to
hardware/firmware, lacks a safe failure mode, or remains merely `speculative`.

When adding registers, devices, or metadata derived from community data:

- Add the capture as a fixture under `tests/fixtures/community/` and drive the new code
  from that fixture (see "Test Fixtures"). The fixture replaces live verification as the
  correctness gate.
- Classify each inferred mapping as `confirmed`, `strong assumption`, or `speculative`.
  `Confirmed` means the register name and value/layout are explicit. `Strong assumption`
  means multiple consistent observations or a clear before/after correlation supports the
  mapping. `Speculative` means evidence is insufficient for production code.
- Add the entity/register through the existing data-driven paths (`REGISTER_MAP`,
  `MULTI_FIELD_FIELDS`, `_define_custom_registers()`, device-type tables) so it is
  covered by the same discovery/entity-factory logic as everything else. Do not bolt on
  one-off register-specific code paths.
- `Confirmed` and `strong assumption` mappings must be considered for production through
  those existing data-driven paths; do not silently defer them for missing live proof.
  Document the evidence and keep inferred entities unavailable unless the expected
  register/value is actually discovered.
- A reasonable, fixture-backed assumption may also enter production when the exact telegram
  family, message/sub-address, response shape, field layout, and hardware scope match
  available community or upstream evidence. Classify it explicitly as a reasonable
  assumption, keep the implementation hardware-gated, and preserve a safe absent-register
  path. A register-name match, plausible value, or uncorrelated telegram is not enough.
- Keep changes additive and opt-in: enabling a community register/device must not change
  behavior for hardware that does not expose it, and must not crash discovery or entity
  generation when the register is absent.
- Prefer conservative metadata: map layouts and read-back values explicit in the capture;
  for strong assumptions, document the evidence and do not fabricate a field layout from
  an isolated or contradictory snippet.
- Add a regression test that loads the fixture and asserts the expected register/entity
  appears on the discovered device graph without error.
- For inferred mappings, also assert that the absent-register path remains safe.
- If the data is incomplete or ambiguous, prefer a discovery-only or YAML-override
  approach until evidence reaches `strong assumption`, and flag the uncertainty to the
  owner rather than presenting it as verified hardware behavior.

## ebusd Define And Polling Rules

Hard-won facts from the 1.10.x line. Read these before touching `_define_custom_registers()` or `_fallback_read()`.

- **An ebusd `define` id never contains the length byte.** For the telegram `f108b509 05 5402005b0d` the
  definition id is `5402005b0d` (the `05` is NN). Ids that start with NN (`055402...`, `021802`) can never match a
  telegram and the register stays `unknown`/unavailable with no error. The B51A ids (`05ff3546`) are correct because
  the `05` there is data after NN=04. Rebuild the request as `f1{zz}{pbsb}{len(id)//2:02x}{id}` and assert it is in the
  capture's `unknown_telegrams`/`labeled_telegrams` (see `test_issue161_passive_definition_ids_match_captured_requests`).
- **Plain `r` messages are not polled by ebusd.** `find -a` only lists the cached value. A register whose key is already
  in `find` is skipped by the map-driven pass of `_fallback_read` (it only reads keys not yet in the graph), so a plain-`r`
  register that must follow the device needs an explicit read. The HMUX0 precise temperatures
  (`RunDataFlowTemp`, `RunDataReturnTemp`) have that explicit block; the v1.10.3 regression (#171) was a gate that
  stopped it for SW0406. `RunDataReturnTemp` was historically read only through the `hmu.` alias map key.
- **Passive `u` definitions** decode traffic the owner's myVaillant gateway (`f1`) already generates. Prefer them for
  telegrams seen in captures; they cost no bus traffic, so they stay unavailable until the gateway sends the frame.
- **Firmware gates are explicit.** `hmux0_precise_temperature_owner` admits only a complete, unique HMUX0 scan with
  HW0504 and SW0303 or SW0406. SW0407 has its own blocklist/passive set; SW0302 and unknown revisions returned absurd
  values in #99. Add a revision only with a capture, a plausibility check and a gate test.
- **Runtime definitions vs the pruning pass.** After `define`, ebusd can list the register as `no data stored` until
  the next read or telegram. `_apply_discovery_graph` must not prune or disable entities of registers the integration
  defined itself (`runtime_defined_key_folds`); it still clears their raw value so a sentinel is never shown as data.
- **Cache seeding generates entities from cached values** (`_async_seed_entities_from_cache`). A rule that hides
  entities must therefore live in `EntityFactoryService.generate`, not only in the live path.
- **Wrong-circuit labels.** A cache-only `z<N>`/`hc<N>` register whose live twin sits under another circuit is a stale
  label and is pruned (`_cache_register_is_supported`).

## Entity Rules Added In 1.10.5

- A heating circuit whose controller reports `Hc<N>CircuitType = inactive` creates no `Hc<N>*` entities, except the
  circuit-type sensor itself. A missing or unreadable type (the F34 `Hc1CircuitType` returns an error) never hides a
  circuit. A YAML override with `enabled: true` still wins.
- Counters of unproven unit are exposed as raw diagnostic counters without `kWh`/`energy`
  (`bai.PrEnergySumHc1/Hwc1`, #152). Do not claim a unit the evidence does not give.
- Strong-assumption passive registers ship disabled by default and unavailable without data
  (`PowerConsumptionHmu`, `CompressorHc/Hwc`, `HeaterYieldHwcTotal`).
- `repairs.py` is a Home Assistant repairs platform; it must keep `async_create_fix_flow` or HA logs
  `Invalid repairs platform`.

## Known Hardware Notes

- HMUX0 firmware seen: SW0302, SW0303, SW0406, SW0407 (all HW0504). SW0303 needs the runtime `define` for
  `RunDataFlowTemp`/`RunDataReturnTemp`; SW0406 gets them from ebusd's own CSV; SW0407 uses passive definitions.
- VWZIO SW0500/HW0504: passive `B516/14` power, `B511/1802` heater runtime/starts, `B516 1000ffff49040000` heater DHW
  heat total (strong assumption, source `0x49` is not named upstream).
- HMUX0 SW0407 compressor counters: `B511` data `1801` heating and `1802` DHW; `1803` is zero in all captures
  (discovery-only).
- Quiet mode (`B508/0209`) is **not** mapped: no capture contains both `00` and `01` in order, and the 2026-09-17
  capture contradicts the quiet=01 theory. Revisit only with one timestamped grab that shows both states.
- An E7000 system manager (`scan.15`, for example Bulex MiPro) has no ebusd configuration in the `next` tree (upstream
  `john30/ebusd-configuration` PR #623), so no zone or climate entities can exist. This is not an integration bug.
- The owner's own system is HMU00/flexoTHERM + CTLV2 + VWZ00. It cannot exercise HMUX0 or VWZIO code paths; those rest
  on community fixtures.

## Developer Helper Tools

| Tool | Use |
| --- | --- |
| `tools/validate.py` | CI parity in one command, with the Windows known-failure baseline. |
| `tools/check_translations.py` | hassfest translation rules (a fixable repair has `fix_flow`, never a `description`). |
| `tools/fetch_attachments.py` | Download issue/discussion attachments to a scratch directory, refuse `tests/fixtures`, flag duplicates of existing fixtures. |
| `tools/gh_reply.py` | Post a reply from a Markdown file to an issue or discussion thread and update `.gh-inbox-state.json`. Only after the owner approved the text. |
| `tools/deploy_ha.sh` | Validate and deploy to the owner's Home Assistant (see below). |
| `tools/search_upstream.sh`, `tools/compare_dumps.py`, `tools/dump_projection.py`, `tools/version.py` | Upstream search, dump diff, dump projection, version consistency. |

Shell notes for agents: on Windows with Git Bash, never pass multi-line Python with backslashes, quotes or `$` through an
inline heredoc. Write a script file (a scratch directory is fine) and run it. Check `git status` before and after bulk
downloads. Foreground `sleep` is blocked; wait for CI with the PR status tool, not with a polling loop.

## Known Limitations

- Many heat-pump registers return `no data stored` while the compressor is idle.
- Register classification is inferred from discovery and metadata; YAML overrides may be needed for uncommon registers.
- Some useful registers may require runtime definitions before they can be discovered.

## Test Fixtures

- ebusd `find` output and discovery dumps are captured as fixtures in `tests/fixtures/`. There is no `data-dump/` directory anymore; all community and local captures live in `tests/fixtures/`.
- `tests/fixtures/community/` holds third-party captures: discovery-dump YAML files (`flexotherm_discovery.yaml`, `arotherm_plus_2zone_discovery.yaml`, `arotherm_plus_basv3_discovery.yaml`, `arotherm_pro7_discovery.yaml`, `geniaset_bass3_discovery.yaml`, `saunier_duval_f34_issue129_discovery.yaml`) and plain `find` output (`basv_find.txt`, `v32_find.txt`, `flexocompact_find.txt`, `dumpvalues.yaml`).
- The fixture trust model and full inventory live in `docs/test-audit-rc3.md`. Classify every fixture as GOLDEN, REDUCED-FAITHFUL, SYNTHETIC, or LEGACY/UNKNOWN; never use a reduced or unknown-provenance fixture as the sole evidence for discovery, circuit ownership, or graph resolution.
- `tests/test_fixture_integrity.py` guards the golden captures: it fails if the issue #99 dumps lose the spurious `ctlv2` records or a discovery dump loses provenance metadata. Do not weaken it to accommodate a stripped fixture.
- `dumpvalues.yaml` records multi-field register field names and is the reference for `MULTI_FIELD_MAP` in `tests/fake_ebusd.py`. Keep the two in sync.
- Load fixtures in tests with `load_find_lines("community/<name>")` for `find` output and `load_discovery_dump("community/<name>")` for discovery-dump YAML; both live in `tests/fake_ebusd.py`. Discovery-dump YAML fixtures need `pyyaml` (installed in CI).
- Open GitHub issues may reference specific community dumps. When investigating an issue, load the matching fixture and confirm the register behavior on the discovered device graph before changing production code.
- New community captures should be added under `tests/fixtures/community/` as discovery-dump YAML (preferred, keeps metadata and `raw_find_lines`) with a fixture-load test, never as a separate `data-dump/` folder.
- **Fixtures are the correctness gate for community data.** A fixture-driven regression test replaces live ebusd verification for anything derived from user/upstream captures. Prefer this over asking for live access; only the owner's own hardware can ever be live-verified.
- **Do not hand-trim a capture to "relevant" records.** Stripping apparently
  unrelated entries can mask the bug: an issue #99 resolution regression only
  reproduces because the real dump still carries the stale alias records. Keep
  every raw `find` line the capture provides.
- A discovery dump can carry both pre- and post-definition `find` output. Use the
  post-definition lines (`load_find_lines(name, after=True)`) when a test asserts
  the effective runtime state after the integration's `define` pass, and the raw
  lines when it asserts the initial discovery state.
- A regression test for reported invalid values should assert both rejection
  (out-of-range/absurd decode becomes unavailable) and preservation (a plausible
  value stays available); reject only the specific field, never clamp or
  transform.

## Validation

`python tools/validate.py` runs everything CI runs (ruff, scoped format, `mypy --strict`, version, translation
rules, YAML, compileall, `git diff --check`, pytest) and, on Windows, compares failing tests with
`tools/known_env_failures.txt` so only new failures fail the run. Use `--quick` to skip pytest and `-k expr` to
narrow it. The individual commands below remain the reference.

Use the repository virtualenv: `.venv/bin/<tool>` on Linux/macOS, `.venv/Scripts/<tool>` on Windows. Create it with
`python -m venv .venv && .venv/Scripts/python -m pip install pytest pytest-asyncio pyyaml voluptuous ruff paramiko`
(`paramiko` is only for `tools/deploy_ha.py`).

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check custom_components/vaillant_ebus/backend/grab_parser.py custom_components/vaillant_ebus/backend/dump_analysis.py custom_components/vaillant_ebus/backend/discovery_service.py custom_components/vaillant_ebus/backend/models.py custom_components/vaillant_ebus/backend/ebus_service.py custom_components/vaillant_ebus/backend/entity_factory.py custom_components/vaillant_ebus/backend/mapping.py custom_components/vaillant_ebus/coordinator.py custom_components/vaillant_ebus/dump_service.py
.venv/bin/pytest -q
python3 tools/version.py check
python3 -m compileall -f custom_components/vaillant_ebus/
```

- The line limit is 120 characters (`ruff` E501), comments included. Every function and test needs an `# Intent:` and a
  `# Why:` comment above it.
- `tools/known_env_failures.txt` is empty: the timer-resolution test that used to fail on Windows was removed in
  1.12.0. `.gitattributes` keeps `tests/fixtures/**` byte-exact (`-text`), so the fixture
  digests match without CRLF changes; `tests/test_search_upstream.py` needs `jq` and is skipped without it. A clone made
  before `.gitattributes` existed needs its fixtures re-checked out (delete the CRLF files, then `git checkout -- tests/fixtures`).
  Record the baseline before a change and compare; do not "fix" failures by editing fixtures.

## Home Assistant Release Smoke Test

Every release candidate must exercise the discovery-dump service on the owner's
Home Assistant server after deployment; a successful startup or unit test alone
does not cover this service.

1. Deploy the candidate with `tools/deploy_ha.sh` after repository validation passes (see "Deploying To The
   Owner's Home Assistant" below), then restart Home Assistant with the HA-MCP `ha_restart` tool. Do not
   substitute an ad-hoc SSH/SMB deployment.
2. Through HA-MCP, confirm the `vaillant_ebus` entry is loaded. Call
   `vaillant_ebus.export_discovery_dump` once with `grab_duration: 0`, then
   again with a short positive duration such as one second. Do not run external
   `grab`/`grab stop` commands or restart ebusd during the positive-duration
   call; the protocol has no session ID to protect against those races.
   Run only one export per ebusd endpoint at a time, including across separate
   Home Assistant instances.
3. Read both newly written files from the paths in the service log/notification.
   Use an HA-MCP file-read tool when available; use the documented read-only SSH
   path only if HA-MCP cannot expose the file.
4. Parse both files as YAML and verify `metadata`, `raw_find_lines`,
   `before_registers`, and `registers`. For the zero-second dump, require
   `grab_status: not_requested` and `grab_captured_duration: 0`. On the owner's
   current ebusd version, the positive-duration dump should report
   `grab_status: continued`, `grab_capture_method: count_delta`, and a positive
   `grab_captured_duration` plus `grab_capture_limitation`; older ebusd versions
   may report an owned `captured` session instead. The continued capture keeps
   only the last payload for each message key and cannot detect an external grab
   stop/restart during its interval, so do not claim it preserves every state
   transition. If the positive-duration dump reports `skipped_active` because `grab result all` exceeded the line
   limit (`GRAB_MAX_RESPONSE_LINES`, 100,000 since 1.10.5), record it as a deviation: the service degraded to a
   register-only dump as designed, but the `continued` criterion is not met.
5. After the positive-duration call, use the documented read-only ebusd command
   `grab result all` through SSH and confirm the response is not `grab disabled`.
   Do not use `grab` as a status probe because it can start capture and hide a
   stopped state.
6. Check fresh HA logs for errors from `custom_components.vaillant_ebus` and
   record the service results and both dump paths in the release plan. A service
   error, missing file, invalid YAML, or missing required section fails the
   smoke test.

## Release Versioning

- The release version must stay identical across `pyproject.toml`, `custom_components/vaillant_ebus/manifest.json`, and the top `## <version>` heading in `CHANGELOG.md`.
- `tools/version.py` is the single source of truth. Bump with `python tools/version.py bump X.Y.Z`, then add the matching `## X.Y.Z - YYYY-MM-DD` CHANGELOG section (release notes are human-written).
- `tests/test_version_consistency.py` runs `python tools/version.py check`, so CI fails on drift. Never hand-edit one version file without updating the other two.
- Publishing a release means pushing the release branch and an annotated `v*` tag; the CI `release` job builds the zip and creates or updates the GitHub release from the top CHANGELOG section. Do not merge the release branch until it has been tested on Home Assistant.

## Deploying To The Owner's Home Assistant

- `tools/deploy_ha.sh` validates (`tools/validate.py`), then runs `tools/deploy_ha.py` (paramiko; `pip install paramiko`).
  Credentials come only from the git-ignored `.env` (`HA_HOST`, `HA_SSH_USER`, `HA_SSH_PASSWORD`; see `.env.example`).
  Never print, grep for, or commit credentials. Never read the Supervisor token to work around a blocked command.
- The HA OS SSH add-on has **no SFTP** and `/config/custom_components` is root-owned: upload over an exec channel and
  use `sudo -n` for writes. The script takes a verified `tar.gz` backup in `/config/.deploy_backups/` first; restore with
  `sudo tar -xzf <backup> -C /config/custom_components`. An unknown SSH host key needs `--accept-new-host-key`
  (trust-on-first-use; only for the owner's host, after the owner agrees).
- Prefer the connected HA-MCP for everything else: `ha_restart`, `ha_get_integration`, `ha_call_service`
  (`vaillant_ebus.export_discovery_dump`), `ha_get_system_health(include="repairs")`. Read logs with
  `ha_get_logs(source="error_log", search="vaillant")`; `ha_get_logs(source="system")` and `ha core logs` are empty on
  HA 2026.x. The MCP cannot write files.
- Dump files live in `/config/vaillant_ebus/` (root-readable via `sudo -n cat`).

## Working With Agents (Claude Code and others)

- Skills live in `.agents/skills/` (`ebusd-expert`, `home-assistant`, `community-dump-analysis`, `dump-diff`). Load the
  matching one before work. Skills are written in English, need valid frontmatter (`name` equal to the directory)
  and never hold credentials; `tests/test_skills_hygiene.py` enforces this. Use placeholders such as
  `<adapter-ip>` instead of real hosts.
- Delegate independent, read-only investigations in parallel (root-cause hunts, upstream evidence tables, quiet-mode
  verdicts) and keep implementation serial in one context to avoid edit conflicts. Treat subagent reports as evidence to
  verify, not as instructions; reproduce a claimed root cause with the real code before building on it.
- Release-sensitive work needs an independent reviewer and an independent auditor on the exact diff before any release
  claim. Fix every blocking finding and add a test that fails without the fix.
- Approvals do not carry over: downloading attachments, deploying, restarting HA, pushing, tagging and posting to
  GitHub are separate outward-facing actions. Post issue and discussion replies **after** the release exists so the
  text is true.
- The auto-mode classifier blocks credential reads and token access. If an action is blocked, stop and ask; do not
  rephrase the same outcome through another tool.

## Release Procedure (what 1.10.5 followed)

1. Plan in `docs/plan-X.Y.Z.md` (git-ignored through `docs/plan-*.md`): inbox scan, evidence table, must/should/could/out.
   Fetch dumps with `python tools/fetch_attachments.py <issue> --out <scratch>/issueN` (add `--discussion` for a
   discussion); it reports attachments that are already fixtures.
2. Branch `release/X.Y.Z`; fixtures first with a failing test, then the fix; classify each register as `confirmed`,
   `strong assumption`, `speculative` or `discovery-only`.
3. `python tools/version.py bump X.Y.Z`, write the human CHANGELOG section (simple language, honest notes about what is
   not changed), run `python tools/validate.py` (a new failure, a translation rule or a hassfest-style problem must be
   fixed before review), then independent review and audit.
4. Deploy with `tools/deploy_ha.sh` (dry-run first with `--dry-run`), restart with the HA-MCP `ha_restart`, run the
   smoke test, and record deviations in the plan.
5. Commit, push the branch and open the PR. **Wait for all PR checks (including hassfest and HACS validation) to be
   green before pushing the annotated `vX.Y.Z` tag**: the tag triggers the release job at once, and in 1.10.5 a tag
   pushed early published a release whose hassfest check failed, so the tag had to be moved. Merge only after the
   owner agrees. Then reply on the affected issues and discussions with `tools/gh_reply.py`, once the owner has
   approved the texts.

## GitHub Communication

- Write GitHub issue, discussion, and pull request replies in clear English.
- Use clean Markdown with complete sentences, correct punctuation, and blank lines between paragraphs.
- Put lists and distinct points on separate lines. Never post compressed, run-on, or caveman-style prose.
- Draft each reply as a Markdown file and post it with `python tools/gh_reply.py issue|discussion <n> <file>`
  (`--dry-run` first). The tool replies under the thread root for discussions and marks the item in
  `.gh-inbox-state.json`. Post only after the owner approved the text, and after the release it announces exists.
