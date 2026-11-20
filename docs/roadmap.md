# What later skills build on (and current gaps)

Built (milestone 1): project scaffold, asset/mask/landmark/job registry, page API, renderer
(proof, rough, guide, masks, reading, detail, export, spread, contact), technical checks, manifests
+ byte-exact rebuild, pinned OFL fonts, vendored resvg 0.49.0.

Built (milestone 2): reference registry, art requests from a panel (pack with shot guide, clean rough
crop, pinned references, continuity, beyond-border regions, acceptance criteria), adapters (host,
manual, command), call log + candidate storage per job, review contact sheet with placement
overlays, trial renders with `--pin`, verdicts, guarded `job select`, mask/landmark invalidation
reports, paint-over helper for corrections, `mask make --snap`, `art-resolution` check, frame-flush
rule in `breakout-cut`, pilot metrics.

Built (milestone 3): story records (premise, canon, beats with reader knowledge, typed script lines,
continuity events, threads), `story check` (setup/payoff/sequence, leaks, continuity, speakers,
page cross-checks, page-turn reveals), dependency map from beats/lines/facts to panels, balloons,
SFX, art and jobs, `story impact` with hypothetical `--text`/`--set`, `story glance` beat sheet,
per-chapter spread pairing, SFX lines lettered from the script, story context in art requests.

Built (milestone 4): design identities (character, costume, prop, environment, world) with
variants, versions, canon links and named views (`id[:variant][@vNNN][#view]`). Costume variants are
chosen from continuity (`design for`, `job request --design`). Design briefs log their image calls.
`references/direction.yaml` holds art-direction revisions: rules with style cards, scope, and render
settings merged per chapter and recorded in manifests. `style revise` pins earlier chapters. Requests
auto-pin the effective cards as one montage reference. Also added: sample-shot test at reading size
with a judgement table, the `design check` codes (missing or mismatched designs, superseded job
styles, art under an older revision), and the markdown guide export.

Built (milestone 5): layout helpers (gutter-aware rows/cols/grid, diagonal cuts, insets, bleed,
borderless panels, breakout regions toward a neighbour), all respecting reading direction and page
side; procedural `rough` assets with landmarks, focal points, sightlines and camera notes (no image
calls), carried into the shot guide and requests; `board plan` (beats to pages/panels with stable
ids, reveals after a turn, retired ids); `board check` (zigzag panel order, balloon order, focal
points per panel, reveal timing, balloon area); alternates with compare renders and id-safe
promotion; lettered rough pages, spreads and page-turn strips.

Built (milestone 6): findings in `reviews/findings.yaml` tied to page revisions (sha of the clean
reading render) with owner, status, crops, probes and survived-a-revision tracking; editorial
findings keep their alternatives; cold-read packets with no metadata, a fixed questionnaire, locked
answers, an answer key and `review score` against beats, continuity and reader knowledge; `review
tech` merging story/design/board/compose checks with owners; the art-vs-story sheet; `review
recheck` (verified, survived, needs-verdict) and pilot metrics.

| Skill | Uses | Gaps to close there |
|---|---|---|
| manga-illustrate (built) | `job request/call/collect/review/verdict/select`, `ref`, `paintover`, `render --pin`, `metrics` | automatic landmark proposal; upscale/cleanup pass to print resolution; masked inpainting adapter; alpha-returning backend; per-criterion structured verdicts |
| manga-board (built) | `layout`, `rough make`, `board plan/check/render/alt/compare/promote`, `art.slot` | plan cannot insert panels into drawn pages (it reports them); reading order across staggered tiers is heuristic (use `order=` and expect `panel-order`); crowding uses balloon area, not text legibility; no automatic layout search; final art must reuse rough landmark names or balloon tails break; rough figures are blocking only (no perspective solve) |
| manga-story (built) | `story check/impact/glance/state/deps` | leak detection is keyword-based (no paraphrase detection); the timeline is per beat, not per panel; no multi-chapter canon merge; no PNG beat sheet |
| manga-design (built) | `ref`, `design`, `style`, `job request --design` | no auto-crop for views (boxes are hand-set); no check that drawn art matches the sheet (needs a reviewer or vision); SFX size rule is advisory (no size-relative-to-panel check); no lint for character-specific words in unscoped rules; type settings switch per chapter, not per beat; sheets arrive about 1280x720 with no upscale |
| manga-review (built) | `review packet/answers/key/score/tech/art/add/set/editorial/decide/verdict/recheck/list/metrics` | no fresh reader in a single-agent run: the agent's own blind read is contaminated when it built the pages; eye path, partial reveals and art-vs-story need a human or vision judgement (`judge:`, verdicts); speaker matching is word-based (a paraphrased answer can miss); probes cover tails, SFX size and check keys only; a recheck re-read needs a new reader for `--pages` packets |
| manga-direct (built) | `work plan/status/next/context/start/done/run/resume/wait/approve/decide/art-style/metrics`, `publish`, `style pin`, `job withdraw` | derivation is per chapter and scans everything each time (about 2-10 s on the demo); no cost model or budget field on units beyond `image_calls`; units are not merged across chapters (a project-wide design unit appears in both plans); `work run` is sequential (no worker pool, though ids and writes are safe for parallel workers); a story-change unit's "inspect" is a judgement recorded in a note; no second host adapter was needed (the host adapter covered generate and reference-guided edit) |

Known technical gaps
* Metrics key panels as `page/panel`, which is ambiguous across chapters (two `p001/arrival`).
* Horizontal Latin lettering only: no vertical Japanese text, no CJK font pinned yet, no hyphenation.
* Kerning comes from HarfBuzz; there is no optical margin or per-glyph manual kerning.
* Balloon shapes: ellipse, rect, box, cloud, burst, custom path. No double/linked balloons yet
  (place two and connect them with `page.raw` or a custom union path).
* Raster-check thresholds (`mask-halo`, `mask-slices-ink`) were tuned on clean ink art; noisy scans
  may need adjustment.
* `rebuild` pins the slot choice (rough vs final) and the landmarks a proof used (milestone 7 fix: a
  proof made while a slot showed its rough used to rebuild with the later final art).
* `rebuild` is exact for the same mangakit + resvg + fonts. The manifest records the mangakit version
  string, not a code hash.
* No PDF/TIFF export, trim marks or CMYK; exports are PNG (L or RGB) with dpi metadata.
* Demo: p003/handoff is generated art (v007); the other pages are still procedural stand-ins, so the
  chapter mixes styles until they are commissioned.
* Generated art arrives at 1152x864 (about 150 dpi as placed); `art-resolution` warns. No upscale
  or vectorize step exists yet.
* `mask-slices-ink` cannot tell sliced linework from background art that touches an outline (a door
  edge right under the envelope in the demo); such warnings must be explained by eye.
* The host image tool's "edit" is a re-draw guided by references, not a pixel-preserving inpaint:
  it ignored geometric instructions and copied the closest reference. Moving parts needs a paint-over.
