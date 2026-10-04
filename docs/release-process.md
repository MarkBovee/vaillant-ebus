# Release, smoke test and deploy

Moved from AGENTS.md. The short hard rules stay in AGENTS.md.

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
