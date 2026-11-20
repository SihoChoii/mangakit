# Direct reference (`mangakit work`, `publish`, `style pin`)

The director keeps a chapter moving. It reads the project, sees what is missing or stale, sends each
piece of work to the skill that owns it with only the context that work needs, and records what was
picked and why. It does not draw, letter or review. The state lives in files, so any agent can pick
the work up where the last one stopped.

## Work units (`work/units/w-NNNN.yaml`)

| field | meaning |
|---|---|
| `id` | `w-0001`… claimed atomically (`O_CREAT|O_EXCL`, max+1), so parallel workers never get the same id |
| `key` | dedupe key of the need, e.g. `render:01:p003:proof`, `art:p004/reveal`, `finding:F011`, `reletter:line-19:p003` |
| `skill` | owner: `direct`, `story`, `design`, `board`, `illustrate`, `compose`, `review` |
| `kind` | `render`, `recheck`, `reletter`, `check`, `inspect`, `art`, `re-request`, `design-sheet`, `fix`, `mask`, `finding`, `decision` |
| `target` | chapter, page, panel, line, beat, finding or `where` |
| `inputs` | the input revisions the unit was planned or finished against (hashes/versions, below) |
| `requested` | the output asked for, in words |
| `status` | `queued`, `running`, `done`, `stale`, `blocked`, `needs-creator`, `cancelled` |
| `after` | unit ids this one waits on |
| `exec` | mangakit argv for automatic units (render, check, recheck); empty for agent units |
| `outputs` | files produced (`work done --output`) |
| `sources` | finding ids it carries |
| `gate` | creator gate that holds it (`series_look`, `lettered_boards`, `final_version`, `editorial`) |
| `image_calls` / `image_calls_used` | expected and spent image calls |
| `origin` | `state` (derived from the project as it is) or `story-change` (derived from an edit; stays until done) |
| `selected` | written by `work next`: when it was picked, against which inputs, and its context file |
| `history` | every status change with time and note; `pid`/`child`/`host` while running |

Writes are atomic (temp file + `os.replace`). A kill leaves the old or the new file, never half of one.
`work/.lock` serialises `plan`, `approve` and `decide`; `reviews/.findings.lock` serialises findings
writes; job and brief ids use the same atomic claim.

### Render input signature
A render unit's inputs are compared with the manifest of the existing output:
`source` (page source sha), `lines` (texts of the lines the page letters), `assets` and `masks`
(versions used), `style` (revision) and `style_render` (its render overrides), `config` (render keys
of project.yaml). If the PNG bytes no longer match the manifest, the unit is stale too. A dialogue edit
changes `lines` on the pages that letter it and nowhere else. A style pin changes `style` (the renders
rerun; the bytes stay the same if no render key changed).

## What `work plan` derives

| source | becomes |
|---|---|
| story diff since `work/baseline-ch<ch>.yaml` — line text | `compose reletter` per page that letters it (exec `check`), `illustrate inspect` (reopen the drawing only if the acting conflicts), `story check`; the renders go stale through `lines` |
| story diff — continuity event or initial state | `story impact <event>`: `board inspect` per panel in the event's span, `illustrate inspect` per drawing or open job, `story check` |
| story diff — beat | `board inspect` of the beat's panels |
| `design check` `design-missing`, `costume-variant-missing`, `design-canon-mismatch`, `view-orphan` | `design design-sheet` (1 image call expected; gate `series_look` if set) |
| `design check` `job-style-superseded` | `illustrate re-request` |
| `design check` `art-style-older` | `direct decision` (redraw or keep, then `work art-style` or a new job) |
| `board check` `needs-art` | `illustrate art` (gate `lettered_boards` until approved for the chapter) |
| `board check` other errors/warnings | `board fix` |
| asset `stale-mask`, `missing-mask`, `mask-dims` | `compose mask` |
| findings `open` (not needs-art) | a unit for the finding's owner; `fixed` findings stay as units waiting for the recheck |
| findings `editorial` | `direct decision`, status `needs-creator`, gate `editorial` |
| stale or missing proof/reading renders | `compose render` (exec), then one `review recheck` after them |

Reconcile rules:
- A `done` unit whose current inputs differ becomes `stale`.
- A `done` unit whose problem still derives with the same inputs is re-queued (`reopened`).
- A queued/stale/blocked `state` unit that no longer derives is `cancelled`. Story-change units are
  never cancelled by a later plan: the baseline moves on, but the edit still needs its follow-up.
- A gated unit stays `needs-creator` until the creator approves the gate for its chapter (or the
  gate is turned off). The next plan then re-queues it.

## Order (`work next`, `work run`)
Order: skill first (`direct`, `story`, `design`, `board`, `illustrate`, `compose`, `review`), then
edits and checks before renders, then page reading order, then id. Only units whose `after` are all
done can run. `work run` executes `exec` units one at a time in that order. Each finishes as `done`
(exit 0, or 1 for a `check`) or `blocked` (log in `work/logs/<id>.log`). Agent units are left for
`work next`.

## Context packet (`work next`, `work context <id>`)
Written to `work/context/<id>.md` and recorded on the unit (`selected`). It holds only what the target
needs:
- `story`: the beat, its summary and location, the beat's lines, continuity before and after (only
  for who and what is in the shot), what the reader knows and suspects, and `CONCEALED`: every fact
  the reader must not learn yet, with the beat that reveals it
- `design`: the variant spec each present character or prop wears at that beat (`design_for`)
- `style`: the effective revision, the rules and cards that reach this shot, and
  `out_of_scope_rules` (scoped rules or cards that were left out, e.g. one character's cuff)
- `board`: the panel note, its page share, focal points, and the art in the slot
- `findings` on that page and panel, the `finding` record for finding units, file paths, and the
  `route` (which skill to load)

## Resume (`work resume`)
1. Each `running` unit is checked. If its worker or child pid is alive on this host it is left alone
   (`still_running`).
2. A dead render whose output exists and matches its current inputs becomes `done` (`recovered`).
   Anything else is re-queued (`requeued`).
3. Then the director re-plans, which adds missing units and marks stale ones.
4. The report lists interrupted, recovered, requeued, missing, newly stale and all stale units, units
   waiting on others, and what runs next (automatic vs agent).

## Creator gates
`project.yaml`:
```yaml
creator:
  gates: {series_look: true, lettered_boards: true, final_version: true}
```
`work approve <gate> <chapter> --by <creator name> --note "<their words>"` appends to
`work/gates.yaml`. It refuses `--by direct|agent|director` and an empty note. The director runs it only
to record an approval the creator gave in words, quoting them. `publish --final` refuses while
`final_version` is on and not approved. Editorial findings are a gate of their own. Record a
"pending creator" decision and leave every alternative open.

## Decisions (`work/decisions.yaml`)
`work decide <subject> --decision --reason [--refs]` is append-only (`D001`…). `style pin` and
`work art-style` write one automatically. Record a decision for every choice that affects later
work: a chapter re-pin, keeping older art under a new revision, a request withdrawn before any call,
or deferring an editorial choice.

## Style controls
- `style revise <id> --base <rev> --from-chapter|--from-beat --rules file.yaml`: append-only; earlier
  unpinned chapters are pinned to what they had.
- `style pin <chapter> --rev <rev> --note <reason>`: re-pin a chapter (logs a decision).
- A rule may carry `scope: [canon ids]`, and so may a card (`{spec, scope}`). A scoped rule or card
  reaches only the shots that show one of those characters. A card image that shows one character's
  costume must be scoped like a rule, because a picture leaks even when the text does not.
- `work art-style <asset@ver> --rev <rev> --reason`: the director looked at the drawing and it meets
  the revision. This clears `art-style-unrecorded` and `art-style-older` for that revision.
- `job withdraw <job> --note`: close a request that will not be called (for example, its brief pinned
  a superseded revision).

## Frozen proof sets (`publish`)
`publish create [name] [--final] [--note]` renders proof and reading for every page into
`publish/ch<ch>/<name>/<page>/`, writes manifests and `set.yaml` (shas, styles, asset versions, check
errors), and makes the files read-only. It never overwrites a set. `publish rebuild <name>` re-renders
each manifest into `build/rebuild/…` and compares the bytes. A rebuild pins:
- the page source, script and project.yaml snapshots
- asset and mask versions, and whether a slot showed its rough or its final
- the landmarks the proof used
- the style revision and its render overrides

The set rebuilds byte-identical after later edits to the text, layout, landmarks, art selection or
style.

## The change table

| change | what reruns | art calls |
|---|---|---|
| shorten or rewrite a line | `story check`, `compose reletter` (fit, overlap, focal checks) on the pages that letter it, those pages' renders, `review recheck`, and an `illustrate inspect` that reopens the drawing only if the acting conflicts | 0 |
| let a sleeve break farther | `compose mask` edit (overlap and mask), render; commission an `extension` job only if the art does not reach | 0, or 1 extension |
| give an object to a different person | the event in `story/continuity.yaml`; impact on the event's span: `board inspect` per panel, `illustrate inspect` per drawing or job, `story check`; schedule art only for drawings that depict the old holder | after inspection only |
| change a costume mid-script | a continuity event: `design design-sheet` for the missing variant, `board/illustrate inspect` on the span, re-request open jobs after the variant exists (`work wait`) | design sheet first |
| heavier ink from chapter N | `style revise` with `--from-chapter N`; earlier chapters keep their pins; open jobs for N become `re-request` | per redrawn panel |
| a review finding | a unit for the finding's owner; after the fix, `review set --status fixed`, renders, `review recheck`, verdicts | depends on the owner |
| an editorial alternative | `needs-creator`; the director records "pending creator" and never picks | 0 until picked |
