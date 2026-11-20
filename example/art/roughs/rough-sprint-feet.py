"""p002/sprint-feet (sprint): feet pounding the platform edge, running left; SFX TAP TAP TAP."""
SIZE = (1228, 448)


def sketch(s):
    s.rect(0, 330, 1228, 118, fill=0.9)
    s.lines([(0, 360), (1228, 360)], dashed=True)
    s.speed(600, 120, 628, 300, angle=0, n=18)
    s.figure("rin", feet=(700, 420), height=760, facing="left", pose="run", lean=10)
    s.focal((534, 408), "front foot")
    s.arrow((900, 420), (560, 420), kind="motion")
    s.camera("LOW, feet only")
