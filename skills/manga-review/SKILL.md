---
name: manga-review
description: Review a rendered manga chapter the way a reader meets it. Run a cold read of the unannotated pages first (who spoke, what changed hands, where the eye went, what surprised, when the reveal landed), then compare it with the intended beats, continuity and references, run the technical checks together, and check the art against the story. File specific findings with location, crop, evidence, severity and the stage that can fix them, tied to the page revision, and recheck affected pages in sequence after fixes to mark findings verified or survived. Use when a chapter or spread has been rendered and needs a verdict, after fixes to confirm them, when a drawing may contradict the story, or when reviewers disagree on an aesthetic choice. Do not use it to fix anything: owners fix (story, design, board, illustrate, compose) and the director decides.
---

# manga-review

You are the reader and the critic. You read first and judge second. The cold read comes before
anything that tells you what the pages are meant to say. Then you compare it with the intent and
turn every gap into a finding someone can act on: what was read, what was meant, where on the page,
the evidence, and who can fix it. You do not fix anything yourself. Every finding is tied to the
page revision it was seen on, so a recheck can tell a verified fix from a finding that survived.
Tools: `mangakit` (the toolkit in the mangakit repo; `install.sh` installs it and puts `mangakit` on PATH); `docs/...` below means the repo's docs folder, which `mangakit docs` prints. Packet rules, questionnaire, key,
scoring, owners, findings schema and recheck table: `docs/review-reference.md`.
Commands: `docs/cli.md`.

## Inputs
- A rendered chapter: the page sources and art that `mangakit` renders. Read only the clean reading
  views during the cold read.
- After the cold read: `story/` (beats, reader knowledge, continuity, script), `references/`
  (designs, direction), `chapters/<ch>/board.yaml`, and page metadata (manifests, check output)
- Existing `reviews/findings.yaml` and earlier rounds, for rechecks
- A fresh reader if one is available: a person, or a helper agent that has not opened the project

## Allowed edits
- `reviews/`: packets, answers, keys, scores, art-vs-story sheets, findings, verdicts and recheck
  output, through `mangakit review`. Answers are locked once recorded. Never edit them after
  opening the story.
- Finding status only through `review set`, `editorial`, `decide` and `verdict`, always with a note.
  `decide` belongs to the director or editor. You record alternatives; you do not pick.
- Do not edit story records, references, page sources, lettering, art, masks or jobs. If a fix is
  obvious, write it into the finding's `intended` and give it to the owner.

## Procedure
1. **Packet.** Run `review packet`. Check that it holds only spreads, page-turn cards, single pages, the
   questionnaire and the answers template; the leak check refuses ids.
2. **Cold read.** Give the packet to a fresh reader. If there is none, read it yourself:
   - Open only the packet images: the spreads at reading size, then `pages/` at 100%.
   - Answer every question in your own words and labels, marking guesses with `?`.
   - Write down what you could not read.
   - Run `review answers <file>` before you open any story file. Set `reader:` and a `note:` that
     says how fresh the read was.
3. **Key.** Run `review key`, then open the story and write `key.yaml`:
   - `identify` every label the reader used.
   - `triage` each unclear item with an owner, page, panel or region, and what was intended. Give it a
     `probe` when there is a measurable proxy, or a `key` to merge it into an existing finding.
   - `judge` the eye paths against the board's focal order, and any reveal that was only half read.
4. **Score.** Run `review score` and read `score.md`. A reveal that is read late or early, a missed
   transfer, or a wrong speaker is a finding even if every check passes.
5. **Technical pass.** Run `review tech`. Triage the output:
   - Mark accepted known issues `wont-fix` with the reason and its evidence.
   - Every `needs-art` becomes an illustrate finding.
   - An intentional overlap must be a declared breakout. Otherwise it is an accidental clip.
6. **Art vs story.** Run `review art` and look at each crop beside its facts: holder, costume, who is
   present, place. Write `ok: false` verdicts for contradictions and run `review art --verdicts`. When
   the drawing and the story disagree, say which side you think is wrong. The director resolves it.
7. **Your own eye.** Use `review add` for anything else, such as a direction rule that does not hold or
   type that does not read at reading size, with a region and evidence. Taste disagreements go to
   `review editorial` with at least two alternatives and their owners.
8. **Recheck after fixes.** Owners mark fixes with `review set <id> --status fixed --note`. Run
   `review recheck`:
   - Probed findings verify or survive on their own.
   - For each `needs-verdict`, open its before/after image and run
     `review verdict <id> verified|survived --note`.
   - When the fixes change how the pages read, cold-read the affected spreads again with
     `review packet --pages ...` and a new reader.
9. **Return.** Report:
   - the packet path, the answers and the score
   - findings by owner, with crops
   - editorial findings with their alternatives
   - the recheck table
   - `review metrics`, including findings that survived a revision, and how fresh the reader was

## Worked example
Request: "Review chapter 01 and confirm the cheap fixes." Example project: `example/` in the mangakit repo is a text-only cut of the demo this worked example comes from.
```
mangakit review packet                 # r01: 01-spread [pages 1,2] | 02-page-turn | 03-spread [page 3]
#   read the packet only; answers.yaml written and recorded before opening story/
mangakit review answers reviews/ch01/cold/r01/answers.yaml
mangakit review key                    # identify runner=rin, cuff hand=rin, train hand=saeki, coat man=saeki
mangakit review tech                   # 10 findings: needs-art x6 (illustrate), sfx-small (compose), art-resolution ...
mangakit review score                  # 15/17: speakers 10/10, transfer 1/1, holder 1/1, eye path 2/3, reveal 0/1
#   reveal partial: the face lands right after the turn, but nothing says he is a detective -> editorial
mangakit review art --verdicts reviews/ch01/art-story/verdicts-r01.yaml   # doors-closing: no envelope in Rin's hands
mangakit review editorial F012 --alt "name-in-script|story|..." --alt "badge-in-art|illustrate|..." --alt "keep-anonymous|story|..."
#   board lengthens the line-02 tail; compose enlarges TAP TAP TAP; both: review set <id> --status fixed --note ...
mangakit review recheck                # F003 sfx verified, F014 tail verified (probe), needs-art x3 on p002 survived
mangakit review verdict F011 survived --note "balloon still sits between Rin and the door"
mangakit review metrics
```
A lesson from the demo: every check passed and the reveal landed after the turn, but the cold
reader still could not say who the man was. A page that renders cleanly is not a page that reads.

## Done when
- A cold read was recorded before the story was opened, and its freshness is stated. Every scored
  question has a result, and every mismatch and unclear item is a finding or a written drop.
- `review tech` ran, and each error and warning is a finding or a wont-fix with a reason. Every panel
  was checked against its asserted facts on the art-vs-story sheet.
- Every finding has observed and intended readings, a page (and panel or region where it applies), a
  crop, evidence, severity, an owner, and the revision it was filed on. Editorial findings keep at
  least two alternatives.
- After fixes, `review recheck` ran on the affected pages in reading order. Every fixed finding is
  verified or survived, by probe or by a verdict with a note.
- `review metrics` was reported. No story record, reference, page source, art or job was edited by
  this skill.
