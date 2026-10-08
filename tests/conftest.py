"""Pytest bootstrap for the test suite.

Importing the shared loader here runs the vaillant_ebus module setup once, before any test module
is collected. Test files can then import vaillant_ebus names in any order.
"""

from tests import _component_loader  # noqa: F401 — loads the shared vaillant_ebus modules once
