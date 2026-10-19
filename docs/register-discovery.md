# Register discovery and community data

Moved from AGENTS.md. The short hard rules stay in AGENTS.md.

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
