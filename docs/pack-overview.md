# Manga skill pack: overview

Seven skills share one file-backed project and one tool, `mangakit`. The director routes the work
and each skill owns one kind of edit, so a change touches the fewest files and reruns the least.

## Skills and what each owns

| skill | owns (only it edits) | load it for |
|---|---|---|
| **manga-direct** | `work/` (units, context packets, decisions, gate records), `publish/`, chapter style pins | "make a chapter", "fix X on page N", what runs next, interrupted work, change requests, creator gates |
| **manga-story** | `story/` (premise, canon, beats, reader knowledge, continuity, script, threads) | what happens, who says what, who holds what, when the reader learns it |
| **manga-design** | `references/` (character, prop and place sheets, variants, views), `references/direction.yaml` | how things look: designs, costume variants, the art-direction revisions and their scope |
| **manga-board** | `chapters/<ch>/board.yaml`, page layout in page sources, `art/roughs/`, alternates | page and panel layout, the eye path, page turns, lettered roughs |
| **manga-illustrate** | `art/jobs/`, drawing versions and their selection, landmarks | final art for a panel: request, host image call, review, guarded selection |
| **manga-compose** | placement, masks, breaks and lettering in page sources; renders and exports | putting art and words on the page, border breaks, lettering fit, proofs |
| **manga-review** | `reviews/` (cold-read packets, answers, scores, findings, verdicts, rechecks) | reading the pages as a reader, filing findings with owners, verifying fixes |

## Handoffs

```
brief ─► direct ─► story ─► design ─► board ─► illustrate ─► compose ─► review
           ▲         (any skill can be called again, in any order)        │
           └────────── findings by owner, stale units, creator gates ◄────┘
```
- story → design: `design check` flags a missing design or costume variant from canon and continuity.
- story → board: beats and lines become panels and balloons (`board plan`). `story impact` lists the
  panels a change touches.
- design → illustrate: the request pins the variant in effect at the beat (`--design`) and the
  effective style revision. Scoped rules and cards reach only the shots they belong to.
- board → illustrate: a `needs-art` slot plus its rough, landmarks and reserved lettering areas form
  the shot guide.
- illustrate → compose: the selected version and its landmarks. Compose places it, masks it and
  letters the page.
- compose → review: renders and manifests. Review files findings with an owner. The director turns
  them into units for that owner.
- review → direct: `editorial` findings wait for the creator. The director never picks one.

## Project layout

```
project.yaml        page, fonts, lettering, render, creator gates
story/              canon, beats, continuity, script, threads           (story)
references/         design sheets, style cards, direction.yaml          (design)
chapters/<ch>/      chapter.yaml (pages, pairing, style pin), board.yaml, pages/*.py   (board/compose)
art/roughs/ assets/ jobs/   rough sketches, drawing versions + masks, art requests      (board/illustrate)
reviews/            packets, findings.yaml, rechecks                     (review)
work/               units/, context/, decisions.yaml, gates.yaml, logs/  (direct)
publish/ch<ch>/<set>/  frozen proof sets with manifests                  (direct)
build/              regenerable renders; history/snapshots/ keeps what proofs were made from
```

## Quick start

```
mangakit init my-manga --direction rtl && cd my-manga
# story: write story/{premise,canon,beats,continuity,script}.yaml        -> mangakit story check
# design: designs and a first direction revision                          -> mangakit design check
mangakit board plan --write --stubs          # pages and panels from the beats
mangakit rough make <id> ; mangakit board check ; mangakit board render
mangakit work plan                           # everything the chapter needs, as units
mangakit work next                           # the next unit + its context packet -> load the routed skill
mangakit work run                            # renders, checks, rechecks
mangakit review packet ...                   # cold read, findings
mangakit work plan && mangakit work status   # findings and stale work come back as units
mangakit publish create proof-001            # freeze; later: mangakit publish rebuild proof-001
```
Ask the creator to approve each gate in their own words: series look, lettered boards before art,
and the final version. Then `work approve` records it.

## Docs
`cli.md` (every command), `project-format.md`, `page-api.md`, and one reference per skill:
`story-`, `design-`, `board-`, `illustrate-`, `compose-`, `review-`, `direct-reference.md`.
`roadmap.md` lists the known gaps.
