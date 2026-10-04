---
name: community-dump-analysis
description: "Analyze a discovery dump from a user/community (GitHub issue, discussion) or from the local HA installation for register and feature research on Vaillant eBUS. Use for: dumps that come from issues/discussions, unknown-telegram analysis, designing a new register or sensor from a capture, \"what is in this dump\", a user asking for support with a dump. Do not use for: loose ebusctl commands (see ebusd-expert), comparing two local dumps (see dump-diff), or writing production code without an evidence table."
license: MIT
metadata:
  author: Mark Bovee
  version: "1.0"
---

# Community Dump Analysis

Find, load and dissect discovery dumps to back register/feature claims with evidence. This is the workflow that was used for the deep research around issues #99/#102/#109/#111.

## Role

You are the analysis hub for Vaillant eBUS data dumps. You collect evidence, and draw no conclusions without evidence. Community data from someone else's hardware **can never be verified live** — the fixture is the correctness gate (see docs/register-discovery.md "Community Data").

## Workflow

### 1. Find and download dumps

- Attachment URLs are in `gh issue view <n> --json body,comments` (pattern `https://github.com/user-attachments/files/<id>/<name>`); fetch them with the script below instead of with `curl -o`.
- Use `python tools/fetch_attachments.py <nr> --out <scratch-dir>` (add `--discussion` for a discussion). The script downloads to a scratch directory, refuses `tests/fixtures`, and reports attachments that are already a fixture. Never download with `curl -o` over an existing path.
- Collect **all** attachments per issue (not only the newest), sort by timestamp/updatedAt.
- Check whether the dump already exists as a fixture (`tests/fixtures/community/`); if so, do not add it under a second name.
- Present locally: `/config/vaillant_ebus/discovery_dump_*.yaml` (via HA, see the `home-assistant` skill).

### 2. Turn it into a fixture

- Copy to `tests/fixtures/community/<hardware>_<issue>_<timestamp>.yaml` (e.g. `hmux0_issue99_2026-09-13_173740.yaml`).
- **Never cut raw find lines or provenance** — test_fixture_integrity guards this. Keep all `raw_find_lines` (and `raw_find_lines_after` if it is there).
- Add the fixture to the parametrize sweep `test_all_fixtures_load` in `tests/test_fake_ebusd.py` (realistic min_registers per dump).
- After the change, run `python tools/validate.py` (on Windows the known environment failures from `tools/known_env_failures.txt` are ignored).
- Write a fixture-backed regression test on the discovered graph (register values, owner circuit, absent behavior).

### 3. Build the evidence table

Use `backend/grab_parser.py` (`parse_grab_lines`, `unknown_telegrams`, `labeled_telegrams`) on the `grab`/`unknown_telegrams`/`labeled_telegrams` sections. For **every** relevant unknown or unmapped telegram, one row:

| column | value |
|---|---|
| local dump(s) | file number + section |
| master / slave | addresses in hex |
| message ID | e.g. `B524` |
| sub-address | e.g. `06020001000900` |
| request bytes | exact |
| response length + bytes | exact |
| observed state(s) | the payload per state |
| occurrence count | count |

Deduplicate on `(slave, message ID, sub-address)`, keep state-specific payloads and counts. Field entries (`Status01.temp`) are not registers — strip field suffixes and resolve the parent register.

### 4. Search upstream (mandatory)

For every candidate: `tools/search_upstream.sh --comments --all` with **multiple** query variants: full message ID (`b511`), message+sub (`b511 0101`), request/payload fragments with and without spaces, slave/device identity (`HMUX0`, `HW0504`), hardware and feature terms (`Quiet mode`, `Cooling`). A zero-result is evidence for that query, never that no mapping exists.

- Rate limits: cache output, wait + retry on HTTP 403, reduce parallel queries, use `gh issue view <n> --comments` / `gh pr view <n> --comments` for promising threads.
- Read promising issues/PRs **in full** (comment chain) before you use a snippet. Note the URL, hardware context and classification.

### 5. Classify

- `confirmed`: name + value/layout explicit (live own hw, or fixture with explicit capture)
- `strong assumption`: multiple consistent observations / clear before-after correlation
- `speculative`: insufficient evidence for production
- `discovery-only`: no layout evidence, presence only

### 6. Layout verification before a runtime define

Check all of the following before a `define -r` in `_define_custom_registers()`:
- master/slave + message ID + sub-address match the evidence telegram.
- Response byte length and field offsets are correct; units/range plausible.
- Hardware/firmware scope is explicit; the definition is additive and tolerates absent/`ERR` without creating a normal entity.
- Prefer passive `u` definitions; no active polling that changes bus behavior unless explicitly needed and safe.

### 7. Implementation route

- Add through existing data-driven paths: `_define_custom_registers()`, `REGISTER_MAP`, `MULTI_FIELD_MAP`, device-type tables. Never one-off register-specific isolated code paths.
- The regression test loads the fixture and asserts both the decoded value and the absent path of the register.
- For writes: see the write conventions in REFERENCE.md; test the write directly against ebusd first and verify the read-back. A "write works" claim requires write-vs-app evidence, not just a `done`.

## References

- Local dump comparison (diffing 2 dumps): skill `dump-diff`.
- Register reverse-engineering / TCP-level: skill `ebusd-expert`.
- Dump structure, telegrams, learned patterns: see `REFERENCE.md`.
