"""manga-direct: concurrency-safe ids, work units derived from project state, stale detection on
input change, resume after an interrupted run, creator gates, frozen proof sets, context packets."""
import multiprocessing as mp
import os

import pytest
import yaml

from mangakit import publish as PB
from mangakit import work as W
from mangakit.ids import claim_dir, claim_file
from mangakit.project import MangakitError, Project

from test_review import rp, w  # noqa: F401  (fixture)


def _claim(args):
    d, n = args
    return [claim_file(d, "w-", ".yaml").name for _ in range(n)]


def test_ids_unique_under_concurrency(tmp_path):
    with mp.get_context("fork").Pool(6) as pool:
        names = sum(pool.map(_claim, [(tmp_path, 15)] * 6), [])
    assert len(names) == 90 == len(set(names))
    assert sorted(names)[-1] == "w-0090.yaml"
    (tmp_path / "w-0042.yaml").unlink()              # a gap never gets reused: max + 1
    assert claim_file(tmp_path, "w-", ".yaml").name == "w-0091.yaml"
    assert claim_dir(tmp_path / "jobs", "job-").name == "job-0001"


def _by(units, **kw):
    return [u for u in units if all(u.get(k) == v or u.get("target", {}).get(k) == v for k, v in kw.items())]


def test_plan_derives_renders_art_and_checks(rp):
    r = W.plan(rp, "01")
    U = r["units"]
    assert len(_by(U, kind="render")) == 6                      # 3 pages x proof/reading, all missing
    art = _by(U, kind="art")
    assert [u["target"]["page"] + "/" + u["target"]["panel"] for u in art] == ["p001/a1"]
    assert art[0]["status"] == "queued" and art[0]["image_calls"] == 1
    rc = _by(U, kind="recheck")[0]
    assert set(rc["after"]) == {u["id"] for u in _by(U, kind="render")}
    # idempotent: planning again creates nothing
    r2 = W.plan(rp, "01")
    assert r2["created"] == [] and r2["stale"] == []


def test_run_then_dialogue_edit_marks_only_lettering_stale(rp):
    W.plan(rp, "01")
    W.run(rp, log=lambda *a: None)
    U = W.load_units(rp)
    assert all(u["status"] == "done" for u in _by(U, kind="render"))
    assert W.plan(rp, "01")["stale"] == []
    s = (rp.root / "story/script.yaml").read_text().replace("Take it.", "Take it, quick.")
    (rp.root / "story/script.yaml").write_text(s)
    r = W.plan(rp, "01")
    assert r["changes"]["lines"] == ["l3"]
    stale = {(W.get_unit(rp, i)["kind"], W.get_unit(rp, i)["target"].get("page")) for i in r["stale"]}
    assert ("render", "p002") in stale and not any(p in ("p001", "p003") for k, p in stale if k == "render")
    new = [W.get_unit(rp, i) for i in r["created"]]
    assert any(u["kind"] == "reletter" and u["target"]["line"] == "l3" for u in new)
    assert not any(u["kind"] == "art" for u in new)              # a dialogue edit commissions no art
    assert sum(u["image_calls"] for u in new) == 0
    # rerunning clears it; the reletter unit (event-derived) survives later plans until done
    W.run(rp, log=lambda *a: None)
    r = W.plan(rp, "01")
    assert r["stale"] == []
    assert _by(W.load_units(rp), kind="reletter")[0]["status"] == "done"


def test_fact_change_creates_inspect_units(rp):
    W.plan(rp, "01")
    w(rp.root, "story/continuity.yaml", """
    events:
    - {id: ev-key, beat: b2, subject: key, attribute: holder, from: ann, value: ann}
    """)
    r = W.plan(rp, "01")
    new = [W.get_unit(rp, i) for i in r["created"]]
    assert r["changes"]["continuity"] == ["ev-key"]
    assert any(u["skill"] == "board" and u["kind"] == "inspect" for u in new)
    assert any(u["kind"] == "check" and u["skill"] == "story" for u in new)


def test_resume_after_interrupt(rp):
    W.plan(rp, "01")
    W.run(rp, limit=2, log=lambda *a: None)                     # finished two renders
    todo = [u for u in W.runnable(rp) if u.get("exec")]
    a, b = todo[0], todo[1]
    W.start(rp, a["id"])                                        # killed before writing anything
    u = W.get_unit(rp, a["id"]); u["pid"] = 999999; W.save_unit(rp, u)
    from mangakit.render import load_page, render_page
    t = b["target"]
    page, _ = load_page(rp, t["page"], chapter="01")
    render_page(page, t["view"])                                # killed after the output, before `done`
    W.start(rp, b["id"])
    u = W.get_unit(rp, b["id"]); u["pid"] = 999999; W.save_unit(rp, u)
    r = W.resume(rp, "01")
    assert set(r["interrupted"]) == {a["id"], b["id"]}
    assert r["recovered"] == [b["id"]] and r["requeued"] == [a["id"]]
    assert a["id"] in r["todo_auto"] and b["id"] not in r["todo_auto"]
    W.run(rp, log=lambda *a: None)
    assert all(u["status"] == "done" for u in _by(W.load_units(rp), kind="render"))


def test_creator_gates(rp):
    cfg = yaml.safe_load((rp.root / "project.yaml").read_text())
    cfg["creator"] = {"gates": {"lettered_boards": True, "final_version": True}}
    (rp.root / "project.yaml").write_text(yaml.safe_dump(cfg))
    pr = Project(rp.root)
    r = W.plan(pr, "01")
    art = _by(r["units"], kind="art")[0]
    assert art["status"] == "needs-creator" and art["gate"] == "lettered_boards"
    with pytest.raises(MangakitError):
        W.approve(pr, "lettered_boards", "01", by="direct", note="looks fine")   # the director cannot approve
    with pytest.raises(MangakitError):
        W.approve(pr, "lettered_boards", "01", by="Creator", note="")
    with pytest.raises(MangakitError):
        PB.publish(pr, "01", "final", final=True)
    W.approve(pr, "lettered_boards", "01", by="Creator", note="boards ok, go to art")
    W.plan(pr, "01")
    assert W.get_unit(pr, art["id"])["status"] == "queued"              # the approval releases it
    assert _by(W.load_units(pr), kind="art")[0]["history"][-1]["note"].startswith("gate lettered_boards")


def test_publish_rebuilds_byte_identical_after_edits(rp):
    S = PB.publish(rp, "01", "first")
    assert [e["page"] for e in S["pages"]] == ["p001", "p002", "p003"]
    with pytest.raises(MangakitError):
        PB.publish(rp, "01", "first")                          # frozen sets are never overwritten
    s = (rp.root / "story/script.yaml").read_text().replace("Mine now.", "Mine, now and always.")
    (rp.root / "story/script.yaml").write_text(s)
    src = rp.root / "chapters/01/pages/p002.py"
    src.write_text(src.read_text().replace("at=(700, 300)", "at=(650, 320)"))
    R = PB.rebuild(rp, "first", "01")
    assert R["identical"] and len(R["rows"]) == 6
    S2 = PB.publish(rp, "01")
    p3 = {e["page"]: e for e in S2["pages"]}["p003"]["views"]["reading"]["sha256"]
    assert p3 != {e["page"]: e for e in S["pages"]}["p003"]["views"]["reading"]["sha256"]
    assert [x["name"] for x in PB.list_sets(rp, "01")] == ["first", "proof-002"]


def test_context_marks_concealed_and_scopes(rp):
    r = W.plan(rp, "01")
    art = _by(r["units"], kind="art")[0]
    ctx = W.context(rp, art)
    assert ctx["story"]["beat"] == "b1"
    assert [c["fact"] for c in ctx["story"]["CONCEALED"]] == ["bo-did-it"]
    assert [l["id"] for l in ctx["story"]["lines"]] == ["l1", "l2"]           # only this beat's lines
    assert set(ctx["story"]["continuity_before"]) <= {"ann.location", "key.holder"}
    n = W.next_unit(rp)
    assert os.path.exists(n["file"]) and W.get_unit(rp, n["unit"]["id"])["selected"]


def test_decisions_append_only(rp):
    a = W.decide(rp, "style pin 01", "sr-001 -> sr-002", "scope fix only")
    b = W.decide(rp, "F9", "keep", "creator call")
    assert (a["id"], b["id"]) == ("D001", "D002")
    D = yaml.safe_load((rp.root / "work/decisions.yaml").read_text())["decisions"]
    assert [d["subject"] for d in D] == ["style pin 01", "F9"]


def test_rebuild_keeps_rough_slot_and_landmarks_after_art_lands(rp, tmp_path):
    """A proof made while a slot showed its rough rebuilds to the rough after the final art is
    selected; landmarks edited later do not move a frozen proof's balloon tails."""
    from PIL import Image
    from mangakit.assets import Registry
    PB.publish(rp, "01", "board")
    f = tmp_path / "ann.png"
    Image.new("L", (600, 400), 200).save(f)
    reg = Registry(rp)
    v = reg.add_version("ann-final", f, select=True)
    reg.set_landmark("ann-final", "ann-mouth", 300, 120)
    S = PB.publish(rp, "01", "art")
    assert S["pages"][0]["views"]["proof"]["assets"] == {"ann-final": v}
    reg.set_landmark("rough-ann", "ann-mouth", 10, 10)          # moved after both sets were frozen
    reg.set_landmark("ann-final", "ann-mouth", 590, 390)
    assert PB.rebuild(rp, "board", "01")["identical"]
    assert PB.rebuild(rp, "art", "01")["identical"]


def test_card_scope_keeps_one_characters_exemplar_out_of_other_shots(rp):
    from mangakit.design import Direction
    w(rp.root, "references/direction.yaml", """
    revisions:
    - id: s1
      effective: {chapter: '01'}
      rules:
        tone-density:
          kind: tone-density
          text: flat blacks
          brief: true
          cards:
          - {spec: "sheet@v001#ann-sleeve", scope: [ann]}
          - "sheet@v001#night"
    """)
    D = Direction(rp)
    assert [c["spec"] for c in D.brief("s1", present=["bo"])["cards"]] == ["sheet@v001#night"]
    assert D.brief("s1", present=["bo"])["out_of_scope"] == ["tone-density:sheet@v001#ann-sleeve"]
    assert len(D.brief("s1", present=["ann", "bo"])["cards"]) == 2
