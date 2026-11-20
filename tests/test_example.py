"""The bundled text-only example project: roughs build, checks pass, pages render, a proof set rebuilds."""
import shutil
from pathlib import Path

import pytest

from mangakit.cli import main
from mangakit.project import KIT_FONTS

EXAMPLE = Path(__file__).resolve().parent.parent / "example"
ROUGHS = sorted(p.stem for p in (EXAMPLE / "art" / "roughs").glob("*.py"))

pytestmark = pytest.mark.skipif(
    not (EXAMPLE / "project.yaml").exists() or not (KIT_FONTS / "ComicNeue-Bold.ttf").exists(),
    reason="example project or fonts missing (run install.sh)")


@pytest.fixture()
def ex(tmp_path, monkeypatch):
    d = tmp_path / "example"
    shutil.copytree(EXAMPLE, d, ignore=shutil.ignore_patterns("build", "art/assets", "history", "work", "publish"))
    (d / "fonts").mkdir(exist_ok=True)
    for f in KIT_FONTS.iterdir():
        shutil.copy2(f, d / "fonts" / f.name)
    monkeypatch.chdir(d)
    return d


def run(*args):
    try:
        main(list(args))
    except SystemExit as e:
        assert not e.code, f"mangakit {' '.join(args)} exited {e.code}"


def test_example_end_to_end(ex, capsys):
    for r in ROUGHS:
        run("rough", "make", r)
    run("story", "check")
    run("board", "check", "01")
    out = capsys.readouterr().out
    assert "story check: 0 error(s)" in out and "board check: 0 error(s)" in out
    for p in ("p002", "p003", "p004"):
        run("render", p, "--view", "reading", "-q")
        assert (ex / "build" / "ch01" / p / "reading.png").exists()
    run("publish", "create", "proof-001", "--chapter", "01")
    capsys.readouterr()
    run("publish", "rebuild", "proof-001", "--chapter", "01")
    out = capsys.readouterr().out
    assert "ALL BYTE-IDENTICAL" in out and "DIFFERENT" not in out
