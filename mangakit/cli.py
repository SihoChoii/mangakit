"""mangakit command line. Run `mangakit <cmd> -h` for details. All commands accept -C <project dir>."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path as FsPath

from .project import MangakitError, Project, init_project, sha256_file


def _proj(a) -> Project:
    return Project.find(a.C)


def _fallback_style(p):
    """project.yaml illustration.style is used only when there is no art direction guide."""
    from .design import Direction
    return "" if Direction(p) else p.cfg.get("illustration", {}).get("style", "")


def _floats(s, n=None):
    v = [float(x) for x in s.replace("x", ",").split(",")]
    if n and len(v) != n:
        raise MangakitError(f"expected {n} numbers in {s!r}")
    return v


def _print_issues(issues, as_json=False):
    if as_json:
        print(json.dumps(issues, indent=2))
        return
    if not issues:
        print("checks: OK (0 issues)")
    for i in issues:
        bb = f" bbox={i['bbox']}" if i.get("bbox") else ""
        print(f"[{i['severity'].upper():5}] {i['code']:24} {i['where']}: {i['message']}{bb}")


def cmd_init(a):
    root = init_project(a.dir, a.title, a.direction, a.language, _floats(a.trim_mm, 2), a.bleed_mm, a.dpi)
    print(f"initialized {root}")


def cmd_info(a):
    p = _proj(a)
    c = p.cfg
    print(f"project   {p.root}\ntitle     {c.get('title')}\nreading   {p.direction}  language {c.get('language')}")
    print(f"trim      {c['page']['trim_mm']} mm  bleed {c['page']['bleed_mm']} mm  = {p.trim_w:.0f}x{p.trim_h:.0f} units "
          f"(+{p.bleed:.0f} bleed), {p.upm:g} units/mm")
    print(f"chapter   {p.chapter}: {p.chapter_pages()}")
    for role, f in p.fonts().items():
        print(f"font      {role:18} {f['file']}  sha256 {f['sha256'][:16]}")
    probs = p.verify_fonts()
    print("fonts     " + ("; ".join(probs) if probs else "all pins verified"))


def cmd_asset(a):
    from .assets import Registry
    from .masktools import inspect_asset
    p = _proj(a)
    r = Registry(p)
    if a.op == "add":
        v = r.add_version(a.asset, a.file, job=a.job, note=a.note or "", select=a.select, kind=a.kind)
        print(f"{a.asset}/{v} registered" + (" and selected" if a.select else " (candidate; not selected)"))
    elif a.op == "select":
        old = r.load(a.asset).get("selected")
        stale = r.select(a.asset, a.version, if_current=a.if_current)
        print(f"{a.asset}: selected {a.version}")
        for m in stale:
            print(f"  ! INVALIDATED mask {m}: registered to a previous version; rebuild it (mangakit mask make)")
        lms = r.load(a.asset).get("landmarks", {})
        for n in sorted(set(lms.get(old or "", {})) - set(lms.get(a.version, {}))):
            print(f"  ! INVALIDATED landmark {n}: set on {old}, not on {a.version}; set it again")
    elif a.op == "landmark":
        v = r.set_landmark(a.asset, a.name, a.x, a.y, ver=a.version, protect=a.protect, note=a.note or "")
        print(f"{a.asset}/{v}: landmark {a.name} = ({a.x}, {a.y})")
    elif a.op == "list":
        for aid in r.ids():
            rec = r.load(aid)
            print(f"{aid:28} selected={rec.get('selected')}  versions={list(rec['versions'])}  "
                  f"masks={ {k: m.get('selected') for k, m in rec.get('masks', {}).items()} }")
    elif a.op == "show":
        import yaml
        print(yaml.safe_dump(r.load(a.asset), sort_keys=False))
        for i in r.validate(a.asset):
            print(f"[{i['severity']}] {i['code']} {i['where']}: {i['message']}")
    elif a.op == "inspect":
        crop = tuple(int(v) for v in _floats(a.crop, 4)) if a.crop else None
        print(inspect_asset(p, a.asset, a.version, a.grid, a.out, crop))


def cmd_mask(a):
    from .assets import Registry
    from .masktools import make_mask, mask_preview, parse_points
    p = _proj(a)
    if a.op == "make":
        polys = [parse_points(s) for s in (a.polygon or [])]
        subs = [parse_points(s) for s in (a.subtract or [])]
        seeds = [tuple(map(float, s.split(","))) for s in (a.bg_seed or [])] or None
        mv = make_mask(p, a.asset, a.name, polys, subs, a.from_png, a.trim_light_edges, a.grow, a.feather,
                       a.version, a.note or "", seeds, snap=a.snap)
        print(f"{a.asset}: mask {a.name}/{mv} registered to the selected drawing and selected")
        print(mask_preview(p, a.asset, a.name, mv))
    elif a.op == "select":
        Registry(p).select_mask(a.asset, a.name, a.mversion)
        print(f"{a.asset}: mask {a.name} -> {a.mversion}")
    elif a.op == "preview":
        print(mask_preview(p, a.asset, a.name, a.mversion, a.out))


def cmd_job(a):
    from .assets import Registry
    from .illustrate import Jobs, get_adapter
    p = _proj(a)
    r = Registry(p)
    J = Jobs(p)
    if a.op == "new":
        print(r.new_job(a.target, a.text or "", a.brief))
    elif a.op == "withdraw":
        j = J.withdraw(a.target, a.note or "")
        print(f"{j['id']} withdrawn: {a.note}")
    elif a.op == "list":
        for j in r.jobs():
            cands = [c["version"] for c in j.get("candidates", [])]
            where = f"{j.get('page', '')}/{j.get('panel', '')}" if j.get("page") else ""
            print(f"{j['id']}  {j['asset']:22} {j['status']:10} {j.get('reason', ''):12} {where:16} "
                  f"calls={len(j.get('calls', []))} candidates={cands} accepted={j.get('accepted')}")
    elif a.op == "request":
        if not (a.target and a.panel and a.asset):
            raise MangakitError("job request <page> --panel <id> --asset <asset-id> [--ref id[@ver] ...]")
        jid = J.request(a.target, a.panel, a.asset, refs=a.ref or [], reason=a.reason, adapter=a.adapter,
                        prev_direction=a.prev_direction or "", transition=a.transition or "",
                        conceal=a.conceal or [], beyond_border=a.beyond or "", acceptance=a.accept or [],
                        notes=a.notes or "", edit_of=a.edit_of, instruction=a.instruction or "",
                        style_words=a.style or _fallback_style(p),
                        aspect=a.aspect, chapter=a.chapter, paintover_file=a.paintover, designs=a.design or [],
                        auto_style=not a.no_style)
        d = J.path(jid)
        print(jid)
        print(f"request   {d / 'request.yaml'}")
        print(f"prompt    {d / 'prompt.md'}")
        print(f"pack      {d / 'pack'}  (guide.png, guide.json, rough-crop.png, refs/)")
        import yaml as _y
        _req = _y.safe_load((d / "request.yaml").read_text())
        if _req.get("style_revision"):
            print(f"style     {_req['style_revision']['revision']} (effective for beat {_req['target']['beat']}, chapter {_req['target']['chapter']})")
        for r in _req["references"]:
            print(f"pinned    {r['id']}@{r['version']}{'#' + r['view']['name'] if r.get('view') else ''}"
                  f"{' [' + r['variant'] + ']' if r.get('variant') else ''}{' (' + r['style_rule'] + ' card)' if r.get('style_rule') else ''}")
        ad = get_adapter(a.adapter, p)
        print(f"adapter   {ad.name} capabilities={ad.capabilities}")
        if a.edit_of and ad.capabilities.get("edit") == "none":
            print("note      backend cannot edit; this runs as a replacement through the same acceptance check")
    elif a.op == "call":
        n, how = J.call(a.target, note=a.note or "")
        print(f"{a.target}: call {n} logged")
        if how:
            print(how)
    elif a.op == "collect":
        files = ([a.version] if a.version else []) + list(a.files or [])
        if a.inbox:
            inbox = J.path(a.target) / "inbox"
            files += sorted(str(f) for f in inbox.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
        vers = J.collect(a.target, files, call_n=a.call, note=a.note or "")
        print(f"{a.target}: candidates {vers} (stored, not selected)")
    elif a.op == "review":
        trials = dict(t.split("=", 1) for t in (a.trial or []))
        print(J.review_sheet(a.target, trials, a.out, also=a.also or []))
    elif a.op == "verdict":
        if a.passed == a.failed:
            raise MangakitError("give exactly one of --pass / --fail")
        J.verdict(a.target, a.version, a.passed, a.note or "")
        print(f"{a.target} {a.version}: {'PASS' if a.passed else 'FAIL'}")
    elif a.op == "select":
        stale, missing = J.select(a.target, a.version, force=a.force)
        job = J.load(a.target)
        print(f"{job['asset']}: selected {a.version} (job {a.target} accepted)")
        for m in stale:
            print(f"INVALIDATED mask {m}: built on an older version; compose must rebuild it (mangakit mask make)")
        for lm in missing:
            print(f"INVALIDATED landmark {lm}: not set on {a.version}; set it (mangakit asset landmark ... --version {a.version})")
    elif a.op == "show":
        import yaml
        print(yaml.safe_dump(J.load(a.target), sort_keys=False, allow_unicode=True))
    elif a.op == "targets":
        # layout positions in image px, assuming the returned image fills the draw area (for paint-overs)
        from .geometry import Path as GPath
        g = json.loads((J.path(a.target) / "pack" / "guide.json").read_text())
        w, h = (int(v) for v in (a.size or "1152x864").split("x"))
        da = g["draw_area_page_units"]
        f = lambda x, y: (round((x - da[0]) * w / (da[2] - da[0]), 1), round((y - da[1]) * h / (da[3] - da[1]), 1))
        print(f"image {w}x{h} filling draw area {da}")
        for lm in g["landmarks"]:
            print(f"landmark {lm['name']:18} page {lm['page_xy']} -> image px {f(*lm['page_xy'])}")
        for b in g["breakouts"]:
            x0, y0, x1, y1 = GPath.from_svg(b["path"]).bbox()
            print(f"breakout {b['name']:18} image px {f(x0, y0)} - {f(x1, y1)}")
        ring = GPath.from_svg(g["panel_path"]).rings()[0]
        print("panel border image px " + " ".join(str(f(*q)) for q in ring))


def cmd_ref(a):
    from .references import RefRegistry
    p = _proj(a)
    r = RefRegistry(p)
    if a.op == "add":
        ver = r.add_ref(a.id, a.file, a.kind, a.identity or "", a.variant or "", a.note or "", select=not a.no_select,
                        canon=a.canon)
        print(f"{a.id}: added {ver}")
    elif a.op == "view":
        if not (a.file and a.box):
            raise MangakitError("ref view <id> <view-name> --box x0,y0,x1,y1 [--version vNNN] [--note]")
        ver = r.add_view(a.id, a.file, _floats(a.box, 4), version=a.version, note=a.note or "")
        res = r.resolve(f"{a.id}@{ver}#{a.file}")
        print(f"{a.id}@{ver}#{a.file}: {res['size'][0]}x{res['size'][1]} px -> {res['file']}")
    elif a.op == "meta":
        r.set_meta(a.id, canon=a.canon, identity=a.identity, kind=a.kind_meta)
        print(f"{a.id}: updated")
    elif a.op == "resolve":
        print(json.dumps(r.resolve(a.id), indent=2))
    elif a.op == "list":
        for rid in r.ids():
            rec = r.load(rid)
            views = {v: sorted(x) for v, x in (rec.get("views") or {}).items()}
            print(f"{rid:28} {rec.get('kind', ''):12} canon={','.join(rec['canon']) if isinstance(rec.get('canon'), list) else (rec.get('canon') or '-'):8} selected={rec.get('selected')} "
                  f"versions={list(rec['versions'])} variants={r.variants(rid) or {}}" + (f" views={views}" if views else ""))
    elif a.op == "show":
        import yaml
        print(yaml.safe_dump(r.load(a.id), sort_keys=False))
    elif a.op == "select":
        r.select(a.id, a.file)
        print(f"{a.id}: selected {a.file}")


def cmd_paintover(a):
    from .assets import Registry
    from .illustrate import paintover
    p = _proj(a)
    r = Registry(p)
    ver, _ = r.version(a.asset, a.version)
    maps = []
    for m in a.map:
        src, dst = m.split(":")
        maps.append((tuple(_floats(src, 2)), tuple(_floats(dst, 2))))
    if len(maps) != 2:
        raise MangakitError("give exactly two --map sx,sy:tx,ty")
    from .masktools import parse_points
    info = paintover(r.file(a.asset, ver), maps, a.out, cut=parse_points(a.cut) if a.cut else None,
                     background=a.background)
    print(f"{a.out}  ({a.asset}@{ver}: scale {info['scale']}, rotate {info['rotate_deg']} deg, shift {info['shift']})")


def _print_story_issues(issues):
    for i in issues:
        print(f"[{i['severity'].upper():5}] {i['code']:24} {i['where']:22} {i['message']}")
    n = {k: sum(1 for i in issues if i["severity"] == k) for k in ("error", "warn", "info")}
    print(f"story check: {n['error']} error(s), {n['warn']} warning(s), {n['info']} info")
    return 2 if n["error"] else (1 if n["warn"] else 0)


def cmd_story(a):
    from . import story as S
    p = _proj(a)
    if a.op == "check":
        st = S.Story(p)
        issues = st.check(S.pages_info(p, a.chapter) if not a.no_pages else None)
        if a.json:
            print(json.dumps(issues, indent=2))
        rc = _print_story_issues(issues) if not a.json else (2 if any(i["severity"] == "error" for i in issues) else 0)
        sys.exit(2 if rc == 2 else (1 if rc == 1 and a.strict else 0))
    if a.op == "state":
        st = S.Story(p)
        if a.target not in st.beat:
            raise MangakitError(f"no beat {a.target!r}")
        k = st.knowledge()[a.target]
        print(json.dumps({"beat": a.target, "continuity_after": st.state_at(a.target), "reader": k}, indent=2))
        return
    if a.op == "deps":
        print(json.dumps(S.deps(p, chapter=a.chapter), indent=2, default=str))
        return
    if a.op == "glance":
        print(S.glance(p, a.chapter, a.out))
        return
    if a.op == "impact":
        if not a.target:
            raise MangakitError("story impact needs a line id, beat id, event id or subject.attribute")
        r = S.impact(p, a.target, new_text=a.text, new_value=a.set, chapter=a.chapter)
        if a.json:
            print(json.dumps(r, indent=2))
            return
        print(f"impact of {r['kind']} {r['target']}")
        if r.get("fact"):
            f = r["fact"]
            print(f"  {f['key']} = {f['value']!r} via {', '.join(f['events']) or 'initial state'}; "
                  f"in effect over {', '.join(f['in_effect'])}")
        for owner in ("story", "board", "compose", "illustrate", "review"):
            for item in r[owner]:
                (act, msg), = item.items()
                print(f"  {owner:10} {act:7} {msg}")
        h = r.get("hypothetical")
        if h:
            print(f"  hypothetical: {h['change']}")
            for i in h["new_issues"] or []:
                print(f"    new [{i['severity']}] {i['code']} {i['where']}: {i['message']}")
            if not h["new_issues"]:
                print("    story check: no new issues")
            for pid, v in (h.get("pages") or {}).items():
                if isinstance(v, str):
                    print(f"    {pid}: {v}")
                else:
                    for i in v:
                        print(f"    {pid} [{i['severity']}] {i['code']} {i['where']}: {i['message']}")
        return
    raise MangakitError(f"unknown story op {a.op}")


def cmd_design(a):
    from . import design as Dz
    import yaml
    p = _proj(a)
    if a.op == "check":
        issues = Dz.check(p)
        if a.json:
            print(json.dumps(issues, indent=2))
        else:
            for i in issues:
                print(f"[{i['severity'].upper():5}] {i['code']:24} {i['where']:26} {i['message']}")
            n = {k: sum(1 for i in issues if i["severity"] == k) for k in ("error", "warn", "info")}
            print(f"design check: {n['error']} error(s), {n['warn']} warning(s), {n['info']} info")
        sys.exit(2 if any(i["severity"] == "error" for i in issues) else
                 (1 if a.strict and any(i["severity"] == "warn" for i in issues) else 0))
    elif a.op == "brief":
        if not (a.target and a.kind and a.prompt):
            raise MangakitError("design brief <ref-id> --kind K --prompt TEXT [--layout L] [--ref spec] [--canon id] [--variant v]")
        bid, bd = Dz.brief(p, a.target, a.kind, a.prompt, a.layout, a.ref or [], a.canon, a.variant, a.aspect or "4:3")
        print(f"{a.target} brief {bid}: call 1 logged")
        print(f"Call the host image tool with the arguments in {bd / 'host-call-1.json'}, then run "
              f"`mangakit design collect {a.target} {bid} <returned-file>`.")
    elif a.op == "recall":
        n = Dz.brief_recall(p, a.target, a.arg)
        print(f"{a.target} brief {a.arg}: call {n} logged (arguments in host-call-{n}.json)")
    elif a.op == "collect":
        ver = Dz.brief_collect(p, a.target, a.arg, a.file, a.note or "", select=not a.no_select)
        print(f"{a.target}: added {ver} from brief {a.arg}")
    elif a.op == "calls":
        c = Dz.calls(p)
        for rid, row in c["refs"].items():
            print(f"{rid:28} calls={row['calls']} " + " ".join(f"[{b['brief']} calls={b['calls']} -> {b['outputs']}]" for b in row["briefs"]))
        print(f"design image calls total: {c['design_calls_total']}")
    elif a.op == "for":
        print(Dz.design_for(p, a.target, beat=a.beat, view=a.view))
    elif a.op == "guide":
        print(Dz.guide_md(p, a.out))
    elif a.op == "sample":
        revs = (a.compare.split(",") if a.compare else [a.revision])
        kw = {}
        if a.sfx_at:
            kw["sfx_at"] = _floats(a.sfx_at, 2)
        if a.line_at:
            kw["line_at"] = _floats(a.line_at, 2)
        imgs = (a.image or "").split(",") if a.image and "," in a.image else [a.image] * len(revs)
        res = [Dz.sample(p, im, r, a.chapter, a.line or "", a.sfx or "", _floats(a.box, 4) if a.box else None,
                         label=r, **kw) for r, im in zip(revs, imgs)]
        for r in res:
            print(f"{r['revision']}: reading-size {r['reading']} (height {r['reading_height_px']} px)  proof {r['proof']}")
            if r["render"]:
                print(f"   render params: {json.dumps(r['render'])}")
        if len(res) > 1 or a.out:
            print(Dz.compare(res, a.out or p.root / "build" / "design" / f"sample-{'-vs-'.join(revs)}.png"))
    else:
        raise MangakitError(f"unknown design op {a.op}")


def cmd_style(a):
    from .design import Direction
    import yaml
    p = _proj(a)
    D = Direction(p)
    if a.op == "list":
        for r in D.revisions:
            print(f"{r['id']:8} effective={r.get('effective')} based_on={r.get('based_on')} rules={sorted(D.rules(r['id']))}  {r.get('note', '')}")
        for d in sorted((p.root / "chapters").iterdir()):
            if (d / "chapter.yaml").exists():
                pin = D.chapter_pin(d.name)
                print(f"chapter {d.name}: {pin or D.effective(d.name)}{' (pinned)' if pin else ''}")
    elif a.op == "show":
        rid = a.target or D.effective(a.chapter, a.beat)
        print(f"# {rid} (chapter {a.chapter or p.chapter}{', beat ' + a.beat if a.beat else ''})")
        print(yaml.safe_dump(D.rules(rid), sort_keys=False, allow_unicode=True))
        print("art brief: " + json.dumps(D.brief(rid), indent=2))
    elif a.op == "revise":
        if not a.target or not (a.from_chapter or a.from_beat) or not a.rules:
            raise MangakitError("style revise <new-id> --base <rev> (--from-chapter C | --from-beat B) --rules rules.yaml [--note]")
        eff = {"chapter": a.from_chapter} if a.from_chapter else {"beat": a.from_beat}
        rules = yaml.safe_load(open(a.rules)) or {}
        pinned = D.revise(a.target, a.base, eff, rules, note=a.note or "", pin_earlier=not a.no_pin)
        print(f"{a.target}: effective from {eff}, based on {a.base}; overrides {sorted(rules)}")
        for x in pinned:
            print(f"pinned chapter {x} (its pages and briefs keep that revision)")
    elif a.op == "pin":
        from .project import dump_yaml, load_yaml
        from .work import decide
        if not a.target or not a.rev:
            raise MangakitError("style pin <chapter> --rev <revision> --reason TEXT")
        if a.rev not in D.by_id:
            raise MangakitError(f"no style revision {a.rev}")
        meta = p.root / "chapters" / a.target / "chapter.yaml"
        m = load_yaml(meta) or {}
        old = m.get("style")
        m["style"] = a.rev
        dump_yaml(meta, m)
        d = decide(p, f"style pin chapter {a.target}", f"{old or 'unpinned'} -> {a.rev}", a.note or "", refs=[old, a.rev])
        print(f"chapter {a.target}: style {old} -> {a.rev} ({d['id']} recorded in work/decisions.yaml)")
    else:
        raise MangakitError(f"unknown style op {a.op}")


def cmd_work(a):
    from . import work as W
    import yaml
    p = _proj(a)
    ch = a.chapter or p.chapter
    if a.op == "plan":
        r = W.plan(p, ch)
        print(f"plan chapter {ch}: created {len(r['created'])}, stale {len(r['stale'])}, reopened {len(r['reopened'])}, "
              f"cancelled {len(r['cancelled'])}; fresh renders {len(r['fresh'])}")
        ch_ = {k: v for k, v in r["changes"].items() if v and k != "first"}
        if ch_:
            print("story changes since baseline: " + json.dumps(ch_))
        for k in ("created", "stale", "reopened", "cancelled"):
            if r[k]:
                print(f"{k}: {' '.join(r[k])}")
        print(W.format_units(r["units"], only=("queued", "stale", "running", "blocked", "needs-creator")))
    elif a.op == "status":
        S = W.status(p)
        print("  ".join(f"{k}={v}" for k, v in sorted(S["counts"].items())))
        only = None if a.all else ("queued", "stale", "running", "blocked", "needs-creator")
        print(W.format_units(S["units"], only=only))
    elif a.op == "next":
        n = W.next_unit(p)
        if not n:
            print("nothing runnable (work status: needs-creator / blocked units wait on a decision)")
            return
        print(f"next: {n['unit']['id']} {n['unit']['skill']} {n['unit']['kind']}: {n['unit']['title']}")
        print(f"route: {n['context']['route']}")
        print(f"context: {n['file']}")
        if not a.quiet:
            print(yaml.safe_dump(n["context"], sort_keys=False, allow_unicode=True, width=110))
    elif a.op == "show":
        u = W.get_unit(p, a.target)
        print(yaml.safe_dump(u, sort_keys=False, allow_unicode=True, width=110))
    elif a.op == "context":
        u = W.get_unit(p, a.target)
        print(W.context_md(W.context(p, u)))
    elif a.op == "start":
        u = W.start(p, a.target)
        print(f"{u['id']} running")
    elif a.op == "done":
        u = W.done(p, a.target, a.output or [], a.note or "", a.image_calls)
        print(f"{u['id']} done; outputs {u['outputs']}")
    elif a.op == "wait":
        u = W.get_unit(p, a.target)
        u["after"] = sorted(set(u.get("after", [])) | set(a.refs or []))
        W._set(p, u, u["status"], f"waits on {' '.join(a.refs or [])}" + (f": {a.note}" if a.note else ""))
        print(f"{u['id']} after {u['after']}")
    elif a.op == "block":
        u = W.get_unit(p, a.target)
        W._set(p, u, "blocked", a.note or "")
        print(f"{u['id']} blocked: {a.note}")
    elif a.op == "run":
        r = W.run(p, limit=a.limit, skills=a.skill, log=lambda m: print(m, flush=True))
        for uid, st in r["ran"]:
            print(f"{uid} {st}")
    elif a.op == "resume":
        r = W.resume(p, ch)
        print(f"interrupted: {' '.join(r['interrupted']) or '-'}")
        if r["still_running"]:
            print(f"still running (live worker, left alone): {' '.join(r['still_running'])}")
        print(f"recovered (output complete): {' '.join(r['recovered']) or '-'}")
        print(f"requeued: {' '.join(r['requeued']) or '-'}")
        print(f"missing (new units): {' '.join(r['created']) or '-'}")
        print(f"newly stale (inputs changed): {' '.join(r['stale']) or '-'}")
        print(f"all stale now: {' '.join(r['stale_all']) or '-'}")
        print(f"waiting on other units: {' '.join(r['waiting']) or '-'}")
        print(f"cancelled (no longer needed): {' '.join(r['cancelled']) or '-'}")
        print(f"to do now, automatic (work run): {' '.join(r['todo_auto']) or '-'}")
        print(f"to do now, agent/skill (work next): {' '.join(r['todo_agent']) or '-'}")
    elif a.op == "approve":
        if not a.target or not a.subject:
            raise MangakitError("work approve <gate> <subject> --by <creator> --note <their decision>")
        x = W.approve(p, a.target, a.subject, a.by, a.note)
        print(f"approved {x['gate']} {x['subject']} by {x['by']}")
    elif a.op == "decide":
        if not a.target or not a.decision:
            raise MangakitError("work decide <subject> --decision TEXT --reason TEXT [--refs ...]")
        d = W.decide(p, a.target, a.decision, a.reason or "", by=a.by or "direct", refs=a.refs or [])
        print(f"{d['id']} {d['subject']}: {d['decision']}")
    elif a.op == "art-style":
        d = W.judge_art_style(p, a.target, a.rev, a.reason or "", by=a.by or "direct")
        print(f"{d['id']} {d['subject']}: {d['decision']}")
    elif a.op == "metrics":
        m = W.metrics(p)
        (W.wdir(p) / "metrics.json").write_text(json.dumps(m, indent=2))
        for k, v in m.items():
            print(f"{k:<44} {v}")
    elif a.op == "gates":
        print(json.dumps({"gates": W.gates(p), "approvals": W.approvals(p)}, indent=2))
    else:
        raise MangakitError(f"unknown work op {a.op}")


def cmd_publish(a):
    from . import publish as P
    p = _proj(a)
    ch = a.chapter or p.chapter
    if a.op == "list":
        for S in P.list_sets(p, ch):
            print(f"{S['name']}  {S['created']}  final={S['final']}  pages={[e['page'] for e in S['pages']]}  {S.get('note', '')}")
    elif a.op == "rebuild":
        R = P.rebuild(p, a.name, ch)
        print(P.format_rebuild(R))
        if not R["identical"]:
            sys.exit(1)
    else:
        S = P.publish(p, ch, a.name, final=a.final, note=a.note or "")
        print(f"published {S['name']} (chapter {ch}, final={S['final']}) -> publish/ch{ch}/{S['name']}/set.yaml")
        for e in S["pages"]:
            print(f"  {e['page']}: " + "  ".join(f"{v} {x['sha256'][:12]} ({x['style']})" for v, x in e["views"].items()))
        if S["check_errors"]:
            print(f"check errors frozen with the set: {S['check_errors']}")


def cmd_metrics(a):
    from .illustrate import metrics
    p = _proj(a)
    m = metrics(p)
    out = p.root / "build" / "metrics.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(m, indent=2))
    if a.json:
        print(json.dumps(m, indent=2))
        return
    for key, v in m["panels"].items():
        print(f"{key:18} asset={v['asset']} calls={v['calls']} accepted={v['accepted']} "
              + " ".join(f"[{j['job']} {j['reason']} calls={j['calls']} {j['status']}]" for j in v["jobs"]))
    print(f"accepted panels                         {m['accepted_panels']}")
    print(f"illustration calls total                {m['illustration_calls_total']}")
    print(f"illustration calls per accepted panel   {m['illustration_calls_per_accepted_panel']}")
    print(f"art calls from lettering/mask edits     {m['art_calls_caused_by_lettering_or_mask_edits']}")
    print(f"design-sheet image calls                {m.get('design_image_calls', 0)}")
    for key, v in m["after_acceptance"].items():
        print(f"  {key} after accepting {v['accepted']}: {len(v['mask_versions_after'])} mask versions "
              f"{v['mask_versions_after']}, art calls {v['art_calls_after']}")
    print(out)


def cmd_review(a):
    from . import review as RV
    p = _proj(a)
    ch = a.chapter or p.chapter
    op = a.op
    if op == "packet":
        r = RV.packet(p, ch, pages=a.pages.split(",") if a.pages else None)
        print(f"round {FsPath(r['dir']).name}: packet {r['packet']}")
        for s in r["sequence"]:
            print(f"  {s['file']}" + (f"  pages {s['pages']}" if s.get("pages") else ""))
        print("give the reader ONLY the packet directory; record answers with `review answers <file>`")
    elif op == "answers":
        if not a.target:
            raise MangakitError("review answers <answers.yaml> [--round rNN]")
        r = RV.record_answers(p, a.target, ch, a.round)
        print(f"recorded answers ({r['reader']}) sha256 {r['sha256'][:12]}; next: `review key`, fill key.yaml, `review score`")
    elif op == "key":
        print(RV.key_template(p, ch, a.round))
    elif op == "score":
        r = RV.score(p, ch, a.round, file=not a.no_file, force=a.force)
        for k, q in r["questions"].items():
            if "total" in q:
                print(f"{k:<11} {q['ok']}/{q['total']}" + (f"  ({q['unjudged']} unjudged)" if q.get("unjudged") else ""))
            else:
                print(f"{k:<11} {q['items']} item(s)")
        print(f"score {r['score']['ok']}/{r['score']['total']}")
        for fid, how, key in r["findings"]:
            print(f"  {fid} {how:<14} {key}")
    elif op == "tech":
        r = RV.tech(p, ch, file=not a.no_file)
        for m in r["issues"]:
            print(f"[{m['severity'].upper():<5}] {m['code']:<24} {m['where']:<32} {m['owner']:<10} ({'+'.join(m['tools'])}) {m['message']}")
        print(f"review tech: {r['raw']} raw issue(s) -> {len(r['issues'])} after de-duplication")
        for fid, how, key in r["filed"]:
            print(f"  {fid} {how:<11} {key}")
    elif op == "art":
        r = RV.art_sheet(p, ch, verdicts=a.verdicts)
        print(r["png"]); print(r["md"])
        for fid, how in r["filed"]:
            print(f"  {fid} {how}")
    elif op == "add":
        if not (a.observed and a.owner):
            raise MangakitError("review add --observed ... --owner OWNER [--intended] [--page --panel --region] [--code --severity]")
        probe = json.loads(a.probe) if a.probe else None
        fid, how = RV.add(p, ch, page=a.page, panel=a.panel_id, region=[float(v) for v in a.region.split(",")] if a.region else None,
                          code=a.code or "visual", severity=a.severity or "warn", owner=a.owner, observed=a.observed,
                          intended=a.intended or "", evidence=a.evidence or [], probe=probe, title=a.title, key=a.key)
        print(f"{fid} {how}")
    elif op == "set":
        f = RV.set_status(p, a.target, a.status, a.note or "", owner=a.owner)
        print(f"{f['id']} -> {f['status']} ({f['owner']})")
    elif op == "editorial":
        alts = []
        for x in a.alt or []:
            name, owner, desc = (x.split("|", 2) + ["", ""])[:3]
            alts.append({"name": name.strip(), "owner": owner.strip() or None, "description": desc.strip(), "by": a.by or "review"})
        f = RV.editorial(p, a.target, alts, a.note or "")
        print(f"{f['id']} editorial: " + ", ".join(x["name"] for x in f["alternatives"]))
    elif op == "decide":
        f = RV.decide(p, a.target, a.name, a.reason or "")
        print(f"{f['id']} decided {a.name} -> {f['status']} ({f['owner']})")
    elif op == "verdict":
        f = RV.verdict(p, a.target, a.name, a.note or "")
        print(f"{f['id']} {a.name} -> {f['status']}")
    elif op == "recheck":
        r = RV.recheck(p, ch)
        print(RV.recheck_md(r))
        print(r["dir"])
    elif op == "list":
        F = RV.summary(p, ch, a.status, a.owner)
        print(json.dumps(F, indent=2, default=str) if a.json else RV.format_findings(F))
        print(f"{len(F)} finding(s)")
    elif op == "metrics":
        m = RV.metrics(p, ch)
        print(json.dumps(m, indent=2) if a.json else "\n".join(f"{k:<40} {v}" for k, v in m.items()))


def _load(a, p):
    from .render import load_page
    pins = dict(x.split("=", 1) for x in (getattr(a, "pin", None) or []))
    page, _ = load_page(p, a.page, pins=pins or None, chapter=getattr(a, "chapter", None), alt=getattr(a, "alt", None))
    return page


def cmd_rough(a):
    from .assets import Registry
    from .rough import make_rough
    p = _proj(a)
    if a.op == "make":
        ids = [a.id] if a.id else sorted(f.stem for f in (p.root / "art" / "roughs").glob("*.py"))
        for aid in ids:
            src = a.source if a.id else None
            ver, created, info = make_rough(p, aid, src, a.note or "")
            print(f"{aid:28} {ver} {'NEW' if created else 'unchanged'}  {info['landmarks']} landmarks  {info['file']}")
    elif a.op == "list":
        reg = Registry(p)
        for aid in reg.ids():
            rec = reg.load(aid)
            if rec.get("kind") != "rough":
                continue
            v = rec.get("selected")
            m = rec["versions"][v].get("rough", {}) if v else {}
            print(f"{aid:28} {v}  focal={len(m.get('focal', []))} sightlines={len(m.get('sightlines', []))} "
                  f"landmarks={sorted(rec.get('landmarks', {}).get(v, {}))}  source={m.get('source')}")
    else:
        raise MangakitError(f"unknown rough op {a.op}")


def cmd_board(a):
    from . import board as B
    p = _proj(a)
    ch = a.chapter or p.chapter
    if a.op == "plan":
        r = B.plan(p, ch, per_page=a.per_page, write=a.write, stubs=a.stubs)
        for pg in r["plan"]["pages"]:
            tag = "after turn" if pg["after_turn"] else ""
            print(f"{pg['id']} [{pg['status']}] spread {pg['spread']} {tag}")
            for pn in pg["panels"]:
                print(f"   {pn['id']:<18} beat={pn.get('beat'):<16} lines={','.join(pn.get('lines', [])) or '-'}"
                      f"  ({pn['status']}{', reveals ' + ','.join(pn['reveals']) if pn.get('reveals') else ''})")
        for x in r["added"]:
            print(f"added {x}")
        for x in r["stubs"]:
            print(f"stub  {x}")
        if r["plan"]["retired"]:
            print("retired ids (never reused): " + ", ".join(x["id"] for x in r["plan"]["retired"]))
        _print_issues(r["issues"])
        print(("wrote " + str(B.plan_path(p, ch).relative_to(p.root))) if a.write else "(dry run: --write saves board.yaml)")
        if any(i["severity"] == "error" for i in r["issues"]):
            sys.exit(2)
    elif a.op == "check":
        alts = B._alts_map(p, ch, a.alt) if a.alt else {}
        R = B.check_chapter(p, ch, alts, all_technical=a.all)
        if a.json:
            print(json.dumps({"issues": R["issues"], "turns": R["turns"]}, indent=2))
        else:
            print(B.format_report(R))
        if any(i["severity"] == "error" for i in R["issues"]):
            sys.exit(2)
    elif a.op == "render":
        r = B.render_board(p, ch, a.alt)
        for pid, f in r["pages"].items():
            print(f"rough   {f}")
        for f in r["spreads"] + r["rough_spreads"]:
            print(f"spread  {f}")
        print(f"turns   {r['turns']}")
        print(f"check   {r['check']}")
    elif a.op == "alt":
        if not a.target or not a.name:
            raise MangakitError("board alt <page> <name> [--from <alt>]")
        f = B.alt_create(p, a.target, a.name, ch, a.from_alt)
        print(f"created {f.relative_to(p.root)} (edit it; panel ids must stay stable)")
    elif a.op == "alts":
        for n, pids in B.list_alts(p, ch).items():
            print(f"{n:<12} {' '.join(pids)}")
    elif a.op == "compare":
        names = (a.target or "current").split(",")
        r = B.compare(p, names, ch, a.out)
        print(r["png"])
        print(r["md"])
        for n, s in r["summary"].items():
            c = s["counts"]
            print(f"{n:<10} {c['error']} error(s) {c['warn']} warn {c['info']} info; art still needed: {len(s['needs_art'])}; "
                  f"board: {s['board'] or '-'}; technical: {s['technical'] or '-'}")
    elif a.op == "promote":
        if not a.target:
            raise MangakitError("board promote <alt-name> --reason \"...\" [--force] [--dry-run]")
        r = B.promote(p, a.target, ch, a.reason or "", a.force, a.dry_run)
        for m in r["moved"]:
            print(f"moved   {m['panel']}: {m['from']} -> {m['to']}" + (f"  jobs {m['jobs']}" if m["jobs"] else ""))
        for d in r["dropped"]:
            print(f"dropped {d['page']}/{d['panel']}" + (f"  referenced by jobs {d['jobs']}" if d["jobs"] else "")
                  + ("  (in board.yaml)" if d["planned"] else ""))
        for x in r["added"]:
            print(f"added   {x}")
        for x in r["stale_jobs"]:
            print(f"stale   {x}")
        for x in r["blocked"]:
            print(f"BLOCKED {x}")
        for x in r["archived"]:
            print(f"archived {x}")
        if r.get("kept"):
            print(f"kept the current layout over alternates {r['alternates']} (logged in alternates.yaml)")
            return
        print("promoted" if r["promoted"] else ("not promoted (dry run)" if a.dry_run and not r["blocked"]
                                                else "not promoted: ids would break (fix the alternate or --force)"))
        if r["blocked"] and not a.force:
            sys.exit(2)
    else:
        raise MangakitError(f"unknown board op {a.op}")


def cmd_render(a):
    from .checks import run_checks
    from .render import render_page
    p = _proj(a)
    page = _load(a, p)
    issues = run_checks(page)
    errors = [i for i in issues if i["severity"] == "error"]
    if a.view == "export" and errors and not a.force:
        _print_issues(issues)
        raise MangakitError("refusing final export with errors (use --force to override)")
    region = _floats(a.region, 4) if a.region else None
    png = render_page(page, a.view, a.out, a.dpi, a.height, a.profile, a.panel, region=region)
    print(png)
    print(png.with_suffix(".manifest.json"))
    if issues and not a.quiet:
        _print_issues(issues)


def cmd_check(a):
    from .checks import run_checks
    p = _proj(a)
    pages = p.chapter_pages(a.chapter) if a.page == "all" else [a.page]
    worst = 0
    allissues = []
    for pid in pages:
        from .render import load_page
        pins = dict(x.split("=", 1) for x in (a.pin or []))
        page, _ = load_page(p, pid, pins=pins or None, chapter=a.chapter)
        issues = run_checks(page)
        for i in issues:
            i["page"] = pid
        allissues += issues
        if any(i["severity"] == "error" for i in issues):
            worst = 2
        elif a.strict and any(i["severity"] == "warn" for i in issues):
            worst = max(worst, 1)
    _print_issues(allissues, a.json)
    sys.exit(worst)


def cmd_spread(a):
    from .render import render_spread, spread_groups
    p = _proj(a)
    pages = p.chapter_pages(a.chapter)
    groups = spread_groups(p, pages, a.chapter)
    if a.page != "all":
        groups = [g for g in groups if a.page in g]
        if not groups:
            raise MangakitError(f"{a.page} not in chapter pages {pages}")
    for g in groups:
        print(render_spread(p, g, a.out if len(groups) == 1 else None, a.chapter))


def cmd_contact(a):
    from .render import contact_sheet
    print(contact_sheet(_proj(a), a.chapter, a.out))


def cmd_rebuild(a):
    from .render import rebuild
    p = _proj(a)
    png, same, notes = rebuild(p, a.manifest, a.out)
    print(png)
    for n in notes:
        print("note:", n)
    print("identical to recorded output: " + ("YES" if same else "NO"))
    sys.exit(0 if same else 3)


def cmd_hash(a):
    for f in a.paths:
        q = FsPath(f)
        files = sorted(x for x in q.rglob("*") if x.is_file()) if q.is_dir() else [q]
        for x in files:
            print(f"{sha256_file(x)}  {x}")


def cmd_docs(a):
    from .project import KIT_DIR
    d = KIT_DIR.parent / "docs"
    if a.name:
        f = d / (a.name if a.name.endswith(".md") else a.name + ".md")
        if not f.exists():
            raise MangakitError(f"no doc {f.name}; have: " + ", ".join(sorted(x.stem for x in d.glob("*.md"))))
        d = f
    print(d)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mangakit", description=__doc__)
    ap.add_argument("-C", default=None, help="project directory (default: search upward from cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="scaffold a project")
    s.add_argument("dir")
    s.add_argument("--title")
    s.add_argument("--direction", choices=["rtl", "ltr"], default="rtl")
    s.add_argument("--language", default="en")
    s.add_argument("--trim-mm", default="182x257", help="WxH in mm (default B5 tankobon 182x257)")
    s.add_argument("--bleed-mm", type=float, default=3)
    s.add_argument("--dpi", type=int, default=600, help="print profile dpi")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("info", help="project summary + font pin verification")
    s.set_defaults(fn=cmd_info)

    s = sub.add_parser("asset", help="asset registry")
    s.add_argument("op", choices=["add", "select", "landmark", "list", "show", "inspect"])
    s.add_argument("asset", nargs="?")
    s.add_argument("rest", nargs="*")
    s.add_argument("--job"); s.add_argument("--note"); s.add_argument("--select", action="store_true")
    s.add_argument("--kind", default="drawing"); s.add_argument("--version"); s.add_argument("--protect", action="store_true")
    s.add_argument("--if-current", help="select only if this version is still the selected one")
    s.add_argument("--grid", type=int, default=100); s.add_argument("--crop"); s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_asset)

    s = sub.add_parser("mask", help="source-coordinate masks")
    s.add_argument("op", choices=["make", "select", "preview"])
    s.add_argument("asset"); s.add_argument("name"); s.add_argument("mversion", nargs="?")
    s.add_argument("--polygon", action="append", help="'x,y x,y ...' or yaml/json file (repeatable, unioned)")
    s.add_argument("--subtract", action="append", help="polygon to remove (repeatable)")
    s.add_argument("--from-png", help="illustrator-supplied alpha/greyscale mask, same size as source")
    s.add_argument("--trim-light-edges", type=int, nargs="?", const=200, default=None,
                   help="remove paper/background pixels (>= threshold) connected to the polygon edge")
    s.add_argument("--bg-seed", action="append", help="x,y source px of background to flood away (repeatable)")
    s.add_argument("--grow", type=int, default=0); s.add_argument("--feather", type=float, default=0.0)
    s.add_argument("--snap", type=int, default=0, help="peel up to N px of paper margin off the mask edge, stopping at ink")
    s.add_argument("--version", help="source drawing version (default: selected)"); s.add_argument("--note")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_mask)

    s = sub.add_parser("job", help="art requests, adapter calls, candidates, review, guarded selection")
    s.add_argument("op", choices=["request", "call", "collect", "review", "verdict", "select", "show", "targets", "list", "new", "withdraw"])
    s.add_argument("target", nargs="?", help="page (request), job id (call/collect/review/verdict/select/show), asset (new)")
    s.add_argument("version", nargs="?", help="candidate version (verdict/select)")
    s.add_argument("files", nargs="*", help="returned image files (collect)")
    s.add_argument("--panel"); s.add_argument("--asset"); s.add_argument("--ref", action="append",
                   help="reference id or id@version (repeat)")
    s.add_argument("--reason", default="new-shot",
                   choices=["new-shot", "correction", "extension", "design-change", "continuity", "lettering", "mask"])
    s.add_argument("--adapter", default="host", help="host | manual | command")
    s.add_argument("--prev-direction"); s.add_argument("--transition"); s.add_argument("--conceal", action="append")
    s.add_argument("--beyond", help="what the art must include beyond the border (default: from breakouts)")
    s.add_argument("--accept", action="append", help="acceptance criterion (repeat; replaces defaults)")
    s.add_argument("--notes"); s.add_argument("--style"); s.add_argument("--aspect")
    s.add_argument("--edit-of", help="selected source version to edit (reference-guided correction)")
    s.add_argument("--instruction", help="what the edit must change")
    s.add_argument("--paintover", help="paint-over guide image to send instead of the raw --edit-of source")
    s.add_argument("--call", type=int, help="call number the files came from (collect)")
    s.add_argument("--inbox", action="store_true", help="collect everything in art/jobs/<id>/inbox (manual adapter)")
    s.add_argument("--trial", action="append", help="label=png trial placement to include (review)")
    s.add_argument("--size", help="WxH of the returned image (targets), default 1152x864")
    s.add_argument("--also", action="append", help="more job ids whose candidates join the sheet (review)")
    s.add_argument("--pass", dest="passed", action="store_true"); s.add_argument("--fail", dest="failed", action="store_true")
    s.add_argument("--note"); s.add_argument("--force", action="store_true"); s.add_argument("-o", "--out")
    s.add_argument("--chapter"); s.add_argument("--text"); s.add_argument("--brief")
    s.add_argument("--design", action="append", help="canon id[#view]: pin its design, variant from the costume at this beat")
    s.add_argument("--no-style", action="store_true", help="do not auto-pin the effective art-direction cards")
    s.set_defaults(fn=cmd_job)

    from .references import KINDS as REF_KINDS
    s = sub.add_parser("ref", help="reference registry (design sheets, style cards, sources): identities, variants, versions, views")
    s.add_argument("op", choices=["add", "list", "show", "select", "view", "meta", "resolve"])
    s.add_argument("id", nargs="?", help="reference id (resolve: a spec id[:variant][@vNNN][#view])")
    s.add_argument("file", nargs="?", help="image (add), version (select), view name (view)")
    s.add_argument("--kind", default="design", choices=list(REF_KINDS))
    s.add_argument("--kind-meta", choices=list(REF_KINDS), help="meta: change the kind")
    s.add_argument("--identity"); s.add_argument("--variant"); s.add_argument("--note")
    s.add_argument("--canon", help="canon id this reference designs (character/prop/location id)")
    s.add_argument("--box", help="view: x0,y0,x1,y1 in source px"); s.add_argument("--version")
    s.add_argument("--no-select", action="store_true")
    s.set_defaults(fn=cmd_ref)

    s = sub.add_parser("paintover", help="move a drawing by a 2-point similarity into a paint-over guide (source px)")
    s.add_argument("asset"); s.add_argument("--version"); s.add_argument("--map", action="append", required=True,
                   help="sx,sy:tx,ty (twice)")
    s.add_argument("--background", help="image to use behind the moved cut instead of the source with a hole")
    s.add_argument("--cut", help="move only this polygon ('x,y x,y ...' or yaml), leave the rest in place")
    s.add_argument("-o", "--out", required=True)
    s.set_defaults(fn=cmd_paintover)

    s = sub.add_parser("design", help="design sheets (briefs + logged image calls), design check, sample-shot test, direction guide")
    s.add_argument("op", choices=["check", "brief", "recall", "collect", "calls", "for", "guide", "sample"])
    s.add_argument("target", nargs="?", help="ref id (brief/recall/collect) or canon id (for)")
    s.add_argument("arg", nargs="?", help="brief id (recall/collect)")
    s.add_argument("file", nargs="?", help="returned image (collect)")
    s.add_argument("--kind"); s.add_argument("--prompt"); s.add_argument("--layout", default="single")
    s.add_argument("--ref", action="append"); s.add_argument("--canon"); s.add_argument("--variant"); s.add_argument("--aspect")
    s.add_argument("--note"); s.add_argument("--no-select", action="store_true")
    s.add_argument("--beat"); s.add_argument("--view"); s.add_argument("--chapter")
    s.add_argument("--image", help="sample: ref spec, asset[@ver] or file"); s.add_argument("--revision")
    s.add_argument("--compare", help="sample: comma-separated revisions side by side")
    s.add_argument("--line"); s.add_argument("--sfx"); s.add_argument("--box", help="sample panel x,y,w,h page units")
    s.add_argument("--sfx-at", help="sample: SFX position as fractions of the panel, e.g. 0.75,0.9")
    s.add_argument("--line-at", help="sample: balloon position as fractions of the panel")
    s.add_argument("-o", "--out"); s.add_argument("--json", action="store_true"); s.add_argument("--strict", action="store_true")
    s.set_defaults(fn=cmd_design)

    s = sub.add_parser("style", help="art direction revisions: list, show, revise (effective from a chapter or beat)")
    s.add_argument("op", choices=["list", "show", "revise", "pin"]); s.add_argument("target", nargs="?")
    s.add_argument("--rev", help="pin: revision to pin the chapter to (--note is the reason)")
    s.add_argument("--base"); s.add_argument("--from-chapter"); s.add_argument("--from-beat")
    s.add_argument("--rules", help="YAML file of rule overrides"); s.add_argument("--note")
    s.add_argument("--no-pin", action="store_true", help="revise: do not pin earlier chapters")
    s.add_argument("--chapter"); s.add_argument("--beat")
    s.set_defaults(fn=cmd_style)

    s = sub.add_parser("work", help="director work units: plan, status, next (context packet), start, done, run, resume, approve, decide")
    s.add_argument("op", choices=["plan", "status", "next", "show", "context", "start", "done", "block", "run", "resume",
                                  "approve", "decide", "gates", "art-style", "wait", "metrics"])
    s.add_argument("target", nargs="?", help="unit id | gate name | decision subject")
    s.add_argument("subject", nargs="?", help="approve: the gated subject (chapter id)")
    s.add_argument("--chapter"); s.add_argument("--all", action="store_true")
    s.add_argument("--output", action="append"); s.add_argument("--note"); s.add_argument("--image-calls", type=int)
    s.add_argument("--limit", type=int); s.add_argument("--skill", action="append")
    s.add_argument("--by", help="approve: the creator who gave the approval")
    s.add_argument("--decision"); s.add_argument("--reason"); s.add_argument("--refs", nargs="*")
    s.add_argument("--rev", help="art-style: the style revision the drawing was judged to meet")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(fn=cmd_work)

    s = sub.add_parser("publish", help="freeze a chapter proof set (manifests) / rebuild it / list sets")
    s.add_argument("op", nargs="?", default="create", choices=["create", "rebuild", "list"])
    s.add_argument("name", nargs="?"); s.add_argument("--chapter"); s.add_argument("--final", action="store_true")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_publish)

    s = sub.add_parser("metrics", help="pilot metrics: illustration calls per accepted panel, art calls from lettering/mask edits")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_metrics)

    s = sub.add_parser("story", help="story records: check, impact, glance (beat sheet), state, deps")
    s.add_argument("op", choices=["check", "impact", "glance", "state", "deps"])
    s.add_argument("target", nargs="?", help="impact: line id | beat id | event id | subject.attribute; state: beat id")
    s.add_argument("--chapter")
    s.add_argument("--text", help="impact on a line: try this wording (fit + leak checks)")
    s.add_argument("--set", help="impact on a fact/event: try this value (hypothetical story check)")
    s.add_argument("-o", "--out")
    s.add_argument("--json", action="store_true")
    s.add_argument("--strict", action="store_true", help="check: exit 1 on warnings")
    s.add_argument("--no-pages", action="store_true", help="check: skip page cross-checks")
    s.set_defaults(fn=cmd_story)

    s = sub.add_parser("rough", help="procedural rough sketches (kind=rough assets) from art/roughs/<id>.py")
    s.add_argument("op", choices=["make", "list"])
    s.add_argument("id", nargs="?", help="asset id (make: omit to build every art/roughs/*.py)")
    s.add_argument("source", nargs="?", help="sketch source (default art/roughs/<id>.py)")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_rough)

    s = sub.add_parser("board", help="chapter plan, board checks, lettered roughs/spreads/page turns, alternates")
    s.add_argument("op", choices=["plan", "check", "render", "alt", "alts", "compare", "promote"])
    s.add_argument("target", nargs="?", help="alt: page id; compare: names (current,b,c); promote: alt name")
    s.add_argument("name", nargs="?", help="alt: new alternate name")
    s.add_argument("--chapter"); s.add_argument("--alt", help="check/render with this alternate set")
    s.add_argument("--from", dest="from_alt", help="alt: copy from this alternate instead of the current page")
    s.add_argument("--per-page", type=int, default=5, help="plan: panels per new page")
    s.add_argument("--write", action="store_true", help="plan: save chapters/<ch>/board.yaml (and new pages in chapter.yaml)")
    s.add_argument("--stubs", action="store_true", help="plan: write stub page sources for planned pages without one")
    s.add_argument("--reason"); s.add_argument("--force", action="store_true"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--all", action="store_true", help="check: include every technical page check")
    s.add_argument("--json", action="store_true"); s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_board)

    s = sub.add_parser("review", help="cold-read packets and scores, aggregate technical pass, art vs story, findings, recheck")
    s.add_argument("op", choices=["packet", "answers", "key", "score", "tech", "art", "add", "set", "editorial", "decide",
                                  "verdict", "recheck", "list", "metrics"])
    s.add_argument("target", nargs="?", help="answers: file; set/editorial/decide/verdict: finding id")
    s.add_argument("name", nargs="?", help="decide: alternative name; verdict: verified|survived")
    s.add_argument("--chapter"); s.add_argument("--round", help="cold-read round (default: latest)")
    s.add_argument("--pages", help="packet: only the spreads of these pages (a recheck read)")
    s.add_argument("--force", action="store_true"); s.add_argument("--no-file", action="store_true", help="report only")
    s.add_argument("--verdicts", help="art: yaml list of {page, panel, ok, observed, intended, owner, severity}")
    s.add_argument("--page"); s.add_argument("--panel", dest="panel_id"); s.add_argument("--region", help="x0,y0,x1,y1 page units")
    s.add_argument("--code"); s.add_argument("--severity", choices=["error", "warn", "info"])
    s.add_argument("--owner", help="story|design|board|illustrate|compose|direct (list: comma-separated filter)")
    s.add_argument("--observed"); s.add_argument("--intended"); s.add_argument("--title"); s.add_argument("--key")
    s.add_argument("--evidence", action="append"); s.add_argument("--probe", help='json, e.g. {"kind":"tail-gap","line":"line-02","max":40}')
    s.add_argument("--status", help="set: open|fixed|verified|wont-fix|editorial; list: filter")
    s.add_argument("--note"); s.add_argument("--reason"); s.add_argument("--by")
    s.add_argument("--alt", action="append", help='editorial: "name|owner|description" (repeat)')
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("render", help="render a page view")
    s.add_argument("page", help="page id (p003) or path to page source")
    s.add_argument("--alt", help="render the alternate layout <page>.alt-<name>.py")
    s.add_argument("--view", default="proof", choices=["proof", "rough", "guide", "masks", "reading", "detail", "export"])
    s.add_argument("--panel", help="panel id (guide view)")
    s.add_argument("--region", help="x0,y0,x1,y1 page units (detail view)")
    s.add_argument("--profile", help="output profile (export view), default print")
    s.add_argument("--dpi", type=float); s.add_argument("--height", type=int, help="px (reading view)")
    s.add_argument("--chapter"); s.add_argument("-o", "--out"); s.add_argument("--force", action="store_true")
    s.add_argument("-q", "--quiet", action="store_true")
    s.add_argument("--pin", action="append", help="asset=vNNN or asset:mask=mNNN; trial a candidate without selecting it")
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("check", help="technical checks (exit 2 on errors, 1 on warnings with --strict)")
    s.add_argument("page", nargs="?", default="all"); s.add_argument("--chapter")
    s.add_argument("--strict", action="store_true"); s.add_argument("--json", action="store_true")
    s.add_argument("--pin", action="append", help="asset=vNNN or asset:mask=mNNN")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("spread", help="spread view(s) honoring reading direction + pairing")
    s.add_argument("page", nargs="?", default="all"); s.add_argument("--chapter"); s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_spread)

    s = sub.add_parser("contact", help="chapter contact sheet")
    s.add_argument("--chapter"); s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_contact)

    s = sub.add_parser("rebuild", help="re-render a proof from its manifest pins and compare bytes")
    s.add_argument("manifest"); s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_rebuild)

    s = sub.add_parser("docs", help="print the path of the mangakit docs folder (or of one doc)")
    s.add_argument("name", nargs="?", help="e.g. page-api, cli, direct-reference")
    s.set_defaults(fn=cmd_docs)

    s = sub.add_parser("hash", help="sha256 of files/dirs (prove art bytes unchanged)")
    s.add_argument("paths", nargs="+")
    s.set_defaults(fn=cmd_hash)

    a = ap.parse_args(argv)
    if a.cmd == "asset":
        _asset_positional(a)
    try:
        a.fn(a)
    except MangakitError as e:
        print(f"mangakit: error: {e}", file=sys.stderr)
        sys.exit(2)


def _asset_positional(a):
    r = a.rest
    a.file = a.version_pos = a.name = a.x = a.y = None
    if a.op == "add":
        a.file = r[0] if r else None
    elif a.op == "select":
        a.version = r[0] if r else a.version
    elif a.op == "landmark":
        if len(r) != 3:
            raise SystemExit("usage: mangakit asset landmark ASSET NAME X Y [--version V] [--protect]")
        a.name, a.x, a.y = r[0], float(r[1]), float(r[2])


if __name__ == "__main__":
    main()
