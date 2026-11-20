"""Procedural rough sketches for boards: blocking figures, heads, hands, props, background masses,
plus board annotations (focal points, sightlines, motion arrows, camera/framing notes).

A sketch source is a Python file (convention: art/roughs/<asset-id>.py):

    SIZE = (1200, 900)                       # source px (optional; default 1200 x 900)
    def sketch(s):
        s.block([(0, 600), (1200, 600), (1200, 900), (0, 900)], fill=0.85)      # platform
        s.figure("rin", feet=(700, 820), height=560, facing="left", pose="run", look=(80, 300))
        s.focal((520, 300), "door gap")
        s.note("WIDE, eye level", (30, 40))

`mangakit rough make <asset-id> [source]` renders it (deterministic: same source -> same bytes),
registers a new version of a kind=rough asset only when the bytes changed, stores every named point
as a landmark of that version (so page sources can align to `rin-mouth` and shot guides list it) and
records focal points / sightlines / notes in the version (`rough:`). The PNG carries only the drawing;
annotations are vector overlays on the rough view, so proof and reading views stay clean.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path as FsPath

from PIL import Image

from .assets import Registry
from .geometry import _num
from .project import MangakitError, Project, sha256_bytes, sha256_file

INK, MID, LIGHT = "#2b2b2b", "#9c9c9c", "#e4e4e4"


def _gray(level):
    """level 0 = black .. 1 = white, or a CSS colour."""
    if isinstance(level, str):
        return level
    v = max(0, min(255, round(255 * float(level))))
    return f"#{v:02x}{v:02x}{v:02x}"


def _rot(v, deg):
    a = math.radians(deg)
    return (v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a))


def _add(p, v, k=1.0):
    return (p[0] + v[0] * k, p[1] + v[1] * k)


class Sketch:
    def __init__(self, w=1200, h=900):
        self.w, self.h = int(w), int(h)
        self.svg: list[str] = []
        self.landmarks: dict[str, tuple] = {}
        self.focal_pts: list[dict] = []
        self.sight: list[dict] = []
        self.notes: list[dict] = []
        self.figures: list[dict] = []
        self.unit = max(2.0, min(w, h) / 300)          # base pencil width

    # ---------------- primitives
    def _line(self, pts, width=None, color=INK, dash=None, cap="round", close=False):
        d = "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in pts) + (" Z" if close else "")
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.svg.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{_num(width or self.unit)}" '
                        f'stroke-linecap="{cap}" stroke-linejoin="round"{da}/>')

    def _poly(self, pts, fill=LIGHT, stroke=INK, width=None, dash=None):
        d = "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in pts) + " Z"
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.svg.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{_num(width or self.unit)}" '
                        f'stroke-linejoin="round"{da}/>')

    def _circle(self, c, r, fill=LIGHT, stroke=INK, width=None, dash=None):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.svg.append(f'<circle cx="{_num(c[0])}" cy="{_num(c[1])}" r="{_num(r)}" fill="{fill}" stroke="{stroke}" '
                        f'stroke-width="{_num(width or self.unit)}"{da}/>')

    def landmark(self, name, at):
        self.landmarks[name] = (float(at[0]), float(at[1]))
        return self.landmarks[name]

    # ---------------- background and blocking
    def block(self, pts, fill=0.85, label=None, stroke=INK, dashed=False):
        """Background mass or set piece (polygon). label becomes a rough-view note."""
        self._poly(pts, _gray(fill), stroke, dash="10 8" if dashed else None)
        if label:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            self.note(label, (min(xs) + 10, min(ys) + 30))

    def rect(self, x, y, w, h, fill=0.85, label=None, dashed=False):
        self.block([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], fill, label, dashed=dashed)

    def tone(self, pts, level=0.55):
        """Flat shadow / dark mass (no outline)."""
        self._poly(pts, _gray(level), "none", 0)

    def lines(self, pts, width=None, dashed=False, level=0.17):
        self._line(pts, width, _gray(level), "10 8" if dashed else None)

    def horizon(self, y, label="horizon"):
        self._line([(0, y), (self.w, y)], self.unit * 0.8, MID, "18 10")
        if label:
            self.note(label, (12, y - 10))

    def perspective(self, vp, n=10, spread=(0, 360), length=None):
        L = length or (self.w + self.h)
        for k in range(n):
            a = math.radians(spread[0] + (spread[1] - spread[0]) * (k + 0.5) / n)
            self._line([vp, (vp[0] + math.cos(a) * L, vp[1] + math.sin(a) * L)], self.unit * 0.6, MID)

    def speed(self, x, y, w, h, angle=0.0, n=24, level=0.35):
        """Deterministic speed lines in a box, along `angle` degrees."""
        for k in range(n):
            t = (k * 0.618034) % 1.0
            yy = y + h * (k + 0.5) / n
            ln = w * (0.35 + 0.6 * t)
            x0 = x + (w - ln) * ((k * 0.381966) % 1.0)
            p0, p1 = (x0, yy), (x0 + ln, yy)
            c = (x + w / 2, y + h / 2)
            p0 = _add(c, _rot((p0[0] - c[0], p0[1] - c[1]), angle))
            p1 = _add(c, _rot((p1[0] - c[0], p1[1] - c[1]), angle))
            self._line([p0, p1], self.unit * 0.9, _gray(level))

    # ---------------- props and hands
    def prop(self, name, pts=None, rect=None, fill=0.95, label=None, rotate=0.0):
        """A prop as a polygon (or rect=(x, y, w, h), rotated about its centre). Landmark = centre."""
        if rect:
            x, y, w, h = rect
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        if rotate:
            pts = [_add((cx, cy), _rot((px - cx, py - cy), rotate)) for px, py in pts]
        self._poly(pts, _gray(fill), INK, self.unit * 1.3)
        self.landmark(name, (cx, cy))
        if label:
            self.note(label, (cx + 12, cy - 12))
        return (cx, cy)

    def hand(self, name, wrist, toward, size=120.0, grip=False, sleeve=None, fill=0.9):
        """Mitten hand from `wrist` pointing at `toward` (point or angle in degrees).
        Landmarks: <name> (fingertips), <name>-wrist. sleeve = level of a sleeve block behind the wrist."""
        if isinstance(toward, (int, float)):
            a = math.radians(toward)
        else:
            a = math.atan2(toward[1] - wrist[1], toward[0] - wrist[0])
        ux, uy = math.cos(a), math.sin(a)
        nx, ny = -uy, ux
        L, W = size, size * (0.42 if grip else 0.5)
        if sleeve is not None:
            s0 = _add(wrist, (ux, uy), -size * 1.4)
            self._poly([_add(s0, (nx, ny), W * 0.75), _add(wrist, (nx, ny), W * 0.68),
                        _add(wrist, (nx, ny), -W * 0.68), _add(s0, (nx, ny), -W * 0.75)], _gray(sleeve))
        tip = _add(wrist, (ux, uy), L)
        palm = [_add(wrist, (nx, ny), W / 2), _add(_add(wrist, (ux, uy), L * 0.8), (nx, ny), W / 2),
                _add(tip, (nx, ny), W * 0.25), _add(tip, (nx, ny), -W * 0.25),
                _add(_add(wrist, (ux, uy), L * 0.8), (nx, ny), -W / 2), _add(wrist, (nx, ny), -W / 2)]
        self._poly(palm, _gray(fill), INK, self.unit * 1.2)
        th0 = _add(_add(wrist, (ux, uy), L * 0.25), (nx, ny), W / 2)
        th1 = _add(_add(wrist, (ux, uy), L * (0.55 if grip else 0.62)), (nx, ny), W * (0.75 if not grip else 0.55))
        self._line([th0, th1], self.unit * 4, _gray(fill))
        self._line([th0, th1], self.unit * 1.2, INK)
        self.landmark(name, tip)
        self.landmark(f"{name}-wrist", wrist)
        return tip

    # ---------------- figures
    def head(self, name, center, r, facing="left", look=None, tilt=0.0, shoulders=True, label=None, fill=0.86,
             hair=0.3, body=0.55):
        """Close-up head (and shoulders) with construction lines. Landmarks: <name>-head, -eye, -mouth, -chin."""
        f = {"left": -1, "right": 1}.get(facing, 0)
        cx, cy = center
        if shoulders:
            sw = r * 2.4
            self._poly([(cx - sw, cy + r * 3.2), (cx - sw * 0.92, cy + r * 2.1), (cx - sw * 0.6, cy + r * 1.7),
                        (cx + sw * 0.6, cy + r * 1.7), (cx + sw * 0.92, cy + r * 2.1), (cx + sw, cy + r * 3.2)],
                       _gray(body))
            self._poly([(cx - r * 0.38, cy + r * 0.8), (cx + r * 0.38, cy + r * 0.8),
                        (cx + r * 0.45, cy + r * 1.75), (cx - r * 0.45, cy + r * 1.75)], _gray(fill))
        if hair is not None:   # hair mass on the back/top of the head reads the facing at a glance
            hf = f if f else 0
            self._circle((cx - hf * r * 0.22, cy - r * 0.16), r * 1.02, _gray(hair), INK, self.unit * 1.4)
            self._circle((cx + hf * r * 0.08, cy + r * 0.06), r * 0.9, _gray(fill), "none", 0)
        else:
            self._circle(center, r, _gray(fill), INK, self.unit * 1.4)
        # construction: face centre line (shifted for 3/4 view), eye line, nose and mouth ticks
        off = f * r * 0.42
        self._line([(cx + off * 0.7, cy - r * 0.95), (cx + off, cy), (cx + off * 0.7, cy + r * 0.95)], self.unit, MID)
        ey = cy - r * 0.05
        self._line([(cx - r * 0.95, ey + tilt), (cx + r * 0.95, ey - tilt)], self.unit, MID)
        eye = (cx + off + f * r * 0.18, ey)
        nose = (cx + off + f * r * 0.55, cy + r * 0.28)
        mouth = (cx + off + f * r * 0.3, cy + r * 0.55)
        self._line([(cx + off, cy + r * 0.05), nose, (cx + off + f * r * 0.1, cy + r * 0.35)], self.unit * 1.2, INK)
        self._line([(mouth[0] - r * 0.18, mouth[1]), (mouth[0] + r * 0.12, mouth[1])], self.unit * 1.4, INK)
        self._circle(eye, r * 0.07, INK, INK, 1)
        self.landmark(f"{name}-head", center)
        self.landmark(f"{name}-eye", eye)
        self.landmark(f"{name}-mouth", mouth)
        self.landmark(f"{name}-chin", (cx + off * 0.7, cy + r))
        if look is not None:
            self.sightline(eye, look, label=f"{name} looks")
        if label:
            self.note(label, (cx + r + 12, cy - r))
        self.figures.append({"name": name, "kind": "head", "center": list(center), "r": r, "facing": facing})
        return eye

    def figure(self, name, feet, height, facing="left", pose="stand", lean=0.0, reach=None, look=None,
               hidden=False, label=None, fill=0.55, hair=0.25):
        """Blocking mannequin standing on `feet` (x, y), `height` px tall.
        pose: stand | walk | run | reach | sit. facing: left | right | front | back.
        reach: point for the leading hand. look: point the figure looks at (adds a sightline).
        hidden: dashed outline (someone present but unseen). Landmarks: <name>-head, -eye, -mouth,
        -hand (leading), -hand-back, -chest, -hip, -feet."""
        f = {"left": -1, "right": 1}.get(facing, 1)
        u = height / 8.0
        fx, fy = feet
        hip = (fx, fy - 4 * u) if pose != "sit" else (fx, fy - 2.3 * u)
        up = lambda v: _add(hip, _rot(v, lean * f))       # noqa: E731  upper body leans toward facing
        neck = up((0, -2.85 * u))
        head = up((0, -3.45 * u))
        chest = up((0, -2.0 * u))
        if pose == "run":
            legs = [((fx + f * 1.3 * u, hip[1] + 1.4 * u), (fx + f * 1.7 * u, fy - 0.15 * u)),
                    ((fx - f * 0.6 * u, hip[1] + 1.8 * u), (fx - f * 1.9 * u, fy - 1.1 * u))]
            arms = [(_add(neck, (f * 1.0 * u, 1.0 * u)), _add(neck, (f * 1.7 * u, 0.2 * u))),
                    (_add(neck, (-f * 0.9 * u, 1.1 * u)), _add(neck, (-f * 1.4 * u, 2.0 * u)))]
        elif pose == "walk":
            legs = [((fx + f * 0.5 * u, hip[1] + 2.0 * u), (fx + f * 1.0 * u, fy)),
                    ((fx - f * 0.3 * u, hip[1] + 2.0 * u), (fx - f * 0.8 * u, fy))]
            arms = [(_add(neck, (f * 0.5 * u, 1.4 * u)), _add(neck, (f * 0.8 * u, 2.7 * u))),
                    (_add(neck, (-f * 0.4 * u, 1.4 * u)), _add(neck, (-f * 0.7 * u, 2.7 * u)))]
        elif pose == "sit":
            legs = [((fx + f * 1.8 * u, hip[1] - 0.1 * u), (fx + f * 1.9 * u, fy)),
                    ((fx + f * 1.6 * u, hip[1] + 0.1 * u), (fx + f * 1.5 * u, fy))]
            arms = [(_add(neck, (f * 0.6 * u, 1.3 * u)), _add(neck, (f * 1.4 * u, 2.2 * u))),
                    (_add(neck, (-f * 0.2 * u, 1.4 * u)), _add(neck, (f * 0.6 * u, 2.6 * u)))]
        else:  # stand / reach
            legs = [((fx + 0.25 * u, hip[1] + 2.0 * u), (fx + 0.4 * u, fy)),
                    ((fx - 0.25 * u, hip[1] + 2.0 * u), (fx - 0.4 * u, fy))]
            arms = [(_add(neck, (f * 0.5 * u, 1.4 * u)), _add(neck, (f * 0.6 * u, 2.8 * u))),
                    (_add(neck, (-f * 0.5 * u, 1.4 * u)), _add(neck, (-f * 0.6 * u, 2.8 * u)))]
        if reach is not None or pose == "reach":
            tgt = reach or _add(neck, (f * 3.0 * u, 0))
            dx, dy = tgt[0] - neck[0], tgt[1] - neck[1]
            dist = math.hypot(dx, dy) or 1
            L = min(dist, 2.9 * u)
            hand = (neck[0] + dx / dist * L, neck[1] + dy / dist * L)
            elbow = _add(((neck[0] + hand[0]) / 2, (neck[1] + hand[1]) / 2), (0, 0.35 * u))
            arms[0] = (elbow, hand)
        dash = "14 9" if hidden else None
        body_col = _gray(fill) if not hidden else "none"
        lw = u * 0.7
        # back limbs first (lighter), torso, then front limbs
        segs_back = [(hip, legs[1][0], legs[1][1]), (neck, arms[1][0], arms[1][1])]
        segs_front = [(hip, legs[0][0], legs[0][1]), (neck, arms[0][0], arms[0][1])]
        for a, b, c in segs_back:
            self._limb([a, b, c], lw, _gray(min(1, fill + 0.08)) if not hidden else "none", dash)
        self._limb([hip, chest, neck], u * 1.05, body_col, dash)
        for a, b, c in segs_front:
            self._limb([a, b, c], lw, body_col, dash)
        self._circle(head, u * 0.55, body_col if not hidden else "none", INK, self.unit * 1.4, dash)
        if not hidden and hair is not None and facing in ("left", "right"):
            self._circle(_add(head, (-f * 0.16 * u, -0.12 * u)), u * 0.42, _gray(hair), "none", 0)
        # facing tick (nose direction)
        if facing in ("left", "right"):
            self._line([_add(head, (f * 0.45 * u, 0)), _add(head, (f * 0.75 * u, 0.12 * u))], self.unit * 1.5, INK)
        eye = _add(head, (f * 0.28 * u, -0.05 * u)) if facing in ("left", "right") else head
        mouth = _add(head, (f * 0.3 * u, 0.28 * u)) if facing in ("left", "right") else _add(head, (0, 0.3 * u))
        for nm, pt in (("head", head), ("eye", eye), ("mouth", mouth), ("hand", arms[0][1]), ("hand-back", arms[1][1]),
                       ("chest", chest), ("hip", hip), ("feet", (fx, fy))):
            self.landmark(f"{name}-{nm}", pt)
        if look is not None:
            self.sightline(eye, look, label=f"{name} looks")
        if label:
            self.note(label, (head[0] + u * 0.8, head[1] - u * 0.6))
        self.figures.append({"name": name, "kind": "figure", "feet": list(feet), "height": height, "pose": pose,
                             "facing": facing, "hidden": hidden})
        return self

    def _limb(self, pts, width, color, dash):
        if color != "none":
            self._line(pts, width, color, None)
        self._line(pts, self.unit * 1.2, INK, dash)

    # ---------------- annotations (rough view overlay, never baked into the PNG)
    def focal(self, at, label=None, rank=1):
        self.focal_pts.append({"at": [float(at[0]), float(at[1])], "label": label, "rank": rank})
        self.landmark(f"focal-{rank}" if rank > 1 else "focal", at)

    def sightline(self, frm, to, label=None, kind="sight"):
        a = self.landmarks[frm] if isinstance(frm, str) else frm
        b = self.landmarks[to] if isinstance(to, str) else to
        self.sight.append({"from": [float(a[0]), float(a[1])], "to": [float(b[0]), float(b[1])], "label": label,
                           "kind": kind})

    def arrow(self, frm, to, label=None, kind="motion"):
        self.sightline(frm, to, label, kind)

    def note(self, text, at):
        self.notes.append({"text": str(text), "at": [float(at[0]), float(at[1])]})

    def camera(self, text):
        """Camera / framing note, bottom-left of the sketch (the panel label sits top-left)."""
        self.note(text, (16, self.h - 20))

    def document(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
                f'height="{self.h}"><rect width="{self.w}" height="{self.h}" fill="#ffffff"/>{"".join(self.svg)}</svg>')

    def meta(self) -> dict:
        return {"focal": self.focal_pts, "sightlines": self.sight, "notes": self.notes, "figures": self.figures}


def run_sketch(source) -> Sketch:
    source = FsPath(source)
    spec = importlib.util.spec_from_file_location(f"mangakit_rough_{abs(hash(str(source)))}", source)
    mod = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    if not hasattr(mod, "sketch"):
        raise MangakitError(f"{source} must define sketch(s)")
    w, h = getattr(mod, "SIZE", (1200, 900))
    s = Sketch(w, h)
    mod.sketch(s)
    return s


def make_rough(project: Project, aid: str, source=None, note: str = "") -> tuple[str, bool, dict]:
    """Render a sketch source to a kind=rough asset version. Returns (version, created, info).
    Idempotent: unchanged source and bytes -> the current selected version, nothing written."""
    from .render import rasterize
    src = FsPath(source) if source else project.root / "art" / "roughs" / f"{aid}.py"
    if not src.exists():
        raise MangakitError(f"no sketch source {src}")
    s = run_sketch(src)
    work = project.build_dir("roughs", aid)
    svg = work / "sketch.svg"
    svg.write_text(s.document())
    png = work / "sketch.png"
    rasterize(svg, png, s.w)
    im = Image.open(png).convert("RGBA")
    bg = Image.new("RGBA", im.size, "white")
    bg.alpha_composite(im)
    bg.convert("L").save(png, optimize=False)
    sha = sha256_file(png)
    reg = Registry(project)
    if reg.exists(aid):
        rec = reg.load(aid)
        if rec.get("kind") not in (None, "rough"):
            raise MangakitError(f"{aid} is a {rec.get('kind')} asset; rough sketches need their own asset id")
        sel = rec.get("selected")
        if sel and rec["versions"][sel]["sha256"] == sha:
            return sel, False, {"file": str(reg.file(aid, sel)), "landmarks": len(s.landmarks)}
    ver = reg.add_version(aid, png, note=note or f"rough sketch from {src.name}", select=True, kind="rough")
    rec = reg.load(aid)
    # provenance: keep the exact sketch source next to the version (immutable like the PNG)
    keep = reg.dir / aid / f"{ver}.sketch.py"
    keep.write_bytes(src.read_bytes())
    try:
        rel = str(src.resolve().relative_to(project.root))
    except ValueError:
        rel = str(src)
    rec["versions"][ver]["rough"] = {"source": rel, "source_sha256": sha256_bytes(src.read_bytes()),
                                     "source_copy": keep.name, **s.meta()}
    rec["versions"][ver]["origin"] = rel
    rec.setdefault("landmarks", {})[ver] = {k: {"xy": [round(x, 1), round(y, 1)], "protect": False, "note": "rough"}
                                            for k, (x, y) in s.landmarks.items()}
    reg.save(aid, rec)
    return ver, True, {"file": str(reg.file(aid, ver)), "landmarks": len(s.landmarks)}
