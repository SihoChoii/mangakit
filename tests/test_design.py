"""manga-design: reference identities/variants/views, design check, costume by continuity, art
direction revisions (effective chapter/beat, pins), render pick-up, auto-pinned style cards, sample."""
import json
import textwrap

import pytest
import yaml
from PIL import Image, ImageDraw

from mangakit import design as Dz
from mangakit.assets import Registry
from mangakit.illustrate import Jobs, compact_prompt
from mangakit.project import MangakitError, Project, sha256_file
from mangakit.references import RefRegistry
from mangakit.render import load_page, rebuild, render_page

from test_mangakit import PAGE, drawing, proj, write_page  # noqa: F401  (fixture reuse)


def img(path, size=(400, 300), shade=200):
    im = Image.new("L", size, 255)
    ImageDraw.Draw(im).rectangle([20, 20, size[0] - 20, size[1] - 20], fill=shade, outline=0, width=4)
    im.save(path)
    return path


def w(root, rel, text):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(textwrap.dedent(text))


@pytest.fixture()
def dp(proj):
    pr, tmp = proj
    root = pr.root
    w(root, "story/canon.yaml", """
        characters: [{id: ann, name: Ann, design: ann-design}, {id: bo, name: Bo}]
        props: [{id: key, design: key-design}]
        locations: [{id: hall}]
        facts: []
        initial:
        - {subject: ann, attribute: costume, value: coat}
        - {subject: ann, attribute: location, value: hall}
    """)
    w(root, "story/beats.yaml", """
        beats:
        - {id: b1, chapter: '01', summary: Ann in her coat., location: hall, present: [ann], shows: [key]}
        - {id: b2, chapter: '02', summary: Ann changes into a gown., location: hall, present: [ann]}
    """)
    w(root, "story/script.yaml", """
        lines:
        - {id: l1, beat: b1, kind: speech, speaker: ann, text: "This is a *test* line for the balloon."}
        - {id: l2, beat: b2, kind: caption, text: Later.}
    """)
    w(root, "story/continuity.yaml", "events: [{id: ev-gown, beat: b2, subject: ann, attribute: costume, from: coat, value: gown}]\n")
    write_page(pr, brk=False)
    w(root, "chapters/02/chapter.yaml", "id: '02'\npages: [p001]\n")
    (root / "chapters/02/pages").mkdir(parents=True, exist_ok=True)
    (root / "chapters/02/pages/p001.py").write_text(
        PAGE.replace("{BREAK}", "").replace("{BX}", "700").replace("{SIZE}", "").replace('beat="b1"', 'beat="b2"')
        .replace('page.balloon("l1"', 'page.balloon("l2"'))
    rr = RefRegistry(pr)
    rr.add_ref("ann-design", img(tmp / "a1.png"), kind="character", variant="coat", canon="ann")
    rr.add_view("ann-design", "hand", [10, 10, 110, 90], note="hand only")
    rr.add_ref("ann-design", img(tmp / "a2.png", shade=120), kind="character", variant="gown", select=False)
    rr.add_ref("key-design", img(tmp / "k.png"), kind="prop", variant="brass", canon="key")
    rr.add_ref("ink-a", img(tmp / "s1.png", shade=230), kind="style")
    rr.add_view("ink-a", "lines", [0, 0, 200, 150])
    rr.add_ref("ink-heavy", img(tmp / "s2.png", shade=40), kind="style")
    w(root, "references/direction.yaml", """
        guide: test
        revisions:
        - id: sr-001
          effective: {chapter: '01'}
          rules:
            line-weight: {kind: line-weight, text: thin pen, cards: ['ink-a@v001#lines'], brief: true,
                          render: {styles: {panel-border: {width: 4.5}}}}
            tone-density: {kind: tone-density, text: open whites, cards: ['ink-a'], brief: true}
            cuff: {kind: motif, text: white ribbed cuff, cards: ['ink-a'], scope: [bo]}
            sfx: {kind: sfx, text: outlined, cards: ['ink-a'], render: {sfx: {outline_width: 6.0}}}
    """)
    return Project(root), tmp


def test_spec_grammar_variants_views(dp):
    pr, _ = dp
    rr = RefRegistry(pr)
    assert rr.resolve("ann-design")["version"] == "v001"
    assert rr.resolve("ann-design:gown")["version"] == "v002"
    r = rr.resolve("ann-design#hand")
    assert r["view"]["name"] == "hand" and r["size"] == [100, 80] and Image.open(r["file"]).size == (100, 80)
    with pytest.raises(MangakitError):
        rr.resolve("ann-design@v002#hand")       # views belong to one version
    with pytest.raises(MangakitError):
        rr.add_view("ann-design", "huge", [0, 0, 9999, 10])
    assert rr.variants("ann-design") == {"coat": ["v001"], "gown": ["v002"]}


def test_costume_follows_continuity(dp):
    pr, _ = dp
    assert Dz.design_for(pr, "ann", beat="b1") == "ann-design:coat"
    assert Dz.design_for(pr, "ann", beat="b2", view="hand") == "ann-design:gown#hand"


def codes(pr):
    return sorted(i["code"] for i in Dz.check(pr) if i["severity"] in ("error", "warn"))


def test_design_check(dp):
    pr, _ = dp
    assert codes(pr) == []
    can = yaml.safe_load((pr.root / "story/canon.yaml").read_text())
    can["characters"][1]["design"] = "bo-design"            # missing reference
    can["initial"][0]["value"] = "armor"                     # costume with no variant
    can["props"][0]["design"] = "ann-design"                 # tied to another canon id
    (pr.root / "story/canon.yaml").write_text(yaml.safe_dump(can))
    c = codes(pr)
    assert {"design-missing", "costume-variant-missing", "design-canon-mismatch"} <= set(c)


def test_direction_effective_and_revise_pins(dp):
    pr, tmp = dp
    D = Dz.Direction(pr)
    assert D.effective("01") == "sr-001" and D.effective("02") == "sr-001"
    pinned = D.revise("sr-002", "sr-001", {"chapter": "02"},
                      {"line-weight": {"kind": "line-weight", "text": "heavy brush", "cards": ["ink-heavy"], "brief": True,
                                       "render": {"styles": {"panel-border": {"width": 7.0}}}}})
    assert pinned == ["01=sr-001"]
    D = Dz.Direction(pr)
    assert D.effective("01") == "sr-001" and D.effective("02") == "sr-002"
    rules = D.rules("sr-002")
    assert rules["line-weight"]["text"] == "heavy brush" and rules["tone-density"]["from_revision"] == "sr-001"
    with pytest.raises(MangakitError):
        D.revise("sr-002", "sr-001", {"chapter": "03"}, {})   # append-only
    # beat-level start (unpinned chapter 02): applies from that beat on
    D.revise("sr-003", "sr-002", {"beat": "b2"}, {"tone-density": {"kind": "tone-density", "text": "x", "cards": ["ink-a"]}})
    D = Dz.Direction(pr)
    assert D.effective("02", "b2") == "sr-003" and D.effective("02") == "sr-002"


def test_render_picks_up_revision_and_rebuilds(dp):
    pr, _ = dp
    p1, _ = load_page(pr, "p001")
    before = sha256_file(render_page(p1, "proof", pr.root / "build/a.png"))
    Dz.Direction(pr).revise("sr-002", "sr-001", {"chapter": "02"},
                            {"line-weight": {"kind": "line-weight", "text": "heavy", "cards": ["ink-heavy"],
                                             "render": {"styles": {"panel-border": {"width": 9.0}}}}})
    p1b, _ = load_page(pr, "p001")
    assert sha256_file(render_page(p1b, "proof", pr.root / "build/b.png")) == before   # ch01 keeps sr-001
    p2, _ = load_page(pr, "p001", chapter="02")
    assert p2.style_info["revision"] == "sr-002" and p2.project.style("panel-border")["width"] == 9.0
    out = render_page(p2, "proof", pr.root / "build/c.png")
    man = json.loads(out.with_suffix(".manifest.json").read_text())
    assert man["style"]["revision"] == "sr-002"
    # change the direction afterwards: rebuild still uses the recorded settings
    D = Dz.Direction(pr)
    D.by_id["sr-002"]["rules"]["line-weight"]["render"]["styles"]["panel-border"]["width"] = 2.0
    D.save()
    _, same, _ = rebuild(pr, out.with_suffix(".manifest.json"))
    assert same


def test_sfx_defaults_from_direction(dp):
    pr, _ = dp
    d = yaml.safe_load((pr.root / "references/direction.yaml").read_text())
    d["revisions"][0]["rules"]["sfx"]["render"] = {"sfx": {"outline_width": 11.0, "size": 90}}
    (pr.root / "references/direction.yaml").write_text(yaml.safe_dump(d))
    page, _ = load_page(pr, "p001")
    L = page.text("BAM", at=(300, 300))
    assert L.data["outline_width"] == 11.0
    L2 = page.text("BAM", at=(300, 300), outline_width=3)   # an explicit page choice wins
    assert L2.data["outline_width"] == 3


def test_request_auto_pins_effective_cards(dp):
    pr, _ = dp
    J = Jobs(pr)
    jid = J.request("p001", "a", "thing", designs=["ann#hand"])
    req = yaml.safe_load((J.path(jid) / "request.yaml").read_text())
    assert req["style_revision"]["revision"] == "sr-001"
    assert "cuff" in req["style_revision"]["out_of_scope"]              # scoped to bo; ann's shot skips it
    ids = [(r["id"], r.get("view", {}) and r["view"]["name"]) for r in req["references"]]
    assert ("ann-design", "hand") in ids and ids[-1][0] == "style-cards"  # 2 cards -> one montage slot
    assert "Art direction sr-001" in req["style"] and "white ribbed cuff" not in req["style"]
    assert "hand view only" in compact_prompt(req, 4)
    # chapter 02 after a revision: the new cards
    Dz.Direction(pr).revise("sr-002", "sr-001", {"chapter": "02"},
                            {"line-weight": {"kind": "line-weight", "text": "heavy", "cards": ["ink-heavy"], "brief": True},
                             "tone-density": {"kind": "tone-density", "text": "deep", "cards": ["ink-heavy"], "brief": False}})
    j2 = J.request("p001", "a", "thing", chapter="02", designs=["ann"])
    r2 = yaml.safe_load((J.path(j2) / "request.yaml").read_text())
    assert r2["style_revision"]["revision"] == "sr-002"
    assert [r["id"] for r in r2["references"]] == ["ann-design", "ink-heavy"] and r2["references"][0]["variant"] == "gown"


def test_placeholder_rough_not_sent(dp):
    pr, _ = dp
    f = pr.root / "chapters/01/pages/p001.py"
    f.write_text(f.read_text().replace('art.selected("thing")', 'art.slot(final="nothing-yet")')
                 .replace('source="tip"', 'source=(400, 300)'))
    J = Jobs(pr)
    jid = J.request("p001", "a", "thing", auto_style=False)
    req = yaml.safe_load((J.path(jid) / "request.yaml").read_text())
    assert req["shot_guide"]["rough_is_placeholder"]
    J.call(jid)
    args = json.loads((J.path(jid) / "host-call-1.json").read_text())["arguments"]
    assert not any("rough-crop" in x for x in args["reference_image_paths"])


def test_job_style_superseded_and_art_older(dp):
    pr, tmp = dp
    J = Jobs(pr)
    jid = J.request("p001", "a", "thing", chapter="02")              # pins sr-001 for b2
    Dz.Direction(pr).revise("sr-002", "sr-001", {"beat": "b2"},
                            {"line-weight": {"kind": "line-weight", "text": "heavy", "cards": ["ink-heavy"]}})
    c = [i for i in Dz.check(pr) if i["code"] == "job-style-superseded"]
    assert c and c[0]["where"] == jid
    # accept art made under sr-001 for b2, which now requires sr-002: flagged, not blocked
    J.call(jid)
    vers = J.collect(jid, [img(tmp / "cand.png", (800, 600))])
    J.verdict(jid, vers[0], True, "ok")
    J.select(jid, vers[0], force=True)
    older = [i for i in Dz.check(pr) if i["code"] == "art-style-older"]
    assert older and older[0]["severity"] == "warn"


def test_brief_logs_calls_and_collect(dp):
    pr, tmp = dp
    bid, bd = Dz.brief(pr, "bo-design", "character", "Bo, a tall man", layout="turnaround", refs=["ink-a#lines"],
                       canon="bo", variant="suit")
    args = json.loads((bd / "host-call-1.json").read_text())["arguments"]
    assert "No text" in args["description"] and len(args["reference_image_paths"]) == 1
    Dz.brief_recall(pr, "bo-design", bid)
    ver = Dz.brief_collect(pr, "bo-design", bid, img(tmp / "bo.png"))
    rec = RefRegistry(pr).load("bo-design")
    assert rec["canon"] == "bo" and rec["versions"][ver]["variant"] == "suit" and rec["versions"][ver]["brief"] == bid
    assert Dz.calls(pr)["refs"]["bo-design"]["calls"] == 2


def test_sample_shot(dp):
    pr, _ = dp
    r = Dz.sample(pr, image="thing", revision="sr-001", line="Hello there.", sfx="BAM")
    im = Image.open(r["reading"])
    assert abs(im.height - pr.cfg["render"]["reading_height_px"]) <= 1  # rasterizer rounds
    assert (pr.root / "build/design/sample-sr-001/judge.md").read_text().count("|") > 10
    out = Dz.compare([r, r], pr.root / "build/design/cmp.png")
    assert Image.open(out).width > 2 * im.width
