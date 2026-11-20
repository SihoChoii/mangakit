"""p003/doors-closing (doors-closing): the doors slide shut; Rin, still on the platform, lunges at
the narrowing gap from the right."""
SIZE = (1228, 463)


def sketch(s):
    s.rect(0, 0, 1228, 463, fill=0.74)                                       # train side
    s.rect(330, 40, 230, 423, fill=0.6, label="door")
    s.rect(600, 40, 230, 423, fill=0.6)
    s.rect(560, 40, 40, 423, fill=0.97)                                      # the gap
    s.arrow((380, 250), (520, 250), kind="motion")
    s.arrow((780, 250), (640, 250), kind="motion")
    s.figure("rin", feet=(1080, 640), height=560, facing="left", pose="run", lean=24, reach=(640, 200),
             look=(580, 200))
    c = s.landmarks["rin-chest"]                                             # review F017: she still holds it
    s.prop("envelope", rect=(c[0] - 30, c[1] - 12, 60, 38), rotate=-10)     # (envelope.holder = rin until give-envelope)
    s.focal((580, 210), "closing gap")
    s.camera("MEDIUM, platform side")
