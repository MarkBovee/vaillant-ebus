"""Unit tests for DHW storage-tank presence detection (#135).

derive_tank_presence reads the controller's HwcStorageTemp sentinel: a live
temperature means a tank is present, an empty/NaN read means no tank, and a
missing register means unknown. These tests pin that tri-state.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]

MODELS_PATH = PROJECT_ROOT / "custom_components/vaillant_ebus/backend/models.py"
SPEC = importlib.util.spec_from_file_location("vaillant_ebus_models", MODELS_PATH)
assert SPEC and SPEC.loader
MODELS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODELS
SPEC.loader.exec_module(MODELS)

derive_tank_presence = MODELS.derive_tank_presence


# Intent: A live positive HwcStorageTemp proves a tank is present, across the
# numeric values seen in the community fixtures (40-62 C).
# Why: pins the tank-present branch of the tri-state detector.
def test_tank_presence_true_for_live_temperature() -> None:
    for temp in ("45", "46.5", "49.5", "62"):
        assert derive_tank_presence({"ctlv2.HwcStorageTemp.value": temp}, "ctlv2") is True


# Intent: The empty/NaN sentinel "(empty ...7fffffff)" means no tank, returning False.
# Why: this is the exact poll reply on monobloc units without a cylinder.
def test_tank_presence_false_for_empty_sentinel() -> None:
    raw = "(empty for 3115b52406020001000500 / 0800010500ffffff7f)"
    assert derive_tank_presence({"ctlv0.HwcStorageTemp.value": raw}, "ctlv0") is False


# Intent: "no data stored" is an idle/absent reply that must not count as a tank.
# Why: keeps the detector conservative when the register returns no live value.
def test_tank_presence_false_for_no_data() -> None:
    assert derive_tank_presence({"ctlv3.HwcStorageTemp.value": "no data stored"}, "ctlv3") is False


# Intent: A missing register or missing circuit yields None (unknown), never a guess.
# Why: the controller may not expose the register at all on some firmware.
def test_tank_presence_unknown_when_missing() -> None:
    assert derive_tank_presence({}, "ctlv2") is None
    assert derive_tank_presence({"ctlv2.HwcStorageTemp.value": "no data stored"}, None) is None


# Intent: A plain placeholder that is neither a live temperature nor an
# empty/no-data sentinel stays unknown rather than being treated as a tank.
# Why: "-" is not a confirmed "no tank"; only an explicit sentinel or a live
# temperature should decide.
def test_tank_presence_unknown_for_plain_placeholder() -> None:
    # "-" is a no-data sentinel, so it reads as no tank, not a live temperature.
    assert derive_tank_presence({"ctlv2.HwcStorageTemp.value": "-"}, "ctlv2") is False


# Intent: Zero and negative temperatures are not a live tank value.
# Why: storage water cannot be at or below 0 and still be a connected tank.
def test_tank_presence_not_true_for_non_positive_temperature() -> None:
    assert derive_tank_presence({"ctlv2.HwcStorageTemp.value": "0"}, "ctlv2") is not True
    assert derive_tank_presence({"ctlv2.HwcStorageTemp.value": "-13.5"}, "ctlv2") is not True


def _fixture_storage_temp(name: str) -> tuple[str, str]:
    """Return (circuit, HwcStorageTemp value) from a discovery-dump fixture."""
    from tests.fake_ebusd import load_discovery_dump

    dump = load_discovery_dump(f"community/{name}")
    for line in dump.get("raw_find_lines", []):
        if "HwcStorageTemp =" in line:
            circuit = line.split()[0]
            value = line.split("=", 1)[1].strip()
            return circuit, value
    raise AssertionError(f"{name}: no HwcStorageTemp in fixture")


# Fixture: an aroTHERM Pro 7 dump without a cylinder reads empty/NaN, so the
# detector must not report a tank even though a heat pump is present.
# Intent: prove the no-tank (empty sentinel) detection against a real discovery dump.
# Why: the Pro 7 monobloc is the exact hardware where a heat pump exists without a tank.
def test_tank_presence_pro7_fixture_no_tank() -> None:
    for name in (
        "arotherm_pro7_quiet_off_idle_discovery.yaml",
        "ecotec_vrt380_15700_discovery.yaml",
    ):
        circuit, value = _fixture_storage_temp(name)
        assert derive_tank_presence({f"{circuit}.HwcStorageTemp.value": value}, circuit) is False


# Fixture: heat-pump dumps that report a live storage temperature must read as
# a tank present.
# Intent: prove the tank-present branch against real discovery dumps.
# Why: heat pumps with a uniSTOR/cylinder report a live HwcStorageTemp, unlike
# the empty-sentinel monobloc units.
def test_tank_presence_tank_fixture_present() -> None:
    for name in (
        "arotherm_plus_2zone_discovery.yaml",
        "v32_boiler_discovery.yaml",
    ):
        circuit, value = _fixture_storage_temp(name)
        assert derive_tank_presence({f"{circuit}.HwcStorageTemp.value": value}, circuit) is True
