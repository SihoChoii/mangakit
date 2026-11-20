"""Story records, validation, continuity timeline, reader knowledge, dependencies and impact.

Files (all optional except script.yaml; see docs/story-reference.md):
  story/premise.yaml     title, logline, premise, audience, length goals, tone
  story/canon.yaml       characters, props, locations (+ adjacency), facts the reader can learn,
                         initial continuity state
  story/beats.yaml       ordered beats: chapter, summary, location, present, shows, asserts,
                         reader {knows, suspects, conceals}, silent
  story/script.yaml      dialogue lines: id, beat, kind (speech|thought|caption|sfx), speaker, text, reveals
  story/continuity.yaml  events: id, beat, subject, attribute, value, from
  story/threads.yaml     setups and payoffs: id, setup {beat|line}, payoff {beat|line} | deferred

Authority: the script owns wording; beats own order and what the reader knows; continuity events
own when a fact changes; canon owns identities. Pages only reference beat and line ids.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path as FsPath

from .project import MangakitError, Project, load_yaml

KINDS = ("speech", "thought", "caption", "sfx")
SPEAKERLESS = ("caption", "sfx")
FILES = ("premise", "canon", "beats", "script", "continuity", "threads")


def _issue(sev, code, where, msg):
    return {"severity": sev, "code": code, "where": where, "message": msg}


class Story:
    def __init__(self, project: Project, overrides: dict | None = None):
        self.p = project
        d = project.root / "story"
        self.data = {}
        for name in FILES:
            f = d / f"{name}.yaml"
            self.data[name] = load_yaml(f) if f.exists() else {}
        for k, v in (overrides or {}).items():
            self.data[k] = v
        s = self.data["script"]
        b = self.data["beats"].get("beats") or s.get("beats") or []  # beats.yaml wins; legacy: in script
        self.beats = list(b)
        self.beat_ix = {x["id"]: i for i, x in enumerate(self.beats)}
        self.beat = {x["id"]: x for x in self.beats}
        self.lines = list(s.get("lines", []))
        self.line = {l["id"]: l for l in self.lines}
        c = self.data["canon"]
        self.characters = {x["id"]: x for x in c.get("characters", [])}
        self.props = {x["id"]: x for x in c.get("props", [])}
        self.locations = {x["id"]: x for x in c.get("locations", [])}
        self.facts = {x["id"]: x for x in c.get("facts", [])}
        self.initial = list(c.get("initial", []))
        self.events = list(self.data["continuity"].get("events", []))
        self.threads = list(self.data["threads"].get("threads", []))

    # ------------------------------------------------------------------ continuity
    def entities(self):
        return {**self.characters, **self.props, **self.locations}

    def _ev_key(self, e):
        return f"{e['subject']}.{e['attribute']}"

    def state_at(self, beat_id, after=True) -> dict:
        """{subject.attribute: value} after (or before) the given beat."""
        st = {f"{x['subject']}.{x['attribute']}": x["value"] for x in self.initial}
        lim = self.beat_ix[beat_id] + (1 if after else 0)
        for e in sorted(self.events, key=lambda e: self.beat_ix.get(e.get("beat"), 1e9)):
            if self.beat_ix.get(e.get("beat"), 1e9) < lim:
                st[self._ev_key(e)] = e["value"]
        return st

    def adjacent(self, a, b):
        if a == b:
            return True
        la, lb = self.locations.get(a, {}), self.locations.get(b, {})
        return b in la.get("adjacent", []) or a in lb.get("adjacent", [])

    def knowledge(self):
        """Per beat: cumulative {known, suspected, concealed} after that beat."""
        known, susp, conc = [], [], []
        out = {}
        for b in self.beats:
            r = b.get("reader", {}) or {}
            for f in r.get("knows", []):
                if f not in known:
                    known.append(f)
                if f in susp:
                    susp.remove(f)
                if f in conc:
                    conc.remove(f)
            for f in r.get("suspects", []):
                if f not in known and f not in susp:
                    susp.append(f)
                if f in conc:
                    conc.remove(f)
            for f in r.get("conceals", []):
                if f not in known and f not in conc:
                    conc.append(f)
            out[b["id"]] = {"known": list(known), "suspected": list(susp), "concealed": list(conc)}
        return out

    def first_known(self, fact):
        for b in self.beats:
            if fact in (b.get("reader", {}) or {}).get("knows", []):
                return b["id"]
        return None

    def _point_beat(self, ref):
        """'beat-id' | {'beat': id} | {'line': id} -> beat id."""
        if ref is None:
            return None
        if isinstance(ref, str):
            return ref if ref in self.beat else (self.line[ref]["beat"] if ref in self.line else None)
        if "line" in ref:
            return self.line.get(ref["line"], {}).get("beat")
        return ref.get("beat")

    # ------------------------------------------------------------------ checks
    def check(self, pages_info=None) -> list[dict]:
        I = []
        bx = self.beat_ix
        # beats
        seen = set()
        for b in self.beats:
            if b["id"] in seen:
                I.append(_issue("error", "duplicate-beat", b["id"], "beat id used twice"))
            seen.add(b["id"])
            for k in ("summary",):
                if not b.get(k):
                    I.append(_issue("warn", "beat-incomplete", b["id"], f"beat has no {k}"))
            loc = b.get("location")
            if loc and self.locations and loc not in self.locations:
                I.append(_issue("error", "unknown-location", b["id"], f"location {loc!r} not in canon"))
            for c in b.get("present", []):
                if c not in self.characters:
                    I.append(_issue("error", "unknown-character", b["id"], f"present {c!r} not in canon"))
            for x in b.get("shows", []):
                if x not in self.entities():
                    I.append(_issue("error", "unknown-entity", b["id"], f"shows {x!r} not in canon"))
            r = b.get("reader", {}) or {}
            for kk in ("knows", "suspects", "conceals"):
                for f in r.get(kk, []):
                    if self.facts and f not in self.facts:
                        I.append(_issue("error", "unknown-fact", b["id"], f"reader.{kk} {f!r} not in canon facts"))
        # knowledge order: once known, never concealed again
        known = set()
        for b in self.beats:
            r = b.get("reader", {}) or {}
            for f in r.get("conceals", []):
                if f in known:
                    I.append(_issue("error", "conceal-after-known", b["id"],
                                    f"{f} is concealed here but the reader already knows it"))
            known |= set(r.get("knows", []))
        for fid, f in self.facts.items():
            fk = self.first_known(fid)
            if f.get("reveal") and fk and fk != f["reveal"]:
                I.append(_issue("warn", "reveal-moved", fid,
                                f"canon says it is revealed at {f['reveal']}, beats make it known at {fk}"))
        # lines
        seen, last = set(), -1
        lines_by_beat = {}
        for l in self.lines:
            lid = l.get("id")
            if lid in seen:
                I.append(_issue("error", "duplicate-line", lid, "line id used twice"))
            seen.add(lid)
            kind = l.get("kind", "speech")
            if kind not in KINDS:
                I.append(_issue("error", "bad-kind", lid, f"kind {kind!r} not in {KINDS}"))
            b = l.get("beat")
            if b not in self.beat:
                I.append(_issue("error", "unknown-beat", lid, f"beat {b!r} does not exist"))
                continue
            lines_by_beat.setdefault(b, []).append(lid)
            if bx[b] < last:
                I.append(_issue("warn", "line-order", lid, f"listed after a line of a later beat (beat {b})"))
            last = max(last, bx[b])
            sp = l.get("speaker")
            if kind in SPEAKERLESS:
                if sp and sp not in self.characters:
                    I.append(_issue("error", "unknown-speaker", lid, f"speaker {sp!r} not in canon characters"))
            else:
                if not sp or sp not in self.characters:
                    I.append(_issue("error", "unknown-speaker", lid, f"{kind} line needs a canon speaker, got {sp!r}"))
                elif self.beat[b].get("present") and sp not in self.beat[b]["present"] and not l.get("offpanel"):
                    I.append(_issue("error", "speaker-absent", lid, f"{sp} speaks in {b} but is not present there"))
            if not str(l.get("text", "")).strip():
                I.append(_issue("error", "empty-line", lid, "no text"))
            # knowledge leaks: explicit reveals, or a concealed fact's keyword in the text
            k_before = self.knowledge()
            prev = self.beats[bx[b] - 1]["id"] if bx[b] > 0 else None
            known_before = set(k_before[prev]["known"]) if prev else set()
            known_after = set(k_before[b]["known"])
            for f in l.get("reveals", []):
                if f not in known_after:
                    I.append(_issue("error", "leak", lid, f"line reveals {f} but beat {b} does not make it known "
                                                          f"(first known at {self.first_known(f)})"))
            text = re.sub(r"[*_]", "", str(l.get("text", "")))
            for fid, f in self.facts.items():
                if fid in known_after or fid in l.get("reveals", []):
                    continue
                for kw in f.get("keywords", []):
                    if re.search(rf"\b{re.escape(kw)}\b", text, re.I):
                        I.append(_issue("error", "leak", lid,
                                        f"text says {kw!r}, a keyword of {fid}, which the reader may not know until "
                                        f"{self.first_known(fid) or 'never in these beats'}"))
                        break
        for b in self.beats:
            if b["id"] not in lines_by_beat and not b.get("silent"):
                I.append(_issue("warn", "beat-without-lines", b["id"], "no script lines (mark silent: true if intended)"))
        # continuity events
        ent = self.entities()
        for x in self.initial:
            if x["subject"] not in ent:
                I.append(_issue("error", "unknown-entity", "canon.initial", f"{x['subject']!r} not in canon"))
        by_key_beat = {}
        for e in self.events:
            eid = e.get("id", "?")
            if e.get("beat") not in self.beat:
                I.append(_issue("error", "unknown-beat", eid, f"event beat {e.get('beat')!r} does not exist"))
                continue
            if e.get("subject") not in ent:
                I.append(_issue("error", "unknown-entity", eid, f"subject {e.get('subject')!r} not in canon"))
                continue
            k = self._ev_key(e)
            prev = by_key_beat.setdefault((k, e["beat"]), e["value"])
            if prev != e["value"]:
                I.append(_issue("error", "contradiction", eid,
                                f"{k} set to both {prev!r} and {e['value']!r} at {e['beat']}"))
            before = self.state_at(e["beat"], after=False).get(k)
            if "from" in e and e["from"] != before:
                I.append(_issue("error", "contradiction", eid,
                                f"{k} changes from {e['from']!r}, but at {e['beat']} it is {before!r}"))
            beat = self.beat[e["beat"]]
            if e["attribute"] in ("holder", "owner"):
                giver, taker = before, e["value"]
                if taker not in self.characters:
                    I.append(_issue("error", "unknown-character", eid, f"{taker!r} is not a character"))
                pres = beat.get("present", [])
                for who, role in ((giver, "giver"), (taker, "receiver")):
                    if who in self.characters and pres and who not in pres:
                        I.append(_issue("error", "contradiction", eid,
                                        f"{role} {who} is not present at {e['beat']}"))
                st = self.state_at(e["beat"], after=False)
                lg, lt = st.get(f"{giver}.location"), st.get(f"{taker}.location")
                if lg and lt and not self.adjacent(lg, lt):
                    I.append(_issue("error", "contradiction", eid,
                                    f"{giver} ({lg}) and {taker} ({lt}) are not in reach of each other at {e['beat']}"))
            if e["attribute"] == "location" and e["value"] not in self.locations and self.locations:
                I.append(_issue("error", "unknown-location", eid, f"{e['value']!r} not in canon locations"))
        # presence vs location: two places at once
        for b in self.beats:
            loc = b.get("location")
            st = self.state_at(b["id"], after=False)
            st_after = self.state_at(b["id"], after=True)
            for c in b.get("present", []):
                cl = st.get(f"{c}.location")
                ca = st_after.get(f"{c}.location")  # a move at this beat (arrival) also places them here
                if loc and cl and not self.adjacent(loc, cl) and not (ca and self.adjacent(loc, ca)):
                    I.append(_issue("error", "two-places", b["id"],
                                    f"{c} is present at {loc} but continuity puts them at {cl}"))
            for a in b.get("asserts", []):
                k, _, v = a.partition("=")
                got = self.state_at(b["id"], after=True).get(k.strip())
                if got != v.strip():
                    I.append(_issue("error", "contradiction", b["id"],
                                    f"beat depicts {k.strip()} = {v.strip()}, continuity says {got!r}"))
        # threads: setup / payoff / sequence
        for t in self.threads:
            tid = t.get("id")
            sb, pb = self._point_beat(t.get("setup")), self._point_beat(t.get("payoff"))
            if t.get("setup") is not None and sb is None:
                I.append(_issue("error", "unknown-beat", tid, f"setup {t.get('setup')} does not resolve"))
            if t.get("payoff") is not None and pb is None:
                I.append(_issue("error", "unknown-beat", tid, f"payoff {t.get('payoff')} does not resolve"))
            if t.get("setup") is None and t.get("payoff") is not None:
                I.append(_issue("error", "payoff-without-setup", tid, "payoff has no setup"))
            if sb and t.get("payoff") is None:
                if t.get("deferred"):
                    I.append(_issue("info", "deferred-payoff", tid, f"open thread, paid off later: {t['deferred']}"))
                else:
                    I.append(_issue("warn", "setup-without-payoff", tid, "setup is never paid off (add payoff or deferred:)"))
            if sb and pb and bx[pb] <= bx[sb]:
                I.append(_issue("error", "payoff-before-setup", tid, f"payoff at {pb} does not come after setup at {sb}"))
            f = t.get("reveals")
            if f and sb:
                fk = self.first_known(f)
                if fk and bx[fk] < bx[sb]:
                    I.append(_issue("error", "reveal-before-setup", tid, f"{f} is known at {fk}, before its setup at {sb}"))
                if fk and pb and fk != pb:
                    I.append(_issue("warn", "reveal-not-at-payoff", tid, f"{f} becomes known at {fk}, payoff is {pb}"))
        # pages: beats exist, order, page-turn reveals
        if pages_info:
            I += self._check_pages(pages_info)
        return I

    def _check_pages(self, info) -> list[dict]:
        I = []
        bx = self.beat_ix
        last, last_page = -1, None
        for pg in info["pages"]:
            for pn in pg["panels"]:
                b = pn["beat"]
                if not b:
                    continue
                if b not in bx:
                    I.append(_issue("error", "unknown-beat", f"{pg['page']}/{pn['id']}", f"panel beat {b!r} not in beats"))
                    continue
                if bx[b] < last:
                    I.append(_issue("warn", "panel-order", f"{pg['page']}/{pn['id']}",
                                    f"beat {b} drawn after a later beat (on {last_page})"))
                last, last_page = max(last, bx[b]), pg["page"]
            for bl in pg["balloons"]:
                if bl["line"] not in self.line:
                    I.append(_issue("error", "unknown-line", f"{pg['page']}/{bl['panel']}", f"balloon line {bl['line']!r}"))
        # a reveal must not sit on the same spread as the beats that conceal it
        page_beats = {pg["page"]: [pn["beat"] for pn in pg["panels"] if pn["beat"]] for pg in info["pages"]}
        spread_of = {p: i for i, g in enumerate(info["spreads"]) for p in g}
        for fid in self.facts:
            fk = self.first_known(fid)
            if not fk:
                continue
            concealing = [b["id"] for b in self.beats if fid in (b.get("reader", {}) or {}).get("conceals", [])
                          and bx[b["id"]] < bx[fk]]
            rp = [p for p, bs in page_beats.items() if fk in bs]
            for r in rp:
                for p, bs in page_beats.items():
                    if p != r and spread_of.get(p) == spread_of.get(r) and set(bs) & set(concealing):
                        I.append(_issue("error", "reveal-on-facing-page", r,
                                        f"{fid} is revealed on {r}, which faces {p} where it is still concealed; "
                                        f"put a page turn between them"))
                    if p == r and set(bs) & set(concealing):
                        I.append(_issue("warn", "reveal-on-same-page", r,
                                        f"{fid} is concealed and revealed on the same page"))
        return I


# ---------------------------------------------------------------------- dependencies
def pages_info(project: Project, chapter=None) -> dict:
    """What every chapter page references: panels (beat), balloons (line), SFX text, art placements."""
    from .render import iter_layers, load_page, spread_groups
    pages = project.chapter_pages(chapter)
    out = []
    for pid in pages:
        try:
            page, src = load_page(project, pid, chapter=chapter)
        except Exception as e:  # a broken page is itself a finding
            out.append({"page": pid, "error": str(e), "panels": [], "balloons": [], "texts": [], "images": []})
            continue
        rec = {"page": pid, "source": str(src.relative_to(project.root)),
               "panels": [{"id": p.id, "beat": p.beat} for p in page.panels.values()],
               "balloons": [], "texts": [], "images": []}
        for L in iter_layers(page.layers):
            if L.kind == "balloon":
                o = L.data["outline"]
                bb = o.bbox() if callable(getattr(o, "bbox", None)) else o.bbox
                rec["balloons"].append({"line": L.data["dialogue"], "panel": L.data.get("panel"),
                                        "bbox": [round(v, 1) for v in bb]})
            elif L.kind == "text":
                rec["texts"].append({"text": L.data.get("text") or L.data.get("content", ""), "panel": L.data.get("panel")})
            elif L.kind == "image" and not L.data["drawing"].missing:
                d = L.data["drawing"]
                m = L.data.get("mask")
                rec["images"].append({"asset": d.asset_id, "version": d.version, "panel": L.data.get("panel"),
                                      "layer": L.name, "mask": f"{m.name}/{m.version}" if m else None})
            elif L.kind == "image":
                rec["images"].append({"asset": L.data["drawing"].asset_id, "version": None,
                                      "panel": L.data.get("panel"), "layer": L.name, "missing": True})
        out.append(rec)
    return {"pages": out, "spreads": spread_groups(project, pages, chapter=chapter)}


def _jobs(project):
    d = project.root / "art" / "jobs"
    out = []
    for j in sorted(d.glob("job-*/request.yaml")) if d.exists() else []:
        r = load_yaml(j)
        job = load_yaml(j.parent / "job.yaml")
        out.append({"job": r["job"], "asset": r["asset"], "page": r["target"]["page"], "panel": r["target"]["panel"],
                    "beat": r["target"].get("beat"), "status": job.get("status"), "accepted": job.get("accepted")})
    return out


def _manifests(project, pages):
    out = []
    b = project.root / "build"
    for f in sorted(b.rglob("*.manifest.json")) if b.exists() else []:
        try:
            m = json.loads(f.read_text())
        except Exception:
            continue
        if m.get("page") in pages:
            out.append({"file": str(f.relative_to(project.root)), "page": m["page"], "view": m.get("view"),
                        "art_only": bool((m.get("params") or {}).get("art_only")),
                        "region": (m.get("params") or {}).get("region"),
                        "lines": list((m.get("script", {}) or {}).get("lines_used", {}))})
    return out


def _region_hits(m, pages, line):
    """A detail render is stale for a line only if its region overlaps that line's balloon."""
    r = m.get("region")
    if not r:
        return True
    for bl in pages.get(m["page"], {}).get("balloons", []):
        if bl["line"] == line and bl.get("bbox"):
            x0, y0, x1, y1 = bl["bbox"]
            if x0 < r[2] and x1 > r[0] and y0 < r[3] and y1 > r[1]:
                return True
    return False


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"[*_]", "", str(s)).lower()).strip()


def deps(project: Project, story: Story | None = None, chapter=None) -> dict:
    st = story or Story(project)
    info = pages_info(project, chapter)
    jobs = _jobs(project)
    mans = _manifests(project, [p["page"] for p in info["pages"]])
    beats = {}
    for b in st.beats:
        beats[b["id"]] = {"panels": [], "lines": [l["id"] for l in st.lines if l.get("beat") == b["id"]],
                          "events": [e.get("id") for e in st.events if e.get("beat") == b["id"]]}
    lines = {l["id"]: {"balloons": [], "sfx_text": []} for l in st.lines}
    for pg in info["pages"]:
        for pn in pg["panels"]:
            if pn["beat"] in beats:
                beats[pn["beat"]]["panels"].append(f"{pg['page']}/{pn['id']}")
        for bl in pg["balloons"]:
            if bl["line"] in lines:
                lines[bl["line"]]["balloons"].append(f"{pg['page']}/{bl['panel']}")
        for t in pg["texts"]:
            for l in st.lines:
                if l.get("kind") == "sfx" and _norm(l["text"]) == _norm(t["text"]):
                    lines[l["id"]]["sfx_text"].append(f"{pg['page']}/{t['panel']}")
    return {"pages": info, "jobs": jobs, "manifests": mans, "beats": beats, "lines": lines}


# ---------------------------------------------------------------------- impact
def impact(project: Project, target: str, new_text=None, new_value=None, chapter=None) -> dict:
    """What goes stale if `target` (line id, beat id, event id, or subject.attribute) changes.

    Returns owner-grouped actions: rerun = must be redone; inspect = look, redo only if it conflicts."""
    st = Story(project)
    D = deps(project, st, chapter)
    pages = {p["page"]: p for p in D["pages"]["pages"]}
    out = {"target": target, "kind": None, "story": [], "board": [], "compose": [], "illustrate": [], "review": [],
           "hypothetical": None}

    def panel_art(panel_keys):
        res, seen = [], set()
        for key in sorted(set(panel_keys)):
            pg, pn = key.split("/")
            for im in pages.get(pg, {}).get("images", []):
                if im["panel"] == pn and (key, im["asset"], im["version"]) not in seen:
                    seen.add((key, im["asset"], im["version"]))
                    res.append((key, im))
        return res

    def jobs_for(panel_keys):
        ks = set(panel_keys)
        return [j for j in D["jobs"] if f"{j['page']}/{j['panel']}" in ks and j["status"] != "rejected"]

    def proofs(page_ids, line=None):
        """Stale renders, one entry per page: every manifest of the page (a line change spares
        art-only renders, which carry no lettering)."""
        by = {}
        for m in D["manifests"]:
            if m["page"] in page_ids and (line is None or (line in m["lines"] and not m["art_only"]
                                                            and _region_hits(m, pages, line))):
                by.setdefault(m["page"], []).append(m["file"].replace(".manifest.json", ""))
        return [f"{pg}: {len(fs)} render(s) - {', '.join(sorted(fs))}" for pg, fs in sorted(by.items())]

    if target in st.line:
        out["kind"] = "line"
        l = st.line[target]
        dl = D["lines"][target]
        out["story"].append({"rerun": f"edit {target} in story/script.yaml (the script owns the wording)"})
        for t in st.threads:
            if (isinstance(t.get("setup"), dict) and t["setup"].get("line") == target) or \
                    (isinstance(t.get("payoff"), dict) and t["payoff"].get("line") == target) or t.get("setup") == target:
                out["story"].append({"inspect": f"thread {t['id']} is set up or paid off by this line; keep it intact"})
        for f in l.get("reveals", []):
            out["story"].append({"inspect": f"this line reveals {f}; the beat sheet's reader knowledge depends on it"})
        for b in dl["balloons"]:
            out["compose"].append({"rerun": f"reflow balloon {target} on {b}, then render and inspect the page"})
        for b in dl["sfx_text"]:
            out["compose"].append({"rerun": f"re-letter SFX {target} on {b}"})
        if not dl["balloons"] and not dl["sfx_text"]:
            out["compose"].append({"inspect": f"{target} is not lettered on any page"})
        panels = dl["balloons"] + dl["sfx_text"]
        for key, im in panel_art(panels):
            out["illustrate"].append({"inspect": f"{im['asset']}@{im['version']} in {key}: reopen only if its acting "
                                                 f"or composition conflicts with the new text"})
        pids = {k.split("/")[0] for k in panels}
        for f in proofs(pids, target):
            out["review"].append({"rerun": f"re-render and re-read {f}"})
        if new_text is not None:
            out["hypothetical"] = _try_line(project, st, target, new_text, pids, chapter)
    elif target in st.beat:
        out["kind"] = "beat"
        db = D["beats"][target]
        out["story"].append({"rerun": f"edit beat {target} in story/beats.yaml; re-run story check"})
        for lid in db["lines"]:
            out["story"].append({"inspect": f"line {lid} belongs to this beat"})
        for eid in db["events"]:
            out["story"].append({"inspect": f"continuity event {eid} happens at this beat"})
        later = [b["id"] for b in st.beats[st.beat_ix[target] + 1:]]
        if later:
            out["story"].append({"inspect": f"reader knowledge after later beats: {', '.join(later)}"})
        for key in db["panels"]:
            out["board"].append({"inspect": f"panel {key} draws this beat"})
        for key, im in panel_art(db["panels"]):
            out["illustrate"].append({"inspect": f"{im['asset']}@{im['version']} in {key}"})
        for j in jobs_for(db["panels"]):
            out["illustrate"].append({"inspect": f"{j['job']} ({j['status']}) was requested from this beat's continuity"})
        for lid in db["lines"]:
            for b in D["lines"][lid]["balloons"]:
                out["compose"].append({"inspect": f"balloon {lid} on {b}"})
        for f in proofs({k.split("/")[0] for k in db["panels"]}):
            out["review"].append({"rerun": f"after the edits, re-render and re-read {f}"})
    else:
        evs = [e for e in st.events if e.get("id") == target]
        key = evs[0] and f"{evs[0]['subject']}.{evs[0]['attribute']}" if evs else target
        evs = evs or [e for e in st.events if f"{e['subject']}.{e['attribute']}" == key]
        if not evs and key not in {f"{x['subject']}.{x['attribute']}" for x in st.initial}:
            raise MangakitError(f"{target!r} is not a line, beat, event id or subject.attribute")
        out["kind"] = "fact"
        subj, attr = key.split(".", 1)
        ordered = sorted(evs, key=lambda e: st.beat_ix[e["beat"]])
        first = st.beat_ix[ordered[0]["beat"]] if ordered else 0
        # every later event on the same fact ends the interval of the first one
        allk = sorted([e for e in st.events if f"{e['subject']}.{e['attribute']}" == key],
                      key=lambda e: st.beat_ix[e["beat"]])
        nxt = [st.beat_ix[e["beat"]] for e in allk if st.beat_ix[e["beat"]] > first]
        end = nxt[0] if (nxt and target != key) else len(st.beats)
        span = [b["id"] for b in st.beats[first:end]]
        old = ordered[0]["value"] if ordered else None
        out["fact"] = {"key": key, "events": [e["id"] for e in ordered], "value": old, "in_effect": span}
        for e in ordered:
            out["story"].append({"rerun": f"edit continuity event {e['id']} ({key} -> {e['value']}) at {e['beat']}"})
            out["story"].append({"rerun": f"edit beat {e['beat']} (what happens) to match"})
        names = {subj, old} - {None}
        if target == key:  # the whole fact: every beat, every value it ever takes
            span = [b["id"] for b in st.beats]
            out["fact"]["in_effect"] = span
            names |= {e["value"] for e in allk} | {x["value"] for x in st.initial
                                                    if f"{x['subject']}.{x['attribute']}" == key}
        dep_beats = [b for b in span if names & (set(st.beat[b].get("present", [])) | set(st.beat[b].get("shows", [])))
                     or any(a.split("=")[0].strip() == key for a in st.beat[b].get("asserts", []))]
        for b in dep_beats:
            for l in st.lines:
                if l["beat"] == b and l.get("speaker") == old:
                    out["story"].append({"rerun": f"{l['id']} is spoken by {old} in {b}: change the speaker or the line"})
        for fid, f in st.facts.items():
            if names & set(f.get("about", [])):
                out["story"].append({"inspect": f"fact {fid} ({f.get('statement', '')}) is about {', '.join(sorted(names & set(f['about'])))}"})
        for t in st.threads:
            if t.get("reveals") in [fid for fid, f in st.facts.items() if names & set(f.get("about", []))]:
                out["story"].append({"inspect": f"thread {t['id']} pays off that fact"})
        panels = [k for b in dep_beats for k in D["beats"][b]["panels"]]
        for b in dep_beats:
            for k in D["beats"][b]["panels"]:
                out["board"].append({"inspect": f"panel {k} ({b}) shows {', '.join(sorted(names & (set(st.beat[b].get('present', [])) | set(st.beat[b].get('shows', [])))) or key)}"})
        for k, im in panel_art(panels):
            out["illustrate"].append({"inspect": f"{im['asset']}@{im['version'] or 'MISSING'} in {k} may depict "
                                                 f"{old or key}; schedule an art job only if it does"})
        for j in jobs_for(panels):
            out["illustrate"].append({"inspect": f"{j['job']} ({j['status']}) request carries the old continuity; "
                                                 f"a new request is needed if the panel is redrawn"})
        for b in dep_beats:
            for lid in D["beats"][b]["lines"]:
                for bl in D["lines"][lid]["balloons"]:
                    if st.line[lid].get("speaker") == old:
                        out["compose"].append({"inspect": f"balloon {lid} on {bl}: tail and speaker may change"})
        for f in proofs({k.split("/")[0] for k in panels}):
            out["review"].append({"rerun": f"after the edits, re-render and re-read {f}"})
        out["review"].append({"rerun": "re-read the chapter spreads: can a reader still identify the transfer and its timing?"})
        if new_value is not None and ordered:
            data = copy.deepcopy(st.data)
            for e in data["continuity"]["events"]:
                if e.get("id") == ordered[0]["id"]:
                    e["value"] = new_value
            out["hypothetical"] = _diff_checks(project, st, Story(project, overrides=data), chapter,
                                               f"{ordered[0]['id']}: {key} -> {new_value}")
    return out


def _diff_checks(project, before: Story, after: Story, chapter, label):
    info = pages_info(project, chapter)
    a = {(i["code"], i["where"], i["message"]) for i in before.check(info)}
    b = after.check(info)
    new = [i for i in b if (i["code"], i["where"], i["message"]) not in a and i["severity"] != "info"]
    return {"change": label, "new_issues": new}


def _try_line(project, st: Story, lid, text, pids, chapter):
    """Re-run story checks and the page checks of every page that letters the line, with new text."""
    from .checks import run_checks
    from .render import load_page
    data = copy.deepcopy(st.data)
    for l in data["script"]["lines"]:
        if l["id"] == lid:
            l["text"] = text
    res = _diff_checks(project, st, Story(project, overrides=data), chapter, f"{lid} text -> {text!r}")
    res["pages"] = {}
    for pid in sorted(pids):
        page, _ = load_page(project, pid, chapter=chapter, script_data=data["script"])
        mine = [i for i in run_checks(page) if lid in i["where"] or lid in i["message"]]
        res["pages"][pid] = mine or "balloon fits; no page issues for this line"
    return res


# ---------------------------------------------------------------------- at a glance
def glance(project: Project, chapter=None, out=None) -> FsPath:
    st = Story(project)
    D = deps(project, st, chapter)
    K = st.knowledge()
    pr = st.data["premise"]
    L = [f"# {pr.get('title', project.cfg.get('title', 'Story'))} - story at a glance", ""]
    if pr.get("logline"):
        L += [f"> {pr['logline']}", ""]
    def _fmt(v):
        return ", ".join(f"{k} {x}" for k, x in v.items()) if isinstance(v, dict) else v
    meta = [f"{k}: {_fmt(pr[k])}" for k in ("audience", "length", "tone") if pr.get(k)]
    if meta:
        L += [" | ".join(str(m) for m in meta), ""]
    spreads = D["pages"]["spreads"]
    L += ["Spreads (reading order): " + "  /  ".join("[" + " ".join(g) + "]" for g in spreads), ""]
    spread_of = {pg: i for i, g in enumerate(spreads) for pg in g}
    last_spread = None
    for b in st.beats:
        bid = b["id"]
        pg = [k.split("/")[0] for k in D["beats"][bid]["panels"]]
        sp = spread_of.get(pg[0]) if pg else None
        if sp is not None and last_spread is not None and sp != last_spread:
            L += [f"---- page turn -> spread [{' '.join(spreads[sp])}] ----", ""]
        last_spread = sp if sp is not None else last_spread
        L.append(f"## {st.beat_ix[bid] + 1}. {bid}  (ch {b.get('chapter', '?')}; "
                 f"{', '.join(D['beats'][bid]['panels']) or 'not drawn yet'})")
        L.append(f"{b.get('summary', '')}")
        where = []
        if b.get("location"):
            where.append(f"at **{b['location']}**")
        if b.get("present"):
            where.append("with " + ", ".join(b["present"]))
        if where:
            L.append("*" + " ".join(where) + "*")
        L.append("")
        for l in st.lines:
            if l.get("beat") == bid:
                who = f" **{l['speaker']}**" if l.get("speaker") else ""
                L.append(f"- `{l['id']}` {l.get('kind', 'speech')}{who}: {l['text']}")
        for e in st.events:
            if e.get("beat") == bid:
                L.append(f"- continuity `{e['id']}`: {e['subject']}.{e['attribute']} -> **{e['value']}**")
        for t in st.threads:
            if st._point_beat(t.get("setup")) == bid:
                L.append(f"- setup `{t['id']}`: {t.get('description', '')}")
            if st._point_beat(t.get("payoff")) == bid:
                L.append(f"- payoff `{t['id']}`: {t.get('description', '')}")
        k = K[bid]
        r = b.get("reader", {}) or {}
        new = [f"+knows {f}" for f in r.get("knows", [])] + [f"+suspects {f}" for f in r.get("suspects", [])] + \
              [f"+conceals {f}" for f in r.get("conceals", [])]
        if new:
            L.append(f"- this beat: {'; '.join(new)}")
        state = st.state_at(bid)
        L.append("- state after: " + ", ".join(f"{k_}={v}" for k_, v in state.items()))
        L.append(f"- reader **knows** {', '.join(k['known']) or '-'}; **suspects** {', '.join(k['suspected']) or '-'}; "
                 f"**concealed** {', '.join(k['concealed']) or '-'}")
        L.append("")
    open_t = [t for t in st.threads if t.get("deferred")]
    if open_t:
        L += ["## Open threads", ""] + [f"- `{t['id']}` -> {t['deferred']}: {t.get('description', '')}" for t in open_t] + [""]
    issues = st.check(D["pages"])
    L += ["## story check", ""] + ([f"- [{i['severity'].upper()}] {i['code']} {i['where']}: {i['message']}"
                                    for i in issues] or ["- OK (0 issues)"])
    o = FsPath(out) if out else project.root / "build" / "story" / "glance.md"
    o.parent.mkdir(parents=True, exist_ok=True)
    o.write_text("\n".join(L) + "\n")
    return o
