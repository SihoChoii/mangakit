# mangakit page API

A page source is a Python file `chapters/<NN>/pages/pNNN.py` that defines

```python
from mangakit import Path, Affine, line_y

def build(page, art, script):
    ...            # describe the page
    return page
```

`mangakit render pNNN` imports it, calls `build`, and renders. Page sources must be
deterministic: no clocks, no network, no image generation, no unseeded randomness.

## Coordinates

* **Page units**: `project.yaml page.units_per_mm` (default 6 u/mm). Origin = top-left of the
  **trim** box, y down. `page.width`, `page.height` = trim size; `page.bleed` = bleed width (art that
  should reach the paper edge must extend to `-page.bleed` / `width + bleed`).
  B5 (182x257 mm) = 1092 x 1542 u, bleed 3 mm = 18 u.
* **Source coordinates**: pixels of the original drawing. Landmarks and masks always live here.
* An image's `transform` maps source px -> page units. The renderer applies the *same* transform
  to the image and to its `source_mask`; clips are in page units.
* Useful frames: `page.trim`, `page.bleed_box`, `page.safe` (trim inset by `safe_mm`).

## Geometry (`mangakit.geometry`)

| Call | Meaning |
|---|---|
| `Path.rect(x, y, w, h)`, `Path.polygon(pts)`, `Path.polyline(pts)`, `Path.ellipse(cx, cy, rx, ry)` | constructors |
| `Path.from_svg("M.. L.. C.. Q.. H.. V.. Z")` | SVG path data (absolute or relative; no arcs `A` or `S/T` shorthands) |
| `p.union(q, ...)`, `p.intersection(q)`, `p.difference(q)`, `p.offset(d)` / `p.inset(d)` | booleans / grow / shrink (shapely, even-odd) |
| `p.bbox()`, `p.contains(pt)`, `p.centroid()`, `p.transformed(affine)`, `p.d()` | queries |
| `Affine.translate/scale/rotate(deg, about)`, `a @ b` (b first), `a.apply(pt)`, `a.inverse()` | transforms |
| `similarity(src_pt, dst_pt, scale, rotate)`, `similarity2(s1, s2, t1, t2)` | landmark alignment |
| `line_y(p1, p2, x)` | y on a line, handy for diagonal frames |

All paths use the even-odd fill rule.

## Structure

`page.panel(id, path, beat=None, order=None) -> Panel`
: Stable panel id (keep it across rough and final), arbitrary path, beat id from
  `story/script.yaml`, reading order (default: call order).

`panel.align(drawing, source, target, scale=1.0, rotate=0.0) -> Placement`
: `source` = landmark name (or source `(x, y)`), `target` = page point. Two-point form:
  `source=["a", "b"], target=[(x1, y1), (x2, y2)]` solves scale + rotation. Landmarks resolve against
  the drawing's *selected version only*; a missing landmark raises.
  `placement.map("landmark")` -> page point, `placement.bounds()` -> page path.

`panel.breakout(region, name=None, over=()) -> Path`
: Declares an allowed border-break region (page units) and returns it for use as a clip. Draw it
  so it starts inside the panel, covers the border stroke and gutter, and reaches as far as the
  break may go. List panels the break may cover in `over=[...]`.

`page.anchor(name, pt)`
: Named page point (speaker mouths, off-panel speakers). Balloon tails accept anchor names.

`with page.group(name=None, clip=None, transform=None, opacity=None):`
: Nested layers share a clip/transform/opacity.

Layers stack in call order (first call = bottom).

## Art (`art` object)

| Call | Returns |
|---|---|
| `art.selected("asset-id")` | `Drawing` for the selected version (or a pinned one during `rebuild`). Missing → placeholder + `missing-asset` error. |
| `art.slot(final="id", rough="id")` | final if it has a selection, else the rough (board stage). |
| `art.mask(drawing, "mask-name")` | selected `Mask` version; raises a `stale-mask` error if registered to another drawing version, `mask-dims` if sizes differ. |

`Drawing`: `asset_id, version, file, width, height, sha256, landmarks, landmark(name)`.

## Drawing primitives

`page.image(drawing, transform=Placement|Affine, clip=Path|[Path,...], source_mask=Mask, opacity=1, name=None, panel=None)`
: Raster art. `clip` = a panel path, a declared breakout, or a list of declared breakouts (unioned).
  Anything else is reported as `undeclared-clip`.

`page.overlay(file, transform=None, size=None, clip=None, opacity=1)`
: Unregistered raster (paper grain, texture). Hash recorded in the manifest. Do not use for drawings.

`page.fill(path, color="#ffffff", opacity=1)` / `page.stroke(path, style="panel-border", **overrides)`
: Vector fill / stroke. Styles come from `project.yaml styles` (`stroke`, `width`, `join`, `cap`).

`page.raw(svg_fragment)`
: Raw SVG in page units for custom vector work.

`page.effect(kind, region, seed, name=None, clip=True, **params)`
: Procedural effect, deterministic from `seed` (seed is recorded in the manifest).
  * `speed_lines`: `angle` (deg), `count`, `width=(min,max)`, `length=(min,max)` fraction, `taper="both"|"one"`
  * `focus_lines`: `center`, `count`, `inner` (clear radius fraction), `jitter`, `width`
  * `tone`: screentone dots, `spacing`, `dot` (radius as fraction of spacing), `angle`

## Lettering

`page.balloon(dialogue, shape="ellipse", at=(x, y), size=None, tail_to=None, breaks=None, font="dialogue", font_size=None, aspect=None, tail_gap=None, tail_width=None, tail_len=None, panel=None, padding=None, style="balloon")`
: * Wording comes from `story/script.yaml` line `dialogue` (the script owns it). `*word*` = emphasis font.
  * `breaks=["LINE ONE", "LINE TWO"]` lets the page own line breaks; they must spell the script text
    (else `breaks-mismatch`).
  * Without `breaks`, words are wrapped to a balloon-friendly block (`aspect` w/h; default 1.5,
    3.2 for boxes). `size=(w, h)` fixes the balloon; overflow is reported, never silently shrunk.
  * `shape`: `ellipse`, `rect` (rounded), `box` (caption, no tail), `cloud`, `burst`, or a `Path`/SVG `d`.
  * `tail_to`: page point or anchor name. The tail stops `tail_gap` short of the target and at most
    `tail_len` beyond the balloon edge.
  * `panel`: owning panel id (used for reading-order checks and shot guides).

`page.text(text, at, font=None, size=None, fill=None, outline=<default>, outline_width=None, rotate=0, anchor="middle", tracking=0, skew=0, panel=None, line=None)`: unset font/size/fill/outline/outline_width come from `project.cfg["sfx"]` (the effective art-direction revision's `sfx` render settings), falling back to sfx / 60 / #000 / #fff / 6. Explicit arguments win.
: Single typeset line (SFX, signs). Baseline at `at[1]`. `line="line-04"` ties it to a script line
  (`kind: sfx`): pass `text=None` to take the wording from the script; the line then counts as
  lettered and `story impact` tracks it.

Font roles: `dialogue`, `dialogue-emphasis`, `caption`, `sfx` (pinned in `project.yaml fonts` with sha256).
Text is converted to vector outlines with HarfBuzz shaping + fontTools, so the rasterizer never
substitutes fonts.

## Same ink twice (border break)

```python
hands = art.selected("hands-at-door")
place = handoff.align(hands, source="finger-contact", target=(338, 1046), scale=0.62)
page.image(hands, transform=place, clip=handoff.path)            # 1. interior copy
# ... other panels' art and effects ...
for p in page.panels.values():
    page.stroke(p.path, style="panel-border")                     # 2. borders
zone = handoff.breakout(Path.polygon([...]), name="tip-break", over=["next-panel"])
page.image(hands, transform=place, clip=zone,                     # 3. same source, same transform,
           source_mask=art.mask(hands, "border-break"))           #    masked, clipped to the zone
```

The break must be drawn after anything it should cover (neighbor panel art, borders) and before
lettering. Inside the panel the second copy is pixel-identical to the first, so the mask edge there
is invisible; only the silhouette outside the panel shows. See compose-reference.md.

## Board additions (milestone 5)
* `L = page.layout()`: `L.live`, `rows`, `cols` (reading order), `grid`, `cut` (diagonal), `vcut`,
  `inset`, `bleed(path, sides)` with `inside`/`outside` resolved from `page.side`. Gutters and margins
  from `project.yaml` `board:`.
* `page.panel(id, path, beat=, order=, border=True|False|Path, note=None)`; `page.borders(style)`
  strokes every bordered panel (a Path border strokes that path instead).
* `panel.fit(drawing, mode="cover"|"contain", anchor=(0.5, 0.5), region=None, scale=1.0)` -> placement.
* `panel.breakout_toward(other, span=(a, b), inside=40, reach=120, name=None)` declares a breakout
  region over the shared gutter (`span` runs in reading direction).
* `page.focal(at, panel=, label=, rank=1)`, `page.sightline(frm, to, panel=, label=)`,
  `page.note(text, at=, panel=)`: `board` layer marks, drawn in `rough` view and the shot guide only.
* `art.slot(final=, rough=)` returns the final art when selected, else the rough (kind `rough`,
  carrying its own focal points and sightlines).
* `page.side` (`left`/`right`) and `page.alt` (alternate name or None) are set by the loader.
See board-reference.md.
