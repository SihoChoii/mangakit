"""End-to-end tests: run with `python3 -m pytest tests -q` from the repo root."""
import json
import textwrap

import numpy as np
import pytest
from PIL import Image, ImageDraw

from mangakit.assets import Registry
from mangakit.checks import run_checks
from mangakit.masktools import make_mask
from mangakit.project import MangakitError, Project, init_project, sha256_file
from mangakit.render import load_page, rebuild, render_page, spread_groups


def drawing(path, size=(800, 600)):
    im = Image.new("L", size, 255)
    d = ImageDraw.Draw(im)
    d.rectangle([100, 100, 700, 500], outline=0, width=8)
    d.polygon([(300, 380), (520, 380), (420, 590)], fill=255, outline=0, width=8)  # "tip" pointing down
    for x in range(120, 700, 20):
        d.line([(x, 110), (x, 360)], fill=0, width=2)
    im.save(path)


PAGE = '''
from mangakit import Path
def build(page, art, script):
    pnl = page.panel("a", Path.polygon([(55, 60), (1037, 60), (1037, 700), (55, 760)]), beat="b1")
    dr = art.selected("thing")
    pl = pnl.align(dr, source="tip", target=(546, 790), scale=1.3)
    page.image(dr, transform=pl, clip=pnl.path, name="inside")
    page.stroke(pnl.path, style="panel-border")
    {BREAK}
    page.balloon("l1", at=({BX}, 200), tail_to=(300, 400){SIZE})
    return page
'''
BREAK = ('zone = pnl.breakout(Path.polygon([(380, 650), (720, 650), (720, 900), (380, 900)]), name="z")\n'
         '    page.image(dr, transform=pl, source_mask=art.mask(dr, "tip"), clip=zone, name="brk")')


@pytest.fixture()
def proj(tmp_path):
    root = init_project(tmp_path / "p", "t")
    (root / "story" / "script.yaml").write_text(textwrap.dedent("""
        beats: [{id: b1}]
        lines: [{id: l1, beat: b1, speaker: a, text: "This is a *test* line for the balloon."}]
    """))
    drawing(tmp_path / "d.png")
    r = Registry(Project(root))
    r.add_version("thing", tmp_path / "d.png", select=True)
    r.set_landmark("thing", "tip", 420, 590)
    return Project(root), tmp_path


def write_page(pr, brk=True, bx=700, size=""):
    f = pr.root / "chapters/01/pages/p001.py"
    f.write_text(PAGE.replace("{BREAK}", BREAK if brk else "").replace("{BX}", str(bx)).replace("{SIZE}", size))


def mask_tip(pr):
    from shapely.geometry import Polygon, box
    tri = Polygon([(300, 380), (520, 380), (420, 590)]).buffer(1.0, join_style=2).intersection(box(0, 300, 800, 600))
    return make_mask(pr, "thing", "tip", [list(tri.exterior.coords)[:-1]], feather=0.6)


def test_render_and_checks_clean(proj):
    pr, _ = proj
    mask_tip(pr)
    write_page(pr)
    page, _ = load_page(pr, "p001")
    all_issues = run_checks(page)
    assert any(i["code"] == "art-resolution" for i in all_issues)  # 800 px drawing at 1.3 u/px is ~117 dpi
    issues = [i for i in all_issues if i["severity"] != "info" and i["code"] != "art-resolution"]
    assert issues == [], issues
    png = render_page(page, "proof")
    man = json.loads(png.with_suffix(".manifest.json").read_text())
    assert man["masks"][0]["version"] == "m001" and man["assets"][0]["version"] == "v001"
    assert man["fonts"]["dialogue"]["sha256"] == pr.fonts()["dialogue"]["sha256"]


def test_same_ink_twice_is_seamless_inside_panel(proj, tmp_path):
    """The breakout copy must not change a single pixel inside the panel (away from the border)."""
    pr, _ = proj
    mask_tip(pr)
    write_page(pr, brk=True)
    a = render_page(load_page(pr, "p001")[0], "proof", out=tmp_path / "with.png", manifest=False)
    write_page(pr, brk=False)
    b = render_page(load_page(pr, "p001")[0], "proof", out=tmp_path / "without.png", manifest=False)
    A = np.asarray(Image.open(a).convert("L")).astype(int)
    B = np.asarray(Image.open(b).convert("L")).astype(int)
    page = load_page(pr, "p001")[0]
    inner = page.panels["a"].path.inset(8).shape()  # stay clear of the border stroke
    k = pr.units_to_px(1, 150)
    m = Image.new("L", (A.shape[1], A.shape[0]), 0)
    ImageDraw.Draw(m).polygon([((x + page.bleed) * k, (y + page.bleed) * k) for x, y in inner.exterior.coords], fill=255)
    inside = np.asarray(m) > 0
    assert np.abs(A - B)[inside].max() <= 1
    outside = ~inside
    assert np.abs(A - B)[outside].sum() > 1000  # the break is actually visible outside the panel


def test_stale_mask_after_new_selection(proj):
    pr, tmp = proj
    mask_tip(pr)
    drawing(tmp / "d2.png")
    r = Registry(pr)
    v = r.add_version("thing", tmp / "d2.png")
    stale = r.select("thing", v)
    assert stale == ["tip"]
    write_page(pr)
    with pytest.raises(MangakitError):  # landmarks are per version: v002 has none yet
        load_page(pr, "p001")
    r.set_landmark("thing", "tip", 420, 590)
    page, _ = load_page(pr, "p001")
    codes = {i["code"] for i in run_checks(page)}
    assert "stale-mask" in codes


def test_select_guard(proj):
    pr, tmp = proj
    drawing(tmp / "d2.png")
    r = Registry(pr)
    v = r.add_version("thing", tmp / "d2.png")
    with pytest.raises(MangakitError):
        r.select("thing", v, if_current="v009")


def test_mask_dimension_mismatch(proj):
    pr, _ = proj
    with pytest.raises(MangakitError):
        Registry(pr).add_mask("thing", "bad", Image.new("L", (10, 10)))


def test_text_overflow_and_breakout_cut(proj):
    pr, _ = proj
    mask_tip(pr)
    write_page(pr, size=", size=(90, 60)")
    f = pr.root / "chapters/01/pages/p001.py"
    f.write_text(f.read_text().replace("(380, 650), (720, 650), (720, 900), (380, 900)",
                                       "(380, 650), (720, 650), (720, 785), (380, 785)"))
    codes = [i["code"] for i in run_checks(load_page(pr, "p001")[0])]
    assert "text-overflow" in codes
    assert "breakout-cut" in codes


def test_missing_asset_renders_placeholder(proj):
    pr, _ = proj
    f = pr.root / "chapters/01/pages/p001.py"
    f.write_text(PAGE.replace("{BREAK}", "").replace("{BX}", "700").replace("{SIZE}", "")
                 .replace('art.selected("thing")', 'art.slot(final="nope")').replace('source="tip"', 'source=(1, 1)'))
    page, _ = load_page(pr, "p001")
    assert any(i["code"] == "missing-asset" for i in run_checks(page))
    assert render_page(page, "rough").exists()


def test_rebuild_identical_after_edits(proj):
    pr, _ = proj
    mask_tip(pr)
    write_page(pr)
    png = render_page(load_page(pr, "p001")[0], "proof")
    man = png.with_suffix(".manifest.json")
    before = sha256_file(png)
    keep = pr.root / "keep.manifest.json"
    keep.write_text(man.read_text())
    write_page(pr, bx=500)                                       # move balloon
    make_mask(pr, "thing", "tip", [[(280, 360), (540, 360), (420, 610)]])  # revise mask
    render_page(load_page(pr, "p001")[0], "proof")
    assert sha256_file(png) != before
    out, same, _ = rebuild(pr, keep, pr.root / "rb.png")
    assert same and sha256_file(out) == before


def test_spread_pairing(proj):
    pr, _ = proj
    assert spread_groups(pr, ["p1", "p2", "p3", "p4"]) == [["p1"], ["p2", "p3"], ["p4"]]
