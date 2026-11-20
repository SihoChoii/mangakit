"""Procedural effects. Every effect is deterministic given its parameters and `seed`;
the seed lives in the page source and is recorded in the proof manifest."""
from __future__ import annotations

import math
import random

from .geometry import Path, _num


def _wedge(x0, y0, x1, y1, w0, w1=0.0):
    """Tapered stroke from (x0,y0) width w0 to (x1,y1) width w1 as polygon d."""
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L, dx / L
    pts = [(x0 + nx * w0 / 2, y0 + ny * w0 / 2), (x1 + nx * w1 / 2, y1 + ny * w1 / 2),
           (x1 - nx * w1 / 2, y1 - ny * w1 / 2), (x0 - nx * w0 / 2, y0 - ny * w0 / 2)]
    return "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in pts) + " Z"


def speed_lines(region: Path, seed: int, angle: float = 0.0, count: int = 90, width=(1.0, 4.0),
                length=(0.35, 1.0), color="#000000", taper="both", **_):
    """Parallel motion lines across `region` at `angle` degrees (0 = horizontal)."""
    rnd = random.Random(seed)
    x0, y0, x1, y1 = region.bbox()
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    diag = math.hypot(x1 - x0, y1 - y0)
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    ds = []
    for _ in range(count):
        off = rnd.uniform(-diag / 2, diag / 2)
        L = diag * rnd.uniform(*length)
        along = rnd.uniform(-diag / 2, diag / 2 - L * 0.3)
        sx, sy = cx + nx * off + ux * along, cy + ny * off + uy * along
        ex, ey = sx + ux * L, sy + uy * L
        w = rnd.uniform(*width)
        if taper == "both":
            mx, my = (sx + ex) / 2, (sy + ey) / 2
            ds.append(_wedge(mx, my, sx, sy, w, 0))
            ds.append(_wedge(mx, my, ex, ey, w, 0))
        else:
            ds.append(_wedge(sx, sy, ex, ey, w, 0))
    return f'<path d="{" ".join(ds)}" fill="{color}"/>'


def focus_lines(region: Path, seed: int, center=None, count: int = 140, inner=0.35, jitter=0.12,
                width=(2.0, 9.0), color="#000000", **_):
    """Radial concentration lines pointing at `center`, leaving a clear area of radius `inner` (fraction)."""
    rnd = random.Random(seed)
    x0, y0, x1, y1 = region.bbox()
    cx, cy = center or ((x0 + x1) / 2, (y0 + y1) / 2)
    R = max(math.hypot(x - cx, y - cy) for x in (x0, x1) for y in (y0, y1))
    r_in = inner * R
    ds = []
    for _ in range(count):
        t = rnd.uniform(0, 2 * math.pi)
        r0 = r_in * (1 + rnd.uniform(-jitter, jitter * 2))
        w = rnd.uniform(*width)
        ds.append(_wedge(cx + math.cos(t) * R * 1.05, cy + math.sin(t) * R * 1.05,
                         cx + math.cos(t) * r0, cy + math.sin(t) * r0, w, 0))
    return f'<path d="{" ".join(ds)}" fill="{color}"/>'


def tone(region: Path, seed: int = 0, spacing: float = 7.0, dot: float = 0.38, angle: float = 45.0,
         color="#000000", uid="tone", **_):
    """Screentone: regular dot grid (dot = radius as fraction of spacing). Returns defs+fill."""
    pid = f"{uid}-pat"
    r = spacing * dot
    pat = (f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="{_num(spacing)}" height="{_num(spacing)}" '
           f'patternTransform="rotate({_num(angle)})"><circle cx="{_num(spacing/2)}" cy="{_num(spacing/2)}" '
           f'r="{_num(r)}" fill="{color}"/></pattern>')
    return f'<defs>{pat}</defs><path d="{region.d()}" fill="url(#{pid})" fill-rule="evenodd"/>'


EFFECTS = {"speed_lines": speed_lines, "focus_lines": focus_lines, "tone": tone}
