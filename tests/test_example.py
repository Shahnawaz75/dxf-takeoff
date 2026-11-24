"""The committed tank-farm example: hand-calculated quantities and committed outputs."""

import importlib.util
import json
from pathlib import Path

import pytest

from dxf_takeoff import takeoff

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _rounded(obj):
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _rounded(v) for k, v in obj.items() if k != "version"}
    if isinstance(obj, list):
        return [_rounded(v) for v in obj]
    return obj


@pytest.fixture(scope="module")
def result():
    return takeoff(EXAMPLES / "tank_farm.dxf", out_units="m", group_by_attribs=["SIZE"],
                   rules=EXAMPLES / "takeoff.toml")


def test_example_matches_hand_calculation(result):
    spec = importlib.util.spec_from_file_location("make_example", EXAMPLES / "make_example.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    for key, mm in generator.expected_mm().items():
        layer, _, kind = key.partition(" ")
        measured = {"": result.length, "area": result.area, "perimeter": result.perimeter}[kind](layer)
        assert measured == pytest.approx(mm * (1e-6 if kind == "area" else 1e-3), rel=1e-12), key


def test_example_counts_and_notes(result):
    assert result.count("GATE-VALVE", SIZE="200") == 4
    assert result.count("BUTTERFLY-VALVE") == 2  # dynamic block stored as *U blocks
    assert result.count("PIPE-SUPPORT") == 9  # one MINSERT, 1 x 9
    assert result.length("Z-DEMOLISHED") == 0  # frozen layer
    assert result.boq.not_in_boq == ("layers SYMBOL", "blocks PUMP x3")


def test_committed_json_is_current(result):
    committed = json.loads((EXAMPLES / "takeoff.json").read_text(encoding="utf-8"))
    assert _rounded(result.to_dict()) == _rounded(committed)
