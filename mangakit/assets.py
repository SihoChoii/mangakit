"""Asset registry under art/.

art/assets/<asset-id>/asset.yaml      registry record (versions, selection, landmarks, masks)
art/assets/<asset-id>/v001.png ...    immutable drawing versions (never overwritten)
art/assets/<asset-id>/masks/<mask>/m001.png  immutable mask versions, registered to ONE source version
art/jobs/<job-id>/job.yaml            illustration jobs; candidates reference their job id

Rules
- Versions are append-only. `select` is the only way the page's art changes.
- Landmarks are stored per drawing version; masks record source_version + source_sha256.
  Selecting a different drawing version makes its old masks/landmarks stale (they are not reused).
"""
from __future__ import annotations

import datetime as _dt
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path as FsPath

from PIL import Image

from .project import MangakitError, Project, dump_yaml, load_yaml, sha256_file

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _now():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Registry:
    def __init__(self, project: Project):
        self.p = project
        self.dir = project.root / "art" / "assets"
        self.jobs_dir = project.root / "art" / "jobs"

    # ---------- records
    def rec_path(self, aid):
        return self.dir / aid / "asset.yaml"

    def exists(self, aid):
        return self.rec_path(aid).exists()

    def load(self, aid) -> dict:
        p = self.rec_path(aid)
        if not p.exists():
            raise MangakitError(f"unknown asset {aid!r} (no {p})")
        return load_yaml(p)

    def save(self, aid, rec):
        dump_yaml(self.rec_path(aid), rec)

    def ids(self):
        return sorted(d.name for d in self.dir.iterdir() if (d / "asset.yaml").exists()) if self.dir.exists() else []

    # ---------- versions
    def add_version(self, aid, file, job=None, note="", select=False, kind="drawing"):
        if not ID_RE.match(aid):
            raise MangakitError(f"asset id must match {ID_RE.pattern}")
        src = FsPath(file)
        if not src.exists():
            raise MangakitError(f"no such file {src}")
        d = self.dir / aid
        d.mkdir(parents=True, exist_ok=True)
        rec = load_yaml(self.rec_path(aid)) if self.exists(aid) else {
            "id": aid, "kind": kind, "selected": None, "versions": {}, "landmarks": {}, "masks": {}}
        n = len(rec["versions"]) + 1
        ver = f"v{n:03d}"
        dst = d / f"{ver}{src.suffix.lower()}"
        shutil.copy2(src, dst)
        with Image.open(dst) as im:
            w, h = im.size
            mode = im.mode
        rec["versions"][ver] = {"file": dst.name, "sha256": sha256_file(dst), "width": w, "height": h,
                                "mode": mode, "job": job, "status": "candidate", "created": _now(),
                                "note": note, "origin": str(src)}
        if select:
            self._select(rec, ver)
        self.save(aid, rec)
        if job:
            self._job_add_candidate(job, aid, ver)
        return ver

    def _select(self, rec, ver):
        if ver not in rec["versions"]:
            raise MangakitError(f"{rec['id']} has no version {ver}")
        old = rec.get("selected")
        if old and old in rec["versions"] and old != ver:
            rec["versions"][old]["status"] = "superseded"
        rec["versions"][ver]["status"] = "selected"
        rec["selected"] = ver
        # masks/landmarks registered to the old version are now stale; report them
        stale = [m for m, mrec in rec.get("masks", {}).items()
                 if mrec.get("selected") and mrec["versions"][mrec["selected"]]["source_version"] != ver]
        return stale

    def select(self, aid, ver, if_current=None):
        rec = self.load(aid)
        if if_current is not None and rec.get("selected") != (if_current or None):
            raise MangakitError(f"{aid}: selected is {rec.get('selected')}, not {if_current}; refusing (stale job?)")
        stale = self._select(rec, ver)
        self.save(aid, rec)
        return stale

    def version(self, aid, ver=None) -> tuple[str, dict]:
        rec = self.load(aid)
        ver = ver or rec.get("selected")
        if not ver:
            raise MangakitError(f"asset {aid!r} has no selected version")
        if ver not in rec["versions"]:
            raise MangakitError(f"asset {aid!r} has no version {ver}")
        return ver, rec["versions"][ver]

    def file(self, aid, ver) -> FsPath:
        return self.dir / aid / self.load(aid)["versions"][ver]["file"]

    # ---------- landmarks (per version)
    def set_landmark(self, aid, name, x, y, ver=None, protect=False, note=""):
        rec = self.load(aid)
        ver = ver or rec.get("selected")
        if ver not in rec["versions"]:
            raise MangakitError(f"{aid} has no version {ver}")
        rec.setdefault("landmarks", {}).setdefault(ver, {})[name] = {
            "xy": [float(x), float(y)], "protect": bool(protect), "note": note}
        self.save(aid, rec)
        return ver

    # ---------- masks (registered to a source version)
    def add_mask(self, aid, name, mask_img: Image.Image, source_ver=None, note="", recipe=None, select=True):
        rec = self.load(aid)
        source_ver = source_ver or rec.get("selected")
        vrec = rec["versions"][source_ver]
        if mask_img.size != (vrec["width"], vrec["height"]):
            raise MangakitError(f"mask size {mask_img.size} != source {source_ver} size "
                                f"{(vrec['width'], vrec['height'])}")
        mrec = rec.setdefault("masks", {}).setdefault(name, {"selected": None, "versions": {}})
        mver = f"m{len(mrec['versions']) + 1:03d}"
        mdir = self.dir / aid / "masks" / name
        mdir.mkdir(parents=True, exist_ok=True)
        f = mdir / f"{mver}.png"
        mask_img.convert("L").save(f, optimize=True)
        mrec["versions"][mver] = {"file": f"masks/{name}/{mver}.png", "sha256": sha256_file(f),
                                  "source_version": source_ver, "source_sha256": vrec["sha256"],
                                  "width": mask_img.size[0], "height": mask_img.size[1],
                                  "created": _now(), "note": note, "recipe": recipe}
        if select:
            mrec["selected"] = mver
        self.save(aid, rec)
        return mver

    def select_mask(self, aid, name, mver):
        rec = self.load(aid)
        mrec = rec.get("masks", {}).get(name)
        if not mrec or mver not in mrec["versions"]:
            raise MangakitError(f"{aid} has no mask {name}/{mver}")
        mrec["selected"] = mver
        self.save(aid, rec)

    # ---------- validation
    def validate(self, aid) -> list[dict]:
        out = []
        rec = self.load(aid)
        for ver, v in rec["versions"].items():
            f = self.dir / aid / v["file"]
            if not f.exists():
                out.append(_issue("error", "missing-asset", f"{aid}/{ver}", f"file missing: {f}"))
            elif sha256_file(f) != v["sha256"]:
                out.append(_issue("error", "asset-modified", f"{aid}/{ver}",
                                  "drawing bytes changed after registration (versions are immutable)"))
        for name, m in rec.get("masks", {}).items():
            for mver, mv in m["versions"].items():
                f = self.dir / aid / mv["file"]
                if not f.exists():
                    out.append(_issue("error", "missing-mask", f"{aid}:{name}/{mver}", f"file missing {f}"))
                    continue
                with Image.open(f) as im:
                    size = im.size
                src = rec["versions"].get(mv["source_version"], {})
                if size != (src.get("width"), src.get("height")):
                    out.append(_issue("error", "mask-dims", f"{aid}:{name}/{mver}",
                                      f"mask {size} != source {mv['source_version']} "
                                      f"{(src.get('width'), src.get('height'))}"))
            sel = m.get("selected")
            if sel and m["versions"][sel]["source_version"] != rec.get("selected"):
                out.append(_issue("error", "stale-mask", f"{aid}:{name}/{sel}",
                                  f"registered to {m['versions'][sel]['source_version']}, "
                                  f"selected drawing is {rec.get('selected')}; rebuild the mask"))
        return out

    # ---------- jobs
    def new_job(self, aid, brief_text="", brief_file=None, inputs=None):
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        from .ids import claim_dir
        d = claim_dir(self.jobs_dir, "job-", 4)      # atomic: two workers never share a job id
        jid = d.name
        if brief_file:
            shutil.copy2(brief_file, d / FsPath(brief_file).name)
        cur = None
        if self.exists(aid):
            cur = self.load(aid).get("selected")
        dump_yaml(d / "job.yaml", {"id": jid, "asset": aid, "status": "open", "created": _now(),
                                   "brief": brief_text, "brief_file": FsPath(brief_file).name if brief_file else None,
                                   "selected_when_opened": cur, "inputs": inputs or {}, "candidates": []})
        return jid

    def _job_add_candidate(self, jid, aid, ver):
        f = self.jobs_dir / jid / "job.yaml"
        if not f.exists():
            raise MangakitError(f"unknown job {jid}")
        j = load_yaml(f)
        j.setdefault("candidates", []).append({"asset": aid, "version": ver, "at": _now()})
        j["status"] = "delivered"
        dump_yaml(f, j)

    def jobs(self):
        if not self.jobs_dir.exists():
            return []
        return [load_yaml(d / "job.yaml") for d in sorted(self.jobs_dir.iterdir()) if (d / "job.yaml").exists()]


def _issue(sev, code, where, msg, bbox=None):
    return {"severity": sev, "code": code, "where": where, "message": msg, **({"bbox": bbox} if bbox else {})}


# ---------------- objects handed to page sources ----------------

@dataclass
class Drawing:
    asset_id: str
    version: str | None
    file: FsPath | None
    width: int
    height: int
    sha256: str | None
    landmarks: dict = field(default_factory=dict)
    missing: str | None = None  # reason, when unusable
    kind: str = "drawing"       # asset kind; "rough" = procedural board sketch (mangakit rough make)
    meta: dict = field(default_factory=dict)  # rough sketches: focal points, sightlines, notes (source px)

    def landmark(self, name):
        if name not in self.landmarks:
            raise MangakitError(f"{self.asset_id}/{self.version}: no landmark {name!r} "
                                f"(have {sorted(self.landmarks)}); landmarks are per drawing version")
        return tuple(self.landmarks[name]["xy"])


@dataclass
class Mask:
    asset_id: str
    name: str
    version: str | None
    file: FsPath | None
    width: int
    height: int
    sha256: str | None
    source_version: str | None
    problem: str | None = None


class Art:
    """`art` object given to page sources: resolves stable asset ids to selected versions.

    pins: {"asset-id": "v002", "asset-id:mask-name": "m001"} override selection (used by rebuild).
    """

    def __init__(self, project: Project, pins: dict | None = None):
        self.reg = Registry(project)
        self.pins = pins or {}
        self.used: dict[str, Drawing] = {}
        self.used_masks: dict[str, Mask] = {}
        self.issues: list[dict] = []

    def selected(self, aid: str) -> Drawing:
        try:
            rec = self.reg.load(aid)
            ver = self.pins.get(aid) or rec.get("selected")
            if not ver:
                raise MangakitError(f"asset {aid!r} has no selected version")
            v = rec["versions"][ver]
            f = self.reg.dir / aid / v["file"]
            if not f.exists():
                raise MangakitError(f"file missing for {aid}/{ver}: {f}")
            lms = rec.get("landmarks", {}).get(ver, {})
            if f"{aid}#landmarks" in self.pins:   # rebuild: the landmarks the proof was made with
                lms = {k: {"xy": list(xy)} for k, xy in self.pins[f"{aid}#landmarks"].items()}
            d = Drawing(aid, ver, f, v["width"], v["height"], v["sha256"], lms,
                        kind=rec.get("kind", "drawing"), meta=v.get("rough") or {})
        except (MangakitError, KeyError) as e:
            self.issues.append(_issue("error", "missing-asset", aid, str(e)))
            d = Drawing(aid, None, None, 1000, 1000, None, {}, missing=str(e))
        self.used[aid] = d
        return d

    def slot(self, final: str, rough: str | None = None) -> Drawing:
        """Use the final asset when it has a selection, else the rough (board stage). Under rebuild
        pins, the slot uses whichever of the two the proof used."""
        if self.pins and final in self.pins:      # trial/rebuild pin on the final: use it
            return self.selected(final)
        if self.pins and rough and rough in self.pins and final not in self.pins:
            return self.selected(rough)
        if rough and (not self.reg.exists(final) or not self.reg.load(final).get("selected")):
            return self.selected(rough)
        return self.selected(final)

    def mask(self, drawing: Drawing, name: str) -> Mask:
        key = f"{drawing.asset_id}:{name}"
        try:
            rec = self.reg.load(drawing.asset_id)
            mrec = rec.get("masks", {}).get(name)
            if not mrec:
                raise MangakitError(f"{drawing.asset_id} has no mask {name!r}")
            mver = self.pins.get(key) or mrec.get("selected")
            mv = mrec["versions"][mver]
            f = self.reg.dir / drawing.asset_id / mv["file"]
            m = Mask(drawing.asset_id, name, mver, f, mv["width"], mv["height"], mv["sha256"], mv["source_version"])
            if mv["source_version"] != drawing.version:
                m.problem = (f"mask {name}/{mver} is registered to {mv['source_version']} but the drawing "
                             f"in use is {drawing.version}")
                self.issues.append(_issue("error", "stale-mask", key, m.problem))
            if (m.width, m.height) != (drawing.width, drawing.height):
                m.problem = f"mask {m.width}x{m.height} != drawing {drawing.width}x{drawing.height}"
                self.issues.append(_issue("error", "mask-dims", key, m.problem))
            if not f.exists():
                raise MangakitError(f"mask file missing {f}")
        except (MangakitError, KeyError) as e:
            self.issues.append(_issue("error", "missing-mask", key, str(e)))
            m = Mask(drawing.asset_id, name, None, None, drawing.width, drawing.height, None, None, problem=str(e))
        self.used_masks[key] = m
        return m
