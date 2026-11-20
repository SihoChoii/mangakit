"""Frozen proof sets: publish a chapter's proofs with their manifests so the same bytes can be rebuilt
after later edits (the manifests pin page source, script, project.yaml, drawing/mask versions, fonts,
style revision and its render overrides; all snapshots live in history/snapshots)."""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import stat
from pathlib import Path as FsPath

import yaml

from .project import MangakitError, Project, load_yaml, sha256_file

VIEWS = ("proof", "reading")


def pdir(project, chapter=None) -> FsPath:
    return project.root / "publish" / f"ch{chapter or project.chapter}"


def list_sets(project, chapter=None) -> list[dict]:
    d = pdir(project, chapter)
    return [load_yaml(f) for f in sorted(d.glob("*/set.yaml"))] if d.exists() else []


def publish(project: Project, chapter=None, name=None, final=False, note="", views=VIEWS, by=None) -> dict:
    from . import work
    from .checks import run_checks
    from .render import load_page, render_page
    ch = str(chapter or project.chapter)
    if final:
        g = work.gates(project)
        if g["final_version"] and not work.approved(project, "final_version", ch):
            raise MangakitError(f"final_version gate: chapter {ch} needs the creator's approval "
                                "(work approve final_version <chapter> --by <creator> --note <their words>)")
    existing = list_sets(project, ch)
    name = name or f"proof-{len(existing) + 1:03d}"
    out = pdir(project, ch) / name
    try:
        out.mkdir(parents=True)
    except FileExistsError:
        raise MangakitError(f"publish set {out.relative_to(project.root)} exists; frozen sets are never overwritten")
    pages, issues = [], {}
    for pid in project.chapter_pages(ch):
        page, _ = load_page(project, pid, chapter=ch)
        errs = [i for i in run_checks(page) if i["severity"] == "error"]
        if errs:
            issues[pid] = [f"{i['code']} {i['where']}" for i in errs]
        entry = {"page": pid, "views": {}}
        for v in views:
            png = render_page(page, v, out / pid / f"{v}.png")
            (out / pid / f"{v}.svg").unlink(missing_ok=True)   # the png + manifest are the record
            mf = png.with_suffix(".manifest.json")
            man = json.loads(mf.read_text())
            man["outputs"] = [o for o in man["outputs"] if o["file"].endswith(".png")]
            mf.write_text(json.dumps(man, indent=2))
            entry["views"][v] = {"png": os.path.relpath(png, project.root), "sha256": sha256_file(png),
                                 "manifest": os.path.relpath(mf, project.root), "style": (man.get("style") or {}).get("revision"),
                                 "assets": {a["id"]: a["version"] for a in man["assets"]}}
        pages.append(entry)
    S = {"chapter": ch, "name": name, "final": bool(final), "created": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
         "note": note, "check_errors": issues, "pages": pages}
    (out / "set.yaml").write_text(yaml.safe_dump(S, sort_keys=False, allow_unicode=True, width=110))
    for f in out.rglob("*"):
        if f.is_file():
            f.chmod(f.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    return S


def rebuild(project: Project, name, chapter=None, keep=False) -> dict:
    """Re-render every page/view of a frozen set from its manifests into build/rebuild/<set>/ and
    compare bytes with the frozen shas."""
    from .render import rebuild as rb
    ch = str(chapter or project.chapter)
    d = pdir(project, ch) / name
    if not (d / "set.yaml").exists():
        raise MangakitError(f"no publish set {name} for chapter {ch} (publish list)")
    S = load_yaml(d / "set.yaml")
    out = project.root / "build" / "rebuild" / f"ch{ch}" / name
    if out.exists():
        shutil.rmtree(out)
    rows, ok = [], True
    for e in S["pages"]:
        for v, x in e["views"].items():
            o = out / e["page"] / f"{v}.png"
            o.parent.mkdir(parents=True, exist_ok=True)
            png, same, notes = rb(project, project.root / x["manifest"], o)
            got = sha256_file(png)
            same = got == x["sha256"]
            ok &= same
            rows.append({"page": e["page"], "view": v, "frozen": x["sha256"][:12], "rebuilt": got[:12],
                         "identical": same, "notes": notes, "file": os.path.relpath(png, project.root)})
            png.with_suffix(".svg").unlink(missing_ok=True)
    return {"set": name, "chapter": ch, "identical": ok, "rows": rows}


def format_rebuild(R) -> str:
    L = [f"publish rebuild {R['set']} (chapter {R['chapter']}): {'ALL BYTE-IDENTICAL' if R['identical'] else 'DIFFERS'}"]
    for r in R["rows"]:
        L.append(f"  {r['page']} {r['view']:<8} frozen {r['frozen']}  rebuilt {r['rebuilt']}  "
                 f"{'identical' if r['identical'] else 'DIFFERENT'}{'  ' + '; '.join(r['notes']) if r['notes'] else ''}")
    return "\n".join(L)
