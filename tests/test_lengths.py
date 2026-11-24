"""Lengths of every supported entity type, against closed-form answers."""

import math

import pytest
from conftest import ellipse_perimeter, new_doc, roundtrip
from ezdxf.math import rational_bspline_from_arc

from dxf_takeoff import takeoff


def test_line_3_4_5(doc):
    doc.modelspace().add_line((1, 1, 0), (4, 5, 0))
    assert takeoff(doc).length() == pytest.approx(5.0, rel=1e-15)


def test_rectangle_polyline_perimeter(doc):
    doc.modelspace().add_lwpolyline([(0, 0), (1000, 0), (1000, 500), (0, 500)], close=True)
    assert takeoff(doc).length() == pytest.approx(3000.0, rel=1e-15)


def test_bulge_semicircle_is_exact_arc_not_chord(doc):
    r = 250.0
    doc.modelspace().add_lwpolyline([(0, 0, 1.0), (2 * r, 0, 0)], format="xyb")
    assert takeoff(doc).length() == pytest.approx(math.pi * r, rel=1e-14)


def test_bulge_quarter_arcs_positive_and_negative(doc):
    b = math.tan(math.pi / 8)  # 90 degree sweep
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0, b), (10, 0, 0)], format="xyb", dxfattribs={"layer": "CCW"})
    msp.add_lwpolyline([(0, 0, -b), (10, 0, 0)], format="xyb", dxfattribs={"layer": "CW"})
    r = 10 / math.sqrt(2)
    result = takeoff(doc)
    assert result.length("CCW") == pytest.approx(r * math.pi / 2, rel=1e-14)
    assert result.length("CW") == pytest.approx(r * math.pi / 2, rel=1e-14)


def test_circle_circumference(doc):
    doc.modelspace().add_circle((5, 5), 10)
    assert takeoff(doc).length() == pytest.approx(20 * math.pi, rel=1e-15)


def test_arc_and_arc_across_zero_degrees(doc):
    msp = doc.modelspace()
    msp.add_arc((0, 0), 5, 30, 120, dxfattribs={"layer": "A"})
    msp.add_arc((0, 0), 5, 350, 10, dxfattribs={"layer": "B"})
    result = takeoff(doc)
    assert result.length("A") == pytest.approx(5 * math.pi / 2, rel=1e-14)
    assert result.length("B") == pytest.approx(5 * math.radians(20), rel=1e-12)


def test_mirrored_extrusion_arc(doc):
    doc.modelspace().add_arc((3, 4), 2, 0, 90, dxfattribs={"extrusion": (0, 0, -1)})
    assert takeoff(doc).length() == pytest.approx(math.pi, rel=1e-14)


def test_full_and_partial_ellipse(doc):
    msp = doc.modelspace()
    msp.add_ellipse((0, 0), major_axis=(30, 0), ratio=0.5, dxfattribs={"layer": "FULL"})
    msp.add_ellipse((0, 0), major_axis=(0, 30), ratio=0.5, start_param=0, end_param=math.pi / 2,
                    dxfattribs={"layer": "QUARTER"})
    result = takeoff(doc)
    exact = ellipse_perimeter(30, 15)
    assert result.length("FULL") == pytest.approx(exact, rel=1e-11)
    assert result.length("QUARTER") == pytest.approx(exact / 4, rel=1e-11)


def test_old_style_2d_polyline_with_bulges_and_3d_polyline(doc, tmp_path):
    msp = doc.modelspace()
    msp.add_polyline2d([(0, 0, 0, 0, 1.0), (20, 0, 0, 0, 0)], format="xyseb", dxfattribs={"layer": "P2D"})
    msp.add_polyline3d([(0, 0, 0), (3, 4, 0), (3, 4, 12)], dxfattribs={"layer": "P3D"})
    result = takeoff(roundtrip(doc, tmp_path))
    assert result.length("P2D") == pytest.approx(10 * math.pi, rel=1e-14)
    assert result.length("P3D") == pytest.approx(17.0, rel=1e-15)


def test_spline_is_flattened_and_reported_as_approximate(doc):
    spline = doc.modelspace().add_spline()
    spline.apply_construction_tool(rational_bspline_from_arc(center=(0, 0), radius=100, start_angle=0, end_angle=90))
    exact = 50 * math.pi
    result = takeoff(doc)
    assert result.length() == pytest.approx(exact, rel=2e-6)
    assert result.lengths[0].approximate and "flattened" in result.spline_method
    coarse = takeoff(doc, spline_tolerance=1.0)
    assert coarse.length() < exact and coarse.length() == pytest.approx(exact, rel=1e-2)
    assert "1 drawing units" in coarse.spline_method


def test_mline_reference_line_length(doc):
    doc.modelspace().add_mline([(0, 0), (4000, 0), (4000, 3000)])
    assert takeoff(doc).length() == pytest.approx(7000.0, rel=1e-15)


def test_group_by_linetype_and_color(doc):
    doc.linetypes.add("DASHED", pattern=[0.6, 0.5, -0.1])
    doc.layers.add("P", color=5)
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "P"})
    msp.add_line((0, 0), (5, 0), dxfattribs={"layer": "P", "linetype": "DASHED", "color": 1})
    by_lt = {(r.layer, r.linetype): r.length for r in takeoff(doc, group_by="layer+linetype").lengths}
    assert by_lt == {("P", "Continuous"): 10.0, ("P", "DASHED"): 5.0}
    by_color = {(r.layer, r.color): r.length for r in takeoff(doc, group_by="layer+color").lengths}
    assert by_color == {("P", "5"): 10.0, ("P", "1"): 5.0}


def test_text_and_dimensions_are_ignored():
    doc = new_doc()
    msp = doc.modelspace()
    msp.add_text("hello")
    msp.add_point((1, 1))
    msp.add_linear_dim(base=(0, 5), p1=(0, 0), p2=(10, 0)).render()
    result = takeoff(doc)
    assert result.lengths == [] and result.blocks == []
