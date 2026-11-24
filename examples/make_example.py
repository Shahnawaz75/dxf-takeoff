"""Generate examples/tank_farm.dxf: a small tank-farm piping plan with known quantities.

    python examples/make_example.py

Units are millimetres ($INSUNITS = 4).  The plan has three storage tanks in a
bund (dike), product lines by size with long-radius bends (polyline bulges),
a pump room, cooling water, a fire water ring main, a drain channel drawn as
a spline, valves as blocks with TAG/SIZE attributes (one valve type is a
dynamic block, stored as anonymous *U blocks), pipe supports as a MINSERT
array, and an abandoned route on a frozen layer.

`expected_mm()` computes key quantities analytically, independent of
dxf-takeoff; the test suite compares both.
"""

from __future__ import annotations

import math
from pathlib import Path

import ezdxf

HERE = Path(__file__).resolve().parent
DXF = HERE / "tank_farm.dxf"

DIKE = (0.0, 0.0, 50_000.0, 32_000.0, 2_000.0)  # x0, y0, x1, y1, corner radius (inner face of bund wall)
TANKS = [("T-101", 12_000.0, 16_000.0, 7_000.0), ("T-102", 30_000.0, 16_000.0, 7_000.0),
         ("T-103", 44_000.0, 16_000.0, 4_000.0)]
PUMP_ROOM = (58_000.0, 2_000.0, 70_000.0, 12_000.0)
PUMPS = [("P-101A", 62_000.0, 4_500.0), ("P-101B", 62_000.0, 7_000.0), ("P-102", 62_000.0, 9_500.0)]
RING = (-3_000.0, -3_000.0, 53_000.0, 35_000.0, 5_000.0)  # fire water ring main, 3 m outside the bund
RING_GAP = 2_000.0  # open at the east side where the supply ties in

# Pipe routes: layer -> list of (corner points, bend radius)
ROUTES: dict[str, list[tuple[list[tuple[float, float]], float]]] = {
    "P-PROD-200": [
        ([(12_000, 9_000), (12_000, 3_000), (56_000, 3_000), (56_000, 4_500), (61_000, 4_500)], 300.0),
        ([(30_000, 9_000), (30_000, 3_600), (55_400, 3_600), (55_400, 7_000), (61_000, 7_000)], 300.0),
        ([(66_000, 4_500), (66_000, 18_000)], 300.0),  # discharge header to the loading bay
    ],
    "P-PROD-150": [
        ([(44_000, 12_000), (44_000, 4_200), (54_800, 4_200), (54_800, 9_500), (61_000, 9_500)], 225.0),
        ([(63_000, 4_500), (66_000, 4_500)], 225.0),
        ([(63_000, 7_000), (66_000, 7_000)], 225.0),
        ([(63_000, 9_500), (66_000, 9_500)], 225.0),
    ],
    "P-CW-100": [([(74_000, 11_000), (59_500, 11_000)], 150.0)],
    "P-CW-50": [([(xb, 11_000), (xb, yp + 900), (62_000, yp + 900)], 75.0)
                for xb, (_, _, yp) in zip((60_900, 60_500, 60_100), PUMPS)],
}
DRAIN = [(46_000, 1_500), (49_000, -500), (51_500, -1_500), (54_000, -4_500), (57_000, -6_000)]

LAYERS = {  # name: (rgb, lineweight in 1/100 mm)
    "P-PROD-200": ((214, 39, 40), 70), "P-PROD-150": ((255, 127, 14), 50),
    "P-CW-100": ((31, 119, 180), 50), "P-CW-50": ((23, 190, 207), 35),
    "P-FW-150": ((148, 103, 189), 50), "P-DRAIN": ((44, 160, 44), 50),
    "P-VALVE": ((40, 40, 40), 25), "SYMBOL": ((40, 40, 40), 25), "S-SUPPORT": ((120, 120, 120), 18),
    "FIRE": ((148, 103, 189), 25), "EQUIP-TANK": ((90, 90, 90), 35), "EQUIP-PUMP": ((90, 90, 90), 25),
    "C-DIKE-WALL": ((140, 86, 75), 70), "C-DIKE-FLOOR": ((236, 226, 198), 13),
    "A-PUMPROOM": ((70, 70, 70), 50), "A-FLOOR": ((205, 220, 235), 13), "TEXT": ((30, 30, 30), 18),
    "Z-DEMOLISHED": ((180, 180, 180), 25),
}


def fillet(points: list[tuple[float, float]], radius: float) -> list[tuple[float, float, float]]:
    """Polyline vertices (x, y, bulge) through `points` with arcs of `radius` at the corners."""
    out = [(*points[0], 0.0)]
    for prev, corner, nxt in zip(points, points[1:], points[2:]):
        d1 = ezdxf.math.Vec2(corner) - ezdxf.math.Vec2(prev)
        d2 = ezdxf.math.Vec2(nxt) - ezdxf.math.Vec2(corner)
        turn = math.atan2(d1.x * d2.y - d1.y * d2.x, d1.dot(d2))
        t = radius * math.tan(abs(turn) / 2)
        a = ezdxf.math.Vec2(corner) - d1.normalize(t)
        b = ezdxf.math.Vec2(corner) + d2.normalize(t)
        out += [(a.x, a.y, math.tan(turn / 4)), (b.x, b.y, 0.0)]
    return out + [(*points[-1], 0.0)]


def filleted_length(points: list[tuple[float, float]], radius: float) -> float:
    """Exact centreline length of `fillet(points, radius)`, computed independently."""
    total = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
    for prev, corner, nxt in zip(points, points[1:], points[2:]):
        a1 = math.atan2(corner[1] - prev[1], corner[0] - prev[0])
        a2 = math.atan2(nxt[1] - corner[1], nxt[0] - corner[0])
        turn = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
        total += radius * turn - 2 * radius * math.tan(turn / 2)
    return total


def rounded_rect(x0: float, y0: float, x1: float, y1: float, r: float) -> list[tuple[float, float, float]]:
    """Closed counter-clockwise rectangle with corner arcs of radius r, as (x, y, bulge)."""
    b = math.tan(math.pi / 8)  # quarter-circle bulge
    return [(x0 + r, y0, 0), (x1 - r, y0, b), (x1, y0 + r, 0), (x1, y1 - r, b),
            (x1 - r, y1, 0), (x0 + r, y1, b), (x0, y1 - r, 0), (x0, y0 + r, b)]


def rounded_rect_perimeter(x0: float, y0: float, x1: float, y1: float, r: float) -> float:
    return 2 * (x1 - x0 - 2 * r) + 2 * (y1 - y0 - 2 * r) + 2 * math.pi * r


def expected_mm() -> dict[str, float]:
    """Key quantities in mm / mm2, from plain geometry (not from dxf-takeoff)."""
    x0, y0, x1, y1, r = DIKE
    gross = (x1 - x0) * (y1 - y0) - (4 - math.pi) * r * r
    px0, py0, px1, py1 = PUMP_ROOM
    return {
        **{layer: sum(filleted_length(pts, rad) for pts, rad in routes) for layer, routes in ROUTES.items()},
        "P-FW-150": rounded_rect_perimeter(*RING) - RING_GAP,
        "C-DIKE-WALL": rounded_rect_perimeter(*DIKE),
        "C-DIKE-FLOOR area": gross - sum(math.pi * t[3] ** 2 for t in TANKS),
        "A-FLOOR area": (px1 - px0) * (py1 - py0),
        "EQUIP-TANK perimeter": sum(2 * math.pi * t[3] for t in TANKS),
    }


def _symbols(doc: ezdxf.document.Drawing) -> list[str]:
    """Block definitions (linework on layer SYMBOL, attributes TAG and SIZE).

    Returns the names of the anonymous blocks of the dynamic butterfly valve.
    """
    def valve(name: str, body) -> None:
        blk = doc.blocks.new(name)
        body(blk)
        blk.add_attdef("TAG", (0, 450), dxfattribs={"height": 250, "layer": "TEXT"})
        blk.add_attdef("SIZE", (0, -650), dxfattribs={"height": 200, "layer": "TEXT"})

    sym = {"layer": "SYMBOL"}
    def bowtie(b, w: float, h: float) -> None:  # two closed triangles meeting at the centre
        b.add_lwpolyline([(-w, -h), (0, 0), (-w, h)], close=True, dxfattribs=sym)
        b.add_lwpolyline([(w, -h), (0, 0), (w, h)], close=True, dxfattribs=sym)

    valve("GATE-VALVE", lambda b: bowtie(b, 300, 250))
    valve("CHECK-VALVE", lambda b: (b.add_lwpolyline([(-300, -250), (-300, 250), (300, 0)], close=True,
                                                     dxfattribs=sym),
                                    b.add_line((300, -250), (300, 250), dxfattribs=sym)))
    valve("BALL-VALVE", lambda b: (bowtie(b, 250, 200), b.add_circle((0, 0), 90, dxfattribs=sym)))
    # dynamic block: AutoCAD stores each stretched state as an anonymous *U block that points
    # back to the dynamic block definition through AcDbBlockRepBTag xdata
    valve("BUTTERFLY-VALVE", lambda b: (b.add_line((0, -300), (0, 300), dxfattribs=sym),
                                        b.add_circle((0, 0), 150, dxfattribs=sym)))
    doc.appids.new("AcDbBlockRepBTag")
    handle = doc.blocks.get("BUTTERFLY-VALVE").block_record.dxf.handle
    anonymous = []
    for half in (250, 350):
        anon = doc.blocks.new_anonymous_block("U")
        anon.add_line((0, -half), (0, half), dxfattribs=sym)
        anon.add_circle((0, 0), 150, dxfattribs=sym)
        anon.block_record.set_xdata("AcDbBlockRepBTag", [(1070, 1), (1005, handle)])
        anonymous.append(anon.name)
    pump = doc.blocks.new("PUMP")
    pump.add_circle((0, 0), 600, dxfattribs=sym)
    pump.add_line((-600, -700), (600, -700), dxfattribs=sym)
    pump.add_attdef("TAG", (900, -100), dxfattribs={"height": 250, "layer": "TEXT"})
    hydrant = doc.blocks.new("HYDRANT")
    hydrant.add_circle((0, 0), 400, dxfattribs=sym)
    hydrant.add_line((-400, 0), (400, 0), dxfattribs=sym)
    doc.blocks.new("PIPE-SUPPORT").add_line((0, -1_000), (0, 1_000), dxfattribs=sym)
    return anonymous


def build() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for name, (rgb, lw) in LAYERS.items():
        layer = doc.layers.add(name, lineweight=lw)
        layer.rgb = rgb
    doc.layers.get("Z-DEMOLISHED").freeze()
    butterfly = _symbols(doc)
    msp = doc.modelspace()
    text = {"layer": "TEXT", "height": 1_600}

    # civil: bund wall and bund floor (hatch with the tank footprints as holes)
    msp.add_lwpolyline(rounded_rect(*DIKE), format="xyb", close=True, dxfattribs={"layer": "C-DIKE-WALL"})
    floor = msp.add_hatch(dxfattribs={"layer": "C-DIKE-FLOOR", "true_color": 0xECE2C6})
    floor.paths.add_polyline_path(rounded_rect(*DIKE), is_closed=True, flags=1)
    for tag, x, y, r in TANKS:
        floor.paths.add_edge_path(flags=0).add_arc((x, y), r, 0, 360)
        msp.add_circle((x, y), r, dxfattribs={"layer": "EQUIP-TANK"})
        msp.add_text(tag, dxfattribs=text).set_placement((x, y), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    msp.add_text("BUND / DIKE", dxfattribs={**text, "height": 1_200}).set_placement(
        (25_000, 29_000), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    # pump room: wall outline plus floor hatch, three pumps
    px0, py0, px1, py1 = PUMP_ROOM
    room = [(px0, py0), (px1, py0), (px1, py1), (px0, py1)]
    msp.add_lwpolyline(room, close=True, dxfattribs={"layer": "A-PUMPROOM"})
    msp.add_hatch(dxfattribs={"layer": "A-FLOOR", "true_color": 0xCDDCEB}).paths.add_polyline_path(room, is_closed=True)
    msp.add_text("PUMP ROOM", dxfattribs={**text, "height": 1_000}).set_placement(
        (64_000, 600), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    for tag, x, y in PUMPS:
        msp.add_blockref("PUMP", (x, y), dxfattribs={"layer": "EQUIP-PUMP"}).add_auto_attribs({"TAG": tag})

    # piping
    for layer, routes in ROUTES.items():
        for points, radius in routes:
            msp.add_lwpolyline(fillet(points, radius), format="xyb", dxfattribs={"layer": layer})
    rx0, ry0, rx1, ry1, rr = RING
    ring = rounded_rect(rx0, ry0, rx1, ry1, rr)  # starts at the south-west, runs counter-clockwise
    half_gap = RING_GAP / 2
    mid = (ry0 + ry1) / 2
    east = [(rx1, mid + half_gap, 0.0)] + ring[3:] + ring[:3] + [(rx1, mid - half_gap, 0.0)]
    msp.add_lwpolyline(east, format="xyb", dxfattribs={"layer": "P-FW-150"})
    msp.add_spline(fit_points=DRAIN, dxfattribs={"layer": "P-DRAIN"})
    msp.add_text("DRAIN TO INTERCEPTOR", dxfattribs={**text, "height": 900}).set_placement(
        (57_200, -6_000), align=ezdxf.enums.TextEntityAlignment.MIDDLE_LEFT)
    msp.add_lwpolyline([(20_000, 9_000), (20_000, 1_000), (40_000, 1_000)], dxfattribs={"layer": "Z-DEMOLISHED"})

    # valves: (block, x, y, rotation, TAG, SIZE)
    valves = [
        ("GATE-VALVE", 12_000, 6_000, 90, "XV-101", "200"), ("GATE-VALVE", 30_000, 6_000, 90, "XV-102", "200"),
        ("GATE-VALVE", 44_000, 8_000, 90, "XV-103", "150"), ("GATE-VALVE", 59_500, 4_500, 0, "HV-111", "200"),
        ("GATE-VALVE", 59_500, 7_000, 0, "HV-112", "200"), ("GATE-VALVE", 59_500, 9_500, 0, "HV-113", "150"),
        ("CHECK-VALVE", 64_500, 4_500, 0, "NRV-121", "150"), ("CHECK-VALVE", 64_500, 7_000, 0, "NRV-122", "150"),
        ("CHECK-VALVE", 64_500, 9_500, 0, "NRV-123", "150"),
        ("BALL-VALVE", 60_900, 9_000, 90, "BV-131", "50"), ("BALL-VALVE", 60_500, 9_800, 90, "BV-132", "50"),
        ("BALL-VALVE", 60_100, 10_400, 90, "BV-133", "50"),
    ]
    for name, x, y, rot, tag, size in valves:
        ref = msp.add_blockref(name, (x, y), dxfattribs={"layer": "P-VALVE", "rotation": rot})
        ref.add_auto_attribs({"TAG": tag, "SIZE": size})
    for anon, x, tag in zip(butterfly, (73_000, 67_500), ("BFV-141", "BFV-142")):
        ref = msp.add_blockref(anon, (x, 11_000), dxfattribs={"layer": "P-VALVE"})
        ref.add_attrib("TAG", tag, (x, 11_450), dxfattribs={"height": 250, "layer": "TEXT"})
        ref.add_attrib("SIZE", "100", (x, 10_350), dxfattribs={"height": 200, "layer": "TEXT"})

    for x, y in ((25_000, ry0), (25_000, ry1), (rx0, mid), (rx1, mid + 6_000)):
        msp.add_blockref("HYDRANT", (x, y), dxfattribs={"layer": "FIRE"})
    # 9 pipe supports every 4 m under the product lines inside the bund, as one MINSERT array
    supports = msp.add_blockref("PIPE-SUPPORT", (14_000, 3_600), dxfattribs={"layer": "S-SUPPORT"})
    supports.grid(size=(1, 9), spacing=(0, 4_000))
    msp.add_text("TANK FARM T-100 - PIPING PLAN (units mm)",
                 dxfattribs={**text, "height": 1_500}).set_placement((-3_000, 37_000))
    return doc


if __name__ == "__main__":
    ezdxf.options.write_fixed_meta_data_for_testing = True  # reproducible file
    build().saveas(DXF)
    print(f"wrote {DXF.name}")
    for key, value in expected_mm().items():
        print(f"{key:22s} {value:16,.3f}")
