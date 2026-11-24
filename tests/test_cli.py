"""Command line: outputs (table, CSV, JSON, Excel) and exit codes."""

import csv
import json
import re
import sys
from pathlib import Path

import pytest
from conftest import roundtrip

from dxf_takeoff import __version__
from dxf_takeoff.cli import main

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

RULES = """
[settings]
currency = "EUR"
[[item]]
description = "Pipe"
match_layer = "PIPE"
quantity = "length"
unit = "m"
rate = 10
[[item]]
description = "Valves"
match_block = "VALVE"
quantity = "count"
rate = 100
"""


@pytest.fixture
def plan(doc, tmp_path):
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (1500, 0), (1500, 1000)], dxfattribs={"layer": "PIPE"})
    hatch = msp.add_hatch(dxfattribs={"layer": "ROOM"})
    hatch.paths.add_polyline_path([(0, 0), (4000, 0), (4000, 2500), (0, 2500)], is_closed=True)
    doc.blocks.new("VALVE").add_circle((0, 0), 50)
    msp.add_blockref("VALVE", (0, 0), dxfattribs={"layer": "VALVES"})
    msp.add_blockref("VALVE", (500, 0), dxfattribs={"layer": "VALVES"})
    (tmp_path / "takeoff.toml").write_text(RULES, encoding="utf-8")
    return roundtrip(doc, tmp_path, "plan.dxf")


def test_terminal_table(plan, capsys):
    assert main([str(plan), "--out-units", "m", "--perimeter"]) == 0
    out = capsys.readouterr().out
    assert f"dxf-takeoff {__version__} | plan.dxf | layout Model" in out
    assert "Length [m]" in out and "Area [m2]" in out and "Perimeter [m]" in out
    assert re.search(r"PIPE\s+1\s+2\.500", out)
    assert re.search(r"ROOM\s+1\s+10\.000\s+13\.000", out)


def test_all_file_outputs(plan, tmp_path, capsys):
    out_dir, xlsx, js = tmp_path / "csv", tmp_path / "takeoff.xlsx", tmp_path / "takeoff.json"
    code = main([str(plan), "--out-units", "m", "--rules", str(tmp_path / "takeoff.toml"),
                 "--csv", str(out_dir), "--xlsx", str(xlsx), "--json", str(js), "-q"])
    assert code == 0 and capsys.readouterr().out == ""
    assert sorted(p.name for p in out_dir.iterdir()) == ["areas.csv", "blocks.csv", "boq.csv", "lengths.csv"]
    with open(out_dir / "lengths.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["layer"] == "PIPE" and float(rows[0]["length_m"]) == pytest.approx(2.5)
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["units"]["length"] == "m" and data["totals"]["blocks"] == 2
    assert data["boq"]["total"] == pytest.approx(225.0)

    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(xlsx)
    assert wb.sheetnames == ["Summary", "Lengths", "Areas", "Blocks", "BOQ"]
    boq = wb["BOQ"]
    assert boq["C2"].value == pytest.approx(2.5) and boq["G2"].value == 10
    assert boq["F2"].value == "=C2*(1+E2/100)" and boq["H2"].value == '=IF(ISNUMBER(G2),F2*G2,"")'
    assert boq["H4"].value == "=SUM(H2:H3)"
    assert wb["Lengths"]["C4"].value == "=SUM(C2:C3)"  # PIPE + VALVES (circle inside the block)
    assert wb["Lengths"]["C2"].number_format == "#,##0.000"


def test_json_to_stdout_is_pure_json(plan, capsys):
    assert main([str(plan), "--json", "-", "--group-by-attrib", "TAG"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["file"] == "plan.dxf" and data["units"]["length"] == "mm"


@pytest.mark.parametrize("args, message", [
    (["missing.dxf"], "file not found"),
    (["{plan}", "--out-units", "furlong"], "unknown length unit"),
    (["{plan}", "--rules", "nope.toml"], "rules file not found"),
    (["{plan}", "--layout", "Sheet 9"], "not found"),
])
def test_errors_exit_with_code_2(plan, capsys, args, message):
    assert main([a.format(plan=plan) for a in args]) == 2
    assert message in capsys.readouterr().err


def test_dwg_files_get_a_helpful_message(tmp_path, capsys):
    dwg = tmp_path / "plan.dwg"
    dwg.write_bytes(b"AC1032" + b"\0" * 100)
    assert main([str(dwg)]) == 2
    assert "ODA File Converter" in capsys.readouterr().err


def test_version_matches_pyproject():
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    assert tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"] == __version__
