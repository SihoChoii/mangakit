---
name: manga-story
description: >-
  Write, check, and change a manga chapter's story records from a concept,
  existing canon, and length and audience goals. These records are the premise,
  canon, ordered beats with what the reader knows after each, the script (stable
  line ids, speaker ids, kinds), continuity events, and setups and payoffs. Use
  when a chapter needs a story or script, when dialogue or a story fact must
  change ("shorten this line", "she gives the envelope to someone else"), when a
  reveal must land behind a page turn, or before any page is boarded or drawn
  from a beat. Do not use it to place balloons, break lines, lay out panels, or
  draw. Those belong to compose, board, and illustrate, and get their stale list
  from here.
---
# manga-story

You own what happens, in what order, and who says what. You also own which facts change when, and
what the reader may know after every beat. You write the story/ records, prove them consistent with
`mangakit story check`, and tell the other skills exactly what a change makes stale. You never edit
pages or art.
Tools: `mangakit` (the toolkit in the mangakit repo; `install.sh` installs it and puts `mangakit` on PATH); `docs/...` below means the repo's docs folder, which `mangakit docs` prints. Schemas, check codes, impact rules:
`docs/story-reference.md`. Commands: `docs/cli.md`.

## Inputs
- A project directory with `project.yaml` (`mangakit init` creates story/ templates)
- The concept or request: what the chapter is for, and any scene, line, or reveal it must contain
- Existing canon: `story/canon.yaml` (characters, props, locations, facts, initial state) and earlier
  chapters' beats and open threads (`deferred:`)
- Length and audience goals: pages, rough beat count, audience, tone (into `story/premise.yaml`)
- Existing pages in `chapters/<ch>/`, if any, and the chapter's `pairing` (which pages face each other)
- For a change: the exact request ("shorten line-17", "a different person takes the envelope")

## Allowed edits
- `story/premise.yaml`, `story/canon.yaml` (identities only; how a character looks belongs to design),
  `story/beats.yaml`, `story/script.yaml` (wording, kind, speaker), `story/continuity.yaml`,
  `story/threads.yaml`
- `chapters/<ch>/chapter.yaml`: page order and `pairing` only, when a reveal needs a page turn.
  Tell the board owner, since this changes which pages face each other.
- Do not edit page sources, balloons, line breaks, masks, art, references, or jobs. The script owns
  words, and the page owns where they sit and how they break. If a drawing disagrees with continuity,
  do not change the story to match it quietly. Report it as a finding for the director, naming the
  panel, the asset version and the fact.
- Never renumber or reuse a line or beat id: pages and art jobs point at them. Add new ids instead.

## Procedure
1. **Premise and canon.** Write the logline, audience, length and goals. Then list every character
   who speaks or acts. Their ids are the only valid speakers. Add props whose possession matters,
   locations with `adjacent` for "within reach", and the initial state (who holds what, who is
   where). Give each fact the reader will learn an id. Give each concealed fact the `keywords` that
   would give it away.
2. **Beats.** Order the beats. For each one, write a one-sentence summary, the location, who is
   present (hidden people count), what is shown, `asserts` for anything a drawing will show as true
   (`envelope.holder=saeki`), and `reader: knows / suspects / conceals`. Put each reveal on its own
   beat. Plan which beats share a spread: a reveal goes on the first page after a page turn.
3. **Script.** Write the lines in reading order. Each line gets a stable id, its beat, a `kind`
   (speech, thought, caption, sfx), a speaker id for speech and thought, the text, and `reveals`
   when the line itself tells the reader a fact. Keep each balloon's line short enough to read at
   page size. Compose will check the fit.
4. **Continuity and threads.** Add one event per changed fact (`subject`, `attribute`, `value`,
   `from`) at the beat where it changes. Link every setup to its payoff, or mark it `deferred:`
   with where it pays off.
5. **Check until clean.** Run `mangakit story check`. Fix every error in the record that owns it,
   then re-run. Explain warnings or fix them. Infos (deferred threads) stay listed. The leak check
   only matches keywords, so also reread lines for hints phrased in other words.
6. **Read the arc.** Run `mangakit story glance` and read `build/story/glance.md` top to bottom as
   a reader would. At each beat ask: what does the reader know, suspect, and not know? Who holds the
   prop? Is there a page turn before the reveal?
7. **For a change, run impact first.** Run `mangakit story impact <line|beat|event|subject.attr>`,
   with `--text "new wording"` or `--set <new value>` to try it without touching files. Make the
   edits in the story records, run steps 5–6 again, and hand the owner-grouped stale list to the
   other skills:
   - `compose` rerun: reflow balloons and re-letter SFX
   - `board` and `illustrate` inspect: look at the panel, and open an art job only if the drawing
     shows the old fact
   - `review` rerun: re-render and re-read
8. **Return.** Report:
   - the `story check` output, which must show 0 errors
   - the beat-sheet path
   - for a change: the impact output, the edits you made, and the stale list with owners
   - any open finding, such as art that contradicts continuity, or a leak the keywords cannot catch

## Worked example
Request: "Make the train-door scene a 3-page chapter where the courier hands off the envelope
before a page-turn reveal of who took it." Example project: `example/` in the mangakit repo is a text-only cut of the demo this worked example comes from.
```
# canon: rin (courier), saeki (detective, hidden recipient), kuroda (client, ch 02); envelope;
#        platform-7 adjacent train-car-3; facts incl. recipient-identity {keywords: [Saeki, detective]}
# beats: cold-open, sprint, doors-closing, give-envelope (conceals recipient-identity),
#        train-departs, reveal (knows recipient-identity; asserts envelope.holder=saeki)
# continuity: ev-envelope-transfer  envelope.holder rin -> saeki  at give-envelope
# chapter.yaml: pages [p002, p003, p004], pairing even-start  -> [p002 p003] / page turn / [p004]
mangakit story check
#  [ERROR] leak line-17: text says 'Saeki', a keyword of recipient-identity ... until reveal
#  [ERROR] contradiction ev-envelope-back: giver saeki is not present at train-departs
#  [ERROR] reveal-on-facing-page p004: ... faces p003 where it is still concealed
# fix: "Take it! *Don't* open it before Kyoto!"; delete ev-envelope-back; pairing even-start
mangakit story check            # 0 errors; info: t-kyoto deferred to chapter 02
mangakit story glance           # build/story/glance.md
mangakit story impact line-17 --text "Take it! Not before Kyoto!"
#  compose rerun: reflow balloon line-17 on p003/handoff; illustrate inspect hands-at-door@v007
#  hypothetical: no new story issues; p003: balloon fits
mangakit story impact ev-envelope-transfer --set kuroda
#  story rerun: the event, beat give-envelope, line-18 and line-20 (spoken by saeki)
#  board/illustrate inspect: p003/handoff, p004/reveal; compose inspect: balloons line-18, line-20
#  hypothetical: receiver kuroda is not present at give-envelope; beats assert envelope.holder=saeki
```

## Done when
- `mangakit story check` shows 0 errors. Every warning is fixed or explained, and every open
  thread is `deferred:` with a destination.
- Every speech and thought line has a canon speaker who is present in its beat, and every beat has
  lines or is `silent: true`.
- You read `build/story/glance.md` and can say who holds each tracked prop at every beat, when it
  changed hands, and what the reader knows after every beat. Each reveal follows a page turn.
- For a change: you ran `story impact` before editing and saved its output. Its hypothetical issues
  are resolved in the story records, and the stale list went to the owning skills. No page or art
  file was edited by this skill.
- No line or beat id was renumbered or reused.
