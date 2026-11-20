"""Reference registry under references/<id>/ref.yaml: design sheets (character, costume, prop,
environment, world), style cards, sources. Same append-only version rules as art assets.

Identity and variants
  ref.yaml  kind, identity, canon: <canon id>, versions: {vNNN: {..., variant: <name>}},
            views: {vNNN: {<view>: {box: [x0, y0, x1, y1], note}}}
A variant is a named look of one identity (a costume, a damaged prop, night/day of a place). A
version is one drawing of it; new versions never overwrite old ones. A view is a crop of one version
(a single pose, the sleeve and cuff) so a brief can pin only what the shot needs.

Spec grammar (art requests, style cards):  id[:variant][@vNNN][#view]
  rin-design                 selected version
  rin-design:courier-jacket  the selected version if it is that variant, else its newest version
  rin-design#cuff            the selected version if it has that view, else the newest one that does
  rin-design@v002#cuff       the 'cuff' view of v002
"""
from __future__ import annotations

import re

from PIL import Image

from .assets import Registry
from .project import MangakitError, Project

DESIGN_KINDS = ("character", "costume", "prop", "environment", "world")
KINDS = DESIGN_KINDS + ("design", "style", "source", "pose", "other")
SPEC_RE = re.compile(r"^(?P<id>[a-z0-9][a-z0-9._-]*)(?::(?P<variant>[A-Za-z0-9._-]+))?"
                     r"(?:@(?P<ver>v\d{3}))?(?:#(?P<view>[A-Za-z0-9._-]+))?$")


def parse_spec(spec: str) -> dict:
    m = SPEC_RE.match(spec.strip())
    if not m:
        raise MangakitError(f"bad reference spec {spec!r}; want id[:variant][@vNNN][#view]")
    return m.groupdict()


class RefRegistry(Registry):
    def __init__(self, project: Project):
        super().__init__(project)
        self.dir = project.root / "references"

    def rec_path(self, rid):
        return self.dir / rid / "ref.yaml"

    def ids(self):
        return sorted(d.name for d in self.dir.iterdir() if (d / "ref.yaml").exists()) if self.dir.exists() else []

    def add_ref(self, rid, file, kind="design", identity="", variant="", note="", select=True, canon=None,
                brief=None):
        if kind not in KINDS:
            raise MangakitError(f"kind must be one of {KINDS}")
        ver = self.add_version(rid, file, note=note, select=select, kind=kind)
        rec = self.load(rid)
        rec["kind"] = kind
        rec.setdefault("identity", identity or rid)
        if canon:
            rec["canon"] = canon.split(",") if isinstance(canon, str) and "," in canon else canon
        if variant:
            rec["versions"][ver]["variant"] = variant
            rec.setdefault("variants", {})[ver] = variant  # legacy map, kept for older readers
        if brief:
            rec["versions"][ver]["brief"] = brief
        self.save(rid, rec)
        return ver

    def set_meta(self, rid, canon=None, identity=None, kind=None):
        rec = self.load(rid)
        if canon is not None:
            rec["canon"] = canon.split(",") if "," in canon else canon
        if identity is not None:
            rec["identity"] = identity
        if kind is not None:
            if kind not in KINDS:
                raise MangakitError(f"kind must be one of {KINDS}")
            rec["kind"] = kind
        self.save(rid, rec)

    def add_view(self, rid, name, box, version=None, note=""):
        """Name a crop of one version (source px). Pinned as id@ver#name."""
        rec = self.load(rid)
        ver = version or rec.get("selected")
        if ver not in rec["versions"]:
            raise MangakitError(f"{rid}: no version {ver}")
        v = rec["versions"][ver]
        x0, y0, x1, y1 = [int(round(float(c))) for c in box]
        if not (0 <= x0 < x1 <= v["width"] and 0 <= y0 < y1 <= v["height"]):
            raise MangakitError(f"{rid}@{ver}: view box {box} outside the {v['width']}x{v['height']} image")
        rec.setdefault("views", {}).setdefault(ver, {})[name] = {"box": [x0, y0, x1, y1], "note": note}
        self.save(rid, rec)
        return ver

    def variant_of(self, rec, ver):
        v = rec["versions"].get(ver, {})
        return v.get("variant") or rec.get("variants", {}).get(ver, "")

    def variants(self, rid) -> dict:
        rec = self.load(rid)
        out = {}
        for ver in rec["versions"]:
            name = self.variant_of(rec, ver)
            if name:
                out.setdefault(name, []).append(ver)
        return out

    def resolve(self, spec: str) -> dict:
        """spec -> pinned record for an art request (file = the view crop when a view is named)."""
        s = parse_spec(spec)
        rid = s["id"]
        if not self.exists(rid):
            raise MangakitError(f"unknown reference {rid!r}")
        rec = self.load(rid)
        ver = s["ver"]
        if not ver and (s["variant"] or s["view"]):
            vs = [v for v in rec["versions"] if not s["variant"] or self.variant_of(rec, v) == s["variant"]]
            if not vs:
                raise MangakitError(f"reference {rid}: no version of variant {s['variant']!r} "
                                    f"(have {sorted(self.variants(rid))})")
            if s["view"]:  # the newest version (of the variant) that has this view
                vs = [v for v in vs if s["view"] in (rec.get("views") or {}).get(v, {})] or vs
            # the selected version wins when it qualifies; otherwise the newest
            ver = rec.get("selected") if rec.get("selected") in vs else vs[-1]
        ver = ver or rec.get("selected")
        if not ver or ver not in rec["versions"]:
            raise MangakitError(f"reference {spec}: no such version")
        if s["variant"] and self.variant_of(rec, ver) != s["variant"]:
            raise MangakitError(f"reference {spec}: {ver} is variant {self.variant_of(rec, ver)!r}")
        v = rec["versions"][ver]
        file = self.dir / rid / v["file"]
        size = [v["width"], v["height"]]
        view = None
        if s["view"]:
            vw = rec.get("views", {}).get(ver, {}).get(s["view"])
            if not vw:
                raise MangakitError(f"reference {rid}@{ver}: no view {s['view']!r} "
                                    f"(have {sorted(rec.get('views', {}).get(ver, {}))})")
            crop = self.dir / rid / "views" / f"{ver}-{s['view']}.png"
            if not crop.exists():
                crop.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(file) as im:
                    im.crop(tuple(vw["box"])).save(crop)
            view = {"name": s["view"], "box": vw["box"], "note": vw.get("note", "")}
            file = crop
            size = [vw["box"][2] - vw["box"][0], vw["box"][3] - vw["box"][1]]
        latest = list(rec["versions"])[-1]
        return {"id": rid, "spec": spec, "version": ver, "kind": rec.get("kind"), "identity": rec.get("identity"),
                "canon": rec.get("canon"), "variant": self.variant_of(rec, ver), "view": view,
                "note": (view or {}).get("note") or v.get("note", ""),
                "sha256": v["sha256"], "file": str(file), "size": size,
                "selected": rec.get("selected"), "latest": latest}
