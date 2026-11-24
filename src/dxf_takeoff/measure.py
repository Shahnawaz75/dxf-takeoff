"""Measure DXF entities: curve lengths, enclosed areas and hatch areas.

All results are in drawing units *after* the block transformation, i.e. in
model (or paper) space coordinates.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ezdxf.entities import DXFGraphic
from ezdxf.entities.boundary_paths import ArcEdge, EllipseEdge, LineEdge, PolylinePath, SplineEdge
from ezdxf.math import OCS, Z_AXIS, BSpline, Matrix44, Vec3, fit_points_to_cad_cv

from .geometry import (
    TAU,
    EllipticArc,
    Piece,
    Segment,
    ccw_sweep,
    chain_loops,
    loop_length,
    loop_polygon,
    loop_vector_area,
    nesting_depths,
    polyline_pieces,
    similarity_scale,
)

#: Entity types that have a length (and an area when they are closed).
CURVE_TYPES = frozenset({"LINE", "ARC", "CIRCLE", "ELLIPSE", "LWPOLYLINE", "POLYLINE", "SPLINE", "MLINE"})
#: Entity types that only have an area.
FILL_TYPES = frozenset({"HATCH", "MPOLYGON"})
#: Geometry that is not measured; it is counted and reported in the notes.
UNSUPPORTED_TYPES = frozenset({
    "3DFACE", "3DSOLID", "BODY", "HELIX", "MESH", "RAY", "REGION", "SOLID", "SURFACE",
    "TRACE", "XLINE", "EXTRUDEDSURFACE", "LOFTEDSURFACE", "PLANESURFACE",
    "REVOLVEDSURFACE", "SWEPTSURFACE",
})

#: Default spline flattening tolerance, relative to the size of the spline.
AUTO_SPLINE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Measure:
    """What one entity contributes, in drawing units after block transforms."""

    length: float | None = None  # None: no length of its own (HATCH)
    area: float | None = None  # None: not a closed shape
    perimeter: float = 0.0
    approximate: bool = False  # True if a spline had to be flattened

    def scaled(self, s: float) -> Measure:
        return Measure(
            None if self.length is None else self.length * s,
            None if self.area is None else self.area * s * s,
            self.perimeter * s,
            self.approximate,
        )


def _apply(pieces: list[Piece], m: Matrix44 | None) -> list[Piece]:
    return pieces if m is None else [p.transform(m) for p in pieces]


def _ocs(entity: DXFGraphic, m: Matrix44 | None) -> Matrix44 | None:
    """Matrix from the entity's OCS to WCS, followed by the block transform `m`."""
    extrusion = Vec3(entity.dxf.get("extrusion", Z_AXIS))
    if extrusion.isclose(Z_AXIS):
        return m
    ocs = OCS(extrusion)
    om = Matrix44.ucs(ocs.ux, ocs.uy, ocs.uz)
    return om if m is None else om @ m


def _fill_sign(style: int, depth: int) -> int:
    """+1 / -1 / 0: how a boundary loop at nesting `depth` counts for a hatch style."""
    if style == 2:  # "ignore": only the outermost boundary
        return 1 if depth == 0 else 0
    if style == 1:  # "outer": outermost area minus its direct islands
        return (1, -1)[depth] if depth < 2 else 0
    return -1 if depth % 2 else 1  # "normal": odd parity, islands alternate


def _closes(points: Sequence[Vec3]) -> bool:
    return len(points) > 2 and points[0].isclose(points[-1], rel_tol=1e-9, abs_tol=1e-9)


class Measurer:
    """Measures entities, caching block content measured under similarity transforms.

    Args:
        spline_tolerance: maximum distance between a spline and its flattened
            polyline, in drawing units; ``None`` uses 1e-6 x the spline size.
    """

    def __init__(self, spline_tolerance: float | None = None) -> None:
        self.spline_tolerance = spline_tolerance
        self._cache: dict[int, Measure | None] = {}

    def measure(self, entity: DXFGraphic, matrix: Matrix44 | None = None) -> Measure | None:
        """Measure `entity` transformed by `matrix`; ``None`` if it has no measurable geometry."""
        if matrix is None:
            return self._measure(entity, None)
        scale = similarity_scale(matrix)
        if scale is not None:
            key = id(entity)
            if key not in self._cache:
                self._cache[key] = self._measure(entity, None)
            local = self._cache[key]
            # flattened splines are re-flattened in WCS to honour the tolerance
            if local is None or not local.approximate:
                return None if local is None else local.scaled(scale)
        return self._measure(entity, matrix)

    def _measure(self, e: DXFGraphic, m: Matrix44 | None) -> Measure | None:
        if e.dxftype() in FILL_TYPES:
            return self._fill(e, m)
        curve = self._curve(e, m)
        if curve is None:
            return None
        pieces, closed, approximate = curve
        length = loop_length(pieces)
        if closed:
            return Measure(length, loop_vector_area(pieces).magnitude, length, approximate)
        return Measure(length, None, 0.0, approximate)

    def _curve(self, e: DXFGraphic, m: Matrix44 | None) -> tuple[list[Piece], bool, bool] | None:
        kind, dxf = e.dxftype(), e.dxf
        if kind == "LINE":
            return _apply([Segment(Vec3(dxf.start), Vec3(dxf.end))], m), False, False
        if kind in ("ARC", "CIRCLE"):
            r = dxf.radius
            t0, t1 = 0.0, TAU
            if kind == "ARC":
                t0 = math.radians(dxf.start_angle)
                t1 = t0 + math.radians(ccw_sweep(dxf.start_angle, dxf.end_angle, 360.0))
            arc = EllipticArc(Vec3(dxf.center), Vec3(r, 0, 0), Vec3(0, r, 0), t0, t1)
            return _apply([arc], _ocs(e, m)), kind == "CIRCLE", False
        if kind == "ELLIPSE":
            t0 = dxf.start_param
            sweep = ccw_sweep(t0, dxf.end_param)
            arc = EllipticArc(Vec3(dxf.center), Vec3(dxf.major_axis), Vec3(e.minor_axis), t0, t0 + sweep)
            return _apply([arc], m), sweep == TAU, False
        if kind == "LWPOLYLINE":
            z = float(dxf.elevation)
            vertices = [(Vec3(float(x), float(y), z), float(b)) for x, y, b in e.get_points("xyb")]
            return self._poly(vertices, e.closed, _ocs(e, m))
        if kind == "POLYLINE":
            # skip spline-frame control points (vertex flag 16), they are not drawn
            vertices = [v for v in e.vertices if not v.dxf.flags & 16]
            if e.is_2d_polyline:
                z = Vec3(dxf.elevation).z
                pts = [(Vec3(v.dxf.location.x, v.dxf.location.y, z), v.dxf.bulge) for v in vertices]
                return self._poly(pts, e.is_closed, _ocs(e, m))
            if e.is_3d_polyline:
                return self._poly([(Vec3(v.dxf.location), 0.0) for v in vertices], e.is_closed, m)
            return None  # polyface and polygon meshes
        if kind == "MLINE":  # length of the reference line
            return self._poly([(Vec3(v.location), 0.0) for v in e.vertices], e.is_closed, m)
        if kind == "SPLINE":
            try:
                spline = e.construction_tool()
            except (ValueError, IndexError):
                return None
            if m is not None:
                spline = spline.transform(m)  # B-splines are affine invariant
            pieces = self._flatten(spline)
            if not pieces:
                return None
            closed = bool(e.closed) or _closes([pieces[0].start, *(p.end for p in pieces)])
            return pieces, closed, True
        return None

    @staticmethod
    def _poly(vertices: list[tuple[Vec3, float]], closed: bool, m: Matrix44 | None):
        points = [p for p, _ in vertices]
        pieces = polyline_pieces(points, [b for _, b in vertices], closed)
        # a polyline whose last vertex returns to the first one encloses an area too
        return _apply(pieces, m), bool(pieces) and (closed or _closes(points)), False

    def _flatten(self, spline: BSpline) -> list[Piece]:
        tol = self.spline_tolerance
        if tol is None:
            cps = spline.control_points
            lo = Vec3(min(p.x for p in cps), min(p.y for p in cps), min(p.z for p in cps))
            hi = Vec3(max(p.x for p in cps), max(p.y for p in cps), max(p.z for p in cps))
            tol = max((hi - lo).magnitude * AUTO_SPLINE_TOLERANCE, 1e-12)
        points = list(spline.flattening(tol))
        return [Segment(a, b) for a, b in zip(points, points[1:])]

    def _fill(self, e: DXFGraphic, m: Matrix44 | None) -> Measure:
        z = Vec3(e.dxf.get("elevation") or (0, 0, 0)).z
        loops: list[list[Piece]] = []
        approximate = False
        for path in e.paths:
            if isinstance(path, PolylinePath):
                pts = [Vec3(v[0], v[1], z) for v in path.vertices]
                bulges = [float(v[2]) if len(v) > 2 else 0.0 for v in path.vertices]
                loop = polyline_pieces(pts, bulges, closed=True)
                if loop:
                    loops.append(loop)
                continue
            edges = []
            for edge in path.edges:
                pieces, flat = self._edge(edge, z)
                approximate |= flat
                edges.append(pieces)
            extent = max((abs(c) for unit in edges for p in unit for c in (*p.start.xy, *p.end.xy)), default=1.0)
            loops.extend(chain_loops(edges, 1e-8 * max(1.0, extent)))
        depths = nesting_depths([loop_polygon(loop) for loop in loops])
        style = e.dxf.get("hatch_style", 0) or 0
        full = _ocs(e, m)
        area = perimeter = 0.0
        for loop, depth in zip(loops, depths):
            sign = _fill_sign(style, depth)
            if sign:
                wcs = _apply(loop, full)
                area += sign * loop_vector_area(wcs).magnitude
                perimeter += loop_length(wcs)
        return Measure(None, max(area, 0.0), perimeter, approximate)

    def _edge(self, edge: object, z: float) -> tuple[list[Piece], bool]:
        """Pieces (in OCS) of one hatch boundary edge, in the edge's real direction."""
        if isinstance(edge, LineEdge):
            return [Segment(Vec3(edge.start.x, edge.start.y, z), Vec3(edge.end.x, edge.end.y, z))], False
        if isinstance(edge, (ArcEdge, EllipseEdge)):
            # ezdxf stores start/end in counter-clockwise order; `ccw` keeps the direction
            if isinstance(edge, ArcEdge):
                r = edge.radius
                t0 = math.radians(edge.start_angle)
                t1 = t0 + math.radians(ccw_sweep(edge.start_angle, edge.end_angle, 360.0))
                arc = EllipticArc(Vec3(edge.center.x, edge.center.y, z), Vec3(r, 0, 0), Vec3(0, r, 0), t0, t1)
            else:
                ce = edge.construction_tool()
                t0 = ce.start_param
                t1 = t0 + ccw_sweep(t0, ce.end_param)
                arc = EllipticArc(
                    Vec3(ce.center.x, ce.center.y, z),
                    Vec3(ce.major_axis.x, ce.major_axis.y, 0),
                    Vec3(ce.minor_axis.x, ce.minor_axis.y, 0),
                    t0,
                    t1,
                )
            return [arc if edge.ccw else arc.reversed()], False
        if isinstance(edge, SplineEdge):
            if edge.control_points:
                spline = BSpline(
                    [Vec3(p[0], p[1], z) for p in edge.control_points],
                    order=edge.degree + 1,
                    knots=edge.knot_values or None,
                    weights=edge.weights or None,
                )
            elif len(edge.fit_points) > 1:
                tangents = None
                if edge.start_tangent and edge.end_tangent:
                    tangents = [Vec3(edge.start_tangent), Vec3(edge.end_tangent)]
                spline = fit_points_to_cad_cv([Vec3(p[0], p[1], z) for p in edge.fit_points], tangents=tangents)
            else:
                return [], False
            return self._flatten(spline), True
        return [], False
