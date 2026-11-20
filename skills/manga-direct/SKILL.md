---
name: manga-direct
description: Direct a manga project from brief to frozen proof. Read the project's state, derive what is missing or stale as file-backed work units, route each unit to the skill that owns it (manga-story, manga-design, manga-board, manga-illustrate, manga-compose, manga-review) with a context packet that holds only what that shot needs and marks what the reader must not know yet, record every pick and decision, resume interrupted work, and freeze proof sets that rebuild byte for byte. Use for "make a chapter", "fix this on page N", "change this line or fact", "what is left", "continue after a crash", or any request that spans more than one skill. Do not use it to write, draw, letter or review yourself, and never approve a creator gate or pick an editorial alternative for the creator.
---

# manga-direct

You run the production, not the pages. You turn a request into units of work, send each one to the
skill that owns that kind of edit, and keep the record: what was asked, which inputs it was made
from, what came back, and which result was picked. Every request is a change to the project's files.
Your job is to rerun the least work that makes the pages true again, and to stop where the creator
must decide.
Tools: `mangakit` (the toolkit in the mangakit repo; `install.sh` installs it and puts `mangakit` on PATH); `docs/...` below means the repo's docs folder, which `mangakit docs` prints. Unit schema, derivation table,
context packet, resume, gates, decisions, publish and the change table:
`docs/direct-reference.md`. Pack map: `docs/pack-overview.md`. Commands:
`docs/cli.md`.

## Inputs
- The request: a fresh brief, a page-level fix, a change to the script or a story fact, or "continue"
- The project: `story/`, `references/`, `chapters/`, `art/`, `reviews/findings.yaml`, and `work/`
  (units, decisions, gate approvals) if it exists
- The creator's settings and words: `creator.gates` in `project.yaml`, and any approval or editorial
  choice the creator stated. Quote it exactly when you record it.
- A budget if one was given (image calls, time). Put it on the units you schedule.

## Allowed edits
- `work/` through `mangakit work`: units, context packets, decisions, waits, and creator approvals
  recorded from the creator's own words
- `publish/` through `mangakit publish`. Frozen sets are never edited or overwritten.
- Chapter style pins (`style pin`), with a reason. Asset style judgements (`work art-style`) after
  you have looked at the drawing. Withdrawing a job that was never called (`job withdraw`).
- Everything else is done by loading the owning skill and following its rules: story records
  (manga-story), designs and direction revisions (manga-design), layout and roughs (manga-board),
  art jobs and selection (manga-illustrate), placement, masks, lettering and renders (manga-compose),
  findings and verdicts (manga-review).
- Never: approve a gate yourself (`work approve` records only what the creator said), pick an
  editorial alternative, select art that has no passing verdict, or make an image call that is not
  in an `art` or `design-sheet` unit within its budget.

## Routing

| the work is about | route to |
|---|---|
| what happens, who says what, who holds or wears what, when the reader learns something | **manga-story** |
| how a character, prop or place looks, costume variants, the art direction and its scope | **manga-design** |
| pages, panels, reading order, the eye path, page turns, roughs, where balloons go | **manga-board** |
| a drawing for a panel: new shot, correction, extension | **manga-illustrate** |
| placing art, masks and border breaks, lettering fit and reflow, renders | **manga-compose** |
| does it read: cold read, findings, checks, rechecks and verdicts | **manga-review** |
| what runs next, conflicts between skills, style pins, gates, frozen proofs | yourself (manga-direct) |

## Procedure
1. **Plan.** Run `work plan --chapter <ch>` for each chapter the request touches. Then run
   `work status`. The plan compares the story with its last baseline. It folds in design, board,
   asset and review checks and the state of every render, then reports created, stale, reopened and
   cancelled units. Do not invent units the plan does not derive. If a need is missing, the request is
   probably a story or board change: route that first and plan again.
2. **Translate the request into the smallest change, using the change table.** For any edit to a
   line, event, beat or fact, run `story impact <target>` before scheduling anything:
   - Line edit: story → compose reflow → render → review. Reopen the drawing only if the acting
     conflicts.
   - Fact or event edit: story → inspect the panels in its span → schedule art only where a drawing
     shows the old fact.
   - A new costume or look: design sheet first, then re-request any open job (`work wait`).
   - A style change: `style revise` from a chapter or beat. Earlier chapters keep their pins.
   - A sleeve or break change: compose mask first. Commission an extension only if the art runs short.
3. **Next.** Run `work next`. It picks by owner order, then edits before renders, then reading order,
   and writes `work/context/<id>.md`. Load the routed skill and give it the context file. The packet
   holds only:
   - this shot's beat and lines
   - the design variants in effect
   - the style rules and cards that reach it (`out_of_scope_rules` lists the ones that do not)
   - the board notes and focal points
   - the open findings
   - `CONCEALED` facts. These must not appear in words or drawings.
4. **Do and record.** Run `work start <id>`, let the owning skill do the work, then run
   `work done <id> --output <files> [--image-calls N] --note "<what was checked>"`:
   - An inspect unit's note says what you compared and why nothing (or something) is redrawn.
   - A failed attempt is `work block <id> --note`.
   - A choice that affects later work is `work decide`: a pin, keeping older art, or deferring to
     the creator.
5. **Automatic units.** Run `work run` for renders, fit checks and the review recheck. Results are
   saved one unit at a time. After a crash or a kill, run `work resume`. It leaves live workers alone,
   recovers finished outputs, requeues the rest, re-plans, and prints what is still missing or stale.
6. **Findings loop.** After renders, `review recheck` (a unit) marks findings verified, survived or
   needs-verdict:
   - Get each verdict from manga-review, or give it by eye and say so in the note.
   - Findings that survive come back as reopened units for the same owner.
   - Editorial findings stay `needs-creator`. Record "pending creator" with `work decide` and keep
     every alternative possible, for example by not drawing one alternative into new art.
7. **Gates.** With `creator.gates` on, units stop at `needs-creator`:
   - series look: design and direction units
   - lettered boards: art units for the chapter
   - final version: `publish --final`

   Show the creator what the gate covers (lettered spreads, sheets, proof set) and ask. When they
   answer, record it with `work approve <gate> <chapter> --by <creator> --note "<their words>"`.
   The next plan re-queues the units.
8. **Freeze.** Run `publish create <name>` at each milestone the creator will look at. It writes proof
   and reading renders with manifests for every page. Later, `publish rebuild <name>` must report
   ALL BYTE-IDENTICAL. If it does not, the rebuild pins are wrong. Fix the pins; never change the set.
9. **Return.** Report:
   - the units by status before and after
   - what each change reran and its image calls (0 for dialogue)
   - decisions made, and what waits on the creator
   - the publish sets and their rebuild results
   - `work metrics`, `review metrics` and `mangakit metrics`

## Two common requests
**"Make a chapter" from a fresh brief.**
1. **manga-story:** premise, canon, beats with reader knowledge, continuity and script. `story check`
   must be clean.
2. **manga-design:** a sheet per character, prop and place in the beats, then the first direction
   revision, with scope on anything that belongs to one character. Gate: series look.
3. **manga-board:** `board plan --write --stubs`, roughs, lettered boards, and alternates for the
   hardest spread. Gate: lettered boards.
4. **Plan.** `work plan`. Each `needs-art` slot is now an `art` unit.
5. **manga-illustrate → manga-compose, one unit at a time,** with the context packet. Render, then
   `work run`.
6. **manga-review:** a cold read with a fresh reader, then findings become units for their owners.
   Loop until the open findings are only art waits and editorial choices.
7. **Freeze.** `publish create`, and `publish --final` once the creator approves.

**"Fix the last balloon on page 3."**
1. Identify the page and balloon. "Page 3" is a reading position in the chapter, not a page id;
   map it through `chapter.yaml`, as the review packet does. Open the page's proof and its source,
   and find the last balloon in reading order (`board check` prints the lettering order per panel).
2. Decide what is wrong. If the words are wrong, it is a line edit: manga-story changes
   `story/script.yaml`, `story impact <line>` shows what reflows, and the plan creates the reflow and
   render units. If the placement, size or tail is wrong, it is manga-compose (or manga-board if the
   eye path is the problem): edit that balloon only.
3. Run `work plan`. Only that page's renders go stale. Run `work run`, which runs check, render and
   recheck.
4. Look at the spread at reading size, record the unit done with a note, and confirm that
   `publish rebuild` of the last set is still identical. No image call is involved.

## Worked example
Example project: `example/` in the mangakit repo, a text-only cut of the demo this worked example comes from (three-page chapter 01 plus a one-page chapter 02).
```
mangakit publish create proof-001           # freeze the starting proofs
mangakit work plan ; mangakit work plan --chapter 02      # 20 + 5 units: art, findings by owner, renders, recheck
mangakit work next                          # design F019 (SFX size) with its context packet
#   design: style revise sr-003 --base sr-001 --from-chapter 01  (cuff rule scope: [that character]; sfx min 18% of panel)
mangakit style pin 01 --rev sr-003 --note "scope/size fix; render keys unchanged; accepted art stays valid"   # D001
mangakit work art-style hands-at-door@v007 --rev sr-003 --reason "looked: same ink, motif on its owner"      # D002
#   board: move the balloon that blocked the eye path; give the canopy rough structure; review set ... fixed
mangakit work decide F012 --decision "pending creator: no alternative picked" --reason "editorial"            # D003
mangakit work run   # killed with SIGKILL mid-run
mangakit work resume    # interrupted w-0018 -> requeued (no output); all stale: w-0020 w-0028; to do: w-0030 w-0018 w-0028
#   change one line ("...Good luck." -> "...Keep it safe.") and one fact (a costume change in chapter 02)
mangakit work plan      # stale: p003 proof+reading, recheck; new: reletter p003, art inspect, story check (0 image calls)
mangakit work plan --chapter 02             # design-sheet for the missing variant, board/illustrate inspects (no art scheduled)
mangakit publish rebuild proof-001          # ALL BYTE-IDENTICAL (6/6)
#   the reveal panel: one art unit, budget 3 image calls: job-0010 v002 failed (costume, gray wash);
#   job-0011 edit of v002 -> v003 passed; select, landmarks, compose render; F010 verified. 2 calls.
mangakit publish create proof-002 ; mangakit publish rebuild proof-001 ; mangakit publish rebuild proof-002
```
Two lessons from the demo:
- A scoped rule is not enough when a style card image shows the same detail. Scope the card too
  (`{spec, scope}`); the second revision did.
- A proof made while a slot showed its rough must rebuild with the rough. The first rebuild after
  the art landed exposed that, and the rebuild pins now include the slot choice and the landmarks.

## Done when
- `work plan` creates nothing new, and every remaining unit is queued with a reason, waits on another
  unit, or is `needs-creator` with the gate named.
- Every unit you finished carries its outputs, a note on what was checked, and the image calls spent.
  Total image calls are within the budget. A dialogue or lettering change spent none.
- Every pick that affects later work is in `work/decisions.yaml`. No gate was approved, and no
  editorial alternative was picked, without the creator's own words quoted.
- After an interruption, `work resume` lists no running units without a live worker.
- Each publish set rebuilds ALL BYTE-IDENTICAL. The latest set matches the current renders.
- The fixes were rechecked by review, and verdicts given by eye say so in their notes.
