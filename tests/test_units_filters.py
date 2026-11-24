"""Units, scale, layer filters, hidden layers and layouts."""

import pytest
from conftest import new_doc

from dxf_takeoff import TakeoffError, takeoff
from dxf_takeoff.units import parse_area_unit


def _rect(doc, layer="0", w=1000.0, h=500.0):
    doc.modelspace().add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True, dxfattribs={"layer": layer})


def test_mm_drawing_reported_in_metres(doc):
    _rect(doc)
    result = takeoff(doc, out_units="m")
    assert (result.length_unit, result.area_unit) == ("m", "m2")
    assert result.length() == pytest.approx(3.0, rel=1e-15)
    assert result.area() == pytest.approx(0.5, rel=1e-15)


def test_inch_drawing_to_mm_and_ft():
    doc = new_doc(insunits=1)
    doc.modelspace().add_line((0, 0), (120, 0))
    assert takeoff(doc, out_units="mm").length() == pytest.approx(3048.0, rel=1e-15)
    assert takeoff(doc, out_units="ft").length() == pytest.approx(10.0, rel=1e-15)


def test_units_override_insunits(doc):
    doc.modelspace().add_line((0, 0), (1000, 0))
    result = takeoff(doc, units="cm", out_units="m")
    assert result.drawing_units == "cm" and result.length() == pytest.approx(10.0, rel=1e-15)


def test_unitless_drawing_needs_units_for_conversion():
    doc = new_doc(insunits=0)
    doc.modelspace().add_line((0, 0), (7, 0))
    with pytest.raises(TakeoffError, match="no units"):
        takeoff(doc, out_units="m")
    result = takeoff(doc)
    assert result.length_unit == "du" and any("no units" in n for n in result.notes)
    assert takeoff(doc, units="ft", out_units="in").length() == pytest.approx(84.0, rel=1e-15)


def test_scale_for_drawings_not_drawn_full_size(doc):
    _rect(doc, w=10, h=5)  # drawn at 1:100
    result = takeoff(doc, scale=100, out_units="m")
    assert result.length() == pytest.approx(3.0, rel=1e-15)
    assert result.area() == pytest.approx(0.5, rel=1e-15)


def test_unknown_units_are_rejected(doc):
    with pytest.raises(TakeoffError, match="unknown length unit"):
        takeoff(doc, out_units="furlong")
    assert parse_area_unit("m²") == "m" and parse_area_unit("sq ft") == "ft"
    with pytest.raises(TakeoffError):
        parse_area_unit("m")


def test_layer_wildcards_are_case_insensitive_and_repeatable(doc):
    for layer in ("P-CW-100", "P-CW-50", "P-FW-150", "A-WALL"):
        doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": layer})
    layers = lambda **kw: [r.layer for r in takeoff(doc, **kw).lengths]  # noqa: E731
    assert layers(layers=["p-cw-*"]) == ["P-CW-50", "P-CW-100"]
    assert layers(layers=["P-CW-1*", "A-*"]) == ["A-WALL", "P-CW-100"]
    assert layers(layers=["P-*"], exclude_layers=["*-FW-*"]) == ["P-CW-50", "P-CW-100"]


def test_frozen_and_off_layers_are_skipped_unless_requested(doc):
    doc.layers.add("FROZEN").freeze()
    doc.layers.add("OFF").off()
    for layer in ("FROZEN", "OFF", "ON"):
        doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": layer})
    result = takeoff(doc)
    assert [r.layer for r in result.lengths] == ["ON"]
    assert any("2 entities on frozen or off layers" in n for n in result.notes)
    assert [r.layer for r in takeoff(doc, include_hidden=True).lengths] == ["FROZEN", "OFF", "ON"]


def test_block_on_frozen_layer_hides_content_off_layer_hides_layer_zero_only(doc):
    doc.layers.add("FRZ").freeze()
    doc.layers.add("OFFL").off()
    block = doc.blocks.new("B")
    block.add_line((0, 0), (1, 0))  # layer 0: inherits the reference layer
    block.add_line((0, 0), (2, 0), dxfattribs={"layer": "OWN"})
    msp = doc.modelspace()
    msp.add_blockref("B", (0, 0), dxfattribs={"layer": "FRZ"})
    msp.add_blockref("B", (0, 0), dxfattribs={"layer": "OFFL"})
    result = takeoff(doc)
    assert {r.layer: r.length for r in result.lengths} == {"OWN": 2.0}  # only from the OFFL reference
    assert result.blocks == []
    assert takeoff(doc, include_hidden=True).count("B") == 2


def test_paperspace_layout(doc):
    doc.modelspace().add_line((0, 0), (10, 0))
    doc.layouts.get("Layout1").add_line((0, 0), (3, 0))
    assert takeoff(doc).length() == 10.0
    assert takeoff(doc, layout="layout1").length() == 3.0
    with pytest.raises(TakeoffError, match="available"):
        takeoff(doc, layout="Sheet 9")
