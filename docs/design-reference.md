# manga-design reference

Design decides how things look. Story decides when a look changes. A chapter's `style:` pin decides
which art-direction revision its pages use. Everything below is append-only: versions and revisions
are added, and never edited or renumbered once a job or page points at them.

## Ownership
| Record | Owner | Says |
|---|---|---|
| `references/<id>/ref.yaml` + `vNNN.*` | design | what a character, costume, prop, environment or world looks like (identity, variants, versions, views) |
| `story/canon.yaml` `design:` field | story writes the id, design makes it exist | which reference designs a canon id |
| `story/continuity.yaml` `<char>.costume` events | story | when the costume changes (the value names a design variant) |
| `references/direction.yaml` | design | art-direction revisions: rules, style cards, render settings |
| `chapters/<ch>/chapter.yaml` `style:` | design (via `style revise`) / direct | the revision a finished chapter keeps |

## Reference records
```yaml
# references/rin-design/ref.yaml
id: rin-design
kind: character          # character | costume | prop | environment | world  (design kinds)
                         # design | style | source | pose | other             (other references)
identity: Rin, courier
canon: rin               # canon id(s) this designs; a list for one environment used by several locations
selected: v001
versions:
  v001: {file: v001.jpg, sha256: ..., variant: courier-jacket, note: "...", brief: b001, added: ...}
  v002: {file: v002.jpg, sha256: ..., variant: courier-jacket, brief: b002}
views:                   # named crops of one version, in source pixels
  front:  {version: v001, box: [x0, y0, x1, y1], note: "full figure, front"}
  cuff:   {version: v002, box: [...], note: "sleeve + cuff detail only"}
```
* **Spec grammar** (`ref resolve`, `--ref`, rule `cards:`, `--design`): `id[:variant][@vNNN][#view]`.
  * `id` alone is the selected version.
  * `:variant` is the selected version if it has that variant, otherwise the newest version that does.
  * `#view` is the version the view belongs to. Adding `@vNNN` with a different version is an error.
  * View crops are cached at `references/<id>/views/<ver>-<view>.png`. Requests pin the crop's
    sha256 and record the view box.
* **Single-view vs multi-pose.** Use a multi-pose sheet (turnaround) to define a design. Pin a
  single view to draw a shot: a full turnaround makes generators draw extra figures or hands. Give
  every sheet views for the parts shots will need (front, face, hands, cuff, prop face) and pin
  those.
* **Costume variants.** A costume is a `variant` of the character's design, or of a separate
  `kind: costume` reference tied to the same canon id. Story's continuity `<char>.costume` value
  must name a variant. `design for <char> --beat B` returns the spec for the costume in effect at B,
  and `job request --design <char>[#view]` uses that.

## Design briefs and image calls
`mangakit design brief <id> --kind K --prompt "..." --layout L [--ref spec]... [--canon C] [--variant V] [--aspect 16:9]`
writes `references/<id>/briefs/bNNN/` with `brief.yaml`, a packed `refs/` folder and
`host-call-1.json`, ready for the host image tool.
* Layouts: `turnaround` (front, 3/4, back, face, in a row), `details` (close-ups of hands, cuffs,
  shoes, accessories), `single`, `prop` (front/back/edge/in-hand), `environment` (an establishing
  view plus key details, with no figures), `card` (a style exemplar).
* Every brief says: no text, no labels, no panel borders, flat even light. A plain white background
  is added except for environment and world kinds.
* Make the call, then run `design collect <id> <bNNN> <image> [--no-select]`. This adds a version
  linked to the brief and logs the call. If a call fails or is unusable, run `design recall <id> <bNNN>`
  to log it before retrying. `design calls` totals the calls per reference, and `metrics` reports
  them as design-sheet image calls.
* Inspect each sheet at 100% before you add views. Record defects in the version note ("cuffs drawn
  black: use v002#cuff for cuffs"). Never repaint a sheet in place. A fix is a new version.

## Art direction (references/direction.yaml)
```yaml
guide: "Chapter look, derived from the accepted handoff panel"
revisions:
- id: sr-001
  effective: {chapter: '01'}          # or {beat: <beat-id>}
  note: "..."
  rules:
    line-weight:  {kind: line-weight, text: "...", cards: ['style-ink@v001#lines'], brief: true,
                   render: {styles: {panel-border: {width: 4.5}, balloon: {width: 2.2}}}}
    tone-density: {kind: tone-density, text: "...", cards: [...], brief: true}
    cuff-motif:   {kind: motif, text: "white ribbed cuff", cards: [...], brief: true, scope: [rin]}
    type:         {kind: type, text: "...", cards: [...], render: {lettering: {size: 34}}}
    sfx:          {kind: sfx, text: "...", cards: [...], render: {sfx: {font: sfx, size: 64, outline_width: 6}}}
    title:        {kind: title, text: "...", cards: [...]}
- id: sr-002
  based_on: sr-001                    # inherits every rule it does not override
  effective: {chapter: '02'}
  note: "Heavier ink treatment going forward"
  rules: {line-weight: {...}}
```
* **Rule kinds:** line-weight, tone-density, motif, type, sfx, title, other. Each rule has `text`
  (the rule in words), `cards` (exemplar specs), and optional `brief` (true means art requests carry
  its text and cards), `render`, and `scope`.
* **`scope: [canon ids]`.** The rule applies only to shots whose beat has one of these present or
  shown. Use it for anything that belongs to one character or prop, such as a costume detail used
  as a motif. Without it, the rule's words reach every brief and the generator puts that detail on
  other characters.
* **`render` keys:** `lettering`, `styles` and `sfx`. They are deep-merged into the project
  settings when a page in an affected chapter loads. The page manifest records the revision and the
  merged values, so `rebuild` uses what was recorded even if the direction changes later. An
  explicit argument in a page source (`outline_width=3`) beats the direction.
* **Effective revision for (chapter, beat):**
  1. The chapter's `style:` pin, if set.
  2. Otherwise the last revision in story order whose start (chapter, or beat position) is at or
     before the beat.
  * Render settings switch per chapter only: a beat-start revision changes art briefs, not lettering
    inside a chapter.
* **`style revise <new> --base <rev> --from-chapter C | --from-beat B --rules rules.yaml --note "..."`**
  * Appends a revision.
  * Pins every earlier chapter that has no `style:` yet to the revision it was using, unless
    `--no-pin` is given. This is what keeps finished chapters stable.
  * Never edit a revision that jobs or manifests have used. Revise instead.
* **Requests.** `job request` auto-pins the effective revision's brief cards for the panel's beat.
  With two or more cards, it packs them into one montage reference (`style-cards@<rev>`), so the
  cards take one reference slot. Their texts go into the style line as `Art direction <rev>: ...`.
  The request records `style_revision` (revision, rules, cards, out_of_scope). `--no-style` turns
  this off, and project `illustration.style` is used only when no direction exists.

## Sample-shot test
`mangakit design sample --image <spec|asset[@ver]|file> [--revision R | --compare R1,R2] [--line "..."] [--sfx "..."] [--sfx-at fx,fy] [--line-at fx,fy] [--box x,y,w,h]`
lays the image out as one panel on a trim-size page. It letters the panel with a balloon and an SFX
in the revision's render settings, then renders:
* `build/design/sample-<rev>/reading.png`, at the reading view's height (`render.reading_height_px`):
  the size a reader sees on a phone. **Judge at this size only. Do not zoom in.**
* `proof.png` at full size, for checking linework
* `judge.md`: one row per rule, with columns for its text, cards, and a pass/fail and note for you
  to fill in
* `--compare` puts the reading views of several revisions side by side, unscaled.

What to judge at reading size:
* Does the line weight hold up?
* Do the solids stay solid, and do tones moiré or turn gray?
* Can the balloon be read in one glance?
* Does the SFX read, and is it the right size relative to the panel?
* Is the motif recognisable?
Write the verdicts in judge.md. A failure becomes a rule change in a new revision, or a note for
the lettering owner.

## `design check` codes
| Code | Sev | Meaning |
|---|---|---|
| design-missing | error | canon `design:` names a reference that does not exist |
| design-canon-mismatch | error | the reference's `canon` is a different id |
| design-kind | warn | a canon design reference is not a design kind (character/costume/prop/environment/world) |
| design-unassigned | warn/info | a character in a beat has no `design:` (warn); info if not in any beat yet |
| costume-variant-missing | error | an initial or continuity `<char>.costume` value has no variant on the character's design |
| view-orphan | error | a view points at a version that does not exist |
| style-base-missing / style-no-start / style-rule-kind / style-render-key / unknown-beat | error | malformed direction |
| style-card-missing | error | a rule's card spec does not resolve |
| style-pin-missing | error | a chapter `style:` names an unknown revision |
| job-style-superseded | error | a live job pinned a revision that is no longer effective for its beat, or a card that has a newer version |
| art-style-older | warn | a selected drawing was made under an older revision than its beat now needs (flag only; the director decides) |
| art-style-unrecorded | info | the selected drawing predates direction records |

## Guide export
`mangakit design guide [-o build/design/direction.md]` writes the direction as markdown: each
revision, its effective start, its rules with inheritance, card thumbnails and render settings, and
the chapter pins.
