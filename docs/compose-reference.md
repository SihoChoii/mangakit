# Composition reference (for manga-compose)

## Layer order that works
1. Panel fills / backgrounds, then each panel's interior art (`clip=panel.path`).
2. Neighbor-panel content the break may cover (art, effects, SFX that sit *under* the break).
3. Panel borders (`page.stroke(p.path, style="panel-border")`).
4. Break layers: same drawing, same `Placement`, `source_mask=art.mask(...)`, `clip=breakout(s)`.
5. Effects that sit above art (motion lines over a hand), then balloons, captions, SFX on top.

## Making a border-break mask
1. `mangakit asset inspect <asset> --grid 50` and read the drawing at full size.
2. Outline only the parts that leave the panel. The polygon edge must follow the *outer edge of the
   ink outline* wherever it will be visible (outside the panel). Inside the panel it can cut anywhere:
   the interior copy is identical there, so that edge is invisible. Keep the inside cut line well
   inside the panel (>= 25 page units from the border).
3. `mangakit mask make <asset> <name> --polygon tip.yaml [--polygon cuff.yaml] --feather 0.7`.
   For organic silhouettes on a white ground add `--trim-light-edges` (with `--bg-seed x,y` if the
   polygon crosses light interiors).
4. Look at the preview (cut-out over magenta). Fix holes, specks, cut linework, background left inside.
5. Declare the allowed region: `panel.breakout(Path.polygon([...]), name=..., over=[...])` from
   inside the panel, across border stroke and gutter, as far as the break may go.
6. `mangakit check <page>`: `breakout-cut` -> widen the region; `mask-halo` -> tighten the polygon;
   `mask-slices-ink` -> move the polygon edge outside the outline; `breakout-intrudes` -> declare `over=`.
7. `mangakit render <page> --view masks` and `--view detail --region ... --dpi 1200` at each crossing.
   The outline must run continuously over both border strokes; borders must stop exactly at the ink.

A tangency (silhouette edge running along a border) reads as a mistake. Move the zone/placement so
the art clearly crosses or clearly stays inside.

## Lettering
* Balloons pull text from the script by line id; never paste wording into the page source.
* Place balloons in reading order (rtl: right-to-left, top-to-bottom within the panel order). The
  `reading-order` check compares against the script order.
* Keep tails short, pointing at the speaker anchor (`page.anchor`, or `placement.map("mouth")`).
* Don't cover faces, hands, contact points: mark such landmarks `--protect`.
* If the text overflows: change `breaks=`, enlarge `size`, or ask the story owner to shorten the line.

## Inspection checklist (look at the PNGs, not only the checks)
* reading view: does the eye go panel 1 -> n and balloon 1 -> n? any tangents, accidental arrows?
* spread view: does the facing page reveal what the page turn should?
* detail views: each border crossing, each hand/face near a balloon, text kerning at print size.
* masks view: halos, holes, specks, alignment against the real gutter.

If a defect is in the drawing (grip unreadable, too little drawn past the border), do not fake it in
composition: write a localized illustration request with an annotated crop
(`--view detail` / `--view guide`) and the job id, and leave the page on the current selection.

## Viewer caching
Some image viewers cache by path. When re-inspecting after an edit, render with `-o` to a new name
(e.g. `build/inspect/p003-proof-r2.png`) or copy the PNG before viewing.

## Thin-lined art (generated or scanned)
A hand-traced polygon leaves a paper margin around thin outlines, and `mask-halo` flags it. Trace
each outline's outer edge (measure the ink rows with `asset inspect --crop ... --grid 10`). Then add
`--snap 4..6` so the edge is peeled back to the ink. Where background art touches an outline (a door
edge right under an envelope), cut on the outline. Explain any remaining `mask-slices-ink` warning
after checking a 1200 dpi detail crop. Art that runs past a frame edge no breakout crosses (an arm
leaving the panel at the side) can extend past that edge in the mask. The frame line cuts it, and
`breakout-cut` does not count it.
