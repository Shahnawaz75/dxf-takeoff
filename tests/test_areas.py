"""Areas of closed shapes and hatches, against closed-form answers."""

import math

import pytest
from conftest import roundtrip
from ezdxf.math import rational_bspline_from_arc

from dxf_takeoff import takeoff


def test_rectangle_area_and_perimeter(doc):
    doc.modelspace().add_lwpolyline([(0, 0), (1000, 0), (1000, 500), (0, 500)], close=True)
    row = takeoff(doc).areas[0]
    assert row.area == pytest.approx(500_000.0, rel=1e-15)
    assert row.perimeter == pytest.approx(3000.0, rel=1e-15)


def test_far_from_origin_has_no_cancellation_error(doc):
    x0, y0 = 4.5e6, 3.2e6  # survey coordinates
    doc.modelspace().add_lwpolyline([(x0, y0), (x0 + 1, y0), (x0 + 1, y0 + 1), (x0, y0 + 1)], close=True)
    assert takeoff(doc).area() == pytest.approx(1.0, rel=1e-9)


def test_closed_polyline_with_bulges_d_shape(doc):
    r = 50.0  # half disk: bulge-1 arc plus the diameter
    doc.modelspace().add_lwpolyline([(0, 0, 1.0), (2 * r, 0, 0)], format="xyb", close=True)
    row = takeoff(doc).areas[0]
    assert row.area == pytest.approx(math.pi * r * r / 2, rel=1e-14)
    assert row.perimeter == pytest.approx(math.pi * r + 2 * r, rel=1e-14)


def test_circle_from_two_negative_bulges(doc):
    doc.modelspace().add_lwpolyline([(0, 0, -1.0), (20, 0, -1.0)], format="xyb", close=True)
    assert takeoff(doc).area() == pytest.approx(math.pi * 100, rel=1e-14)


def test_polyline_closed_by_returning_to_start_counts_as_area(doc):
    doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])  # not flagged closed
    assert takeoff(doc).area() == pytest.approx(100.0, rel=1e-15)


def test_open_polyline_has_no_area(doc):
    doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 10)])
    assert takeoff(doc).areas == []


def test_circle_and_ellipse_area(doc):
    msp = doc.modelspace()
    msp.add_circle((0, 0), 10, dxfattribs={"layer": "C"})
    msp.add_ellipse((0, 0), major_axis=(20, 20), ratio=0.25, dxfattribs={"layer": "E"})
    result = takeoff(doc)
    assert result.area("C") == pytest.approx(math.pi * 100, rel=1e-15)
    a = math.hypot(20, 20)
    assert result.area("E") == pytest.approx(math.pi * a * a * 0.25, rel=1e-14)


def test_hatch_with_circular_hole(doc, tmp_path):
    hatch = doc.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (100, 0), (100, 50), (0, 50)], is_closed=True, flags=1)
    hatch.paths.add_edge_path(flags=16).add_arc((50, 25), 10, 0, 360)
    row = takeoff(roundtrip(doc, tmp_path)).areas[0]
    assert row.area == pytest.approx(5000 - math.pi * 100, rel=1e-14)
    assert row.perimeter == pytest.approx(300 + 20 * math.pi, rel=1e-14)


def test_hatch_edge_path_rounded_rectangle_any_edge_order(doc, tmp_path):
    """Lines + quarter arcs, with one line reversed: the loop must still chain correctly."""
    w, h, r = 100.0, 60.0, 10.0
    path = doc.modelspace().add_hatch().paths.add_edge_path()
    path.add_line((r, 0), (w - r, 0))
    path.add_arc((w - r, r), r, 270, 360)
    path.add_line((w, h - r), (w, r))  # reversed on purpose
    path.add_arc((w - r, h - r), r, 0, 90)
    path.add_line((w - r, h), (r, h))
    path.add_arc((r, h - r), r, 90, 180)
    path.add_line((0, h - r), (0, r))
    path.add_arc((r, r), r, 180, 270)
    result = takeoff(roundtrip(doc, tmp_path))
    assert result.area() == pytest.approx(w * h - (4 - math.pi) * r * r, rel=1e-14)
    assert result.perimeter() == pytest.approx(2 * (w - 2 * r) + 2 * (h - 2 * r) + 2 * math.pi * r, rel=1e-14)


def test_hatch_clockwise_arc_edge(doc, tmp_path):
    path = doc.modelspace().add_hatch().paths.add_edge_path()
    path.add_line((10, 0), (-10, 0))
    path.add_arc((0, 0), 10, 0, 180, ccw=False)  # runs clockwise from (-10, 0) over the top to (10, 0)
    assert takeoff(roundtrip(doc, tmp_path)).area() == pytest.approx(50 * math.pi, rel=1e-14)


def test_hatch_with_elliptical_hole(doc, tmp_path):
    hatch = doc.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (200, 0), (200, 100), (0, 100)], is_closed=True, flags=1)
    hatch.paths.add_edge_path().add_ellipse((100, 50), major_axis=(40, 0), ratio=0.5)
    assert takeoff(roundtrip(doc, tmp_path)).area() == pytest.approx(20000 - math.pi * 40 * 20, rel=1e-14)


@pytest.mark.parametrize("style, expected", [(0, 10000 - 3600 + 400), (1, 10000 - 3600), (2, 10000)])
def test_hatch_island_styles(doc, style, expected):
    """Outer 100x100, hole 60x60, island 20x20 inside the hole."""
    hatch = doc.modelspace().add_hatch(dxfattribs={"hatch_style": style})
    for size in (100, 60, 20):
        lo, hi = (100 - size) / 2, (100 + size) / 2
        hatch.paths.add_polyline_path([(lo, lo), (hi, lo), (hi, hi), (lo, hi)], is_closed=True)
    assert takeoff(doc).area() == pytest.approx(expected, rel=1e-14)


def test_closed_spline_area_is_approximate(doc):
    spline = doc.modelspace().add_spline()
    spline.apply_construction_tool(rational_bspline_from_arc(center=(0, 0), radius=10, start_angle=0, end_angle=360))
    row = takeoff(doc).areas[0]
    assert row.approximate
    assert row.area == pytest.approx(math.pi * 100, rel=1e-5)
