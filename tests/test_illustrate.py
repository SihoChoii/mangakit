"""manga-illustrate loop: art requests, adapters, candidates, review, guarded selection, metrics."""
import json
import subprocess
import sys

import numpy as np
import pytest
import yaml
from PIL import Image, ImageDraw

from mangakit.assets import Registry
from mangakit.checks import run_checks
from mangakit.illustrate import ADAPTERS, Jobs, compact_prompt, metrics, paintover
from mangakit.masktools import make_mask, snap_to_ink
from mangakit.project import MangakitError
from mangakit.references import RefRegistry
from mangakit.render import load_page

from test_mangakit import drawing, mask_tip, proj, write_page  # noqa: F401  (fixture reuse)


def _ref(pr, tmp_path, rid="sheet", kind="design"):
    f = tmp_path / f"{rid}.png"
    Image.new("L", (300, 200), 200).save(f)
    return RefRegistry(pr).add_ref(rid, f, kind=kind, note=f"{rid} note")


def _cand(tmp_path, name="c.png", size=(800, 600), shift=0):
    f = tmp_path / name
    im = Image.new("L", size, 255)
    ImageDraw.Draw(im).rectangle([100 + shift, 100, 700, 500], outline=0, width=8)
    im.save(f)
    return f


def test_request_pack_contents(proj):
    pr, tmp = proj
    write_page(pr)
    _ref(pr, tmp, "sheet"); _ref(pr, tmp, "style", "style")
    J = Jobs(pr)
    jid = J.request("p001", "a", "thing", refs=["sheet", "style@v001"], prev_direction="L->R",
                    conceal=["the face"], notes="close-up")
    d = J.path(jid)
    req = yaml.safe_load((d / "request.yaml").read_text())
    assert req["target"]["page"] == "p001" and req["target"]["panel"] == "a"
    assert len(req["target"]["page_sha256"]) == 64 and req["base_selection"] == "v001"
    assert [(r["id"], r["version"]) for r in req["references"]] == [("sheet", "v001"), ("style", "v001")]
    assert all((d / r["pack_file"]).exists() for r in req["references"])
    for f in ("guide.png", "guide.json", "rough-crop.png", "context-crop.png"):
        assert (d / "pack" / f).exists(), f
    assert "the face" in req["continuity"]["conceal"] and req["continuity"]["previous_screen_direction"] == "L->R"
    assert "z:" in req["beyond_border"] and "% of the image" in req["beyond_border"]
    assert req["acceptance"] and (d / "prompt.md").read_text().startswith("# Art request")
    # rough crop is the panel's own drawing resampled into the draw area: no lettering, no borders
    rc = Image.open(d / "pack" / "rough-crop.png")
    da = req["shot_guide"]["draw_area_page_units"]
    assert abs(rc.width / rc.height - (da[2] - da[0]) / (da[3] - da[1])) < 0.01


def test_host_adapter_call_and_collect_metrics(proj):
    pr, tmp = proj
    write_page(pr)
    _ref(pr, tmp, "sheet")
    J = Jobs(pr)
    jid = J.request("p001", "a", "thing", refs=["sheet"])
    n, how = J.call(jid)
    call = json.loads((J.path(jid) / f"host-call-{n}.json").read_text())["arguments"]
    assert call["reference_image_paths"][0].endswith("rough-crop.png")
    assert call["aspect_ratio"] in ("1:1", "4:3", "3:4", "16:9", "9:16") and "description" in call
    vers = J.collect(jid, [_cand(tmp)])
    assert vers == ["v002"] and Registry(pr).load("thing")["selected"] == "v001"  # stored, not selected
    assert (J.path(jid) / "candidates" / "v002-call1.png").exists()
    with pytest.raises(MangakitError):
        J.select(jid, "v002")  # no passing verdict yet
    J.verdict(jid, "v002", True, "ok")
    stale, missing = J.select(jid, "v002")
    assert stale == ["tip"] or stale == []  # mask only exists if made; landmark 'tip' must be reported
    assert missing == ["tip"]
    m = metrics(pr)
    assert m["illustration_calls_per_accepted_panel"] == 1.0
    assert m["art_calls_caused_by_lettering_or_mask_edits"] == 0


def test_select_refuses_when_selection_moved(proj):
    pr, tmp = proj
    write_page(pr)
    J = Jobs(pr)
    jid = J.request("p001", "a", "thing")
    J.call(jid)
    J.collect(jid, [_cand(tmp)])
    J.verdict(jid, "v002", True)
    other = Registry(pr).add_version("thing", _cand(tmp, "o.png", shift=5))
    Registry(pr).select("thing", other)  # someone else changed the selection meanwhile
    with pytest.raises(MangakitError, match="refusing"):
        J.select(jid, "v002")


def test_edit_request_sends_source_not_rough(proj):
    pr, tmp = proj
    write_page(pr)
    J = Jobs(pr)
    jid = J.request("p001", "a", "thing", reason="correction", edit_of="v001", instruction="lower the arm")
    req = yaml.safe_load((J.path(jid) / "request.yaml").read_text())
    assert req["edit_of"]["version"] == "v001" and req["edit_of"]["sha256"]
    n, _ = J.call(jid)
    call = json.loads((J.path(jid) / f"host-call-{n}.json").read_text())["arguments"]
    assert call["reference_image_paths"][0].endswith("edit-source@v001.png")
    assert not any(p.endswith("rough-crop.png") for p in call["reference_image_paths"])
    assert "lower the arm" in call["description"]
    po = tmp / "po.png"
    Image.new("L", (800, 600), 255).save(po)
    jid2 = J.request("p001", "a", "thing", reason="correction", edit_of="v001", instruction="x", paintover_file=po)
    J.call(jid2)
    call2 = json.loads((J.path(jid2) / "host-call-1.json").read_text())["arguments"]
    assert call2["reference_image_paths"][0].endswith("paintover.png")
    assert not any("edit-source" in p for p in call2["reference_image_paths"])  # never the unmoved source too


def test_manual_and_command_adapters(proj):
    pr, tmp = proj
    write_page(pr)
    J = Jobs(pr)
    jid = J.request("p001", "a", "thing", adapter="manual")
    assert (J.path(jid) / "pack" / "README.txt").exists() and (J.path(jid) / "inbox").is_dir()
    J.call(jid)
    _cand(tmp).rename(J.path(jid) / "inbox" / "back.png")
    assert J.collect(jid, [J.path(jid) / "inbox" / "back.png"]) == ["v002"]
    # command adapter: a fake backend that copies the rough crop to the out dir
    script = tmp / "fake_backend.py"
    script.write_text("import shutil,sys; refs=sys.argv[1].split(','); shutil.copy(refs[0], sys.argv[2] + '/out.png')\n")
    cfg = yaml.safe_load((pr.root / "project.yaml").read_text())
    cfg["illustration"] = {"adapters": {"command": {"run": f"{sys.executable} {script} {{refs}} {{out_dir}}"}}}
    (pr.root / "project.yaml").write_text(yaml.safe_dump(cfg))
    from mangakit.project import Project
    pr2 = Project(pr.root)
    J2 = Jobs(pr2)
    jid2 = J2.request("p001", "a", "thing", adapter="command")
    J2.call(jid2)  # synchronous: candidates collected immediately
    job = J2.load(jid2)
    assert job["calls"][0]["status"] == "done" and job["calls"][0]["outputs"] == ["v003"]
    assert set(ADAPTERS) == {"manual", "host", "command"}


def test_review_sheet_and_render_has_no_generation(proj):
    pr, tmp = proj
    write_page(pr)
    J = Jobs(pr)
    jid = J.request("p001", "a", "thing")
    J.call(jid)
    J.collect(jid, [_cand(tmp)])
    Registry(pr).set_landmark("thing", "tip", 420, 590, ver="v002")
    out = J.review_sheet(jid)
    assert Image.open(out).size[0] > 1000
    import mangakit.render as R, mangakit.checks as C
    for mod in (R, C):  # image generation stays out of the render/check path
        src = open(mod.__file__).read()
        assert "illustrate" not in src and "adapter" not in src.lower()


def test_paintover_maps_points(tmp_path):
    src = tmp_path / "s.png"
    im = Image.new("L", (400, 300), 255)
    ImageDraw.Draw(im).ellipse([95, 95, 105, 105], fill=0)
    ImageDraw.Draw(im).ellipse([295, 95, 305, 105], fill=0)
    im.save(src)
    info = paintover(src, [((100, 100), (100, 200)), ((300, 100), (300, 200))], tmp_path / "o.png")
    o = np.asarray(Image.open(tmp_path / "o.png"))
    assert o[200, 100] < 50 and o[200, 300] < 50 and o[100, 100] > 200
    assert info["scale"] == 1.0 and abs(info["rotate_deg"]) < 1e-6


def test_snap_to_ink_removes_paper_margin():
    g = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(g).rectangle([30, 30, 70, 70], outline=0, width=2)
    m = Image.new("L", (100, 100), 0)
    ImageDraw.Draw(m).rectangle([25, 25, 75, 75], fill=255)  # 5 px paper margin
    s = np.asarray(snap_to_ink(g, m, steps=8)) > 127
    assert not s[26, 50] and s[30, 50] and s[50, 50]  # margin gone, outline and interior kept


def test_breakout_flush_with_unbroken_frame_edge_is_not_a_cut(proj):
    pr, tmp = proj
    mask_tip(pr)
    # art that runs past the panel's right edge (never crossed by a breakout) is cut by that edge's
    # extension, not by the breakout region
    f = pr.root / "chapters/01/pages/p001.py"
    tmpl = '''
from mangakit import Path
def build(page, art, script):
    pnl = page.panel("a", Path.polygon([(55, 60), (700, 60), (700, 700), (55, 760)]), beat="b1")
    dr = art.selected("thing")
    pl = pnl.align(dr, source="tip", target=(650, 790), scale=1.3)
    page.image(dr, transform=pl, clip=pnl.path, name="inside")
    page.stroke(pnl.path, style="panel-border")
    zone = pnl.breakout(Path.polygon([(300, 640), (ZX, 640), (ZX, 900), (300, 900)]), name="z")
    page.image(dr, transform=pl, source_mask=art.mask(dr, "tip"), clip=zone, name="brk")
    return page
'''
    f.write_text(tmpl.replace("ZX", "700"))  # zone ends on the frame's right edge line: flush, allowed
    page, _ = load_page(pr, "p001")
    codes = [i["code"] for i in run_checks(page)]
    assert "breakout-cut" not in codes, codes
    f.write_text(tmpl.replace("ZX", "620"))  # zone ends short of it: a real straight cut
    page, _ = load_page(pr, "p001")
    assert "breakout-cut" in [i["code"] for i in run_checks(page)]
