"""Art requests, image adapters, candidate storage, acceptance review, pilot metrics.

Image generation never runs inside rendering. It happens only through an adapter, driven by
`mangakit job call` / `mangakit job collect`, and every call is logged on its job.

Flow:  job request -> (job call -> host/backend -> job collect)* -> job review -> landmarks ->
       render --pin -> job verdict -> job select (guarded) -> compose rebuilds masks/landmark use.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path as FsPath

from PIL import Image, ImageDraw, ImageFont

from .assets import Registry
from .project import MangakitError, Project, dump_yaml, load_yaml, sha256_file
from .references import RefRegistry

REASONS = ("new-shot", "correction", "extension", "design-change", "continuity", "lettering", "mask")
ART_FREE_REASONS = ("lettering", "mask")  # should never need art calls (spec section 7 metric)

DEFAULT_ACCEPTANCE = [
    "Identity and costume match the referenced design versions (no invented details).",
    "Acting reads at reading size: the intended action/contact is unmistakable.",
    "Hands: correct finger count, believable grip, the contact point is clear.",
    "Framing matches the shot guide crop; important landmarks land near their marked positions.",
    "Art extends past the panel border far enough to cover every breakout region (see beyond_border).",
    "Reserved lettering areas stay free of important detail.",
    "Screen direction continues from the previous shot; nothing concealed is revealed.",
    "Style matches the style exemplar: monochrome ink, line weight, tone density.",
    "No text, labels, panel borders, signatures or watermarks drawn into the image.",
]


def _now():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _git_rev(root: FsPath):
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
        return r.stdout.strip() or None
    except FileNotFoundError:
        return None


def _font(project, size):
    try:
        return ImageFont.truetype(str(project.font_path("caption")), size)
    except Exception:
        return ImageFont.load_default()


class Jobs:
    def __init__(self, project: Project):
        self.p = project
        self.reg = Registry(project)
        self.dir = project.root / "art" / "jobs"

    def path(self, jid):
        d = self.dir / jid
        if not (d / "job.yaml").exists():
            raise MangakitError(f"unknown job {jid}")
        return d

    def load(self, jid):
        return load_yaml(self.path(jid) / "job.yaml")

    def save(self, jid, job):
        dump_yaml(self.dir / jid / "job.yaml", job)

    # ------------------------------------------------------------------ request
    def request(self, page_ref, panel, asset, refs=(), reason="new-shot", adapter="host", prev_direction="",
                transition="", conceal=(), beyond_border="", acceptance=(), notes="", edit_of=None,
                instruction="", style_words="", aspect=None, chapter=None, paintover_file=None, designs=(),
                auto_style=True):
        from .render import load_page, render_guide, render_page
        if reason not in REASONS:
            raise MangakitError(f"reason must be one of {REASONS}")
        page, src = load_page(self.p, page_ref, chapter=chapter)
        if panel not in page.panels:
            raise MangakitError(f"no panel {panel} on {page.id}; have {list(page.panels)}")
        P = page.panels[panel]
        cur = self.reg.load(asset).get("selected") if self.reg.exists(asset) else None
        jid = self.reg.new_job(asset, notes)
        d = self.dir / jid
        pack = d / "pack"
        (pack / "refs").mkdir(parents=True)
        guide_png = render_guide(page, panel, pack / "guide.png")
        guide = json.loads((pack / "guide.json").read_text())
        da = guide["draw_area_page_units"]
        render_page(page, "detail", pack / "context-crop.png", dpi=150, region=da, manifest=False, art_only=True)
        has_rough = rough_crop(page, panel, da, pack / "rough-crop.png") is not None
        rr = RefRegistry(self.p)
        from .design import Direction, design_for
        # designs by canon id: the costume in effect at this beat picks the variant (story owns when)
        specs = [design_for(self.p, x.split("#")[0], beat=P.beat, view=x.split("#", 1)[1] if "#" in x else None)
                 for x in designs] + list(refs)
        # art direction: the revision effective for this beat; its brief cards are pinned unless already given
        D = Direction(self.p)
        _b = beat_rec = page.script.beats.get(P.beat or "", {})
        sr = D.brief(D.effective(chapter or self.p.chapter, P.beat),
                     present=list(_b.get("present", [])) + list(_b.get("shows", [])) if _b else None) \
            if D and auto_style else None
        if sr:
            have = {rr.resolve(x)["id"] for x in specs}
            for c in sr["cards"]:
                if rr.resolve(c["spec"])["id"] not in have:
                    specs.append(c["spec"])
        pinned = []
        for spec in specs:
            r = rr.resolve(spec)
            tag = f"{r['id']}@{r['version']}" + (f"-{r['view']['name']}" if r.get("view") else "")
            dst = pack / "refs" / f"{tag}{FsPath(r['file']).suffix}"
            shutil.copy2(r["file"], dst)
            r["pack_file"] = os.path.relpath(dst, d)
            if sr and any(c["spec"] == spec for c in sr["cards"]):
                r["style_rule"] = next(c["rule"] for c in sr["cards"] if c["spec"] == spec)
            pinned.append(r)
        cards = [r for r in pinned if r.get("style_rule")]
        if len(cards) > 1:  # one montage = one reference slot (hosts cap the number of images)
            from PIL import Image as _Im
            ims = [_Im.open(d / r["pack_file"]).convert("L") for r in cards]
            H = 400
            ims = [im.resize((max(1, round(im.width * H / im.height)), H)) for im in ims]
            mont = _Im.new("L", (sum(i.width for i in ims) + 24 * (len(ims) - 1), H), 255)
            x = 0
            for im in ims:
                mont.paste(im, (x, 0))
                x += im.width + 24
            mf = pack / "refs" / f"style-cards@{sr['revision']}.png"
            mont.save(mf)
            merged = {"id": f"style-cards", "version": sr["revision"], "kind": "style", "style_rule": "+".join(
                dict.fromkeys(r["style_rule"] for r in cards)), "cards": [r["spec"] for r in cards], "sha256": sha256_file(mf),
                "pack_file": os.path.relpath(mf, d), "variant": "",
                "note": "style cards left to right: " + "; ".join(f"{r['style_rule']} ({r.get('note', '')})" for r in cards)}
            pinned = [r for r in pinned if not r.get("style_rule")] + [merged]
        if sr:
            style_words = " ".join(x for x in [style_words, f"Art direction {sr['revision']}: " + "; ".join(sr["rules"]) + "."]
                                   if x)
        beat = page.script.beats.get(P.beat or "", {})
        know = _story_context(self.p, P.beat, beat)
        idx = list(page.panels).index(panel)
        nxt = list(page.panels.values())[idx + 1] if idx + 1 < len(page.panels) else None
        lines = [{"id": lid, "speaker": page.script.lines[lid].get("speaker"), "text": page.script.lines[lid].get("text")}
                 for lid in page.script.lines_for_beat(P.beat or "")]
        w = da[2] - da[0]
        h = da[3] - da[1]
        auto = []
        for b in P.breakouts:
            x0, y0, x1, y1 = b.path.bbox()
            auto.append(f"{b.name}: the drawing must continue past the panel border and stay clean in the region "
                        f"x {100 * (x0 - da[0]) / w:.0f}-{100 * (x1 - da[0]) / w:.0f}%, "
                        f"y {100 * (y0 - da[1]) / h:.0f}-{100 * (y1 - da[1]) / h:.0f}% of the image "
                        f"(page units {[round(v) for v in (x0, y0, x1, y1)]}; it will be cut out over panel(s) {b.over})")
        beyond_border = "; ".join(([beyond_border] if beyond_border else []) + auto) or "no breakouts"
        w = da[2] - da[0]
        h = da[3] - da[1]
        if aspect is None:
            ratios = {"1:1": 1, "4:3": 4 / 3, "3:4": 3 / 4, "16:9": 16 / 9, "9:16": 9 / 16}
            aspect = min(ratios, key=lambda k: abs(ratios[k] - w / h))
        edit = None
        if edit_of:
            ver, v = self.reg.version(asset, edit_of)
            edit = {"asset": asset, "version": ver, "sha256": v["sha256"],
                    "file": str(self.reg.dir / asset / v["file"]), "instruction": instruction}
            shutil.copy2(edit["file"], pack / f"edit-source@{ver}{FsPath(edit['file']).suffix}")
            edit["pack_file"] = f"pack/edit-source@{ver}{FsPath(edit['file']).suffix}"
            if paintover_file:  # agent-made guide (moved parts, rough marks) sent instead of the raw source
                pf = FsPath(paintover_file)
                shutil.copy2(pf, pack / f"paintover{pf.suffix.lower()}")
                edit["paintover"] = {"pack_file": f"pack/paintover{pf.suffix.lower()}", "sha256": sha256_file(pf)}
                edit["source_pack_file"] = edit["pack_file"]
                edit["pack_file"] = edit["paintover"]["pack_file"]
        req = {
            "job": jid, "asset": asset, "reason": reason, "adapter": adapter,
            "color": self.p.cfg.get("color", "bw"),
            "target": {"page": page.id, "panel": panel, "beat": P.beat, "chapter": str(chapter or self.p.chapter),
                       "page_source": os.path.relpath(src, self.p.root), "page_sha256": sha256_file(src),
                       "git": _git_rev(self.p.root), "reading_direction": page.direction},
            "base_selection": cur,
            "shot_guide": {"png": "pack/guide.png", "json": "pack/guide.json", "rough_crop": "pack/rough-crop.png",
                           "context_crop": "pack/context-crop.png", "rough_is_placeholder": not has_rough,
                           "draw_area_page_units": da, "aspect_ratio": aspect,
                           "min_source_px_for_print": guide["min_source_px_for_print"],
                           "landmarks": guide["landmarks"], "reserved_lettering": guide["reserved_lettering"],
                           "focal": guide.get("focal", []), "sightlines": guide.get("sightlines", []),
                           "board_note": guide.get("board_note")},
            "references": pinned,
            "continuity": {"beat_summary": beat.get("summary", ""), "reader_knows_after": know["known"],
                           "conceal": list(conceal) + [c for c in know["concealed"] if c not in conceal],
                           "state": know["state"],
                           "previous_screen_direction": prev_direction,
                           "transition_to_next": transition or (f"leads into panel '{nxt.id}' ({nxt.beat})" if nxt else ""),
                           "dialogue_in_panel": lines},
            "beyond_border": beyond_border,
            "edit_of": edit,
            "style": style_words,
            "style_revision": sr,
            "acceptance": list(acceptance) or DEFAULT_ACCEPTANCE,
            "notes": notes,
            "created": _now(),
        }
        dump_yaml(d / "request.yaml", req)
        (d / "prompt.md").write_text(render_prompt(req))
        job = self.load(jid)
        job.update({"kind": "art-request", "reason": reason, "adapter": adapter, "page": page.id, "panel": panel,
                    "request": "request.yaml", "calls": [], "verdicts": {}, "status": "open"})
        self.save(jid, job)
        get_adapter(adapter, self.p).prepare(self, jid, req)
        return jid

    # ------------------------------------------------------------------ calls
    def call(self, jid, note=""):
        job = self.load(jid)
        req = load_yaml(self.path(jid) / "request.yaml")
        ad = get_adapter(job.get("adapter", "host"), self.p)
        entry = {"n": len(job["calls"]) + 1, "adapter": ad.name, "mode": "edit" if req.get("edit_of") else "generate",
                 "at": _now(), "status": "pending", "outputs": [], "note": note}
        job["calls"].append(entry)
        self.save(jid, job)
        out = ad.submit(self, jid, req, entry["n"])
        if out:  # synchronous backends
            self.collect(jid, out, call_n=entry["n"])
        return entry["n"], ad.instructions(self, jid, req, entry["n"])

    def collect(self, jid, files, call_n=None, note=""):
        job = self.load(jid)
        d = self.path(jid)
        cdir = d / "candidates"
        cdir.mkdir(exist_ok=True)
        if not job.get("calls"):
            raise MangakitError(f"{jid}: no call logged; run `mangakit job call {jid}` before collecting")
        call = next((c for c in job["calls"] if c["n"] == call_n), None) if call_n else \
            next((c for c in reversed(job["calls"]) if c["status"] == "pending"), job["calls"][-1])
        vers = []
        for f in files:
            f = FsPath(f)
            ver = self.reg.add_version(job["asset"], f, job=jid, note=note or f"call {call['n']} of {jid}")
            keep = cdir / f"{ver}-call{call['n']}{f.suffix.lower()}"
            shutil.copy2(f, keep)
            vers.append(ver)
        job = self.load(jid)  # add_version appended candidates
        for c in job["calls"]:
            if c["n"] == call["n"]:
                c["outputs"] += vers
                c["status"] = "done" if vers else "empty"
        job["status"] = "delivered"
        self.save(jid, job)
        return vers

    def withdraw(self, jid, note):
        """Close a request that will not be called (superseded brief); its record stays."""
        job = self.load(jid)
        if job.get("status") == "accepted":
            raise MangakitError(f"{jid} is accepted; select a different version instead")
        if not note:
            raise MangakitError("say why the request is withdrawn (--note)")
        job["status"] = "withdrawn"
        job["withdrawn"] = {"at": _now(), "note": note}
        self.save(jid, job)
        return job

    # ------------------------------------------------------------------ review / select
    def verdict(self, jid, ver, ok, note=""):
        job = self.load(jid)
        job.setdefault("verdicts", {})[ver] = {"pass": bool(ok), "note": note, "at": _now()}
        outs = [v for c in job.get("calls", []) for v in c["outputs"]]
        if job.get("status") != "accepted" and outs and all(v in job["verdicts"] for v in outs):
            job["status"] = "reviewed" if any(job["verdicts"][v]["pass"] for v in outs) else "rejected"
        self.save(jid, job)

    def select(self, jid, ver, force=False):
        job = self.load(jid)
        req = load_yaml(self.path(jid) / "request.yaml")
        v = job.get("verdicts", {}).get(ver)
        if not force and not (v and v["pass"]):
            raise MangakitError(f"{ver} has no passing verdict on {jid}; run `mangakit job verdict {jid} {ver} --pass`")
        base = req.get("base_selection")
        stale = self.reg.select(job["asset"], ver, if_current=base or "")
        rec = self.reg.load(job["asset"])
        prev_lm = sorted(rec.get("landmarks", {}).get(base or "", {}))
        have_lm = sorted(rec.get("landmarks", {}).get(ver, {}))
        job["status"] = "accepted"
        job["accepted"] = ver
        job["accepted_at"] = _now()
        self.save(jid, job)
        missing = [n for n in prev_lm if n not in have_lm]
        return stale, missing

    def _placement_inverse(self, req, asset, ver):
        """page -> source px transform of `asset@ver` as the page source places it, or None."""
        from .render import iter_layers, load_page
        try:
            page, _ = load_page(self.p, req["target"]["page"], pins={asset: ver})
        except Exception:
            return None
        for L in iter_layers(page.layers):
            if L.kind == "image" and L.data.get("panel") == req["target"]["panel"] \
                    and L.data["drawing"].asset_id == asset and not L.data["drawing"].missing:
                return L.data["transform"].inverse()
        return None

    def review_sheet(self, jid, page_trials: dict | None = None, out=None, also=()) -> FsPath:
        """Contact sheet: shot guide + rough crop + every candidate (+ trial placements if given).
        `also`: more job ids (e.g. the corrections of the same panel) whose candidates join the sheet."""
        job = self.load(jid)
        d = self.path(jid)
        req = load_yaml(d / "request.yaml")
        tiles = [("shot guide", d / "pack" / "guide.png"), ("rough crop", d / "pack" / "rough-crop.png")]
        for k in [jid, *also]:
            jk, dk = self.load(k), self.path(k)
            rk = load_yaml(dk / "request.yaml")
            if rk.get("edit_of"):
                e = rk["edit_of"]
                tiles.append((f"{k}: {'paint-over from' if e.get('paintover') else 'edit of'} {e['version']}",
                              dk / e["pack_file"]))
            for c in jk.get("calls", []):
                for ver in c["outputs"]:
                    f = self.reg.file(jk["asset"], ver)
                    v = jk.get("verdicts", {}).get(ver)
                    tag = "" if not v else ("  PASS" if v["pass"] else "  FAIL")
                    tiles.append((f"{ver} ({k} call {c['n']}){tag}", f))
        for label, f in (page_trials or {}).items():
            tiles.append((label, FsPath(f)))
        H = 520
        guide = json.loads((d / "pack" / "guide.json").read_text())
        da = guide["draw_area_page_units"]
        from .geometry import Path as GPath
        panel_rings = GPath.from_svg(guide["panel_path"]).rings()
        brk = [GPath.from_svg(b["path"]).bbox() for b in guide["breakouts"]]
        rec = self.reg.load(job["asset"])
        ims = []
        for label, f in tiles:
            im = Image.open(f).convert("RGB")
            sx, sy = im.width / (da[2] - da[0]), im.height / (da[3] - da[1])
            k = H / im.height
            im = im.resize((max(1, int(im.width * k)), H), Image.LANCZOS)
            ver = label.split(" ")[0]
            if ver in rec["versions"] or label == "rough crop":
                # overlay in this image's own pixels: where the panel border, breakout regions and layout
                # landmarks fall. Candidates with landmarks use their real placement from the page source
                # (loaded with this version pinned); otherwise assume the image fills the draw area.
                M = None
                if ver in rec["versions"] and rec.get("landmarks", {}).get(ver):
                    M = self._placement_inverse(req, job["asset"], ver)
                if M is None:
                    P = lambda x, y, sx=sx, sy=sy, k=k: ((x - da[0]) * sx * k, (y - da[1]) * sy * k)
                    how = "fill"
                else:
                    P = lambda x, y, M=M, k=k: (lambda q: (q[0] * k, q[1] * k))(M.apply((x, y)))
                    how = "placed"
                ov = ImageDraw.Draw(im)
                for ring in panel_rings:
                    ov.line([P(*p) for p in ring] + [P(*ring[0])], fill=(0, 160, 255), width=2)
                for x0, y0, x1, y1 in brk:
                    ov.polygon([P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)], outline=(255, 60, 60))
                for lm in guide["landmarks"]:
                    x, y = P(*lm["page_xy"])
                    ov.line([(x - 9, y), (x + 9, y)], fill=(230, 0, 0), width=2)
                    ov.line([(x, y - 9), (x, y + 9)], fill=(230, 0, 0), width=2)
                for nm, lm in rec.get("landmarks", {}).get(ver, {}).items():
                    x, y = lm["xy"][0] * k, lm["xy"][1] * k
                    ov.ellipse([x - 6, y - 6, x + 6, y + 6], outline=(0, 200, 0), width=3)
                if ver in rec["versions"]:
                    label = f"{label}  [{how}]"
            ims.append((label, im))
        cols = 3
        cw = max(im.width for _, im in ims)
        rows = (len(ims) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (cw + 20) + 20, rows * (H + 60) + 70), "#3a3a3a")
        dr = ImageDraw.Draw(sheet)
        f = _font(self.p, 24)
        dr.text((20, 18), f"{jid}  {job['asset']}  {req['target']['page']}/{req['target']['panel']}  reason={req['reason']}",
                fill="white", font=f)
        for i, (label, im) in enumerate(ims):
            r, c = divmod(i, cols)
            x, y = 20 + c * (cw + 20), 60 + r * (H + 60)
            sheet.paste(im, (x, y + 34))
            dr.text((x, y + 4), label, fill="#ffe680", font=f)
        dr.text((20, sheet.height - 34), "overlay: blue = panel border, red = breakout regions, red + = layout landmark targets, "
                "green o = landmarks set on that version; [placed] = real placement from page source, [fill] = assumed to fill the draw area", fill="#cccccc", font=_font(self.p, 18))
        o = FsPath(out) if out else d / "review.png"
        sheet.save(o)
        return o


def paintover(src_file, maps, out, size=None, fill=255, cut=None, background=None):
    """Paint-over guide for a correction the backend cannot make from words alone.

    Moves the drawing (or only the `cut` polygon, in source px) with a 2-point similarity so two
    source points land on two target points. With `cut`, the rest of the drawing stays where it was,
    the vacated area is left as paper (or `background`, an image the agent prepared, e.g. a
    re-tiled backdrop), and the moved part is pasted on top.
    maps: [((sx, sy), (tx, ty)), ((sx2, sy2), (tx2, ty2))] in source px -> output px."""
    import cmath
    import math
    from .masktools import poly_mask
    (s1, t1), (s2, t2) = [(complex(*a), complex(*b)) for a, b in maps]
    a = (t2 - t1) / (s2 - s1)
    b = t1 - a * s1
    ia, ib = 1 / a, -b / a  # output -> source
    im = Image.open(src_file).convert("L")
    size = size or im.size
    data = (ia.real, -ia.imag, ib.real, ia.imag, ia.real, ib.imag)
    moved = im.transform(size, Image.AFFINE, data, resample=Image.BICUBIC, fillcolor=fill)
    if cut:
        m = poly_mask(im.size, [cut])
        rest = Image.composite(Image.new("L", im.size, fill), im, m).resize(size) if size != im.size else \
            Image.composite(Image.new("L", im.size, fill), im, m)
        if background:
            rest = Image.open(background).convert("L").resize(size)
        mm = m.transform(size, Image.AFFINE, data, resample=Image.BICUBIC, fillcolor=0)
        moved = Image.composite(moved, rest, mm)
    moved.save(out)
    return {"scale": round(abs(a), 4), "rotate_deg": round(math.degrees(cmath.phase(a)), 2),
            "shift": [round(b.real, 1), round(b.imag, 1)], "cut": bool(cut)}


def rough_crop(page, panel, da, out, width_px=1152):
    """The panel's current drawing (rough or previous final) resampled into the draw area, without
    borders, neighbouring panels or lettering: a clean composition reference for the illustrator.
    Falls back to the art-only page crop when the panel has no drawing yet."""
    from .render import iter_layers
    lay = next((L for L in iter_layers(page.layers) if L.kind == "image" and L.data.get("panel") == panel
                and not L.data["drawing"].missing), None)
    if lay is None:  # no drawing yet (only a placeholder slot): there is no composition to send
        shutil.copy2(FsPath(out).with_name("context-crop.png"), out)
        return None
    src = Image.open(lay.data["drawing"].file).convert("L")
    s = width_px / (da[2] - da[0])
    h = round((da[3] - da[1]) * s)
    I = lay.data["transform"].inverse()
    data = (I.a / s, I.c / s, I.a * da[0] + I.c * da[1] + I.e,
            I.b / s, I.d / s, I.b * da[0] + I.d * da[1] + I.f)
    im = src.transform((width_px, h), Image.AFFINE, data, resample=Image.BICUBIC, fillcolor=255)
    im.save(out)
    return out


def _story_context(project, beat_id, beat) -> dict:
    """Cumulative reader knowledge and continuity state for a beat (story/ files), with the
    legacy per-beat reader_knows / conceal keys as a fallback."""
    from .story import Story
    try:
        st = Story(project)
        if beat_id in st.beat:
            k = st.knowledge()[beat_id]
            return {"known": k["known"], "concealed": k["concealed"], "state": st.state_at(beat_id)}
    except Exception:
        pass
    return {"known": list(beat.get("reader_knows", [])), "concealed": list(beat.get("conceal", [])), "state": {}}


def render_prompt(req: dict) -> str:
    """Host-neutral text brief. Adapters may shorten it to fit their backend."""
    t, sg, c = req["target"], req["shot_guide"], req["continuity"]
    refs = "\n".join(f"- {r['id']}@{r['version']}{'#' + r['view']['name'] if r.get('view') else ''} ({r['kind']}"
                     f"{', ' + r['style_rule'] + ' card' if r.get('style_rule') else ''}): {r.get('note') or r.get('identity')}"
                     + (f" [variant: {r['variant']}]" if r.get("variant") else "") for r in req["references"])
    lms = "\n".join(f"- {l['name']} at page {l['page_xy']}" for l in sg["landmarks"]) or "- none"
    lett = "\n".join(f"- keep clear: {l['dialogue']} area {l['bbox']}" for l in sg["reserved_lettering"]) or "- none"
    eye = "; ".join(f"{f['rank']}. {f.get('label') or 'focal'} at page {f['page_xy']}" for f in sg.get("focal", []))
    if sg.get("board_note") or eye:
        lms += "\n" + (f"- board: {sg['board_note']}\n" if sg.get("board_note") else "") + (f"- eye path: {eye}" if eye else "")
    acc = "\n".join(f"- {a}" for a in req["acceptance"])
    edit = ""
    if req.get("edit_of"):
        e = req["edit_of"]
        edit = (f"\n## Edit of the selected drawing\nSource: {e['asset']}@{e['version']} (first reference image). "
                f"Keep everything else identical: same characters, framing, linework and tones.\n"
                f"Change only: {e['instruction']}\n")
    lines = "\n".join(f"- {l['speaker']}: \"{l['text']}\"" for l in c["dialogue_in_panel"]) or "- none"
    return f"""# Art request {req['job']} - {req['asset']}
Target: {t['page']} / panel {t['panel']} (beat {t['beat']}), reading direction {t['reading_direction']}.
Reason: {req['reason']}. Aspect ratio {sg['aspect_ratio']}; at least {sg['min_source_px_for_print']} px for print.
{edit}
## Shot
{c['beat_summary']}
Composition: follow the rough crop (pack/rough-crop.png) and shot guide (pack/guide.png): same camera,
same placement of the key shapes. {req.get('notes', '')}

## Must include beyond the panel border
{req['beyond_border']}

## Landmarks (where key points sit in the layout)
{lms}

## Lettering that will be added later (do not draw text)
{lett}
Dialogue in this panel (context only):
{lines}

## Continuity
- previous shot screen direction: {c['previous_screen_direction'] or 'n/a'}
- transition: {c['transition_to_next'] or 'n/a'}
- reader knows after this beat: {', '.join(c['reader_knows_after']) or 'n/a'}
- keep concealed: {', '.join(c['conceal']) or 'nothing'}
- story state at this beat: {', '.join(f"{k}={v}" for k, v in (c.get('state') or {}).items()) or 'n/a'}

## References (pinned versions)
{refs or '- none'}

## Style
{req.get('style') or 'Match the style exemplar.'}

## Acceptance criteria
{acc}
"""


# ---------------------------------------------------------------------- adapters
class Adapter:
    """Translate the common art request into what a backend accepts.

    capabilities: generate (text+refs -> image), edit ('none' | 'reference' = re-draw guided by the
    selected source | 'masked' = pixel-preserving inpaint), alpha (returns transparency).
    """
    name = "base"
    capabilities = {"generate": True, "edit": "none", "alpha": False}

    def __init__(self, project: Project):
        self.p = project
        self.cfg = (project.cfg.get("illustration", {}) or {}).get("adapters", {}).get(self.name, {})

    def prepare(self, jobs: Jobs, jid, req):
        pass

    def submit(self, jobs: Jobs, jid, req, n) -> list:
        return []  # asynchronous by default: outputs arrive via `job collect`

    def instructions(self, jobs, jid, req, n) -> str:
        return ""


class ManualAdapter(Adapter):
    """Writes the pack for a human or another agent; images come back through art/jobs/<id>/inbox/."""
    name = "manual"
    capabilities = {"generate": True, "edit": "reference", "alpha": True}

    def prepare(self, jobs, jid, req):
        d = jobs.path(jid)
        (d / "inbox").mkdir(exist_ok=True)
        (d / "pack" / "README.txt").write_text(
            f"Art request {jid}. Read ../prompt.md and ../request.yaml. Return PNG files (optionally with alpha)\n"
            f"into {d / 'inbox'} and then run: mangakit job collect {jid} --inbox\n")

    def instructions(self, jobs, jid, req, n):
        d = jobs.path(jid)
        return f"Send {d / 'prompt.md'} and {d / 'pack'} to the illustrator; drop results in {d / 'inbox'}; then `mangakit job collect {jid} --inbox`."


class HostToolAdapter(Adapter):
    """For hosts whose image tool is called by the agent (not by mangakit). Writes host-call-<n>.json
    with the tool arguments; the agent makes the call and collects the returned file(s).
    Argument names are configurable in project.yaml illustration.adapters.host:
      {prompt_arg: description, refs_arg: reference_image_paths, aspect_arg: aspect_ratio, max_refs: 4}"""
    name = "host"
    capabilities = {"generate": True, "edit": "reference", "alpha": False}

    def submit(self, jobs, jid, req, n):
        d = jobs.path(jid)
        cfg = {"prompt_arg": "description", "refs_arg": "reference_image_paths", "aspect_arg": "aspect_ratio",
               "max_refs": 4, "max_prompt_chars": 3500, **self.cfg}
        refs = []
        if req.get("edit_of"):
            # edits: the source carries the composition; the crude rough would pull the style back toward it
            refs.append(str(d / req["edit_of"]["pack_file"]))
        elif not req["shot_guide"].get("rough_is_placeholder"):
            refs.append(str(d / "pack" / "rough-crop.png"))
        refs += [str(d / r["pack_file"]) for r in req["references"]]
        refs = refs[: cfg["max_refs"]]
        args = {cfg["prompt_arg"]: compact_prompt(req, len(refs), cfg["max_prompt_chars"]),
                cfg["refs_arg"]: refs, cfg["aspect_arg"]: req["shot_guide"]["aspect_ratio"],
                "filename": f"{jid}-call{n}.png"}
        (d / f"host-call-{n}.json").write_text(json.dumps({"job": jid, "call": n, "arguments": args}, indent=2))
        return []

    def instructions(self, jobs, jid, req, n):
        f = jobs.path(jid) / f"host-call-{n}.json"
        return (f"Call the host image tool with the arguments in {f}, then run "
                f"`mangakit job collect {jid} <returned-file> --call {n}`.")


class CommandAdapter(Adapter):
    """Runs a shell command template from project.yaml illustration.adapters.command.run, e.g.
    'my-imagegen --prompt {prompt} --refs {refs} --out {out_dir}'. New image files in out_dir are collected."""
    name = "command"
    capabilities = {"generate": True, "edit": "reference", "alpha": False}

    def submit(self, jobs, jid, req, n):
        tmpl = self.cfg.get("run")
        if not tmpl:
            raise MangakitError("illustration.adapters.command.run not set in project.yaml")
        d = jobs.path(jid)
        out = d / f"out-call{n}"
        out.mkdir(exist_ok=True)
        e = req.get("edit_of")
        # with a paint-over, never also send the unmoved source: backends copy the closest reference
        refs = ([str(d / e["pack_file"])] if e else
                ([] if req["shot_guide"].get("rough_is_placeholder") else [str(d / "pack" / "rough-crop.png")])) \
            + [str(d / r["pack_file"]) for r in req["references"]]
        cmd = tmpl.format(prompt=shlex.quote(str(d / "prompt.md")), refs=shlex.quote(",".join(refs)),
                          out_dir=shlex.quote(str(out)), aspect=req["shot_guide"]["aspect_ratio"], job=jid)
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if r.returncode != 0:
            raise MangakitError(f"command adapter failed: {r.stderr.strip()[:400]}")
        return sorted(p for p in out.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))


ADAPTERS = {a.name: a for a in (ManualAdapter, HostToolAdapter, CommandAdapter)}


def get_adapter(name, project) -> Adapter:
    if name not in ADAPTERS:
        raise MangakitError(f"unknown adapter {name}; have {sorted(ADAPTERS)}")
    return ADAPTERS[name](project)


def _conceal_in_shot(req, c):
    """Concealment ids whose subject (the id's first token, e.g. 'her' in 'her-face') is named in the
    shot (notes or beat, capitalised). Naming an absent character's secret makes backends draw her."""
    import re as _re
    txt = f"{req.get('notes', '')} {c.get('beat_summary', '')}"
    out = []
    for x in c.get("conceal", []):
        subj = str(x).split("-")[0]
        if _re.search(r"\b" + _re.escape(subj.capitalize()) + r"\b", txt) or subj.lower() not in ("her",):
            out.append(x)
    return out


def compact_prompt(req, n_refs, limit=3500) -> str:
    """One-paragraph prompt for single-string image tools, naming each reference image by position."""
    t, c = req["target"], req["continuity"]
    order = []
    if req.get("edit_of"):
        order.append(f"the {'paint-over guide' if req['edit_of'].get('paintover') else 'drawing to edit'} "
                     f"({req['edit_of']['asset']}@{req['edit_of']['version']})")
    elif not req["shot_guide"].get("rough_is_placeholder"):
        order.append("a layout rough of the panel (composition only; do not copy its crude drawing style or any lines that look like panel borders)")
    order += [f"{r['kind']} reference {r['id']}"
              + (f" ({r['style_rule']} card)" if r.get("style_rule") else "")
              + (f", {r['view']['name']} view only" if r.get("view") else "")
              + f": {r.get('note') or r.get('identity')}" for r in req["references"]]
    refs_txt = "; ".join(f"image {i + 1} is {o}" for i, o in enumerate(order[:n_refs]))
    bw = "full-color" if str(req.get("color", "")).startswith("full") else "black-and-white"
    if req.get("edit_of") and req["edit_of"].get("paintover"):
        head = (f"Image 1 is a paint-over guide made from our {bw} manga panel drawing: parts were moved "
                f"into their new positions. Redraw it as one clean finished panel in exactly the same style, keeping "
                f"every moved part where the guide puts it: {req['edit_of']['instruction']}.")
    elif req.get("edit_of"):
        head = (f"Edit image 1, a {bw} manga panel drawing. Keep the same characters, objects, camera, "
                f"framing, line style and tones; change only this: {req['edit_of']['instruction']}.")
    else:
        head = (f"{bw.capitalize()} manga panel illustration. Story beat (context only; never draw any of its words, "
                f"names, logos or UI text): {c['beat_summary']}")
    parts = [head, req.get("style") or "", f"Composition notes: {req.get('notes', '')}",
             f"Beyond the panel border: {req['beyond_border']}",
             f"Keep concealed: {', '.join(_conceal_in_shot(req, c))}." if _conceal_in_shot(req, c) else "",
             f"Reading direction {t['reading_direction']}; previous shot direction: {c['previous_screen_direction']}."
             if c["previous_screen_direction"] else "",
             f"References: {refs_txt}.",
             "No text, letters, speech balloons, panel borders, frames, signatures or watermarks."]
    s = " ".join(p.strip() for p in parts if p and p.strip())
    return s[:limit]


# ---------------------------------------------------------------------- metrics
def metrics(project: Project) -> dict:
    jobs = Jobs(project)
    rows = [j for j in Registry(project).jobs() if j.get("kind") == "art-request"]
    per_panel: dict[str, dict] = {}
    art_free_calls = 0
    for j in rows:
        key = f"{j['page']}/{j['panel']}"
        n = len(j.get("calls", []))
        p = per_panel.setdefault(key, {"asset": j["asset"], "jobs": [], "calls": 0, "accepted": None})
        p["jobs"].append({"job": j["id"], "reason": j["reason"], "calls": n, "status": j["status"],
                          "accepted": j.get("accepted")})
        p["calls"] += n
        if j.get("accepted"):
            p["accepted"] = j["accepted"]
        if j["reason"] in ART_FREE_REASONS:
            art_free_calls += n
    # evidence for the "zero art calls from lettering/mask edits" metric: after each acceptance, how many
    # mask versions were made on the accepted drawing, and how many art calls hit that asset meanwhile
    reg = Registry(project)
    after = {}
    for j in rows:
        if not j.get("accepted"):
            continue
        t = j.get("accepted_at", "")
        rec = reg.load(j["asset"])
        masks = [f"{n}/{mv}" for n, m in rec.get("masks", {}).items() for mv, v in m["versions"].items()
                 if v.get("source_version") == j["accepted"] and v.get("created", "") >= t]
        later_calls = sum(1 for k in rows if k["asset"] == j["asset"] for c in k.get("calls", []) if c["at"] > t)
        after[f"{j['page']}/{j['panel']}"] = {"accepted": j["accepted"], "accepted_at": t,
                                              "mask_versions_after": masks, "art_calls_after": later_calls}
    accepted = [p for p in per_panel.values() if p["accepted"]]
    return {
        "panels": per_panel,
        "accepted_panels": len(accepted),
        "illustration_calls_total": sum(p["calls"] for p in per_panel.values()),
        "illustration_calls_per_accepted_panel": (round(sum(p["calls"] for p in accepted) / len(accepted), 2)
                                                  if accepted else None),
        "art_calls_caused_by_lettering_or_mask_edits": art_free_calls,
        "design_image_calls": __import__("mangakit.design", fromlist=["calls"]).calls(project)["design_calls_total"],
        "after_acceptance": after,
        "note": "render/check/rebuild never call image generation; only `job call` does",
    }
