"""manga-review: cold-read packets and scoring, aggregate technical pass, art-vs-story sheet, findings
tied to page revisions, recheck (verified vs survived), pilot metrics.

A page revision is the sha256 of its clean reading render (what a reader sees), plus the page source
and art versions that produced it. Findings record the revision they were filed against; a finding
that still holds after its page's revision changed has survived a revision."""
from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import json
import re
import shutil
from pathlib import Path as FsPath

import yaml
from PIL import Image, ImageDraw

from .project import MangakitError, Project, load_yaml
from .story import Story

OWNERS = ("story", "design", "board", "illustrate", "compose", "direct")
STATUSES = ("open", "fixed", "verified", "wont-fix", "editorial")
SEVERITIES = ("error", "warn", "info")
FINDINGS = "findings.yaml"


def _now():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _chapter(project, chapter):
    return str(chapter or project.chapter)


def _rel(project, p):
    try:
        return str(FsPath(p).resolve().relative_to(project.root.resolve()))
    except ValueError:
        return str(p)


def _font(project, size):
    from .render import _pil_font
    return _pil_font(project, size)


# ============================================================================ revisions
def page_revision(project: Project, pid: str, chapter=None) -> dict:
    """Render the clean reading view and return {rev, png, source, assets}. rev = first 12 hex of the
    reading PNG's sha256: renders are deterministic, so a new rev means the reader sees a new page."""
    from .render import load_page, render_page
    page, src = load_page(project, pid, chapter=chapter)
    png = render_page(page, "reading", manifest=True)
    man = json.loads(png.with_suffix(".manifest.json").read_text())
    return {"page": pid, "rev": hashlib.sha256(png.read_bytes()).hexdigest()[:12], "png": str(png),
            "source": man["page_source"]["sha256"][:12],
            "assets": {a["id"]: a["version"] for a in man["assets"]},
            "masks": {m["key"]: m["version"] for m in man["masks"]},
            "style": (man.get("style") or {}).get("revision"), "_page": page}


def chapter_revisions(project, chapter=None) -> dict:
    ch = _chapter(project, chapter)
    return {pid: page_revision(project, pid, ch) for pid in project.chapter_pages(ch)}


# ============================================================================ cold-read packet
QUESTIONNAIRE = """# Cold read

You are reading a short comic chapter for the first time. You get only the pages. Do not look at
anything else in this project before you have written every answer.

How to read: the images are numbered in reading order. `NN-spread.png` shows two facing pages, or
one page, the way they lie open in the book. {direction_note} A `NN-page-turn.png` image means
you turn the page: what follows was hidden until then. `pages/` has the same pages one by one.

Read the whole chapter once at the size given, without zooming. Then fill in `answers.yaml`. Use
your own words and your own names for people ("the runner", "man in the coat"). Write "unknown"
when you cannot tell; a guess is fine if you mark it with "?". Page numbers are the numbers printed
under each page in the spread images.

1. **Speaker order.** List every balloon, caption and sound in the order you read it, with the page,
   its first few words, and who said it (a person, `caption`, `sound`, or `unknown`).
2. **What changed hands.** Did any object pass from one person to another? What, from whom, to whom,
   on which page, at what moment?
3. **Owner at the end.** At the last page, who has each object that matters?
4. **Eye path.** For each page: where did your eye land first, and where did it go next?
5. **Surprise.** What surprised you, and on which page?
6. **Reveal timing.** When did you learn who someone was, or something that had been hidden? Page,
   and whether it came right after a page turn.
7. **Unclear.** Anything you could not read, could not follow, or read twice. Page and where on it.
"""

ANSWERS_TEMPLATE = """# Cold-read answers. Fill in from the pages only. Keep the keys; add list items as needed.
reader: ''            # who read (a name, or 'fresh-helper', or 'self-blind')
read_at: ''
characters:           # everyone you saw, with your own label
- {label: '', description: '', pages: []}
speakers:             # Q1, in reading order
- {page: 1, words: '', speaker: ''}
transfers:            # Q2
- {object: '', from: '', to: '', page: 0, moment: ''}
holder_end:           # Q3
- {object: '', holder: ''}
eye_path:             # Q4: page number -> [first, next, ...]
  1: ['', '']
surprises:            # Q5
- {page: 0, what: ''}
reveals:              # Q6
- {page: 0, what: '', after_turn: false}
unclear:              # Q7
- {page: 0, where: '', what: ''}
"""


def _round_dir(project, ch, name=None, new=False) -> FsPath:
    base = project.root / "reviews" / f"ch{ch}" / "cold"
    base.mkdir(parents=True, exist_ok=True)
    rounds = sorted(p.name for p in base.iterdir() if p.is_dir() and re.fullmatch(r"r\d{2}", p.name))
    if name:
        return base / name
    if new or not rounds:
        return base / f"r{len(rounds) + 1:02d}"
    return base / rounds[-1]


def _blank_page(size):
    return Image.new("RGB", size, "#9a9a9a")


def packet(project: Project, chapter=None, pages=None, out=None) -> dict:
    """Unannotated reading-size spreads in reading order with page-turn cards, single pages, the fixed
    questionnaire and an answers template. Nothing in the packet names a panel, beat, line, asset
    or file of the project. The round record (revisions, packet page -> page id) is written next to
    the packet, outside it. `pages` limits the packet to those pages' spreads (a recheck read)."""
    from .render import lone_slot, spread_groups
    ch = _chapter(project, chapter)
    allp = project.chapter_pages(ch)
    groups = spread_groups(project, allp, ch)
    if pages:
        groups = [g for g in groups if set(g) & set(pages)]
    rd = FsPath(out) if out else _round_dir(project, ch, new=True)
    pk = rd / "packet"
    if pk.exists():
        shutil.rmtree(pk)
    (pk / "pages").mkdir(parents=True)
    revs = {pid: page_revision(project, pid, ch) for g in groups for pid in g}
    rtl = project.direction == "rtl"
    # packet page numbers are chapter page positions, so a partial (recheck) packet keeps them
    number = {pid: allp.index(pid) + 1 for g in groups for pid in g}
    seq = []
    k = 0
    prev_ix = None
    for gi, g in enumerate(groups):
        ix = spread_groups(project, allp, ch).index(g)
        if gi and ix == prev_ix + 1:
            k += 1
            card = Image.new("RGB", (1200, 300), "#222222")
            d = ImageDraw.Draw(card)
            d.text((600, 150), "TURN THE PAGE", fill="#ffffff", font=_font(project, 64), anchor="mm")
            f = pk / f"{k:02d}-page-turn.png"
            card.save(f)
            seq.append({"file": f.name, "kind": "page-turn"})
        elif gi:
            k += 1
            card = Image.new("RGB", (1200, 300), "#222222")
            d = ImageDraw.Draw(card)
            d.text((600, 150), "(pages skipped)", fill="#ffffff", font=_font(project, 48), anchor="mm")
            f = pk / f"{k:02d}-skip.png"
            card.save(f)
            seq.append({"file": f.name, "kind": "skip"})
        prev_ix = ix
        ims = {pid: Image.open(revs[pid]["png"]).convert("RGB") for pid in g}
        w, h = next(iter(ims.values())).size
        canvas = Image.new("RGB", (w * 2 + 6, h + 56), "#8a8a8a")
        d = ImageDraw.Draw(canvas)
        if len(g) == 2:
            slots = dict(zip(g, [1, 0] if rtl else [0, 1]))
        else:
            slots = {g[0]: lone_slot(project, g, allp, ch)}
        for pid, s in slots.items():
            canvas.paste(ims[pid], (s * (w + 6), 0))
            d.text((s * (w + 6) + w // 2, h + 28), f"page {number[pid]}", fill="white", font=_font(project, 26), anchor="mm")
        k += 1
        f = pk / f"{k:02d}-spread.png"
        canvas.save(f)
        seq.append({"file": f.name, "kind": "spread", "pages": [number[p] for p in g]})
        for pid in g:
            shutil.copy2(revs[pid]["png"], pk / "pages" / f"{number[pid]}.png")
    note = ("Read right to left: the right-hand page comes first, and each page reads from top right."
            if rtl else "Read left to right: the left-hand page comes first.")
    (pk / "questionnaire.md").write_text(QUESTIONNAIRE.format(direction_note=note))
    (pk / "answers.yaml").write_text(ANSWERS_TEMPLATE)
    rec = {"round": rd.name, "chapter": ch, "created": _now(), "direction": project.direction,
           "packet": _rel(project, pk), "sequence": seq,
           "pages": {str(number[pid]): {"page": pid, "rev": revs[pid]["rev"], "source": revs[pid]["source"],
                                         "assets": revs[pid]["assets"]} for pid in number},
           "answers": None, "key": None}
    (rd / "round.yaml").write_text(yaml.safe_dump(rec, sort_keys=False, allow_unicode=True))
    leaks = packet_leaks(project, pk)
    if leaks:
        raise MangakitError(f"packet would leak project metadata: {leaks}")
    return {"dir": str(rd), "packet": str(pk), "sequence": seq, "pages": rec["pages"]}


def packet_leaks(project, pk) -> list[str]:
    """Words of the project's ids found in packet file names or text files (the packet must say
    nothing the pages do not)."""
    st = Story(project)
    ids = set(st.beat) | set(st.line) | set(st.facts) | set(st.characters) | set(st.props) | set(st.locations)
    ids |= set(project.chapter_pages())
    from .assets import Registry
    try:
        ids |= set(Registry(project).ids())
    except Exception:
        pass
    words = {i.lower() for i in ids if len(i) > 3}
    hits = []
    for f in FsPath(pk).rglob("*"):
        if any(w in f.name.lower() for w in words):
            hits.append(f.name)
        if f.suffix in (".md", ".yaml", ".txt", ".json"):
            t = f.read_text().lower()
            fixed = (QUESTIONNAIRE + ANSWERS_TEMPLATE).lower()     # the fixed text may use common words
            hits += [f"{f.name}:{w}" for w in words if re.search(rf"\b{re.escape(w)}\b", t) and w not in fixed]
        if f.suffix not in (".png", ".md", ".yaml") and f.is_file():
            hits.append(f"{f.name}: unexpected file type")
    return hits


# ============================================================================ findings store
def _locked(fn):
    """Serialize findings read-modify-write across processes (two reviewers, a recheck and a tech pass)."""
    import functools

    @functools.wraps(fn)
    def wrap(project, *a, **kw):
        from .ids import locked
        with locked(project.root / "reviews" / ".findings.lock"):
            return fn(project, *a, **kw)
    return wrap


def findings_path(project) -> FsPath:
    return project.root / "reviews" / FINDINGS


def load_findings(project) -> list[dict]:
    f = findings_path(project)
    return list((load_yaml(f) or {}).get("findings") or []) if f.exists() else []


def save_findings(project, F):
    f = findings_path(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# Review findings. Written by `mangakit review`; edit status through `review set`.\n"
                 + yaml.safe_dump({"findings": F}, sort_keys=False, allow_unicode=True, width=110))


def _next_id(F):
    # callers hold the findings lock, so max+1 cannot be handed out twice
    n = max([int(x["id"][1:]) for x in F if re.fullmatch(r"F\d+", x.get("id", ""))] or [0])
    return f"F{n + 1:03d}"


def _hist(f, status=None, note="", by="review", **kw):
    h = {"at": _now(), "by": by}
    if status:
        h["status"] = status
    if note:
        h["note"] = note
    h.update(kw)
    f.setdefault("history", []).append(h)


def _crop(project, f, rev):
    """Crop of the clean reading render at `rev` for the finding's region (page units), or the
    whole page. Saved as reviews/ch<ch>/findings/<id>[-<tag>].png."""
    if not f.get("page") or f["page"] not in (rev or {}):
        return None
    r = rev[f["page"]]
    im = Image.open(r["png"]).convert("RGB")
    page = r["_page"]
    s = im.height / page.height
    reg = f.get("region")
    if reg:
        pad = 30
        x0, y0, x1, y1 = reg
        box = [max(0, int((x0 - pad) * s)), max(0, int((y0 - pad) * s)),
               min(im.width, int((x1 + pad) * s)), min(im.height, int((y1 + pad) * s))]
        im = im.crop(box)
    out = project.root / "reviews" / f"ch{f['chapter']}" / "findings" / f"{f['id']}@{r['rev']}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return _rel(project, out)


def _region_of(rev, page, panel=None, region=None):
    if region:
        return [round(float(v), 1) for v in region]
    if panel and page in (rev or {}):
        pn = rev[page]["_page"].panels.get(panel)
        if pn:
            return [round(v, 1) for v in pn.bbox]
    return None


def file_finding(project, F, rev, *, key, code, severity, owner, chapter, observed, intended, page=None,
                 panel=None, region=None, evidence=(), source="manual", probe=None, by="review", round_=None,
                 title=None) -> tuple[str, str]:
    """Add a finding, or record that an existing one (same key, not closed) reproduced.
    Returns (id, 'new' | 'reproduced' | 'survived' | 'reopened')."""
    if owner not in OWNERS:
        raise MangakitError(f"owner must be one of {OWNERS}")
    if severity not in SEVERITIES:
        raise MangakitError(f"severity must be one of {SEVERITIES}")
    r = (rev or {}).get(page) if page else None
    cur = {"page": page, "rev": r["rev"], "source": r["source"], "assets": r["assets"]} if r else None
    for f in F:
        if f["key"] != key:
            continue
        if f["status"] in ("editorial", "wont-fix"):     # a decision stands until someone reopens it
            f.setdefault("checks", []).append({"at": _now(), "rev": cur["rev"] if cur else None,
                                               "result": f"reproduced ({f['status']})", "round": round_, "by": by})
            return f["id"], f["status"]
        last = (f.get("checks") or [{}])[-1].get("rev") or (f.get("revision") or {}).get("rev")
        changed = bool(cur and last and cur["rev"] != last)
        if f["status"] == "verified":
            f["status"] = "open"
            _hist(f, "open", "reproduced after it was verified (regression)", by)
            res = "reopened"
        elif changed:
            f["survived"] = f.get("survived", 0) + 1
            res = "survived"
        else:
            res = "reproduced"
        f.setdefault("checks", []).append({"at": _now(), "rev": cur["rev"] if cur else None, "result": res,
                                           "round": round_, "by": by})
        f["evidence"] = list(dict.fromkeys(list(f.get("evidence", [])) + list(evidence)))
        return f["id"], res
    f = {"id": _next_id(F), "key": key, "code": code, "title": title or code, "source": source,
         "severity": severity, "owner": owner, "status": "open", "chapter": chapter,
         "page": page, "panel": panel, "region": _region_of(rev, page, panel, region),
         "observed": observed, "intended": intended, "evidence": list(evidence),
         "revision": dict(cur, round=round_) if cur else {"round": round_}, "survived": 0,
         "checks": [{"at": _now(), "rev": cur["rev"] if cur else None, "result": "filed", "round": round_, "by": by}]}
    if probe:
        f["probe"] = probe
    f["crop"] = _crop(project, f, rev) if cur else None
    _hist(f, "open", "filed", by)
    F.append(f)
    return f["id"], "new"


@_locked
def set_status(project, fid, status, note="", by="review", owner=None):
    if status not in STATUSES:
        raise MangakitError(f"status must be one of {STATUSES}")
    F = load_findings(project)
    f = _get(F, fid)
    if status in ("wont-fix", "fixed") and not note:
        raise MangakitError(f"{status} needs --note (what was done or why not)")
    f["status"] = status
    if owner:
        if owner not in OWNERS:
            raise MangakitError(f"owner must be one of {OWNERS}")
        f["owner"] = owner
    _hist(f, status, note, by)
    save_findings(project, F)
    return f


def _get(F, fid):
    for f in F:
        if f["id"] == fid:
            return f
    raise MangakitError(f"no finding {fid}")


@_locked
def editorial(project, fid, alternatives: list[dict], note="", by="review"):
    """Mark a finding as an editorial choice and keep every alternative (name, by, description, ref).
    The director (or editor) decides with `decide`; nothing is discarded."""
    if len(alternatives) < 2:
        raise MangakitError("an editorial finding keeps at least two alternatives")
    F = load_findings(project)
    f = _get(F, fid)
    have = {a["name"] for a in f.get("alternatives", [])}
    f.setdefault("alternatives", []).extend(a for a in alternatives if a["name"] not in have)
    f["status"] = "editorial"
    _hist(f, "editorial", note or f"alternatives: {', '.join(a['name'] for a in f['alternatives'])}", by)
    save_findings(project, F)
    return f


@_locked
def decide(project, fid, choice, reason, by="direct"):
    F = load_findings(project)
    f = _get(F, fid)
    names = [a["name"] for a in f.get("alternatives", [])]
    if choice not in names:
        raise MangakitError(f"{fid}: choose one of {names}")
    if not reason:
        raise MangakitError("decide needs --reason")
    f["decision"] = {"choice": choice, "reason": reason, "at": _now(), "by": by}
    # the alternatives stay recorded; the finding goes back to open work for the chosen option's owner
    alt = next(a for a in f["alternatives"] if a["name"] == choice)
    f["status"] = "wont-fix" if alt.get("keep") else "open"
    if alt.get("owner"):
        f["owner"] = alt["owner"]
    _hist(f, f["status"], f"decided: {choice} ({reason})", by)
    save_findings(project, F)
    return f


# ============================================================================ technical pass
# one name for checks that several tools report
CANON_CODE = {"unlettered-line": "line-not-lettered", "missing-dialogue": "line-not-lettered",
              "reading-order": "balloon-order"}
# owner of each code; anything else falls back to the tool that reported it
CODE_OWNER = {
    # story
    "beat-order": "board", "line-not-lettered": "board", "balloon-order": "board", "beat-not-boarded": "board",
    "reveal-on-facing-page": "board", "reveal-without-turn": "board", "reveal-not-first-after-turn": "board",
    # art and assets
    "needs-art": "illustrate", "art-resolution": "illustrate", "missing-asset": "illustrate",
    "asset-modified": "illustrate", "job-style-superseded": "illustrate", "art-style-older": "direct",
    "art-style-unrecorded": "design",
    # compose (finishing)
    "text-overflow": "compose", "breaks-mismatch": "compose", "balloon-off-trim": "compose",
    "balloon-outside-safe": "compose", "text-off-trim": "compose", "balloon-overlap": "compose",
    "balloon-covers-landmark": "compose", "stale-mask": "compose", "missing-mask": "compose", "mask-dims": "compose",
    "mask-halo": "compose", "mask-slices-ink": "compose", "breakout-cut": "compose", "breakout-intrudes": "compose",
    "undeclared-clip": "compose", "breakout-empty": "compose", "art-gap": "compose", "font-pin": "compose",
    "sfx-small": "compose",
}
TOOL_OWNER = {"story": "story", "design": "design", "board": "board", "page": "compose", "review": "compose"}
# info-level codes that are work items (filed); other infos stay in the report only
FILE_INFO = {"needs-art", "art-style-unrecorded"}
SFX_MIN = 0.18     # SFX height / panel height at which a sound starts to read as a sound effect at reading size


def _norm_where(w):
    return str(w).replace(":", "/").split(" ")[0]


def _where_page(where, pages):
    head = str(where).replace(":", "/").split("/")[0]
    return head if head in pages else None


def sfx_sizes(project, ch, built) -> list[dict]:
    """SFX height relative to its panel. The direction's sfx rule may set render.sfx.min_panel_height;
    otherwise project.yaml review.sfx_min_panel_height, default SFX_MIN."""
    from .board import page_facts
    lim = (project.cfg.get("review") or {}).get("sfx_min_panel_height", SFX_MIN)
    out = []
    for pid, page in built.items():
        si = getattr(page, "style_info", {}) or {}
        lim_p = ((si.get("render") or {}).get("sfx") or {}).get("min_panel_height", lim)
        F = page_facts(page)
        for l in F["letters"]:
            if l["kind"] != "sfx" or not l["panel"]:
                continue
            b, pb = l["bbox"], F["panels"][l["panel"]]["bbox"]
            ratio = (b[3] - b[1]) / max(1.0, pb[3] - pb[1])
            out.append({"page": pid, "panel": l["panel"], "line": l["line"], "ratio": round(ratio, 3), "min": lim_p,
                        "bbox": b})
    return out


@_locked
def tech(project: Project, chapter=None, file=True, rev=None) -> dict:
    """story check (with page cross-checks) + design check + board check (every technical page check)
    + review's own measurements, de-duplicated by (code, place) into findings with owners."""
    from . import board as B
    from . import design as D
    from .render import load_page
    from .story import pages_info
    ch = _chapter(project, chapter)
    pages = project.chapter_pages(ch)
    raw = []
    st = Story(project)
    for x in st.check(pages_info(project, ch)):
        raw.append(dict(x, tool="story"))
    try:
        for x in D.check(project):
            raw.append(dict(x, tool="design"))
    except MangakitError as e:
        raw.append({"severity": "error", "code": "design-check-failed", "where": "design", "message": str(e), "tool": "design"})
    R = B.check_chapter(project, ch, with_technical=True, all_technical=True)
    for x in R["issues"]:
        raw.append(dict(x, tool="page" if x.get("source") == "page" else "board"))
    built = {}
    from .checks import run_checks
    for pid in pages:
        try:
            built[pid] = load_page(project, pid, chapter=ch)[0]
        except Exception:
            continue
        for x in run_checks(built[pid]):       # the page checks the board pass leaves to its own codes
            if x["code"] in ("reading-order", "unlettered-line"):
                raw.append(dict(x, where=x["where"] if x["code"] == "unlettered-line" else pid, tool="page"))
    for s in sfx_sizes(project, ch, built):
        if s["ratio"] < s["min"]:
            raw.append({"severity": "warn", "code": "sfx-small", "where": f"{s['page']}/{s['panel']}",
                        "message": f"{s['line']} is {s['ratio']:.0%} of the panel height (rule minimum {s['min']:.0%})",
                        "tool": "review", "line": s["line"], "bbox": s["bbox"]})
    merged = {}
    for x in raw:
        code = CANON_CODE.get(x["code"], x["code"])
        key = f"tech:{code}:{_norm_where(x['where'])}"
        m = merged.get(key)
        if m:
            m["tools"] = sorted(set(m["tools"]) | {x["tool"]})
            if SEVERITIES.index(x["severity"]) < SEVERITIES.index(m["severity"]):
                m["severity"] = x["severity"]
            continue
        merged[key] = {"key": key, "code": code, "severity": x["severity"], "where": x["where"],
                       "message": x["message"], "tools": [x["tool"]],
                       "owner": CODE_OWNER.get(code) or TOOL_OWNER[x["tool"]], "bbox": x.get("bbox")}
    issues = sorted(merged.values(), key=lambda m: (SEVERITIES.index(m["severity"]), m["code"], m["where"]))
    res = {"chapter": ch, "raw": len(raw), "issues": issues, "filed": []}
    if file:
        rev = rev or chapter_revisions(project, ch)
        F = load_findings(project)
        for m in issues:
            if m["severity"] == "info" and m["code"] not in FILE_INFO:
                continue
            page = _where_page(m["where"], pages)
            w = _norm_where(m["where"]).split("/")
            panel = w[1] if page and len(w) > 1 and rev.get(page) and w[1] in rev[page]["_page"].panels else None
            fid, how = file_finding(project, F, rev, key=m["key"], code=m["code"], severity=m["severity"],
                                    owner=m["owner"], chapter=ch, page=page, panel=panel, region=m.get("bbox"),
                                    observed=m["message"], intended=f"no {m['code']} ({'/'.join(m['tools'])} check)",
                                    evidence=[f"{'+'.join(m['tools'])} check: {m['code']} at {m['where']}"],
                                    source="tech", probe={"kind": "tech", "key": m["key"]})
            res["filed"].append((fid, how, m["key"]))
        save_findings(project, F)
    return res


# ============================================================================ cold-read answers and score
def record_answers(project, file, chapter=None, round_=None) -> dict:
    """Copy the reader's answers into the round and lock them (sha256 in round.yaml). Answers are
    recorded before the key is written, and the score refuses answers changed after locking."""
    ch = _chapter(project, chapter)
    rd = _round_dir(project, ch, round_)
    rf = rd / "round.yaml"
    if not rf.exists():
        raise MangakitError(f"no round at {rd}; run `review packet` first")
    rec = load_yaml(rf)
    if rec.get("key"):
        raise MangakitError(f"{rd.name}: the key was already written; answers can no longer be recorded")
    data = FsPath(file).read_bytes()
    A = yaml.safe_load(data) or {}
    for k in ("speakers", "transfers", "holder_end", "eye_path", "surprises", "reveals", "unclear"):
        A.setdefault(k, [] if k != "eye_path" else {})
    dst = rd / "answers.yaml"
    if FsPath(file).resolve() != dst.resolve():
        dst.write_bytes(data)
    rec["answers"] = {"file": "answers.yaml", "sha256": hashlib.sha256(data).hexdigest(), "at": _now(),
                      "reader": A.get("reader")}
    rf.write_text(yaml.safe_dump(rec, sort_keys=False, allow_unicode=True))
    return rec["answers"]


KEY_TEMPLATE = """# Answer key for {round}: written AFTER the answers were recorded, with the story open.
# identify: map every label the reader used (people and objects) to a canon id; leave a label out
#   if it matches nothing. `caption`, `sound` and `unknown` are built in.
# triage: one entry per unclear item (by index): owner, project page id, optional panel or region
#   [x0,y0,x1,y1], severity (error|warn|info), what was intended. drop: true for no finding.
# judge: override or add a judgement for an answer, by path (eye_path.2, reveals[0], transfers[0]):
#   result ok | partial | wrong, note, owner.
identify:
{labels}
triage:
{triage}
judge: {{}}
"""


def key_template(project, chapter=None, round_=None) -> FsPath:
    ch = _chapter(project, chapter)
    rd = _round_dir(project, ch, round_)
    A = load_yaml(rd / "answers.yaml") or {}
    labels = sorted({c.get("label") for c in A.get("characters", []) if c.get("label")})
    pg = (load_yaml(rd / "round.yaml") or {}).get("pages", {})
    tri = "\n".join(f"  {i}: {{owner: direct, page: {pg.get(str(u.get('page')), {}).get('page')}, panel: null, "
                    f"severity: warn, intended: ''}}   # {str(u.get('what'))[:70]}" for i, u in enumerate(A.get("unclear", [])))
    out = rd / "key.template.yaml"
    out.write_text(KEY_TEMPLATE.format(round=rd.name, labels="\n".join(f"  {l!r}: " for l in labels) or "  {}",
                                       triage=tri or "  {}"))
    return out


def _words(s):
    return re.sub(r"[^a-z0-9 ]+", " ", str(s).lower().replace("*", "")).split()


def _sim(a, b):
    a, b = " ".join(_words(a)), " ".join(_words(b))
    if not a or not b:
        return 0.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    if b.startswith(a) or a.startswith(b):
        r = max(r, 0.9)
    return r


def _ident(K, label):
    """Reader label -> canon id (or caption/sound/unknown); a trailing '?' marks a guess."""
    if label is None:
        return None, False
    s = str(label).strip()
    guess = s.endswith("?")
    s = s.rstrip("?").strip()
    if s.lower() in ("caption", "sound", "sfx", "unknown", "narration"):
        return {"sfx": "sound", "narration": "caption"}.get(s.lower(), s.lower()), guess
    ids = K.get("identify") or {}
    for k, v in ids.items():
        if str(k).strip().lower() == s.lower():
            return v, guess
    return None, guess


def _lis_keep(seq):
    """Indexes of a longest increasing subsequence (items outside it are out of order)."""
    if not seq:
        return set()
    n = len(seq)
    best = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if seq[j] < seq[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = max(range(n), key=lambda k: best[k])
    keep = set()
    while i >= 0:
        keep.add(i)
        i = prev[i]
    return keep


def intended(project, ch, rev) -> dict:
    """What the chapter means to say, from story + board facts, per page in reading order."""
    from . import board as B
    st = Story(project)
    pages = [p for p in project.chapter_pages(ch) if p in rev]
    R = B.check_chapter(project, ch, with_technical=False)
    lines = []
    for pid in pages:
        F = R["facts"].get(pid)
        for l in (F or {}).get("letters", []):
            L = st.line.get(l["line"], {})
            kind = L.get("kind")
            who = "caption" if kind == "caption" else "sound" if kind == "sfx" else L.get("speaker")
            lines.append({"line": l["line"], "page": pid, "panel": l["panel"], "text": L.get("text", ""),
                          "speaker": who, "bbox": l["bbox"]})
    beats = [b for b in st.beats if str(b.get("chapter")) == ch]
    beat_page = {}
    for pid in pages:
        F = R["facts"].get(pid) or {}
        for pn in F.get("geometric", []):
            b = F["panels"][pn]["beat"]
            beat_page.setdefault(b, (pid, pn))
    transfers = []
    for e in st.events:
        if e.get("attribute") == "holder" and e.get("beat") in beat_page:
            pid, pn = beat_page[e["beat"]]
            transfers.append({"object": e["subject"], "from": e.get("from"), "to": e["value"], "page": pid,
                              "panel": pn, "beat": e["beat"], "event": e.get("id")})
    holders = {}
    if beats:
        stt = st.state_at(beats[-1]["id"], after=True)
        for k, v in stt.items():
            subj, attr = k.split(".", 1)
            if attr == "holder" and subj in st.props:
                holders[subj] = v
    reveals = []
    for k, t in enumerate(R["turns"]):
        for r in t["reveals"]:
            reveals.append(dict(r, after_turn=t["after_turn"], about=st.facts.get(r["fact"], {}).get("about", []),
                                keywords=st.facts.get(r["fact"], {}).get("keywords", []),
                                statement=st.facts.get(r["fact"], {}).get("statement", "")))
    focal = {}
    for pid in pages:
        F = R["facts"].get(pid) or {}
        seq = []
        for pn in F.get("geometric", []):
            ms = sorted([m for m in F["marks"] if m["mark"] == "focal" and m.get("panel") == pn],
                        key=lambda m: m.get("rank", 1))
            seq += [f"{pn}: {m.get('label') or 'focal'}" for m in ms]
        focal[pid] = seq
    return {"lines": lines, "transfers": transfers, "holders": holders, "reveals": reveals, "focal": focal,
            "pages": pages}


@_locked
def score(project: Project, chapter=None, round_=None, file=True, force=False) -> dict:
    """Compare a recorded cold read with the intended reading and file a finding per mismatch."""
    ch = _chapter(project, chapter)
    rd = _round_dir(project, ch, round_)
    rec = load_yaml(rd / "round.yaml")
    if not rec.get("answers"):
        raise MangakitError(f"{rd.name}: record the answers first (`review answers`)")
    data = (rd / "answers.yaml").read_bytes()
    if hashlib.sha256(data).hexdigest() != rec["answers"]["sha256"]:
        raise MangakitError(f"{rd.name}: answers.yaml changed after it was recorded")
    kf = rd / "key.yaml"
    if not kf.exists():
        key_template(project, ch, rd.name)
        raise MangakitError(f"{rd.name}: write key.yaml (template: {rd / 'key.template.yaml'})")
    A = yaml.safe_load(data) or {}
    K = load_yaml(kf) or {}
    if not rec.get("key"):
        rec["key"] = {"file": "key.yaml", "sha256": hashlib.sha256(kf.read_bytes()).hexdigest(), "at": _now()}
        (rd / "round.yaml").write_text(yaml.safe_dump(rec, sort_keys=False, allow_unicode=True))
    num = {int(k): v["page"] for k, v in rec["pages"].items()}
    rev = {pid: page_revision(project, pid, ch) for pid in num.values()}
    stale = [pid for n, pid in num.items() if rev[pid]["rev"] != rec["pages"][str(n)]["rev"]]
    if stale and not force:
        raise MangakitError(f"pages changed since the packet was made: {stale}; score against what was read "
                            f"(rebuild those revisions) or pass --force")
    I = intended(project, ch, rev)
    judge = K.get("judge") or {}
    out = {"round": rd.name, "reader": A.get("reader"), "questions": {}, "findings": [], "stale": stale}
    new = []   # (kwargs for file_finding)

    def J(path):
        return judge.get(path) or {}

    # Q1 speakers -------------------------------------------------------------------------------
    by_page = {}
    for i, s in enumerate(A.get("speakers") or []):
        by_page.setdefault(num.get(s.get("page")), []).append((i, s))
    matched = {}
    for pid in I["pages"]:
        cands = [l for l in I["lines"] if l["page"] == pid]
        for i, s in by_page.get(pid, []):
            best = max(cands, key=lambda l: _sim(s.get("words", ""), l["text"]), default=None)
            if best and _sim(s.get("words", ""), best["text"]) >= 0.45 and best["line"] not in matched:
                matched[best["line"]] = (i, s)
    rows, ok = [], 0
    order_ix = {l["line"]: k for k, l in enumerate(I["lines"])}
    reader_seq = sorted(matched, key=lambda lid: matched[lid][0])
    keep = _lis_keep([order_ix[l] for l in reader_seq])
    out_of_order = {reader_seq[k] for k in range(len(reader_seq)) if k not in keep}
    for l in I["lines"]:
        m = matched.get(l["line"])
        if not m:
            rows.append({"line": l["line"], "page": l["page"], "intended": l["speaker"], "read": None, "result": "missed"})
            new.append(dict(key=f"cold:missed-line:{l['line']}", code="cold-missed-line", severity="warn", owner="compose",
                            page=l["page"], panel=l["panel"], region=l["bbox"],
                            observed=f"the reader did not report {l['text']!r}",
                            intended=f"{l['line']} is read in its panel ({l['speaker']})"))
            continue
        i, s = m
        who, guess = _ident(K, s.get("speaker"))
        good = who == l["speaker"]
        res = ("ok" if not guess else "ok (guess)") if good else "wrong-speaker"
        if l["line"] in out_of_order:
            res += ", out of order"
        ok += 1 if good and l["line"] not in out_of_order else 0
        rows.append({"line": l["line"], "page": l["page"], "intended": l["speaker"], "read": s.get("speaker"),
                     "identified": who, "result": res, "answer": f"speakers[{i}]"})
        if not good:
            new.append(dict(key=f"cold:speaker:{l['line']}", code="cold-speaker", severity="warn", owner="board",
                            page=l["page"], panel=l["panel"], region=l["bbox"],
                            observed=f"{l['text']!r} read as said by {s.get('speaker')!r}",
                            intended=f"said by {l['speaker']}", evidence=[f"answers.yaml#speakers[{i}]"]))
        if l["line"] in out_of_order:
            new.append(dict(key=f"cold:order:{l['line']}", code="cold-order", severity="warn", owner="board",
                            page=l["page"], panel=l["panel"], region=l["bbox"],
                            observed=f"{l['text']!r} was read out of script order",
                            intended="balloons read in script order", evidence=[f"answers.yaml#speakers[{i}]"]))
    out["questions"]["speakers"] = {"ok": ok, "total": len(I["lines"]), "rows": rows}

    # Q2 transfers --------------------------------------------------------------------------------
    rows, ok = [], 0
    ans = A.get("transfers") or []
    for t in I["transfers"]:
        hit = None
        for i, a in enumerate(ans):
            if _ident(K, a.get("object"))[0] == t["object"]:
                hit = (i, a)
                break
        if not hit:
            rows.append({"object": t["object"], "result": "missed"})
            new.append(dict(key=f"cold:transfer:{t['event'] or t['object']}", code="cold-transfer-missed", severity="error",
                            owner="board", page=t["page"], panel=t["panel"],
                            observed=f"the reader did not see {t['object']} change hands",
                            intended=f"{t['object']}: {t['from']} -> {t['to']} in {t['page']}/{t['panel']}"))
            continue
        i, a = hit
        fr, to = _ident(K, a.get("from"))[0], _ident(K, a.get("to"))[0]
        pg = num.get(a.get("page"))
        bad = [x for x, good in (("from", fr == t["from"]), ("to", to == t["to"]), ("page", pg == t["page"])) if not good]
        j = J(f"transfers[{i}]")
        res = j.get("result") or ("ok" if not bad else "wrong " + "/".join(bad))
        ok += res == "ok"
        rows.append({"object": t["object"], "intended": f"{t['from']} -> {t['to']} on {t['page']}",
                     "read": f"{a.get('from')} -> {a.get('to')} on page {a.get('page')}", "result": res})
        if res != "ok":
            new.append(dict(key=f"cold:transfer:{t['event'] or t['object']}", code="cold-transfer", severity="error",
                            owner=j.get("owner", "board"), page=t["page"], panel=t["panel"],
                            observed=f"read as {a.get('from')} -> {a.get('to')} on page {a.get('page')}",
                            intended=f"{t['from']} -> {t['to']} in {t['page']}/{t['panel']}",
                            evidence=[f"answers.yaml#transfers[{i}]"] + ([j["note"]] if j.get("note") else [])))
    out["questions"]["transfers"] = {"ok": ok, "total": len(I["transfers"]), "rows": rows}

    # Q3 owner at the end -------------------------------------------------------------------------
    rows, ok = [], 0
    for obj, holder in I["holders"].items():
        a = next((x for x in A.get("holder_end") or [] if _ident(K, x.get("object"))[0] == obj), None)
        got = _ident(K, a.get("holder"))[0] if a else None
        res = "ok" if got == holder else ("missed" if not a else "wrong")
        ok += res == "ok"
        rows.append({"object": obj, "intended": holder, "read": a.get("holder") if a else None, "result": res})
        if res != "ok":
            last = I["pages"][-1]
            new.append(dict(key=f"cold:holder-end:{obj}", code="cold-holder-end", severity="error", owner="board",
                            page=last, observed=f"at the end the reader thinks {obj} is with {a.get('holder') if a else 'nobody'}",
                            intended=f"{obj} is with {holder}"))
    out["questions"]["holder_end"] = {"ok": ok, "total": len(I["holders"]), "rows": rows}

    # Q4 eye path (judged by the reviewer against the board's focal order) ---------------------------
    rows, ok, judged = [], 0, 0
    for n, pid in sorted(num.items()):
        a = (A.get("eye_path") or {}).get(n) or (A.get("eye_path") or {}).get(str(n)) or []
        j = J(f"eye_path.{n}")
        res = j.get("result", "unjudged")
        judged += res != "unjudged"
        ok += res == "ok"
        rows.append({"page": pid, "read": a, "intended": I["focal"].get(pid, []), "result": res, "note": j.get("note")})
        if res in ("wrong", "partial"):
            new.append(dict(key=f"cold:eye-path:{pid}", code="cold-eye-path", severity="warn", owner=j.get("owner", "board"),
                            page=pid, panel=j.get("panel"), observed=f"eye went: {' -> '.join(map(str, a))}",
                            intended=" -> ".join(I["focal"].get(pid, [])), evidence=[j.get("note", "")]))
    out["questions"]["eye_path"] = {"ok": ok, "total": judged, "unjudged": len(rows) - judged, "rows": rows}

    # Q6 reveals (and Q5 surprises) -----------------------------------------------------------------
    rows, ok = [], 0
    ra = A.get("reveals") or []
    for r in I["reveals"]:
        hit = None
        for i, a in enumerate(ra):
            jj = J(f"reveals[{i}]")
            if jj.get("fact") == r["fact"]:
                hit = (i, a)
                break
            text = " " + " ".join(_words(a.get("what", ""))) + " "
            ents = {_ident(K, lab)[0] for lab in (K.get("identify") or {}) if f" {' '.join(_words(lab))} " in text}
            if ents & set(r["about"]) or any(f" {w.lower()} " in text for w in r["keywords"]):
                hit = (i, a)
                break
        if not hit:
            rows.append({"fact": r["fact"], "intended": f"{r['page']} after a turn" if r["after_turn"] else r["page"],
                         "result": "missed"})
            new.append(dict(key=f"cold:reveal:{r['fact']}", code="cold-reveal-missed", severity="error", owner="board",
                            page=r["page"], panel=r["panel"], observed="the reader did not report this reveal",
                            intended=f"{r['statement']} (revealed in {r['page']}/{r['panel']})"))
            continue
        i, a = hit
        pg = num.get(a.get("page"))
        order = I["pages"].index(pg) - I["pages"].index(r["page"]) if pg in I["pages"] else None
        j = J(f"reveals[{i}]")
        res = j.get("result") or ("ok" if order == 0 and bool(a.get("after_turn")) == r["after_turn"] else
                                  "early" if order is not None and order < 0 else "late" if order else "timing")
        ok += res == "ok"
        rows.append({"fact": r["fact"], "intended": f"{r['page']}" + (" right after a page turn" if r["after_turn"] else ""),
                     "read": f"page {a.get('page')}" + (" after a turn" if a.get("after_turn") else ""), "what": a.get("what"),
                     "result": res, "note": j.get("note")})
        if res != "ok":
            code = {"early": "cold-reveal-early", "late": "cold-reveal-late", "partial": "cold-reveal-partial"}.get(res, "cold-reveal")
            new.append(dict(key=f"cold:reveal:{r['fact']}", code=code, severity="error" if res == "early" else "warn",
                            owner=j.get("owner", "board"), page=r["page"], panel=r["panel"],
                            observed=f"{a.get('what')} (page {a.get('page')})", intended=r["statement"],
                            evidence=[f"answers.yaml#reveals[{i}]"] + ([j["note"]] if j.get("note") else [])))
    out["questions"]["reveals"] = {"ok": ok, "total": len(I["reveals"]), "rows": rows}
    rp = {r["page"] for r in I["reveals"]}
    sp = [num.get(s.get("page")) for s in A.get("surprises") or []]
    hit = bool(rp & set(sp)) if rp else True
    out["questions"]["surprise"] = {"ok": int(hit), "total": 1 if rp else 0, "rows": [
        {"read": [f"page {s.get('page')}: {s.get('what')}" for s in A.get("surprises") or []],
         "intended": sorted(rp), "result": "ok" if hit else "flat"}]}
    if not hit:
        for r in I["reveals"]:
            new.append(dict(key=f"cold:surprise:{r['fact']}", code="cold-reveal-flat", severity="info", owner="board",
                            page=r["page"], panel=r["panel"], observed="nothing on the reveal page surprised the reader",
                            intended=f"the reveal of {r['fact']} lands as a surprise"))

    # Q7 unclear ----------------------------------------------------------------------------------
    tri = K.get("triage") or {}
    rows = []
    for i, u in enumerate(A.get("unclear") or []):
        t = tri.get(i) or tri.get(str(i)) or {}
        pid = t.get("page") or num.get(u.get("page"))
        rows.append({"page": pid, "where": u.get("where"), "what": u.get("what"), "owner": t.get("owner", "direct"),
                     "dropped": bool(t.get("drop"))})
        if t.get("drop"):
            continue
        new.append(dict(key=t.get("key") or f"cold:unclear:{rd.name}:{i}", code=t.get("code", "cold-unclear"),
                        severity=t.get("severity", "warn"), owner=t.get("owner", "direct"), page=pid, panel=t.get("panel"),
                        region=t.get("region"), observed=f"{u.get('where')}: {u.get('what')}",
                        intended=t.get("intended", ""), evidence=[f"answers.yaml#unclear[{i}]"], probe=t.get("probe"),
                        title=t.get("title")))
    out["questions"]["unclear"] = {"items": len(rows), "rows": rows}
    scored = [q for k, q in out["questions"].items() if k not in ("unclear",) and q.get("total")]
    out["score"] = {"ok": sum(q["ok"] for q in scored), "total": sum(q["total"] for q in scored)}

    if file:
        F = load_findings(project)
        for kw in new:
            ev = [f"{_rel(project, rd)}/{e}" if e.startswith("answers.yaml") else e for e in kw.pop("evidence", []) if e]
            fid, how = file_finding(project, F, rev, chapter=ch, source="cold-read", round_=rd.name,
                                    evidence=ev + [f"{_rel(project, rd)}/packet"], **kw)
            out["findings"].append((fid, how, kw["key"]))
        # earlier cold-read findings this read no longer reproduces
        keys = {kw["key"] for kw in new}
        for f in F:
            if f["source"] != "cold-read" or f["status"] not in ("open", "fixed") or f["key"] in keys:
                continue
            if f["key"].startswith("cold:unclear:") or (f.get("checks") or [{}])[-1].get("round") == rd.name:
                continue
            pg = f.get("page")
            last = (f.get("checks") or [{}])[-1].get("rev")
            changed = pg in rev and last and rev[pg]["rev"] != last
            res = "verified" if changed or f["status"] == "fixed" else "not-reproduced"
            f.setdefault("checks", []).append({"at": _now(), "rev": rev.get(pg, {}).get("rev"), "result": res, "round": rd.name})
            if res == "verified":
                f["status"] = "verified"
                _hist(f, "verified", f"cold read {rd.name} reads it as intended")
            out["findings"].append((f["id"], res, f["key"]))
        save_findings(project, F)
    (rd / "score.json").write_text(json.dumps(out, indent=2, default=str))
    (rd / "score.md").write_text(score_md(out))
    return out


def score_md(S) -> str:
    L = [f"# Cold-read score: {S['round']} (reader: {S['reader']})", "",
         f"Overall: {S['score']['ok']}/{S['score']['total']} scored answers match the intended reading.", ""]
    Q = S["questions"]
    L += ["## 1. Speaker order", "", "| line | page | intended | read | result |", "|---|---|---|---|---|"]
    L += [f"| {r['line']} | {r['page']} | {r['intended']} | {r.get('read') or '-'} | {r['result']} |" for r in Q["speakers"]["rows"]]
    L += ["", f"{Q['speakers']['ok']}/{Q['speakers']['total']}", "", "## 2. What changed hands", ""]
    L += [f"- {r['object']}: intended {r.get('intended', '-')}; read {r.get('read', '-')}: **{r['result']}**" for r in Q["transfers"]["rows"]]
    L += ["", "## 3. Owner at the end", ""]
    L += [f"- {r['object']}: intended {r['intended']}; read {r['read']}: **{r['result']}**" for r in Q["holder_end"]["rows"]]
    L += ["", "## 4. Eye path (reader vs board focal order)", ""]
    for r in Q["eye_path"]["rows"]:
        L += [f"- {r['page']}: read {' -> '.join(map(str, r['read']))}", f"  intended {' -> '.join(r['intended'])}",
              f"  **{r['result']}**" + (f": {r['note']}" if r.get("note") else "")]
    L += ["", "## 5. Surprise", ""]
    for r in Q["surprise"]["rows"]:
        L += [f"- read: {'; '.join(r['read']) or '-'}", f"- reveal pages: {', '.join(r['intended']) or '-'}: **{r['result']}**"]
    L += ["", "## 6. Reveal timing", ""]
    L += [f"- {r['fact']}: intended {r['intended']}; read {r.get('read', '-')} ({r.get('what', '')}): **{r['result']}**"
          + (f" ({r['note']})" if r.get("note") else "") for r in Q["reveals"]["rows"]]
    L += ["", "## 7. Unclear", ""]
    L += [f"- {r['page']} {r['where']}: {r['what']} -> {'dropped' if r['dropped'] else r['owner']}" for r in Q["unclear"]["rows"]]
    L += ["", "## Findings", ""] + [f"- {fid} {how}: {key}" for fid, how, key in S["findings"]]
    if S.get("stale"):
        L += ["", f"WARNING: scored against changed pages {S['stale']}"]
    return "\n".join(L) + "\n"


# ============================================================================ art vs story
def panel_assertions(project, ch, rev) -> list[dict]:
    """Per panel in reading order: what the story asserts there (location, who is present and in
    which costume, props shown and who holds them, explicit asserts) and the art that shows it."""
    from . import board as B
    from .design import design_for
    st = Story(project)
    R = B.check_chapter(project, ch, with_technical=False)
    rows = []
    for pid in [p for p in project.chapter_pages(ch) if p in rev]:
        F = R["facts"].get(pid) or {}
        for pn in F.get("geometric", []):
            b = F["panels"][pn]["beat"]
            beat = st.beat.get(b, {})
            before = st.state_at(b, after=False) if b in st.beat else {}
            after = st.state_at(b, after=True) if b in st.beat else {}
            present = []
            for c in beat.get("present", []):
                cos = after.get(f"{c}.costume")
                try:
                    d = design_for(project, c, beat=b)
                except MangakitError:
                    d = None
                present.append({"id": c, "costume": cos, "design": d, "location": after.get(f"{c}.location")})
            props = []
            here = set(beat.get("present", []))
            carried = [k.split(".")[0] for k, v in before.items() if k.endswith(".holder") and v in here]
            for pr in list(dict.fromkeys(list(beat.get("shows", [])) + carried)):
                h0, h1 = before.get(f"{pr}.holder"), after.get(f"{pr}.holder")
                props.append({"id": pr, "holder": h1 if h0 == h1 else f"{h0} -> {h1}",
                              "shown": pr in beat.get("shows", [])})
            art = [f"{i['asset']}@{i['version']} ({i['kind']})" for i in F["images"] if i["panel"] == pn and not i["break"]]
            rows.append({"page": pid, "panel": pn, "beat": b, "location": beat.get("location"), "present": present,
                         "props": props, "asserts": beat.get("asserts", []), "art": art,
                         "final": any(i["kind"] == "drawing" for i in F["images"] if i["panel"] == pn),
                         "bbox": F["panels"][pn]["bbox"]})
    return rows


@_locked
def art_sheet(project: Project, chapter=None, out=None, verdicts=None) -> dict:
    """A sheet per chapter: each panel's crop (clean reading render) next to the facts the story asserts
    there, plus the design view thumbnails of who is present, for an eye check. With `verdicts`
    (yaml: list of {page, panel, ok, observed, intended, owner, severity, region}) every ok: false
    becomes an `art-contradicts-story` finding."""
    from .references import RefRegistry
    ch = _chapter(project, chapter)
    rev = chapter_revisions(project, ch)
    rows = panel_assertions(project, ch, rev)
    od = FsPath(out) if out else project.root / "reviews" / f"ch{ch}" / "art-story"
    od.mkdir(parents=True, exist_ok=True)
    rr = RefRegistry(project)
    CH, TW, W = 320, 520, 1500
    sheet = Image.new("RGB", (W, 60 + len(rows) * (CH + 20)), "#ffffff")
    d = ImageDraw.Draw(sheet)
    d.text((20, 30), f"chapter {ch}: art vs story, panels in reading order (crop | asserted facts | design views)",
           fill="#000000", font=_font(project, 24), anchor="lm")
    md = [f"# Art vs story, chapter {ch}", "", "Look at each crop against the facts beside it. A drawing that "
          "contradicts the story (wrong holder, costume, person, place) is a finding; record it in a verdicts "
          "file and run `review art --verdicts`.", ""]
    for k, r in enumerate(rows):
        y = 60 + k * (CH + 20)
        im = Image.open(rev[r["page"]]["png"]).convert("RGB")
        s = im.height / rev[r["page"]]["_page"].height
        x0, y0, x1, y1 = r["bbox"]
        c = im.crop((max(0, int(x0 * s)), max(0, int(y0 * s)), min(im.width, int(x1 * s)), min(im.height, int(y1 * s))))
        c.thumbnail((TW, CH))
        sheet.paste(c, (20, y))
        lines = [f"{r['page']}/{r['panel']}   beat {r['beat']}   at {r['location']}",
                 "present: " + ", ".join(f"{p['id']} [{p['costume'] or '-'}]" for p in r["present"]),
                 "props: " + (", ".join(f"{p['id']} held by {p['holder']}" + ("" if p["shown"] else " (carried, not in shows)")
                                        for p in r["props"]) or "-"),
                 "asserts: " + (", ".join(r["asserts"]) or "-"),
                 "art: " + (", ".join(r["art"]) or "NONE") + ("" if r["final"] else "   (no final art)")]
        for i, t in enumerate(lines):
            d.text((TW + 40, y + 16 + i * 34), t, fill="#000000" if i else "#b00000", font=_font(project, 21))
        tx = TW + 40
        for p in r["present"]:
            if not p["design"]:
                continue
            try:
                ref = rr.resolve(p["design"])
                t = Image.open(ref["file"]).convert("RGB")
                t.thumbnail((150, 100))
                if tx + 160 > W:
                    break
                sheet.paste(t, (tx, y + CH - 100))
                d.text((tx, y + CH - 112), p["design"][:28], fill="#555555", font=_font(project, 14))
                tx += 170
            except Exception:
                continue
        md += [f"## {r['page']}/{r['panel']} ({r['beat']})", *[f"- {t}" for t in lines[1:]],
               f"- design: {', '.join(p['design'] or '-' for p in r['present'])}", ""]
    png = od / "art-story.png"
    sheet.save(png)
    (od / "art-story.md").write_text("\n".join(md) + "\n")
    (od / "art-story.yaml").write_text(yaml.safe_dump({"chapter": ch, "panels": rows}, sort_keys=False, allow_unicode=True))
    res = {"png": str(png), "md": str(od / "art-story.md"), "rows": rows, "filed": []}
    if verdicts:
        V = load_yaml(verdicts) or []
        F = load_findings(project)
        for v in V if isinstance(V, list) else V.get("verdicts", []):
            if v.get("ok", True):
                continue
            fid, how = file_finding(project, F, rev, key=v.get("key") or f"art:{v['page']}/{v['panel']}:{_slug(v.get('observed', ''))}",
                                    code=v.get("code", "art-contradicts-story"), severity=v.get("severity", "warn"),
                                    owner=v.get("owner", "illustrate"), chapter=ch, page=v["page"], panel=v.get("panel"),
                                    region=v.get("region"), observed=v.get("observed", ""), intended=v.get("intended", ""),
                                    evidence=[_rel(project, png), *v.get("evidence", [])], source="art-story",
                                    probe=v.get("probe"), title=v.get("title"))
            res["filed"].append((fid, how))
        save_findings(project, F)
    return res


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:32]


@_locked
def add(project, chapter=None, **kw) -> tuple[str, str]:
    """A finding the reviewer files by hand (visual read, editorial note, design judgement)."""
    ch = _chapter(project, chapter)
    page = kw.get("page")
    rev = {page: page_revision(project, page, ch)} if page else {}
    F = load_findings(project)
    key = kw.pop("key", None) or f"manual:{page or 'chapter'}:{kw.get('panel') or ''}:{_slug(kw.get('title') or kw['observed'])}"
    fid, how = file_finding(project, F, rev, key=key, chapter=ch, source=kw.pop("source", "manual"), **kw)
    save_findings(project, F)
    return fid, how


# ============================================================================ probes, recheck
def run_probe(project, f, rev, tech_keys) -> tuple[str | None, str]:
    """Machine check attached to a finding. Returns ('holds' | 'gone' | None, detail)."""
    p = f.get("probe") or {}
    kind = p.get("kind")
    if kind == "tech":
        return ("holds" if p["key"] in tech_keys else "gone"), p["key"]
    page = rev.get(p.get("page") or f.get("page"), {}).get("_page")
    if page is None:
        return None, "page not built"
    from .render import iter_layers
    if kind == "tail-gap":
        import math
        for L in iter_layers(page.layers):
            if L.kind == "balloon" and L.data["dialogue"] == p["line"]:
                tip, to = L.data.get("tail_tip"), L.data.get("tail_to")
                if tip is None or to is None:
                    return "holds", f"{p['line']} has no tail"
                tgt = page.anchors[to] if isinstance(to, str) else to
                gap = math.dist(tip, tgt)
                return ("holds" if gap > p.get("max", 40) else "gone"), f"{p['line']} tail tip {gap:.0f} u from its target (max {p.get('max', 40)})"
        return "holds", f"{p['line']} not lettered"
    if kind == "sfx-size":
        for s in sfx_sizes(project, f["chapter"], {page.id: page}):
            if s["line"] == p["line"]:
                lim = p.get("min", s["min"])
                return ("holds" if s["ratio"] < lim else "gone"), f"{p['line']} at {s['ratio']:.0%} of panel height (min {lim:.0%})"
        return None, f"{p['line']} not found"
    return None, "no probe"


@_locked
def recheck(project: Project, chapter=None, out=None) -> dict:
    """Re-render every page that has an open or fixed finding, in reading order, with its spread;
    re-run the technical pass and each finding's probe. A finding whose check no longer holds is
    verified. One that still holds after its page's revision changed has survived that revision.
    Findings without a machine check get before/after crops and wait for a verdict."""
    from .render import spread_groups
    ch = _chapter(project, chapter)
    F = load_findings(project)
    live = [f for f in F if f["status"] in ("open", "fixed") and str(f.get("chapter")) == ch]
    pages = [p for p in project.chapter_pages(ch) if any(f.get("page") == p for f in live)]
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    od = FsPath(out) if out else project.root / "reviews" / f"ch{ch}" / "recheck" / stamp
    od.mkdir(parents=True, exist_ok=True)
    rev = {}
    for pid in pages:                       # in reading order
        rev[pid] = page_revision(project, pid, ch)
    groups = [g for g in spread_groups(project, project.chapter_pages(ch), ch) if set(g) & set(pages)]
    from . import board as B
    spreads = []
    for g in groups:
        for pid in g:
            rev.setdefault(pid, page_revision(project, pid, ch))
        im = B.spread_image(project, g, ch)
        p = od / f"spread-{'-'.join(g)}.png"
        im.save(p)
        spreads.append(_rel(project, p))
    T = tech(project, ch, file=False)
    tech_keys = {m["key"] for m in T["issues"]}
    rows = []
    for f in live:
        pg = f.get("page")
        last = next((c["rev"] for c in reversed(f.get("checks") or []) if c.get("rev")), None) or (f.get("revision") or {}).get("rev")
        cur = rev.get(pg, {}).get("rev")
        changed = bool(cur and last and cur != last)
        state, detail = run_probe(project, f, rev, tech_keys) if f.get("probe") else (None, "")
        if state == "gone":
            res = "verified"
            f["status"] = "verified"
            _hist(f, "verified", f"recheck: {detail}", rev=cur)
        elif state == "holds":
            res = "survived" if changed else "unchanged"
            if changed:
                f["survived"] = f.get("survived", 0) + 1
                if f["status"] == "fixed":
                    f["status"] = "open"
                    _hist(f, "open", f"recheck: the fix did not remove it ({detail})", rev=cur)
        else:
            res = "needs-verdict" if changed else "unchanged"
        before = f.get("crop")
        after = _crop(project, f, rev) if (changed and pg in rev) else None
        if after:
            f["crop_after"] = after
            if before:
                ba = _before_after(project, before, after, od / f"{f['id']}-before-after.png", f)
                f.setdefault("evidence", []).append(_rel(project, ba))
        f.setdefault("checks", []).append({"at": _now(), "rev": cur, "result": res, "detail": detail or None})
        rows.append({"id": f["id"], "page": pg, "owner": f["owner"], "code": f["code"], "rev": f"{last} -> {cur}" if changed else cur,
                     "result": res, "detail": detail, "status": f["status"], "survived": f.get("survived", 0)})
    # new technical issues that appeared on the rechecked pages
    known = {f["key"] for f in F}
    fresh = [m for m in T["issues"] if m["key"] not in known and (m["severity"] != "info" or m["code"] in FILE_INFO)
             and _where_page(m["where"], project.chapter_pages(ch)) in pages]
    save_findings(project, F)
    if fresh:
        tech(project, ch, file=True, rev=rev)
    rep = {"dir": str(od), "pages": [{"page": p, "rev": rev[p]["rev"]} for p in pages], "spreads": spreads,
           "rows": rows, "new": [m["key"] for m in fresh]}
    (od / "recheck.md").write_text(recheck_md(rep))
    (od / "recheck.json").write_text(json.dumps(rep, indent=2))
    return rep


def _before_after(project, before, after, out, f):
    a = Image.open(project.root / before).convert("RGB")
    b = Image.open(project.root / after).convert("RGB")
    h = max(a.height, b.height)
    im = Image.new("RGB", (a.width + b.width + 30, h + 40), "#ffffff")
    im.paste(a, (0, 40))
    im.paste(b, (a.width + 30, 40))
    d = ImageDraw.Draw(im)
    d.text((4, 20), f"{f['id']} before", fill="#000000", font=_font(project, 18), anchor="lm")
    d.text((a.width + 34, 20), "after", fill="#000000", font=_font(project, 18), anchor="lm")
    im.save(out)
    return out


def recheck_md(rep) -> str:
    L = ["# Recheck", "", "Pages re-rendered in reading order: " + ", ".join(f"{p['page']}@{p['rev']}" for p in rep["pages"]),
         "", "Spreads: " + ", ".join(rep["spreads"]), "", "| finding | page | owner | code | revision | result | detail |",
         "|---|---|---|---|---|---|---|"]
    L += [f"| {r['id']} | {r['page']} | {r['owner']} | {r['code']} | {r['rev']} | {r['result']} | {r['detail'] or ''} |" for r in rep["rows"]]
    c = {}
    for r in rep["rows"]:
        c[r["result"]] = c.get(r["result"], 0) + 1
    L += ["", "Totals: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items()))]
    if rep["new"]:
        L += ["", "New technical issues filed: " + ", ".join(rep["new"])]
    return "\n".join(L) + "\n"


@_locked
def verdict(project, fid, result, note, by="review"):
    """Close a needs-verdict recheck by eye: verified (the fix reads as intended) or survived."""
    if result not in ("verified", "survived"):
        raise MangakitError("verdict is verified or survived")
    if not note:
        raise MangakitError("a verdict needs --note (what you looked at)")
    F = load_findings(project)
    f = _get(F, fid)
    if result == "verified":
        f["status"] = "verified"
    else:
        f["survived"] = f.get("survived", 0) + 1
        f["status"] = "open"
    f.setdefault("checks", []).append({"at": _now(), "rev": (f.get("checks") or [{}])[-1].get("rev"), "result": result,
                                       "detail": note, "by": by})
    _hist(f, f["status"], f"verdict {result}: {note}", by)
    save_findings(project, F)
    return f


# ============================================================================ listing and metrics
def summary(project, chapter=None, status=None, owner=None) -> list[dict]:
    F = load_findings(project)
    return [f for f in F if (not chapter or str(f.get("chapter")) == str(chapter))
            and (not status or f["status"] in status.split(",")) and (not owner or f["owner"] in owner.split(","))]


def format_findings(F) -> str:
    out = []
    for f in F:
        where = f"{f.get('page') or '-'}{'/' + f['panel'] if f.get('panel') else ''}"
        out.append(f"{f['id']} [{f['status']:<9}] {f['severity']:<5} {f['owner']:<10} {f['code']:<22} {where:<22} "
                   f"survived={f.get('survived', 0)}")
        out.append(f"     observed: {f['observed']}")
        if f.get("intended"):
            out.append(f"     intended: {f['intended']}")
        if f.get("alternatives"):
            out.append("     alternatives: " + "; ".join(f"{a['name']} ({a.get('owner', '-')}): {a.get('description', '')}" for a in f["alternatives"]))
        if f.get("crop"):
            out.append(f"     crop: {f['crop']}")
    return "\n".join(out)


def metrics(project, chapter=None) -> dict:
    """Pilot metrics: illustration calls per accepted panel and art calls from lettering/mask edits
    (from the job log), findings that survived a revision, and the latest cold-read score."""
    from .illustrate import metrics as art_metrics
    ch = _chapter(project, chapter)
    m = art_metrics(project)
    F = [f for f in load_findings(project) if str(f.get("chapter")) == ch]
    revised = [f for f in F if any(c.get("result") in ("survived", "verified", "needs-verdict") for c in f.get("checks", []))
               or f.get("survived")]
    rd = _round_dir(project, ch)
    sc = json.loads((rd / "score.json").read_text()) if (rd / "score.json").exists() else None
    return {"chapter": ch,
            "illustration_calls_per_accepted_panel": m["illustration_calls_per_accepted_panel"],
            "accepted_panels": m["accepted_panels"],
            "art_calls_from_lettering_or_mask_edits": m["art_calls_caused_by_lettering_or_mask_edits"],
            "findings": len(F), "open": sum(f["status"] == "open" for f in F),
            "findings_rechecked_after_a_revision": len(revised),
            "findings_survived_a_revision": sum(1 for f in F if f.get("survived")),
            "cold_read": {"round": rd.name, "reader": sc and sc["reader"], **(sc["score"] if sc else {})},
            "by_owner": {o: sum(1 for f in F if f["owner"] == o and f["status"] in ("open", "editorial")) for o in OWNERS}}
