---
name: manga-illustrate
description: >-
  Commission, correct, and accept the drawing for one manga panel from its
  board, references and shot guide, using whatever image backend the host
  provides. Use when a panel needs new art, a drawing must be fixed (wrong pose,
  hands, framing, missing art beyond a border break), a design change makes
  approved art stale, or someone says "draw the handoff panel" or "the cuff has
  to reach below the border". Do not use it to move balloons, rebuild masks, or
  re-place art; those are composition edits and must not cost an art call.
---
# manga-illustrate

You turn a panel's board and references into an accepted drawing version. You request art, look
at what comes back, correct it, and select it. You never edit page layout or lettering here.
Tools: `mangakit` (the toolkit in the mangakit repo; `install.sh` installs it and puts `mangakit` on PATH); `docs/...` below means the repo's docs folder, which `mangakit docs` prints. Request format, adapters, paint-overs,
and selection rules: `docs/illustrate-reference.md`. Commands and check
codes: `docs/cli.md`.

## Inputs
- A project directory with `project.yaml`, plus the page and panel id (for example `p003` / `handoff`)
- The page source and its rough, with the panel's breakouts and lettering already placed
- Pinned references in `references/` (`mangakit ref list`): design sheets, a style exemplar, props
- The beat in `story/beats.yaml` (lines in `story/script.yaml`), including what the reader knows and what stays concealed
- The image backend the host provides. Run `mangakit job request` and check which adapter fits:
  `host` (an image tool you call), `manual` (a person or another agent), or `command` (a scripted backend).
- Any note from composition or review, such as "cuff never crosses the border" or "six fingers"

## Allowed edits
- `art/jobs/<job>/`: requests, call logs, collected candidates, verdicts, review sheets
- New drawing versions through `mangakit job collect`, landmarks on those versions, and selection
  through `mangakit job select` (guarded)
- New reference versions with `mangakit ref add`, when the director or design owner supplies them
- Do not edit page sources, masks, balloons, `story/script.yaml`, or `project.yaml` fonts and format.
  Never overwrite or delete a drawing version. If the layout itself must change, send a request to
  composition or the board owner.

## Procedure
1. **Write the request.** Run `mangakit job request <page> --panel <id> --asset <asset> --ref
   <design>@<ver> --ref <style>@<ver>` with `--prev-direction`, `--transition`, `--conceal`, and
   `--notes` describing the shot in plain words: who, what action, where the key shapes sit, and
   what must stay clear. Read `prompt.md` and look at `pack/guide.png` and `pack/rough-crop.png`.
   Check that `beyond_border` names every breakout. Pin the fewest references that carry identity
   and style.
2. **Call the backend.** Run `mangakit job call <job>` once per call, then follow what it prints:
   - `host`: call the host image tool with the arguments in `host-call-<n>.json`, then run
     `mangakit job collect <job> <file> --call <n>`.
   - `manual`: send `prompt.md` and `pack/`, and when images arrive in `inbox/`, run
     `mangakit job collect <job> --inbox`.
   - `command`: candidates are collected automatically.

   Every call is logged, including calls that return nothing usable. Candidates are stored and
   never selected.
3. **Review every candidate.** Run `mangakit job review <job>` and open the sheet. Judge each
   candidate against each acceptance criterion: identity, acting at reading size, hands and
   contact point, framing, art beyond the border, clear lettering zones, screen direction and
   concealment, style, and no text in the image. For a promising candidate:
   - Set its landmarks with `mangakit asset inspect <asset> --version <v> --grid 50` and
     `mangakit asset landmark ... --version <v>`.
   - Render it in the page without selecting it:
     `mangakit render <page> --pin <asset>=<v> -o art/jobs/<job>/trial-<v>.png`.
   - Rebuild the sheet with `--trial` so the placed overlay and the page are side by side.

   Record `mangakit job verdict <job> <v> --pass|--fail --note "<criteria>"` for every candidate.
4. **Correct once, locally.** Take the best failing candidate. Run `mangakit job request ...
   --reason correction --edit-of <v> --instruction "<what changes, where, in % of the image; what
   stays>"`.
   - If the change moves parts (an arm lower, an object across a border), build a paint-over first:
     `mangakit job targets <job>` gives target points, then `mangakit paintover <asset> --version
     <v> --map ... --map ... [--cut <poly>] [--background <img>] -o po.png`.
   - Pass it with `--paintover po.png`, and send only the paint-over and the style reference.
     Instruction-only edits usually redraw without moving anything, so prefer the paint-over.
   - If the backend cannot edit, the same request runs as a replacement. Repeat step 3 on the result.
5. **Select.** Run `mangakit job select <job> <v>`. It refuses without a passing verdict or if the
   selection moved since the request. Read the INVALIDATED lines. Set any missing landmarks
   yourself. Hand stale masks to composition, or rebuild them yourself if you are also doing compose.
6. **Return.** Report:
   - the accepted version and its job
   - the review sheet and trial or proof PNG
   - the verdict notes of rejected candidates
   - `mangakit metrics` output: calls per accepted panel, and art calls from lettering or mask
     edits, which must be 0
   - any open defect, with its owner

## Worked example
Request: "Commission p003 'handoff' from its rough: the envelope tip and the courier's cuff must
break the diagonal border." Example project: `example/` in the mangakit repo is a text-only cut of the demo this worked example comes from.
```
mangakit ref add courier-handoff-design sheet.jpg --kind design --note "black sleeve, white ribbed cuff, wax-seal envelope"
mangakit ref add style-ink-night exemplar.png --kind style
mangakit job request p003 --panel handoff --asset hands-at-door --ref courier-handoff-design --ref style-ink-night \
  --prev-direction "courier on screen right, reaching right-to-left" --conceal "recipient's face" --notes "..."   # job-0003
mangakit job call job-0003    # host: call the image tool with host-call-1.json, then
mangakit job collect job-0003 <file> --call 1                                    # v002 (second call: v003)
mangakit job review job-0003  # v002 fine drawing, cuff far above the border; v003 copied the crude rough
mangakit job verdict job-0003 v002 --fail --note "cuff at 40% height, cut-out region is 70-83%"
mangakit job request p003 ... --reason correction --edit-of v002 --instruction "lower the forearm ..."   # job-0004: v004 moved nothing
mangakit job targets job-0003 && mangakit paintover hands-at-door --version v002 \
  --map 385,565:350,658 --map 930,345:783,665 --cut "<arm+hands+envelope>" --background doors.png -o po.png
mangakit job request p003 ... --reason correction --edit-of v002 --paintover po.png --ref style-ink-night   # job-0006 -> v007
mangakit asset landmark hands-at-door finger-contact 405 605 --version v007 --protect   # + envelope-tip, cuff-low, fist
mangakit render p003 --pin hands-at-door=v007 -o art/jobs/job-0006/trial-v007.png      # hands land on the diagonal
mangakit job verdict job-0006 v007 --pass --note "two hands, cuff and envelope cross the border, style matches"
mangakit job select job-0006 v007     # INVALIDATED mask border-break -> composition rebuilds it (m009)
mangakit metrics                      # calls per accepted panel 6; art calls from lettering/mask edits 0
```

## Done when
- The accepted version has a passing verdict that names the criteria, and every other candidate
  has a verdict note.
- You looked at the review sheet and a trial or proof render with the version placed in the real
  page, including a `--view detail` crop of the hands and of every border crossing.
- `job select` succeeded. Its INVALIDATED masks and landmarks are fixed, or handed to composition
  with the asset and version.
- `mangakit metrics` shows the call count for the panel, and 0 art calls caused by lettering or
  mask edits.
- No drawing version was overwritten. The request, pack, call logs, and candidates for every job
  are in `art/jobs/`.
