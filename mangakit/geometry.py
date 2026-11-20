"""Page geometry: affine transforms and paths.

Page coordinates are in *page units* (project.yaml `page.units_per_mm`), origin at
the top-left corner of the trim box, y pointing down. Bleed extends into negative
coordinates. Source-image coordinates are pixels of the original drawing.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box as _box
from shapely.ops import unary_union

Pt = tuple[float, float]


@dataclass(frozen=True)
class Affine:
    """2D affine in SVG matrix order: x' = a*x + c*y + e, y' = b*x + d*y + f."""
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @staticmethod
    def identity() -> "Affine":
        return Affine()

    @staticmethod
    def translate(tx: float, ty: float) -> "Affine":
        return Affine(1, 0, 0, 1, tx, ty)

    @staticmethod
    def scale(sx: float, sy: float | None = None) -> "Affine":
        return Affine(sx, 0, 0, sx if sy is None else sy, 0, 0)

    @staticmethod
    def rotate(deg: float, about: Pt = (0.0, 0.0)) -> "Affine":
        r = math.radians(deg)
        co, si = math.cos(r), math.sin(r)
        rot = Affine(co, si, -si, co, 0, 0)
        if about == (0.0, 0.0):
            return rot
        return Affine.translate(*about) @ rot @ Affine.translate(-about[0], -about[1])

    def __matmul__(self, o: "Affine") -> "Affine":
        """self @ o : apply o first, then self."""
        return Affine(
            self.a * o.a + self.c * o.b,
            self.b * o.a + self.d * o.b,
            self.a * o.c + self.c * o.d,
            self.b * o.c + self.d * o.d,
            self.a * o.e + self.c * o.f + self.e,
            self.b * o.e + self.d * o.f + self.f,
        )

    def then(self, o: "Affine") -> "Affine":
        return o @ self

    def apply(self, p: Sequence[float]) -> Pt:
        x, y = p
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def inverse(self) -> "Affine":
        det = self.a * self.d - self.b * self.c
        if abs(det) < 1e-12:
            raise ValueError("singular transform")
        a, b, c, d = self.d / det, -self.b / det, -self.c / det, self.a / det
        e = -(a * self.e + c * self.f)
        f = -(b * self.e + d * self.f)
        return Affine(a, b, c, d, e, f)

    @property
    def scale_factor(self) -> float:
        return math.sqrt(abs(self.a * self.d - self.b * self.c))

    def to_svg(self) -> str:
        return "matrix(%s)" % " ".join(_num(v) for v in (self.a, self.b, self.c, self.d, self.e, self.f))

    def to_list(self) -> list[float]:
        return [round(v, 6) for v in (self.a, self.b, self.c, self.d, self.e, self.f)]

    def shapely_params(self) -> list[float]:
        return [self.a, self.c, self.b, self.d, self.e, self.f]


def similarity(src: Pt, dst: Pt, scale: float = 1.0, rotate: float = 0.0) -> Affine:
    """Map source point -> target point with uniform scale and rotation about it."""
    return Affine.translate(*dst) @ Affine.rotate(rotate) @ Affine.scale(scale) @ Affine.translate(-src[0], -src[1])


def similarity2(s1: Pt, s2: Pt, t1: Pt, t2: Pt) -> Affine:
    """Similarity (no shear) mapping two source points onto two target points."""
    vs = (s2[0] - s1[0], s2[1] - s1[1])
    vt = (t2[0] - t1[0], t2[1] - t1[1])
    ls, lt = math.hypot(*vs), math.hypot(*vt)
    if ls < 1e-9:
        raise ValueError("source landmarks coincide")
    ang = math.degrees(math.atan2(vt[1], vt[0]) - math.atan2(vs[1], vs[0]))
    return similarity(s1, t1, lt / ls, ang)


def _num(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


_TOKEN = re.compile(r"[MmLlHhVvCcQqZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


class Path:
    """A vector path: list of subpaths, each a list of ops.

    ops: ("M", x, y) ("L", x, y) ("C", x1, y1, x2, y2, x, y) ("Z",)
    Fill rule is even-odd everywhere in mangakit.
    """

    def __init__(self, subpaths: list[list[tuple]] | None = None):
        self.subpaths = subpaths or []

    # ---- constructors
    @staticmethod
    def rect(x: float, y: float, w: float, h: float) -> "Path":
        return Path.polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])

    @staticmethod
    def polygon(pts: Iterable[Sequence[float]]) -> "Path":
        pts = [tuple(map(float, p)) for p in pts]
        sp = [("M", *pts[0])] + [("L", *p) for p in pts[1:]] + [("Z",)]
        return Path([sp])

    @staticmethod
    def polyline(pts: Iterable[Sequence[float]]) -> "Path":
        pts = [tuple(map(float, p)) for p in pts]
        return Path([[("M", *pts[0])] + [("L", *p) for p in pts[1:]]])

    @staticmethod
    def ellipse(cx: float, cy: float, rx: float, ry: float) -> "Path":
        k = 0.5522847498
        sp = [
            ("M", cx + rx, cy),
            ("C", cx + rx, cy + k * ry, cx + k * rx, cy + ry, cx, cy + ry),
            ("C", cx - k * rx, cy + ry, cx - rx, cy + k * ry, cx - rx, cy),
            ("C", cx - rx, cy - k * ry, cx - k * rx, cy - ry, cx, cy - ry),
            ("C", cx + k * rx, cy - ry, cx + rx, cy - k * ry, cx + rx, cy),
            ("Z",),
        ]
        return Path([sp])

    @staticmethod
    def from_svg(d: str) -> "Path":
        toks = _TOKEN.findall(d)
        i, cmd = 0, None
        subs: list[list[tuple]] = []
        cur: list[tuple] = []
        x = y = sx = sy = 0.0

        def nums(n):
            nonlocal i
            vals = [float(t) for t in toks[i:i + n]]
            i += n
            return vals

        while i < len(toks):
            t = toks[i]
            if t.isalpha():
                cmd = t
                i += 1
                if cmd in "Zz":
                    cur.append(("Z",))
                    x, y = sx, sy
                    continue
            rel = cmd.islower()
            C = cmd.upper()
            if C == "M":
                px, py = nums(2)
                if rel:
                    px, py = px + x, py + y
                if cur:
                    subs.append(cur)
                cur = [("M", px, py)]
                x, y, sx, sy = px, py, px, py
                cmd = "l" if rel else "L"
            elif C == "L":
                px, py = nums(2)
                if rel:
                    px, py = px + x, py + y
                cur.append(("L", px, py)); x, y = px, py
            elif C == "H":
                (px,) = nums(1)
                px = px + x if rel else px
                cur.append(("L", px, y)); x = px
            elif C == "V":
                (py,) = nums(1)
                py = py + y if rel else py
                cur.append(("L", x, py)); y = py
            elif C == "C":
                v = nums(6)
                if rel:
                    v = [v[j] + (x if j % 2 == 0 else y) for j in range(6)]
                cur.append(("C", *v)); x, y = v[4], v[5]
            elif C == "Q":
                v = nums(4)
                if rel:
                    v = [v[j] + (x if j % 2 == 0 else y) for j in range(4)]
                qx, qy, px, py = v
                cur.append(("C", x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y),
                            px + 2 / 3 * (qx - px), py + 2 / 3 * (qy - py), px, py))
                x, y = px, py
            else:
                raise ValueError(f"unsupported path command {cmd!r} (use M L H V C Q Z)")
        if cur:
            subs.append(cur)
        return Path(subs)

    @staticmethod
    def from_shapely(g) -> "Path":
        subs = []
        polys = [g] if isinstance(g, Polygon) else list(getattr(g, "geoms", []))
        for p in polys:
            if not isinstance(p, Polygon) or p.is_empty:
                continue
            for ring in [p.exterior, *p.interiors]:
                c = list(ring.coords)[:-1]
                subs.append([("M", *c[0])] + [("L", *q) for q in c[1:]] + [("Z",)])
        return Path(subs)

    # ---- conversion
    def d(self) -> str:
        out = []
        for sp in self.subpaths:
            for op in sp:
                out.append(op[0] + " ".join(_num(v) for v in op[1:]))
        return " ".join(out)

    def transformed(self, t: Affine) -> "Path":
        subs = []
        for sp in self.subpaths:
            nsp = []
            for op in sp:
                if op[0] == "Z":
                    nsp.append(op)
                else:
                    vals = op[1:]
                    pts = [t.apply((vals[j], vals[j + 1])) for j in range(0, len(vals), 2)]
                    nsp.append((op[0], *[c for p in pts for c in p]))
            subs.append(nsp)
        return Path(subs)

    def rings(self, segs: int = 24) -> list[list[Pt]]:
        rings = []
        for sp in self.subpaths:
            pts: list[Pt] = []
            for op in sp:
                if op[0] in "ML":
                    pts.append((op[1], op[2]))
                elif op[0] == "C":
                    x0, y0 = pts[-1]
                    x1, y1, x2, y2, x3, y3 = op[1:]
                    for k in range(1, segs + 1):
                        t = k / segs
                        mt = 1 - t
                        pts.append((mt**3 * x0 + 3 * mt * mt * t * x1 + 3 * mt * t * t * x2 + t**3 * x3,
                                    mt**3 * y0 + 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t**3 * y3))
            if len(pts) >= 3:
                rings.append(pts)
        return rings

    def shape(self):
        """Shapely geometry (even-odd)."""
        g = None
        for r in self.rings():
            p = Polygon(r).buffer(0)
            g = p if g is None else g.symmetric_difference(p)
        return g if g is not None else Polygon()

    # ---- boolean + misc
    def union(self, *others: "Path") -> "Path":
        return Path.from_shapely(unary_union([self.shape(), *[o.shape() for o in others]]))

    def intersection(self, other: "Path") -> "Path":
        return Path.from_shapely(self.shape().intersection(other.shape()))

    def difference(self, other: "Path") -> "Path":
        return Path.from_shapely(self.shape().difference(other.shape()))

    def offset(self, dist: float) -> "Path":
        """Grow (dist>0) or shrink (dist<0) the filled region, mitred corners."""
        return Path.from_shapely(self.shape().buffer(dist, join_style=2, mitre_limit=8))

    inset = lambda self, dist: self.offset(-dist)

    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for r in self.rings() for p in r]
        ys = [p[1] for r in self.rings() for p in r]
        return (min(xs), min(ys), max(xs), max(ys))

    def contains(self, p: Pt) -> bool:
        return self.shape().contains(Point(p))

    def centroid(self) -> Pt:
        c = self.shape().centroid
        return (c.x, c.y)

    def __repr__(self):
        return f"Path({self.d()[:60]}...)"


def as_path(x) -> Path:
    if isinstance(x, Path):
        return x
    if isinstance(x, str):
        return Path.from_svg(x)
    return Path.polygon(x)


def line_y(p1: Pt, p2: Pt, x: float) -> float:
    """y of the infinite line p1-p2 at x (helper for diagonal frames)."""
    return p1[1] + (p2[1] - p1[1]) * (x - p1[0]) / (p2[0] - p1[0])


__all__ = ["Affine", "Path", "as_path", "similarity", "similarity2", "line_y", "_box", "MultiPolygon", "affinity"]
