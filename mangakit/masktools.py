"""Build and inspect masks in *source-image* coordinates, and inspect drawings."""
from __future__ import annotations

import json
from pathlib import Path as FsPath

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .assets import Registry
from .project import MangakitError, Project

SS = 4  # polygon supersampling


def parse_points(spec: str):
    p = FsPath(spec)
    if p.exists():
        data = yaml.safe_load(p.read_text())
        if isinstance(data, dict):
            data = data.get("points") or data.get("polygon")
        return [tuple(map(float, q)) for q in data]
    pts = []
    for tok in spec.replace(";", " ").split():
        x, y = tok.split(",")
        pts.append((float(x), float(y)))
    if len(pts) < 3:
        raise MangakitError("polygon needs >= 3 points: 'x,y x,y x,y ...' or a yaml/json file")
    return pts


def poly_mask(size, polys, subtract=()):
    w, h = size
    im = Image.new("L", (w * SS, h * SS), 0)
    d = ImageDraw.Draw(im)
    for pts in polys:
        d.polygon([(x * SS, y * SS) for x, y in pts], fill=255)
    for pts in subtract:
        d.polygon([(x * SS, y * SS) for x, y in pts], fill=0)
    return im.resize((w, h), Image.LANCZOS)


def trim_light_edges(src_gray: Image.Image, mask: Image.Image, threshold=200, seeds=None) -> Image.Image:
    """Remove light (paper/background) pixels inside the mask, flood-filled from `seeds`
    (source px known to be background) or, without seeds, from every light pixel on the mask
    boundary. The cut-out then follows the drawing's own ink outline instead of the polygon.
    Use seeds when the polygon edge also crosses light *interior* areas (paper of an envelope,
    a white shirt) that must stay opaque."""
    g = np.asarray(src_gray)
    m = np.asarray(mask) > 127
    cand = (m & (g >= threshold)).astype(np.uint8) * 255
    work = Image.fromarray(cand)
    if seeds:
        pts = [(int(x), int(y)) for x, y in seeds]
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    else:
        border = m & ~(np.asarray(mask.filter(ImageFilter.MinFilter(3))) > 127)
        ys, xs = np.nonzero(border & (cand > 0))
        xs, ys = xs.tolist(), ys.tolist()
    for x, y in zip(xs, ys):
        if work.getpixel((x, y)) == 255:
            ImageDraw.floodfill(work, (x, y), 128, thresh=0)
    removed = np.asarray(work) == 128
    out = np.where(removed, 0, np.asarray(mask)).astype(np.uint8)
    return Image.fromarray(out)


def snap_to_ink(src_gray: Image.Image, mask: Image.Image, steps=4, threshold=200) -> Image.Image:
    """Peel light (paper) pixels off the mask edge one layer at a time, up to `steps` px, stopping
    wherever the edge reaches ink. Removes the thin paper margin a hand-traced polygon leaves
    around thin linework. Light *interior* areas cut by the polygon edge also lose up to `steps` px,
    so use it where those edges lie inside the panel (invisible) or keep `steps` small."""
    g = np.asarray(src_gray) >= threshold
    m = np.asarray(mask) > 127
    for _ in range(int(steps)):
        er = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))) > 127
        peel = m & ~er & g
        if not peel.any():
            break
        m = m & ~peel
    return Image.fromarray((m * 255).astype(np.uint8))


def make_mask(project: Project, aid, name, polygons=(), subtract=(), from_png=None, trim_light=None,
              grow=0, feather=0.0, source_ver=None, note="", bg_seeds=None, snap=0):
    reg = Registry(project)
    ver, v = reg.version(aid, source_ver)
    src = Image.open(reg.dir / aid / v["file"])
    size = src.size
    recipe = {"source_version": ver, "polygons": [list(map(list, p)) for p in polygons],
              "subtract": [list(map(list, p)) for p in subtract], "from_png": str(from_png) if from_png else None,
              "trim_light_edges": trim_light, "bg_seeds": bg_seeds, "snap": snap, "grow": grow, "feather": feather}
    if from_png:
        im = Image.open(from_png)
        if im.size != size:
            raise MangakitError(f"{from_png} is {im.size}, source {aid}/{ver} is {size}")
        mask = im.getchannel("A") if "A" in im.getbands() else im.convert("L")
        if polygons:
            mask = Image.fromarray(np.minimum(np.asarray(mask), np.asarray(poly_mask(size, polygons, subtract))))
    else:
        if not polygons:
            raise MangakitError("give --polygon (repeatable) or --from-png")
        mask = poly_mask(size, polygons, subtract)
    if trim_light is not None:
        mask = trim_light_edges(src.convert("L"), mask, trim_light, bg_seeds)
    if snap:
        mask = snap_to_ink(src.convert("L"), mask, snap, trim_light or 200)
    if grow:
        flt = ImageFilter.MaxFilter if grow > 0 else ImageFilter.MinFilter
        mask = mask.filter(flt(2 * abs(int(grow)) + 1))
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    mver = reg.add_mask(aid, name, mask, ver, note=note, recipe=recipe)
    return mver


def _font(project, size):
    try:
        return ImageFont.truetype(str(project.font_path("caption")), size)
    except Exception:
        return ImageFont.load_default()


def mask_preview(project: Project, aid, name, mver=None, out=None, bg=(255, 0, 255)):
    """Three panels in source coords: drawing+mask outline, cut-out over contrasting bg, mask alone."""
    reg = Registry(project)
    rec = reg.load(aid)
    mrec = rec["masks"][name]
    mver = mver or mrec["selected"]
    mv = mrec["versions"][mver]
    src = Image.open(reg.dir / aid / rec["versions"][mv["source_version"]]["file"]).convert("RGB")
    mask = Image.open(reg.dir / aid / mv["file"]).convert("L")
    w, h = src.size
    a = src.copy()
    edge = mask.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    edge = edge.filter(ImageFilter.MaxFilter(3))
    a.paste((0, 200, 255), mask=edge)
    tint = Image.new("RGB", src.size, (0, 160, 255))
    a = Image.composite(Image.blend(a, tint, 0.18), a, mask)
    b = Image.new("RGB", src.size, bg)
    b.paste(src, mask=mask)
    c = mask.convert("RGB")
    sheet = Image.new("RGB", (w * 3 + 40, h + 60), (40, 40, 40))
    for i, im in enumerate((a, b, c)):
        sheet.paste(im, (10 + i * (w + 10), 50))
    d = ImageDraw.Draw(sheet)
    f = _font(project, 28)
    for i, t in enumerate(("source + mask edge", "cut-out over contrast", f"mask {name}/{mver}")):
        d.text((10 + i * (w + 10), 12), t, fill="white", font=f)
    o = FsPath(out) if out else project.build_dir("masks") / f"{aid}--{name}--{mver}.png"
    o.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(o)
    return o


def inspect_asset(project: Project, aid, ver=None, grid=100, out=None, crop=None):
    """Drawing with a labelled source-pixel grid and its landmarks, for picking coordinates."""
    reg = Registry(project)
    ver, v = reg.version(aid, ver)
    im = Image.open(reg.dir / aid / v["file"]).convert("RGB")
    rec = reg.load(aid)
    d = ImageDraw.Draw(im)
    f = _font(project, max(14, grid // 5))
    W, H = im.size
    for x in range(0, W, grid):
        d.line([(x, 0), (x, H)], fill=(0, 170, 255), width=1)
        d.text((x + 3, 3), str(x), fill=(0, 120, 220), font=f)
    for y in range(0, H, grid):
        d.line([(0, y), (W, y)], fill=(0, 170, 255), width=1)
        d.text((3, y + 3), str(y), fill=(0, 120, 220), font=f)
    for nm, lm in rec.get("landmarks", {}).get(ver, {}).items():
        x, y = lm["xy"]
        d.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(230, 0, 0), width=3)
        d.text((x + 12, y - 12), nm, fill=(230, 0, 0), font=f)
    if crop:
        im = im.crop(crop)
    o = FsPath(out) if out else project.build_dir("inspect") / f"{aid}-{ver}-grid.png"
    o.parent.mkdir(parents=True, exist_ok=True)
    im.save(o)
    return o
