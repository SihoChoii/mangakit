"""p003/train-departs (train-departs): the shut train streaks away left; Rin, small, left behind
on the platform at lower left, watching it go."""
SIZE = (1228, 550)


def sketch(s):
    s.rect(0, 60, 1228, 300, fill=0.72, label="train pulling away")
    s.speed(0, 70, 1228, 280, angle=0, n=26, level=0.45)
    s.rect(0, 360, 1228, 190, fill=0.9)
    s.lines([(0, 390), (1228, 390)], dashed=True)
    s.figure("rin", feet=(250, 520), height=200, facing="left", pose="stand", look=(40, 260))
    s.arrow((900, 200), (300, 200), kind="motion")
    s.focal(s.landmarks["rin-head"], "Rin, left behind", rank=1)
    s.camera("WIDE, Rin small")
