"""Board layout helpers: live area, gutter-aware rows/columns, diagonal cuts, insets, bleeds,
gutter breakout zones, and geometric reading order. All results are page-unit Paths.

Reading direction (rtl / ltr) decides which piece of a side-by-side split comes first; rows always
read top to bottom. Margins come from project.yaml `board:` (see docs/board-reference.md):

    board:
      margins_mm: {top: 10, bottom: 12, inside: 9, outside: 9}
      gutter_mm: {row: 3.7, col: 3.7}      # row = between tiers (horizontal gutter), col = between columns
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon, box
from shapely.ops import substring, unary_union

from .geometry import Path, as_path
from .project import MangakitError

DEFAULT_BOARD = {"margins_mm": {"top": 10.0, "bottom": 12.0, "inside": 9.0, "outside": 9.0},
                 "gutter_mm": {"row": 4.0, "col": 2.5}}
FAR = 1e5


def board_cfg(project) -> dict:
    b = dict(DEFAULT_BOARD)
    user = project.cfg.get("board", {}) or {}
    for k in ("margins_mm", "gutter_mm"):
        b[k] = {**DEFAULT_BOARD[k], **(user.get(k) or {})}
    for k, v in user.items():
        if k not in b:
            b[k] = v
    return b


def _poly(p):
    g = as_path(p).shape()
    return g


def _path(g) -> Path:
    g = g.buffer(0)
    if g.is_empty:
        raise MangakitError("layout produced an empty panel (gutter or cut outside the region?)")
    if g.geom_type == "MultiPolygon":  # keep the largest piece; slivers from rounding are dropped
        g = max(g.geoms, key=lambda q: q.area)
    return Path.from_shapely(Polygon([(round(x, 2), round(y, 2)) for x, y in g.exterior.coords],
                                     [[(round(x, 2), round(y, 2)) for x, y in r.coords] for r in g.interiors]))


def _halfplane(p1, p2, side: float, offset: float):
    """Points on `side` (+1 / -1) of the directed line p1->p2, shifted `offset` away from it."""
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1.0
    ux, uy = dx / L, dy / L
    nx, ny = -uy * side, ux * side          # normal toward `side`
    ax, ay = x1 + nx * offset - ux * FAR, y1 + ny * offset - uy * FAR
    bx, by = x1 + nx * offset + ux * FAR, y1 + ny * offset + uy * FAR
    return Polygon([(ax, ay), (bx, by), (bx + nx * FAR, by + ny * FAR), (ax + nx * FAR, ay + ny * FAR)])


def split(region, p1, p2, gutter: float):
    """Cut `region` along the line p1->p2 with a gutter measured perpendicular to the cut.
    Returns (left, right) as seen travelling p1->p2 on the page: west->east gives (upper, lower),
    north->south gives (east, west)."""
    g = _poly(region)
    a = g.intersection(_halfplane(p1, p2, -1, gutter / 2))
    b = g.intersection(_halfplane(p1, p2, +1, gutter / 2))
    return _path(a), _path(b)


class Layout:
    """Bound to a page: `L = page.layout()`. Every helper returns Paths for page.panel()."""

    def __init__(self, page, margins_mm=None, gutter_mm=None):
        self.page = page
        cfg = board_cfg(page.project)
        m = {**cfg["margins_mm"], **(margins_mm or {})}
        g = {**cfg["gutter_mm"], **(gutter_mm or {})}
        u = page.project.upm
        self.margins = {k: v * u for k, v in m.items()}
        self.row_gutter, self.col_gutter = g["row"] * u, g["col"] * u
        side = getattr(page, "side", None) or "right"
        # the inside (binding) edge is the page's edge toward the other page of the spread
        left = self.margins["inside"] if side == "right" else self.margins["outside"]
        right = self.margins["outside"] if side == "right" else self.margins["inside"]
        self.side = side
        self.x0, self.y0 = left, self.margins["top"]
        self.x1, self.y1 = page.width - right, page.height - self.margins["bottom"]
        self.rtl = page.direction == "rtl"

    # ---------- frames
    @property
    def live(self) -> Path:
        return Path.rect(self.x0, self.y0, self.x1 - self.x0, self.y1 - self.y0)

    def _region(self, region):
        return self.live if region is None else as_path(region)

    def rows(self, weights=(1, 1), region=None, gutter=None) -> list[Path]:
        """Horizontal tiers, top to bottom; heights proportional to weights (gutters excluded)."""
        r = self._region(region)
        g = self.row_gutter if gutter is None else gutter
        x0, y0, x1, y1 = r.bbox()
        total = (y1 - y0) - g * (len(weights) - 1)
        out, y, rest = [], y0, r
        for w in weights[:-1]:
            y += total * w / sum(weights)
            top, rest = split(rest, (x0 - 10, y + g / 2), (x1 + 10, y + g / 2), g)
            out.append(top)
            y += g
        out.append(rest)
        return out

    def cols(self, weights=(1, 1), region=None, gutter=None) -> list[Path]:
        """Side-by-side panels in READING order (rtl: rightmost first); widths follow weights in
        reading order."""
        r = self._region(region)
        g = self.col_gutter if gutter is None else gutter
        x0, y0, x1, y1 = r.bbox()
        total = (x1 - x0) - g * (len(weights) - 1)
        out, rest = [], r
        if self.rtl:
            x = x1
            for w in weights[:-1]:
                x -= total * w / sum(weights)
                first, rest = self._vsplit(rest, x - g / 2, x - g / 2, g)
                out.append(first)
                x -= g
        else:
            x = x0
            for w in weights[:-1]:
                x += total * w / sum(weights)
                first, rest = self._vsplit(rest, x + g / 2, x + g / 2, g)
                out.append(first)
                x += g
        out.append(rest)
        return out

    def grid(self, rows, region=None, row_weights=None) -> list[list[Path]]:
        """rows = [n_cols or [col weights], ...] -> [[panel paths of row 0 in reading order], ...]."""
        tiers = self.rows(row_weights or [1] * len(rows), region)
        return [self.cols([1] * c if isinstance(c, int) else c, t) if (c if isinstance(c, int) else len(c)) > 1 else [t]
                for t, c in zip(tiers, rows)]

    def cut(self, region, left_y: float, right_y: float, gutter=None) -> tuple[Path, Path]:
        """Diagonal tier cut: a line from (region left, left_y) to (region right, right_y).
        Returns (upper, lower); the gutter is measured perpendicular to the cut."""
        r = as_path(region)
        x0, _, x1, _ = r.bbox()
        g = self.row_gutter if gutter is None else gutter
        upper, lower = split(r, (x0, left_y), (x1, right_y), g)
        return upper, lower

    def vcut(self, region, top_x: float, bottom_x: float, gutter=None) -> tuple[Path, Path]:
        """Diagonal column cut from (top_x, region top) to (bottom_x, region bottom).
        Returns the two pieces in READING order (rtl: right piece first)."""
        g = self.col_gutter if gutter is None else gutter
        return self._vsplit(as_path(region), top_x, bottom_x, g)

    def _vsplit(self, r, top_x, bottom_x, g):
        _, y0, _, y1 = r.bbox()
        right, left = split(r, (top_x, y0), (bottom_x, y1), g)   # travelling south: left = east
        return (right, left) if self.rtl else (left, right)

    def inset(self, host, rect, gap=None) -> tuple[Path, Path]:
        """An inset panel over `host`. Returns (host_visible, inset): use host_visible as the host
        panel path (its art and checks skip the inset) and pass border=host to page.panel so the host's
        outer frame is stroked, not the hole. The white gap is `gap` (default: column gutter)."""
        g = self.col_gutter if gap is None else gap
        ins = as_path(rect)
        hv = as_path(host).difference(ins.offset(g))
        return hv, ins

    def bleed(self, path, sides=("all",), tol=1.5) -> Path:
        """Push the panel's edges that lie on the live-area edge out to the bleed edge.
        sides: any of top, bottom, left, right, inside, outside, all."""
        sides = set([sides] if isinstance(sides, str) else sides)
        if "inside" in sides:
            sides.add("left" if self.side == "right" else "right")
        if "outside" in sides:
            sides.add("right" if self.side == "right" else "left")
        if "all" in sides:
            sides |= {"top", "bottom", "left", "right"}
        b = self.page.bleed
        W, H = self.page.width, self.page.height
        g = as_path(path).shape()
        pts = []
        for x, y in list(g.exterior.coords)[:-1]:
            if "left" in sides and abs(x - self.x0) < tol:
                x = -b
            if "right" in sides and abs(x - self.x1) < tol:
                x = W + b
            if "top" in sides and abs(y - self.y0) < tol:
                y = -b
            if "bottom" in sides and abs(y - self.y1) < tol:
                y = H + b
            pts.append((x, y))
        return Path.polygon(pts)


# ---------------------------------------------------------------- breakouts through a gutter
def gutter_line(a, b):
    """The edge of panel a that faces panel b across their gutter (a LineString), or None."""
    A, B = _poly(a), _poly(b)
    gap = A.distance(B)
    edge = A.exterior.intersection(B.buffer(gap + 1.0))
    if edge.is_empty:
        return None, gap
    if edge.geom_type == "MultiLineString":
        from shapely.ops import linemerge
        edge = linemerge(edge)
        if edge.geom_type == "MultiLineString":
            edge = max(edge.geoms, key=lambda e: e.length)
    if edge.geom_type != "LineString":
        return None, gap
    return edge, gap


def breakout_zone(a, b, span=(0.0, 1.0), inside=40.0, reach=120.0, rtl=True, page_box=None) -> Path:
    """Allowed break region from panel a into panel b: starts `inside` units inside a (covering its
    border stroke), crosses the gutter and reaches `reach` units into b, limited to `span` = fractions
    (t0, t1) along the shared edge measured from its reading-start end (rtl: right / top end)."""
    A, B = _poly(a), _poly(b)
    edge, gap = gutter_line(a, b)
    if edge is None:
        raise MangakitError("panels do not share a gutter edge")
    c0, c1 = edge.coords[0], edge.coords[-1]
    horizontal = abs(c1[0] - c0[0]) >= abs(c1[1] - c0[1])
    # orient from reading start: rtl = from the right end; ltr = from the left end; vertical = from the top
    if horizontal:
        start_first = (c0[0] > c1[0]) if rtl else (c0[0] < c1[0])
    else:
        start_first = c0[1] < c1[1]
    if not start_first:
        edge = LineString(list(edge.coords)[::-1])
    seg = substring(edge, span[0], span[1], normalized=True)
    limit = seg.buffer(gap + reach + inside + 10, cap_style=2)
    band = A.buffer(gap + reach).intersection(B.buffer(gap + inside))
    zone = band.intersection(limit).intersection(A.union(B).union(A.buffer(gap + 1).intersection(B.buffer(gap + 1))))
    if page_box is not None:
        zone = zone.intersection(_poly(page_box))
    return _path(zone)


# ---------------------------------------------------------------- reading order
def _yrange_at(g, x):
    hit = g.intersection(LineString([(x, -FAR), (x, FAR)]))
    if hit.is_empty:
        return None
    return hit.bounds[1], hit.bounds[3]


def precedes(a, b, rtl=True, tol=2.0) -> int:
    """+1 if shape a reads before b, -1 if after, 0 if undecided."""
    ax0, ay0, ax1, ay1 = a.bounds
    bx0, by0, bx1, by1 = b.bounds
    if ay1 <= by0 + tol:
        return 1
    if by1 <= ay0 + tol:
        return -1
    lo, hi = max(ax0, bx0), min(ax1, bx1)
    if hi - lo > tol:      # stacked with overlapping bboxes (diagonal tiers): compare along verticals
        votes = 0
        for k in range(1, 8):
            x = lo + (hi - lo) * k / 8
            ra, rb = _yrange_at(a, x), _yrange_at(b, x)
            if ra and rb:
                if ra[1] <= rb[0] + tol:
                    votes += 1
                elif rb[1] <= ra[0] + tol:
                    votes -= 1
        if votes:
            return 1 if votes > 0 else -1
    ca, cb = a.centroid.x, b.centroid.x
    if abs(ca - cb) > tol:
        return (1 if ca > cb else -1) if rtl else (1 if ca < cb else -1)
    return 1 if a.centroid.y < b.centroid.y else -1


def reading_order(shapes: dict, rtl=True) -> list:
    """Geometric reading order of named shapes (panels, or balloon bodies inside one panel):
    tiers top to bottom; within a tier rtl reads right to left; a tall panel beside a stack reads
    before (rtl: if it is on the right) the whole stack."""
    ids = list(shapes)
    G = {k: _poly(v) if not hasattr(v, "geom_type") else v for k, v in shapes.items()}
    before = {k: set() for k in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            p = precedes(G[a], G[b], rtl)
            if p > 0:
                before[b].add(a)
            elif p < 0:
                before[a].add(b)
    out, left = [], set(ids)

    def tiebreak(k):
        c = G[k].centroid
        return (round(G[k].bounds[1] / 40), -c.x if rtl else c.x)
    while left:
        ready = [k for k in left if not (before[k] & left)]
        if not ready:          # a cycle (staggered layout): fall back to position
            ready = [min(left, key=tiebreak)]
        k = min(ready, key=tiebreak)
        out.append(k)
        left.discard(k)
    return out
