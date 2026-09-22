# Release 1.9.4 — Plan

Status: **IN PROGRESS**
Branch: `release/1.9.4`
Datum: 2026-09-22

## Risk class: Release-sensitive patch

This release publishes merged PR #156, which fixes stale cache entities found
on the F34 BAI00/BASS3 community capture. No unrelated feature work is included.

## Scope

### Must

- Bump the version consistently to `1.9.4`.
- Add changelog notes for PR #156.
- Preserve the complete F34 community fixtures and cache/entity regression tests.
- Run the full release validation and independent release audit.

### Should

- Open and merge a release PR.
- Create and push annotated tag `v1.9.4` on the merged `main` commit.
- Verify the GitHub Release and release zip asset.

### Out of scope

- New F34 register mappings for values reported as `ERR: invalid position`,
  `ERR: element not found`, or `no data stored`.
- Unrelated entity-model or polling changes.

## Validation

- `.venv/bin/ruff check .`
- Scoped Ruff format check from `AGENTS.md`.
- `.venv/bin/pytest -q`
- `python3 tools/version.py check`
- `python3 -m compileall -f custom_components/vaillant_ebus/`
- Independent release audit.

## Release gate

- Version is `1.9.4` in `pyproject.toml`, `manifest.json`, and `CHANGELOG.md`.
- Release notes match the merged PR and evidence scope.
- All local and GitHub validation checks pass.
- Do not shut down any machine as part of the release workflow.
