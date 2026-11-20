# Illustration reference

How `mangakit` commissions a drawing for one panel, stores what comes back, decides what to
accept, and hands the accepted version to composition. Image generation never runs inside
`render`, `check` or `rebuild`; it runs only through an adapter, one logged `job call` at a time.

```
job request ─▶ job call ─▶ (backend) ─▶ job collect ─▶ job review ─▶ asset landmark ─▶ render --pin
     ▲                                                                                     │
     └──────────── correction: job request --edit-of vNNN [--paintover] ◀── job verdict ◀──┘
                                                                              │ pass
                                                        job select (guarded) ─▶ compose rebuilds masks
```

## 1. The art request
`mangakit job request <page> --panel <id> --asset <asset-id> --ref <id>[@vNNN] ...` reads the page
source at its current revision and writes `art/jobs/job-NNNN/`:

| File | What it is |
|---|---|
| `request.yaml` | the structured request (schema in project-format.md) |
| `prompt.md` | the same request as a human-readable brief |
| `pack/guide.png`, `pack/guide.json` | shot guide: panel crop, draw area incl. breakout margin, landmarks, reserved lettering, breakouts, min source px for print |
| `pack/rough-crop.png` | the panel's current drawing (rough or old final) resampled to the draw area. No borders, lettering or neighbouring panels. This is the composition reference the backend sees. |
| `pack/context-crop.png` | the art-only page crop over the draw area, with neighbours visible (for people) |
| `pack/refs/<id>@<ver>.*` | copies of the pinned references |
| `pack/edit-source@<ver>.*`, `pack/paintover.*` | for corrections |

What goes into it:
* **Target:** page, panel, beat, page-source sha256, git revision, reading direction.
* **References** pinned by version and sha256. Use the fewest that carry identity and style. A
  multi-pose design sheet invites the backend to paste extra poses (a four-hand result in the demo).
* **Continuity:** beat summary, what the reader knows after the beat, what must stay concealed
  (script `conceal` plus `--conceal`), previous shot's screen direction, transition to the next panel,
  the panel's dialogue for context.
* **Beyond the border:** filled in automatically from the panel's breakouts, as percentages of the
  image and in page units. Add `--beyond` text for anything else.
* **Acceptance criteria:** defaults cover identity/costume, acting at reading size, hands and contact
  point, framing and landmarks, beyond-border coverage, clear lettering zones, screen direction and
  concealment, style, and no text or borders in the image. Replace them with `--accept` (repeatable).
* `--reason` is one of new-shot, correction, extension, design-change or continuity. lettering and
  mask also exist, but only so the metric can count them; they should never be needed.

## 2. Adapters
An adapter translates the common request into what one backend accepts. Capabilities:
`generate`, `edit` (`none`, `reference` = re-draw guided by the source, `masked` = pixel-preserving
inpaint) and `alpha`.

| Adapter | For | `job call` does | Results arrive by |
|---|---|---|---|
| `host` | an image tool the agent calls itself | writes `host-call-<n>.json` with the tool arguments (prompt string, reference paths, aspect ratio, filename; argument names set in `project.yaml`) | `job collect <job> <file> --call n` |
| `manual` | a human illustrator or another agent | points at `prompt.md`, `pack/`, `inbox/` | files dropped in `inbox/`, then `job collect <job> --inbox` |
| `command` | a scriptable backend (CLI or API wrapper) | runs `illustration.adapters.command.run` with `{prompt} {refs} {out_dir} {aspect} {job}` | collected automatically from `out_dir` |

Reference order the host and command adapters send:
* **New shot:** rough crop, then references.
* **Edit:** the source only, then references. The crude rough pulls the style back toward it.
* **Paint-over:** the paint-over only, then references. Never send the unmoved source as well: the
  backend copies the closest reference.

When a backend cannot edit (`edit: none`), the same request runs as a replacement and goes
through the same acceptance check. Either way the result is a new immutable version. Corrections
never overwrite.

No usable alpha back? Composition makes the mask from the drawing (`mask make` with polygons,
`--trim-light-edges`, `--snap`).

## 3. Candidates and review
* `job collect` registers each file as a new **candidate** version of the asset. It is never
  selected. A copy goes to `candidates/<ver>-call<n>.*`, and the call is marked done.
* `job review <job> [--also <job> ...] [--trial label=png]` builds a contact sheet. It shows the
  shot guide, the rough crop, edit sources or paint-overs, and every candidate with its verdict and
  overlays:
  * panel border in blue
  * breakout regions in red
  * layout landmark targets as red +
  * the version's own landmarks as green o

  Once a version has landmarks, the overlay uses its **real placement** from the page source
  (`[placed]`). Before that it assumes the image fills the draw area (`[fill]`).
* Landmark placement check: set the version's landmarks (`asset inspect --grid`, then `asset
  landmark ... --version vNNN`). Then run `mangakit render <page> --pin <asset>=vNNN -o
  .../trial.png` and `mangakit check <page> --pin ...` to see it in the real page without
  selecting it.
* Look at every candidate yourself against every criterion, then record
  `job verdict <job> <ver> --pass|--fail --note "..."`. The note should name the criteria that
  failed, so the next request can fix them.

## 4. Corrections
Write a new request with `--reason correction --edit-of <best version> --instruction "what changes"`.
Keep the instruction local: what moves where, as percentages of the image, and what must stay the same.

The demo found that reference-guided edits handle local fixes (detail, finish, cleanup) but ignore
geometric moves. For moves, make a **paint-over**:
```
mangakit paintover <asset> --version v002 --map <src contact>:<target contact> --map <src cuff>:<target cuff> \
    --cut "<polygon around the moving parts>" --background backdrop.png -o paintover.png
mangakit job request ... --reason correction --edit-of v002 --paintover paintover.png --instruction "keep every part where the guide puts it; finish the sleeves; ..."
```
* `--map` takes two point pairs in source px, and the similarity transform puts both points where
  the layout needs them. Get the targets from `mangakit job targets <job> --size WxH`.
* `--cut` moves only the polygon. The rest of the drawing stays in place, or `--background`
  supplies a clean backdrop (in the demo, the door gap re-tiled from its top rows).
* The paint-over must have no holes, tilted background fragments, or duplicated parts. Backends
  reproduce them.

## 5. Selection and invalidation
`job select <job> <ver>` needs a passing verdict. It calls `asset select --if-current
<base_selection>`, so it refuses if someone selected a different version after the request was
written. It then reports:
* `INVALIDATED mask <name>`: masks registered to the old version. Checks raise `stale-mask` until
  composition rebuilds them with `mask make`.
* `INVALIDATED landmark <name>`: landmarks the old version had and the new one lacks. Page sources
  that align on them fail loudly until they are set.

The job becomes `accepted`. Other jobs for the panel stay `rejected` or `reviewed`, with their
verdicts kept.

## 6. Metrics (spec section 7)
`mangakit metrics` writes `build/metrics.json`:
* illustration calls per accepted panel (all calls across that panel's jobs)
* art calls caused by lettering or mask edits (calls in jobs with reason lettering or mask). This
  should be 0.
* after each acceptance, the mask versions made on the accepted drawing and the art calls made on
  that asset since then. This is evidence that mask and lettering work cost no art calls.

Reference-sheet generation is not a panel call. Record it in the report if a backend made the
references.

## 7. Demo record (p003/handoff, from the full demo project)
(The demo scripts are not part of this repo; `example/` is a text-only cut of the demo.)

| Job | Reason | Calls | Result |
|---|---|---|---|
| job-0003 | new-shot (rough crop + design sheet + style) | 2 | v002: strong drawing, but the cuff was far above the diagonal (fail). v003: copied the crude rough (fail). |
| job-0004 | correction, edit of v002 by instruction | 1 | v004: nothing moved (fail) |
| job-0005 | correction, paint-over (whole image rotated) | 2 | v005: reproduced v002 because the unmoved source was also sent (fail). v006: four hands, from the design sheet (fail). |
| job-0006 | correction, clean paint-over (cut + re-tiled backdrop), style ref only | 1 | v007: pass, accepted |

Composition then made `border-break` m004 to m009 on v007 with zero art calls, and moved the SFX off
the break.
