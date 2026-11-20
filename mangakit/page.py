"""Page-authoring library. A page source defines build(page, art, script) and calls these.

Coordinates: page units, origin at trim top-left (bleed is negative / beyond width,height).
Layer order is call order (first call = bottom).
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Point, Polygon

from .assets import Art, Drawing, Mask, _issue
from .effects import EFFECTS
from .geometry import Affine, Path, as_path, similarity, similarity2
from .project import MangakitError, Project, Script
from .text import Typesetter, load_font, text_path


@dataclass
class Placement:
    drawing: Drawing
    transform: Affine

    def map(self, landmark_or_pt):
        """Source landmark name or source (x, y) -> page point."""
        p = self.drawing.landmark(landmark_or_pt) if isinstance(landmark_or_pt, str) else landmark_or_pt
        return self.transform.apply(p)

    def bounds(self) -> Path:
        return Path.rect(0, 0, self.drawing.width, self.drawing.height).transformed(self.transform)


@dataclass
class Breakout:
    name: str
    panel: str
    path: Path
    over: list = field(default_factory=list)  # other panel ids this break may cover


@dataclass
class Panel:
    page: "Page"
    id: str
    path: Path
    beat: str | None
    order: int
    breakouts: list = field(default_factory=list)
    border: Any = True          # True: stroke the panel path; False: borderless; a Path: stroke that instead
    note: str | None = None     # board note (camera, framing), shown on the rough view

    def align(self, drawing: Drawing, source, target, scale: float = 1.0, rotate: float = 0.0) -> Placement:
        """Place `drawing` so source landmark(s) land on target page point(s).

        source="name", target=(x,y): translate + given uniform scale/rotation about that landmark.
        source=["a","b"], target=[(x1,y1),(x2,y2)]: solve scale+rotation from two landmarks.
        Landmark names resolve against the drawing's *selected version* only.
        """
        if drawing.missing:
            # keep geometry usable for rough layouts: centre a placeholder on target
            two = isinstance(source, (list, tuple)) and len(source) == 2 and isinstance(source[0], str)
            t = target[0] if two else target
            return Placement(drawing, similarity((drawing.width / 2, drawing.height / 2), t, scale, rotate))
        if isinstance(source, (list, tuple)) and len(source) == 2 and isinstance(source[0], str):
            s1, s2 = drawing.landmark(source[0]), drawing.landmark(source[1])
            return Placement(drawing, similarity2(s1, s2, tuple(target[0]), tuple(target[1])))
        s = drawing.landmark(source) if isinstance(source, str) else tuple(source)
        return Placement(drawing, similarity(s, tuple(target), scale, rotate))

    def breakout(self, region, name: str | None = None, over=()) -> Path:
        """Declare an allowed border-break region (page coords) for this panel. Returns its path,
        to be used as the clip of the breakout image layer. Include the border stroke width."""
        b = Breakout(name or f"{self.id}-break{len(self.breakouts) + 1}", self.id, as_path(region), list(over))
        self.breakouts.append(b)
        self.page.breakouts[b.name] = b
        return b.path

    def fit(self, drawing: Drawing, mode: str = "cover", anchor=(0.5, 0.5), region=None, scale: float = 1.0) -> Placement:
        """Scale a drawing to cover (or be contained by) the panel's bbox, or `region` (a Path or
        (x0, y0, x1, y1)); `anchor` = the fractional point of the drawing that lands on the same
        fractional point of the region. Use for rough sketches and establishing shots."""
        if region is None:
            x0, y0, x1, y1 = self.path.bbox()
        elif isinstance(region, Path):
            x0, y0, x1, y1 = region.bbox()
        else:
            x0, y0, x1, y1 = region
        w, h = x1 - x0, y1 - y0
        k = (max if mode == "cover" else min)(w / drawing.width, h / drawing.height) * scale
        src = (anchor[0] * drawing.width, anchor[1] * drawing.height)
        return Placement(drawing, similarity(src, (x0 + anchor[0] * w, y0 + anchor[1] * h), k))

    def breakout_toward(self, other: "Panel | str", span=(0.0, 1.0), inside: float = 40.0, reach: float = 120.0,
                        name: str | None = None) -> Path:
        """Declare a narrow break region through the gutter toward `other`: it starts `inside` units in
        this panel, crosses the gutter and reaches `reach` units into the other panel, limited to `span`
        (fractions along the shared edge from its reading-start end). `other` is added to over=."""
        from .layout import breakout_zone
        o = self.page.panels[other] if isinstance(other, str) else other
        z = breakout_zone(self.path, o.path, span, inside, reach, self.page.direction == "rtl", self.page.bleed_box)
        return self.breakout(z, name=name, over=[o.id])

    @property
    def bbox(self):
        return self.path.bbox()


@dataclass
class Layer:
    kind: str
    name: str
    data: dict[str, Any]


class Page:
    def __init__(self, project: Project, page_id: str, art: Art, script: Script):
        self.project, self.id, self.art, self.script = project, page_id, art, script
        self.width, self.height, self.bleed = project.trim_w, project.trim_h, project.bleed
        self.direction = project.direction
        self.panels: dict[str, Panel] = {}
        self.breakouts: dict[str, Breakout] = {}
        self.anchors: dict[str, tuple] = {}
        self.layers: list[Layer] = []
        self._stack: list[list[Layer]] = [self.layers]
        self.issues: list[dict] = []
        self.effect_seeds: dict[str, int] = {}
        self.side: str | None = None       # 'left' / 'right' slot in its spread (set by load_page)
        self.alt: str | None = None        # alternate layout name when rendering pNNN.alt-<name>.py
        self._n = 0
        self._fonts = {}

    # ----- frames
    @property
    def trim(self) -> Path:
        return Path.rect(0, 0, self.width, self.height)

    @property
    def bleed_box(self) -> Path:
        b = self.bleed
        return Path.rect(-b, -b, self.width + 2 * b, self.height + 2 * b)

    @property
    def safe(self) -> Path:
        s = self.project.safe
        return Path.rect(s, s, self.width - 2 * s, self.height - 2 * s)

    def _name(self, kind, name=None):
        self._n += 1
        return name or f"{kind}-{self._n}"

    def _add(self, layer: Layer):
        self._stack[-1].append(layer)
        return layer

    def font(self, role):
        if role not in self._fonts:
            self._fonts[role] = load_font(str(self.project.font_path(role)))
        return self._fonts[role]

    # ----- structure
    def panel(self, id: str, path, beat: str | None = None, order: int | None = None, border=True,
              note: str | None = None) -> Panel:
        if id in self.panels:
            raise MangakitError(f"duplicate panel id {id}")
        p = Panel(self, id, as_path(path), beat, order if order is not None else len(self.panels) + 1,
                  border=border if isinstance(border, bool) else as_path(border), note=note)
        self.panels[id] = p
        return p

    def layout(self, margins_mm=None, gutter_mm=None):
        """Layout helpers bound to this page (live area, rows, cols, cuts, insets, bleeds)."""
        from .layout import Layout
        return Layout(self, margins_mm, gutter_mm)

    def borders(self, style: str = "panel-border", **over):
        """Stroke every bordered panel (in panel order). Borderless panels (border=False) are skipped;
        border=<Path> strokes that path (e.g. an inset's host keeps its outer frame)."""
        out = []
        for p in sorted(self.panels.values(), key=lambda q: q.order):
            if p.border is False:
                continue
            out.append(self.stroke(p.path if p.border is True else p.border, style=style, name=f"border-{p.id}", **over))
        return out

    # ----- board marks: drawn on the rough and guide views only, never in proof/export
    def focal(self, at, panel: str | None = None, label: str | None = None, rank: int = 1):
        """Declare where the eye should land in a panel (rank 1 = first)."""
        return self._add(Layer("board", self._name("focal"), {"mark": "focal", "at": tuple(at), "panel": panel,
                                                              "label": label, "rank": rank}))

    def sightline(self, frm, to, panel: str | None = None, label: str | None = None):
        """A gaze or motion line that should lead the eye (points or anchor names)."""
        a = self.anchors[frm] if isinstance(frm, str) else tuple(frm)
        b = self.anchors[to] if isinstance(to, str) else tuple(to)
        return self._add(Layer("board", self._name("sightline"), {"mark": "sightline", "from": a, "to": b,
                                                                  "panel": panel, "label": label}))

    def note(self, text: str, at, panel: str | None = None):
        """Board note (camera, framing, acting) at a page point."""
        return self._add(Layer("board", self._name("note"), {"mark": "note", "text": text, "at": tuple(at),
                                                             "panel": panel}))

    def anchor(self, name: str, pt) -> tuple:
        self.anchors[name] = tuple(pt)
        return self.anchors[name]

    def _clip_ref(self, clip):
        if clip is None:
            return None
        if isinstance(clip, (list, tuple)) and clip and all(isinstance(c, Path) for c in clip):
            names = []
            for c in clip:
                r = self._clip_ref(c)
                if not r or r[0] != "breakout":
                    return ["custom", None]
                names.append(r[1])
            return ["breakouts", names]
        for p in self.panels.values():
            if clip is p.path:
                return ["panel", p.id]
        for b in self.breakouts.values():
            if clip is b.path:
                return ["breakout", b.name]
        return ["custom", None]

    @contextmanager
    def group(self, name=None, clip=None, transform: Affine | None = None, opacity: float | None = None):
        g = Layer("group", self._name("group", name), {"clip": as_path(clip) if clip is not None else None,
                                                       "transform": transform, "opacity": opacity, "children": []})
        self._add(g)
        self._stack.append(g.data["children"])
        try:
            yield g
        finally:
            self._stack.pop()

    # ----- art
    def image(self, drawing: Drawing, transform=None, clip=None, source_mask: Mask | None = None,
              opacity: float = 1.0, name=None, panel: str | None = None):
        if isinstance(transform, Placement):
            transform = transform.transform
        transform = transform or Affine()
        ref = self._clip_ref(clip)
        if isinstance(clip, (list, tuple)) and clip and isinstance(clip[0], Path):
            clip = clip[0].union(*clip[1:])  # several declared breakouts used as one clip
        if panel is None and ref:
            if ref[0] == "panel":
                panel = ref[1]
            elif ref[0] == "breakout":
                panel = self.breakouts[ref[1]].panel
            elif ref[0] == "breakouts":
                owners = {self.breakouts[n].panel for n in ref[1]}
                panel = owners.pop() if len(owners) == 1 else None
        return self._add(Layer("image", self._name("image", name), {
            "drawing": drawing, "transform": transform, "clip": as_path(clip) if clip is not None else None,
            "clip_ref": ref, "mask": source_mask, "opacity": opacity, "panel": panel}))

    def overlay(self, file, transform: Affine | None = None, size=None, clip=None, opacity=1.0, name=None):
        """Unregistered raster overlay (texture, paper grain). Prefer registered assets for drawings."""
        from PIL import Image
        with Image.open(file) as im:
            w, h = size or im.size
        d = Drawing(f"overlay:{file}", "file", __import__("pathlib").Path(file).resolve(), w, h, None)
        return self.image(d, transform, clip, None, opacity, name or self._name("overlay"))

    # ----- vector
    def fill(self, path, color="#ffffff", name=None, opacity=1.0):
        return self._add(Layer("fill", self._name("fill", name), {"path": as_path(path), "color": color,
                                                                   "opacity": opacity}))

    def stroke(self, path, style: str | dict = "panel-border", name=None, **over):
        st = dict(self.project.style(style)) if isinstance(style, str) else dict(style)
        st.update(over)
        return self._add(Layer("stroke", self._name("stroke", name), {"path": as_path(path), "style": st,
                                                                       "style_name": style if isinstance(style, str) else None}))

    def raw(self, svg_fragment: str, name=None):
        """Raw SVG in page coordinates (custom vector work)."""
        return self._add(Layer("raw", self._name("raw", name), {"svg": svg_fragment}))

    def effect(self, kind: str, region, seed: int, name=None, clip=True, **params):
        if kind not in EFFECTS:
            raise MangakitError(f"unknown effect {kind}; have {sorted(EFFECTS)}")
        region = as_path(region)
        nm = self._name(kind, name)
        svg = EFFECTS[kind](region, seed=seed, uid=nm, **params)
        self.effect_seeds[nm] = seed
        return self._add(Layer("effect", nm, {"effect": kind, "seed": seed, "params": params,
                                              "region": region, "clip": region if clip else None, "svg": svg}))

    # ----- lettering
    def text(self, text: str, at, font=None, size=None, fill=None, outline: str | None = "",
             outline_width=None, rotate=0.0, anchor="middle", tracking=0.0, skew=0.0, name=None, panel=None,
             line: str | None = None):
        """Typeset a single line (SFX, signs, captions without a balloon). Baseline at at[1].
        line= ties it to a script line (kind sfx); the text then comes from the script when not given."""
        if line is not None:
            l = self.script.line(line)
            if l is None:
                raise MangakitError(f"text line {line!r} is not in the script")
            text = text or l.get("text", "")
        sfx = {"font": "sfx", "size": 60, "fill": "#000000", "outline": "#ffffff", "outline_width": 6.0,
               **self.project.cfg.get("sfx", {})}  # defaults; the art direction's sfx rule may override
        font = font or sfx["font"]
        size = size if size is not None else sfx["size"]
        fill = fill or sfx["fill"]
        outline = sfx["outline"] if outline == "" else outline
        outline_width = outline_width if outline_width is not None else sfx["outline_width"]
        f = self.font(font)
        d, bb = text_path(f, text, at[0], at[1], size, anchor, tracking, skew)
        return self._add(Layer("text", self._name("text", name), {
            "d": d, "bbox": bb, "fill": fill, "outline": outline, "outline_width": outline_width,
            "rotate": rotate, "at": tuple(at), "text": text, "font": font, "panel": panel, "line": line}))

    def balloon(self, dialogue: str, shape="ellipse", at=None, size=None, tail_to=None, breaks=None,
                font="dialogue", font_size=None, aspect=None, tail_gap=None, tail_width=None, panel=None,
                name=None, style="balloon", padding=None, tail_len=None):
        """Balloon for a script line. Wording comes from story/script.yaml (the script owns it);
        `breaks` (list of strings) lets the page own line breaks. `tail_to` = page point or anchor name."""
        lt = self.project.lettering
        line = self.script.line(dialogue)
        if line is None:
            self.issues.append(_issue("error", "missing-dialogue", dialogue, f"{dialogue} not in story/script.yaml"))
            text = f"[{dialogue}?]"
        else:
            text = line.get("text", "")
        fs = font_size or lt.get("font_size", 21)
        emph_role = "dialogue-emphasis" if "dialogue-emphasis" in self.project.fonts() else font
        ts = Typesetter(self.font(font), self.font(emph_role), fs, lt.get("line_height", 1.12),
                        uppercase=lt.get("uppercase", False))
        if breaks:
            # page owns line breaks, but wording must still match the script
            joined = " ".join(" ".join(b.split()) for b in breaks).replace("*", "")
            if " ".join(text.replace("*", "").split()) != joined and line is not None:
                self.issues.append(_issue("error", "breaks-mismatch", dialogue,
                                          f"breaks {breaks!r} do not spell the script text {text!r}"))
            lines = ts.manual(breaks)
        else:
            if aspect is None:
                aspect = 3.2 if shape in ("box", "rect") else 1.5
            lines = ts.balanced(text, aspect)
        bw = max((l.width for l in lines), default=10)
        bh = ts.block_height(lines)
        pad = padding if padding is not None else lt.get("balloon_padding", 16)
        if at is None:
            raise MangakitError(f"balloon {dialogue}: give at=(x, y)")
        cx, cy = at
        if isinstance(shape, (Path, str)) and not (isinstance(shape, str) and shape in
                                                    ("ellipse", "rect", "box", "cloud", "burst")):
            body = as_path(shape)
            shape_name = "custom"
        else:
            shape_name = shape
            body = _balloon_body(shape, cx, cy, bw, bh, pad, size)
        outline = body
        tip = None
        if tail_to is not None and shape_name not in ("box",):
            target = self.anchors[tail_to] if isinstance(tail_to, str) else tuple(tail_to)
            gap = tail_gap if tail_gap is not None else lt.get("tail_gap", 18)
            outline, tip = _with_tail(body, (cx, cy), target, gap, tail_width, tail_len)
        text_d, boxes = ts.render(lines, cx, cy)
        return self._add(Layer("balloon", self._name("balloon", name or dialogue), {
            "dialogue": dialogue, "speaker": (line or {}).get("speaker"), "shape": shape_name,
            "body": body, "outline": outline, "text_d": text_d, "boxes": boxes, "lines": [
                " ".join(w for w, _ in l.words) for l in lines],
            "at": (cx, cy), "tail_tip": tip, "tail_to": tail_to, "style": dict(self.project.style(style)),
            "panel": panel, "font": font, "font_size": fs, "padding": pad}))


def _balloon_body(shape, cx, cy, bw, bh, pad, size):
    if shape in ("rect", "box"):
        w, h = size or (bw + 2 * pad, bh + 2 * pad)
        r = 0 if shape == "box" else min(pad, h / 2)
        g = Polygon([(cx - w / 2 + r, cy - h / 2 + r), (cx + w / 2 - r, cy - h / 2 + r),
                     (cx + w / 2 - r, cy + h / 2 - r), (cx - w / 2 + r, cy + h / 2 - r)])
        if r:
            g = g.buffer(r, quad_segs=8)
        return Path.from_shapely(g)
    if size:
        rx, ry = size[0] / 2, size[1] / 2
    else:
        rx = bw / 2 * math.sqrt(2) + pad
        ry = bh / 2 * math.sqrt(2) + pad * 0.75
    if shape == "ellipse":
        return Path.ellipse(cx, cy, rx, ry)
    if shape == "burst":
        n = max(12, int((rx + ry) / 9))
        pts = []
        for i in range(2 * n):
            t = math.pi * i / n
            k = 1.28 if i % 2 == 0 else 1.0
            pts.append((cx + math.cos(t) * rx * k, cy + math.sin(t) * ry * k))
        return Path.polygon(pts)
    if shape == "cloud":
        n = max(9, int((rx + ry) / 22))
        from shapely import affinity
        from shapely.ops import unary_union
        circles = [affinity.scale(Point(cx, cy).buffer(1, quad_segs=16), rx * 0.92, ry * 0.92)]
        for i in range(n):
            t = 2 * math.pi * i / n
            r = (rx + ry) / 2 * math.sin(math.pi / n) * 1.35
            circles.append(Point(cx + math.cos(t) * rx * 0.92, cy + math.sin(t) * ry * 0.92).buffer(r, quad_segs=12))
        return Path.from_shapely(unary_union(circles))
    raise MangakitError(f"unknown balloon shape {shape}")


def _with_tail(body: Path, center, target, gap, width=None, max_len=None):
    """Curved wedge tail from the balloon toward `target`. The tip stops `gap` short of the
    target and at most `max_len` beyond the balloon edge (default 0.9 x balloon half-height + 30)."""
    from shapely.geometry import LineString
    cx, cy = center
    tx, ty = target
    dx, dy = tx - cx, ty - cy
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    shp = body.shape()
    x0, y0, x1, y1 = shp.bounds
    ray = LineString([(cx, cy), (cx + ux * 1e5, cy + uy * 1e5)])
    hit = shp.exterior.intersection(ray) if hasattr(shp, "exterior") else None
    edge = 0.0
    if hit is not None and not hit.is_empty:
        pts = [hit] if hit.geom_type == "Point" else list(getattr(hit, "geoms", []))
        edge = max(math.hypot(p.x - cx, p.y - cy) for p in pts if p.geom_type == "Point") if pts else 0.0
    if max_len is None:
        max_len = 0.9 * (y1 - y0) / 2 + 30
    reach = min(L - gap, edge + max_len)
    reach = max(reach, edge + 12)
    tip = (cx + ux * reach, cy + uy * reach)
    L = reach
    w = width or max(16.0, min(46.0, 0.5 * min(x1 - x0, y1 - y0) / 2))
    nx, ny = -uy, ux
    b1 = (cx + nx * w / 2, cy + ny * w / 2)
    b2 = (cx - nx * w / 2, cy - ny * w / 2)
    bend = 0.10 * L
    ctrl = ((cx + tip[0]) / 2 + nx * bend, (cy + tip[1]) / 2 + ny * bend)
    pts = []
    for start in (b1, b2):
        seg = []
        for k in range(0, 17):
            t = k / 16
            seg.append(((1 - t) ** 2 * start[0] + 2 * (1 - t) * t * ctrl[0] + t * t * tip[0],
                        (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * ctrl[1] + t * t * tip[1]))
        pts.append(seg)
    poly = pts[0] + list(reversed(pts[1]))
    tail = Polygon(poly).buffer(0)
    return Path.from_shapely(shp.union(tail).simplify(0.05)), tip
