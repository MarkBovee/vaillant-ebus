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


PACKAGE = "vaillant_ebus_pure"


# Intent: register private stand-in packages (`vaillant_ebus_pure`, `vaillant_ebus_pure.backend`) unless they exist.
# Why: older test files re-execute backend modules under the `vaillant_ebus` name and replace each other's classes;
# a private namespace keeps every module imported here consistent with the others imported here.
def _ensure_packages() -> None:
    for name, path in ((PACKAGE, COMPONENT_PATH), (f"{PACKAGE}.backend", BACKEND_PATH)):
        if name not in sys.modules:
            package = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None, is_package=True))
            package.__path__ = [str(path)]
            sys.modules[name] = package


# Intent: return a backend module (for example ``"models"``) loaded under the private ``vaillant_ebus_pure.backend``.
# Why: tests need the production module objects, not copies, so identity checks and enums stay consistent.
def load_backend(name: str) -> ModuleType:
    _ensure_packages()
    return importlib.import_module(f"{PACKAGE}.backend.{name}")
