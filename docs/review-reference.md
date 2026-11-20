# Review reference

Review reads the rendered chapter the way a reader does, then compares that reading with what the
story, references and board intended. Every mismatch becomes a finding with a location, evidence,
and the stage that can fix it. Review never fixes anything itself; owners fix, review rechecks.

## Order of work
1. `review packet`: a cold-read packet. Give it to a reader who has not seen the project.
2. The reader fills `answers.yaml` from the packet only. `review answers <file>` records and locks it.
3. `review key` writes `key.template.yaml`. With the story open, write `key.yaml`: who each of the
   reader's labels is, triage of the unclear items, and judgements of free answers.
4. `review score`: compares the answers with the intended reading and files findings.
5. `review tech`: story, design, board and compose checks plus review measurements in one pass.
6. `review art`: the art-vs-story sheet. Look, then `review art --verdicts <file>`.
7. `review add` for anything else seen by eye; `review editorial` for choices with alternatives.
8. Owners fix; each fix is marked `review set <id> --status fixed --note "..."`.
9. `review recheck`: re-renders the affected pages in reading order with their spreads, re-runs every
   machine check, and lists what is verified, what survived, and what needs a verdict.

## Files
| Path | What |
|---|---|
| `reviews/findings.yaml` | every finding (schema below) |
| `reviews/ch<ch>/cold/rNN/packet/` | what the reader gets: `NN-spread.png`, `NN-page-turn.png`, `pages/<n>.png`, `questionnaire.md`, `answers.yaml` (template) |
| `reviews/ch<ch>/cold/rNN/round.yaml` | packet page number -> page id and revision, answers sha256 and time, key sha256 |
| `reviews/ch<ch>/cold/rNN/answers.yaml` | the reader's answers (locked) |
| `reviews/ch<ch>/cold/rNN/key.yaml` | the answer key (identify, triage, judge) |
| `reviews/ch<ch>/cold/rNN/score.md`, `score.json` | the score per question and the findings filed |
| `reviews/ch<ch>/art-story/art-story.png/.md/.yaml` | panel crops next to asserted facts and design views |
| `reviews/ch<ch>/findings/<id>@<rev>.png` | the crop of a finding at a page revision |
| `reviews/ch<ch>/recheck/<stamp>/` | spreads, before/after crops, `recheck.md`, `recheck.json` |

## Page revision
`rev` is the first 12 hex digits of the sha256 of the page's clean reading render. Renders are
deterministic, so the same inputs give the same rev and any visible change gives a new one. Findings
also record the page source sha and the art versions. A finding *survived a revision* when its
page's rev changed after it was filed or last checked and it still holds.

## Packet rules
* Only clean reading-size renders (no board marks, notes, labels, ids), in reading order. Spreads lie
  as the book opens (rtl: earlier page on the right); a page-turn card stands between spreads.
* Page numbers are chapter page positions ("page 1"), never page ids.
* `packet_leaks` refuses a packet whose file names or text contain any beat, line, fact, canon,
  page or asset id (except words the fixed questionnaire itself uses).
* `--pages p002,p003` makes a partial packet of those spreads for a re-read after fixes.
* A fresh reader is best: a person or an agent that has not opened the project. If the reviewer
  must read it, read only the packet, write every answer, record them, and only then open the story.
  Say so in `reader:` and `note:`.

## Questionnaire (fixed)
1. Speaker order: every balloon, caption and sound in reading order, with page, first words, speaker.
2. What changed hands: object, from, to, page, moment.
3. Owner at the end: who has each object on the last page.
4. Eye path: per page, where the eye landed first and then.
5. Surprise: what, and on which page.
6. Reveal timing: when something hidden became known; page; whether right after a turn.
7. Unclear: anything not read, not followed, or read twice; page and where.

## Key (`key.yaml`)
```yaml
identify: {runner: rin, man in coat: saeki, envelope: envelope}   # reader label -> canon id
triage:                    # by unclear index
  0: {owner: board, page: p002, panel: platform, region: [x0,y0,x1,y1], severity: warn,
      intended: "...", title: "...", key: "...", probe: {...}}    # key: merge into an existing finding
  1: {drop: true}          # no finding (say why in a comment)
judge:                     # free answers and overrides
  eye_path.1: {result: ok | partial | wrong, note: "...", owner: board}
  reveals[0]: {result: partial, fact: <fact id>, owner: story, note: "..."}
```

## Scoring
| Question | Intended | Match | Finding (owner) |
|---|---|---|---|
| speakers | lines in board reading order; speaker, `caption` or `sound` | words by fuzzy match on the same page, speaker by `identify`; order by longest increasing run | `cold-speaker`, `cold-order` (board), `cold-missed-line` (compose) |
| transfers | continuity `holder` events, page of the event's beat | object, from, to, page | `cold-transfer-missed`, `cold-transfer` (board) |
| holder_end | holder of each prop after the chapter's last beat | holder | `cold-holder-end` (board) |
| eye_path | focal points per panel in rank order (board) | by `judge` only | `cold-eye-path` (board) |
| reveals | facts revealed (reader.knows of a concealed fact), page, after a turn | fact by label or keyword, page and turn | `cold-reveal-missed`, `-early` (error), `-late`, `-partial` (board or judge owner) |
| surprise | the reveal pages | any surprise on a reveal page | `cold-reveal-flat` (info) |
| unclear | - | each item | `cold-unclear` (triage owner, default direct) |
A later round that reads a finding's item as intended marks it verified if the page changed or the
finding was fixed, otherwise `not-reproduced`. Score refuses answers changed after recording and
pages changed since the packet (`--force` to score anyway; the stale pages are listed).

## Technical pass (`review tech`)
Runs `story check` with page cross-checks, `design check`, `board check` with every technical page
check, and review's measurements, then merges issues with the same canonical code and place
(`unlettered-line`/`missing-dialogue` -> `line-not-lettered`, `reading-order` -> `balloon-order`).
Errors and warnings are filed; infos only for work items (`needs-art`, `art-style-unrecorded`).
Owners: story codes about pages and reveals go to board; art, assets, resolution and superseded jobs
to illustrate; masks, breakouts, lettering fit, fonts and SFX size to compose; direction and design
codes to design; `art-style-older` to direct.
Review measurement: `sfx-small` (warn, compose) when an SFX is shorter than `min_panel_height` of its
panel (direction sfx rule `render.sfx.min_panel_height`, else `project.yaml review.sfx_min_panel_height`,
default 0.18).
An intentional overlap must be a declared breakout region; then `breakout-cut`/`breakout-intrudes`
tell it from accidental clipping, and review files only the accidental ones.

## Art vs story (`review art`)
Per panel in reading order: beat, location, who is present with the costume continuity gives at that
beat, props shown or carried by someone present with their holder (`a -> b` when it changes in that
beat), explicit asserts, the art (final or rough), and the design view thumbnails for who is present.
A drawing that contradicts the story goes in a verdicts file:
```yaml
- {page: p003, panel: doors-closing, ok: false, owner: board, severity: warn, title: "...",
   observed: "...", intended: "...", region: [..], probe: {...}}
```
Code `art-contradicts-story`. When the story is what is wrong, owner is story; the director
resolves which side changes.

## Findings schema
```yaml
- id: F014
  key: cold:tail:line-02        # dedupe key; the same key reproduces instead of duplicating
  code: cold-unclear
  title: tail stops short of the speaker
  source: cold-read | tech | art-story | manual
  severity: error | warn | info
  owner: story | design | board | illustrate | compose | direct
  status: open | fixed | verified | wont-fix | editorial
  chapter: '01'
  page: p002
  panel: platform
  region: [x0, y0, x1, y1]      # page units
  observed: "the reading"       # what the reader or check saw
  intended: "the intent"        # what story/board/design meant
  evidence: [paths, check lines]
  revision: {page, rev, source, assets, round}     # when filed
  crop: reviews/ch01/findings/F014@<rev>.png
  crop_after: ...               # after the last recheck that saw a new rev
  probe: {kind: tech, key: ...} | {kind: tail-gap, line, max} | {kind: sfx-size, line, min}
  survived: 0                   # revisions it survived
  checks: [{at, rev, result: filed|reproduced|survived|verified|needs-verdict|unchanged|not-reproduced, round, detail}]
  alternatives: [{name, owner, description, by, keep}]    # editorial
  decision: {choice, reason, at, by}
  history: [{at, by, status, note}]
```
Rules: `fixed` and `wont-fix` need a note. `editorial` keeps at least two alternatives; `decide`
records the choice and reason and keeps every alternative; a `keep: true` choice closes as wont-fix,
otherwise the finding goes back to open for the chosen owner. A wont-fix or editorial finding is not
re-filed when its check reproduces. A verified finding that reproduces is reopened (regression).

## Recheck
For each open or fixed finding, after re-rendering its page:
| Probe | Page rev | Result |
|---|---|---|
| no longer holds | any | verified |
| holds | changed | survived (+1); a `fixed` finding goes back to open |
| holds | same | unchanged |
| no probe | changed | needs-verdict: look at `<id>-before-after.png`, then `review verdict <id> verified|survived --note` |
| no probe | same | unchanged |
New technical issues on the rechecked pages are filed. Attach a probe whenever a visual finding has
a measurable proxy (a tail gap, an SFX size, a check key), so the recheck can decide by itself.

## Metrics (`review metrics`)
Illustration calls per accepted panel and art calls caused by lettering or mask-only edits (from the
job log), findings, open findings by owner, findings rechecked after a revision, findings that
survived a revision, and the latest cold-read score. A page that rendered is not a page that reads:
report the score and the survivors, not just the check count.
