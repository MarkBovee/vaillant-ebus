"""Release-version consistency guard.

The version must stay identical across ``pyproject.toml``, the Home Assistant
``manifest.json``, and the top ``## <version>`` heading in ``CHANGELOG.md``.
Drift silently ships a mislabelled release, so this runs in CI through the
normal pytest step. The single source of truth is ``tools/version.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# Intent: pyproject.toml, manifest.json and the CHANGELOG heading carry one release version.
# Why: a mismatch ships a mislabelled release; the shared checker keeps them in sync automatically.
def test_release_version_is_consistent() -> None:
    result = subprocess.run(
        [sys.executable, "tools/version.py", "check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
