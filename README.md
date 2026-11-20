# mangakit: agent skill pack + toolkit for making manga

Seven agent skills (story, design, board, illustrate, compose, review, direct) and the toolkit they
share, `mangakit`. A manga project is a folder of plain files: story records, design references,
one Python page source per page, versioned art, review findings and work units. `mangakit` renders
the pages to SVG and PNG with [resvg](https://github.com/linebender/resvg), checks them, and freezes
proof sets that rebuild byte for byte. Image generation is never built in: it plugs in through an
adapter, so any image model, a human illustrator, or another agent can draw the panels.

```
skills/        seven SKILL.md files (manga-direct, -story, -design, -board, -illustrate, -compose, -review)
mangakit/      the toolkit (Python package + `mangakit` CLI)
docs/          command reference, project format, page API, one reference per skill, roadmap
tests/         end-to-end tests (all fixtures are generated in the test)
example/       a small text-only project: story records, art direction, chapter pages with procedural roughs
install.sh     downloads resvg + fonts (sha256-checked), pip-installs mangakit, copies the skills
```

## The seven skills

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


Start with **manga-direct**: it plans the work as units, hands each unit to the owning skill with a
context packet, and stops at the creator's gates (series look, lettered boards before final art,
the final version). It records the creator's own words for a gate and never approves one itself.

## Install

Needs Python 3.10+, `curl`, and `unzip` on macOS.

```
git clone https://github.com/SihoChoii/mangakit && cd mangakit
python3 -m venv .venv && . .venv/bin/activate        # recommended
bash install.sh                                         # skills go to ~/.claude/skills
bash install.sh --skills-dir /path/to/your/agent/skills # or anywhere else
bash install.sh --no-skills                             # toolkit only
```

`install.sh` does four things:

1. Downloads **resvg 0.49.0** from the
   [official release](https://github.com/linebender/resvg/releases/tag/v0.49.0)
   (`resvg-linux-x86_64.tar.gz` or `resvg-macos-aarch64.zip`), checks the archive's and the
   binary's sha256, and puts it at `vendor/resvg-0.49.0/resvg`.
2. Downloads the four fonts from [google/fonts](https://github.com/google/fonts) (pinned commit),
   checks each sha256 against the hashes the toolkit pins, and puts them in `mangakit/fonts/` and
   `example/fonts/`: Comic Neue Regular, Bold and Bold Italic (dialogue and captions) and Bangers (SFX).
3. Runs `pip install -e .` (deps: Pillow, PyYAML, numpy, shapely, fontTools, uharfbuzz). Pass extra
   pip flags with `PIP_FLAGS=...`.
4. Copies `skills/*/SKILL.md` into the skills folder (`--skills-dir`, default `~/.claude/skills`).

Supported platforms: **Linux x86_64** and **macOS arm64** (both have pinned resvg builds). On other
platforms, put a resvg 0.49.0 binary at `vendor/resvg-0.49.0/resvg` or on `PATH` before you run it.
resvg also ships Linux aarch64, macOS x86_64 and Windows builds, but this installer doesn't pin them.

**Agents with their own skill library.** Some agents, such as Grok Bot, keep skills in a managed
library rather than a folder. Either point `--skills-dir` at the folder that library reads, or add each
`skills/<name>/SKILL.md` through the agent's own skill tools. The skills refer to the docs as `docs/...`.
`mangakit docs` prints where that folder is.

Run the tests: `python3 -m pytest tests -q`.

## Quick start

With the example project:

```
cd example
for r in art/roughs/*.py; do mangakit rough make "$(basename "$r" .py)"; done
mangakit story check                 # 0 errors
mangakit board check 01              # 0 errors; needs-art infos list the panels without final art
mangakit render p003 --view reading  # build/ch01/p003/reading.png
mangakit design check                # reports the design sheets the story needs (the design skill's job)
mangakit work plan && mangakit work status
mangakit publish create proof-001 && mangakit publish rebuild proof-001   # byte-identical
```

To start a new project, run `mangakit init my-manga --direction rtl`. Then ask your agent to load
**manga-direct** and give it a brief. Each step and its command is in `docs/pack-overview.md`.

## How image generation plugs in

`mangakit job request <page> --panel <panel>` writes an art request. It contains the prompt, a shot
guide made from the rough, the pinned design and style references, and the lettering areas to keep
clear. `mangakit job call <job>` hands it to an adapter, which you set in `project.yaml` under
`illustration.adapters`:

| adapter | who draws | what `job call` does | how results come back |
|---|---|---|---|
| `host` | the agent's own image tool | writes `host-call-<n>.json` with the tool arguments (prompt, reference image paths, aspect ratio). The agent calls its image tool with them | `mangakit job collect <job> <file> --call n` |
| `manual` | a person, or another agent | points at `prompt.md`, `pack/` and `inbox/` | drop files in `inbox/`, then `job collect <job> --inbox` |
| `command` | a script or API wrapper | runs `illustration.adapters.command.run` with `{prompt} {refs} {out_dir} {aspect} {job}` | collected from `out_dir` |

Candidates are stored but never selected automatically. `job review` builds a review sheet, and
`job verdict --pass/--fail` records the call. `job select` refuses a candidate without a passing
verdict. Reference-guided corrections use `--edit-of <version>` (optionally with `--paintover`).
Rendering, checking and rebuilding never call an image backend. See `docs/illustrate-reference.md`.

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


## Known limits

- **Low-resolution art.** Image models typically return about 1280x720 pixels. That places at
  roughly 150-200 dpi on a B5 page, while the print profile wants 600 dpi. `check` reports
  `art-resolution`, and print output needs an upscale pass, which isn't included.
- **Lettering is Latin and horizontal only.** There's no vertical Japanese typesetting, no ruby,
  and no right-to-left scripts inside balloons. Pages can still read right-to-left.
- **No PDF or CMYK export.** Exports are RGB/grayscale PNG (plus SVG). Prepress conversion is up to you.
- **Cold reads need a fresh reader.** `manga-review` scores a blind read against a locked answer key.
  The agent that built the pages can't read them cold, so verifying "unclear to a reader"
  findings needs a person or a separate agent that hasn't seen the work.
- **Byte-identical rebuilds hold for the same toolkit, fonts and resvg binary.** The Linux and macOS
  resvg builds are different binaries, so a set frozen on one platform may not match on the other.
- More gaps are listed in `docs/roadmap.md`.

## License

The code, docs and skills are under the MIT License, copyright (c) 2026 Siho Choi; see `LICENSE`.
The repository doesn't include the fonts or the resvg binary; `install.sh` downloads them from upstream.
Comic Neue and Bangers are under the SIL Open Font License 1.1 (texts in `mangakit/fonts/OFL-*.txt`).
resvg is licensed Apache-2.0 OR MIT by its authors.
