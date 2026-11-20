"""manga-board: chapter plan (beats -> pages -> panels, stable ids), board checks (geometric reading
order, balloon order vs script, focal/sightline flow, crowding, reveals after page turns),
alternate layouts (pNNN.alt-<name>.py) with compare renders and id-safe promotion, and board renders
(lettered roughs, spreads, page-turn strip).

Authority: the story owns beats, lines and reveals; the board owns which page and panel shows them,
the panel geometry, reading order and lettering placement (page sources). Panel ids are names, never
numbers: they are kept across re-plans, alternates and promotion, and retired ids are never reused.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
from pathlib import Path as FsPath

from PIL import Image, ImageDraw
from shapely.geometry import Point

from .layout import reading_order
from .project import MangakitError, Project, dump_yaml, load_yaml
from .story import Story, _issue

PLAN_FILE = "board.yaml"
ALT_LOG = "alternates.yaml"
CROWDED, TOO_SMALL = 0.30, 0.50
# technical page checks that matter at board stage (the rest, e.g. art-resolution or mask raster
# checks, belong to compose/illustrate; `board check --all` shows them)
BOARD_TECH = {"text-overflow", "balloon-off-trim", "balloon-outside-safe", "balloon-overlap", "balloon-covers-landmark",
              "text-off-trim", "missing-dialogue", "breaks-mismatch", "missing-asset", "undeclared-clip",
              "breakout-intrudes", "breakout-cut", "art-gap", "font-pin", "stale-mask", "missing-mask", "mask-dims"}


def _now():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _chapter(project, chapter):
    return str(chapter or project.chapter)


def plan_path(project, chapter=None) -> FsPath:
    return project.root / "chapters" / _chapter(project, chapter) / PLAN_FILE


def _slug(s):
    return re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-") or "panel"


def _chapter_beats(st: Story, chapter):
    return [b for b in st.beats if str(b.get("chapter", "")) == chapter]


def _reveal_facts(st: Story, beat_id):
    """Facts this beat reveals that an earlier beat concealed."""
    b = st.beat[beat_id]
    out = []
    for f in (b.get("reader", {}) or {}).get("knows", []):
        if any(f in (x.get("reader", {}) or {}).get("conceals", []) for x in st.beats[:st.beat_ix[beat_id]]):
            out.append(f)
    return out


# ============================================================================ page facts
def page_facts(page) -> dict:
    """Everything the board checks need from one built page: panels in declared and geometric order,
    lettering in reading order, focal marks and sightlines (page marks + rough sketch marks)."""
    from .render import _balloons, iter_layers, rough_marks_on_page
    rtl = page.direction == "rtl"
    panels = page.panels
    shapes = {pid: p.path.shape() for pid, p in panels.items()}
    declared = [p.id for p in sorted(panels.values(), key=lambda q: q.order)]
    geo = reading_order(shapes, rtl) if shapes else []

    def owner(pt, given=None):
        if given and given in panels:
            return given
        P = Point(pt)
        for pid in geo:
            if shapes[pid].contains(P):
                return pid
        return None

    letters = []
    for L in iter_layers(page.layers):
        if L.kind == "balloon":
            body = L.data["body"]
            letters.append({"line": L.data["dialogue"], "kind": "balloon", "panel": owner(L.data["at"], L.data["panel"]),
                            "shape": body.shape(), "bbox": [round(v, 1) for v in body.bbox()], "at": L.data["at"]})
        elif L.kind == "text" and L.data.get("line"):
            x0, y0, x1, y1 = L.data["bbox"]
            from shapely.geometry import box
            letters.append({"line": L.data["line"], "kind": "sfx", "panel": owner(L.data["at"], L.data["panel"]),
                            "shape": box(x0, y0, x1, y1), "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
                            "at": L.data["at"]})
    rank = {pid: i for i, pid in enumerate(geo)}
    seq = []
    for pid in geo + [None]:
        inside = [l for l in letters if l["panel"] == pid]
        order = reading_order({i: l["shape"] for i, l in enumerate(inside)}, rtl) if inside else []
        seq += [inside[i] for i in order]
    marks = []
    for L in iter_layers(page.layers):
        if L.kind == "board" and L.data["mark"] in ("focal", "sightline"):
            m = dict(L.data)
            pt = m["at"] if m["mark"] == "focal" else m["from"]
            m["panel"] = owner(pt, m.get("panel"))
            marks.append(m)
        elif L.kind == "image" and L.data["drawing"].kind == "rough" and not L.data["mask"]:
            for m in rough_marks_on_page(L):
                if m["mark"] == "note":
                    continue
                pt = m["at"] if m["mark"] == "focal" else m["from"]
                clip = L.data["clip"]
                if clip is not None and not clip.shape().buffer(2).contains(Point(pt)):
                    continue          # the mark is cropped out of this panel
                m["panel"] = owner(pt, L.data["panel"])
                marks.append(m)
    images = []
    for L in iter_layers(page.layers):
        if L.kind == "image":
            d = L.data["drawing"]
            images.append({"panel": L.data["panel"], "asset": d.asset_id, "version": d.version,
                           "kind": "missing" if d.missing else d.kind, "break": L.data["mask"] is not None})
    return {"page": page.id, "alt": page.alt, "side": page.side, "declared": declared, "geometric": geo,
            "rank": rank, "panels": {pid: {"beat": p.beat, "bbox": [round(v, 1) for v in p.bbox],
                                           "area": shapes[pid].area, "note": p.note,
                                           "share": round(shapes[pid].intersection(page.trim.shape()).area
                                                          / (page.width * page.height), 3)}
                                     for pid, p in panels.items()},
            "shapes": shapes, "letters": seq, "marks": marks, "images": images}


# ============================================================================ checks
def check_page(page, facts=None, story: Story | None = None) -> list[dict]:
    F = facts or page_facts(page)
    I = []
    where = page.id + (f".alt-{page.alt}" if page.alt else "")
    if F["declared"] != F["geometric"]:
        I.append(_issue("warn", "panel-order", where,
                        f"declared order {F['declared']} but the layout reads {F['geometric']} ({page.direction})"))
    # bleeding into the binding loses art in the gutter unless it is a deliberate spread panel
    for pid, P in F["panels"].items():
        x0, y0, x1, y1 = P["bbox"]
        if (page.side == "right" and x0 < -0.5) or (page.side == "left" and x1 > page.width + 0.5):
            I.append(_issue("info", "bleed-inside", f"{where}/{pid}",
                            "panel bleeds over the inside (binding) edge; art there disappears into the gutter"))
    # lettering order vs script order
    order = page.script.order
    placed = [l["line"] for l in F["letters"]]
    script_order = [i for i in order if i in placed]
    if placed != script_order:
        I.append(_issue("warn", "balloon-order", where,
                        f"reading order {placed} differs from script order {script_order}"))
    for l in F["letters"]:
        line = page.script.lines.get(l["line"])
        pid = l["panel"]
        if pid is None:
            I.append(_issue("warn", "lettering-outside-panels", f"{where}/{l['line']}", "lettering sits in no panel"))
            continue
        pb = F["panels"][pid]["beat"]
        if line and pb and line.get("beat") != pb:
            I.append(_issue("warn", "balloon-beat", f"{where}/{pid}",
                            f"{l['line']} belongs to beat {line.get('beat')} but panel {pid} shows {pb}"))
        if l["kind"] == "balloon":
            out = l["shape"].difference(F["shapes"][pid]).area / max(1.0, l["shape"].area)
            if out > 0.2:
                I.append(_issue("warn", "balloon-outside-panel", f"{where}/{l['line']}",
                                f"{out:.0%} of the balloon lies outside panel {pid}"))
    # crowding
    for pid, P in F["panels"].items():
        shp = F["shapes"][pid]
        ls = [l for l in F["letters"] if l["panel"] == pid]
        if not ls:
            continue
        area = sum(l["shape"].intersection(shp).area for l in ls)
        frac = area / max(1.0, P["area"])
        x0, y0, x1, y1 = P["bbox"]
        big = [l["line"] for l in ls if (l["bbox"][2] - l["bbox"][0]) > 0.9 * (x1 - x0) or
               (l["bbox"][3] - l["bbox"][1]) > 0.9 * (y1 - y0)]
        if big or frac > TOO_SMALL:
            I.append(_issue("error", "panel-too-small", f"{where}/{pid}",
                            f"lettering covers {frac:.0%} of the panel" + (f"; {big} wider/taller than the panel" if big else "")))
        elif frac > CROWDED:
            I.append(_issue("warn", "panel-crowded", f"{where}/{pid}",
                            f"lettering covers {frac:.0%} of the panel (limit {CROWDED:.0%}); enlarge it or move lines"))
    # focal points and sightlines
    geo = F["geometric"]
    for pid in geo:
        kinds = {im["kind"] for im in F["images"] if im["panel"] == pid and not im["break"]}
        if "rough" in kinds or "missing" in kinds:
            what = sorted({im["asset"] for im in F["images"] if im["panel"] == pid and im["kind"] in ("rough", "missing")})
            I.append(_issue("info", "needs-art", f"{where}/{pid}",
                            ("rough only: " if kinds <= {"rough", "missing"} else "final art + rough extension: ") + ", ".join(what)))
        fm = [m for m in F["marks"] if m["mark"] == "focal" and m["panel"] == pid]
        if not fm:
            I.append(_issue("info", "no-focal", f"{where}/{pid}", "no focal point declared (page.focal or a rough sketch)"))
        for m in fm:
            for l in F["letters"]:
                if l["shape"].buffer(4).contains(Point(m["at"])):
                    I.append(_issue("warn", "focal-covered", f"{where}/{pid}",
                                    f"focal point {m.get('label') or ''} is under {l['line']}"))
    for m in F["marks"]:
        if m["mark"] != "sightline" or m["panel"] not in F["rank"]:
            continue
        pid = m["panel"]
        x0, y0, x1, y1 = F["panels"][pid]["bbox"]
        core = F["shapes"][pid].buffer(-0.04 * min(x1 - x0, y1 - y0))
        if core.contains(Point(m["to"])):
            continue       # gaze stays inside the panel (looks at something shown); ending at the edge = leaves it
        k = F["rank"][pid]
        if k + 1 >= len(geo):
            continue
        nshape = F["shapes"][geo[k + 1]]
        nxt = nshape.centroid
        vx, vy = m["to"][0] - m["from"][0], m["to"][1] - m["from"][1]
        fwd = -1 if page.direction == "rtl" else 1
        if nshape.bounds[1] >= F["shapes"][pid].centroid.y:
            # next panel starts a lower tier: forward (rtl: left) or down leads on; back or up fights the read
            against = (vx * fwd < 0 and abs(vx) > abs(vy)) or (vy < 0 and abs(vy) > abs(vx))
        else:
            against = vx * (nxt.x - m["from"][0]) + vy * (nxt.y - m["from"][1]) < 0
        if against:
            I.append(_issue("info", "sightline-against-flow", f"{where}/{pid}",
                            f"sightline '{m.get('label') or m.get('kind', 'gaze')}' leaves the panel away from the next panel {geo[k + 1]}"))
    return I


def _load(project, pid, chapter, alts):
    from .render import load_page
    page, _ = load_page(project, pid, chapter=chapter, alt=(alts or {}).get(pid))
    return page


def check_chapter(project: Project, chapter=None, alts=None, with_technical=True, all_technical=False) -> dict:
    """Board checks for every page of a chapter (alts = {page: alt-name} to check alternates)."""
    from .checks import run_checks
    from .render import spread_groups
    ch = _chapter(project, chapter)
    st = Story(project)
    pages = project.chapter_pages(ch)
    I, facts, built = [], {}, {}
    info = {"pages": [], "spreads": spread_groups(project, pages, chapter=ch)}
    for pid in pages:
        try:
            page = _load(project, pid, ch, alts)
        except Exception as e:  # a broken page is a finding, not a crash
            I.append(_issue("error", "page-broken", pid, str(e)))
            continue
        built[pid] = page
        F = page_facts(page)
        facts[pid] = F
        I += check_page(page, F, st)
        if with_technical:
            for x in run_checks(page):
                if x["code"] in ("reading-order", "unlettered-line"):
                    continue
                if not all_technical and x["code"] not in BOARD_TECH:
                    continue        # superseded by the board's balloon-order / line coverage checks
                x = dict(x)
                x["where"] = f"{pid}:{x['where']}"
                x["source"] = "page"
                I.append(x)
        info["pages"].append({"page": pid, "panels": [{"id": p, "beat": F["panels"][p]["beat"]} for p in F["geometric"]],
                              "balloons": [{"line": l["line"], "panel": l["panel"]} for l in F["letters"]]})
    # story cross-checks against the boarded pages: beat order, reveals vs facing pages
    for x in st._check_pages(info):
        x = dict(x)
        if x["code"] == "panel-order":
            x["code"] = "beat-order"
        I.append(x)
    # coverage: every beat of the chapter boarded, every line lettered somewhere
    beats = _chapter_beats(st, ch)
    drawn = {F["panels"][p]["beat"] for F in facts.values() for p in F["panels"]}
    lettered = {l["line"] for F in facts.values() for l in F["letters"]}
    for b in beats:
        if b["id"] not in drawn:
            I.append(_issue("error", "beat-not-boarded", b["id"], "no panel shows this beat"))
        for l in st.lines:
            if l.get("beat") == b["id"] and l["id"] not in lettered:
                I.append(_issue("error", "line-not-lettered", l["id"], f"line of beat {b['id']} is not lettered on any page"))
    # ids unique in the chapter (a panel may move between pages; its id must stay unambiguous)
    seen = {}
    for pid, F in facts.items():
        for p in F["panels"]:
            if p in seen:
                I.append(_issue("warn", "panel-id-duplicate", f"{pid}/{p}", f"panel id also used on {seen[p]}"))
            seen[p] = pid
    # page turns and reveals
    turns = []
    spreads = info["spreads"]
    rtl = project.direction == "rtl"
    for k, g in enumerate(spreads):
        reveals = []
        for pid in g:
            F = facts.get(pid)
            if not F:
                continue
            for pn in F["geometric"]:
                b = F["panels"][pn]["beat"]
                if b and b in st.beat:
                    for f in _reveal_facts(st, b):
                        reveals.append({"fact": f, "page": pid, "panel": pn, "beat": b})
        for r in reveals:
            first = g[0]
            if k == 0:
                I.append(_issue("warn", "reveal-without-turn", f"{r['page']}/{r['panel']}",
                                f"{r['fact']} is revealed on the opening spread; no page turn precedes it"))
            elif r["page"] != first:
                I.append(_issue("warn", "reveal-not-first-after-turn", f"{r['page']}/{r['panel']}",
                                f"{r['fact']} lands on {r['page']}, the second page of spread {g}; the eye meets {first} first"))
        turns.append({"spread": g, "after_turn": k > 0, "reveals": reveals})
    plan = load_yaml(plan_path(project, ch)) if plan_path(project, ch).exists() else None
    if plan:
        I += _plan_compliance(plan, facts)
    return {"chapter": ch, "issues": I, "facts": facts, "turns": turns, "spreads": spreads, "alts": alts or {},
            "direction": project.direction}


def _plan_compliance(plan, facts) -> list[dict]:
    I = []
    where_now = {p: pid for pid, F in facts.items() for p in F["panels"]}
    for pg in plan.get("pages", []):
        for pn in pg.get("panels", []):
            now = where_now.get(pn["id"])
            if now is None:
                if pg["id"] in facts:
                    I.append(_issue("warn", "plan-panel-missing", f"{pg['id']}/{pn['id']}",
                                    f"planned panel (beat {pn.get('beat')}) is not on the page"))
            elif now != pg["id"]:
                I.append(_issue("info", "plan-panel-moved", pn["id"], f"planned on {pg['id']}, drawn on {now}"))
    planned = {pn["id"] for pg in plan.get("pages", []) for pn in pg.get("panels", [])}
    for p, pid in where_now.items():
        if p not in planned:
            I.append(_issue("info", "plan-unplanned-panel", f"{pid}/{p}", "panel is not in board.yaml (run board plan)"))
    for r in plan.get("retired", []):
        if r["id"] in where_now:
            I.append(_issue("error", "retired-id-reused", r["id"], f"retired panel id reused on {where_now[r['id']]}"))
    return I


def format_report(R) -> str:
    out = [f"board check chapter {R['chapter']}  read={R['direction']}"
           + (f"  alts={R['alts']}" if R["alts"] else "")]
    for pid, F in R["facts"].items():
        out.append(f"\n{pid}{' (alt ' + F['alt'] + ')' if F['alt'] else ''}  side={F['side']}")
        for i, pn in enumerate(F["geometric"], 1):
            P = F["panels"][pn]
            ls = [l["line"] for l in F["letters"] if l["panel"] == pn]
            fm = [m for m in F["marks"] if m["panel"] == pn and m["mark"] == "focal"]
            sl = [m for m in F["marks"] if m["panel"] == pn and m["mark"] == "sightline"]
            art = sorted({f"{im['asset']}@{im['version']}" + ("(rough)" if im["kind"] == "rough" else "")
                          + ("(MISSING)" if im["kind"] == "missing" else "")
                          for im in F["images"] if im["panel"] == pn and not im["break"]})
            out.append(f"  {i}. {pn:<16} beat={P['beat'] or '-':<16} {P['share']:>4.0%} of page  lines={','.join(ls) or '-'}")
            out.append(f"     focal: " + ("; ".join(f"F{m.get('rank', 1)} {m.get('label') or ''} @({m['at'][0]:.0f},{m['at'][1]:.0f})"
                                                   for m in sorted(fm, key=lambda m: m.get('rank', 1))) or "-")
                       + (f"   lines of sight: {len(sl)}" if sl else "") + (f"   art: {', '.join(art)}" if art else ""))
    out.append("\nspreads / page turns:")
    for t in R["turns"]:
        tag = "after a page turn" if t["after_turn"] else "opening"
        rv = "; ".join(f"reveals {r['fact']} on {r['page']}/{r['panel']}" for r in t["reveals"]) or "no reveal"
        out.append(f"  [{' '.join(t['spread'])}]  {tag}: {rv}")
    sev = {"error": 0, "warn": 1, "info": 2}
    out.append("")
    for i in sorted(R["issues"], key=lambda x: (sev.get(x["severity"], 3), x.get("source", ""), x["code"])):
        out.append(f"[{i['severity'].upper():5}] {i['code']:<28} {i['where']:<30} {i['message']}")
    n = {s: sum(1 for i in R["issues"] if i["severity"] == s) for s in ("error", "warn", "info")}
    out.append(f"board check: {n['error']} error(s), {n['warn']} warning(s), {n['info']} info")
    return "\n".join(out)


# ============================================================================ chapter plan
def plan(project: Project, chapter=None, per_page: int = 5, write=False, stubs=False) -> dict:
    """Map the chapter's beats to pages and panels. Drawn pages are authoritative (their panel ids and
    beats are kept), then board.yaml, then new allocations. Reveal beats start on the first page after
    a page turn that follows every beat concealing the fact. Ids are never renumbered or reused."""
    from .render import load_page, spread_groups
    ch = _chapter(project, chapter)
    st = Story(project)
    beats = _chapter_beats(st, ch)
    old = load_yaml(plan_path(project, ch)) if plan_path(project, ch).exists() else {}
    retired = list(old.get("retired", []))
    pages = list(project.chapter_pages(ch))
    for pg in old.get("pages", []):
        if pg["id"] not in pages:
            pages.append(pg["id"])
    layout = {pid: [] for pid in pages}            # pid -> [panel dicts]
    status = {}
    for pid in pages:
        f = project.root / "chapters" / ch / "pages" / f"{pid}.py"
        if f.exists():
            try:
                page, _ = load_page(project, pid, chapter=ch)
            except Exception as e:
                raise MangakitError(f"{pid} does not build: {e}")
            F = page_facts(page)
            for pn in F["geometric"]:
                layout[pid].append({"id": pn, "beat": F["panels"][pn]["beat"],
                                    "lines": [l["line"] for l in F["letters"] if l["panel"] == pn], "status": "drawn"})
            status[pid] = "drawn"
        else:
            opg = next((p for p in old.get("pages", []) if p["id"] == pid), {"panels": []})
            layout[pid] = [dict(p, status="planned") for p in opg.get("panels", [])]
            status[pid] = "planned"
    used = {p["id"] for ps in layout.values() for p in ps} | {r["id"] for r in retired}
    # retire planned panels whose beat left the chapter
    beat_ids = {b["id"] for b in beats}
    for pid in pages:
        keep = []
        for p in layout[pid]:
            if p["status"] == "planned" and p.get("beat") not in beat_ids:
                retired.append({"id": p["id"], "page": pid, "beat": p.get("beat"), "at": _now(),
                                "why": "beat no longer in chapter"})
            else:
                keep.append(p)
        layout[pid] = keep
    placed = {p["beat"] for ps in layout.values() for p in ps if p.get("beat")}
    added = []

    def spreads_now():
        return spread_groups(project, pages, chapter=ch)

    def new_page():
        nums = [int(m.group(1)) for p in pages for m in [re.match(r"p(\d+)$", p)] if m]
        pid = f"p{(max(nums) + 1) if nums else 1:03d}"
        pages.append(pid)
        layout[pid] = []
        status[pid] = "planned"
        return pid

    def page_of_beat(bid):
        for pid in pages:
            if any(p.get("beat") == bid for p in layout[pid]):
                return pid
        return None

    for b in beats:
        if b["id"] in placed:
            continue
        prev = [x["id"] for x in beats[:beats.index(b)] if page_of_beat(x["id"])]
        start = pages.index(page_of_beat(prev[-1])) if prev else 0
        if not pages:
            new_page()
        reveal = _reveal_facts(st, b["id"])
        k = start
        while True:
            if k >= len(pages):
                new_page()
            pid = pages[k]
            if reveal:
                concealing = [x["id"] for x in st.beats[:st.beat_ix[b["id"]]]
                              if set(reveal) & set((x.get("reader", {}) or {}).get("conceals", []))]
                sp = spreads_now()
                si = {p: i for i, g in enumerate(sp) for p in g}
                ok = sp[si[pid]][0] == pid and all(si.get(page_of_beat(c), -1) < si[pid] for c in concealing if page_of_beat(c))
                ok = ok and not any(layout[pid]) if status[pid] == "planned" else ok and False
            else:
                ok = status[pid] == "planned" and len(layout[pid]) < per_page
            if ok:
                break
            k += 1
        n = 1
        base = _slug(b["id"])
        pn = base
        while pn in used:
            n += 1
            pn = f"{base}-{n}"
        used.add(pn)
        lines = [l["id"] for l in st.lines if l.get("beat") == b["id"]]
        layout[pid].append({"id": pn, "beat": b["id"], "lines": lines, "status": "planned",
                            **({"size": "large", "reveals": reveal} if reveal else {})})
        added.append(f"{pid}/{pn}")
        placed.add(b["id"])
    sp = spreads_now()
    si = {p: i for i, g in enumerate(sp) for p in g}
    out = {"chapter": ch, "direction": project.direction,
           "pairing": __import__("mangakit.render", fromlist=["pairing"]).pairing(project, ch),
           "pages": [], "retired": retired, "updated": _now()}
    for pid in pages:
        g = sp[si[pid]]
        out["pages"].append({"id": pid, "status": status[pid], "spread": si[pid] + 1, "after_turn": si[pid] > 0 and g[0] == pid,
                             "panels": layout[pid]})
    issues = []
    lines_planned = {l for pg in out["pages"] for p in pg["panels"] for l in p.get("lines", [])}
    for b in beats:
        if not page_of_beat(b["id"]):
            issues.append(_issue("error", "beat-unplaced", b["id"], "beat has no panel"))
        for l in st.lines:
            if l.get("beat") == b["id"] and l["id"] not in lines_planned:
                issues.append(_issue("warn", "line-unplaced", l["id"], f"line of beat {b['id']} is in no planned panel"))
    last = -1
    for pg in out["pages"]:
        for p in pg["panels"]:
            ix = st.beat_ix.get(p.get("beat"), -1)
            if ix >= 0 and ix < last:
                issues.append(_issue("warn", "beat-order", f"{pg['id']}/{p['id']}", "beat placed after a later beat"))
            last = max(last, ix)
    out_info = {"plan": out, "added": added, "issues": issues, "stubs": []}
    if write:
        dump_yaml(plan_path(project, ch), out)
        meta = project.root / "chapters" / ch / "chapter.yaml"
        m = load_yaml(meta) if meta.exists() else {"id": ch}
        if list(m.get("pages") or []) != pages:
            m["pages"] = pages
            dump_yaml(meta, m)
    if stubs:
        for pg in out["pages"]:
            f = project.root / "chapters" / ch / "pages" / f"{pg['id']}.py"
            if not f.exists() and pg["panels"]:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(stub_source(pg, st))
                out_info["stubs"].append(str(f.relative_to(project.root)))
    return out_info


def stub_source(pg, st: Story) -> str:
    """A first lettered-rough page source for a planned page: one tier per panel (weights from line
    counts; reveal panels get more), balloons stacked from each panel's reading-start corner,
    rough slots per panel (rough-<panel> until final art <panel> is selected)."""
    ps = pg["panels"]
    w = [3 if p.get("size") == "large" else 1 + 0.4 * len(p.get("lines", [])) for p in ps]
    L = [f'"""{pg["id"]} - board stub from `mangakit board plan --stubs`. Replace the tiers with the real layout."""',
         "", "", "def build(page, art, script):", "    L = page.layout()",
         f"    tiers = L.rows({[round(x, 2) for x in w]})", "    rtl = page.direction == 'rtl'"]
    for i, p in enumerate(ps):
        v = p["id"].replace("-", "_")
        L.append(f'    {v} = page.panel("{p["id"]}", tiers[{i}], beat="{p["beat"]}")')
        L.append(f'    d = art.slot(final="{p["id"]}", rough="rough-{p["id"]}")')
        L.append(f"    x0, y0, x1, y1 = {v}.bbox")
        L.append(f"    page.image(d, transform={v}.align(d, source=(d.width / 2, d.height / 2), target=((x0 + x1) / 2, (y0 + y1) / 2),"
                 f" scale=max((x1 - x0) / d.width, (y1 - y0) / d.height)), clip={v}.path)")
    L.append("    page.borders()")
    for i, p in enumerate(ps):
        v = p["id"].replace("-", "_")
        for k, lid in enumerate(p.get("lines", [])):
            line = st.line.get(lid, {})
            if line.get("kind") == "sfx":
                L.append(f'    page.text(None, at=(({v}.bbox[0] + {v}.bbox[2]) / 2, {v}.bbox[3] - 40), panel="{p["id"]}", line="{lid}")')
            else:
                shape = '"box"' if line.get("kind") == "caption" else '"ellipse"'
                L.append(f'    page.balloon("{lid}", shape={shape}, at=(({v}.bbox[2] - 150 - {k} * 60) if rtl else ({v}.bbox[0] + 150 + {k} * 60), '
                         f'{v}.bbox[1] + 90 + {k} * 110), panel="{p["id"]}")')
    L.append("    return page")
    return "\n".join(L) + "\n"


# ============================================================================ alternates
def list_alts(project, chapter=None) -> dict:
    ch = _chapter(project, chapter)
    d = project.root / "chapters" / ch / "pages"
    out = {}
    for f in sorted(d.glob("p*.alt-*.py")):
        pid, name = f.stem.split(".alt-", 1)
        out.setdefault(name, []).append(pid)
    return out


def alt_create(project, pid, name, chapter=None, from_alt=None) -> FsPath:
    from .render import alt_file
    ch = _chapter(project, chapter)
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", name) or name.startswith("pre-"):
        raise MangakitError("alt names: lowercase letters, digits and dashes; 'pre-*' is reserved for archives")
    dst = alt_file(project, pid, name, ch)
    if dst.exists():
        raise MangakitError(f"{dst.relative_to(project.root)} exists")
    src = alt_file(project, pid, from_alt, ch) if from_alt else project.page_file(pid, ch)
    shutil.copy2(src, dst)
    return dst


def _alts_map(project, chapter, name):
    if name in (None, "current"):
        return {}
    pids = list_alts(project, chapter).get(name)
    if not pids:
        raise MangakitError(f"no alternate named {name!r} in chapter {_chapter(project, chapter)}")
    return {p: name for p in pids}


def spread_image(project, group, chapter=None, alts=None, view="reading", highlight=None, label=None) -> Image.Image:
    """Spread at reading height, pages in their slots (rtl: earlier page on the right), with optional
    red frames around panels ({page: [bbox,...]} in page units)."""
    from .render import _pil_font, _reading_png, lone_slot
    alts = alts or {}
    ims, pages_ = [], []
    for pid in group:
        png, page = _reading_png(project, pid, chapter, alts.get(pid), view)
        ims.append(Image.open(png).convert("RGB"))
        pages_.append(page)
    w, h = ims[0].size
    rtl = project.direction == "rtl"
    if len(group) == 2:
        slots = [1, 0] if rtl else [0, 1]
    else:
        slots = [lone_slot(project, group, project.chapter_pages(chapter), chapter)]
    canvas = Image.new("RGB", (w * 2 + 6, h + 56), "#8a8a8a")
    d = ImageDraw.Draw(canvas)
    f = _pil_font(project, 26)
    for im, k, pid, page in zip(ims, slots, group, pages_):
        x = k * (w + 6)
        canvas.paste(im, (x, 0))
        s = h / page.height
        for bb in (highlight or {}).get(pid, []):
            d.rectangle([x + bb[0] * s, bb[1] * s, x + bb[2] * s, bb[3] * s], outline="#e00000", width=5)
        d.text((x + w // 2, h + 28), pid + (f" (alt {alts[pid]})" if alts.get(pid) else ""), fill="white", font=f, anchor="mm")
    d.text((w + 3, h + 28), "<-- read" if rtl else "read -->", fill="#ffe680", font=_pil_font(project, 20), anchor="mm")
    if label:
        d.text((10, h + 28), label, fill="#ffffff", font=_pil_font(project, 22), anchor="lm")
    return canvas


def render_board(project: Project, chapter=None, alt=None, out_dir=None) -> dict:
    """Lettered roughs per page, spreads (reading and rough), and the page-turn strip with reveal
    panels framed in red. Returns paths."""
    from .render import _pil_font, load_page, render_page
    ch = _chapter(project, chapter)
    alts = _alts_map(project, ch, alt)
    tag = f"alt-{alt}" if alts else "current"
    od = FsPath(out_dir) if out_dir else project.build_dir(f"ch{ch}", "board", tag)
    od.mkdir(parents=True, exist_ok=True)
    R = check_chapter(project, ch, alts)
    res = {"dir": str(od), "pages": {}, "spreads": [], "rough_spreads": []}
    for pid in project.chapter_pages(ch):
        page, _ = load_page(project, pid, chapter=ch, alt=alts.get(pid))
        rough = render_page(page, "rough")
        dst = od / f"{pid}-rough.png"
        shutil.copy2(rough, dst)
        res["pages"][pid] = str(dst)
    hl = {}
    for t in R["turns"]:
        for r in t["reveals"]:
            hl.setdefault(r["page"], []).append(R["facts"][r["page"]]["panels"][r["panel"]]["bbox"])
    strip = []
    for k, t in enumerate(R["turns"]):
        g = t["spread"]
        im = spread_image(project, g, ch, alts, "reading", hl if t["after_turn"] else None)
        p = od / f"spread-{'-'.join(g)}.png"
        im.save(p)
        res["spreads"].append(str(p))
        rim = spread_image(project, g, ch, alts, "rough")
        rp = od / f"rough-spread-{'-'.join(g)}.png"
        rim.save(rp)
        res["rough_spreads"].append(str(rp))
        strip.append((im, t))
    # page-turn strip: spreads top to bottom in reading order with turn bars between them
    W = max(im.width for im, _ in strip)
    bar = 70
    H = sum(im.height for im, _ in strip) + bar * (len(strip) - 1) + 60
    canvas = Image.new("RGB", (W, H), "#3a3a3a")
    d = ImageDraw.Draw(canvas)
    d.text((14, 30), f"chapter {ch} board ({tag}): spreads in reading order; red = reveal panel after a page turn",
           fill="#ffffff", font=_pil_font(project, 24), anchor="lm")
    y = 60
    for i, (im, t) in enumerate(strip):
        if i:
            rv = ", ".join(f"{r['fact']} on {r['page']}" for r in t["reveals"]) or "no reveal"
            d.rectangle([0, y, W, y + bar - 8], fill="#c0392b" if t["reveals"] else "#555555")
            d.text((W // 2, y + (bar - 8) // 2), f"PAGE TURN  ->  {rv}", fill="#ffffff", font=_pil_font(project, 28), anchor="mm")
            y += bar
        canvas.paste(im, (0, y))
        y += im.height
    tp = od / "turns.png"
    canvas.save(tp)
    res["turns"] = str(tp)
    rep = od / "board-check.txt"
    rep.write_text(format_report(R) + "\n")
    res["check"] = str(rep)
    res["report"] = R
    return res


def compare(project: Project, names, chapter=None, out=None) -> dict:
    """Side-by-side comparison of alternates: for each name (or 'current') the affected spreads at
    reading size, with that layout's board-check summary. Returns paths and per-alt summaries."""
    from .render import _pil_font, spread_groups
    ch = _chapter(project, chapter)
    maps = {n: _alts_map(project, ch, n) for n in names}
    touched = sorted({p for m in maps.values() for p in m})
    groups = [g for g in spread_groups(project, project.chapter_pages(ch), chapter=ch) if set(g) & set(touched)] \
        or spread_groups(project, project.chapter_pages(ch), chapter=ch)[:1]
    rows, summ = [], {}
    for n in names:
        R = check_chapter(project, ch, maps[n])
        cnt = {s: sum(1 for i in R["issues"] if i["severity"] == s) for s in ("error", "warn", "info")}
        board = [i for i in R["issues"] if i.get("source") != "page" and i["severity"] != "info"]
        tech = [i for i in R["issues"] if i.get("source") == "page" and i["severity"] != "info"]
        shares = {f"{pid}/{pn}": F["panels"][pn]["share"] for pid, F in R["facts"].items() for pn in F["panels"]}
        needs = [i["where"] for i in R["issues"] if i["code"] == "needs-art"]
        summ[n] = {"counts": cnt, "board": [f"{i['code']} {i['where']}" for i in board],
                   "panel_share": shares, "needs_art": needs,
                   "technical": [f"{i['code']} {i['where']}" for i in tech], "report": format_report(R)}
        ims = [spread_image(project, g, ch, maps[n], "reading", label=n) for g in groups]
        rows.append((n, ims, cnt, summ[n]["board"], summ[n]["technical"]))
    W = max(sum(im.width for im in ims) + 10 * (len(ims) - 1) for _, ims, *_ in rows) + 520
    H = sum(max(im.height for im in ims) for _, ims, *_ in rows) + 20 * len(rows)
    canvas = Image.new("RGB", (W, H), "#2f2f2f")
    d = ImageDraw.Draw(canvas)
    y = 0
    for n, ims, cnt, board, tech in rows:
        x = 0
        for im in ims:
            canvas.paste(im, (x, y))
            x += im.width + 10
        tx = x + 10
        d.text((tx, y + 20), "current layout" if n == "current" else f"alt {n}", fill="#ffe680", font=_pil_font(project, 44))
        d.text((tx, y + 82), f"{cnt['error']} error(s)  {cnt['warn']} warn  {cnt['info']} info", fill="#ffffff",
               font=_pil_font(project, 30))
        yy = y + 130
        big = sorted(((v, k) for k, v in summ[n]["panel_share"].items() if k.split("/")[0] in touched), reverse=True)[:4]
        for line in (["board:"] + [f"  {b}" for b in board[:12]] + ["technical:"] + [f"  {t}" for t in tech[:8]]
                     + ["largest panels (share of page):"] + [f"  {k} {v:.0%}" for v, k in big]
                     + [f"art still needed: {len(summ[n]['needs_art'])} panel(s)"]):
            d.text((tx, yy), line[:40], fill="#dddddd", font=_pil_font(project, 24))
            yy += 32
        y += max(im.height for im in ims) + 20
    ch_dir = project.build_dir(f"ch{ch}", "board")
    o = FsPath(out) if out else ch_dir / f"compare-{'-vs-'.join(names)}.png"
    o.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(o)
    md = o.with_suffix(".md")
    md.write_text("\n\n".join(f"## {n}\n\n```\n{summ[n]['report']}\n```" for n in names) + "\n")
    return {"png": str(o), "md": str(md), "summary": {n: {k: v for k, v in s.items() if k != "report"} for n, s in summ.items()}}


def _job_refs(project, chapter):
    """(page, panel) -> [job ids] for art requests that target a panel."""
    out = {}
    jd = project.root / "art" / "jobs"
    for f in sorted(jd.glob("job-*/request.yaml")) if jd.exists() else []:
        t = (load_yaml(f) or {}).get("target", {})
        if str(t.get("chapter", project.chapter)) == str(chapter):
            out.setdefault((t.get("page"), t.get("panel")), []).append(f.parent.name)
    return out


def promote(project: Project, name, chapter=None, reason="", force=False, dry_run=False) -> dict:
    """Make alternate `name` the current layout of every page it covers. Panel ids must survive:
    an id that disappears from the chapter is refused when a job or the plan references it (unless
    force). Moves between pages are allowed and reported. The replaced sources are archived as
    pNNN.alt-pre-<name>.py and the promotion is logged in alternates.yaml."""
    from .render import alt_file, load_page
    ch = _chapter(project, chapter)
    if not reason and not dry_run:
        raise MangakitError("a promotion needs --reason (what the comparison showed)")
    logf = project.root / "chapters" / ch / ALT_LOG
    if name == "current":       # a decision to keep the current layout is logged too
        log = load_yaml(logf) if logf.exists() else {"promotions": []}
        others = sorted(n for n in list_alts(project, ch) if not n.startswith("pre-"))
        entry = {"alt": "current", "kept": True, "at": _now(), "reason": reason, "alternates": others}
        if not dry_run:
            log["promotions"].append(entry)
            dump_yaml(logf, log)
        return {"alt": "current", "pages": [], "dropped": [], "moved": [], "added": [], "blocked": [], "stale_jobs": [],
                "archived": [], "promoted": False, "kept": True, "alternates": others}
    amap = _alts_map(project, ch, name)
    pages = project.chapter_pages(ch)
    before, after = {}, {}
    for pid in pages:
        before[pid] = list(load_page(project, pid, chapter=ch)[0].panels)
        after[pid] = list(load_page(project, pid, chapter=ch, alt=amap.get(pid))[0].panels)
    where_b = {p: pid for pid, ps in before.items() for p in ps}
    where_a = {p: pid for pid, ps in after.items() for p in ps}
    jobs = _job_refs(project, ch)
    plan = load_yaml(plan_path(project, ch)) if plan_path(project, ch).exists() else {}
    planned = {pn["id"] for pg in plan.get("pages", []) for pn in pg.get("panels", [])}
    dropped, moved, added, blocked, stale = [], [], [], [], []
    for p, pid in where_b.items():
        if p not in where_a:
            refs = [j for (pg, pn), js in jobs.items() if pn == p and pg == pid for j in js]
            dropped.append({"panel": p, "page": pid, "jobs": refs, "planned": p in planned})
            if refs or p in planned:
                blocked.append(f"{pid}/{p} would disappear but is referenced by {refs or 'board.yaml'}")
        elif where_a[p] != pid:
            refs = [j for (pg, pn), js in jobs.items() if pn == p and pg == pid for j in js]
            moved.append({"panel": p, "from": pid, "to": where_a[p], "jobs": refs})
            stale += [f"{j}: targets {pid}/{p}, now on {where_a[p]} (re-request or update the target)" for j in refs]
    for p, pid in where_a.items():
        if p not in where_b:
            added.append(f"{pid}/{p}")
    res = {"alt": name, "pages": sorted(amap), "dropped": dropped, "moved": moved, "added": added,
           "blocked": blocked, "stale_jobs": stale, "archived": [], "promoted": False}
    if blocked and not force:
        return res
    if dry_run:
        return res
    log = load_yaml(logf) if logf.exists() else {"promotions": []}
    for pid in sorted(amap):
        cur = project.page_file(pid, ch)
        arch = alt_file(project, pid, f"pre-{name}", ch)
        n = 2
        while arch.exists():
            arch = alt_file(project, pid, f"pre-{name}-{n}", ch)
            n += 1
        shutil.copy2(cur, arch)
        shutil.copy2(alt_file(project, pid, name, ch), cur)
        alt_file(project, pid, name, ch).unlink()
        res["archived"].append(str(arch.relative_to(project.root)))
    log["promotions"].append({"alt": name, "at": _now(), "reason": reason, "pages": sorted(amap),
                              "archived": res["archived"], "moved": moved, "added": added,
                              "dropped": [d["panel"] for d in dropped], "forced": bool(blocked)})
    dump_yaml(logf, log)
    if plan:
        for d in dropped:
            plan.setdefault("retired", []).append({"id": d["panel"], "page": d["page"], "at": _now(),
                                                   "why": f"dropped by promoting alt {name}"})
        dump_yaml(plan_path(project, ch), plan)
        plan_res = __import__("mangakit.board", fromlist=["plan"]).plan(project, ch, write=True)
        res["plan_added"] = plan_res["added"]
    res["promoted"] = True
    return res
