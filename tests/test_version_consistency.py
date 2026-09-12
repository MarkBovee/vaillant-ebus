"""Release-version consistency guard.

The version must stay identical across ``pyproject.toml``, the Home Assistant
``manifest.json``, and the top ``## <version>`` heading in ``CHANGELOG.md``.
Drift silently ships a mislabelled release, so this runs in CI through the
normal pytest step. The single source of truth is ``tools/version.py``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _version_tool() -> object:
    spec = importlib.util.spec_from_file_location("version_tool", ROOT / "tools" / "version.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


# Intent: bump keeps pyproject.toml PEP 440 (1.8.0rc2) while manifest keeps the display form (1.8.0-rc2).
# Why: ``1.8.0-rc2`` is not valid PEP 440; the check-normalizer strips separators,
# so drift would go unnoticed without this pin.
def test_pyproject_normalizes_pre_release() -> None:
    version_tool = _version_tool()
    assert version_tool.pyproject_version("1.8.3-rc1") == "1.8.3rc1"
    assert version_tool.pyproject_version("1.8.3") == "1.8.3"
    assert version_tool.canonical("1.8.3-rc1") == version_tool.canonical("1.8.3rc1") == "183rc1"
