"""p003 - the handoff at the train door (left-hand page of the [p002 p003] spread).

Panels (rtl): doors-closing (wide tier) -> handoff (diagonal bottom edge; the envelope tip and the
cuff break it) -> train-departs. The page turn after this page reveals the recipient (p004).

Example project: every panel shows a procedural rough (art/roughs/) until final art is commissioned
(`mangakit job request`) and selected. See docs/page-api.md for breakouts and break masks.
"""
from mangakit import Path

M, TOP, BOT = 55, 60, 1472          # outer margins (page units, 6 u/mm) = project board margins
W = 1092 - M                         # right edge of live panels
GUT = 22                             # gutter


def build(page, art, script):
    # ---- frames ---------------------------------------------------------------------------
    left, right = (M, 1130), (W, 1010)                    # diagonal bottom edge of the handoff panel
    doors = page.panel("doors-closing", Path.rect(M, TOP, W - M, 430 - TOP), beat="doors-closing",
                       note="MEDIUM: doors sliding shut, Rin lunges")
    handoff = page.panel("handoff", Path.polygon([(M, 452), (W, 452), right, left]), beat="give-envelope")
    departs = page.panel("train-departs", Path.polygon([(M, left[1] + GUT), (W, right[1] + GUT), (W, BOT), (M, BOT)]),
                         beat="train-departs", note="WIDE: train streaks away, Rin left behind")

    # ---- panel 1: doors closing (rough) --------------------------------------------------------
    d1 = art.slot(final="doors-closing-art", rough="rough-doors-closing")
    p1 = doors.fit(d1, anchor=(0.5, 0.5) if d1.kind == "rough" else (0.5, 0.0))   # final art: keep her head in frame
    page.image(d1, transform=p1, clip=doors.path)
    page.anchor("courier-mouth", p1.map("rin-mouth"))

    # ---- panel 2: the handoff (rough until final art is selected) ------------------------------
    d2 = art.slot(final="hands-at-door", rough="rough-handoff")
    place = handoff.fit(d2)
    page.image(d2, transform=place, clip=handoff.path, name="handoff-art")
    page.focal(place.map("finger-contact"), panel="handoff", label="the envelope changes hands")

    # ---- panel 3: doors shut, train pulls away (rough + speed) ------------------------------------
    d3 = art.slot(final="train-departs-art", rough="rough-train-departs")
    p3 = departs.fit(d3, anchor=(0.5, 0.5) if d3.kind == "rough" else (0.5, 0.0))   # final art: her head clears the handoff breakout
    page.image(d3, transform=p3, clip=departs.path)
    page.effect("speed_lines", departs.path, seed=3107, angle=-1.5, count=60, width=(0.8, 2.4),
                length=(0.25, 0.9), name="departs-speed")
    page.text(None, at=(800, 1300), font="sfx", size=130, rotate=-7, outline_width=7, panel="train-departs", line="line-21")

    page.borders()

    # ---- lettering ---------------------------------------------------------------------------
    page.balloon("line-16", at=(545, 112), tail_to="courier-mouth", panel="doors-closing")   # final art: left of her face, clear of the doors
    page.anchor("courier-offpanel", (1090, 760))
    page.balloon("line-17", at=(845, 560), tail_to="courier-offpanel", panel="handoff", aspect=1.7)
    page.anchor("recipient", (60, 980))
    page.balloon("line-18", at=(215, 845), tail_to="recipient", panel="handoff")
    page.balloon("line-19", at=(130, 1250), tail_to=p3.map("rin-mouth"), panel="train-departs")   # final art: left of her head, off her figure
    return page
