"""manga-review: cold-read packet (no metadata), locked answers, scoring against the story, aggregate
technical pass with owners, art-vs-story sheet, findings tied to page revisions, recheck
(verified / survived / needs-verdict), editorial alternatives, metrics."""
import textwrap

import pytest
import yaml
from PIL import Image

from mangakit import review as RV
from mangakit.project import MangakitError, Project, init_project
from mangakit.rough import make_rough

CANON = """
characters: [{id: ann, name: Ann}, {id: bo, name: Bo}]
props: [{id: key, name: brass key}]
locations: [{id: hall}]
facts:
- {id: bo-did-it, statement: Bo took the key., about: [bo], keywords: [thief]}
initial:
- {subject: ann, attribute: location, value: hall}
- {subject: bo, attribute: location, value: hall}
- {subject: key, attribute: holder, value: ann}
"""
BEATS = """
beats:
- {id: b1, chapter: '01', summary: Ann alone., location: hall, present: [ann], shows: [key], reader: {conceals: [bo-did-it]}}
- {id: b2, chapter: '01', summary: Ann gives the key away., location: hall, present: [ann, bo], shows: [key]}
- {id: b3, chapter: '01', summary: Bo smiles., location: hall, present: [bo], shows: [key], reader: {knows: [bo-did-it]}}
"""
CONT = """
events:
- {id: ev-key, beat: b2, subject: key, attribute: holder, from: ann, value: bo}
"""
SCRIPT = """
lines:
- {id: l1, beat: b1, kind: caption, text: Night.}
- {id: l2, beat: b1, kind: speech, speaker: ann, text: "Who is there?"}
- {id: l3, beat: b2, kind: speech, speaker: ann, text: "Take it."}
- {id: l4, beat: b2, kind: sfx, text: CLINK}
- {id: l5, beat: b3, kind: speech, speaker: bo, text: Mine now.}
"""
SKETCH = '''
SIZE = (600, 400)
def sketch(s):
    s.figure("ann", feet=(420, 380), height=300, facing="left", pose="stand")
    s.focal(s.landmarks["ann-head"], "Ann")
'''
P1 = '''
def build(page, art, script):
    L = page.layout()
    (one,) = L.rows([1])
    a = page.panel("a1", one, beat="b1")
    d = art.slot(final="ann-final", rough="rough-ann")
    p = a.fit(d)
    page.image(d, transform=p, clip=a.path)
    page.borders()
    page.balloon("l1", shape="box", at=(900, 100), panel="a1")
    page.balloon("l2", at=(600, 300), tail_to=p.map("ann-mouth"), panel="a1")
    return page
'''
P2 = '''
def build(page, art, script):
    L = page.layout()
    (one,) = L.rows([1])
    page.panel("b-1", one, beat="b2")
    page.borders()
    page.balloon("l3", at=(700, 300), panel="b-1")
    page.text(None, at=(400, 900), font="sfx", size=SFX, panel="b-1", line="l4")
    return page
'''
P3 = '''
def build(page, art, script):
    L = page.layout()
    page.panel("c-1", L.live, beat="b3")
    page.borders()
    page.focal((500, 700), panel="c-1", label="Bo")
    page.balloon("l5", at=(800, 200), panel="c-1")
    return page
'''


def w(root, rel, text):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(textwrap.dedent(text))
    return f


@pytest.fixture()
def rp(tmp_path):
    root = init_project(tmp_path / "rp", "t")
    w(root, "story/canon.yaml", CANON)
    w(root, "story/beats.yaml", BEATS)
    w(root, "story/continuity.yaml", CONT)
    w(root, "story/script.yaml", SCRIPT)
    w(root, "chapters/01/chapter.yaml", "id: '01'\npairing: even-start\npages: [p001, p002, p003]\n")
    w(root, "chapters/01/pages/p001.py", P1)
    w(root, "chapters/01/pages/p002.py", P2.replace("SFX", "200"))
    w(root, "chapters/01/pages/p003.py", P3)
    w(root, "art/roughs/rough-ann.py", SKETCH)
    pr = Project(root)
    make_rough(pr, "rough-ann")
    return pr


GOOD = {
    "reader": "t", "characters": [{"label": "girl"}, {"label": "tall man"}, {"label": "key"}],
    "speakers": [{"page": 1, "words": "Night", "speaker": "caption"}, {"page": 1, "words": "who is there", "speaker": "girl"},
                 {"page": 2, "words": "take it", "speaker": "girl"}, {"page": 2, "words": "clink", "speaker": "sound"},
                 {"page": 3, "words": "mine now", "speaker": "tall man"}],
    "transfers": [{"object": "key", "from": "girl", "to": "tall man", "page": 2}],
    "holder_end": [{"object": "key", "holder": "tall man"}],
    "eye_path": {1: ["girl"], 2: ["balloon"], 3: ["man"]},
    "surprises": [{"page": 3, "what": "the tall man is smug"}],
    "reveals": [{"page": 3, "what": "the tall man had planned it", "after_turn": True}],
    "unclear": [{"page": 2, "where": "middle", "what": "what is the noise?"}],
}
KEY = {"identify": {"girl": "ann", "tall man": "bo", "key": "key"},
       "triage": {0: {"owner": "compose", "page": "p002", "panel": "b-1", "severity": "info", "intended": "a key dropping"}},
       "judge": {"eye_path.1": {"result": "ok"}}}


def cold(rp, answers, key=KEY):
    r = RV.packet(rp, "01")
    rd = rp.root / "reviews/ch01/cold" / r["dir"].split("/")[-1]
    f = rd / "my-answers.yaml"
    f.write_text(yaml.safe_dump(answers))
    RV.record_answers(rp, f, "01")
    (rd / "key.yaml").write_text(yaml.safe_dump(key))
    return rd, RV.score(rp, "01")


# ---------------------------------------------------------------- packet
def test_packet_is_clean_and_ordered(rp):
    r = RV.packet(rp, "01")
    pk = rp.root / r["packet"]
    kinds = [s["kind"] for s in r["sequence"]]
    assert kinds == ["spread", "page-turn", "spread"]
    files = sorted(p.name for p in pk.rglob("*") if p.is_file())
    assert files == ["01-spread.png", "02-page-turn.png", "03-spread.png", "1.png", "2.png", "3.png",
                     "answers.yaml", "questionnaire.md"]
    assert RV.packet_leaks(rp, pk) == []
    rec = yaml.safe_load((rp.root / "reviews/ch01/cold/r01/round.yaml").read_text())
    assert [rec["pages"][k]["page"] for k in ("1", "2", "3")] == ["p001", "p002", "p003"]
    assert len(rec["pages"]["1"]["rev"]) == 12
    # spreads at reading size; the earlier page sits on the right (rtl)
    im = Image.open(pk / "01-spread.png")
    page1 = Image.open(pk / "pages/1.png")
    assert im.height == page1.height + 56 and im.width == 2 * page1.width + 6
    (pk / "b2-notes.txt").write_text("x")
    assert RV.packet_leaks(rp, pk)                       # a file named after a beat is a leak
    assert RV.packet(rp, "01", pages=["p003"])["sequence"] == [{"file": "01-spread.png", "kind": "spread", "pages": [3]}]


# ---------------------------------------------------------------- score
def test_score_correct_read_files_only_triage(rp):
    rd, S = cold(rp, GOOD)
    q = S["questions"]
    assert (q["speakers"]["ok"], q["transfers"]["ok"], q["holder_end"]["ok"], q["reveals"]["ok"]) == (5, 1, 1, 1)
    assert q["eye_path"]["unjudged"] == 2 and q["surprise"]["ok"] == 1
    F = RV.load_findings(rp)
    assert [f["code"] for f in F] == ["cold-unclear"] and F[0]["owner"] == "compose" and F[0]["panel"] == "b-1"
    assert F[0]["revision"]["rev"] and F[0]["crop"] and (rp.root / F[0]["crop"]).exists()
    assert "score.md" in [p.name for p in rd.iterdir()]


def test_score_mismatches_become_findings(rp):
    bad = yaml.safe_load(yaml.safe_dump(GOOD))
    bad["speakers"][2]["speaker"] = "tall man"                 # wrong speaker
    bad["speakers"][3], bad["speakers"][4] = bad["speakers"][4], bad["speakers"][3]   # out of order
    bad["transfers"] = []                                       # missed the transfer
    bad["holder_end"] = [{"object": "key", "holder": "girl"}]
    bad["reveals"] = [{"page": 1, "what": "the tall man is the thief", "after_turn": False}]   # early
    rd, S = cold(rp, bad)
    codes = {f["code"] for f in RV.load_findings(rp)}
    assert {"cold-speaker", "cold-order", "cold-transfer-missed", "cold-holder-end", "cold-reveal-early"} <= codes
    sp = next(f for f in RV.load_findings(rp) if f["code"] == "cold-speaker")
    assert sp["page"] == "p002" and sp["owner"] == "board" and "tall man" in sp["observed"]


def test_answers_are_locked_before_the_key(rp):
    r = RV.packet(rp, "01")
    rd = rp.root / "reviews/ch01/cold/r01"
    f = rd / "a.yaml"
    f.write_text(yaml.safe_dump(GOOD))
    RV.record_answers(rp, f, "01")
    with pytest.raises(MangakitError, match="key.yaml"):
        RV.score(rp, "01")                                      # writes the key template
    assert (rd / "key.template.yaml").exists()
    (rd / "key.yaml").write_text(yaml.safe_dump(KEY))
    (rd / "answers.yaml").write_text(yaml.safe_dump(dict(GOOD, reader="edited")))
    with pytest.raises(MangakitError, match="changed after"):
        RV.score(rp, "01")
    (rd / "answers.yaml").write_text(f.read_text())
    RV.score(rp, "01")
    with pytest.raises(MangakitError, match="key was already written"):
        RV.record_answers(rp, f, "01")
    # the pages changed since the packet: scoring refuses without --force
    w(rp.root, "chapters/01/pages/p002.py", P2.replace("SFX", "120"))
    with pytest.raises(MangakitError, match="changed since the packet"):
        RV.score(rp, "01")


# ---------------------------------------------------------------- tech
def test_tech_dedupes_and_assigns_owners(rp):
    w(rp.root, "chapters/01/pages/p003.py", P3.replace('    page.balloon("l5", at=(800, 200), panel="c-1")\n', ""))
    w(rp.root, "chapters/01/pages/p002.py", P2.replace("SFX", "60"))
    T = RV.tech(rp, "01")
    by = {m["code"]: m for m in T["issues"]}
    assert by["line-not-lettered"]["tools"] == ["board", "page"] and by["line-not-lettered"]["owner"] == "board"
    assert by["sfx-small"]["owner"] == "compose" and by["needs-art"]["owner"] == "illustrate"
    assert T["raw"] > len(T["issues"])
    F = RV.load_findings(rp)
    assert len({f["key"] for f in F}) == len(F)
    again = RV.tech(rp, "01")
    assert {how for _, how, _ in again["filed"]} == {"reproduced"}
    nid = next(f["id"] for f in F if f["code"] == "needs-art")
    RV.set_status(rp, nid, "wont-fix", note="the rough is the final look")
    third = RV.tech(rp, "01")
    assert (nid, "wont-fix") in [(i, h) for i, h, _ in third["filed"]] and len(RV.load_findings(rp)) == len(F)


def test_finding_survives_only_across_revisions(rp):
    w(rp.root, "chapters/01/pages/p002.py", P2.replace("SFX", "60"))
    RV.tech(rp, "01")
    f = next(x for x in RV.load_findings(rp) if x["code"] == "sfx-small")
    assert f["survived"] == 0
    w(rp.root, "chapters/01/pages/p002.py", P2.replace("SFX", "62"))          # a new revision, still small
    RV.tech(rp, "01")
    f = next(x for x in RV.load_findings(rp) if x["code"] == "sfx-small")
    assert f["survived"] == 1 and [c["result"] for c in f["checks"]] == ["filed", "survived"]


# ---------------------------------------------------------------- recheck
def test_recheck_verified_survived_needs_verdict(rp):
    w(rp.root, "chapters/01/pages/p002.py", P2.replace("SFX", "60"))
    RV.tech(rp, "01")
    a = RV.add(rp, "01", page="p001", panel="a1", code="visual", severity="warn", owner="board",
               observed="tail short", intended="tail reaches Ann", probe={"kind": "tail-gap", "line": "l2", "max": 1})[0]
    b = RV.add(rp, "01", page="p002", panel="b-1", code="visual", severity="info", owner="illustrate",
               observed="the key is hard to see", intended="the key reads")[0]
    sfx = next(x for x in RV.load_findings(rp) if x["code"] == "sfx-small")["id"]
    with pytest.raises(MangakitError):
        RV.set_status(rp, sfx, "fixed")                                        # needs a note
    RV.set_status(rp, sfx, "fixed", note="size 60 -> 400")
    w(rp.root, "chapters/01/pages/p002.py", P2.replace("SFX", "400"))
    rep = RV.recheck(rp, "01")
    res = {r["id"]: r["result"] for r in rep["rows"]}
    assert res[sfx] == "verified"
    assert res[b] == "needs-verdict"                      # page changed, no machine check
    assert res[a] == "unchanged"                          # p001 not revised; probe still holds
    assert any(r["result"] == "survived" for r in rep["rows"] if r["code"] == "needs-art") is False
    assert (rp.root / "reviews/ch01/recheck").exists() and rep["spreads"]
    RV.verdict(rp, b, "survived", note="still hard to see")
    f = next(x for x in RV.load_findings(rp) if x["id"] == b)
    assert f["survived"] == 1 and f["status"] == "open"
    # survived: a machine-checked finding on a page that changed but still fails
    w(rp.root, "chapters/01/pages/p001.py", P1.replace("at=(600, 300)", "at=(560, 300)"))
    rep = RV.recheck(rp, "01")
    row = next(r for r in rep["rows"] if r["id"] == a)
    assert row["result"] == "survived" and "tail tip" in row["detail"]


def test_regression_reopens_a_verified_finding(rp):
    w(rp.root, "chapters/01/pages/p002.py", P2.replace("SFX", "60"))
    RV.tech(rp, "01")
    w(rp.root, "chapters/01/pages/p002.py", P2.replace("SFX", "400"))
    RV.recheck(rp, "01")
    f = next(x for x in RV.load_findings(rp) if x["code"] == "sfx-small")
    assert f["status"] == "verified"
    w(rp.root, "chapters/01/pages/p002.py", P2.replace("SFX", "50"))
    r = RV.tech(rp, "01")
    assert (f["id"], "reopened", f["key"]) in r["filed"]


# ---------------------------------------------------------------- editorial, art, metrics
def test_editorial_keeps_alternatives(rp):
    fid = RV.add(rp, "01", page="p003", code="visual", severity="warn", owner="story",
                 observed="reveal is vague", intended="Bo is the thief")[0]
    with pytest.raises(MangakitError):
        RV.editorial(rp, fid, [{"name": "a"}])
    RV.editorial(rp, fid, [{"name": "caption", "owner": "story"}, {"name": "keep", "keep": True}])
    with pytest.raises(MangakitError):
        RV.decide(rp, fid, "caption", "")
    f = RV.decide(rp, fid, "keep", "the vagueness is the point")
    assert f["status"] == "wont-fix" and [a["name"] for a in f["alternatives"]] == ["caption", "keep"]
    assert f["decision"]["choice"] == "keep"


def test_art_sheet_lists_carried_props_and_files_verdicts(rp, tmp_path):
    v = tmp_path / "v.yaml"
    v.write_text(yaml.safe_dump([{"page": "p001", "panel": "a1", "ok": False, "owner": "board",
                                  "observed": "no key in Ann's hand", "intended": "Ann holds the key"}]))
    r = RV.art_sheet(rp, "01", verdicts=v)
    rows = {f"{x['page']}/{x['panel']}": x for x in r["rows"]}
    assert rows["p002/b-1"]["props"][0]["holder"] == "ann -> bo"
    assert rows["p001/a1"]["art"] == ["rough-ann@v001 (rough)"] and not rows["p001/a1"]["final"]
    assert Image.open(r["png"]).height > 3 * 300
    F = RV.load_findings(rp)
    assert F[0]["code"] == "art-contradicts-story" and F[0]["source"] == "art-story" and F[0]["panel"] == "a1"


def test_metrics(rp):
    cold(rp, GOOD)
    m = RV.metrics(rp, "01")
    assert m["cold_read"]["ok"] == m["cold_read"]["total"] and m["findings"] == 1
    assert "illustration_calls_per_accepted_panel" in m and m["findings_survived_a_revision"] == 0
