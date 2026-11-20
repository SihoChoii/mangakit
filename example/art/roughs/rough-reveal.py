"""p004/reveal (reveal): on the moving train, Detective Saeki looks down at the envelope in his hand.
Face first (identity), then the seal."""
SIZE = (1100, 1582)


def sketch(s):
    s.rect(0, 60, 1100, 520, fill=0.88, label="window: night lights streaking")
    s.speed(0, 90, 1100, 460, angle=0, n=22, level=0.6)
    s.rect(0, 1330, 1100, 252, fill=0.7, label="seat")
    s.head("saeki", (640, 600), 230, facing="left", look=(330, 1130), label="Saeki: calm, eyes down")
    s.block([(160, 900), (1100, 860), (1100, 1582), (100, 1582)], fill=0.42)   # dark overcoat
    s.hand("saeki-hand", (620, 1240), (330, 1150), size=190, sleeve=0.3)
    s.prop("envelope", rect=(220, 1060, 280, 180), rotate=-8, label="the envelope")
    s.prop("seal", rect=(335, 1125, 44, 44), fill=0.25)
    s.focal(s.landmarks["saeki-eye"], "Saeki's face", rank=1)
    s.focal(s.landmarks["seal"], "the seal", rank=2)
    s.camera("MEDIUM CU, page-turn reveal")
