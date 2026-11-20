"""Story records: check, continuity timeline, reader knowledge, dependencies, impact, glance."""
import textwrap

import pytest
import yaml

from mangakit.checks import run_checks
from mangakit.project import Project, init_project
from mangakit.render import load_page, spread_groups
from mangakit.story import Story, deps, glance, impact, pages_info

CANON = """
characters: [{id: ann, name: Ann}, {id: bo, name: Bo}, {id: cy, name: Cy}]
props: [{id: key, name: brass key}]
locations: [{id: hall, adjacent: [porch]}, {id: porch}, {id: far}]
facts:
- {id: ann-has-key, about: [ann, key]}
- {id: bo-is-thief, about: [bo], keywords: [thief], reveal: unmask}
initial:
- {subject: key, attribute: holder, value: ann}
- {subject: ann, attribute: location, value: hall}
- {subject: bo, attribute: location, value: porch}
- {subject: cy, attribute: location, value: far}
"""
BEATS = """
beats:
- {id: open, summary: Ann holds the key., location: hall, present: [ann], reader: {knows: [ann-has-key]}}
- {id: pass, summary: Ann hands the key out the door., location: hall, present: [ann, bo],
   asserts: [key.holder=bo], reader: {conceals: [bo-is-thief]}}
- {id: unmask, summary: Bo is the thief., location: porch, present: [bo], asserts: [key.holder=bo],
   reader: {knows: [bo-is-thief]}}
"""
SCRIPT = """
lines:
- {id: l1, beat: open, kind: caption, text: Midnight.}
- {id: l2, beat: pass, kind: speech, speaker: ann, text: Take it.}
- {id: l3, beat: pass, kind: speech, speaker: bo, text: Thanks.}
- {id: l4, beat: unmask, kind: speech, speaker: bo, text: Mine now.}
- {id: l5, beat: unmask, kind: sfx, text: CLICK}
"""
CONT = """
events:
- {id: ev-pass, beat: pass, subject: key, attribute: holder, from: ann, value: bo}
"""
THREADS = """
threads:
- {id: t-who, setup: {beat: pass}, payoff: {beat: unmask}, reveals: bo-is-thief}
"""
PAGE = '''
from mangakit import Path
def build(page, art, script):
    for i, (pid, beat) in enumerate(PANELS):
        p = page.panel(pid, Path.rect(55, 60 + i * 480, 980, 440), beat=beat)
        page.stroke(p.path, style="panel-border")
    for lid, pid, y in BALLOONS:
        page.balloon(lid, at=(500, y), panel=pid)
    for lid, pid in TEXTS:
        page.text(None, at=(300, 1300), line=lid, panel=pid)
    return page
'''


def w(root, rel, text):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(textwrap.dedent(text))


@pytest.fixture()
def sp(tmp_path):
    root = init_project(tmp_path / "s", "s")
    for n, t in (("canon", CANON), ("beats", BEATS), ("script", SCRIPT), ("continuity", CONT), ("threads", THREADS)):
        w(root, f"story/{n}.yaml", t)
    pages = root / "chapters" / "01" / "pages"
    (pages / "p001.py").unlink()
    w(root, "chapters/01/pages/p001.py", "PANELS=[('a','open'),('b','pass')]\nBALLOONS=[('l1','a',120),('l2','b',600),"
      "('l3','b',800)]\nTEXTS=[]\n" + PAGE)
    w(root, "chapters/01/pages/p002.py", "PANELS=[('c','unmask')]\nBALLOONS=[('l4','c',200)]\nTEXTS=[('l5','c')]\n" + PAGE)
    w(root, "chapters/01/chapter.yaml", "id: '01'\npages: [p001, p002]\npairing: odd-start\n")
    return Project(root)


def codes(p, **kw):
    return sorted(i["code"] for i in Story(p, **kw).check(pages_info(p)) if i["severity"] != "info")


def edit(p, name, fn):
    f = p.root / "story" / f"{name}.yaml"
    d = yaml.safe_load(f.read_text())
    fn(d)
    f.write_text(yaml.safe_dump(d, sort_keys=False))


def test_clean_story_and_timeline(sp):
    assert codes(sp) == []
    st = Story(sp)
    assert st.state_at("open")["key.holder"] == "ann"
    assert st.state_at("pass")["key.holder"] == "bo"
    k = st.knowledge()
    assert k["pass"]["concealed"] == ["bo-is-thief"] and "bo-is-thief" in k["unmask"]["known"]
    # odd-start: p001 alone, p002 alone in the next spread -> the reveal is behind a page turn
    assert spread_groups(sp, ["p001", "p002"]) == [["p001"], ["p002"]]


def test_leak_and_unknown_speaker(sp):
    edit(sp, "script", lambda d: d["lines"][2].update(text="Thanks, says the thief."))
    edit(sp, "script", lambda d: d["lines"][1].update(speaker="zed"))
    c = codes(sp)
    assert "leak" in c and "unknown-speaker" in c


def test_speaker_absent_and_beat_without_lines(sp):
    edit(sp, "script", lambda d: d["lines"].__setitem__(0, {**d["lines"][0], "kind": "speech", "speaker": "bo"}))
    c = codes(sp)
    assert "speaker-absent" in c
    edit(sp, "script", lambda d: d["lines"].pop(0))
    assert "beat-without-lines" in codes(sp)


def test_continuity_contradictions(sp):
    # handing the key back at unmask: Ann is not there, and the beat depicts Bo holding it
    edit(sp, "continuity", lambda d: d["events"].append(
        {"id": "ev-back", "beat": "unmask", "subject": "key", "attribute": "holder", "from": "ann", "value": "ann"}))
    c = codes(sp)
    assert c.count("contradiction") >= 3  # wrong 'from', giver absent, assert fails
    # two places at once: Cy present in the hall while continuity keeps her far away
    edit(sp, "continuity", lambda d: d["events"].pop())
    edit(sp, "beats", lambda d: d["beats"][0]["present"].append("cy"))
    assert "two-places" in codes(sp)


def test_transfer_out_of_reach(sp):
    edit(sp, "canon", lambda d: d["initial"].__setitem__(2, {"subject": "bo", "attribute": "location", "value": "far"}))
    assert "contradiction" in codes(sp)


def test_threads(sp):
    edit(sp, "threads", lambda d: d["threads"].extend([
        {"id": "t-open", "setup": {"line": "l2"}},
        {"id": "t-orphan", "payoff": {"beat": "unmask"}},
        {"id": "t-back", "setup": {"beat": "unmask"}, "payoff": {"beat": "open"}},
        {"id": "t-later", "setup": {"beat": "open"}, "deferred": "chapter 02"},
        {"id": "t-early", "setup": {"beat": "unmask"}, "payoff": {"beat": "unmask"}, "reveals": "ann-has-key"}]))
    c = codes(sp)
    for code in ("setup-without-payoff", "payoff-without-setup", "payoff-before-setup", "reveal-before-setup"):
        assert code in c, code
    assert any(i["code"] == "deferred-payoff" for i in Story(sp).check())


def test_conceal_after_known_and_reveal_on_facing_page(sp):
    w(sp.root, "chapters/01/chapter.yaml", "id: '01'\npages: [p001, p002]\npairing: even-start\n")
    assert "reveal-on-facing-page" in codes(sp)
    edit(sp, "beats", lambda d: d["beats"][2]["reader"].update(conceals=["ann-has-key"]))
    assert "conceal-after-known" in codes(sp)


def test_sfx_line_counts_as_lettered(sp):
    page, _ = load_page(sp, "p002")
    assert not [i for i in run_checks(page) if i["code"] == "unlettered-line"]
    assert any(L.kind == "text" and L.data["text"] == "CLICK" for L in page.layers)


def test_deps_and_impact_line(sp):
    D = deps(sp)
    assert D["beats"]["pass"]["panels"] == ["p001/b"]
    assert D["lines"]["l5"]["sfx_text"] == ["p002/c"] and D["lines"]["l2"]["balloons"] == ["p001/b"]
    r = impact(sp, "l2", new_text="Take it now. " * 60)
    assert any("p001/b" in list(x.values())[0] for x in r["compose"])
    assert r["hypothetical"]["pages"]["p001"] != "balloon fits; no page issues for this line"
    r = impact(sp, "l3", new_text="Thanks, I'm the thief.")
    assert [i["code"] for i in r["hypothetical"]["new_issues"]] == ["leak"]


def test_impact_fact_different_recipient(sp):
    r = impact(sp, "ev-pass", new_value="cy")
    assert r["fact"]["in_effect"] == ["pass", "unmask"]
    story = " ".join(list(x.values())[0] for x in r["story"])
    assert "l3" in story and "l4" in story          # Bo's lines depend on Bo holding the key
    assert any("p002/c" in list(x.values())[0] for x in r["board"])
    new = [i["code"] for i in r["hypothetical"]["new_issues"]]
    assert "contradiction" in new                   # Cy is not there; beats depict Bo holding it
    # the hypothetical did not touch the files
    assert Story(sp).state_at("unmask")["key.holder"] == "bo"
    r = impact(sp, "pass")
    assert r["kind"] == "beat" and any("ev-pass" in list(x.values())[0] for x in r["story"])


def test_glance(sp):
    out = glance(sp)
    t = out.read_text()
    assert "## 2. pass" in t and "concealed** bo-is-thief" in t and "page turn" in t
    assert "key.holder=bo" in t


def test_init_story_templates_check_clean(tmp_path):
    root = init_project(tmp_path / "n", "n")
    p = Project(root)
    assert [i for i in Story(p).check(pages_info(p)) if i["severity"] == "error"] == []
