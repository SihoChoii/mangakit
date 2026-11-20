# mangakit CLI

Run inside a project (or pass `-C <project>`). Page refs are ids (`p003`, resolved in the active
chapter) or paths to a page source. Every render prints the PNG path and its manifest path, then any
check issues. Exit code 2 = error.

## Project
| Command | Does |
|---|---|
| `mangakit init <dir> [--title T] [--direction rtl\|ltr] [--language en] [--trim-mm 182x257] [--bleed-mm 3] [--dpi 600]` | scaffold project, copy + pin kit fonts |
| `mangakit info` | settings summary, chapter pages, font pin verification |
| `mangakit hash <path>...` | sha256 of files/dirs (prove art bytes did not change) |

## References (design sheets, style exemplars, props; see design-reference.md)
| Command | Does |
|---|---|
| `mangakit ref add <id> <file> --kind character\|costume\|prop\|environment\|world\|design\|style\|source\|pose\|other [--identity I] [--variant V] [--canon C[,C2]] [--note N] [--no-select]` | register an immutable reference version (selected unless `--no-select`) |
| `mangakit ref list` / `ref show <id>` / `ref select <id> <vNNN>` | registry summary (canon, variants, views) / record / switch version |
| `mangakit ref view <id> <name> --box x0,y0,x1,y1 [--version vNNN] [--note N]` | name a crop of one version (single-view pinning) |
| `mangakit ref meta <id> [--canon C] [--identity I] [--kind-meta K]` | edit identity fields (not versions) |
| `mangakit ref resolve 'id[:variant][@vNNN][#view]'` | what a spec pins (version, view box, sha256, file) |

## Design and art direction (see design-reference.md)
```
mangakit design check [--json] [--strict]                            design + direction + job style checks; exit 2 on errors
mangakit design brief <id> --kind K --prompt "..." --layout turnaround|details|single|prop|environment|card [--ref spec]... [--canon C] [--variant V] [--aspect 16:9]
mangakit design collect <id> <bNNN> <image> [--no-select]            add the generated sheet as a version, log the call
mangakit design recall <id> <bNNN>                                   log a failed/unusable call before retrying
mangakit design calls                                                image calls per reference
mangakit design for <canon-id> [--beat B] [--view V]                 design spec in effect (costume variant from continuity)
mangakit design guide [-o build/design/direction.md]                 markdown art-direction guide
mangakit design sample --image <spec|asset|file> [--revision R | --compare R1,R2] [--line T] [--sfx T] [--sfx-at fx,fy] [--line-at fx,fy] [--box x,y,w,h] [-o dir]
mangakit style list | style show <rev> [--chapter C --beat B]       revisions, effective starts, pins / merged rules
mangakit style revise <new> --base <rev> (--from-chapter C | --from-beat B) --rules rules.yaml [--note N] [--no-pin]
mangakit style pin <chapter> --rev <rev> --note "reason"            re-pin a chapter; logs a decision in work/decisions.yaml
```
`job withdraw <job> --note "..."` closes a request that will not be called (status `withdrawn`).
`job request` adds `--design <canon-id>[#view]` (repeatable; the costume variant comes from continuity at
the panel's beat) and `--no-style` (skip auto-pinned direction cards).

## Story (see story-reference.md)

```
mangakit story check [--chapter 01] [--json] [--strict] [--no-pages]   exit 2 on errors
mangakit story glance [-o build/story/glance.md]                       beat sheet with reader knowledge
mangakit story impact <line-id|beat-id|event-id|subject.attr> [--text "new wording"] [--set new-value] [--json]
mangakit story state <beat-id>                                         continuity state + reader knowledge after a beat
mangakit story deps                                                    JSON dependency map (beats, lines -> panels, balloons, SFX, art, jobs, renders)
```

## Illustration jobs (see illustrate-reference.md)
| Command | Does |
|---|---|
| `mangakit job request <page> --panel P --asset A [--ref id[@vNNN] ...] [--reason new-shot\|correction\|extension\|design-change\|continuity] [--adapter host\|manual\|command] [--prev-direction T] [--transition T] [--conceal T ...] [--beyond T] [--accept T ...] [--notes T] [--style T] [--aspect R]` | art request from a panel: `request.yaml`, `prompt.md`, `pack/` (shot guide PNG+JSON, rough crop, context crop, pinned refs) |
| `... --edit-of vNNN --instruction "what changes" [--paintover guide.png]` | correction of an existing version: the backend gets that source (or the paint-over made from it) as image 1 |
| `mangakit job call <job> [--note N]` | log one backend call and prepare it: `host` writes `host-call-<n>.json` (tool arguments), `manual` points at `inbox/`, `command` runs the configured backend and collects its outputs |
| `mangakit job collect <job> <file>... [--call n] [--inbox]` | store returned images as candidate versions (never selected) + copies in `candidates/` |
| `mangakit job review <job> [--also <job> ...] [--trial "label=png" ...] [-o out.png]` | contact sheet: shot guide, rough crop, edit sources, every candidate with verdict, overlays (panel border, breakout regions, landmark targets; real placement when the version has landmarks), trial page renders |
| `mangakit job verdict <job> <vNNN> --pass\|--fail --note "criteria notes"` | record the acceptance decision per candidate |
| `mangakit job select <job> <vNNN> [--force]` | select a passing candidate, guarded by the job's `base_selection` (refuses if the selection moved); prints INVALIDATED masks and landmarks |
| `mangakit job targets <job> [--size WxH]` | layout landmarks, breakout boxes and panel border in image px (image filling the draw area): the target points for `paintover --map` |
| `mangakit job show <job>` / `job list` | job record / all jobs with reason, panel, calls, candidates, accepted |
| `mangakit job new <asset> --text "brief"` | bare job without a request (legacy) |
| `mangakit paintover <asset> --version vNNN --map sx,sy:tx,ty --map sx,sy:tx,ty [--cut poly] [--background img] -o out.png` | move a drawing (or only the `--cut` polygon) with a 2-point similarity: a paint-over guide for corrections a backend cannot make from words |
| `mangakit metrics [--json]` | pilot metrics: illustration calls per accepted panel, art calls caused by lettering/mask edits, mask versions and art calls after each acceptance; writes `build/metrics.json` |

## Assets, landmarks
| Command | Does |
|---|---|
| `mangakit asset add <asset> <file> [--job J] [--note N] [--select]` | register an immutable new version (candidate unless `--select`) |
| `mangakit asset select <asset> <vNNN> [--if-current vMMM]` | select a version (refuses if `--if-current` no longer holds); prints INVALIDATED masks and landmarks not set on the new version |
| `mangakit asset landmark <asset> <name> <x> <y> [--version V] [--protect]` | landmark in source px for that version; `--protect` = balloons must not cover it |
| `mangakit asset list` / `asset show <asset>` | registry summary / full record + validation |
| `mangakit asset inspect <asset> [--grid 100] [--crop x0,y0,x1,y1] [-o out.png]` | drawing with a labelled source-px grid + landmarks (pick coordinates from this) |

## Masks (source-image coordinates)
| Command | Does |
|---|---|
| `mangakit mask make <asset> <name> --polygon "x,y x,y ..."\|file.yaml [--polygon ...] [--subtract ...] [--from-png alpha.png] [--trim-light-edges [T]] [--bg-seed x,y] [--snap N] [--grow N] [--feather PX] [--version vNNN] [--note N]` | build + register a new mask version for the selected drawing, select it, write a preview |
| `mangakit mask preview <asset> <name> [mNNN] [-o out.png]` | source + mask edge / cut-out over magenta / mask alone |
| `mangakit mask select <asset> <name> <mNNN>` | switch mask version |

Polygons are unioned. `--trim-light-edges` floods away paper pixels (>= T, default 200) connected
to the polygon edge, or only those connected to `--bg-seed` points (use seeds when the polygon edge
crosses light interior areas that must stay opaque). `--snap N` then peels up to N px of paper off
the mask edge, stopping at ink: use it on thin-lined art (generated or scanned) so a hand-traced
polygon leaves no paper margin. The recipe is stored with the mask.

## Rendering
| Command | View |
|---|---|
| `mangakit render <page>` | `proof`: full bleed canvas + trim/safe guides, proof dpi |
| `mangakit render <page> --view rough` | lettered rough: art faded, panel ids/order/beats, balloon order numbers, breakout zones hatched |
| `mangakit render <page> --view guide --panel <id>` | shot guide PNG + JSON for the illustrator (crop, draw area incl. bleed/break margin, landmarks, reserved lettering, breakouts, min source px for print) |
| `mangakit render <page> --view masks` | all non-break layers at 25 % over magenta, break layers opaque, panel (cyan) and breakout (yellow) outlines |
| `mangakit render <page> --view reading [--height PX]` | trim-only page at reading size |
| `mangakit render <page> --view detail --region x0,y0,x1,y1 [--dpi 1200]` | full-size crop in page units (seams, hands, lettering) |
| `mangakit render <page> --view export [--profile print\|web] [--force]` | final file at profile dpi/mode with or without bleed; refuses on check errors |
| `mangakit spread [<page>\|all]` | spread(s) per `spreads.pairing`, earlier page on the right for rtl |
| `mangakit contact` | chapter contact sheet in spread order |
| `--pin asset=vNNN` / `--pin asset:mask=mNNN` | render (or `check`) with a candidate pinned instead of the selection: trial placement without selecting |
| `-o <file>` | write elsewhere (manifest goes next to it). Use unique names when an image viewer caches by path. |

## Checks and rebuild
| Command | Does |
|---|---|
| `mangakit check [<page>\|all] [--strict] [--json]` | technical checks (exit 2 on errors; 1 on warnings with `--strict`) |
| `mangakit rebuild <manifest.json> [-o out.png]` | re-render from the manifest's snapshots + pinned versions; prints `identical to recorded output: YES/NO` |

### Check codes

Story check codes (`mangakit story check`) are listed in story-reference.md.
| Code | Severity | Meaning |
|---|---|---|
| `missing-asset`, `missing-mask`, `missing-dialogue` | error | reference does not resolve |
| `asset-modified` | error | registered bytes changed on disk |
| `stale-mask` | error | mask registered to another drawing version |
| `mask-dims` | error | mask size != source size |
| `font-pin` | error | font file missing or sha256 differs from project.yaml |
| `text-overflow` | error | a line's ink box leaves the balloon interior |
| `breaks-mismatch` | error | page line breaks do not spell the script text |
| `balloon-off-trim` | error | balloon crosses trim |
| `breakout-cut` | error | masked silhouette outside the panel is chopped by its allowed region (art beyond a frame edge that no breakout crosses is cut by that edge's own line and is not counted: an arm leaving frame at the side) |
| `undeclared-clip` | warn | image clipped to something that is neither a panel nor declared breakout(s) |
| `breakout-intrudes` | warn | breakout region covers another panel not listed in `over=` |
| `mask-slices-ink` | warn | ink just outside the visible mask edge (cut linework) |
| `mask-halo` | warn | visible mask edge is paper (margin shows over gutter/neighbor art) |
| `art-gap` | warn | panel art does not cover the panel |
| `art-resolution` | warn (< 50 % of print dpi) / info | placed drawing's effective dpi is below the print profile |
| `balloon-outside-safe`, `text-off-trim` | warn | lettering near/over the edge |
| `balloon-covers-landmark` | warn | balloon covers a `--protect` landmark |
| `balloon-overlap` | warn | balloons overlap |
| `reading-order` | warn | spatial balloon order (panel order, rows, reading direction) != script order |
| `unlettered-line` | warn | a script line of a beat on this page has no balloon |
| `breakout-empty` | info | masked layer never leaves the panel |

Design codes (`design check`): design-missing, design-canon-mismatch, design-kind, design-unassigned,
costume-variant-missing, view-orphan, style-base-missing, style-no-start, style-rule-kind,
style-render-key, style-card-missing, style-pin-missing, unknown-beat, job-style-superseded,
art-style-older (flag only), art-style-unrecorded. See design-reference.md.

## Board (milestone 5)
```
mangakit rough make [id] [source] [--note N]   # render art/roughs/<id>.py (all when id omitted); kind=rough, no image call
mangakit rough list
mangakit board plan    [--chapter C] [--per-page N] [--write] [--stubs] [--json]
mangakit board check   [--chapter C] [--alt NAME] [--all] [--json] [-o FILE]
mangakit board render  [--chapter C] [--alt NAME]          # build/<ch>/board/<set>/
mangakit board alt <pid> <name> [--from OTHER]             # copy page source to <pid>.alt-<name>.py
mangakit board alts
mangakit board compare current,b,c [-o FILE]
mangakit board promote <name|current> --reason "..." [--dry-run] [--force]   # exit 2 when blocked
mangakit render <pid> --view rough --alt <name>
```
Board codes: page-broken, panel-id-duplicate, beat-not-boarded, line-not-lettered,
reveal-on-facing-page (errors); reveal-without-turn, reveal-not-first-after-turn, beat-order,
panel-order, balloon-order, balloon-beat, balloon-outside-panel, lettering-outside-panels,
panel-too-small, focal-covered, retired-id-reused, plan-panel-missing, plan-panel-moved,
plan-unplanned-panel (warnings); panel-crowded, no-focal, sightline-against-flow, bleed-inside,
needs-art (info). See board-reference.md.

## Review (milestone 6)
```
mangakit review packet  [--chapter C] [--pages p002,p003]      # reviews/ch<C>/cold/rNN/packet/
mangakit review answers <answers.yaml> [--round rNN]           # record + lock
mangakit review key     [--round rNN]                          # key.template.yaml
mangakit review score   [--round rNN] [--force] [--no-file]
mangakit review tech    [--no-file]
mangakit review art     [--verdicts verdicts.yaml]
mangakit review add --observed "..." --owner O [--intended] [--page P --panel N --region x0,y0,x1,y1]
                    [--code C] [--severity S] [--title T] [--evidence E ...] [--probe JSON] [--key K]
mangakit review set <id> --status open|fixed|verified|wont-fix|editorial --note "..." [--owner O]
mangakit review editorial <id> --alt "name|owner|description" --alt ... [--note]
mangakit review decide <id> <alternative> --reason "..."
mangakit review verdict <id> verified|survived --note "..."
mangakit review recheck
mangakit review list [--status s1,s2] [--owner o1,o2] [--json]
mangakit review metrics [--json]
```
Review codes: cold-speaker, cold-order, cold-missed-line, cold-transfer, cold-transfer-missed,
cold-holder-end, cold-eye-path, cold-reveal, cold-reveal-missed, cold-reveal-early, cold-reveal-late,
cold-reveal-partial, cold-reveal-flat, cold-unclear, art-contradicts-story, sfx-small, plus every
check code through `review tech`. See review-reference.md.

## Direct: work units, gates, decisions, frozen proofs (milestone 7; see direct-reference.md)
```
mangakit work plan    [--chapter C]        derive needs, reconcile with work/units (created / stale / reopened / cancelled)
mangakit work status  [--all]              counts + open units
mangakit work next    [-q]                 pick the next runnable unit, write work/context/<id>.md, record the selection
mangakit work context <id>                 print a unit's context packet (CONCEALED facts, scoped style, design variants)
mangakit work show <id>
mangakit work start <id> | done <id> [--output F ...] [--note] [--image-calls N] | block <id> --note
mangakit work wait <id> --refs <id> ... [--note]   add dependencies
mangakit work run     [--limit N] [--skill S]      execute automatic units (render, check, recheck) in order, saving each
mangakit work resume  [--chapter C]        after an interruption: recover / requeue dead running units, re-plan, list what is left
mangakit work approve <gate> <chapter> --by <creator> --note "<their words>"   record a creator approval (never by the director)
mangakit work decide <subject> --decision "..." --reason "..." [--refs ...]
mangakit work art-style <asset@ver> --rev <rev> --reason "..."   the drawing was looked at and meets the revision
mangakit work gates | metrics
mangakit publish [create] [name] [--final] [--note]   freeze proof + reading per page into publish/ch<C>/<name>/
mangakit publish rebuild <name> [--chapter C]         rebuild from the frozen manifests, compare bytes (exit 1 if any differ)
mangakit publish list
```
