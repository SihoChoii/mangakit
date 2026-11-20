# Story reference (manga-story)

The story records say what happens, in what order, who says what, which facts change when, and
what the reader may know after each beat. Pages reference beats (`panel(..., beat=)`) and lines
(`balloon("line-17")`, `text(None, line="line-04")`). They never restate story facts.

## Authority

| Record | Owns | Changed by |
|---|---|---|
| `premise.yaml` | what the chapter is for: logline, audience, length, tone, goals | story, with the person commissioning the work |
| `canon.yaml` | who and what exists: character ids (the only valid speakers), props, locations, facts, initial state | story (identities); design owns how they look (`design:` points at a reference id) |
| `beats.yaml` | order of events, who is present where, what each beat makes the reader know, suspect, or not know yet | story |
| `script.yaml` | wording of every line, its kind and speaker | story. Compose owns line breaks and placement, never the words |
| `continuity.yaml` | when a story fact (`subject.attribute`) changes value | story |
| `threads.yaml` | setups and their payoffs | story |
| selected art | what was actually drawn | illustrate. A drawing that disagrees with continuity is a review finding; the director decides which side changes |

## Files

### premise.yaml
```yaml
title: Last Train
logline: One sentence.
premise: A paragraph.
audience: teen and up
length: {chapter: '01', pages: 3, target_beats: 6}
tone: night-time noir
goals: [A reader can say who holds the envelope at every point.]
```

### canon.yaml
```yaml
characters: [{id: rin, name: Rin Asano, role: courier, design: courier-design}]
props:      [{id: envelope, name: sealed envelope}]
locations:  [{id: platform-7, adjacent: [train-car-3]}, {id: train-car-3}]   # adjacent = within reach
facts:
- id: recipient-identity
  statement: The person who took the envelope is the detective.
  about: [saeki]                        # entities the fact is about (used by impact)
  keywords: [Saeki, detective]          # words that leak the fact if a line uses them early
  reveal: reveal                        # optional: the beat that should reveal it (warns if beats disagree)
initial:                                # state before the first beat
- {subject: envelope, attribute: holder, value: rin}
- {subject: rin, attribute: location, value: platform-7}
```
Attributes are free-form. Built-in meaning: `holder`/`owner` (possession transfer rules) and
`location` (presence and two-places rules). Use anything else (`costume`, `injury`, `door`) as a plain
timeline fact and check it with beat `asserts`.

### beats.yaml
```yaml
beats:
- id: give-envelope          # stable; pages reference it
  chapter: '01'
  summary: Rin pushes the envelope through the closing doors; an unseen hand takes it.
  location: platform-7
  present: [rin, saeki]      # who is in the scene (hidden characters count)
  shows: [envelope]          # entities the panels depict
  asserts: [envelope.holder=saeki]   # what the drawing will show; checked against continuity after the beat
  reader: {knows: [envelope-changed-hands], suspects: [], conceals: [recipient-identity]}
  silent: false              # true = a beat with no lines on purpose
```
Reader knowledge is cumulative: `knows` adds a fact (and clears it from suspected/concealed),
`suspects` adds a hint, `conceals` marks a fact the reader must not learn yet. Once known, a fact
cannot be concealed again.

### script.yaml
```yaml
lines:
- {id: line-17, beat: give-envelope, kind: speech, speaker: rin, text: "Take it! *Don't* open it before Kyoto!", reveals: [kyoto-deadline]}
- {id: line-04, beat: sprint, kind: sfx, text: TAP TAP TAP}
- {id: line-01, beat: cold-open, kind: caption, text: Shinjuku line. 0:42 a.m.}
```
`kind`: `speech` | `thought` | `caption` | `sfx`. Speech and thought need a canon speaker who is
present in the beat (`offpanel: true` still requires presence; a voice from another place is a
different beat). Captions and SFX may have no speaker. `reveals` declares facts the line itself
tells the reader. `*emphasis*` is lettering markup. Line ids never get renumbered; add new ids.

### continuity.yaml
```yaml
events:
- {id: ev-envelope-transfer, beat: give-envelope, subject: envelope, attribute: holder, from: rin, value: saeki}
```
An event takes effect at its beat; `state_at(beat)` is the state after it. `from` is optional and
checked.

### threads.yaml
```yaml
threads:
- {id: t-mystery-hand, setup: {beat: give-envelope}, payoff: {beat: reveal}, reveals: recipient-identity}
- {id: t-kyoto, setup: {line: line-17}, deferred: chapter 02}
```
Setup and payoff: a beat id, `{beat: id}` or `{line: id}`. `deferred:` marks a payoff in a later
chapter. `reveals:` ties the thread to a fact so reveal timing is checked.

## story check codes

| Code | Sev | Meaning |
|---|---|---|
| `setup-without-payoff` | warn | thread has a setup and no payoff or `deferred` |
| `deferred-payoff` | info | open thread paid off later (listed so it is not forgotten) |
| `payoff-without-setup` | error | thread has a payoff and no setup |
| `payoff-before-setup` | error | payoff beat is not after its setup |
| `reveal-before-setup` | error | the thread's fact is known before its setup |
| `reveal-not-at-payoff` | warn | the fact becomes known somewhere other than the payoff |
| `reveal-moved` | warn | canon `reveal:` and beats disagree on when a fact is learned |
| `leak` | error | a line reveals or names (keyword) a fact the reader may not know yet at that beat |
| `conceal-after-known` | error | a fact is concealed after the reader already knows it |
| `unknown-speaker` | error | speech/thought without a canon character speaker, or a speaker id not in canon |
| `speaker-absent` | error | speaker is not present in the line's beat |
| `beat-without-lines` | warn | beat has no lines and is not `silent: true` |
| `line-order` | warn | script order runs backwards through the beats |
| `contradiction` | error | event `from` disagrees with the timeline; one fact set twice at a beat; a transfer whose giver or receiver is absent or out of reach; a beat `asserts` something continuity does not say |
| `two-places` | error | a present character's continuity location is neither the beat location nor adjacent to it |
| `unknown-beat` / `unknown-line` / `unknown-character` / `unknown-entity` / `unknown-location` / `unknown-fact` | error | dangling id (in story files or pages) |
| `panel-order` | warn | chapter pages draw beats out of order |
| `reveal-on-facing-page` | error | a fact is revealed on a page that faces a page where it is still concealed (no page turn between) |
| `reveal-on-same-page` | warn | concealed and revealed on the same page |
| `duplicate-beat` / `duplicate-line` / `bad-kind` / `empty-line` / `beat-incomplete` | error/warn | record hygiene |

Exit code: 2 with errors; with `--strict`, 1 with warnings. Page cross-checks use the chapter in
`chapters/<ch>/chapter.yaml` and its `pairing` (falls back to `project.yaml spreads.pairing`).

The leak check is keyword-based: give each concealable fact the names, titles and words that would
give it away. It cannot catch a paraphrase; a cold read (review) still has to.

## Dependencies and impact

`mangakit story deps` maps each beat to panels, lines and events, and each line to balloons and SFX
text layers. It also lists placed art (asset@version per panel), art jobs (from request.yaml
targets) and every build manifest per page.

`mangakit story impact <target>` groups what goes stale by owner. `rerun` means the work must be
redone. `inspect` means look at it and redo it only if it now conflicts.

| Target | story | board | compose | illustrate | review |
|---|---|---|---|---|---|
| line | rerun: the script edit. inspect: threads it sets up or pays off, facts it reveals | - | rerun: reflow its balloon or re-letter its SFX | inspect: art in that panel (acting/composition only) | rerun: renders that letter the line (art-only renders and detail crops away from the balloon are spared) |
| beat | rerun: the beat. inspect: its lines, events, later reader knowledge | inspect: panels drawing it | inspect: its balloons | inspect: art and live jobs for those panels | rerun: renders of those pages |
| fact (event id or `subject.attr`) | rerun: the event, its beat, lines spoken by the old value in the interval. inspect: facts and threads about it | inspect: panels in the interval that show or present the subject or old value | inspect: balloons by the old value (tail/speaker) | inspect: art in those panels; live jobs carry old continuity | rerun after edits: renders of those pages; re-read the spreads |

The interval of an event id runs from its beat to the next event on the same fact.

Hypotheticals (files are never touched):
* `--text "..."` on a line re-runs story check (new leaks) and the page checks of every page that
  letters the line with the new wording (fit, overlap, safe area).
* `--set VALUE` on an event re-runs story check with the new value and lists only new issues.

## Story at a glance

`mangakit story glance` writes `build/story/glance.md`: premise header, spreads in reading order,
then for every beat: panels, summary, location and cast, lines (id, kind, speaker, text), continuity
events, setups and payoffs, what this beat adds to reader knowledge, the state after it, the cumulative
known / suspected / concealed lists, page-turn markers, open threads and the current check result.

## Recipes (spec section 6)

**Shorten this line.** `story impact line-17 --text "shorter"` -> edit the text in script.yaml ->
`check` the page -> render and look -> reopen the drawing only if the acting or composition now
conflicts. No art job for wording.

**She gives the envelope to a different person.** Add the person to canon if new.
Run `story impact ev-envelope-transfer --set <id>`, then edit the event, the beat (`present`,
`summary`, `asserts`) and the lines it names. Run `story check` until it is clean, then inspect every
listed panel. Schedule art jobs only for panels whose drawing shows the old recipient. Then
re-render and re-read the spreads.
