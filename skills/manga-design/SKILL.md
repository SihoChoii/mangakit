---
name: manga-design
description: Make and maintain how a manga looks. That means character, costume, prop, environment and world design sheets, recorded as versioned references with variants and single-part views tied to canon ids. It also means a separate, versioned art-direction guide whose rules (line weight, tone density, motifs, type, SFX, title) each carry exemplar style cards, tested on a sample shot at actual reading size. Use when a canon character, prop or place needs a design or a new costume or state, when art requests need references to pin, when the look of the book must be defined or changed ("use a heavier ink treatment going forward"), or when `design check` reports missing designs or superseded styles. Do not use it to decide when a costume changes (story), to lay out panels (board), to draw shots (illustrate) or to letter pages (compose).
---

# manga-design

You own what everything looks like, and the rules that make the whole book look like one book. You
make design sheets and register them as references. You write the art-direction guide as
append-only revisions. You prove the guide works at the size a reader sees it. You never edit story
records, page sources or panel art. A new look is a new version or a new revision. Nothing you
publish is changed in place.
Tools: `mangakit` (the toolkit in the mangakit repo; `install.sh` installs it and puts `mangakit` on PATH); `docs/...` below means the repo's docs folder, which `mangakit docs` prints. Schemas, spec grammar, direction
format and check codes: `docs/design-reference.md`. Commands:
`docs/cli.md`.

## Inputs
- A project directory (`project.yaml`, `story/`, `references/`, `chapters/`)
- Visual inputs: accepted panel art, client references and mood images, existing sheets in
  `references/`, and anything the brief says the book should look like
- Script needs, from story:
  - `story/canon.yaml`: characters, props and locations, each with a `design:` id
  - `story/beats.yaml`: who is present and what is shown at each beat
  - `story/continuity.yaml`: `<char>.costume` events, which say when a look changes
- For a direction change: the request, and where it starts (a chapter or a beat)
- The image tool the host provides, plus a call budget from the director

## Allowed edits
- `references/<id>/`: add versions, views, briefs, and identity fields (`ref add|view|meta`,
  `design brief|collect|recall`). Versions are immutable. A fix is a new version.
- `references/direction.yaml`: append revisions (`style revise`), or write the first one. Never
  edit a revision that a job or a page manifest has used.
- `chapters/<ch>/chapter.yaml` `style:` only, and only through `style revise`, which pins earlier
  chapters.
- Do not edit story records. If a canon `design:` id is missing or wrong, or a costume needs a
  continuity event, report it to story with the exact id and value. Story owns when a costume
  changes. You own what each variant looks like.
- Do not edit page sources, lettering, masks, art assets or jobs. You may open art requests only to
  try a design (`job request`), and you hand them to illustrate.

## Procedure
1. **Inventory.**
   - Run `mangakit design check`. List every canon id that appears in a beat, its `design:` id, and
     every costume value in continuity.
   - Each of these needs a reference, and each costume value needs a variant. Decide which already
     exist (`ref list`) and which to make.
   - Agree the call budget before any image call.
2. **Derive the look first.** Start from the accepted art if there is any. Register it, or crops of
   it, as `kind: style` references, then name views on them (`ref view`) for each visual rule:
   linework, solids, hatching, a motif. Render type, SFX and title exemplars with mangakit from the
   project fonts. Do not generate them.
3. **Design sheets.** For each missing design:
   - Write a brief with `design brief <id> --kind K --layout L --canon C --variant V --ref <style card>`.
     Describe the design, never a scene. Use `turnaround` to define a character, `details` for
     hands, cuffs, shoes and accessories, `prop` for props, and `environment` for places. Pin the
     style cards so the sheet matches the ink.
   - Make the call with the host image tool, using `host-call-1.json`, then run `design collect`.
     Log every failed call with `design recall`.
   - Look at each sheet at 100%, then name views for every part a shot will need (front, face,
     hands, cuff, prop front/back). Record defects in the version note and route around them ("cuff
     colour wrong in v001: use v002#cuff"). Collect detail sheets with `--no-select` so the
     turnaround stays selected.
   - Shots pin single views, never a whole multi-pose sheet. Extra figures and extra hands come from
     whole sheets.
4. **Costumes.** Give each costume or state its own variant on the design. Check
   `design for <char> --beat <b>` at the beats on each side of every costume event. A missing
   variant is `costume-variant-missing`.
5. **Art direction.** Write one revision with a rule per concern:
   - Use `line-weight`, `tone-density`, one `motif` rule per element, `type`, `sfx` and `title`.
   - Each rule gets one sentence of `text` an artist could follow, `cards` that show it, and
     `brief: true` if illustration needs it.
   - Rules that change rendering get `render` settings: border and balloon `styles`, `lettering`,
     `sfx`.
   - A rule about one character or prop gets `scope: [canon ids]`. Without a scope its words reach
     every shot, and the generator copies that detail onto everyone.
   - The first revision's render settings should equal the project's current ones, so existing
     proofs rebuild byte-identical.
6. **Sample-shot test.**
   - Run `design sample --image <accepted art or sheet view> --revision <rev> --line "<a real line>" --sfx "<a real SFX>"`.
     Use `--compare old,new` for a change.
   - Open `reading.png` at its actual size. That is the reader's size, so do not zoom in.
   - Fill in `judge.md` rule by rule. For a failure, change the rule in a new revision, or give the
     owning skill a note.
7. **Changing the look.**
   - "Heavier ink going forward" means
     `style revise <new> --base <current> --from-chapter <C> | --from-beat <B> --rules rules.yaml --note "<request>"`.
     Earlier chapters get pinned automatically.
   - Run `design check`. Every `job-style-superseded` goes to illustrate to re-request. Report each
     `art-style-older` to the director. Never redraw it yourself.
   - Show that a new request in the new range carries the new revision, and that an earlier
     chapter's pages still rebuild byte-identical.
8. **Export and return.** Run `design guide`, which writes `build/design/direction.md`. Report:
   - `design check` with 0 errors
   - sheet paths with their views, and the guide path
   - the sample `reading.png` and the filled `judge.md`
   - image calls (`design calls`) against the budget
   - pins and superseded jobs, and findings for story, illustrate and compose

## Worked example
Request: "Design the courier, the detective, the envelope and the train door from the accepted
handoff panel. Then make the ink heavier from chapter 02." Example project: `example/` in the mangakit repo is a text-only cut of the demo this worked example comes from.
```
mangakit design check                          # ERROR design-missing: courier-design (canon rin)
# style cards from the accepted panel (no image call)
mangakit ref add style-ink-v007 art/assets/hands-at-door/v007.png --kind style
mangakit ref view style-ink-v007 lines --box 259,472,810,731    # also solids, hatching, seal
# sheets: 6 image calls in total
mangakit design brief rin-design --kind character --layout turnaround --canon rin \
    --variant courier-jacket --prompt "..." --ref style-ink-v007#lines
#   host image tool with briefs/b001/host-call-1.json, then:
mangakit design collect rin-design b001 <image>
#   v001 has the cuffs drawn black, so a details sheet follows:
mangakit design collect rin-design b002 <image> --no-select
mangakit ref view rin-design cuff --version v002 --box ...
# also saeki-design (canon saeki, variant dark-overcoat), envelope-design (prop),
#      train-door-env (environment; canon platform-7,train-car-3,train-departing)
# direction: sr-001 effective ch01 (render = current project values), one rule per concern
mangakit design sample --image hands-at-door@v007 --revision sr-001 --line "Take it! ..." --sfx KSSHHH
#   judge.md: sfx FAIL (too small for the panel at reading size) -> follow-up rule change
mangakit style revise sr-002 --base sr-001 --from-chapter 02 --rules sr-002-rules.yaml \
    --note "heavier ink from chapter 02"
#   pinned chapter 01=sr-001
mangakit job request p001 --chapter 02 --panel arrival --asset saeki-kyoto \
    --design saeki#three-quarter --design envelope#back
#   style sr-002; pinned saeki-design@v001#three-quarter [dark-overcoat], style-cards@sr-002
mangakit rebuild build/ch01/p003/proof.manifest.json  # identical: YES (ch01 keeps sr-001)
mangakit design check                          # 0 errors; info: art-style-unrecorded hands-at-door@v007
```
A lesson from the demo: an unscoped motif rule ("white ribbed cuff") went into every brief, so the
detective came back wearing the courier's cuff. Give a character's details `scope:`.

## Done when
- `mangakit design check` shows 0 errors. Every canon id that appears in a beat has a design
  reference tied to it, and every costume value has a variant.
- Every sheet was inspected at 100%. Its defects are written in version notes, and shots have
  single views to pin for the parts they need.
- `references/direction.yaml` has a rule for line weight, tone density, motifs, type, SFX and title.
  Each rule has text and at least one resolvable card. Character-specific rules are scoped.
- The direction was tested with `design sample` at reading size, and `judge.md` has a verdict for
  every rule. Failures are fixed in a later revision or handed to their owner.
- For a change: the new revision starts where the request said. Earlier chapters are pinned, and
  their pages rebuild byte-identical. A new request in range carries the new revision. Superseded
  jobs and older-revision art are listed for their owners.
- Every image call is counted (`design calls`) and within the agreed budget. No story record, page
  source, lettering or panel art was edited by this skill.
