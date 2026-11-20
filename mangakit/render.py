"""Renderer: page source -> Page -> SVG -> PNG (resvg), plus views and manifests.

Rendering never generates art: it only reads registered, selected (or pinned) bytes.
"""
from __future__ import annotations

import datetime as _dt
import html
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path as FsPath

from PIL import Image, ImageDraw

from . import __version__
from .assets import Art, Registry
from .geometry import Affine, Path, _num
from .page import Page
from .project import (VENDOR_RESVG, MangakitError, Project, Script, load_yaml, sha256_bytes,
                      sha256_file)
from .text import load_font, text_path

CONTRAST_BG = "#ff00ff"


# ------------------------------------------------------------------ loading
def alt_file(project: Project, page_id: str, alt: str, chapter=None) -> FsPath:
    return project.root / "chapters" / str(chapter or project.chapter) / "pages" / f"{page_id}.alt-{alt}.py"


def load_page(project: Project, page_ref: str, pins: dict | None = None, page_file=None,
              script_data=None, chapter=None, style_render=None, style_revision=None, alt=None) -> tuple[Page, FsPath]:
    """style_render: project.yaml overrides (lettering, styles, sfx) from the art direction. None = take
    them from the style revision effective for the chapter (references/direction.yaml); rebuild passes
    the recorded ones. alt: load the alternate layout chapters/<ch>/pages/<page>.alt-<alt>.py."""
    if alt:
        page_file = alt_file(project, page_ref, alt, chapter)
        if not page_file.exists():
            raise MangakitError(f"no alternate {page_file.relative_to(project.root)} (board alt {page_ref} {alt})")
    f = FsPath(page_file) if page_file else project.page_file(page_ref, chapter)
    if style_render is None:
        from .design import Direction
        style_revision, style_render = Direction(project).render_params(chapter)
    if style_render:
        from .design import _deep_merge
        project = Project(project.root, cfg=_deep_merge(project.cfg, style_render))
    page_id = page_ref if page_file else f.stem
    if page_file and ".alt-" in FsPath(page_file).stem and page_id == FsPath(page_file).stem:
        page_id, alt = FsPath(page_file).stem.split(".alt-", 1)
    spec = importlib.util.spec_from_file_location(f"mangakit_page_{page_id}_{abs(hash(str(f)))}", f)
    mod = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # keep __pycache__ out of the project
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    if not hasattr(mod, "build"):
        raise MangakitError(f"{f} must define build(page, art, script)")
    art = Art(project, pins)
    script = Script(project, data=script_data) if script_data is not None else Script(project)
    page = Page(project, page_id, art, script)
    page.alt = alt
    page.side = _page_side(project, page_id, chapter)
    res = mod.build(page, art, script)
    page = res if isinstance(res, Page) else page
    page.source_file = f
    page.style_info = {"revision": style_revision, "render": style_render or {}}
    page.chapter = str(chapter or project.chapter)
    return page, f


def _page_side(project: Project, page_id: str, chapter=None) -> str | None:
    """'left' or 'right': the page's slot in its spread (pairing + reading direction)."""
    try:
        pages = project.chapter_pages(chapter)
    except Exception:
        return None
    if page_id not in pages:
        return None
    rtl = project.direction == "rtl"
    for g in spread_groups(project, pages, chapter):
        if page_id in g:
            if len(g) == 1:
                return "left" if lone_slot(project, g, pages, chapter) == 0 else "right"
            first = g.index(page_id) == 0
            return ("right" if first else "left") if rtl else ("left" if first else "right")
    return None


# ------------------------------------------------------------------ svg emission
class SvgWriter:
    def __init__(self, page: Page, svg_dir: FsPath, view: str = "proof", highlight_panel=None):
        self.page, self.dir, self.view = page, FsPath(svg_dir), view
        self.defs: list[str] = []
        self.n = 0
        self.highlight = highlight_panel

    def uid(self, p):
        self.n += 1
        return f"{p}{self.n}"

    def href(self, f) -> str:
        return html.escape(os.path.relpath(FsPath(f).resolve(), self.dir.resolve()))

    def clip_attr(self, path: Path | None) -> str:
        if path is None:
            return ""
        cid = self.uid("clip")
        self.defs.append(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse">'
                         f'<path d="{path.d()}" clip-rule="evenodd"/></clipPath>')
        return f' clip-path="url(#{cid})"'

    # layers
    def layer(self, L) -> str:
        if self.view == "art" and L.kind in ("balloon", "text"):
            return ""  # art-only crops (for illustration packs) carry no lettering
        fn = getattr(self, f"l_{L.kind}")
        return fn(L)

    def l_group(self, L):
        d = L.data
        attrs = self.clip_attr(d["clip"])
        if d["transform"] is not None:
            attrs += f' transform="{d["transform"].to_svg()}"'
        if d["opacity"] is not None:
            attrs += f' opacity="{d["opacity"]}"'
        return f'<g id="{L.name}"{attrs}>' + "".join(self.layer(c) for c in d["children"]) + "</g>"

    def l_image(self, L):
        d = L.data
        dr = d["drawing"]
        op = d["opacity"]
        is_break = d["mask"] is not None
        if self.view == "rough" and dr.kind != "rough":
            op *= 0.4
        if self.view == "masks" and not is_break:
            op *= 0.25
        inner_attr = ""
        if dr.missing or dr.file is None:
            body = (f'<rect width="{dr.width}" height="{dr.height}" fill="#d0d0d0" stroke="#808080" stroke-width="6"/>'
                    f'<path d="M0 0 L{dr.width} {dr.height} M{dr.width} 0 L0 {dr.height}" stroke="#808080" stroke-width="6"/>'
                    + self.label(f"MISSING ART: {dr.asset_id}", dr.width / 2, dr.height / 2 - 20, 40, "#606060", "middle"))
        else:
            if d["mask"] is not None and d["mask"].file is not None:
                mid = self.uid("mask")
                m = d["mask"]
                self.defs.append(
                    f'<mask id="{mid}" maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" '
                    f'x="0" y="0" width="{m.width}" height="{m.height}">'
                    f'<image href="{self.href(m.file)}" x="0" y="0" width="{m.width}" height="{m.height}" '
                    f'preserveAspectRatio="none"/></mask>')
                inner_attr = f' mask="url(#{mid})"'
            body = (f'<image href="{self.href(dr.file)}" x="0" y="0" width="{dr.width}" height="{dr.height}" '
                    f'preserveAspectRatio="none"{inner_attr}/>')
        return (f'<g id="{L.name}"{self.clip_attr(d["clip"])} opacity="{_num(op)}">'
                f'<g transform="{d["transform"].to_svg()}">{body}</g></g>')

    def l_fill(self, L):
        d = L.data
        return f'<path id="{L.name}" d="{d["path"].d()}" fill="{d["color"]}" fill-rule="evenodd" opacity="{d["opacity"]}"/>'

    def l_stroke(self, L):
        d, st = L.data, L.data["style"]
        return (f'<path id="{L.name}" d="{d["path"].d()}" fill="none" stroke="{st.get("stroke", "#000")}" '
                f'stroke-width="{st.get("width", 2)}" stroke-linejoin="{st.get("join", "miter")}" '
                f'stroke-linecap="{st.get("cap", "butt")}" stroke-miterlimit="10"/>')

    def l_raw(self, L):
        return f'<g id="{L.name}">{L.data["svg"]}</g>'

    def l_effect(self, L):
        d = L.data
        return f'<g id="{L.name}"{self.clip_attr(d["clip"])}>{d["svg"]}</g>'

    def l_text(self, L):
        d = L.data
        tr = ""
        if d["rotate"]:
            tr = f' transform="rotate({_num(d["rotate"])} {_num(d["at"][0])} {_num(d["at"][1])})"'
        out = f'<g id="{L.name}"{tr}>'
        if d["outline"]:
            out += (f'<path d="{d["d"]}" fill="{d["outline"]}" stroke="{d["outline"]}" '
                    f'stroke-width="{d["outline_width"] * 2}" stroke-linejoin="round"/>')
        out += f'<path d="{d["d"]}" fill="{d["fill"]}"/></g>'
        return out

    def l_board(self, L):
        if self.view != "rough":
            return ""   # board marks never reach proof, reading or export renders
        return board_marks_svg(self, [L.data])

    def l_balloon(self, L):
        d, st = L.data, L.data["style"]
        return (f'<g id="{L.name}"><path d="{d["outline"].d()}" fill="{st.get("fill", "#fff")}" '
                f'stroke="{st.get("stroke", "#000")}" stroke-width="{st.get("width", 2.4)}" '
                f'stroke-linejoin="round" fill-rule="evenodd"/>'
                f'<path d="{d["text_d"]}" fill="{st.get("text", "#000")}"/></g>')

    # overlays for rough/guide views
    def label(self, text, x, y, size=18, fill="#0050ff", anchor="start"):
        f = load_font(str(self.page.project.font_path("caption")))
        d, _ = text_path(f, text, x, y, size, anchor)
        return (f'<path d="{d}" fill="#ffffff" stroke="#ffffff" stroke-width="5" stroke-linejoin="round"/>'
                f'<path d="{d}" fill="{fill}"/>')

    def overlays_rough(self):
        out = []
        for p in self.page.panels.values():
            x0, y0, x1, y1 = p.bbox
            from shapely.geometry import LineString
            probe = LineString([(x0 + 14, y0 - 1), (x0 + 14, y1 + 1)]).intersection(p.path.shape())
            top = probe.bounds[1] if not probe.is_empty else y0
            if p.note is not None:   # board pages: keep labels on the paper for bleed panels
                top, x0 = max(top, 0.0), max(x0, 0.0)
            out.append(f'<path d="{p.path.d()}" fill="none" stroke="#0050ff" stroke-width="2" stroke-dasharray="10 6"/>')
            out.append(self.label(f"{p.order}. {p.id}" + (f"  [{p.beat}]" if p.beat else ""), x0 + 12, top + 30, 20))
            if p.note:
                out.append(self.label(p.note, x0 + 12, top + 54, 17, "#0050ff"))
        for b in self.page.breakouts.values():
            out.append(_hatch(self, b.path, "#ff2a2a"))
        for L in iter_layers(self.page.layers):   # rough sketches: their focal points / sightlines / notes
            if L.kind == "image" and L.data["drawing"].kind == "rough" and L.data["drawing"].meta and not L.data["mask"]:
                marks = rough_marks_on_page(L)
                if marks:
                    out.append(f'<g{self.clip_attr(L.data["clip"])}>' + board_marks_svg(self, marks) + "</g>")
        for i, L in enumerate(_balloons(self.page.layers), 1):
            x0, y0, x1, y1 = L.data["body"].bbox()
            x, y = x0 + 6, y0 + 6
            out.append(f'<circle cx="{_num(x)}" cy="{_num(y)}" r="14" fill="#ff7a00"/>')
            out.append(self.label(str(i), x, y + 7, 18, "#ffffff", "middle"))
        return "".join(out)

    def document(self, viewbox, extra="", bg="#ffffff", guides=False) -> str:
        pg = self.page
        body = "".join(self.layer(L) for L in pg.layers)
        if self.view == "rough":
            extra = self.overlays_rough() + extra
        if guides:
            extra += (f'<path d="{pg.trim.d()}" fill="none" stroke="#00b7ff" stroke-width="1.2"/>'
                      f'<path d="{pg.safe.d()}" fill="none" stroke="#00b7ff" stroke-width="1" stroke-dasharray="4 6"/>')
        x, y, w, h = viewbox
        return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'viewBox="{_num(x)} {_num(y)} {_num(w)} {_num(h)}" width="{_num(w)}" height="{_num(h)}">'
                f'<defs>{"".join(self.defs)}</defs>'
                f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" fill="{bg}"/>'
                f'{body}{extra}</svg>')


def _balloons(layers):
    out = []
    for L in layers:
        if L.kind == "balloon":
            out.append(L)
        elif L.kind == "group":
            out += _balloons(L.data["children"])
    return out


def iter_layers(layers):
    for L in layers:
        yield L
        if L.kind == "group":
            yield from iter_layers(L.data["children"])


def rough_marks_on_page(L) -> list[dict]:
    """A rough sketch's declared focal points, sightlines, arrows and notes mapped to page units."""
    t = L.data["transform"]
    m = L.data["drawing"].meta
    out = []
    for f in m.get("focal", []):
        out.append({"mark": "focal", "at": t.apply(f["at"]), "label": f.get("label"), "rank": f.get("rank", 1),
                    "panel": L.data["panel"], "from_rough": L.data["drawing"].asset_id})
    for a in m.get("sightlines", []):
        out.append({"mark": "sightline", "from": t.apply(a["from"]), "to": t.apply(a["to"]), "label": a.get("label"),
                    "kind": a.get("kind", "sight"), "panel": L.data["panel"], "from_rough": L.data["drawing"].asset_id})
    for n in m.get("notes", []):
        out.append({"mark": "note", "text": n["text"], "at": t.apply(n["at"]), "panel": L.data["panel"],
                    "from_rough": L.data["drawing"].asset_id})
    return out


def board_marks_svg(w: "SvgWriter", marks) -> str:
    out = []
    for m in marks:
        if m["mark"] == "focal":
            x, y = m["at"]
            out.append(f'<circle cx="{_num(x)}" cy="{_num(y)}" r="22" fill="none" stroke="#e00000" stroke-width="3"/>'
                       f'<circle cx="{_num(x)}" cy="{_num(y)}" r="8" fill="#e00000"/>')
            out.append(w.label(f"F{m.get('rank', 1)}" + (f" {m['label']}" if m.get("label") else ""), x + 26, y - 14, 17, "#e00000"))
        elif m["mark"] == "sightline":
            (x1, y1), (x2, y2) = m["from"], m["to"]
            col = "#e00000" if m.get("kind", "sight") == "sight" else "#0050ff"
            import math as _m
            a = _m.atan2(y2 - y1, x2 - x1)
            hx1, hy1 = x2 - 22 * _m.cos(a - 0.45), y2 - 22 * _m.sin(a - 0.45)
            hx2, hy2 = x2 - 22 * _m.cos(a + 0.45), y2 - 22 * _m.sin(a + 0.45)
            out.append(f'<path d="M{_num(x1)} {_num(y1)} L{_num(x2)} {_num(y2)}" stroke="{col}" stroke-width="3" '
                       f'stroke-dasharray="12 7" fill="none"/>'
                       f'<path d="M{_num(hx1)} {_num(hy1)} L{_num(x2)} {_num(y2)} L{_num(hx2)} {_num(hy2)}" '
                       f'stroke="{col}" stroke-width="3" fill="none"/>')
            if m.get("label"):
                out.append(w.label(m["label"], (x1 + x2) / 2 + 8, (y1 + y2) / 2 - 8, 15, col))
        elif m["mark"] == "note":
            x, y = m["at"]
            out.append(w.label(m["text"], x, y, 17, "#0050ff"))
    return "".join(out)


def _hatch(w: SvgWriter, path: Path, color):
    pid = w.uid("hatch")
    w.defs.append(f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="12" height="12" '
                  f'patternTransform="rotate(45)"><rect width="5" height="12" fill="{color}" opacity="0.35"/></pattern>')
    return (f'<path d="{path.d()}" fill="url(#{pid})" stroke="{color}" stroke-width="2" '
            f'stroke-dasharray="6 4" fill-rule="evenodd"/>')


# ------------------------------------------------------------------ rasterize
def resvg_bin() -> str:
    if VENDOR_RESVG.exists():
        return str(VENDOR_RESVG)
    b = shutil.which("resvg")
    if not b:
        raise MangakitError("resvg not found (expected vendored binary at %s)" % VENDOR_RESVG)
    return b


def rasterize(svg_file: FsPath, png_file: FsPath, width_px: int):
    cmd = [resvg_bin(), "--width", str(int(round(width_px))), "--shape-rendering", "geometricPrecision",
           "--image-rendering", "optimizeQuality", "--skip-system-fonts", str(svg_file), str(png_file)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise MangakitError(f"resvg failed: {r.stderr.strip()}")
    if r.stderr.strip():
        print("resvg:", r.stderr.strip(), file=sys.stderr)


# ------------------------------------------------------------------ manifest
def snapshot(project: Project, data: bytes, ext: str) -> str:
    h = sha256_bytes(data)
    d = project.root / "history" / "snapshots"   # not regenerable: keep under version control
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{h}{ext}"
    if not f.exists():
        f.write_bytes(data)
    return os.path.relpath(f, project.root)


def manifest_for(page: Page, view: str, outputs: list[FsPath], params: dict) -> dict:
    pr = page.project
    reg = Registry(pr)
    src_bytes = FsPath(page.source_file).read_bytes()
    script_bytes = page.script.path.read_bytes() if page.script.path.exists() else b""
    proj_bytes = (pr.root / "project.yaml").read_bytes()
    assets, masks = [], []
    for aid, d in sorted(page.art.used.items()):
        assets.append({"id": aid, "version": d.version, "sha256": d.sha256,
                       "file": os.path.relpath(d.file, pr.root) if d.file else None,
                       "landmarks": {k: v["xy"] for k, v in d.landmarks.items()}})
    for key, m in sorted(page.art.used_masks.items()):
        masks.append({"key": key, "version": m.version, "sha256": m.sha256, "source_version": m.source_version,
                      "file": os.path.relpath(m.file, pr.root) if m.file else None})
    overlays = []
    for L in iter_layers(page.layers):
        if L.kind == "image" and str(L.data["drawing"].asset_id).startswith("overlay:"):
            f = L.data["drawing"].file
            overlays.append({"file": str(f), "sha256": sha256_file(f) if f and f.exists() else None})
    rv = subprocess.run([resvg_bin(), "--version"], capture_output=True, text=True).stdout.strip()
    return {
        "mangakit": __version__,
        "page": page.id,
        "view": view,
        "params": params,
        "created": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "page_source": {"path": os.path.relpath(page.source_file, pr.root), "sha256": sha256_bytes(src_bytes),
                        "snapshot": snapshot(pr, src_bytes, ".py")},
        "script": {"sha256": sha256_bytes(script_bytes), "snapshot": snapshot(pr, script_bytes, ".yaml"),
                   "lines_used": dict(sorted(page.script.used.items()))},
        "project_yaml": {"sha256": sha256_bytes(proj_bytes), "snapshot": snapshot(pr, proj_bytes, ".yaml")},
        "assets": assets,
        "masks": masks,
        "overlays": overlays,
        "fonts": {k: {"file": v["file"], "sha256": v["sha256"]} for k, v in pr.fonts().items()},
        "effects": page.effect_seeds,
        "style": getattr(page, "style_info", {"revision": None, "render": {}}),
        "renderer": {"name": "resvg", "version": rv, "sha256": sha256_file(resvg_bin())},
        "outputs": [{"file": os.path.relpath(o, pr.root) if str(o).startswith(str(pr.root)) else str(o),
                     "sha256": sha256_file(o), "size": list(Image.open(o).size)} for o in outputs if o.suffix == ".png"],
    }


def pins_from_manifest(man: dict) -> dict:
    pins = {a["id"]: a["version"] for a in man["assets"] if a["version"]}
    pins.update({f"{a['id']}#landmarks": a.get("landmarks") or {} for a in man["assets"] if a["version"]})
    pins.update({m["key"]: m["version"] for m in man["masks"] if m["version"]})
    return pins


def write_manifest(out_png: FsPath, page: Page, view: str, params: dict, extra_outputs=()):
    man = manifest_for(page, view, [out_png, *extra_outputs], params)
    mf = out_png.with_suffix(".manifest.json")
    mf.write_text(json.dumps(man, indent=2))
    return mf


# ------------------------------------------------------------------ views
def _out(project, page, name, out=None) -> FsPath:
    if out:
        o = FsPath(out).resolve()
        o.parent.mkdir(parents=True, exist_ok=True)
        return o
    pid = page.id + (f".alt-{page.alt}" if getattr(page, "alt", None) else "")
    return project.build_dir(f"ch{getattr(page, 'chapter', None) or project.chapter}", pid) / f"{name}.png"


def render_page(page: Page, view="proof", out=None, dpi=None, height_px=None, profile=None, panel=None,
                manifest=True, region=None, art_only=False) -> FsPath:
    pr = page.project
    rc = pr.render_cfg
    b = page.bleed
    bleed_vb = (-b, -b, page.width + 2 * b, page.height + 2 * b)
    trim_vb = (0, 0, page.width, page.height)
    params = {"view": view}
    if view == "guide":
        return render_guide(page, panel, out)
    if view == "detail":
        if not region:
            raise MangakitError("detail view needs region x0,y0,x1,y1 in page units")
        x0, y0, x1, y1 = region
        tag = "-".join(str(int(v)) for v in region)
        png = _out(pr, page, f"detail-{tag}", out)
        w = SvgWriter(page, png.parent, "art" if art_only else "detail")
        vb = (x0, y0, x1 - x0, y1 - y0)
        svg = w.document(vb)
        dpi = dpi or 600
        params.update({"region": list(region), "art_only": art_only})
    elif view == "export":
        prof = pr.cfg["output_profiles"][profile or "print"]
        vb = bleed_vb if prof.get("bleed", True) else trim_vb
        dpi = dpi or prof["dpi"]
        png = _out(pr, page, f"export-{profile or 'print'}", out)
        params.update({"profile": profile or "print", "dpi": dpi, **prof})
        w = SvgWriter(page, png.parent, "export")
        svg = w.document(vb)
    else:
        name = {"proof": "proof", "rough": "rough", "masks": "masks", "reading": "reading"}[view]
        png = _out(pr, page, name, out)
        w = SvgWriter(page, png.parent, view)
        if view == "reading":
            vb = trim_vb
            svg = w.document(vb)
        elif view == "masks":
            vb = bleed_vb
            extra = "".join(f'<path d="{p.path.d()}" fill="none" stroke="#00ffff" stroke-width="1.5"/>'
                            for p in page.panels.values())
            extra += "".join(f'<path d="{bk.path.d()}" fill="none" stroke="#ffff00" stroke-width="1.5" '
                             f'stroke-dasharray="6 4"/>' for bk in page.breakouts.values())
            svg = w.document(vb, extra=extra, bg=CONTRAST_BG)
        else:
            vb = bleed_vb
            svg = w.document(vb, guides=(view == "proof"))
        dpi = dpi or rc.get("proof_dpi", 150)
    svg_file = png.with_suffix(".svg")
    svg_file.write_text(svg)
    if view == "reading":
        hp = height_px or rc.get("reading_height_px", 1100)
        width_px = hp * vb[2] / vb[3]
        params["height_px"] = hp
    else:
        width_px = pr.units_to_px(vb[2], dpi)
        params["dpi"] = dpi
    rasterize(svg_file, png, width_px)
    if view == "export":
        im = Image.open(png)
        mode = pr.cfg["output_profiles"][profile or "print"].get("mode", "RGB")
        bg = Image.new("RGBA", im.size, "white")
        bg.alpha_composite(im.convert("RGBA"))
        bg.convert(mode).save(png, dpi=(dpi, dpi), optimize=True)
    if manifest:
        write_manifest(png, page, view, params, [svg_file])
    return png


def render_guide(page: Page, panel_id: str, out=None, margin=40) -> FsPath:
    """Shot guide for one panel: crop, landmarks, reserved lettering, breakout/bleed drawing area."""
    pr = page.project
    if panel_id not in page.panels:
        raise MangakitError(f"no panel {panel_id}; have {list(page.panels)}")
    P = page.panels[panel_id]
    region = P.path
    for b in P.breakouts:
        region = region.union(b.path)
    x0, y0, x1, y1 = region.bbox()
    # panels touching the trim edge need art through the bleed
    b = page.bleed
    if x0 <= 1: x0 = -b
    if y0 <= 1: y0 = -b
    if x1 >= page.width - 1: x1 = page.width + b
    if y1 >= page.height - 1: y1 = page.height + b
    draw_area = (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    vb = (draw_area[0] - 30, draw_area[1] - 60, draw_area[2] - draw_area[0] + 60, draw_area[3] - draw_area[1] + 90)
    png = _out(pr, page, f"guide-{panel_id}", out)
    w = SvgWriter(page, png.parent, "rough")
    extra = [
             f'<path d="{Path.rect(vb[0], vb[1], vb[2], vb[3]).difference(region).d()}" fill="#ffffff" '
             f'opacity="0.72" fill-rule="evenodd"/>',
             f'<rect x="{_num(draw_area[0])}" y="{_num(draw_area[1])}" width="{_num(draw_area[2]-draw_area[0])}" '
             f'height="{_num(draw_area[3]-draw_area[1])}" fill="none" stroke="#00a000" stroke-width="3" '
             f'stroke-dasharray="14 8"/>',
             w.label("DRAW AREA (incl. bleed / break margin)", draw_area[0], draw_area[1] - 10, 20, "#00a000"),
             f'<path d="{P.path.d()}" fill="none" stroke="#000" stroke-width="5"/>']
    lettering = []
    for L in _balloons(page.layers):
        if L.data["panel"] in (panel_id, None) and L.data["outline"].shape().intersects(region.shape()):
            bx = L.data["body"].bbox()
            lettering.append({"dialogue": L.data["dialogue"], "bbox": [round(v, 1) for v in bx]})
            extra.append(f'<path d="{L.data["outline"].d()}" fill="#9a9a9a" opacity="0.75"/>')
            extra.append(w.label(f"LETTERING {L.data['dialogue']}", bx[0], (bx[1] + bx[3]) / 2, 16, "#000"))
    landmarks = []
    for L in iter_layers(page.layers):
        if L.kind == "image" and L.data["panel"] == panel_id and not L.data["drawing"].missing:
            for nm, lm in L.data["drawing"].landmarks.items():
                x, y = L.data["transform"].apply(lm["xy"])
                if not any(l["name"] == nm for l in landmarks):
                    landmarks.append({"name": nm, "page_xy": [round(x, 1), round(y, 1)], "source_xy": lm["xy"],
                                      "asset": L.data["drawing"].asset_id})
    for nm, (x, y) in page.anchors.items():
        if region.shape().buffer(margin).contains(__import__("shapely.geometry", fromlist=["Point"]).Point(x, y)):
            landmarks.append({"name": nm, "page_xy": [round(x, 1), round(y, 1)], "anchor": True})
    for lm in landmarks:
        x, y = lm["page_xy"]
        extra.append(f'<path d="M{x-16} {y} L{x+16} {y} M{x} {y-16} L{x} {y+16}" stroke="#e00000" stroke-width="3"/>'
                     f'<circle cx="{x}" cy="{y}" r="7" fill="none" stroke="#e00000" stroke-width="2"/>')
        extra.append(w.label(lm["name"], x + 12, y - 12, 16, "#e00000"))
    extra.append(w.label(f"SHOT GUIDE {page.id}/{panel_id}  beat={P.beat}  read={page.direction}",
                         vb[0] + 10, vb[1] + 30, 22, "#000"))
    svg = w.document(vb, extra="".join(extra))
    svg_file = png.with_suffix(".svg")
    svg_file.write_text(svg)
    dpi = pr.render_cfg.get("proof_dpi", 150)
    rasterize(svg_file, png, pr.units_to_px(vb[2], dpi))
    final_dpi = pr.cfg["output_profiles"].get("print", {}).get("dpi", 600)
    guide = {
        "page": page.id, "panel": panel_id, "beat": P.beat, "reading_direction": page.direction,
        "panel_path": P.path.d(), "panel_bbox": [round(v, 1) for v in P.bbox],
        "draw_area_page_units": [round(v, 1) for v in draw_area],
        "min_source_px_for_print": [int(pr.units_to_px(draw_area[2] - draw_area[0], final_dpi)),
                                    int(pr.units_to_px(draw_area[3] - draw_area[1], final_dpi))],
        "breakouts": [{"name": bk.name, "path": bk.path.d(), "over": bk.over} for bk in P.breakouts],
        "reserved_lettering": lettering, "landmarks": landmarks,
        "neighbors": [p.id for p in page.panels.values() if p.id != panel_id],
    }
    # board intent: where the eye should land and which way gazes/motion should lead (rough sketches
    # placed in this panel + page.focal / page.sightline marks)
    from .board import page_facts
    marks = [m for m in page_facts(page)["marks"] if m["panel"] == panel_id]
    guide["focal"] = [{"rank": m.get("rank", 1), "label": m.get("label"), "page_xy": [round(v, 1) for v in m["at"]]}
                      for m in sorted(marks, key=lambda m: m.get("rank", 1)) if m["mark"] == "focal"]
    guide["sightlines"] = [{"label": m.get("label"), "kind": m.get("kind", "sight"),
                            "from": [round(v, 1) for v in m["from"]], "to": [round(v, 1) for v in m["to"]]}
                           for m in marks if m["mark"] == "sightline"]
    guide["board_note"] = P.note
    gj = png.with_suffix(".json")
    gj.write_text(json.dumps(guide, indent=2))
    write_manifest(png, page, "guide", {"panel": panel_id, "dpi": dpi}, [svg_file, gj])
    return png


# ------------------------------------------------------------------ spreads / contact
def pairing(project: Project, chapter=None) -> str:
    """odd-start (first page alone, a recto) or even-start (first two pages face each other).
    chapter.yaml `pairing:` overrides project.yaml spreads.pairing."""
    meta = project.root / "chapters" / (chapter or project.chapter) / "chapter.yaml"
    if meta.exists():
        p = (load_yaml(meta) or {}).get("pairing")
        if p:
            return p
    return project.cfg.get("spreads", {}).get("pairing", "odd-start")


def spread_groups(project: Project, pages: list[str], chapter=None) -> list[list[str]]:
    pairing_ = pairing(project, chapter)
    groups, i = [], 0
    if pairing_ == "odd-start" and pages:
        groups.append([pages[0]])
        i = 1
    while i < len(pages):
        groups.append(pages[i:i + 2])
        i += 2
    return groups


def lone_slot(project: Project, group: list[str], pages: list[str], chapter=None) -> int:
    """Slot (0 = left, 1 = right) for a single-page group. The opening page of an odd-start
    chapter is a recto (left in rtl, right in ltr); a trailing page opens a new spread (right in rtl)."""
    rtl = project.direction == "rtl"
    opening = (pairing(project, chapter) == "odd-start" and pages and group[0] == pages[0])
    if opening:
        return 0 if rtl else 1
    return 1 if rtl else 0


def _reading_png(project, pid, chapter=None, alt=None, view="reading"):
    page, _ = load_page(project, pid, chapter=chapter, alt=alt)
    if view == "rough":   # lettered rough at reading height
        png = render_page(page, "rough", manifest=True)
        im = Image.open(png)
        hp = project.render_cfg.get("reading_height_px", 1100)
        b = page.bleed
        # crop the bleed off so it lines up with reading pages, then scale to reading height
        sx = im.width / (page.width + 2 * b)
        im = im.crop((round(b * sx), round(b * sx), round((b + page.width) * sx), round((b + page.height) * sx)))
        im = im.resize((round(hp * page.width / page.height), hp), Image.LANCZOS)
        o = png.with_name("rough-reading.png")
        im.save(o)
        return o, page
    return render_page(page, "reading", manifest=True), page


def render_spread(project: Project, group: list[str], out=None, chapter=None, alts=None, view="reading") -> FsPath:
    alts = alts or {}
    ims = []
    for pid in group:
        png, _ = _reading_png(project, pid, chapter, alts.get(pid), view)
        ims.append(Image.open(png).convert("RGB"))
    h = ims[0].height
    w = ims[0].width
    first_alone = len(group) == 1
    rtl = project.direction == "rtl"
    canvas = Image.new("RGB", (w * 2 + 6, h + 60), "#8a8a8a")
    # earlier page sits on the right for rtl, left for ltr; a lone first page is the recto
    slots = [None, None]
    if len(group) == 2:
        slots = [ims[1], ims[0]] if rtl else [ims[0], ims[1]]
        labels = [group[1], group[0]] if rtl else [group[0], group[1]]
    else:
        k = lone_slot(project, group, project.chapter_pages(chapter), chapter)
        slots = [ims[0], None] if k == 0 else [None, ims[0]]
        labels = [group[0], ""] if k == 0 else ["", group[0]]
    for k, im in enumerate(slots):
        if im is not None:
            canvas.paste(im, (k * (w + 6), 0))
    d = ImageDraw.Draw(canvas)
    f = _pil_font(project, 28)
    arrow = "<-- reading direction" if rtl else "reading direction -->"
    for k, lab in enumerate(labels):
        if lab:
            if alts.get(lab):
                lab = f"{lab} (alt {alts[lab]})"
            d.text((k * (w + 6) + w // 2, h + 30), lab, fill="white", font=f, anchor="mm")
    d.text((w + 3, h + 30), arrow, fill="#ffe680", font=_pil_font(project, 20), anchor="mm")
    o = FsPath(out) if out else project.build_dir(f"ch{chapter or project.chapter}", "spreads") / f"spread-{'-'.join(group)}.png"
    o.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(o)
    return o


def _pil_font(project, size):
    from PIL import ImageFont
    return ImageFont.truetype(str(project.font_path("caption")), size)


def contact_sheet(project: Project, chapter=None, out=None) -> FsPath:
    pages = project.chapter_pages(chapter)
    groups = spread_groups(project, pages, chapter)
    th = project.render_cfg.get("thumb_height_px", 420)
    thumbs = {}
    for pid in pages:
        png, _ = _reading_png(project, pid, chapter)
        im = Image.open(png).convert("RGB")
        thumbs[pid] = im.resize((int(im.width * th / im.height), th), Image.LANCZOS)
    tw = next(iter(thumbs.values())).width
    cols = 2
    rows = (len(groups) + cols - 1) // cols
    cw, ch = tw * 2 + 10, th + 50
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * 30, rows * ch + (rows + 1) * 20 + 40), "#505050")
    d = ImageDraw.Draw(sheet)
    d.text((30, 14), f"{project.cfg.get('title', '')}  ch{chapter or project.chapter}  ({project.direction})",
           fill="white", font=_pil_font(project, 22))
    rtl = project.direction == "rtl"
    for gi, g in enumerate(groups):
        r, c = divmod(gi, cols)
        if rtl:
            c = cols - 1 - c
        ox, oy = 30 + c * (cw + 30), 50 + r * (ch + 20)
        order = list(reversed(g)) if rtl else g
        if len(g) == 1:
            order = [g[0], None] if lone_slot(project, g, pages, chapter) == 0 else [None, g[0]]
        for k, pid in enumerate(order):
            if pid:
                sheet.paste(thumbs[pid], (ox + k * (tw + 10), oy))
                d.text((ox + k * (tw + 10) + tw // 2, oy + th + 22), pid, fill="white",
                       font=_pil_font(project, 20), anchor="mm")
    o = FsPath(out) if out else project.build_dir(f"ch{chapter or project.chapter}") / "contact.png"
    sheet.save(o)
    return o


# ------------------------------------------------------------------ rebuild
def rebuild(project: Project, manifest_file, out=None) -> tuple[FsPath, bool, list[str]]:
    man = json.loads(FsPath(manifest_file).read_text())
    pins = pins_from_manifest(man)
    src = project.root / man["page_source"]["snapshot"]
    script = load_yaml(project.root / man["script"]["snapshot"])
    cfg = load_yaml(project.root / man["project_yaml"]["snapshot"])
    pr = Project(project.root, cfg=cfg)
    notes = []
    for k, f in man["fonts"].items():
        if sha256_file(pr.root / f["file"]) != f["sha256"]:
            notes.append(f"font {k} bytes differ from pinned")
    st = man.get("style") or {}
    page, _ = load_page(pr, man["page"], pins=pins, page_file=src, script_data=script,
                        style_render=st.get("render", {}), style_revision=st.get("revision"))
    page.source_file = src
    p = man["params"]
    o = FsPath(out) if out else FsPath(manifest_file).with_name(FsPath(manifest_file).stem.replace(".manifest", "") + ".rebuild.png")
    if man["view"] == "guide":
        png = render_guide(page, p["panel"], o)
    else:
        png = render_page(page, man["view"], o, dpi=p.get("dpi"), height_px=p.get("height_px"),
                          profile=p.get("profile"), manifest=False, region=p.get("region"))
    want = man["outputs"][0]["sha256"]
    same = sha256_file(png) == want
    return png, same, notes
