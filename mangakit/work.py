"""manga-direct: file-backed work units, derived from the project's state.

A unit of work carries an id, the skill that owns it, its target, the input revisions it was planned
(or completed) against, the requested output, its status and what it produced. `plan` derives what
the project needs now (story changes since the baseline, design/board/asset checks, review findings,
stale or missing renders) and reconciles it with the units on disk:

    queued        -> needs doing                       running -> started (pid recorded)
    done          -> outputs recorded against inputs   stale   -> done, but an input changed since
    blocked       -> failed, or waiting on a unit      needs-creator -> waiting on a creator gate/decision
    cancelled     -> no longer derived (resolved elsewhere)

Units are saved one file each as they change, so an interrupted run loses at most the unit in flight;
`resume` finds running units whose process is gone, checks their outputs, and re-plans."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path as FsPath

import yaml

from .ids import claim_file, locked
from .project import MangakitError, Project, load_yaml

STATUSES = ("queued", "running", "done", "stale", "blocked", "needs-creator", "cancelled")
LIVE = ("queued", "running", "done", "stale", "blocked", "needs-creator")
SKILLS = ("direct", "story", "design", "board", "illustrate", "compose", "review")
ORDER = {s: i for i, s in enumerate(SKILLS + ("publish",))}
KIND_LAST = {"render": 1, "recheck": 1}     # within a skill: edits and checks before renders
GATES = ("series_look", "lettered_boards", "final_version")
RENDER_VIEWS = ("proof", "reading")
RENDER_CFG_KEYS = ("page", "fonts", "lettering", "styles", "sfx", "board", "render", "reading_direction", "color")


def _now():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _ch(project, chapter):
    return str(chapter or project.chapter)


def wdir(project) -> FsPath:
    d = project.root / "work"
    (d / "units").mkdir(parents=True, exist_ok=True)
    return d


def _lock(project):
    return locked(wdir(project) / ".lock")


# ============================================================================ units on disk
def load_units(project) -> list[dict]:
    d = wdir(project) / "units"
    out = []
    for f in sorted(d.glob("w-*.yaml")):
        u = load_yaml(f)
        if u:
            out.append(u)
    return out


def save_unit(project, u):
    f = wdir(project) / "units" / f"{u['id']}.yaml"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(u, sort_keys=False, allow_unicode=True, width=110))
    os.replace(tmp, f)        # atomic: a kill never leaves half a unit


def get_unit(project, uid) -> dict:
    f = wdir(project) / "units" / f"{uid}.yaml"
    if not f.exists():
        raise MangakitError(f"no work unit {uid}")
    return load_yaml(f)


def new_unit(project, need) -> dict:
    f = claim_file(wdir(project) / "units", "w-", ".yaml", 4)
    u = {"id": f.stem, "key": need["key"], "skill": need["skill"], "kind": need["kind"], "title": need["title"],
         "target": need.get("target", {}), "inputs": need.get("inputs", {}), "requested": need.get("requested", ""),
         "status": need.get("status", "queued"), "after": need.get("after", []), "exec": need.get("exec"),
         "outputs": [], "sources": need.get("sources", []), "gate": need.get("gate"), "image_calls": need.get("image_calls", 0),
         "origin": need.get("origin", "state"),
         "created": _now(), "history": [{"at": _now(), "status": need.get("status", "queued"), "note": need.get("reason", "")}]}
    save_unit(project, u)
    return u


def _set(project, u, status, note="", **kw):
    u["status"] = status
    u.update(kw)
    u.setdefault("history", []).append({"at": _now(), "status": status, **({"note": note} if note else {})})
    save_unit(project, u)
    return u


# ============================================================================ input revisions
def _sha(p: FsPath) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.exists() else None


def page_inputs(project, pid, chapter=None) -> dict:
    """The revisions a page render depends on, from the live project (same shape as manifest_inputs)."""
    from .render import load_page
    ch = _ch(project, chapter)
    page, src = load_page(project, pid, chapter=ch)
    assets = {aid: d.version for aid, d in sorted(page.art.used.items())}
    masks = {key: m.version for key, m in sorted(page.art.used_masks.items())}
    lines = dict(sorted(page.script.used.items()))
    si = getattr(page, "style_info", {}) or {}
    cfg = {k: project.cfg.get(k) for k in RENDER_CFG_KEYS}
    return {"source": _sha(FsPath(src)), "lines": _h(lines), "assets": assets, "masks": masks,
            "style": si.get("revision"), "style_render": _h(si.get("render") or {}), "config": _h(cfg)}


def manifest_inputs(project, man: dict) -> dict:
    """The same signature, recorded in a render manifest."""
    cfg = load_yaml(project.root / man["project_yaml"]["snapshot"]) or {}
    lines = dict((man.get("script") or {}).get("lines_used") or {})
    st = man.get("style") or {}
    return {"source": man["page_source"]["sha256"][:12], "lines": _h(lines),
            "assets": {a["id"]: a["version"] for a in man["assets"]}, "masks": {m["key"]: m["version"] for m in man["masks"]},
            "style": st.get("revision"), "style_render": _h(st.get("render") or {}), "config": _h({k: cfg.get(k) for k in RENDER_CFG_KEYS})}


def render_state(project, pid, view, chapter=None, cur=None) -> tuple[str, dict, list[str]]:
    """('fresh' | 'stale' | 'missing', current inputs, changed keys) for build/ch<ch>/<pid>/<view>.png."""
    ch = _ch(project, chapter)
    cur = cur or page_inputs(project, pid, ch)
    mf = project.root / "build" / f"ch{ch}" / pid / f"{view}.manifest.json"
    png = mf.with_name(f"{view}.png")
    if not mf.exists() or not png.exists():
        return "missing", cur, []
    man = json.loads(mf.read_text())
    old = manifest_inputs(project, man)
    if (man.get("outputs") or [{}])[0].get("sha256") != hashlib.sha256(png.read_bytes()).hexdigest():
        return "stale", cur, ["output-bytes"]
    changed = [k for k in cur if cur[k] != old.get(k)]
    return ("stale" if changed else "fresh"), cur, changed


# ============================================================================ story baseline (what changed)
def _story_snapshot(project) -> dict:
    from .story import Story
    st = Story(project)
    return {"lines": {l["id"]: {k: l.get(k) for k in ("text", "speaker", "kind", "beat")} for l in st.lines},
            "beats": {b["id"]: b for b in st.beats},
            "facts": st.facts,
            "continuity": {e.get("id") or f"{e['subject']}.{e['attribute']}@{e['beat']}": e for e in st.events},
            "initial": {f"{x['subject']}.{x['attribute']}": x["value"] for x in st.initial}}


def baseline_path(project, chapter):
    return wdir(project) / f"baseline-ch{chapter}.yaml"


def story_changes(project, chapter) -> dict:
    """Story records that differ from the baseline the last plan recorded."""
    cur = _story_snapshot(project)
    bf = baseline_path(project, chapter)
    if not bf.exists():
        return {"lines": [], "beats": [], "facts": [], "continuity": [], "initial": [], "first": True, "_cur": cur}
    old = load_yaml(bf) or {}
    out = {"_cur": cur, "first": False}
    for k in ("lines", "beats", "facts", "continuity", "initial"):
        a, b = old.get(k) or {}, cur[k]
        out[k] = sorted([x for x in set(a) | set(b) if a.get(x) != b.get(x)])
    return out


# ============================================================================ deriving needs
def _need(key, skill, kind, title, target=None, inputs=None, requested="", exec_=None, reason="", after=(),
          sources=(), gate=None, image_calls=0, status=None, problem=True):
    n = {"key": key, "skill": skill, "kind": kind, "title": title, "target": target or {}, "inputs": inputs or {},
         "requested": requested, "exec": exec_, "reason": reason, "after": list(after), "sources": list(sources),
         "gate": gate, "image_calls": image_calls, "problem": problem}
    if status:
        n["status"] = status
    return n


def gates(project) -> dict:
    g = ((project.cfg.get("creator") or {}).get("gates") or {})
    return {k: bool(g.get(k, False)) for k in GATES}


def approvals(project) -> list[dict]:
    f = wdir(project) / "gates.yaml"
    return list((load_yaml(f) or {}).get("approvals") or []) if f.exists() else []


def approved(project, gate, subject) -> bool:
    return any(a["gate"] == gate and str(a["subject"]) == str(subject) for a in approvals(project))


def approve(project, gate, subject, by, note) -> dict:
    """Record a creator approval. The director never calls this on its own: `by` names the creator and
    `note` quotes what they said."""
    if gate not in GATES and gate != "editorial":
        raise MangakitError(f"gate must be one of {GATES + ('editorial',)}")
    if not by or by in ("direct", "agent", "director"):
        raise MangakitError("an approval names the creator who gave it (--by)")
    if not note:
        raise MangakitError("an approval quotes the creator's decision (--note)")
    with _lock(project):
        A = approvals(project)
        a = {"gate": gate, "subject": subject, "by": by, "note": note, "at": _now()}
        A.append(a)
        (wdir(project) / "gates.yaml").write_text(yaml.safe_dump({"approvals": A}, sort_keys=False, allow_unicode=True))
    return a


def _where(w) -> dict:
    parts = str(w).split()[0].split("/")
    if parts and parts[0][:1] == "p" and parts[0][1:].isdigit():
        return {"page": parts[0], **({"panel": parts[1]} if len(parts) > 1 and parts[1] else {})}
    return {}


def derive(project, chapter=None, changes=None) -> list[dict]:
    """Everything the chapter needs now, as unit specs (not yet reconciled with units on disk)."""
    from . import board as B
    from . import design as D
    from . import review as RV
    from .assets import Registry
    from .story import Story, impact
    ch = _ch(project, chapter)
    st = Story(project)
    pages = project.chapter_pages(ch)
    G = gates(project)
    needs = []
    changes = changes if changes is not None else story_changes(project, ch)

    # --- story changes since the baseline -------------------------------------------------------
    for lid in changes.get("lines", []):
        imp = impact(project, lid, chapter=ch) if lid in st.line else None
        rec = (changes["_cur"]["lines"].get(lid) or {})
        if not imp:
            continue
        for a in imp["compose"]:
            if "rerun" in a:
                pg = a["rerun"].split(" on ")[1].split("/")[0] if " on " in a["rerun"] else None
                needs.append(_need(f"reletter:{lid}:{pg}", "compose", "reletter", f"reflow {lid} on {pg}",
                                   {"chapter": ch, "page": pg, "line": lid}, {"text": _h(rec.get("text"))},
                                   "balloon fits the new text (no text-overflow), page re-rendered",
                                   ["check", pg, "--chapter", ch], reason=f"script line {lid} changed"))
        for a in imp["illustrate"]:
            needs.append(_need(f"inspect-art:{lid}", "illustrate", "inspect", f"art vs new text of {lid}",
                               {"chapter": ch, "line": lid}, {"text": _h(rec.get("text"))},
                               a["inspect"], reason=f"script line {lid} changed; reopen the drawing only if the acting conflicts"))
    for key in changes.get("continuity", []) + changes.get("initial", []):
        e = changes["_cur"]["continuity"].get(key)
        fact = f"{e['subject']}.{e['attribute']}" if e else key.split("@")[0]
        tgt = e["id"] if e and e.get("id") else fact     # an event: only the beats it is in effect over
        try:
            imp = impact(project, tgt, chapter=ch)
        except MangakitError:
            continue
        sig = {"fact": _h(changes["_cur"]["continuity"].get(key) or changes["_cur"]["initial"].get(key))}
        for a in imp["board"]:
            pk = a["inspect"].split()[1]
            needs.append(_need(f"inspect-board:{fact}:{pk}", "board", "inspect", f"panel {pk} vs changed {fact}",
                               {"chapter": ch, "page": pk.split("/")[0], "panel": pk.split("/")[1], "fact": fact}, sig,
                               a["inspect"], reason=f"story fact {fact} changed ({key})"))
        for i, a in enumerate(imp["illustrate"]):
            needs.append(_need(f"inspect-art:{fact}:{i}", "illustrate", "inspect", f"art vs changed {fact}",
                               {"chapter": ch, "fact": fact}, sig, a["inspect"],
                               reason=f"story fact {fact} changed; schedule art only if the drawing depicts the old value"))
    for bid in changes.get("beats", []):
        if bid in st.beat and str(st.beat[bid].get("chapter")) == ch:
            needs.append(_need(f"inspect-beat:{bid}", "board", "inspect", f"panels of beat {bid}", {"chapter": ch, "beat": bid},
                               {"beat": _h(st.beat[bid])}, "the panels still draw the beat", reason=f"beat {bid} changed"))
    if any(changes.get(k) for k in ("lines", "beats", "facts", "continuity", "initial")):
        needs.append(_need("story-check", "story", "check", "story check after the edit", {"chapter": ch},
                           {"story": _h({k: v for k, v in changes["_cur"].items()})}, "0 errors",
                           ["story", "check", "--chapter", ch], reason="story records changed"))

    for n in needs:
        n["origin"] = "story-change"     # event-derived: stays until done, even after the baseline moves on

    # --- design ---------------------------------------------------------------------------------
    for x in D.check(project):
        if x["severity"] == "info" and x["code"] not in ("art-style-unrecorded",):
            continue
        c, w = x["code"], x["where"]
        if c in ("design-missing", "costume-variant-missing", "design-canon-mismatch", "view-orphan"):
            needs.append(_need(f"design:{c}:{w}", "design", "design-sheet", f"{c} {w}", {"where": w},
                               {"issue": _h(x)}, x["message"], reason=c, image_calls=1,
                               gate="series_look" if G["series_look"] else None))
        elif c == "job-style-superseded":
            needs.append(_need(f"rerequest:{w}", "illustrate", "re-request", f"re-request {w} under the current style",
                               {"job": w.split()[0]}, {"issue": _h(x)}, x["message"], reason=c))
        elif c == "art-style-older":
            needs.append(_need(f"decide:{c}:{w}", "direct", "decision", f"redraw or keep {w}", {"where": w},
                               {"issue": _h(x)}, "a recorded decision (work decide)", reason=x["message"]))
        elif x["severity"] in ("error", "warn"):
            needs.append(_need(f"design:{c}:{w}", "design", "fix", f"{c} {w}", {"where": w}, {"issue": _h(x)}, x["message"], reason=c))

    # --- board and assets ------------------------------------------------------------------------
    R = B.check_chapter(project, ch, with_technical=True)
    for x in R["issues"]:
        if x["code"] == "needs-art":
            pid, pn = x["where"].split("/")
            beat = R["facts"][pid]["panels"][pn]["beat"]
            gate = None
            if G["lettered_boards"] and not approved(project, "lettered_boards", ch):
                gate = "lettered_boards"
            needs.append(_need(f"art:{pid}/{pn}", "illustrate", "art", f"final art for {pid}/{pn}",
                               {"chapter": ch, "page": pid, "panel": pn, "beat": beat},
                               {"page": page_inputs(project, pid, ch)["source"]}, "an accepted drawing selected in the slot, "
                               "placed and checked by compose", reason=x["message"], image_calls=1, gate=gate))
        elif x["severity"] in ("error", "warn"):
            needs.append(_need(f"board:{x['code']}:{x['where']}", "board", "fix", f"{x['code']} {x['where']}",
                               {"chapter": ch, "where": x["where"], **_where(x["where"])}, {"issue": _h(x)}, x["message"], reason=x["code"]))
    reg = Registry(project)
    for aid in reg.ids():
        for x in reg.validate(aid):
            if x["code"] in ("stale-mask", "missing-mask", "mask-dims"):
                needs.append(_need(f"mask:{x['where']}", "compose", "mask", f"{x['code']} {x['where']}", {"where": x["where"]},
                                   {"issue": _h(x)}, x["message"], reason=x["code"]))

    # --- review findings ------------------------------------------------------------------------
    for f in RV.load_findings(project):
        if str(f.get("chapter")) != ch:
            continue
        if f["status"] == "editorial":
            needs.append(_need(f"editorial:{f['id']}", "direct", "decision", f"editorial choice {f['id']}: {f.get('title') or f['code']}",
                               {"chapter": ch, "finding": f["id"], "page": f.get("page")}, {"finding": _h(f.get("alternatives"))},
                               "the creator (or editor) picks an alternative; `review decide` records it",
                               reason="alternatives preserved for editorial selection", status="needs-creator",
                               sources=[f["id"]], gate="editorial"))
            continue
        if f["status"] not in ("open", "fixed"):
            continue
        if f["code"] == "needs-art":          # the board's needs-art unit carries it
            continue
        skill = f["owner"] if f["owner"] in SKILLS else "direct"
        needs.append(_need(f"finding:{f['id']}", skill, "finding", f"{f['id']} {f.get('title') or f['code']}",
                           {"chapter": ch, "finding": f["id"], "page": f.get("page"), "panel": f.get("panel")},
                           {"finding": _h([f.get("observed"), f.get("intended")])},
                           f["intended"] or "resolve the finding, then `review set <id> --status fixed`",
                           reason=f["observed"], sources=[f["id"]],
                           problem=f["status"] == "open"))     # fixed = waiting for recheck, not a new problem
    # attach needs-art findings to their art units
    for n in needs:
        if n["kind"] == "art":
            k = f"tech:needs-art:{n['target']['page']}/{n['target']['panel']}"
            n["sources"] += [f["id"] for f in RV.load_findings(project) if f["key"] == k]

    # --- renders (products: stale when an input changed) ------------------------------------------
    rkeys = []
    for pid in pages:
        cur = page_inputs(project, pid, ch)
        for view in RENDER_VIEWS:
            state, cur, changed = render_state(project, pid, view, ch, cur)
            key = f"render:{ch}:{pid}:{view}"
            needs.append(_need(key, "compose", "render", f"render {pid} {view}", {"chapter": ch, "page": pid, "view": view},
                               cur, f"build/ch{ch}/{pid}/{view}.png + manifest", ["render", pid, "--view", view, "--chapter", ch, "-q"],
                               reason=f"{state}: {', '.join(changed)}" if changed else state, problem=False,
                               status=None if state != "fresh" else "fresh"))
            if state != "fresh":
                rkeys.append(key)
    allin = {k: n["inputs"] for n in needs if n["kind"] == "render" for k in [n["key"]]}
    rc = _need(f"recheck:{ch}", "review", "recheck", f"review recheck chapter {ch}", {"chapter": ch},
               {"renders": _h(allin)}, "recheck table (verified / survived / needs-verdict)",
               ["review", "recheck", "--chapter", ch], reason="pages re-rendered", after=rkeys, problem=False)
    rc["new_only_if"] = bool(rkeys)        # first plan with everything fresh: no recheck needed
    needs.append(rc)
    return needs


# ============================================================================ plan / reconcile
def plan(project, chapter=None, write=True) -> dict:
    """Reconcile derived needs with the units on disk. Returns {created, stale, reopened, cancelled, units}."""
    ch = _ch(project, chapter)
    with _lock(project):
        changes = story_changes(project, ch)
        needs = derive(project, ch, changes)
        units = load_units(project)
        live = {}
        for u in units:
            if u["status"] in LIVE and u.get("target", {}).get("chapter", ch) in (ch, None):
                live.setdefault(u["key"], u)
        res = {"created": [], "stale": [], "reopened": [], "cancelled": [], "fresh": [], "changes": {k: v for k, v in changes.items() if not k.startswith("_")}}
        keys = set()
        key2id = {}
        for n in needs:
            keys.add(n["key"])
            u = live.get(n["key"])
            fresh = n.get("status") == "fresh"
            if u is None:
                if fresh or n.get("new_only_if") is False:
                    res["fresh"].append(n["key"])
                    continue
                if not write:
                    res["created"].append(n["key"])
                    continue
                st = n.get("status") or ("needs-creator" if n.get("gate") and n["gate"] != "editorial" else "queued")
                u = new_unit(project, dict(n, status=st))
                res["created"].append(u["id"])
            elif u["status"] == "done":
                if fresh:
                    continue
                if u.get("inputs") != n["inputs"]:
                    if write:
                        changed = sorted(k for k in set(u.get("inputs", {})) | set(n["inputs"]) if u.get("inputs", {}).get(k) != n["inputs"].get(k))
                        _set(project, u, "stale", f"inputs changed: {', '.join(changed)}", planned_inputs=n["inputs"])
                    res["stale"].append(u["id"])
                elif n["problem"]:
                    if write:
                        _set(project, u, "queued", "still derived after it was done (the problem persists)")
                    res["reopened"].append(u["id"])
            elif u["status"] in ("queued", "blocked", "stale", "needs-creator"):
                if fresh and u["kind"] == "render":
                    if write:
                        _set(project, u, "done", "already fresh (rendered elsewhere)", inputs=n["inputs"])
                    continue
                if write and u["status"] == "queued" and u.get("inputs") != n["inputs"]:
                    u["inputs"] = n["inputs"]
                    save_unit(project, u)
                if write and n.get("gate") and n["gate"] != "editorial" and u["status"] == "queued" and not _gate_open(project, n):
                    _set(project, u, "needs-creator", f"gate {n['gate']}", gate=n["gate"])
                elif write and u["status"] == "needs-creator" and (u.get("gate") or n.get("gate")) != "editorial" \
                        and (not n.get("gate") or _gate_open(project, n)):
                    g = u.get("gate") or n.get("gate") or "creator"
                    _set(project, u, "queued", f"gate {g} approved or turned off")
            key2id[n["key"]] = u["id"] if u else None
        # map 'after' keys to ids
        if write:
            for u in load_units(project):
                if u["status"] in ("queued", "stale", "needs-creator", "blocked") and any(not str(a).startswith("w-") for a in u.get("after", [])):
                    u["after"] = [key2id.get(a) or a for a in u["after"] if key2id.get(a) or str(a).startswith("w-")]
                    save_unit(project, u)
            for k, u in live.items():
                if k not in keys and u["status"] in ("queued", "blocked", "stale") and u.get("origin") != "story-change":
                    _set(project, u, "cancelled", "no longer derived (resolved elsewhere)")
                    res["cancelled"].append(u["id"])
            baseline_path(project, ch).write_text(yaml.safe_dump(changes["_cur"], sort_keys=True, allow_unicode=True))
        res["units"] = load_units(project)
        return res


def _gate_open(project, n) -> bool:
    g = n.get("gate")
    if not g:
        return True
    subj = n["target"].get("chapter")
    return approved(project, g, subj)


# ============================================================================ status / next / context
def runnable(project, units=None) -> list[dict]:
    units = units if units is not None else load_units(project)
    done = {u["id"] for u in units if u["status"] == "done"}
    pages = {}
    out = []
    for u in units:
        if u["status"] not in ("queued", "stale"):
            continue
        if any(a not in done for a in u.get("after", [])):
            continue
        out.append(u)

    def rank(u):
        ch = u["target"].get("chapter") or "00"
        pg = u["target"].get("page") or ""
        if ch not in pages:
            try:
                pages[ch] = project.chapter_pages(ch)
            except Exception:
                pages[ch] = []
        pix = pages[ch].index(pg) if pg in pages[ch] else 999
        return (ORDER.get(u["skill"], 99), KIND_LAST.get(u["kind"], 0), pix, u["id"])
    return sorted(out, key=rank)


def status(project) -> dict:
    U = load_units(project)
    c = {}
    for u in U:
        c[u["status"]] = c.get(u["status"], 0) + 1
    return {"counts": c, "units": U}


def context(project, u) -> dict:
    """Context for one unit: only what its target needs. For a panel: the beat, its lines, who is
    present and the design variant each wears there, props and holders, the style revision and the
    rules that reach this shot, the board's note and focal points, open findings, and every fact the
    reader must not learn yet (CONCEALED: keep out of the drawing and the words)."""
    from . import board as B
    from . import review as RV
    from .design import Direction, design_for
    from .story import Story
    st = Story(project)
    t = u.get("target") or {}
    ch = t.get("chapter") or project.chapter
    ctx = {"unit": u["id"], "skill": u["skill"], "kind": u["kind"], "title": u["title"], "requested": u.get("requested"),
           "target": t, "inputs": u.get("inputs")}
    pid, pn = t.get("page"), t.get("panel")
    beat = t.get("beat")
    if pid and pn and not beat:
        try:
            F = B.check_chapter(project, ch, with_technical=False)["facts"].get(pid) or {}
            beat = (F.get("panels") or {}).get(pn, {}).get("beat")
        except Exception:
            beat = None
    if beat and beat in st.beat:
        b = st.beat[beat]
        K = st.knowledge()
        known = K[beat]
        future = [f for f in st.facts if f not in known["known"] and f not in known["concealed"]
                  and f not in known["suspected"]]
        before, after = st.state_at(beat, after=False), st.state_at(beat, after=True)
        ctx["story"] = {"beat": beat, "summary": b.get("summary"), "location": b.get("location"),
                        "lines": [{"id": l["id"], "kind": l.get("kind"), "speaker": l.get("speaker"), "text": l["text"]}
                                  for l in st.lines if l.get("beat") == beat],
                        "continuity_before": {k: v for k, v in before.items() if k.split(".")[0] in set(b.get("present", [])) | set(b.get("shows", []))},
                        "continuity_after": {k: v for k, v in after.items() if k.split(".")[0] in set(b.get("present", [])) | set(b.get("shows", []))},
                        "reader_knows": known["known"], "reader_suspects": known["suspected"],
                        "CONCEALED": [{"fact": f, "statement": st.facts.get(f, {}).get("statement"),
                                       "revealed_at": st.first_known(f)} for f in known["concealed"] + future]}
        D = Direction(project)
        rid = D.effective(ch, beat)
        ctx["design"] = []
        for c in b.get("present", []) + b.get("shows", []):
            try:
                ctx["design"].append({"canon": c, "spec": design_for(project, c, beat=beat)})
            except MangakitError as e:
                ctx["design"].append({"canon": c, "missing": str(e)})
        if rid:
            br = D.brief(rid, present=b.get("present", []) + b.get("shows", []))
            ctx["style"] = {"revision": rid, "rules": br["rules"], "cards": [c["spec"] for c in br["cards"]],
                            "out_of_scope_rules": br["out_of_scope"]}
    if pid:
        try:
            F = B.check_chapter(project, ch, with_technical=False)["facts"].get(pid) or {}
            if pn and pn in F.get("panels", {}):
                ctx["board"] = {"note": F["panels"][pn].get("note"), "share": F["panels"][pn].get("share"),
                                "focal": [m.get("label") for m in F["marks"] if m["mark"] == "focal" and m.get("panel") == pn],
                                "art": [f"{i['asset']}@{i['version']} ({i['kind']})" for i in F["images"] if i["panel"] == pn]}
        except Exception:
            pass
        ctx["findings"] = [{"id": f["id"], "owner": f["owner"], "status": f["status"], "observed": f["observed"],
                            "intended": f.get("intended")} for f in RV.load_findings(project)
                           if f.get("page") == pid and f["status"] in ("open", "fixed", "editorial") and (not pn or f.get("panel") in (pn, None))]
        ctx["files"] = {"page_source": f"chapters/{ch}/pages/{pid}.py", "proof": f"build/ch{ch}/{pid}/proof.png"}
    if t.get("finding"):
        f = next((x for x in RV.load_findings(project) if x["id"] == t["finding"]), None)
        if f:
            ctx["finding"] = {k: f.get(k) for k in ("id", "code", "title", "owner", "status", "observed", "intended",
                                                     "evidence", "crop", "alternatives", "probe")}
    ctx["route"] = ROUTE.get(u["skill"], "")
    return ctx


ROUTE = {
    "story": "load skill manga-story: edit beats/lines/continuity, then `story check`",
    "design": "load skill manga-design: sheets, variants, direction revisions (`style revise`), `design check`",
    "board": "load skill manga-board: layout, lettering placement, roughs, `board check`",
    "illustrate": "load skill manga-illustrate: `job request` with the design pins and style above, host image call, review, `job select`",
    "compose": "load skill manga-compose: placement, masks, breaks, lettering fit, render, `check`",
    "review": "load skill manga-review: packet/score/tech/art, findings, `review recheck`",
    "direct": "a director decision: record it with `work decide`; creator decisions wait for `work approve`",
}


def context_md(ctx) -> str:
    return "# Context for " + ctx["unit"] + "\n\n```yaml\n" + yaml.safe_dump(ctx, sort_keys=False, allow_unicode=True, width=110) + "```\n"


def next_unit(project, mark=True) -> dict | None:
    R = runnable(project)
    if not R:
        return None
    u = R[0]
    ctx = context(project, u)
    out = wdir(project) / "context" / f"{u['id']}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(context_md(ctx))
    if mark:
        u["selected"] = {"at": _now(), "inputs": u.get("planned_inputs") or u.get("inputs"), "context": str(out.relative_to(project.root))}
        save_unit(project, u)
    return {"unit": u, "context": ctx, "file": str(out)}


def start(project, uid):
    u = get_unit(project, uid)
    if u["status"] not in ("queued", "stale", "blocked"):
        raise MangakitError(f"{uid} is {u['status']}")
    return _set(project, u, "running", "started", started=_now(), pid=os.getpid(), host=socket.gethostname())


def done(project, uid, outputs=(), note="", image_calls=None):
    """Record a finished unit against the inputs it was planned with (re-derived now)."""
    u = get_unit(project, uid)
    cur = None
    for n in derive_one(project, u):
        cur = n["inputs"]
    inputs = cur or u.get("planned_inputs") or u.get("inputs")
    kw = {"finished": _now(), "outputs": list(outputs) or u.get("outputs", []), "inputs": inputs}
    if image_calls is not None:
        kw["image_calls_used"] = image_calls
    u.pop("planned_inputs", None)
    return _set(project, u, "done", note or "done", **kw)


def derive_one(project, u) -> list[dict]:
    """Current inputs of the same need: renders are recomputed directly, anything else by key from a
    fresh derive (the unit then records the state it was finished against)."""
    t = u.get("target") or {}
    if u["kind"] == "render":
        return [{"inputs": page_inputs(project, t["page"], t.get("chapter"))}]
    if u.get("origin") == "story-change":
        return []
    ch = t.get("chapter") or project.chapter
    return [n for n in derive(project, ch, changes={}) if n["key"] == u["key"]]


def decide(project, subject, decision, reason, by="direct", refs=()) -> dict:
    with _lock(project):
        f = wdir(project) / "decisions.yaml"
        D = list((load_yaml(f) or {}).get("decisions") or []) if f.exists() else []
        d = {"id": f"D{len(D) + 1:03d}", "at": _now(), "by": by, "subject": subject, "decision": decision,
             "reason": reason, "refs": list(refs)}
        D.append(d)
        f.write_text(yaml.safe_dump({"decisions": D}, sort_keys=False, allow_unicode=True, width=110))
    return d


def judge_art_style(project, spec, revision, reason, by="direct") -> dict:
    """Record that a drawing version was looked at and meets a style revision (clears art-style-unrecorded /
    art-style-older for that revision). Decision logged in work/decisions.yaml."""
    from .assets import Registry
    from .design import Direction
    aid, _, ver = spec.partition("@")
    reg = Registry(project)
    rec = reg.load(aid)
    ver = ver or rec.get("selected")
    if ver not in rec["versions"]:
        raise MangakitError(f"no version {ver} of {aid}")
    if revision not in Direction(project).by_id:
        raise MangakitError(f"no style revision {revision}")
    if not reason:
        raise MangakitError("a style judgement says what was looked at (--reason)")
    d = decide(project, f"art style {aid}@{ver}", f"meets {revision}", reason, by=by, refs=[f"{aid}@{ver}", revision])
    j = rec["versions"][ver].setdefault("style_judged", {"revisions": [], "decisions": []})
    if revision not in j["revisions"]:
        j["revisions"].append(revision)
    j["decisions"].append(d["id"])
    reg.save(aid, rec)
    return d


# ============================================================================ run / resume
def _alive(pid, host) -> bool:
    if host != socket.gethostname() or not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:   # a zombie or a different program reusing the pid does not count
        cmd = FsPath(f"/proc/{pid}/cmdline").read_bytes().decode(errors="ignore")
        stat = FsPath(f"/proc/{pid}/stat").read_text().split()[2]
        return "mangakit" in cmd and stat != "Z"
    except OSError:
        return True


def run(project, limit=None, skills=None, log=print) -> dict:
    """Execute runnable units that carry an `exec` (mangakit commands: render, check, recheck),
    one at a time in plan order, saving each as it finishes. Agent units (art, inspect, decisions)
    are left for `work next`."""
    ran = []
    while True:
        R = [u for u in runnable(project) if u.get("exec") and (not skills or u["skill"] in skills)]
        if not R or (limit is not None and len(ran) >= limit):
            break
        u = R[0]
        start(project, u["id"])
        logf = wdir(project) / "logs" / f"{u['id']}.log"
        logf.parent.mkdir(exist_ok=True)
        cmd = [sys.executable, "-m", "mangakit.cli", "-C", str(project.root), *u["exec"]]
        log(f"{u['id']} {u['skill']:<8} {u['title']}")
        with open(logf, "w") as fh:
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
            uu = get_unit(project, u["id"]); uu["child"] = proc.pid; save_unit(project, uu)
            rc = proc.wait()
        u = get_unit(project, u["id"])
        if rc == 0 or (u["kind"] == "check" and rc == 1):
            outs = _outputs(project, u)
            done(project, u["id"], outs, f"ran: mangakit {' '.join(u['exec'])}")
            ran.append((u["id"], "done"))
        else:
            _set(project, u, "blocked", f"exit {rc}; see {logf.relative_to(project.root)}")
            ran.append((u["id"], "blocked"))
    return {"ran": ran}


def _outputs(project, u):
    t = u.get("target") or {}
    if u["kind"] == "render":
        ch = t.get("chapter") or project.chapter
        b = f"build/ch{ch}/{t['page']}/{t['view']}"
        return [f"{b}.png", f"{b}.manifest.json"]
    return []


def resume(project, chapter=None) -> dict:
    """After an interruption: running units whose process is gone are checked. A render whose output
    exists and matches its inputs is recorded done; anything else is requeued. Then re-plan, which
    adds what is missing and marks done work stale where an input changed."""
    out = {"interrupted": [], "recovered": [], "requeued": [], "still_running": []}
    for u in load_units(project):
        if u["status"] != "running":
            continue
        if _alive(u.get("pid"), u.get("host")) or _alive(u.get("child"), u.get("host")):
            out.setdefault("still_running", []).append(u["id"])    # a live worker owns it: leave it alone
            continue
        out["interrupted"].append(u["id"])
        t = u.get("target") or {}
        if u["kind"] == "render" and render_state(project, t["page"], t["view"], t.get("chapter"))[0] == "fresh":
            done(project, u["id"], _outputs(project, u), "recovered on resume: output complete and fresh")
            out["recovered"].append(u["id"])
        else:
            _set(project, u, "queued", "requeued on resume: interrupted before its output was recorded")
            out["requeued"].append(u["id"])
    P = plan(project, chapter)
    out.update({k: P[k] for k in ("created", "stale", "reopened", "cancelled")})
    U = load_units(project)
    out["stale_all"] = [u["id"] for u in U if u["status"] == "stale"]
    out["waiting"] = [u["id"] for u in U if u["status"] in ("queued", "stale") and u not in runnable(project, U)]
    R = runnable(project)
    out["todo_auto"] = [u["id"] for u in R if u.get("exec")]
    out["todo_agent"] = [u["id"] for u in R if not u.get("exec")]
    return out


def format_units(U, only=None) -> str:
    rows = []
    for u in U:
        if only and u["status"] not in only:
            continue
        t = u.get("target") or {}
        where = "/".join(x for x in (t.get("page"), t.get("panel")) if x) or t.get("finding") or t.get("line") or t.get("where") or ""
        rows.append(f"{u['id']}  {u['status']:<13} {u['skill']:<10} {u['kind']:<11} {where:<22} {u['title']}"
                    + (f"  [gate {u['gate']}]" if u.get("gate") and u["status"] == "needs-creator" else ""))
    return "\n".join(rows)


def metrics(project) -> dict:
    """Director-level pilot numbers from the unit files: units by status and origin, image calls spent
    per unit kind, image calls caused by story-change units (dialogue/fact edits), interruptions."""
    U = load_units(project)
    by = {}
    for u in U:
        by[u["status"]] = by.get(u["status"], 0) + 1
    calls = {}
    for u in U:
        n = u.get("image_calls_used") or 0
        if n:
            calls[u["kind"]] = calls.get(u["kind"], 0) + n
    hist = [h for u in U for h in u.get("history", [])]
    dec = (load_yaml(wdir(project) / "decisions.yaml") or {}).get("decisions", []) if (wdir(project) / "decisions.yaml").exists() else []
    return {"units": len(U), "by_status": by,
            "story_change_units": sum(1 for u in U if u.get("origin") == "story-change"),
            "image_calls_by_unit_kind": calls,
            "image_calls_from_story_change_units": sum(u.get("image_calls_used") or 0 for u in U if u.get("origin") == "story-change"),
            "image_calls_from_render_or_lettering_units": sum(u.get("image_calls_used") or 0 for u in U if u["kind"] in ("render", "reletter", "mask")),
            "stale_events": sum(1 for h in hist if h["status"] == "stale"),
            "requeued_on_resume": sum(1 for h in hist if "requeued on resume" in (h.get("note") or "")),
            "recovered_on_resume": sum(1 for h in hist if "recovered on resume" in (h.get("note") or "")),
            "decisions": len(dec), "creator_approvals": len(approvals(project)),
            "waiting_on_creator": [u["id"] for u in U if u["status"] == "needs-creator"]}
