"""Import the pure ``backend`` modules without importing Home Assistant.

``custom_components/vaillant_ebus/__init__.py`` needs Home Assistant, which the backend does not. Registering
lightweight stand-in packages lets tests import backend modules normally, once, instead of repeating
``importlib.util`` blocks per test file.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

BACKEND_PATH = Path(__file__).parents[1] / "custom_components" / "vaillant_ebus" / "backend"
COMPONENT_PATH = BACKEND_PATH.parent


# Intent: register stand-in `vaillant_ebus` and `vaillant_ebus.backend` packages unless they already exist.
# Why: other test modules register the same names; reusing them keeps one module object per backend file.
def _ensure_packages() -> None:
    for name, path in (("vaillant_ebus", COMPONENT_PATH), ("vaillant_ebus.backend", BACKEND_PATH)):
        if name not in sys.modules:
            package = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None, is_package=True))
            package.__path__ = [str(path)]
            sys.modules[name] = package


# Intent: return a backend module (for example ``"models"``) loaded under ``vaillant_ebus.backend``.
# Why: tests need the production module objects, not copies, so identity checks and enums stay consistent.
def load_backend(name: str) -> ModuleType:
    _ensure_packages()
    return importlib.import_module(f"vaillant_ebus.backend.{name}")
