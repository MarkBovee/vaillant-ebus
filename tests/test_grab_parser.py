"""Unit tests for grab_parser (ebusd grab telegram parsing)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

BACKEND_PATH = Path(__file__).parents[1] / "custom_components/vaillant_ebus/backend"
COMPONENT_PATH = BACKEND_PATH.parent

for name, path in (
    ("vaillant_ebus", COMPONENT_PATH),
    ("vaillant_ebus.backend", BACKEND_PATH),
):
    pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec(name, None))
    pkg.__path__ = [str(path)]
    sys.modules[name] = pkg

spec = importlib.util.spec_from_file_location(
    "vaillant_ebus.backend.grab_parser", BACKEND_PATH / "grab_parser.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules["vaillant_ebus.backend.grab_parser"] = module
spec.loader.exec_module(module)

parse_grab_lines = module.parse_grab_lines
unknown_telegrams = module.unknown_telegrams

GRAB_LINES = [
    "[grab] grab started",
    "1008b51009000022ffffff070004 / 0101 = 19: hmu SetMode",
    "1008b5110100 / 09410111436809000016 = 3",
    "1076b5040100 / 0a0322581014080526e61b = 3",
    "10feb505025c01 = 3",
    "10feb508020900 = 1",
    "f108b503020002 / 0affffffffffffffffffff = 3",
    "[grab stop] grab stopped",
]


class TestParseGrabLines:
    def test_labeled_telegram_parsed(self) -> None:
        telegrams = parse_grab_lines(GRAB_LINES)
        labeled = [t for t in telegrams if t["label"]]
        assert len(labeled) == 1
        t = labeled[0]
        assert t["label"] == "hmu SetMode"
        assert t["msgid"] == "b510"
        assert t["master"] == "10"
        assert t["slave"] == "08"
        assert t["sub"] == "09000022ffffff070004"
        assert t["resp"] == "0101"
        assert t["count"] == "19"

    def test_unknown_telegrams_parsed(self) -> None:
        telegrams = parse_grab_lines(GRAB_LINES)
        unknown = [t for t in telegrams if t["label"] is None]
        assert len(unknown) == 5
        for t in unknown:
            assert t["label"] is None
        bc = [t for t in unknown if t["msgid"] == "b505"][0]
        assert bc["resp"] is None
        assert bc["master"] == "10"
        assert bc["slave"] == "fe"

    def test_unknown_telegrams_helper(self) -> None:
        unknown = unknown_telegrams(GRAB_LINES)
        assert all(t["label"] is None for t in unknown)
        assert len(unknown) == 5

    def test_roundtrip_real_fixture(self) -> None:
        import yaml

        fixture = (
            Path(__file__).parents[1]
            / "tests/fixtures/community/arotherm_plus_ctlv2_cooling_discovery.yaml"
        )
        data = yaml.safe_load(fixture.read_text())
        grab = data.get("grab", [])
        assert grab, "fixture should contain grab data"
        unknown = unknown_telegrams(grab)
        labeled = [t for t in parse_grab_lines(grab) if t["label"]]
        assert unknown, "fixture grab should contain unknown telegrams"
        assert labeled, "fixture grab should contain labeled telegrams"
