"""manga-board: layout helpers, geometric reading order, procedural roughs, board checks, chapter
plan with stable ids, alternates (compare, id-safe promotion), board renders."""
import json
import textwrap

import pytest
import yaml
from PIL import Image

from mangakit import board as B
from mangakit.assets import Registry
from mangakit.geometry import Path
from mangakit.illustrate import Jobs
from mangakit.layout import breakout_zone, reading_order
from mangakit.project import MangakitError, Project, init_project
from mangakit.render import load_page, render_page
from mangakit.rough import make_rough

CANON = """
characters: [{id: ann, name: Ann}, {id: bo, name: Bo}]
props: []
locations: [{id: hall}]
facts:
- {id: bo-did-it, about: [bo]}
initial:
- {subject: ann, attribute: location, value: hall}
- {subject: bo, attribute: location, value: hall}
"""
BEATS = """
beats:
- {id: b1, chapter: '01', summary: Ann alone., location: hall, present: [ann], reader: {conceals: [bo-did-it]}}
- {id: b2, chapter: '01', summary: Ann waits., location: hall, present: [ann]}
- {id: b3, chapter: '01', summary: Bo steps out., location: hall, present: [ann, bo], reader: {knows: [bo-did-it]}}
"""
SCRIPT = """
lines:
- {id: l1, beat: b1, kind: caption, text: Night.}
- {id: l2, beat: b1, kind: speech, speaker: ann, text: "Who is there?"}
- {id: l3, beat: b2, kind: speech, speaker: ann, text: "Hello?"}
- {id: l4, beat: b3, kind: speech, speaker: bo, text: Me.}
"""
SKETCH = '''
SIZE = (600, 400)
def sketch(s):
    s.rect(0, 300, 600, 100, fill=0.9)
    s.figure("ann", feet=(420, 380), height=300, facing="left", pose="stand", look=(20, 150))
    s.focal(s.landmarks["ann-head"], "Ann")
    s.camera("WIDE")
'''

PAGE_A = '''
def build(page, art, script):
    L = page.layout()
    top, low = L.rows([1, 1])
    a = page.panel("a1", L.bleed(top, ("top", "outside")), beat="b1", note="wide")
    b = page.panel("a2", low, beat="b1")
    d = art.slot(final="ann-final", rough="rough-ann")
    p = a.fit(d)
    page.image(d, transform=p, clip=a.path)
    page.borders()
    x0, y0, x1, y1 = a.bbox
    page.balloon("l1", shape="box", at=(x1 - 200, 100), panel="a1")
    page.balloon("l2", at=(x1 - 420, 300), tail_to=p.map("ann-mouth"), panel="a1")
    return page
'''
PAGE_B = '''
def build(page, art, script):
    L = page.layout()
    (one,) = L.rows([1])
    page.panel("b-1", one, beat="b2")
    page.borders()
    page.balloon("l3", at=(600, 300), panel="b-1")
    return page
'''
PAGE_C = '''
def build(page, art, script):
    L = page.layout()
    page.panel("c-1", L.live, beat="b3")
    page.borders()
    page.focal((500, 700), panel="c-1", label="Bo")
    page.balloon("l4", at=(800, 200), panel="c-1")
    return page
'''


def w(root, rel, text):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(textwrap.dedent(text))
    return f


@pytest.fixture()
def bp(tmp_path):
    root = init_project(tmp_path / "bp", "t")
    w(root, "story/canon.yaml", CANON)
    w(root, "story/beats.yaml", BEATS)
    w(root, "story/script.yaml", SCRIPT)
    w(root, "chapters/01/chapter.yaml", "id: '01'\npairing: even-start\npages: [p001, p002, p003]\n")
    (root / "chapters/01/pages/p001.py").unlink(missing_ok=True)
    w(root, "chapters/01/pages/p001.py", PAGE_A)
    w(root, "chapters/01/pages/p002.py", PAGE_B)
    w(root, "chapters/01/pages/p003.py", PAGE_C)
    w(root, "art/roughs/rough-ann.py", SKETCH)
    pr = Project(root)
    make_rough(pr, "rough-ann")
    return pr


def codes(R, sev=("error", "warn")):
    return sorted({i["code"] for i in R["issues"] if i["severity"] in sev})


# ---------------------------------------------------------------- layout
def test_layout_rows_cols_gutters_and_direction(bp):
    page, _ = load_page(bp, "p001")
    L = page.layout()
    rows = L.rows([1, 2])
    (a0, a1), (b0, b1) = [(r.bbox()[1], r.bbox()[3]) for r in rows]
    assert abs((b0 - a1) - L.row_gutter) < 0.05 and abs((b1 - b0) - 2 * (a1 - a0)) < 1
    cols = L.cols([1, 1])
    assert cols[0].bbox()[0] > cols[1].bbox()[0]                      # rtl: right column reads first
    assert abs(cols[0].bbox()[0] - cols[1].bbox()[2] - L.col_gutter) < 0.05
    up, down = L.cut(L.live, 900, 700)                                 # diagonal; gutter perpendicular
    assert up.shape().distance(down.shape()) == pytest.approx(L.row_gutter, abs=0.05)
    ltr = Project(bp.root, cfg={**bp.cfg, "reading_direction": "ltr"})
    pl, _ = load_page(ltr, "p001")
    c2 = pl.layout().cols([1, 1])
    assert c2[0].bbox()[0] < c2[1].bbox()[0]


def test_bleed_respects_page_side_and_inset(bp):
    p1, _ = load_page(bp, "p001")          # even-start rtl: p001 is the right-hand page
    p2, _ = load_page(bp, "p002")
    assert (p1.side, p2.side) == ("right", "left")
    b1 = p1.layout().bleed(p1.layout().live, ("outside",)).bbox()
    b2 = p2.layout().bleed(p2.layout().live, ("outside",)).bbox()
    assert b1[2] == pytest.approx(p1.width + p1.bleed) and b1[0] > 0       # right page: outside = right
    assert b2[0] == pytest.approx(-p2.bleed) and b2[2] < p2.width          # left page: outside = left
    host, ins = p1.layout().inset(p1.layout().live, Path.rect(600, 100, 300, 200))
    assert host.shape().distance(ins.shape()) == pytest.approx(p1.layout().col_gutter, abs=0.05)


def test_reading_order_tiers_columns_diagonals():
    S = {"L": Path.rect(0, 0, 100, 1000), "R1": Path.rect(120, 0, 100, 490), "R2": Path.rect(120, 510, 100, 490)}
    assert reading_order(S, rtl=True) == ["R1", "R2", "L"]
    assert reading_order(S, rtl=False) == ["L", "R1", "R2"]
    T = {"low": Path.polygon([(0, 1032), (1000, 912), (1000, 1400), (0, 1400)]),
         "up": Path.polygon([(0, 0), (1000, 0), (1000, 890), (0, 1010)])}
    assert reading_order(T) == ["up", "low"]


def test_breakout_toward_span(bp):
    page, _ = load_page(bp, "p001")
    a, b = page.panels["a1"], page.panels["a2"]
    z = a.breakout_toward(b, span=(0.0, 0.3), inside=30, reach=80)
    x0, y0, x1, y1 = z.bbox()
    assert page.breakouts[f"a1-break1"].over == ["a2"]
    assert x0 > a.bbox[0] + 0.6 * (a.bbox[2] - a.bbox[0])                 # rtl: span starts at the right end
    assert y0 < a.bbox[3] and y1 > b.bbox[1]                               # crosses the gutter


# ---------------------------------------------------------------- roughs
def test_rough_is_deterministic_with_landmarks_and_marks(bp):
    reg = Registry(bp)
    rec = reg.load("rough-ann")
    assert rec["kind"] == "rough" and rec["selected"] == "v001"
    assert {"ann-mouth", "ann-eye", "ann-hand", "focal"} <= set(rec["landmarks"]["v001"])
    meta = rec["versions"]["v001"]["rough"]
    assert meta["focal"][0]["label"] == "Ann" and meta["sightlines"] and meta["source"] == "art/roughs/rough-ann.py"
    assert make_rough(bp, "rough-ann")[:2] == ("v001", False)               # same source -> same bytes
    w(bp.root, "art/roughs/rough-ann.py", SKETCH.replace('facing="left"', 'facing="right"'))
    assert make_rough(bp, "rough-ann")[:2] == ("v002", True)
    with pytest.raises(MangakitError):
        Registry(bp).add_version("ann-final", bp.root / "art/assets/rough-ann/v001.png", select=True)
        make_rough(bp, "ann-final", bp.root / "art/roughs/rough-ann.py")   # not a rough asset


def test_rough_marks_only_on_rough_view_and_in_guide(bp):
    page, _ = load_page(bp, "p001")
    proof = render_page(page, "proof").with_suffix(".svg").read_text()
    rough = render_page(page, "rough").with_suffix(".svg").read_text()
    assert "#e00000" not in proof and "#e00000" in rough
    assert not [i for i in __import__("mangakit.checks", fromlist=["x"]).run_checks(page) if i["code"] == "art-resolution"]
    g = json.loads(render_page(page, "guide", panel="a1").with_suffix(".json").read_text())
    assert "ann-mouth" in [l["name"] for l in g["landmarks"]] and g["focal"][0]["label"] == "Ann"
    assert g["board_note"] == "wide"
    jid = Jobs(bp).request("p001", "a1", "ann-final", auto_style=False)
    req = yaml.safe_load((Jobs(bp).path(jid) / "request.yaml").read_text())
    assert req["shot_guide"]["rough_is_placeholder"] is False and req["shot_guide"]["focal"]


# ---------------------------------------------------------------- checks
def test_clean_board_and_reveal_after_turn(bp):
    R = B.check_chapter(bp, "01")
    assert codes(R) == []
    assert R["turns"][1]["after_turn"] and R["turns"][1]["reveals"][0]["page"] == "p003"
    info = codes(R, ("info",))
    assert "needs-art" in info and "no-focal" in info                     # rough-only panel, panel without focus


def test_seeded_board_errors(bp):
    w(bp.root, "chapters/01/chapter.yaml", "id: '01'\npairing: odd-start\npages: [p001, p002, p003]\n")
    f = bp.root / "chapters/01/pages/p001.py"
    s = f.read_text().replace('at=(x1 - 200, 100), panel="a1"', 'at=(x0 + 200, 330), panel="a1"')       # l1 after l2
    s = s.replace('beat="b1", note="wide")', 'beat="b1", note="wide", order=2)').replace('page.panel("a2", low, beat="b1")',
                                                                                          'page.panel("a2", low, beat="b1", order=1)')
    s = s.replace('L.bleed(top, ("top", "outside"))', 'L.bleed(top, ("top", "inside"))')
    f.write_text(s)
    g = bp.root / "chapters/01/pages/p002.py"
    g.write_text(g.read_text().replace('page.balloon("l3", at=(600, 300), panel="b-1")',
                                       'page.balloon("l3", at=(600, 300), panel="b-1")\n'
                                       '    page.balloon("l4", at=(600, 700), panel="b-1", font_size=120)'))
    h = bp.root / "chapters/01/pages/p003.py"
    h.write_text(h.read_text().replace('page.balloon("l4", at=(800, 200), panel="c-1")',
                                       'page.balloon("l4", at=(500, 700), panel="c-1")'))
    R = B.check_chapter(bp, "01")
    c = codes(R)
    for k in ("panel-order", "balloon-order", "balloon-beat", "reveal-not-first-after-turn", "focal-covered"):
        assert k in c, k
    assert "bleed-inside" in codes(R, ("info",))
    # p001 alone, then [p002 p003]: l4 lettered on p002 (conceals nothing) is fine, but drop it everywhere:
    h.write_text(h.read_text().replace('    page.balloon("l4", at=(500, 700), panel="c-1")\n', ""))
    g.write_text(PAGE_B)
    R = B.check_chapter(bp, "01")
    assert "line-not-lettered" in codes(R)


def test_panel_too_small_for_balloons(bp):
    g = bp.root / "chapters/01/pages/p002.py"
    g.write_text(PAGE_B.replace('page.panel("b-1", one, beat="b2")',
                                'page.panel("b-1", Path.rect(500, 600, 160, 120), beat="b2")')
                 .replace("def build", "from mangakit.geometry import Path\n\ndef build")
                 .replace('at=(600, 300)', 'at=(580, 660)'))
    R = B.check_chapter(bp, "01")
    assert {"panel-too-small", "panel-crowded"} & set(codes(R, ("error", "warn", "info")))


def test_sightline_against_flow(bp):
    w(bp.root, "art/roughs/rough-ann.py", SKETCH.replace('facing="left", pose="stand", look=(20, 150)',
                                                         'facing="right", pose="stand", look=(600, 150)'))
    make_rough(bp, "rough-ann")
    R = B.check_chapter(bp, "01")
    assert "sightline-against-flow" in codes(R, ("info",))


# ---------------------------------------------------------------- plan
def test_plan_keeps_ids_places_reveal_after_turn_and_never_reuses(bp):
    st = bp.root / "story"
    # a new beat b4 (reveal of a second concealed fact) and a new line; b2's page will be redrawn later
    w(bp.root, "story/canon.yaml", CANON.replace("facts:\n", "facts:\n- {id: ann-knew, about: [ann]}\n"))
    w(bp.root, "story/beats.yaml", BEATS.replace("present: [ann]}\n- {id: b3", "present: [ann], reader: {conceals: [ann-knew]}}\n- {id: b3")
      + "- {id: b4, chapter: '01', summary: Ann smiles., location: hall, present: [ann], reader: {knows: [ann-knew]}}\n")
    w(bp.root, "story/script.yaml", SCRIPT + "- {id: l5, beat: b4, kind: speech, speaker: ann, text: I knew.}\n")
    r = B.plan(bp, "01", write=True, stubs=True)
    pages = {p["id"]: p for p in r["plan"]["pages"]}
    assert [p["id"] for p in pages["p001"]["panels"]] == ["a1", "a2"]          # drawn ids kept
    assert r["added"] == ["p005/b4"]                                            # p004 would face p003: next turn
    assert pages["p005"]["after_turn"] and pages["p004"]["panels"] == []
    assert pages["p005"]["panels"][0]["lines"] == ["l5"] and pages["p005"]["panels"][0]["reveals"] == ["ann-knew"]
    assert (bp.root / "chapters/01/pages/p005.py").exists()
    assert yaml.safe_load((bp.root / "chapters/01/chapter.yaml").read_text())["pages"][-1] == "p005"
    page, _ = load_page(bp, "p005")                                              # stub builds and letters l5
    assert "b4" in [p.id for p in page.panels.values()] and render_page(page, "rough").exists()
    # retire b4 (story drops it): its id is never handed out again
    w(bp.root, "story/beats.yaml", yaml.safe_dump({"beats": yaml.safe_load((st / "beats.yaml").read_text())["beats"][:3]}))
    (bp.root / "chapters/01/pages/p005.py").unlink()
    r = B.plan(bp, "01", write=True)
    assert "b4" in [x["id"] for x in r["plan"]["retired"]]
    w(bp.root, "story/beats.yaml", (st / "beats.yaml").read_text() +
      "- {id: b4, chapter: '01', summary: again, location: hall, present: [ann]}\n")
    r = B.plan(bp, "01", write=True)
    assert any(x.endswith("/b4-2") for x in r["added"])


# ---------------------------------------------------------------- alternates
def test_alternates_compare_and_promote(bp):
    f = B.alt_create(bp, "p001", "b")
    f.write_text(PAGE_A.replace("L.rows([1, 1])", "L.rows([2, 1])"))
    page, _ = load_page(bp, "p001", alt="b")
    assert page.alt == "b" and "p001.alt-b" in str(render_page(page, "rough"))
    r = B.compare(bp, ["current", "b"], "01")
    assert Image.open(r["png"]).height > 500 and set(r["summary"]) == {"current", "b"}
    with pytest.raises(MangakitError):
        B.promote(bp, "b", "01", reason="")                                    # needs a reason
    # an alternate that renames a referenced panel is refused
    jid = Jobs(bp).request("p001", "a2", "x-art", auto_style=False)
    g = B.alt_create(bp, "p001", "c")
    g.write_text(PAGE_A.replace('"a2"', '"a2-new"'))
    r = B.promote(bp, "c", "01", reason="try")
    assert not r["promoted"] and r["blocked"] and r["dropped"][0]["jobs"] == [jid]
    # moving a panel to another page is allowed and reported; old source archived; log written
    B.alt_create(bp, "p001", "d").write_text(PAGE_A.replace('    b = page.panel("a2", low, beat="b1")\n', ""))
    B.alt_create(bp, "p002", "d").write_text(PAGE_B.replace('    page.panel("b-1", one, beat="b2")',
                                                            '    t, u = L.rows([1, 1])\n    page.panel("a2", t, beat="b1")\n'
                                                            '    page.panel("b-1", u, beat="b2")'))
    r = B.promote(bp, "d", "01", reason="a2 joins p002")
    assert r["promoted"] and r["moved"] == [{"panel": "a2", "from": "p001", "to": "p002", "jobs": [jid]}]
    assert r["stale_jobs"] and (bp.root / "chapters/01/pages/p001.alt-pre-d.py").exists()
    assert "a2" in [p.id for p in load_page(bp, "p002")[0].panels.values()]
    log = yaml.safe_load((bp.root / "chapters/01/alternates.yaml").read_text())
    assert log["promotions"][-1]["alt"] == "d"
    assert B.promote(bp, "current", "01", reason="keep")["kept"]


def test_board_render_outputs(bp):
    r = B.render_board(bp, "01")
    assert Image.open(r["turns"]).height > Image.open(r["spreads"][0]).height
    assert len(r["spreads"]) == 2 and all(FsP.exists() for FsP in map(__import__("pathlib").Path, r["pages"].values()))
    assert "page turns" in open(r["check"]).read()
