"""Block references: transforms, MINSERT, dynamic blocks, attributes, nested counts."""

import math

import pytest
from conftest import ellipse_perimeter, ramanujan2, roundtrip
from ezdxf.math import Matrix44, Vec3

from dxf_takeoff import takeoff


def _child_block(doc):
    """10x20 closed rectangle (perimeter 60, area 200), circle r=1, line of length 5."""
    child = doc.blocks.new("CHILD", base_point=(3, 7))
    child.add_lwpolyline([(0, 0), (10, 0), (10, 20), (0, 20)], close=True, dxfattribs={"layer": "RECT"})
    child.add_circle((50, 50), 1, dxfattribs={"layer": "CIRC"})
    child.add_line((0, 0), (3, 4), dxfattribs={"layer": "LINE"})
    return child


def test_nested_blocks_scale_and_rotation(doc, tmp_path):
    _child_block(doc)
    parent = doc.blocks.new("PARENT")
    parent.add_blockref("CHILD", (100, 50), dxfattribs={"xscale": 2, "yscale": 2, "zscale": 2, "rotation": 30})
    doc.modelspace().add_blockref("PARENT", (1000, 0), dxfattribs={"rotation": 45})
    result = takeoff(roundtrip(doc, tmp_path))
    assert result.length("RECT") == pytest.approx(120, rel=1e-14)
    assert result.length("CIRC") == pytest.approx(4 * math.pi, rel=1e-14)
    assert result.length("LINE") == pytest.approx(10, rel=1e-14)
    assert result.area("RECT") == pytest.approx(800, rel=1e-13)
    assert result.area("CIRC") == pytest.approx(4 * math.pi, rel=1e-13)


def test_three_levels_multiply_scales(doc):
    _child_block(doc)
    doc.blocks.new("PARENT").add_blockref("CHILD", (0, 0), dxfattribs={"xscale": 2, "yscale": 2, "zscale": 2})
    doc.blocks.new("TOP").add_blockref("PARENT", (5, 5), dxfattribs={"xscale": 3, "yscale": 3, "zscale": 3,
                                                                     "rotation": 10})
    doc.modelspace().add_blockref("TOP", (0, 0))
    result = takeoff(doc)
    assert result.length("RECT") == pytest.approx(360, rel=1e-13)
    assert result.area("RECT") == pytest.approx(200 * 36, rel=1e-13)


def test_non_uniform_scale_turns_circle_into_ellipse(doc):
    doc.blocks.new("C").add_circle((0, 0), 10)
    doc.modelspace().add_blockref("C", (0, 0), dxfattribs={"xscale": 2, "yscale": 1, "rotation": 30})
    result = takeoff(doc)
    # exact series reference; Ramanujan II agrees to ~4e-10 for a/b = 2
    assert result.length() == pytest.approx(ellipse_perimeter(20, 10), rel=1e-11)
    assert result.length() == pytest.approx(ramanujan2(20, 10), rel=1e-9)
    assert result.area() == pytest.approx(math.pi * 20 * 10, rel=1e-14)


def test_non_uniform_scale_on_arc_and_bulge(doc):
    block = doc.blocks.new("HALF")
    block.add_arc((0, 0), 10, 0, 180, dxfattribs={"layer": "ARC"})
    block.add_lwpolyline([(-10, 0, 1.0), (10, 0, 0)], format="xyb", dxfattribs={"layer": "BULGE"})
    doc.modelspace().add_blockref("HALF", (0, 0), dxfattribs={"xscale": 1, "yscale": 3})
    result = takeoff(doc)
    half = ellipse_perimeter(30, 10) / 2  # x = 10 cos t, y = 30 sin t over half a turn
    assert result.length("ARC") == pytest.approx(half, rel=1e-11)
    assert result.length("BULGE") == pytest.approx(half, rel=1e-11)


def test_rotation_inside_non_uniform_scale_is_a_full_affine_transform(doc):
    doc.blocks.new("R").add_lwpolyline([(0, 0), (10, 0), (10, 20), (0, 20)], close=True)
    doc.blocks.new("S").add_blockref("R", (0, 0), dxfattribs={"rotation": 45})
    doc.modelspace().add_blockref("S", (0, 0), dxfattribs={"xscale": 2, "yscale": 1})
    m = Matrix44.z_rotate(math.radians(45)) @ Matrix44.scale(2, 1, 1)
    corners = [m.transform(Vec3(p)) for p in [(0, 0), (10, 0), (10, 20), (0, 20)]]
    expected = sum(a.distance(b) for a, b in zip(corners, corners[1:] + corners[:1]))
    result = takeoff(doc)
    assert result.length() == pytest.approx(expected, rel=1e-14)
    assert result.area() == pytest.approx(200 * 2, rel=1e-14)  # area x det = sx * sy


def test_mirrored_insert_keeps_positive_quantities(doc):
    _child_block(doc)
    doc.modelspace().add_blockref("CHILD", (0, 0), dxfattribs={"xscale": -1})
    result = takeoff(doc)
    assert result.length("RECT") == pytest.approx(60, rel=1e-15)
    assert result.area("RECT") == pytest.approx(200, rel=1e-14)


def test_minsert_3x2_counts_every_instance(doc):
    doc.blocks.new("SUPPORT").add_line((0, 0), (10, 0))
    doc.modelspace().add_blockref("SUPPORT", (0, 0)).grid(size=(2, 3), spacing=(100, 50))
    result = takeoff(doc)
    assert result.count("SUPPORT") == 6
    assert result.length() == pytest.approx(60, rel=1e-15)


def test_dynamic_block_resolves_to_effective_name(doc, tmp_path):
    real = doc.blocks.new("GATE-VALVE")
    real.add_line((0, 0), (1, 0))
    anon = doc.blocks.new_anonymous_block("U")  # what AutoCAD makes of a stretched dynamic block
    anon.add_line((0, 0), (2, 0))
    doc.appids.new("AcDbBlockRepBTag")
    anon.block_record.set_xdata("AcDbBlockRepBTag", [(1070, 1), (1005, real.block_record.dxf.handle)])
    msp = doc.modelspace()
    msp.add_blockref(anon.name, (0, 0))
    msp.add_blockref("GATE-VALVE", (5, 0))
    result = takeoff(roundtrip(doc, tmp_path))
    assert [(r.block, r.count) for r in result.blocks] == [("GATE-VALVE", 2)]


def test_group_counts_by_attribute_values(doc):
    valve = doc.blocks.new("VALVE")
    valve.add_attdef("TAG", (0, 1))
    valve.add_attdef("SIZE", (0, 0))
    msp = doc.modelspace()
    for tag, size in [("V-1", "100"), ("V-2", "100"), ("V-3", "50"), ("V-4", "100")]:
        msp.add_blockref("VALVE", (0, 0)).add_auto_attribs({"TAG": tag, "SIZE": size})
    result = takeoff(doc, group_by_attribs=["size"])
    assert [(r.block, r.attribs, r.count) for r in result.blocks] == [
        ("VALVE", {"SIZE": "50"}, 1),
        ("VALVE", {"SIZE": "100"}, 3),
    ]
    assert result.count("VALVE", SIZE="100") == 3
    assert result.count("VAL*", TAG="V-[12]") == 2


def test_nested_counts_are_optional(doc):
    doc.blocks.new("VALVE").add_line((0, 0), (1, 0))
    skid = doc.blocks.new("SKID")
    skid.add_blockref("VALVE", (0, 0))
    skid.add_blockref("VALVE", (5, 0))
    msp = doc.modelspace()
    msp.add_blockref("SKID", (0, 0))
    msp.add_blockref("SKID", (50, 0))
    msp.add_blockref("VALVE", (99, 0))
    flat = {r.block: r.count for r in takeoff(doc).blocks}
    assert flat == {"SKID": 2, "VALVE": 1}
    nested = {r.block: (r.count, r.nested) for r in takeoff(doc, nested=True).blocks}
    assert nested == {"SKID": (2, 0), "VALVE": (5, 4)}


def test_layer_zero_content_takes_the_reference_layer(doc):
    block = doc.blocks.new("FIX")
    block.add_line((0, 0), (10, 0))  # layer 0 -> inherits
    block.add_line((0, 0), (0, 7), dxfattribs={"layer": "OWN"})
    doc.modelspace().add_blockref("FIX", (0, 0), dxfattribs={"layer": "P-CW"})
    result = takeoff(doc)
    assert {r.layer: r.length for r in result.lengths} == {"OWN": 7.0, "P-CW": 10.0}


def test_no_block_geometry_still_counts(doc):
    _child_block(doc)
    doc.modelspace().add_blockref("CHILD", (0, 0))
    result = takeoff(doc, block_geometry=False)
    assert result.lengths == [] and result.count("CHILD") == 1
