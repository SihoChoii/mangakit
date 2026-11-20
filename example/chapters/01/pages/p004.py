"""p004 - page-turn reveal (first page after the turn; the [p004] spread is read alone).

Board: one full-live-area panel. recipient-face v003 (job-0011, an edit of job-0010 v002; job-0008 v001
failed review) is the final art: face first (identity), then the seal.
"""


def build(page, art, script):
    L = page.layout()
    face = page.panel("reveal", L.live, beat="reveal", note="MEDIUM CU: Saeki, eyes on the seal")
    drawing = art.slot(final="recipient-face", rough="rough-reveal")
    place = face.fit(drawing)
    page.image(drawing, transform=place, clip=face.path)
    page.focal(place.map("saeki-eye"), panel="reveal", label="Saeki's face")   # final art carries the eye path now
    page.focal(place.map("seal"), panel="reveal", label="the seal")
    page.borders()
    page.balloon("line-20", at=(860, 220), tail_to=place.map("saeki-mouth"), panel="reveal")
    return page
