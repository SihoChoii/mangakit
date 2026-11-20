"""Project discovery, settings, scaffolding, script access."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path as FsPath

import yaml

KIT_DIR = FsPath(__file__).resolve().parent
KIT_FONTS = KIT_DIR / "fonts"
VENDOR_RESVG = KIT_DIR.parent / "vendor" / "resvg-0.49.0" / "resvg"


class MangakitError(Exception):
    pass


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_yaml(p):
    with open(p) as f:
        return yaml.safe_load(f) or {}


def dump_yaml(p, data):
    tmp = str(p) + ".tmp"
    with open(tmp, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, width=100)
    os.replace(tmp, p)


# Fonts shipped with the kit (all SIL Open Font License 1.1, from github.com/google/fonts).
KIT_FONT_TABLE = {
    "dialogue": ("ComicNeue-Bold.ttf", "OFL-ComicNeue.txt"),
    "dialogue-emphasis": ("ComicNeue-BoldItalic.ttf", "OFL-ComicNeue.txt"),
    "caption": ("ComicNeue-Regular.ttf", "OFL-ComicNeue.txt"),
    "sfx": ("Bangers-Regular.ttf", "OFL-Bangers.txt"),
}


def default_project_yaml(title, direction, language, trim_mm, bleed_mm, dpi):
    return {
        "mangakit": 1,
        "title": title,
        "reading_direction": direction,
        "language": language,
        "color": "monochrome",
        "page": {
            "trim_mm": list(trim_mm),
            "bleed_mm": bleed_mm,
            "safe_mm": 8,
            "units_per_mm": 6,
        },
        "spreads": {
            # odd-start: page 1 stands alone, then (2,3), (4,5)...; even-start: (1,2), (3,4)...
            "pairing": "odd-start",
        },
        "active_chapter": "01",
        "fonts": {},  # filled by init with pinned copies + sha256
        "lettering": {
            "uppercase": language == "en",
            "font_size": 21,
            "line_height": 1.12,
            "balloon_padding": 16,
            "tail_gap": 18,
        },
        "styles": {
            "panel-border": {"stroke": "#000000", "width": 4.5, "join": "miter"},
            "balloon": {"stroke": "#000000", "width": 2.4, "fill": "#ffffff"},
            "thin": {"stroke": "#000000", "width": 1.5, "join": "round"},
        },
        "render": {
            "renderer": "resvg",
            "renderer_version": "0.49.0",
            "proof_dpi": 150,
            "reading_height_px": 1100,
            "thumb_height_px": 420,
            "background": "#ffffff",
        },
        "output_profiles": {
            "print": {"dpi": dpi, "bleed": True, "mode": "L", "format": "png"},
            "web": {"dpi": 150, "bleed": False, "mode": "RGB", "format": "png"},
        },
    }


# story/ templates (schema: docs/story-reference.md)
PREMISE_TEMPLATE = {"title": "", "logline": "One sentence: who wants what, and what stands in the way.",
                    "premise": "", "audience": "", "length": {"chapter": "01", "pages": 1}, "tone": "", "goals": []}
CANON_TEMPLATE = {"characters": [{"id": "lead", "name": "Lead", "role": "protagonist"}],
                  "props": [], "locations": [{"id": "place-1", "name": "Somewhere", "adjacent": []}],
                  "facts": [], "initial": []}
BEATS_TEMPLATE = {"beats": [{"id": "beat-1", "chapter": "01", "summary": "What happens in this beat",
                             "location": "place-1", "present": ["lead"], "reader": {"knows": []}}]}
SCRIPT_TEMPLATE = {
    "lines": [
        {"id": "line-1", "beat": "beat-1", "kind": "caption", "text": "Replace me."},
    ],
}
THREADS_TEMPLATE = {"threads": []}

PAGE_TEMPLATE = '''"""Page source. Rendered by `mangakit render {page}`.

build(page, art, script) describes the page in page units (origin = trim top-left).
See docs/page-api.md in the mangakit repo
"""
from mangakit import Path


def build(page, art, script):
    m = 50
    p1 = page.panel("p1", path=Path.rect(m, m, page.width - 2 * m, page.height - 2 * m), beat="beat-1")
    page.fill(p1.path, "#ffffff")
    page.stroke(p1.path, style="panel-border")
    page.balloon("line-1", at=(page.width / 2, 200))
    return page
'''


def init_project(target, title=None, direction="rtl", language="en", trim_mm=(182, 257), bleed_mm=3, dpi=600):
    root = FsPath(target).resolve()
    if (root / "project.yaml").exists():
        raise MangakitError(f"{root}/project.yaml already exists")
    for d in ["story", "references/designs", "references/style", "references/sources",
              "chapters/01/pages", "art/assets", "art/jobs", "reviews", "build", "fonts", "history/snapshots"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    cfg = default_project_yaml(title or root.name, direction, language, trim_mm, bleed_mm, dpi)
    for role, (ttf, lic) in KIT_FONT_TABLE.items():
        shutil.copy2(KIT_FONTS / ttf, root / "fonts" / ttf)
        shutil.copy2(KIT_FONTS / lic, root / "fonts" / lic)
        cfg["fonts"][role] = {"file": f"fonts/{ttf}", "sha256": sha256_file(root / "fonts" / ttf),
                              "license": "OFL-1.1", "license_file": f"fonts/{lic}"}
    cfg["render"]["renderer_sha256"] = sha256_file(VENDOR_RESVG) if VENDOR_RESVG.exists() else None
    dump_yaml(root / "project.yaml", cfg)
    dump_yaml(root / "story" / "premise.yaml", {**PREMISE_TEMPLATE, "title": cfg["title"]})
    dump_yaml(root / "story" / "canon.yaml", CANON_TEMPLATE)
    dump_yaml(root / "story" / "beats.yaml", BEATS_TEMPLATE)
    dump_yaml(root / "story" / "script.yaml", SCRIPT_TEMPLATE)
    dump_yaml(root / "story" / "threads.yaml", THREADS_TEMPLATE)
    dump_yaml(root / "story" / "continuity.yaml", {"events": []})
    dump_yaml(root / "chapters" / "01" / "chapter.yaml", {"id": "01", "title": "", "pages": ["p001"]})
    (root / "chapters" / "01" / "pages" / "p001.py").write_text(PAGE_TEMPLATE.format(page="p001"))
    dump_yaml(root / "reviews" / "findings.yaml", {"findings": []})
    (root / ".gitignore").write_text("build/\n__pycache__/\n")
    (root / "README.md").write_text(
        f"# {cfg['title']}\n\nmangakit project. Layout: see docs/project-format.md in the mangakit repo\n")
    return root


class Project:
    def __init__(self, root, cfg: dict | None = None):
        self.root = FsPath(root).resolve()
        self.cfg = cfg if cfg is not None else load_yaml(self.root / "project.yaml")
        pg = self.cfg["page"]
        self.upm = float(pg.get("units_per_mm", 6))
        self.trim_w = pg["trim_mm"][0] * self.upm
        self.trim_h = pg["trim_mm"][1] * self.upm
        self.bleed = pg.get("bleed_mm", 3) * self.upm
        self.safe = pg.get("safe_mm", 8) * self.upm
        self.direction = self.cfg.get("reading_direction", "rtl")

    @staticmethod
    def find(start=None) -> "Project":
        p = FsPath(start or os.getcwd()).resolve()
        if p.is_file():
            p = p.parent
        for q in [p, *p.parents]:
            if (q / "project.yaml").exists():
                return Project(q)
        raise MangakitError(f"no project.yaml at or above {p}")

    @property
    def chapter(self) -> str:
        return str(self.cfg.get("active_chapter", "01"))

    def page_file(self, ref: str, chapter: str | None = None) -> FsPath:
        p = FsPath(ref)
        if p.suffix == ".py" and p.exists():
            return p.resolve()
        ch = chapter or self.chapter
        f = self.root / "chapters" / ch / "pages" / f"{ref}.py"
        if not f.exists():
            raise MangakitError(f"page source not found: {f}")
        return f

    def chapter_pages(self, chapter: str | None = None) -> list[str]:
        ch = chapter or self.chapter
        meta = self.root / "chapters" / ch / "chapter.yaml"
        if meta.exists():
            pages = load_yaml(meta).get("pages")
            if pages:
                return list(pages)
        return sorted(f.stem for f in (self.root / "chapters" / ch / "pages").glob("p*.py"))

    def build_dir(self, *parts) -> FsPath:
        d = self.root.joinpath("build", *parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def fonts(self) -> dict:
        return self.cfg.get("fonts", {})

    def font_path(self, role: str) -> FsPath:
        f = self.fonts().get(role)
        if not f:
            raise MangakitError(f"font role {role!r} not pinned in project.yaml")
        return self.root / f["file"]

    def verify_fonts(self) -> list[str]:
        problems = []
        for role, f in self.fonts().items():
            p = self.root / f["file"]
            if not p.exists():
                problems.append(f"font {role}: missing file {p}")
            elif sha256_file(p) != f.get("sha256"):
                problems.append(f"font {role}: sha256 mismatch for {p} (pinned {f.get('sha256')[:12]})")
        return problems

    def style(self, name: str) -> dict:
        s = self.cfg.get("styles", {}).get(name)
        if s is None:
            raise MangakitError(f"style {name!r} not defined in project.yaml styles")
        return s

    def mm_to_px(self, mm, dpi):
        return mm / 25.4 * dpi

    def units_to_px(self, units, dpi):
        return units / self.upm / 25.4 * dpi

    @property
    def lettering(self) -> dict:
        return self.cfg.get("lettering", {})

    @property
    def render_cfg(self) -> dict:
        return self.cfg.get("render", {})


class Script:
    """Read-only view of story/script.yaml. The script owns dialogue wording."""

    def __init__(self, project: Project, path=None, data=None):
        self.path = FsPath(path) if path else project.root / "story" / "script.yaml"
        self.data = data if data is not None else (load_yaml(self.path) if self.path.exists() else {})
        self.lines = {l["id"]: l for l in self.data.get("lines", [])}
        self.order = [l["id"] for l in self.data.get("lines", [])]
        beats = self.data.get("beats")
        bf = project.root / "story" / "beats.yaml"
        if not beats and bf.exists():  # beats live in story/beats.yaml; older projects keep them in the script
            beats = (load_yaml(bf) or {}).get("beats", [])
        self.beats = {b["id"]: b for b in beats or []}
        self.used: dict[str, str] = {}

    def line(self, line_id: str) -> dict | None:
        l = self.lines.get(line_id)
        if l is not None:
            self.used[line_id] = l.get("text", "")
        return l

    def lines_for_beat(self, beat: str) -> list[str]:
        return [i for i in self.order if self.lines[i].get("beat") == beat]
