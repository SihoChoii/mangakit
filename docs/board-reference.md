# Board reference

Board turns a script into a rough lettered chapter. It owns which page and panel each beat and line
lands on, panel geometry, reading order, the eye path (focal points, sightlines), and lettering
placement. Story owns beats, lines and reveals. Illustrate owns final art. Compose owns finishing.
The rough and the finished page are the same page source: the same panel ids, geometry and
dialogue anchors. A rough is only a placeholder drawing in an art slot.

## Files
| Path | What |
|---|---|
| `chapters/<ch>/pages/<pid>.py` | the page source (one per page), `build(page, art, script)` |
| `chapters/<ch>/pages/<pid>.alt-<name>.py` | an alternate layout for that page; same API |
| `chapters/<ch>/pages/<pid>.alt-pre-<name>.py` | the source replaced when alternate `<name>` was promoted (archive) |
| `chapters/<ch>/board.yaml` | the plan: pages, panel ids, beats, lines, reveals, retired ids (`board plan --write`) |
| `chapters/<ch>/alternates.yaml` | promotion log: alternate, reason, time, moved/dropped ids, or `kept: true` |
| `art/roughs/<asset>.py` | a procedural rough sketch; `rough make` registers it as an asset of `kind: rough` |
| `project.yaml` `board:` | `margins_mm` (top, bottom, inside, outside) and `gutter_mm` (row, col) |
| `build/<ch>/board/<set>/` | `pNNN-rough.png`, `spread-*.png`, `rough-spread-*.png`, `turns.png`, `board-check.txt` |
| `build/<ch>/board/compare-<a>-vs-<b>.png/.md` | side-by-side spreads of alternate sets with a fact table |

`<set>` is `current` or an alternate name. An alternate set is every `*.alt-<name>.py` in the
chapter, with the current source for pages that have none.

## Layout helpers (`L = page.layout()`)
All shapes are `Path`s in page units. Every helper keeps the live area (trim minus margins) and
the gutters from `board:`; bleed helpers extend to the bleed edge. `inside`/`outside` follow the
page side (`page.side`, from spread pairing and reading direction), so the same source works on
either page.
| Helper | Returns |
|---|---|
| `L.live` | the live-area rectangle |
| `L.rows(weights, region=None, gutter=None)` | horizontal tiers, top to bottom |
| `L.cols(weights, region=None, gutter=None)` | columns in reading order (right first for rtl) |
| `L.grid(rows, region=None, row_weights=None)` | list of tiers, each a list of cells in reading order; `rows` gives each tier's column weights |
| `L.cut(region, left_y, right_y, gutter=None)` | `(upper, lower)` split by a diagonal line; the gutter is perpendicular to the cut |
| `L.vcut(region, top_x, bottom_x)` | `(first, second)` in reading order, slanted vertical split |
| `L.inset(host, rect, gap=None)` | `(host_minus_inset, inset)` |
| `L.bleed(path, sides)` | path pushed to the bleed on `top bottom left right inside outside all`; avoid `inside` (binding) |
| `panel.fit(drawing, mode="cover"|"contain", anchor=(ax, ay), region=None, scale=1)` | transform placing a drawing in a panel |
| `panel.breakout_toward(other, span=(a, b), inside=, reach=, name=)` | declares a breakout region crossing the gutter to `other`; `span` runs in reading direction |

`page.panel(id, path, beat=, border=True|False|Path, note=, order=)`: `border=False` is a borderless
panel; `note` is a camera or intent note shown on the rough. `page.borders(style=None)` strokes all
bordered panels. `order=` overrides geometric order; avoid it, since `panel-order` checks the
declared order against the geometry.

## Board marks
`page.focal(at, panel=, label=, rank=)`, `page.sightline(frm, to, panel=, label=)`,
`page.note(text, at=, panel=)`. These sit on the `board` layer: drawn in the `rough` view and the
shot guide, never in proof, reading or export. Roughs carry their own focal points and sightlines;
they are mapped through the image transform onto the page, so you rarely need page-level marks
except over final art.

## Rough sketches
A sketch source defines `SIZE = (w, h)` and `def sketch(s):`. `s` is a `Sketch`:
`block rect tone lines horizon perspective speed prop hand head figure focal sightline arrow note
camera landmark document meta`. `s.figure(name, feet=, height=, facing=, pose=stand|walk|run|reach|sit,
reach=, look=, hidden=, hair=)` registers landmarks `<name>-head`, `-eye`, `-mouth`, `-hand`, `-feet`;
`s.prop` and `s.landmark` add more. Use the canon or design ids as landmark names that the final art
will also carry, because balloon tails and the shot guide are anchored to them.

`mangakit rough make [id]` renders without any image call, records `vNNN.sketch.py` next to the
PNG, stores landmarks, and stores the marks under `versions.vNNN.rough`. It is idempotent: the same
source gives the same bytes and no new version. Fill an art slot with
`art.slot(final="<final asset>", rough="<rough asset>")`: the final art is used when it has a selected
version, otherwise the rough. A request made from a roughed slot carries the rough, its focal points
(ranked), its sightlines and the panel note (`board:` and `eye path:` lines in the prompt), and is no
longer flagged `rough_is_placeholder`.

## Plan (`board plan`)
Builds `board.yaml` from the story and the existing page sources.
* Drawn pages keep their panel ids, in place. Ids are names; nothing is renumbered.
* A beat with no panel gets a new panel named after the beat, on the page after the last placed
  beat (up to `--per-page`). New pages are appended.
* A beat whose `reader.knows` reveals a concealed fact goes on the first page after a page turn.
  If the next page would face the previous one, the plan leaves an empty page so the reveal lands
  after the turn. Report it; the board can fill that page with build-up panels instead.
* Ids that disappear go to `retired:` with the date. A retired id is never handed out again
  (`<id>-2`).
* `--write` saves `board.yaml` and adds new pages to `chapter.yaml`; `--stubs` writes a stub source
  for each new page (one tier per panel, a `rough-<panel>` slot per panel, every line lettered in script order).

## Check (`board check`)
Reads every page of the set, the story and the plan. It prints per page, in reading order: panel,
beat, share of page, lines, focal points in rank order, sightline count, art (final or rough), and
then the spreads and page turns with the reveal on each. Technical compose checks in `BOARD_TECH`
are included by default (`--all` for every one).
| Code | Sev | Meaning |
|---|---|---|
| `page-broken` | error | the page source failed to build |
| `panel-id-duplicate` | error | the same panel id twice in the chapter |
| `beat-not-boarded` | error | a chapter beat has no panel |
| `line-not-lettered` | error | a script line of a boarded beat has no balloon |
| `reveal-on-facing-page` | error | a reveal sits on a page the reader sees together with the previous page |
| `reveal-without-turn` | warn | a reveal on the chapter's opening page with no turn before it |
| `reveal-not-first-after-turn` | warn | the reveal is not in the first panel(s) read after the turn |
| `beat-order` | warn | beats out of story order in reading order (from the story page checks) |
| `panel-order` | warn | the declared order differs from the geometric zigzag |
| `balloon-order` | warn | balloons read (by panel, then rtl/ltr zigzag inside the panel) out of script order |
| `balloon-beat` | warn | a line is lettered in a panel of another beat |
| `balloon-outside-panel` | warn | the balloon's centre is outside its panel |
| `lettering-outside-panels` | warn | a balloon is not in any panel |
| `panel-too-small` | warn | balloons cover more than half of the panel |
| `focal-covered` | warn | a balloon covers a focal point |
| `retired-id-reused` / `plan-panel-missing` / `plan-panel-moved` / `plan-unplanned-panel` | warn | drift from `board.yaml`; re-plan or restore |
| `panel-crowded` | info | balloons cover more than 30% of the panel |
| `no-focal` | info | a panel has no focal point (the sketch's was cropped out, or none was set) |
| `sightline-against-flow` | info | a gaze leads backwards out of the page tier; fine if it is intentional |
| `bleed-inside` | info | a panel bleeds into the binding |
| `needs-art` | info | the panel shows only a rough (the work list for illustrate) |

Reading order is geometric: tiers by vertical overlap (diagonal cuts are sampled along vertical
lines), right-first within a tier for rtl, top-first for panels stacked inside a column.

## Render (`board render`)
`board render [--alt name]` writes for the set: each page in the rough view (`pNNN-rough.png`, lettered,
marks and notes drawn), the reading-size spreads (`spread-*.png`), rough spreads, `turns.png` (each
spread in order with the page turns marked and the reveal highlighted) and `board-check.txt`.
`mangakit render <pid> --view rough --alt <name>` renders one alternate page.

## Alternates
* `board alt <pid> <name> [--from other]` copies the page source to `<pid>.alt-<name>.py`.
* `board alts` lists the sets. `board check|render --alt <name>` work on a set.
* `board compare current,b,c` renders the sets side by side, at reading size, and writes a table:
  errors, warnings, panels and shares, focal points, art needed.
* `board promote <name> --reason "<why>" [--dry-run] [--force]` makes the alternate current.
  It requires a reason. Every current id must still exist somewhere in the chapter: an id that
  disappears and is referenced by a job or an accepted asset blocks the promotion (exit 2) unless
  `--force`. Panels that move pages are listed with their jobs (to re-request). Replaced sources are
  archived as `<pid>.alt-pre-<name>.py`, the log is appended, dropped ids are retired, and the plan
  is rewritten. `board promote current --reason ...` records a kept decision.

## Difficult panels
For a reveal or a transfer across panels: draw the diagonal or tall frame, rough the hands or prop
in their final positions, reserve the balloon area (letter before art), declare a narrow breakout
region with `breakout_toward` where the art may cross the gutter, render the spread and `turns.png`,
and check that the prop is readable at reading size and that the reveal is the first thing read after
the turn. Try at least two alternates for the hardest spread and log the pick with its reason.
