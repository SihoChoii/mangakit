"""p002/platform (cold-open): night platform, last train waiting on the left, Rin enters from the
right running left (reading direction rtl = forward) toward the one open door."""
SIZE = (1410, 772)


def sketch(s):
    # canopy (review F013): a roof with structure, not a flat band - light underside, a darker fascia
    # edge, roof beams and two hanging lamps, so it reads as the platform roof and not as a print fault
    s.tone([(0, 0), (1410, 0), (1410, 46), (0, 46)], 0.82)                  # canopy underside
    s.rect(0, 46, 1410, 14, fill=0.45, label="platform canopy")             # fascia edge
    for x in range(60, 1410, 220):
        s.lines([(x, 0), (x + 40, 46)])                                      # roof beams
    for x in (300, 1300):
        s.lines([(x, 60), (x, 92)])
        s.rect(x - 22, 92, 44, 10, fill=0.97)                                # hanging lamps
    s.rect(0, 120, 930, 440, fill=0.72, label="last train (doors open)")     # train body
    for x in (30, 230, 700):
        s.rect(x, 170, 150, 140, fill=0.9)                                   # windows
    s.rect(400, 150, 110, 410, fill=0.62)                                    # door leaf
    s.rect(560, 150, 110, 410, fill=0.62)                                    # door leaf
    s.rect(510, 150, 50, 410, fill=0.97)                                     # lit gap
    s.rect(0, 560, 1410, 212, fill=0.9, label="platform 7")
    s.lines([(0, 600), (1410, 600)], dashed=True)                            # tactile strip
    s.figure("rin", feet=(1130, 715), height=360, facing="left", pose="run", lean=16, look=(535, 330))
    c = s.landmarks["rin-chest"]
    s.prop("envelope", rect=(c[0] - 26, c[1] - 10, 52, 34), rotate=-12)
    s.arrow((1060, 740), (760, 740), "runs for the door", kind="motion")
    s.focal(s.landmarks["rin-head"], "Rin", rank=1)
    s.focal((535, 330), "open door", rank=2)
    s.camera("WIDE, eye level - the eye travels Rin -> open door")
