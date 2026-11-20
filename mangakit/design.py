"""Design records: reference sheets tied to canon, costume variants keyed by continuity, and the art
direction guide (versioned style rules with style cards, effective from a chapter or beat).

references/direction.yaml
  guide: <title>
  revisions:
  - id: sr-001
    effective: {chapter: '01'}            # or {beat: <beat-id>} (art briefs switch at that beat)
    based_on: null                        # a revision inherits every rule of its base, then overrides
    note: ...
    rules:
      line-weight:                         # rule kinds: line-weight, tone-density, motif, type, sfx, title, other
        kind: line-weight
        text: plain-words rule sent in every art brief
        cards: [style-line@v001#cuff]      # style cards: exemplar images (reference specs) for this rule
        brief: true                        # pin the cards in art requests (false = text only)
        render: {styles: {panel-border: {width: 4.5}}}   # project.yaml overrides for pages under it
chapters/<ch>/chapter.yaml `style: sr-001` pins a chapter to a revision (written by `style revise`).

Authority: design owns what things look like (sheets, variants, the direction); story owns when a
look changes (continuity events on <char>.costume); a chapter's pin owns which revision its pages use.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path as FsPath

from .project import MangakitError, Project, dump_yaml, load_yaml, sha256_file
from .references import DESIGN_KINDS, RefRegistry, parse_spec

RULE_KINDS = ("line-weight", "tone-density", "motif", "type", "sfx", "title", "other")
RENDER_KEYS = ("lettering", "styles", "sfx")
ART_RULES = ("line-weight", "tone-density", "motif", "other")


def _issue(sev, code, where, msg):
    return {"severity": sev, "code": code, "where": where, "message": msg}


def _deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _story(project):
    from .story import Story
    return Story(project)


# ---------------------------------------------------------------------- direction
class Direction:
    def __init__(self, project: Project, data: dict | None = None):
        self.p = project
        self.file = project.root / "references" / "direction.yaml"
        self.data = data if data is not None else (load_yaml(self.file) if self.file.exists() else {})
        self.revisions = list(self.data.get("revisions", []) or [])
        self.by_id = {r["id"]: r for r in self.revisions}

    def __bool__(self):
        return bool(self.revisions)

    def save(self):
        self.data["revisions"] = self.revisions
        dump_yaml(self.file, self.data)

    def rules(self, rid) -> dict:
        """Effective rule set of a revision (base chain merged, later wins per rule key)."""
        chain, r, seen = [], self.by_id.get(rid), set()
        if r is None:
            raise MangakitError(f"no style revision {rid!r}")
        while r is not None and r["id"] not in seen:
            seen.add(r["id"])
            chain.append(r)
            r = self.by_id.get(r.get("based_on")) if r.get("based_on") else None
        out = {}
        for r in reversed(chain):
            for k, v in (r.get("rules") or {}).items():
                out[k] = _deep_merge(out.get(k, {}), v) if v.get("inherit", True) and k in out else copy.deepcopy(v)
                out[k]["from_revision"] = r["id"]
        return out

    # positions: (chapter, beat index); chapter-level effectivity sits before the chapter's first beat
    def _pos(self, chapter, beat=None, story=None):
        if beat:
            st = story or _story(self.p)
            if beat not in st.beat_ix:
                raise MangakitError(f"unknown beat {beat!r}")
            return (str(st.beat[beat].get("chapter") or chapter or self.p.chapter), st.beat_ix[beat])
        return (str(chapter or self.p.chapter), -1)

    def key(self, rev, story=None):
        e = rev.get("effective") or {}
        if e.get("beat"):
            return self._pos(e.get("chapter"), e["beat"], story)
        return (str(e.get("chapter", "00")), -1)

    def chapter_pin(self, chapter):
        meta = self.p.root / "chapters" / str(chapter or self.p.chapter) / "chapter.yaml"
        return (load_yaml(meta) or {}).get("style") if meta.exists() else None

    def effective(self, chapter=None, beat=None, story=None, ignore_pin=False):
        """The revision that applies at a chapter (and beat). A chapter pin wins."""
        if not self.revisions:
            return None
        ch = str(chapter or self.p.chapter)
        if beat:
            st = story or _story(self.p)
            if beat in st.beat:
                ch = str(st.beat[beat].get("chapter") or ch)
        pin = None if ignore_pin else self.chapter_pin(ch)
        if pin:
            return pin
        pos = self._pos(ch, beat, story) if beat else (ch, -1)
        best = None
        for r in sorted(self.revisions, key=lambda r: self.key(r, story)):
            if self.key(r, story) <= pos:
                best = r["id"]
        return best

    def render_params(self, chapter=None) -> tuple[str | None, dict]:
        rid = self.effective(chapter)
        if not rid:
            return None, {}
        out = {}
        for rule in self.rules(rid).values():
            out = _deep_merge(out, {k: v for k, v in (rule.get("render") or {}).items() if k in RENDER_KEYS})
        return rid, out

    def brief(self, rid, present=None) -> dict:
        """What an art request carries: rule texts (art rules) and the cards to pin. A rule with
        `scope: [canon ids]` is sent only to shots that show one of them (a cuff motif that belongs to
        one character must not reach another character's brief)."""
        rules = self.rules(rid)
        texts, cards, skipped = [], [], []
        for name, r in rules.items():
            if r.get("scope") and present is not None and not set(r["scope"]) & set(present):
                skipped.append(name)
                continue
            if r.get("kind", name) in ART_RULES or r.get("brief"):
                if r.get("text"):
                    texts.append(f"{name}: {r['text']}")
                if r.get("brief"):
                    for c in r.get("cards", []):
                        # a card may be scoped too ({spec, scope}): an exemplar that shows one character's
                        # costume must not reach another character's shot as a picture
                        if isinstance(c, dict):
                            if c.get("scope") and present is not None and not set(c["scope"]) & set(present):
                                skipped.append(f"{name}:{c['spec']}")
                                continue
                            c = c["spec"]
                        cards.append({"rule": name, "spec": c})
        return {"revision": rid, "rules": texts, "cards": cards, "out_of_scope": skipped}

    def revise(self, new_id, base, effective: dict, rules: dict, note="", pin_earlier=True) -> list[str]:
        """Add a revision; pin every earlier chapter that has pages to its current revision, so their
        art keeps the style it was made under. Returns the chapters pinned."""
        if new_id in self.by_id:
            raise MangakitError(f"style revision {new_id} exists; revisions are append-only")
        if base and base not in self.by_id:
            raise MangakitError(f"no base revision {base!r}")
        pinned = []
        rev = {"id": new_id, "effective": effective, "based_on": base, "note": note, "rules": rules}
        start = self.key(rev)
        if pin_earlier:
            for d in sorted((self.p.root / "chapters").iterdir()):
                meta = d / "chapter.yaml"
                if not meta.exists() or d.name >= start[0]:  # only chapters before the new start
                    continue
                m = load_yaml(meta) or {}
                if m.get("style"):
                    continue
                cur = self.effective(d.name)
                if cur:
                    m["style"] = cur
                    dump_yaml(meta, m)
                    pinned.append(f"{d.name}={cur}")
        self.revisions.append(rev)
        self.by_id[new_id] = rev
        self.save()
        return pinned


# ---------------------------------------------------------------------- designs for canon
def design_for(project: Project, canon_id: str, beat=None, view=None, story=None) -> str:
    """Reference spec for a canon id at a beat: the costume (continuity <id>.costume) picks the variant.
    Story owns when the costume changes; the reference owns what it looks like."""
    st = story or _story(project)
    rr = RefRegistry(project)
    ent = st.entities().get(canon_id)
    if ent is None:
        raise MangakitError(f"{canon_id!r} is not in canon")
    costume = st.state_at(beat).get(f"{canon_id}.costume") if beat else None
    if costume is None and beat is None:
        costume = next((x["value"] for x in st.initial if x["subject"] == canon_id and x["attribute"] == "costume"), None)
    spec = None
    if costume:
        for rid in rr.ids():
            rec = rr.load(rid)
            tied = rec.get("canon")
            tied = [tied] if isinstance(tied, str) else (tied or [])
            if rec.get("kind") == "costume" and canon_id in tied and costume in rr.variants(rid):
                spec = f"{rid}:{costume}"
    if spec is None:
        rid = ent.get("design")
        if not rid:
            raise MangakitError(f"canon {canon_id} has no design: reference")
        spec = f"{rid}:{costume}" if costume and costume in rr.variants(rid) else rid
    return spec + (f"#{view}" if view else "")


# ---------------------------------------------------------------------- briefs (design-sheet image calls)
SHEET_LAYOUTS = {
    "turnaround": "a character model sheet: the same character standing full body in front, three-quarter and "
                  "back views side by side, neutral pose, evenly spaced, same scale",
    "details": "a detail sheet: separate close-up studies, each in its own clear space, no overlap",
    "single": "one single view, centred, nothing else in the image",
    "prop": "a prop sheet: the object from the front, from the side and in a hand for scale, evenly spaced",
    "environment": "an environment sheet: one establishing view of the place, empty of people, eye-level camera",
    "card": "a style card: one small finished sample that demonstrates the rule",
}


def brief(project: Project, rid, kind, prompt, layout="single", refs=(), canon=None, variant=None,
          aspect="4:3", adapter="host") -> tuple[str, FsPath]:
    """Write a design-sheet brief + host call (logged). The agent makes the call and collects."""
    rr = RefRegistry(project)
    d = project.root / "references" / rid / "briefs"
    d.mkdir(parents=True, exist_ok=True)
    from .ids import claim_dir
    bd = claim_dir(d, "b", 3)
    bid = bd.name
    (bd / "refs").mkdir(parents=True)
    pinned = []
    for spec in refs:
        r = rr.resolve(spec)
        dst = bd / "refs" / (spec.replace("@", "_").replace("#", "-").replace(":", "~") + FsPath(r["file"]).suffix)
        shutil.copy2(r["file"], dst)
        pinned.append({"spec": spec, "version": r["version"], "sha256": r["sha256"], "file": str(dst),
                       "note": r.get("note", "")})
    lay = SHEET_LAYOUTS.get(layout, layout)
    ref_txt = "; ".join(f"image {i + 1} is {p['spec']}: {p['note']}" for i, p in enumerate(pinned))
    bg = "" if kind in ("environment", "world") else "Plain white background. "
    text = (f"{prompt.strip()} Layout: {lay}. {bg}"
            + (f"References: {ref_txt}. " if pinned else "")
            + "No text, letters, labels, numbers, arrows, signatures or watermarks.")
    rec = {"brief": bid, "ref": rid, "kind": kind, "canon": canon, "variant": variant, "layout": layout,
           "prompt": prompt, "refs": pinned, "adapter": adapter, "calls": [], "status": "open"}
    args = {"description": text, "reference_image_paths": [p["file"] for p in pinned], "aspect_ratio": aspect,
            "filename": f"{rid}-{bid}.png"}
    rec["calls"].append({"n": 1, "status": "pending", "arguments": "host-call-1.json"})
    (bd / "host-call-1.json").write_text(json.dumps({"brief": bid, "ref": rid, "arguments": args}, indent=2))
    dump_yaml(bd / "brief.yaml", rec)
    return bid, bd


def brief_collect(project: Project, rid, bid, file, note="", select=True) -> str:
    rr = RefRegistry(project)
    bd = project.root / "references" / rid / "briefs" / bid
    rec = load_yaml(bd / "brief.yaml")
    ver = rr.add_ref(rid, file, rec["kind"], variant=rec.get("variant") or "", note=note or rec["prompt"][:200],
                     select=select, canon=rec.get("canon"), brief=bid)
    for c in rec["calls"]:
        if c["status"] == "pending":
            c["status"] = "done"
            c["output"] = ver
            break
    rec["status"] = "collected"
    dump_yaml(bd / "brief.yaml", rec)
    return ver


def brief_recall(project: Project, rid, bid) -> int:
    """Log another call on a brief (a retry); returns its number."""
    bd = project.root / "references" / rid / "briefs" / bid
    rec = load_yaml(bd / "brief.yaml")
    n = len(rec["calls"]) + 1
    shutil.copy2(bd / "host-call-1.json", bd / f"host-call-{n}.json")
    rec["calls"].append({"n": n, "status": "pending", "arguments": f"host-call-{n}.json"})
    dump_yaml(bd / "brief.yaml", rec)
    return n


def calls(project: Project) -> dict:
    """Design image calls per reference (from brief logs)."""
    out, total = {}, 0
    d = project.root / "references"
    for f in sorted(d.glob("*/briefs/*/brief.yaml")) if d.exists() else []:
        rec = load_yaml(f)
        n = len(rec.get("calls", []))
        total += n
        row = out.setdefault(rec["ref"], {"calls": 0, "briefs": []})
        row["calls"] += n
        row["briefs"].append({"brief": rec["brief"], "calls": n, "status": rec.get("status"),
                              "outputs": [c.get("output") for c in rec["calls"] if c.get("output")]})
    return {"refs": out, "design_calls_total": total}


# ---------------------------------------------------------------------- checks
def check(project: Project) -> list[dict]:
    I = []
    st = _story(project)
    rr = RefRegistry(project)
    ids = set(rr.ids())
    shown = {x for b in st.beats for x in b.get("shows", []) + b.get("present", [])} | \
            {b.get("location") for b in st.beats if b.get("location")}
    for group, ents in (("character", st.characters), ("prop", st.props), ("environment", st.locations)):
        for cid, ent in ents.items():
            did = ent.get("design")
            if not did:
                sev = "warn" if (group == "character" and cid in shown) else "info"
                I.append(_issue(sev, "design-unassigned", cid, f"{group} {cid} has no design: reference in canon"
                                + ("" if cid in shown else " (not in any beat yet)")))
                continue
            if did not in ids:
                I.append(_issue("error", "design-missing", cid, f"canon design {did!r} has no references/{did}/ref.yaml"))
                continue
            rec = rr.load(did)
            tied = rec.get("canon")
            tied = [tied] if isinstance(tied, str) else (tied or [])
            if tied and cid not in tied:
                I.append(_issue("error", "design-canon-mismatch", cid, f"{did} is tied to canon {tied}"))
            if rec.get("kind") not in DESIGN_KINDS + ("design",):
                I.append(_issue("warn", "design-kind", did, f"kind {rec.get('kind')!r} is not a design kind"))
            if not rec.get("selected"):
                I.append(_issue("error", "design-missing", cid, f"{did} has no selected version"))
    # costumes: every costume value continuity uses must have a look
    for x in list(st.initial) + list(st.events):
        if x.get("attribute") != "costume" or x.get("subject") not in st.characters:
            continue
        ent = st.characters[x["subject"]]
        def _tied(rid):
            t = rr.load(rid).get("canon")
            return x["subject"] in ([t] if isinstance(t, str) else (t or []))
        found = any((_tied(rid) or rid == ent.get("design"))
                    and x["value"] in rr.variants(rid) for rid in ids)
        if not found and ent.get("design") in ids:
            I.append(_issue("error", "costume-variant-missing", x.get("id", f"{x['subject']}.costume"),
                            f"{x['subject']} wears {x['value']!r} but no design reference has that variant"))
    # views
    for rid in ids:
        rec = rr.load(rid)
        for ver, views in (rec.get("views") or {}).items():
            if ver not in rec["versions"]:
                I.append(_issue("error", "view-orphan", rid, f"views for missing version {ver}"))
    # direction
    D = Direction(project)
    for r in D.revisions:
        if r.get("based_on") and r["based_on"] not in D.by_id:
            I.append(_issue("error", "style-base-missing", r["id"], f"based_on {r['based_on']!r} does not exist"))
        e = r.get("effective") or {}
        if e.get("beat") and e["beat"] not in st.beat:
            I.append(_issue("error", "unknown-beat", r["id"], f"effective beat {e['beat']!r}"))
        if not e:
            I.append(_issue("error", "style-no-start", r["id"], "revision has no effective chapter or beat"))
    for r in D.revisions:
        try:
            rules = D.rules(r["id"])
        except MangakitError as ex:
            I.append(_issue("error", "style-base-missing", r["id"], str(ex)))
            continue
        for name, rule in rules.items():
            if rule.get("kind", name) not in RULE_KINDS:
                I.append(_issue("warn", "style-rule-kind", f"{r['id']}/{name}", f"kind {rule.get('kind')!r}"))
            if not rule.get("cards"):
                I.append(_issue("warn", "style-card-missing", f"{r['id']}/{name}", "rule has no style card (exemplar image)"))
            for c in rule.get("cards", []):
                c = c["spec"] if isinstance(c, dict) else c
                try:
                    rr.resolve(c)
                except MangakitError as ex:
                    I.append(_issue("error", "style-card-missing", f"{r['id']}/{name}", str(ex)))
            for k in (rule.get("render") or {}):
                if k not in RENDER_KEYS:
                    I.append(_issue("warn", "style-render-key", f"{r['id']}/{name}", f"render key {k!r} ignored"))
    chapters = project.root / "chapters"
    for d in sorted(chapters.iterdir()) if chapters.exists() else []:
        pin = D.chapter_pin(d.name)
        if pin and pin not in D.by_id:
            I.append(_issue("error", "style-pin-missing", f"chapter {d.name}", f"pinned to unknown revision {pin!r}"))
    if D:
        I += _check_jobs(project, D, st, rr)
    return I


def _check_jobs(project, D, st, rr):
    from .assets import Registry
    I = []
    reg = Registry(project)
    jdir = project.root / "art" / "jobs"
    reqs = {}
    for f in sorted(jdir.glob("job-*/request.yaml")) if jdir.exists() else []:
        req = load_yaml(f)
        job = load_yaml(f.parent / "job.yaml")
        reqs[req["job"]] = (req, job)
        beat = req["target"].get("beat")
        ch = req["target"].get("chapter")
        live = job.get("status") not in ("accepted", "rejected", "reviewed", "withdrawn")
        sr = (req.get("style_revision") or {}).get("revision")
        want = D.effective(ch, beat, story=st) if beat in st.beat else D.effective(ch)
        if live and sr and want and sr != want:
            I.append(_issue("warn", "job-style-superseded", req["job"],
                            f"request pins style {sr}; {req['target']['page']}/{req['target']['panel']} now needs {want}: "
                            f"re-request before calling"))
        if live:
            for r in req.get("references", []):
                try:
                    cur = rr.resolve(r.get("spec") or f"{r['id']}@{r['version']}")
                except MangakitError:
                    continue
                if r.get("kind") == "style" and cur.get("latest") != r["version"] and not r.get("spec", "").count("@"):
                    I.append(_issue("warn", "job-style-superseded", req["job"],
                                    f"style card {r['id']}@{r['version']} has a newer version {cur['latest']}"))
    # selected art made under an older revision than its beat requires (flag only)
    order = {r["id"]: i for i, r in enumerate(sorted(D.revisions, key=lambda r: D.key(r, st)))}
    for aid in reg.ids():
        rec = reg.load(aid)
        ver = rec.get("selected")
        if not ver:
            continue
        jid = rec["versions"][ver].get("job")
        if not jid or jid not in reqs:
            continue
        req, _ = reqs[jid]
        beat = req["target"].get("beat")
        ch = req["target"].get("chapter")
        want = D.effective(ch, beat, story=st, ignore_pin=False) if beat in st.beat else D.effective(ch)
        got = (req.get("style_revision") or {}).get("revision")
        where = f"{aid}@{ver}"
        judged = rec["versions"][ver].get("style_judged") or {}    # director looked: drawing meets revision(s)
        if want and want in judged.get("revisions", []):
            continue
        if not got:
            I.append(_issue("info", "art-style-unrecorded", where,
                            f"made by {jid} before the direction guide; treat as {want} only after a look"))
        elif want and order.get(got, -1) < order.get(want, -1):
            I.append(_issue("warn", "art-style-older", where,
                            f"made under {got}; its beat {beat} now requires {want} (flag only: decide restyle or pin)"))
    return I


# ---------------------------------------------------------------------- sample shot
SAMPLE_PAGE = '''"""Sample-shot test page (generated by `mangakit design sample`)."""
from mangakit import Path

IMAGE = {image!r}
LINE = {line!r}
SFX = {sfx!r}
SFX_AT = {sfx_at!r}
LINE_AT = {line_at!r}
BOX = {box!r}


def build(page, art, script):
    x, y, w, h = BOX
    pnl = page.panel("sample", Path.rect(x, y, w, h), beat=None)
    if IMAGE:
        from PIL import Image
        with Image.open(IMAGE) as im:
            iw, ih = im.size
        s = max(w / iw, h / ih)
        from mangakit.geometry import Affine
        t = Affine.translate(x + (w - iw * s) / 2, y + (h - ih * s) / 2) @ Affine.scale(s)
        page.overlay(IMAGE, transform=t, clip=pnl.path)
    page.stroke(pnl.path, style="panel-border")
    if LINE:
        page.balloon("sample-line", at=(x + w * LINE_AT[0], y + h * LINE_AT[1]), panel="sample")
    if SFX:
        page.text(SFX, at=(x + w * SFX_AT[0], y + h * SFX_AT[1]), rotate=-6, panel="sample")
    return page
'''


def sample(project: Project, image=None, revision=None, chapter=None, line="", sfx="", box=None, out=None,
           label=None, sfx_at=(0.3, 0.85), line_at=(0.78, 0.2)) -> dict:
    """Render a test panel under a style revision at actual reading size (the project's reading view)."""
    from .render import load_page, render_page
    D = Direction(project)
    rid = revision or D.effective(chapter)
    params = {}
    if rid:
        for rule in D.rules(rid).values():
            params = _deep_merge(params, {k: v for k, v in (rule.get("render") or {}).items() if k in RENDER_KEYS})
    img = None
    if image:
        from .assets import Registry
        rr, ar = RefRegistry(project), Registry(project)
        if os.path.exists(image):
            img = str(FsPath(image).resolve())
        elif rr.exists(parse_spec(image)["id"]):
            img = rr.resolve(image)["file"]
        else:  # an art asset: id[@vNNN]
            aid, _, ver = image.partition("@")
            img = str(ar.file(aid, ar.version(aid, ver or None)[0]))
    box = box or [55, 60, project.trim_w - 110, project.trim_h * 0.55]
    d = project.build_dir("design", f"sample-{label or rid or 'none'}")
    src = d / "sample.py"
    src.write_text(SAMPLE_PAGE.format(image=img, line=line, sfx=sfx, box=[round(v, 1) for v in box],
                                      sfx_at=list(sfx_at), line_at=list(line_at)))
    script = {"lines": [{"id": "sample-line", "beat": "sample", "kind": "speech", "text": line or "..."}]}
    page, _ = load_page(project, "sample", page_file=src, script_data=script, style_render=params, style_revision=rid)
    png = render_page(page, "reading", out or d / "reading.png")
    full = render_page(page, "proof", d / "proof.png", manifest=False)
    # what to judge, one question per rule, at this size (fill in by eye; see design-reference.md)
    if rid:
        rows = [f"# Sample-shot test: {rid}", "", f"- reading-size render: {png} "
                f"(page height {project.cfg.get('render', {}).get('reading_height_px', 1100)} px, view unscaled)",
                f"- image: {img}", "", "| rule | what it says | holds at reading size? |", "|---|---|---|"]
        rows += [f"| {n} | {r.get('text', '')} | |" for n, r in D.rules(rid).items()]
        (d / "judge.md").write_text("\n".join(rows) + "\n")
    return {"revision": rid, "render": params, "reading": str(png), "proof": str(full), "image": img,
            "reading_height_px": project.cfg.get("render", {}).get("reading_height_px", 1100)}


def compare(results: list[dict], out) -> FsPath:
    """Side-by-side of sample renders (each at reading size, unscaled)."""
    from PIL import Image, ImageDraw
    ims = [Image.open(r["reading"]).convert("RGB") for r in results]
    w = sum(i.width for i in ims) + 20 * (len(ims) + 1)
    h = max(i.height for i in ims) + 70
    c = Image.new("RGB", (w, h), "#8a8a8a")
    dr = ImageDraw.Draw(c)
    x = 20
    for r, im in zip(results, ims):
        c.paste(im, (x, 20))
        dr.text((x, im.height + 32), f"{r['revision']}  (reading size {im.width}x{im.height}px, unscaled)", fill="white")
        x += im.width + 20
    FsPath(out).parent.mkdir(parents=True, exist_ok=True)
    c.save(out)
    return FsPath(out)


# ---------------------------------------------------------------------- guide (markdown)
def guide_md(project: Project, out=None) -> FsPath:
    D = Direction(project)
    rr = RefRegistry(project)
    st = _story(project)
    L = [f"# {D.data.get('guide', 'Art direction')}", ""]
    for r in sorted(D.revisions, key=lambda r: D.key(r, st)):
        e = r.get("effective") or {}
        L.append(f"## {r['id']}  (from {'beat ' + e['beat'] if e.get('beat') else 'chapter ' + str(e.get('chapter'))}"
                 f"{', based on ' + r['based_on'] if r.get('based_on') else ''})")
        if r.get("note"):
            L.append(r["note"])
        L.append("")
        for name, rule in D.rules(r["id"]).items():
            own = "" if rule.get("from_revision") == r["id"] else f" *(inherited from {rule['from_revision']})*"
            L.append(f"### {name}{own}")
            L.append(rule.get("text", ""))
            for c in rule.get("cards", []):
                c = c["spec"] + f" (scope {', '.join(c.get('scope', []))})" if isinstance(c, dict) and c.get("scope") else \
                    (c["spec"] if isinstance(c, dict) else c)
                try:
                    f = rr.resolve(c.split(" (scope")[0])["file"]
                    L.append(f"- card `{c}`: ![{c}]({os.path.relpath(f, (FsPath(out).parent if out else project.root / 'build' / 'design'))})")
                except MangakitError as ex:
                    L.append(f"- card `{c}`: MISSING ({ex})")
            if rule.get("render"):
                L.append(f"- render: `{json.dumps(rule['render'])}`")
            L.append(f"- in art briefs: {'cards + text' if rule.get('brief') else ('text' if rule.get('kind', name) in ART_RULES else 'no (compose/render)')}")
            L.append("")
    pins = {d.name: D.chapter_pin(d.name) for d in sorted((project.root / "chapters").iterdir()) if (d / "chapter.yaml").exists()}
    L += ["## Chapters", ""] + [f"- chapter {c}: {p or D.effective(c)}{' (pinned)' if p else ''}" for c, p in pins.items()]
    o = FsPath(out) if out else project.root / "build" / "design" / "direction.md"
    o.parent.mkdir(parents=True, exist_ok=True)
    o.write_text("\n".join(L) + "\n")
    return o
