"""Technical checks on a built Page. Each issue: severity, code, where, message, [bbox].

These complement (never replace) looking at the rendered page.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from shapely.geometry import Point, box
from shapely.ops import unary_union

from .assets import Registry, _issue
from .page import Page
from .render import _balloons, iter_layers

RES = 0.5  # raster checks: pixels per page unit


def _r(b):
    return [round(float(v), 1) for v in b]


def run_checks(page: Page) -> list[dict]:
    pr = page.project
    issues: list[dict] = []
    issues += page.art.issues + page.issues
    for p in pr.verify_fonts():
        issues.append(_issue("error", "font-pin", "project.yaml", p))
    reg = Registry(pr)
    for aid, d in page.art.used.items():
        if d.missing:
            continue
        for i in reg.validate(aid):
            if i["code"] == "stale-mask":
                continue  # reported per use by art.mask
            if i["where"].split("/")[0].split(":")[0] == aid and (
                    i["where"].endswith("/" + d.version) or ":" in i["where"]):
                issues.append(i)
    panels = {pid: p.path.shape() for pid, p in page.panels.items()}
    trim = page.trim.shape()
    safe = page.safe.shape()
    layers = list(iter_layers(page.layers))

    # ---- image layers: clips, coverage, breakouts
    covered: dict[str, list] = {}
    for L in layers:
        if L.kind != "image":
            continue
        d = L.data
        dr = d["drawing"]
        from .geometry import Path as _P
        img_poly = _P.rect(0, 0, dr.width, dr.height).transformed(d["transform"]).shape()
        if not dr.missing and d.get("mask") is None and dr.kind != "rough":  # roughs never print
            T = d["transform"]
            upx = abs(T.a * T.d - T.b * T.c) ** 0.5  # page units per source px
            eff = 25.4 * pr.upm / upx if upx else 0
            want = pr.cfg.get("output_profiles", {}).get("print", {}).get("dpi", 600)
            if eff < want:
                sev = "warn" if eff < 0.5 * want else "info"
                issues.append(_issue(sev, "art-resolution", f"{dr.asset_id}/{dr.version}",
                                     f"{dr.width}x{dr.height} px placed at {eff:.0f} dpi effective; print profile "
                                     f"wants {want} dpi (needs ~{want / eff:.1f}x the pixels, or an upscale pass)"))
        ref = d["clip_ref"]
        if ref and ref[0] == "custom":
            issues.append(_issue("warn", "undeclared-clip", L.name,
                                 "image clipped to a region that is neither a panel nor a declared breakout; "
                                 "declare it with panel.breakout(...) if the overlap is intended"))
        if ref and ref[0] == "panel" and d["mask"] is None and not dr.missing:
            covered.setdefault(ref[1], []).append(img_poly)
        if d["mask"] is not None and d["mask"].file is not None and not dr.missing:
            issues += _check_breakout_layer(page, L, panels)
        names = [ref[1]] if ref and ref[0] == "breakout" else (ref[1] if ref and ref[0] == "breakouts" else [])
        for bname in names:
            bk = page.breakouts[bname]
            for pid, shp in panels.items():
                if pid == bk.panel or pid in bk.over:
                    continue
                inter = bk.path.shape().intersection(shp)
                if inter.area > 4:
                    issues.append(_issue("warn", "breakout-intrudes", L.name,
                                         f"breakout {bk.name} overlaps panel {pid} interior "
                                         f"({inter.area:.0f} u²); add over=['{pid}'] if intended",
                                         _r(inter.bounds)))
    for pid, polys in covered.items():
        gap = panels[pid].difference(unary_union(polys))
        if gap.area > 0.002 * panels[pid].area:
            issues.append(_issue("warn", "art-gap", pid, f"panel art leaves {gap.area:.0f} u² of the panel uncovered",
                                 _r(gap.bounds)))

    # ---- balloons
    balloons = _balloons(page.layers)
    for L in balloons:
        d = L.data
        sw = d["style"].get("width", 2.4)
        body = d["body"].shape()
        inner = body.buffer(-(sw / 2 + 3))
        for i, bx in enumerate(d["boxes"]):
            if not inner.contains(box(*bx)):
                issues.append(_issue("error", "text-overflow", L.name,
                                     f"line {i + 1} {d['lines'][i]!r} leaves the balloon interior "
                                     f"(grow the balloon, change breaks, or shorten the script line)", _r(bx)))
        out = d["outline"].shape()
        if not trim.contains(out):
            issues.append(_issue("error", "balloon-off-trim", L.name, "balloon crosses the trim edge", _r(out.bounds)))
        elif not safe.contains(out):
            issues.append(_issue("warn", "balloon-outside-safe", L.name, "balloon extends outside the safe area",
                                 _r(out.bounds)))
        seen = set()
        for M in layers:
            if M.kind == "image" and not M.data["drawing"].missing:
                for nm, lm in M.data["drawing"].landmarks.items():
                    if lm.get("protect"):
                        pt = M.data["transform"].apply(lm["xy"])
                        key = (M.data["drawing"].asset_id, nm, round(pt[0], 1), round(pt[1], 1))
                        if key in seen:
                            continue
                        seen.add(key)
                        if out.contains(Point(pt)):
                            issues.append(_issue("warn", "balloon-covers-landmark", L.name,
                                                 f"covers protected landmark {M.data['drawing'].asset_id}:{nm}",
                                                 _r((*pt, *pt))))
    for i, A in enumerate(balloons):
        for B in balloons[i + 1:]:
            a, b = A.data["outline"].shape(), B.data["outline"].shape()
            if a.intersects(b) and a.intersection(b).area > 2:
                issues.append(_issue("warn", "balloon-overlap", f"{A.name}+{B.name}", "balloons overlap",
                                     _r(a.intersection(b).bounds)))
    for L in layers:
        if L.kind == "text" and not trim.contains(box(*L.data["bbox"])):
            issues.append(_issue("warn", "text-off-trim", L.name, f"text {L.data['text']!r} crosses the trim",
                                 _r(L.data["bbox"])))

    # ---- reading order: script order vs spatial order (panel order, then rows, then direction)
    def panel_of(L):
        if L.data["panel"]:
            return L.data["panel"]
        c = Point(L.data["at"])
        for pid, shp in panels.items():
            if shp.contains(c):
                return pid
        return None

    def key(L):
        pid = panel_of(L)
        order = page.panels[pid].order if pid else 999
        x, y = L.data["at"]
        return (order, round(y / 80), -x if page.direction == "rtl" else x)

    placed = [L.data["dialogue"] for L in sorted(balloons, key=key)]
    script_order = [i for i in page.script.order if i in placed]
    if placed != script_order:
        issues.append(_issue("warn", "reading-order", page.id,
                             f"spatial balloon order {placed} differs from script order {script_order}"))
    beats = {p.beat for p in page.panels.values() if p.beat}
    lettered = {L.data["dialogue"] for L in balloons} | {
        L.data.get("line") for L in iter_layers(page.layers) if L.kind == "text"}
    def _lettered_on_sibling(b, lid):
        # a beat that spans a spread (or a page turn) is lettered across pages: accept a line set on
        # another page source that carries the same beat
        try:
            for f in sorted(page.project.root.glob("chapters/*/pages/p*.py")):
                if f.stem == page.id or "." in f.stem:
                    continue
                t = f.read_text()
                if (f"beat='{b}'" in t or f'beat="{b}"' in t) and (f"'{lid}'" in t or f'"{lid}"' in t):
                    return True
        except Exception:
            return False
        return False
    for b in beats:
        for lid in page.script.lines_for_beat(b):
            if lid not in lettered and not _lettered_on_sibling(b, lid):
                issues.append(_issue("warn", "unlettered-line", lid, f"script line for beat {b} has no balloon"))
    return issues


def _raster_poly(shape, size, origin):
    im = Image.new("L", size, 0)
    dr = ImageDraw.Draw(im)
    geoms = getattr(shape, "geoms", [shape])
    for g in geoms:
        if g.is_empty:
            continue
        dr.polygon([((x - origin[0]) * RES, (y - origin[1]) * RES) for x, y in g.exterior.coords], fill=255)
        for hole in g.interiors:
            dr.polygon([((x - origin[0]) * RES, (y - origin[1]) * RES) for x, y in hole.coords], fill=0)
    return np.asarray(im) > 127


def _flush_area(panel_shape, clip_shape, reach=5000.0):
    """Half-planes beyond the panel edges that no breakout region crosses. Art cut there is cut by the
    straight extension of the frame's own edge (an arm leaving frame at the side), not by the
    breakout region, so it is not a breakout-cut. A non-convex panel (an inset's host, a notched
    frame) uses its outer frame: the convex hull."""
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient
    if panel_shape.geom_type != "Polygon":
        return None
    if panel_shape.convex_hull.area - panel_shape.area > 1.0:
        panel_shape = panel_shape.convex_hull
    ring = list(orient(panel_shape.simplify(0.01), 1.0).exterior.coords)[:-1]  # CCW (y-down: inside on the right)
    parts = []
    for i in range(len(ring)):
        (ax, ay), (bx, by) = ring[i], ring[(i + 1) % len(ring)]
        dx, dy = bx - ax, by - ay
        n = (dx * dx + dy * dy) ** 0.5
        if n < 1e-6:
            continue
        # outward normal: the side away from the panel's centroid
        nx, ny = dy / n, -dx / n
        c = panel_shape.centroid
        if (c.x - ax) * nx + (c.y - ay) * ny > 0:
            nx, ny = -nx, -ny
        ux, uy = dx / n * reach, dy / n * reach
        hp = Polygon([(ax - ux, ay - uy), (bx + ux, by + uy),
                      (bx + ux + nx * reach, by + uy + ny * reach), (ax - ux + nx * reach, ay - uy + ny * reach)])
        if clip_shape is None or clip_shape.intersection(hp).area < 1.0:
            parts.append(hp)
    return unary_union(parts) if parts else None


def _check_breakout_layer(page: Page, L, panels, res=2.0) -> list[dict]:
    """Raster test of a masked (border-break) layer in page space, inside its clip's bbox.

    breakout-cut: silhouette outside the panel that the allowed region chops off (hard edge).
    mask-slices-ink: ink just outside the visible mask edge (the cut-out slices linework).
    mask-halo: the visible mask edge runs through paper, not ink (a paper margin shows over the gutter
               or neighboring art; tighten the polygon or use --trim-light-edges).
    breakout-empty: the masked art never leaves the panel (layer has no effect).
    """
    from .geometry import Affine
    out = []
    d = L.data
    dr, m = d["drawing"], d["mask"]
    pid = d["panel"]
    mask_img = Image.open(m.file).convert("L")
    # region of interest: mask footprint on the page, padded
    mb = mask_img.getbbox()
    if mb is None:
        return [_issue("info", "breakout-empty", L.name, "mask is empty")]
    from .geometry import Path as _P
    foot = _P.rect(mb[0], mb[1], mb[2] - mb[0], mb[3] - mb[1]).transformed(d["transform"]).shape().buffer(20)
    x0, y0, x1, y1 = foot.bounds
    origin = (x0, y0)
    size = (max(1, int((x1 - x0) * res)), max(1, int((y1 - y0) * res)))
    M = d["transform"].inverse() @ Affine.translate(*origin) @ Affine.scale(1 / res)
    coeffs = (M.a, M.c, M.e, M.b, M.d, M.f)
    mask_pg = np.asarray(mask_img.transform(size, Image.AFFINE, coeffs, Image.BILINEAR)) > 127
    gray = np.asarray(Image.open(dr.file).convert("L").transform(size, Image.AFFINE, coeffs, Image.BILINEAR,
                                                                  fillcolor=255))
    ink, paper = gray < 110, gray > 200

    def rast(shape):
        im = Image.new("L", size, 0)
        dd = ImageDraw.Draw(im)
        for g in getattr(shape, "geoms", [shape]):
            if g.is_empty:
                continue
            dd.polygon([((x - x0) * res, (y - y0) * res) for x, y in g.exterior.coords], fill=255)
            for h in g.interiors:
                dd.polygon([((x - x0) * res, (y - y0) * res) for x, y in h.coords], fill=0)
        return np.asarray(im) > 127

    panel = rast(panels[pid]) if pid in panels else np.zeros(size[::-1], bool)
    clip = rast(d["clip"].shape()) if d["clip"] is not None else np.ones(size[::-1], bool)

    def bbox_of(sel):
        ys, xs = np.nonzero(sel)
        return _r((xs.min() / res + x0, ys.min() / res + y0, xs.max() / res + x0, ys.max() / res + y0))

    fl = _flush_area(panels[pid], d["clip"].shape() if d["clip"] is not None else None) if pid in panels else None
    flush = rast(fl.intersection(box(x0 - 1, y0 - 1, x1 + 1, y1 + 1))) if fl is not None else np.zeros(size[::-1], bool)
    # the frame-edge extension itself is the cut line there; widen by a pixel so the edge isn't counted
    flush = np.asarray(Image.fromarray((flush * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 127
    outside = mask_pg & ~panel
    if (outside & clip).sum() == 0:
        out.append(_issue("info", "breakout-empty", L.name, "masked art does not extend past the panel"))
    cut = outside & ~clip & ~flush
    if cut.sum() > 2 * res * res:
        out.append(_issue("error", "breakout-cut", L.name,
                          f"{cut.sum() / res / res:.0f} u² of masked art outside the panel is chopped by the "
                          f"allowed breakout region (straight cut edge); widen the region or tighten the mask",
                          bbox_of(cut)))
    mimg = Image.fromarray((mask_pg * 255).astype(np.uint8))
    outer = (np.asarray(mimg.filter(ImageFilter.MaxFilter(3))) > 0) & ~mask_pg
    # second pixel layer inside the edge (0.5-1.0 u deep at res 2): paper there = a margin of >= ~0.5 u
    e1 = np.asarray(mimg.filter(ImageFilter.MinFilter(3))) > 0
    e2 = np.asarray(mimg.filter(ImageFilter.MinFilter(5))) > 0
    inner = e1 & ~e2
    vis = ~panel & clip & ~flush
    vo, vi = outer & vis, inner & vis
    dbg = os.environ.get("MANGAKIT_CHECK_DEBUG")
    if dbg:  # red = ink just outside the visible edge, blue = paper just inside it
        rgb = np.stack([gray] * 3, -1).astype(np.uint8)
        rgb[vo & ink] = (255, 0, 0)
        rgb[vi & paper] = (0, 80, 255)
        Image.fromarray(rgb).save(os.path.join(dbg, f"{page.id}-{L.name}-edges.png"))
    if vo.sum() > 20:
        ratio = (vo & ink).sum() / vo.sum()
        if ratio > 0.12:
            out.append(_issue("warn", "mask-slices-ink", L.name,
                              f"{ratio:.0%} of the visible mask edge has ink just outside it: the cut-out slices "
                              f"linework or leaves part of an outline behind (inspect `mangakit mask preview`)",
                              bbox_of(vo & ink)))
    if vi.sum() > 20:
        ratio = (vi & paper).sum() / vi.sum()
        if ratio > 0.25:
            out.append(_issue("warn", "mask-halo", L.name,
                              f"{ratio:.0%} of the visible mask edge is paper, not ink: a paper margin will cover "
                              f"the gutter/neighbor art; tighten the mask to the outline", bbox_of(vi & paper)))
    return out
