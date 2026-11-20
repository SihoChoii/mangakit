"""p002/sprint-close (sprint): Rin's face, close, running left; envelope pinned under her arm."""
SIZE = (1228, 588)


def sketch(s):
    s.speed(0, 0, 1228, 588, angle=0, n=30, level=0.75)
    s.head("rin", (720, 300), 150, facing="left", look=(0, 250), label="Rin: jaw set, sweating")
    s.prop("envelope", rect=(860, 470, 190, 110), rotate=-14, label="envelope under arm")
    s.focal(s.landmarks["rin-eye"], "Rin's eyes")
    s.camera("CU, slight low angle")
