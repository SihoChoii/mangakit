---
name: manga-board
description: Board a manga chapter. Turn the script into a rough lettered chapter with stable page and panel ids, placing panels, focal points, sightlines, dialogue, reveals and transitions in reading order. Draw procedural rough sketches where there is no final art, render the pages, spreads and page turns at reading size, and try alternate layouts for difficult pages or spreads, then promote one without breaking ids. Use when a chapter or page needs a layout, when story adds, moves or cuts beats or lines, when a reveal must land after a page turn, when illustrate needs a rough to draw from, or when `board check` reports problems. Do not use it to write or change beats and lines (story), to design looks (design), to draw final art (illustrate) or to finish masks, breaks and lettering polish (compose).
---

# manga-board

You own where everything goes on the page and the order the reader meets it. You assign beats and
lines to pages and panels, draw the panel geometry, place balloons, and set the eye path: the focal
point of each panel and the sightlines that lead to the next. You draw roughs in code, never with an
image call. The rough and the finished page are the same page source, with the same panel ids,
geometry and balloon anchors, so final art drops into a slot without re-lettering. Panel ids are
names. You never renumber them and never reuse a retired one.
Tools: `mangakit` (the toolkit in the mangakit repo; `install.sh` installs it and puts `mangakit` on PATH); `docs/...` below means the repo's docs folder, which `mangakit docs` prints. Layout helpers, sketch API, plan,
check codes and alternates: `docs/board-reference.md`. Page API:
`docs/page-api.md`. Commands: `docs/cli.md`.

## Inputs
- A project directory (`project.yaml` with page format, reading direction and `board:` margins and
  gutters; `story/`; `chapters/<ch>/chapter.yaml` with page list and spread pairing)
- From story: `beats.yaml` (order, who is present, `reader.conceals`/`reader.knows` reveals),
  `script.yaml` (lines in order, kind, speaker)
- From design: reference views for characters, props and places, used to draw the roughs
- Existing page sources and selected art. Accepted art is kept; you lay out around it.

## Allowed edits
- `chapters/<ch>/pages/<pid>.py` and `<pid>.alt-<name>.py`: panels, layout, art slots and placement,
  balloons, board marks (`focal`, `sightline`, `note`). Promote alternates only through
  `board promote`.
- `chapters/<ch>/board.yaml` (through `board plan --write`), `chapters/<ch>/alternates.yaml` (through
  `board promote`), the `pages:` list in `chapter.yaml`, and `board:` in `project.yaml`.
- `art/roughs/*.py` and rough assets through `rough make`. Never register a rough over final art.
- Do not edit story records. A line that will not fit, a beat that needs splitting, or a reveal that
  cannot land after a turn goes back to story with the exact ids.
- Do not edit final art, masks, landmarks of final art, or jobs. Panels that need art go to
  illustrate as the `needs-art` list. Moved panels with jobs go to the director.

## Procedure
1. **Plan.** Run `mangakit board plan --chapter <C>`. Read the page and spread map:
   - Every beat has a panel, and every line belongs to a boarded beat.
   - Every reveal (`reader.knows` of a concealed fact) is on the first page after a turn, never on a
     page that faces the one before it. If the plan leaves a page empty to reach a turn, fill it with
     build-up panels or ask story to move a beat.
   - Existing ids stay in place. Save with `--write`, and use `--stubs` to get first sources for new pages.
2. **Lay out each page** with `L = page.layout()`: rows, columns, diagonal `cut`, `inset`, and
   `bleed` (never into the binding). Keep one dominant panel per page. The zigzag must read in the
   project's direction without help: avoid `order=`.
3. **Letter before art.** Place every line of each panel's beat in script order, starting at the
   panel's reading-start corner, with tails pointed at landmark names (`<character>-mouth`).
   Reserve the balloon area so it does not cover a focal point.
4. **Rough sketches** for every panel with no final art: write `art/roughs/<asset>.py` with figures,
   props, a horizon, `focal`, `sightline` and a `camera` note, then `rough make`. Name landmarks
   after canon or design ids, the names the final art will carry. Use
   `art.slot(final=..., rough=...)` so final art replaces the rough automatically. Keep accepted art
   exactly where it is.
5. **Difficult panels** (a transfer, a reveal, a breakout): draw the diagonal or tall frame, rough
   the hands or prop in their final positions, reserve the balloon area, declare a narrow breakout
   region with `breakout_toward`, then render the spread and check that the action reads at reading
   size and that the reveal is the first thing read after the turn.
6. **Alternates** for the hardest page or spread: `board alt <pid> <name>` and edit, at least two.
   Run `board compare current,<a>,<b>` and open the PNG at its actual size. Pick by readability at
   reading size, panel share for the key action, new art needed, and checks. Then run
   `board promote <name> --reason "..."` (use `--dry-run` first), or
   `board promote current --reason "..."` to keep the current layout. Never force through a block
   that would orphan a job or accepted art.
7. **Check and render.** Run `board check` until it shows 0 errors and 0 warnings, and explain each
   info. Run `board render` and look at every `pNNN-rough.png`, each `spread-*.png` at actual size,
   and `turns.png`.
8. **Return.** Report:
   - the check output, with the page and spread paths and `turns.png`
   - the comparison and the logged decision
   - the `needs-art` list for illustrate, with the shot guides carrying focal points and notes
   - moved or stale jobs for the director
   - requests for story with exact ids

## Worked example
Request: "Board the three-page chapter as lettered roughs. The prop changes hands before the turn,
and the recipient is revealed after it." The chapter pairs as [p1 p2] / turn / [p3], read rtl.
```
mangakit board plan --chapter 01            # p1 cold-open, sprint | p2 doors-closing, give-prop, departs | turn | p3 reveal
mangakit board plan --chapter 01 --write
mangakit rough make                          # rough-platform, rough-sprint-*, rough-doors, rough-departs, rough-reveal (no image calls)
#   p1: L.rows([540,470,358]); platform borderless, L.bleed(top, ("top","outside")); slot(final=..., rough=...)
#   p2: the accepted hands art keeps its transform and border-break; doors and departs use roughs
#   p3: one large reveal panel; focal "face" rank 1, "seal" rank 2; one short line away from the face
mangakit board alt p2 b ; mangakit board alt p1 b    # b: doors move to p1, tall handoff
mangakit board alt p2 c                              # c: doors as an inset over a tall handoff
mangakit board compare current,b,c
#   b: handoff 59% of p2 but the extra area is empty rough that needs new art; crops p1's sprint focal (no-focal)
#   c: doors inset is 9% of the page and cramped
mangakit board promote current --reason "same hands size at reading size; b/c only add extension art ..."
mangakit board check --chapter 01           # 0 errors, 0 warnings, 6 needs-art info
#   [p1 p2] opening: no reveal | [p3] after a page turn: reveals recipient-identity on p3/reveal
mangakit board render --chapter 01          # pNNN-rough.png, spread-*.png, turns.png
```
A lesson from the demo: an alternate that adds a tier squeezes its neighbours, and the crop can cut a
rough's focal point out of frame (`no-focal`). Check the panels you did not mean to change, too.

## Done when
- `mangakit board check` shows 0 errors and 0 warnings. Every info is explained, and every
  `needs-art` panel is handed to illustrate.
- Every beat has a panel and every line a balloon, in script order, in the project's reading
  direction. Every panel lists its focal points in rank order.
- Every reveal is on the first page after a turn and in the first panel(s) read there, as
  `turns.png` shows.
- No panel id was renumbered and no retired id was reused. `board.yaml` matches the sources.
- The hardest page or spread had at least two alternates compared at reading size, and the pick,
  including keeping the current layout, is logged with its reason in `alternates.yaml`.
- Accepted art is unchanged and its pages still rebuild. No image call was made by this skill. No
  story record, final art, mask or job was edited.
