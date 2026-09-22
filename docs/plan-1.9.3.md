# Release 1.9.3 — Plan

Status: **IN PROGRESS**
Branch: `release/1.9.3`
Datum: 2026-09-22

## Risk class: Release-sensitive patch

This is a focused follow-up release for the merged v1.9.2 hotfix in PR #154.
No new feature scope is added.

## Scope

### Must

- Set the release version consistently to `1.9.3`.
- Add a changelog entry for the merged fix: the global Energy counter scale
  setting must work when the optional `entities.yaml` file is absent or invalid.
- Preserve the regression test covering the no-`entities.yaml` path.
- Run the complete repository release validation before opening the release PR.

### Should

- Open a release PR from `release/1.9.3` to `main`.
- Merge the PR, then create and push annotated tag `v1.9.3`.
- Verify the merged commit, tag, and clean local branch state.

### Could

- None. Avoid unrelated cleanup or feature work in this patch release.

## Validation

- `.venv/bin/ruff check .`
- Scoped Ruff format check from `AGENTS.md`.
- `.venv/bin/pytest -q`
- `python3 tools/version.py check`
- `python3 -m compileall -f custom_components/vaillant_ebus/`
- Independent review/audit of the release diff and release-gate evidence.

## Release gate

- Release notes match the actual merged hotfix.
- Version is `1.9.3` in `pyproject.toml`, `manifest.json`, and `CHANGELOG.md`.
- No unresolved validation, review, or audit findings.
- Do not shut down any machine as part of the release workflow.
