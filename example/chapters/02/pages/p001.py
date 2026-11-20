"""ch02 p001 - Kyoto arrival. Board stage: art not commissioned (example: no final art yet)."""
from mangakit import Path


def build(page, art, script):
    M, W = 55, 1092 - 55
    b = page.bleed
    arrival = page.panel("arrival", Path.rect(-b, -b, page.width + 2 * b, 900 + b), beat="kyoto-arrival")
    drawing = art.slot(final="saeki-kyoto")
    place = arrival.align(drawing, source=(500, 500), target=(546, 450), scale=1.1)
    page.image(drawing, transform=place, clip=arrival.path)
    low = page.panel("steps", Path.rect(M, 930, W - M, 540), beat="kyoto-arrival")
    page.stroke(low.path, style="panel-border")
    page.balloon("line-22", shape="box", at=(page.width - 230, 110), panel="arrival")
    return page
