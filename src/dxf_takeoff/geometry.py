"""Exact geometry primitives: straight segments and elliptic arcs.

Every curve dxf-takeoff measures is broken down into two kinds of pieces:

* :class:`Segment` - a straight line from `start` to `end`;
* :class:`EllipticArc` - ``p(t) = center + a*cos(t) + b*sin(t)`` for ``t`` in
  ``[t0, t1]``.

Circles, arcs, polyline bulges and ellipses are all elliptic arcs, and an
elliptic arc stays an elliptic arc under *any* affine transformation (block
scaling, rotation, mirroring, non-uniform scaling).  Areas are therefore exact
closed-form expressions (Green's theorem).  Lengths are exact for segments and
circular arcs; the length of a non-circular arc is an elliptic integral, which
is computed by adaptive Gauss-Legendre quadrature to about 1e-12 relative error.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ezdxf.math import Matrix44, Vec3

TAU = 2.0 * math.pi


def _legendre(n: int, x: float) -> tuple[float, float]:
    """Legendre polynomial P_n(x) and its derivative."""
    p0, p1 = 1.0, x
    for k in range(2, n + 1):
        p0, p1 = p1, ((2 * k - 1) * x * p1 - (k - 1) * p0) / k
    return p1, n * (x * p1 - p0) / (x * x - 1.0)


def _gauss_legendre(n: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Nodes and weights of the n-point Gauss-Legendre rule on [-1, 1]."""
    nodes, weights = [], []
    for i in range(1, n + 1):
        x = math.cos(math.pi * (i - 0.25) / (n + 0.5))
        for _ in range(100):
            p, dp = _legendre(n, x)
            dx = p / dp
            x -= dx
            if abs(dx) < 1e-16:
                break
        _, dp = _legendre(n, x)
        nodes.append(x)
        weights.append(2.0 / ((1.0 - x * x) * dp * dp))
    return tuple(nodes), tuple(weights)


_GL_X, _GL_W = _gauss_legendre(10)


def _gl(f: Callable[[float], float], lo: float, hi: float) -> float:
    half, mid = 0.5 * (hi - lo), 0.5 * (hi + lo)
    return half * sum(w * f(mid + half * x) for x, w in zip(_GL_X, _GL_W))


def integrate(f: Callable[[float], float], lo: float, hi: float, rel_tol: float = 1e-12) -> float:
    """Adaptive Gauss-Legendre quadrature of a smooth function over [lo, hi]."""
    if lo == hi:
        return 0.0
    sign = 1.0
    if hi < lo:
        lo, hi, sign = hi, lo, -1.0
    width = hi - lo
    edges = [lo + width * i / 8 for i in range(9)]
    stack = [(a, b, _gl(f, a, b)) for a, b in zip(edges, edges[1:])]
    tol = rel_tol * max(abs(sum(s[2] for s in stack)), 1e-300)
    total = 0.0
    while stack:
        a, b, whole = stack.pop()
        mid = 0.5 * (a + b)
        left, right = _gl(f, a, mid), _gl(f, mid, b)
        if abs(left + right - whole) <= tol * (b - a) / width or (b - a) < width * 1e-12:
            total += left + right
        else:
            stack.append((a, mid, left))
            stack.append((mid, b, right))
    return sign * total


@dataclass(frozen=True)
class Segment:
    """Straight line piece."""

    start: Vec3
    end: Vec3

    def length(self) -> float:
        return self.start.distance(self.end)

    def vector_area(self, origin: Vec3) -> Vec3:
        """Contribution to the loop integral 1/2 * (p x dp), relative to `origin`."""
        return (self.start - origin).cross(self.end - origin) * 0.5

    def transform(self, m: Matrix44) -> Segment:
        return Segment(m.transform(self.start), m.transform(self.end))

    def reversed(self) -> Segment:
        return Segment(self.end, self.start)

    def points(self) -> list[Vec3]:
        """Polygon points of the piece, without the end point."""
        return [self.start]


@dataclass(frozen=True)
class EllipticArc:
    """Elliptic (or circular) arc ``center + a*cos(t) + b*sin(t)``, t from `t0` to `t1`.

    `a` and `b` are conjugate semi-diameters; for a circle of radius r they are
    perpendicular vectors of length r.  `t1` may be smaller than `t0` (the arc
    then runs clockwise in its parameter space).
    """

    center: Vec3
    a: Vec3
    b: Vec3
    t0: float
    t1: float

    def point(self, t: float) -> Vec3:
        return self.center + self.a * math.cos(t) + self.b * math.sin(t)

    @property
    def start(self) -> Vec3:
        return self.point(self.t0)

    @property
    def end(self) -> Vec3:
        return self.point(self.t1)

    @property
    def is_circular(self) -> bool:
        a2, b2 = self.a.dot(self.a), self.b.dot(self.b)
        return math.isclose(a2, b2, rel_tol=1e-12) and abs(self.a.dot(self.b)) <= 1e-12 * a2

    def length(self) -> float:
        a2, b2, ab = self.a.dot(self.a), self.b.dot(self.b), self.a.dot(self.b)
        if self.is_circular:
            return math.sqrt(a2) * abs(self.t1 - self.t0)

        def speed(t: float) -> float:  # |p'(t)|
            s, c = math.sin(t), math.cos(t)
            return math.sqrt(max(a2 * s * s - 2.0 * ab * s * c + b2 * c * c, 0.0))

        return abs(integrate(speed, self.t0, self.t1))

    def vector_area(self, origin: Vec3) -> Vec3:
        """Exact value of 1/2 * integral(p x p' dt), relative to `origin`."""
        c, a, b, t0, t1 = self.center - origin, self.a, self.b, self.t0, self.t1
        return (
            c.cross(a) * (math.cos(t1) - math.cos(t0))
            + c.cross(b) * (math.sin(t1) - math.sin(t0))
            + a.cross(b) * (t1 - t0)
        ) * 0.5

    def transform(self, m: Matrix44) -> EllipticArc:
        return EllipticArc(
            m.transform(self.center),
            m.transform_direction(self.a),
            m.transform_direction(self.b),
            self.t0,
            self.t1,
        )

    def reversed(self) -> EllipticArc:
        return EllipticArc(self.center, self.a, self.b, self.t1, self.t0)

    def points(self) -> list[Vec3]:
        """Polygon points (64 per full turn), without the end point."""
        n = max(4, math.ceil(abs(self.t1 - self.t0) / TAU * 64))
        step = (self.t1 - self.t0) / n
        return [self.point(self.t0 + i * step) for i in range(n)]


Piece = Segment | EllipticArc


def ccw_sweep(start: float, end: float, full: float = TAU) -> float:
    """Counter-clockwise sweep from `start` to `end`; equal angles mean a full turn."""
    span = (end - start) % full
    return full if span <= full * 1e-10 else span


def bulge_piece(p0: Vec3, p1: Vec3, bulge: float) -> Piece:
    """Polyline segment from `p0` to `p1` (same z); a non-zero bulge makes it an exact arc.

    bulge = tan(sweep / 4); positive bulges run counter-clockwise.
    """
    if abs(bulge) < 1e-12 or p0.isclose(p1, abs_tol=1e-12):
        return Segment(p0, p1)
    d = p1 - p0
    center = (p0 + p1) * 0.5 + Vec3(-d.y, d.x, 0.0) * ((1.0 - bulge * bulge) / (4.0 * bulge))
    radius = math.hypot(p0.x - center.x, p0.y - center.y)
    start = math.atan2(p0.y - center.y, p0.x - center.x)
    sweep = 4.0 * math.atan(bulge)
    return EllipticArc(center, Vec3(radius, 0, 0), Vec3(0, radius, 0), start, start + sweep)


def polyline_pieces(points: Sequence[Vec3], bulges: Sequence[float], closed: bool) -> list[Piece]:
    """Pieces of a polyline given its vertices and per-vertex bulges."""
    n = len(points)
    if n < 2:
        return []
    count = n if closed else n - 1
    return [bulge_piece(points[i], points[(i + 1) % n], bulges[i]) for i in range(count)]


def loop_length(pieces: Sequence[Piece]) -> float:
    return math.fsum(p.length() for p in pieces)


def loop_vector_area(pieces: Sequence[Piece]) -> Vec3:
    """Vector area of a closed loop; gaps between pieces are bridged by straight lines.

    For a planar loop its magnitude is the enclosed area and its direction is
    the loop normal (right-hand rule).  The first point is used as origin to
    avoid cancellation errors far away from (0, 0).
    """
    if not pieces:
        return Vec3()
    origin = pieces[0].start
    total = Vec3()
    prev_end = pieces[-1].end
    for piece in pieces:
        total += Segment(prev_end, piece.start).vector_area(origin)
        total += piece.vector_area(origin)
        prev_end = piece.end
    return total


def reverse_chain(pieces: Sequence[Piece]) -> list[Piece]:
    return [p.reversed() for p in reversed(pieces)]


def chain_loops(units: Sequence[Sequence[Piece]], tol: float) -> list[list[Piece]]:
    """Join edges (each a short chain of pieces) head-to-tail into closed loops.

    Edges are reversed where needed so that every loop has one consistent
    direction, which Green's theorem requires.  A new loop starts once the
    current one is closed.
    """
    loops: list[list[Piece]] = []
    cur: list[Piece] = []
    for unit in units:
        if not unit:
            continue
        if cur and cur[0].start.isclose(cur[-1].end, abs_tol=tol):
            loops.append(cur)
            cur = []
        if not cur:
            cur = list(unit)
            continue
        start, end = cur[0].start, cur[-1].end
        u_start, u_end = unit[0].start, unit[-1].end
        if end.isclose(u_start, abs_tol=tol):
            cur.extend(unit)
        elif end.isclose(u_end, abs_tol=tol):
            cur.extend(reverse_chain(unit))
        elif start.isclose(u_end, abs_tol=tol):
            cur = list(unit) + cur
        elif start.isclose(u_start, abs_tol=tol):
            cur = reverse_chain(cur) + list(unit)
        else:  # gap: keep the order, the gap is closed by a straight line
            cur.extend(unit)
    if cur:
        loops.append(cur)
    return loops


def loop_polygon(pieces: Sequence[Piece]) -> list[tuple[float, float]]:
    """2D polygon (x, y) approximating a loop, for point-in-polygon tests."""
    return [(p.x, p.y) for piece in pieces for p in piece.points()]


def polygon_area(poly: Sequence[tuple[float, float]]) -> float:
    """Signed shoelace area of a 2D polygon."""
    if len(poly) < 3:
        return 0.0
    x0, y0 = poly[0]
    return 0.5 * math.fsum(
        (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        for (x1, y1), (x2, y2) in zip(poly[1:], poly[2:])
    )


def point_in_polygon(x: float, y: float, poly: Sequence[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test (even-odd rule)."""
    inside = False
    xj, yj = poly[-1]
    for xi, yi in poly:
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        xj, yj = xi, yi
    return inside


def nesting_depths(polys: Sequence[Sequence[tuple[float, float]]]) -> list[int]:
    """For each polygon, the number of other polygons that contain it.

    Containment is decided by a majority vote of sample points on the polygon,
    so loops that touch at a vertex are still classified correctly.
    """
    boxes = [
        (min(x for x, _ in p), min(y for _, y in p), max(x for x, _ in p), max(y for _, y in p))
        if p else (0.0, 0.0, 0.0, 0.0)
        for p in polys
    ]
    areas = [abs(polygon_area(p)) for p in polys]
    depths = [0] * len(polys)
    for i, poly in enumerate(polys):
        if len(poly) < 3:
            continue
        step = max(1, len(poly) // 9)
        samples = poly[::step][:9]
        for j, other in enumerate(polys):
            if i == j or len(other) < 3 or areas[j] <= areas[i]:
                continue
            bi, bj = boxes[i], boxes[j]
            pad = 1e-7 * (bj[2] - bj[0] + bj[3] - bj[1])
            if (bi[0] < bj[0] - pad or bi[1] < bj[1] - pad
                    or bi[2] > bj[2] + pad or bi[3] > bj[3] + pad):
                continue
            inside = sum(point_in_polygon(x, y, other) for x, y in samples)
            if 2 * inside > len(samples):
                depths[i] += 1
    return depths


def similarity_scale(m: Matrix44 | None) -> float | None:
    """Scale factor if `m` is a similarity (rotation/mirror + uniform scale), else None."""
    if m is None:
        return 1.0
    ux, uy, uz = m.ux, m.uy, m.uz
    s2 = ux.dot(ux)
    if not (math.isclose(uy.dot(uy), s2, rel_tol=1e-12) and math.isclose(uz.dot(uz), s2, rel_tol=1e-12)):
        return None
    eps = 1e-12 * s2
    if abs(ux.dot(uy)) > eps or abs(ux.dot(uz)) > eps or abs(uy.dot(uz)) > eps:
        return None
    return math.sqrt(s2)
