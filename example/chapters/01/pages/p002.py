"""p002 - cold open + sprint (chapter page 1, right-hand page of the [p002 p003] spread, read first).

Board: three tiers from the layout helpers (rtl). The wide bleeds off the top and the outside edge (not into the binding); the two
sprint panels sit in the live area. No final art yet: each panel shows its procedural rough until the
final asset in its slot is selected. Rin runs LEFT throughout, with the reading direction, so the
eye is carried toward the open door and across the gutter to p003.
"""


def build(page, art, script):
    L = page.layout()
    wide, close, feet = L.rows([540, 470, 358])
    plat = page.panel("platform", L.bleed(wide, ("top", "outside")), beat="cold-open", border=False,
                      note="WIDE: last train, 0:42; Rin enters right")
    top = page.panel("sprint-close", close, beat="sprint", note="CU Rin, running left")
    low = page.panel("sprint-feet", feet, beat="sprint", note="LOW: feet, speed")

    d1 = art.slot(final="platform-wide", rough="rough-platform")
    p1 = plat.fit(d1)
    page.image(d1, transform=p1, clip=plat.path)
    d2 = art.slot(final="rin-sprint-face", rough="rough-sprint-close")
    p2 = top.fit(d2)
    page.image(d2, transform=p2, clip=top.path)
    page.effect("speed_lines", low.path, seed=202, angle=0, count=60, width=(1, 3))
    d3 = art.slot(final="rin-sprint-feet", rough="rough-sprint-feet")
    p3 = low.fit(d3)
    page.image(d3, transform=p3, clip=low.path)
    page.borders()

    page.balloon("line-01", shape="box", at=(page.width - 230, 96), panel="platform")
    page.balloon("line-02", at=(935, 212), tail_to=p1.map("rin-mouth"), panel="platform")   # review F014, F011: above Rin, off her look at the door
    page.balloon("line-03", at=(600, 705), tail_to=p2.map("rin-mouth"), panel="sprint-close")   # final art: into the open space beside her face
    page.text(None, at=(310, 1215), font="sfx", size=92, rotate=-4, panel="sprint-feet", line="line-04")   # review F003
    return page
