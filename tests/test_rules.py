"""BOQ rules: matching, unit conversion, waste, rates, totals and validation."""

import pytest

from dxf_takeoff import TakeoffError, load_rules, takeoff

RULES = """
[settings]
title = "Test job"
currency = "USD"

[[item]]
code = "P-01"
description = "Chilled water pipe"
match_layer = "P-CHW-*"
quantity = "length"
unit = "m"
waste = 5
rate = 12.5

[[item]]
description = "Chilled water pipe in mm"
match_layer = ["P-CHW-100", "P-CHW-50"]
quantity = "length"
unit = "mm"

[[item]]
description = "Floor coating"
match_layer = "A-FLOOR"
quantity = "area"
unit = "m2"
waste = 10
rate = 20

[[item]]
description = "Skirting"
match_layer = "A-FLOOR"
quantity = "perimeter"
unit = "m"
factor = 2

[[item]]
description = "Gate valve DN100"
match_block = "GATE*"
where = { SIZE = "100" }
quantity = "count"
rate = 250
"""


@pytest.fixture
def job(doc, tmp_path):
    msp = doc.modelspace()
    msp.add_line((0, 0), (60_000, 0), dxfattribs={"layer": "P-CHW-100"})
    msp.add_line((0, 0), (40_000, 0), dxfattribs={"layer": "P-CHW-50"})
    msp.add_line((0, 0), (1_000, 0), dxfattribs={"layer": "TEXT-FRAME"})
    hatch = msp.add_hatch(dxfattribs={"layer": "A-FLOOR"})
    hatch.paths.add_polyline_path([(0, 0), (2000, 0), (2000, 1000), (0, 1000)], is_closed=True)
    valve = doc.blocks.new("GATE-VALVE")
    valve.add_attdef("SIZE", (0, 0))
    for size in ("100", "100", "50"):
        msp.add_blockref("GATE-VALVE", (0, 0)).add_auto_attribs({"SIZE": size})
    msp.add_blockref("GATE-VALVE", (0, 0))  # no SIZE attribute
    path = tmp_path / "takeoff.toml"
    path.write_text(RULES, encoding="utf-8")
    return takeoff(doc, rules=path).boq


def test_length_item_with_waste_and_rate(job):
    line = job.lines[0]
    assert (line.code, line.unit, line.matched) == ("P-01", "m", 2)
    assert line.net == pytest.approx(100.0, rel=1e-15)
    assert line.gross == pytest.approx(105.0, rel=1e-15)
    assert line.amount == pytest.approx(1312.5, rel=1e-15)


def test_item_unit_is_converted(job):
    assert job.lines[1].net == pytest.approx(100_000.0, rel=1e-15) and job.lines[1].amount is None


def test_area_and_perimeter_items(job):
    area, skirting = job.lines[2], job.lines[3]
    assert area.net == pytest.approx(2.0, rel=1e-15) and area.amount == pytest.approx(44.0, rel=1e-15)
    assert skirting.net == pytest.approx(12.0, rel=1e-15)  # 6 m perimeter x factor 2


def test_count_item_filters_attributes(job):
    line = job.lines[4]
    assert (line.net, line.unit, line.amount) == (2.0, "nr", 500.0)


def test_total_and_items_not_in_boq(job):
    assert job.total == pytest.approx(1312.5 + 44 + 500, rel=1e-15)
    assert (job.title, job.currency) == ("Test job", "USD")
    assert job.not_in_boq == ("layers TEXT-FRAME", "blocks GATE-VALVE x2")


@pytest.mark.parametrize("item, message", [
    ('description = "x"\nquantity = "length"\nwastage = 5', "unknown key"),
    ('description = "x"\nquantity = "volume"', "quantity must be"),
    ('description = "x"\nquantity = "area"\nunit = "m"', "area unit"),
    ('description = "x"\nquantity = "length"\nmatch_block = "V*"', "only apply"),
    ('description = "x"\nquantity = "count"\nrate = -1', "non-negative"),
    ('quantity = "count"', "description is required"),
])
def test_invalid_rules_are_rejected_with_a_clear_message(tmp_path, item, message):
    path = tmp_path / "bad.toml"
    path.write_text(f"[[item]]\n{item}\n", encoding="utf-8")
    with pytest.raises(TakeoffError, match=message):
        load_rules(path)


def test_rules_file_must_exist_and_be_toml(tmp_path):
    with pytest.raises(TakeoffError, match="not found"):
        load_rules(tmp_path / "missing.toml")
    bad = tmp_path / "broken.toml"
    bad.write_text("[[item]\n", encoding="utf-8")
    with pytest.raises(TakeoffError, match="invalid TOML"):
        load_rules(bad)
