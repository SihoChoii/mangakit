"""p003/handoff (give-envelope): two hands meet in the narrowing door gap; Rin's cuffed hand (right,
platform side) passes the sealed envelope to a coat sleeve inside the car (left)."""
SIZE = (1100, 700)


def sketch(s):
    s.rect(0, 0, 1100, 700, fill=0.93)
    s.rect(470, 0, 160, 700, fill=0.2, label="door gap")
    s.block([(0, 240), (380, 300), (380, 420), (0, 420)], fill=0.35, label="coat sleeve (inside)")
    s.block([(1100, 300), (700, 330), (700, 450), (1100, 470)], fill=0.3, label="Rin's sleeve + white cuff")
    s.prop("envelope", rect=(430, 330, 240, 150), rotate=-6)
    s.landmark("finger-contact", (550, 400))
    s.focal((550, 400), "the envelope changes hands")
    s.camera("CLOSE, the gap between the doors")
