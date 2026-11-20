# mangakit project format

```
project.yaml            settings (one authority per fact, see below)
story/premise.yaml      title, logline, premise, audience, length, tone, goals
story/canon.yaml        characters (the only valid speakers), props, locations (+adjacency), facts, initial state
story/beats.yaml        ordered beats: summary, location, present, shows, asserts, reader knows/suspects/conceals
story/script.yaml       dialogue lines: id, beat, kind, speaker, text (owns wording)
story/continuity.yaml   continuity events: subject.attribute changes to value at beat
story/threads.yaml      setups and payoffs linked by id (see story-reference.md)
references/<id>/        ref.yaml + vNNN.<ext>: design sheets, style exemplars, props (kind, identity, variants, versions)
chapters/01/chapter.yaml  ordered page ids
chapters/01/pages/p003.py page sources (own panel geometry, placement, line breaks)
art/assets/<id>/        registry record + immutable drawing versions + masks
art/jobs/<job-id>/      illustration jobs: job.yaml, request.yaml, prompt.md, pack/, host-call-<n>.json, inbox/, candidates/, review.png
reviews/findings.yaml   review findings tied to revisions
work/units/w-NNNN.yaml  director work units (id, skill, inputs, requested, status, outputs, history)
work/baseline-ch<C>.yaml story snapshot the last plan compared against
work/context/<id>.md    context packet handed to the skill doing a unit
work/decisions.yaml     append-only director decisions (D001...)
work/gates.yaml         creator approvals (gate, subject, by, note)
work/logs/<id>.log      output of automatic units
publish/ch<C>/<name>/   frozen proof sets: <page>/{proof,reading}.png + manifests, set.yaml (read-only)
fonts/                  pinned font files (+ OFL licenses)
build/                  regenerable: proofs, spreads, contact sheets, manifests, exports
history/snapshots/      content-addressed copies of page sources, scripts, project.yaml used by proofs
```

Create with `mangakit init <dir> [--direction rtl|ltr] [--language en] [--trim-mm 182x257] [--bleed-mm 3] [--dpi 600]`.

## project.yaml

| Key | Meaning |
|---|---|
| `reading_direction` | `rtl` (manga) or `ltr`. Drives spread order, contact sheet order, reading-order checks. |
| `language`, `color` | metadata; `lettering.uppercase` defaults to true for `en`. |
| `page.trim_mm`, `bleed_mm`, `safe_mm`, `units_per_mm` | page format and page-unit scale. |
| `spreads.pairing` | `odd-start` (p1 alone as recto, then 2-3, 4-5) or `even-start` (1-2, 3-4). `chapters/<ch>/chapter.yaml pairing:` overrides it per chapter. |
| `active_chapter` | default chapter for page ids. |
| `fonts.<role>` | `file`, `sha256`, `license`. Render fails the `font-pin` check if bytes change. |
| `lettering` | `font_size`, `line_height`, `balloon_padding`, `tail_gap`, `uppercase`. |
| `styles.<name>` | stroke styles (`panel-border`, `balloon`, ...). |
| `render` | renderer + version + sha256, `proof_dpi`, `reading_height_px`, `thumb_height_px`. |
| `output_profiles.<name>` | `dpi`, `bleed` (true = full bleed canvas, false = trim), `mode` (`L`/`RGB`), `format`. |

## Story (story/*.yaml)

Full schema and check codes: [story-reference.md](story-reference.md).

```yaml
# script.yaml
lines:  [{id: line-17, beat: give-envelope, kind: speech, speaker: rin, text: "Take it! *Don't* open it before Kyoto!"}]
```
Line order in the file is the intended reading order (checked against balloon placement). Beats live
in `story/beats.yaml`; a `beats:` list inside script.yaml (older projects) is still read.
SFX lines (`kind: sfx`) are lettered with `page.text(None, at=..., line="line-04")`.

## Asset registry (art/assets/<id>/asset.yaml)

```yaml
id: hands-at-door
selected: v001
versions:
  v001: {file: v001.png, sha256: ..., width: 1800, height: 1300, job: job-0001, status: selected}
landmarks:
  v001: {finger-contact: {xy: [577.4, 1009.7], protect: true}}
masks:
  border-break:
    selected: m003
    versions:
      m001: {file: masks/border-break/m001.png, source_version: v001, source_sha256: ..., recipe: {...}}
```

* Versions and masks are append-only files; nothing is overwritten. `select` changes what pages use.
* Landmarks are per drawing version; masks record `source_version` + `source_sha256`. Selecting a
  new drawing version leaves old masks/landmarks attached to the old version (reported stale).
* `asset select --if-current vNNN` refuses if someone else changed the selection (late job results).
* Masks are 8-bit greyscale, white = visible, same pixel size as their source version.

## Jobs (art/jobs/job-NNNN/job.yaml)

`id, asset, status (open|delivered), brief, brief_file, selected_when_opened, inputs, candidates[]`.
`mangakit asset add <id> <file> --job job-NNNN` records the candidate on the job. Selection is always
an explicit later step.

## Proof manifests (build/.../<view>.manifest.json)

Every render writes one next to the PNG: page source sha256 + snapshot path, script sha256 + snapshot
+ the exact line texts used, project.yaml snapshot, asset versions + sha256 + landmarks, mask versions
+ sha256 + source version, overlays, font sha256s, effect seeds, renderer version + binary sha256,
view params, output sha256. Snapshots are content-addressed under `history/snapshots/` (tracked; `build/` stays disposable).
`mangakit rebuild <manifest>` re-renders from the snapshots and pins and reports whether the bytes
match. Keep the manifest files you may need to rebuild (copy them out of `build/`, e.g. into `history/proofs/`).

## References (references/<id>/ref.yaml)
Same append-only version rules as drawings.
* `kind` is a design kind (character, costume, prop, environment, world) or design, style, source,
  pose, other.
* `identity` names who or what it depicts. `canon` is the canon id or ids it designs.
* `versions.<v>.variant` is the costume or state. `views` are named crops of one version, cached in
  `views/`.
* `briefs/bNNN/` holds the design brief and its image-call log.
* Specs are written `id[:variant][@vNNN][#view]`. Art requests pin version, view box and sha256.
  Full schema: design-reference.md.

## Art direction (references/direction.yaml)
Revisions (`id`, `effective: {chapter}|{beat}`, `based_on`, `note`, `rules`). A rule has kind,
text, cards, brief, render, scope. A card is a spec string or `{spec, scope: [canon ids]}` (a scoped
card is pinned only for shots that show one of them). A chapter's `chapter.yaml` can pin `style: <rev>`. Render
settings from the effective revision are merged into project settings at page load and recorded in
the manifest (`style: {revision, render}`). See design-reference.md.

## Art requests (art/jobs/job-NNNN/request.yaml)
```yaml
job: job-0006
asset: hands-at-door
reason: correction          # new-shot | correction | extension | design-change | continuity | lettering | mask
adapter: host               # host | manual | command
target: {page: p003, panel: handoff, beat: give-envelope, page_source: chapters/01/pages/p003.py,
         page_sha256: ..., git: 240b3fd, reading_direction: rtl}
base_selection: v001        # selection when the job opened; `job select` refuses if it moved
shot_guide: {png: pack/guide.png, json: pack/guide.json, rough_crop: pack/rough-crop.png,
             context_crop: pack/context-crop.png, draw_area_page_units: [x0, y0, x1, y1],
             aspect_ratio: "4:3", min_source_px_for_print: [w, h], landmarks: [...], reserved_lettering: [...],
             rough_is_placeholder: false}   # true: the rough is an empty slot and is not sent
references: [{id, spec, version, kind, identity, canon, variant, view: {name, box, note}, style_rule, note, sha256, file, pack_file, size}]
style_revision: {revision, chapter, beat, rules: {...}, cards: [{rule, spec}], out_of_scope: [...]}
continuity: {beat_summary, reader_knows_after, conceal, previous_screen_direction, transition_to_next,
             dialogue_in_panel}
beyond_border: "tip-break: the drawing must continue past the panel border ... x 27-54%, y 75-95% of the image ..."
edit_of: {asset, version, sha256, file, instruction, pack_file, paintover: {pack_file, sha256}}   # or null
style: "..."
acceptance: ["...", ...]
notes: "..."
```
`job.yaml` adds `calls` (n, adapter, mode generate|edit, at, status pending|done|empty, outputs,
note), `candidates`, `verdicts` (per version: pass, note, at), `status` (open, delivered, reviewed,
rejected, accepted) and `accepted` / `accepted_at`.

## Illustration settings (project.yaml)
```yaml
illustration:
  style: "Monochrome seinen manga ink on white paper: ..."   # default --style, used only when no direction.yaml exists
  adapters:
    host: {prompt_arg: description, refs_arg: reference_image_paths, aspect_arg: aspect_ratio, max_refs: 4}
    command: {run: "my-imagegen --prompt {prompt} --refs {refs} --aspect {aspect} --out {out_dir}"}
```

## Board (milestone 5)
```yaml
board:                         # project.yaml; defaults shown
  margins_mm: {top: 10, bottom: 12, inside: 9, outside: 9}
  gutter_mm: {row: 4.0, col: 2.5}
```
* `art/roughs/<asset>.py`: sketch source (`SIZE`, `sketch(s)`). The registry record has `kind: rough`;
  each version stores `vNNN.sketch.py` and `rough: {source, focal: [{at, label, rank}], sightlines:
  [{from, to, label}], notes, camera}`; landmarks as for any drawing.
* `chapters/<ch>/board.yaml`: `chapter, direction, pairing, pages: [{id, status (drawn|planned), spread, after_turn,
  panels: [{id, beat, lines, reveals, size, status}]}], retired: [{id, page, at}]`.
* `chapters/<ch>/alternates.yaml`: `promotions: [{alt, at, reason, pages, moved, dropped, archived}
  | {alt: current, kept: true, at, reason, alternates}]`.
* `chapters/<ch>/pages/<pid>.alt-<name>.py` alternates; `<pid>.alt-pre-<name>.py` archives.

## Review (milestone 6)
```yaml
review:                        # project.yaml, optional
  sfx_min_panel_height: 0.18   # sfx-small threshold unless the direction's sfx rule sets render.sfx.min_panel_height
```
* `reviews/findings.yaml`: `findings: [...]`, schema in review-reference.md.
* `reviews/ch<ch>/cold/rNN/`: `packet/` (reader-facing), `round.yaml`, `answers.yaml`, `key.yaml`, `score.md/json`.
* `reviews/ch<ch>/art-story/`, `reviews/ch<ch>/findings/<id>@<rev>.png`, `reviews/ch<ch>/recheck/<stamp>/`.

## Direct (milestone 7)
`project.yaml`:
```yaml
creator:
  gates:
    series_look: true       # design sheets and direction changes wait for the creator
    lettered_boards: true   # art units for a chapter wait for approval of its lettered boards
    final_version: true     # publish --final waits for approval
```
Work units, decisions, gates and publish sets: see direct-reference.md. Asset versions may carry
`style_judged: {revisions: [...], decisions: [...]}` (written by `work art-style`).
