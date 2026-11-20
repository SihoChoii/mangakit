---
name: manga-compose
description: >-
  Turn a boarded manga page into a finished, lettered page from already-selected
  art. Use when a page source exists and the job is placing or aligning
  drawings, building cut-out masks or border breaks, lettering balloons and SFX,
  adding procedural effects, fixing a balloon or mask, or exporting the page.
  Also use for requests like "move the balloon on page 3" or "let the sleeve
  break farther". Do not use it to create or edit drawings; send those to
  illustration.
---
# manga-compose

You edit page source and masks so the page reads well. You never draw or generate art here.
Tools: `mangakit` (the toolkit in the mangakit repo; `install.sh` installs it and puts `mangakit` on PATH); `docs/...` below means the repo's docs folder, which `mangakit docs` prints. API reference:
`docs/page-api.md`. Commands and check codes:
`docs/cli.md`. Border breaks, masks, lettering, and inspection:
`docs/compose-reference.md`.

## Inputs
- A project directory with `project.yaml`, plus the page id (for example `p003`)
- The page source `chapters/<NN>/pages/<page>.py`, and the rough from a fresh `mangakit render <page> --view rough`
- Selected art versions (`mangakit asset list`) and script lines (`story/script.yaml`)
- Any note from the director or reviewer, such as "balloon covers the hands"

## Allowed edits
- `chapters/<NN>/pages/<page>.py`: placements, clips, breakout regions, layer order, effects, balloons, line breaks, and SFX. Keep panel ids, beat ids, and reading order unless the request names them.
- New mask versions and landmarks via `mangakit mask make|select` and `mangakit asset landmark`
- `build/` outputs
- Do not change drawing files, run `asset select`, edit the wording in `story/script.yaml`, or change fonts and page format in `project.yaml`. If one of those needs to change, return a request to its owner (illustration, story, or director).

## Procedure
1. **Open the page.** Read the page source. Run `mangakit render <page> --view rough` and `mangakit asset show <id>` for each drawing it uses. Look at the neighbouring pages at thumbnail size with `mangakit spread <page>` or `mangakit contact`.
2. **Place the art.** Replace each rough slot with its finished drawing: `art.selected(id)` or `art.slot(final=, rough=)`. Align it on landmarks with `panel.align(drawing, source="landmark", target=(x, y), scale=...)` so eyes, hands, or the contact point land where the board put them. Keep every crop and transform explicit in the source. If a landmark is missing, find it with `mangakit asset inspect <id> --grid 50` and add it with `mangakit asset landmark`.
3. **Build cutouts in source coordinates.** For a border break, draw the same ink twice. First the interior copy clipped to the panel, then the borders, then the same drawing with the same placement, `source_mask=art.mask(...)`, clipped to a declared `panel.breakout(..., over=[...])`. Make the mask with `mangakit mask make` and look at its preview over magenta. Then run `mangakit check <page>`, `mangakit render <page> --view masks`, and `--view detail --region ... --dpi 1200` at every crossing. Fix halos, cut linework, and tangents, then look again.
4. **Letter.** Add `page.balloon("<line-id>", at=..., tail_to=<speaker anchor>)` for each script line in reading order. Add `page.text(...)` for SFX. Adjust breaks, size, and tails while looking at the full page with `mangakit render <page>`. Keep balloons off faces, hands, and contact points; mark those landmarks with `--protect`.
5. **Render and inspect.** Run `mangakit render <page>`, `--view reading`, `mangakit spread <page>`, and `mangakit check <page>`. Read the PNGs yourself and check reading order, overlaps, clipping, focal points, and whether the facing page gives away the page-turn reveal. Render to a new filename with `-o` before re-viewing, since image viewers can cache. If a defect comes from the drawing itself, write a localized illustration request. It should name the asset and version, attach an annotated `--view detail` or `--view guide` crop, and state exactly what must change. Do not patch the drawing in composition.
6. **Return.** Report the edited page source, the selected mask versions, the proof PNG and its manifest, the check output, and any unresolved issue with its owner. Run `mangakit hash art/assets` before and after to show the drawings are unchanged.

## Worked example
Request: "On p003, the 'Got it.' balloon covers the hands, and the cuff should break the border too." Example project: `example/` in the mangakit repo is a text-only cut of the demo this worked example comes from.
```
mangakit check p003     # WARN balloon-covers-landmark line-18 ... finger-contact
mangakit hash art/assets > /tmp/art-before.txt
# page source: page.balloon("line-18", at=(335, 1030), ...)  ->  at=(215, 845)
mangakit mask make hands-at-door border-break --polygon tip.yaml --polygon cuff.yaml --feather 0.7   # -> m002
# page source: cuff_zone = handoff.breakout(Path.polygon([...]), name="cuff-break", over=["train-departs"])
#              page.image(hands, transform=place, source_mask=art.mask(hands, "border-break"),
#                         clip=[tip_zone, cuff_zone], name="handoff-break")
mangakit check p003     # ERROR breakout-cut -> widen cuff_zone; WARN mask-halo -> tighten polygon (m003)
mangakit render p003 --view detail --region 600,980,860,1110 --dpi 1200 -o build/inspect/cuff-r2.png
mangakit render p003 && mangakit spread p003 && mangakit check p003     # checks: OK (0 issues)
mangakit hash art/assets | diff /tmp/art-before.txt -                    # only new mask files differ
```

## Done when
- `mangakit check <page>` reports no errors, and every remaining warning is explained in the report.
- The proof, reading, and spread PNGs were rendered from the current source, and you looked at them, including a detail crop of every border break.
- The proof manifest pins the drawing, mask, font, and page-source versions, and `mangakit rebuild <manifest>` prints `identical to recorded output: YES`.
- `mangakit hash art/assets` shows no drawing file changed. Only new mask files and the `asset.yaml` record may differ.
