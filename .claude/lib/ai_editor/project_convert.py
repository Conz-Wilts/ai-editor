#!/usr/bin/env python3
"""plan.json <-> project.json, and keeping the user's work when plan.py runs again. Stdlib only.

    from_plan(plan, name=None) -> project      every plan key lands on a track item or in planExtras
    to_plan(project, format_id=None) -> plan   the inverse: to_plan(from_plan(p)) == p for any plan.py output
    merge(old, new) -> project                 a re-plan (new) laid over the project the user edited (old):
                                               ids kept by anchor, pinned / user / claude items never lost
    sync(edit_dir) -> project                  plan.json (+ an old overrides.json, migrated once) into project.json

Matching a re-planned item to the one already there: a card by its anchor (trigger word, start) within
preview.py's MATCH_S (0.75 s), a zoom by its start within ZOOM_MATCH_S (0.4 s), a caption or cue by its start
within 0.05 s and the same words or file. A matched plan item keeps its id; a pinned one keeps its own values.

    python3 project_convert.py demo
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_schema as ps  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "style-edit" / "scripts"
MATCH_S, ZOOM_MATCH_S, NEAR_S = 0.75, 0.4, 0.05
MODELED = ("video", "width", "height", "fps", "durationInFrames", "captions", "zooms", "cards", "sfx", "music")
CARD_KEYS = ("start", "end", "src", "anim", "box", "entrance", "layout", "lane", "trigger_word")
SFX_LEN_S = 0.5   # a cue's block on the timeline (the file plays to its end either way)


def _preview():
    sys.path.insert(0, str(SCRIPTS))
    import preview  # noqa: E402
    return preview


try:   # one source for the match windows (preview.py is the live preview's server; it imports only stdlib)
    _p = _preview()
    MATCH_S, ZOOM_MATCH_S = _p.MATCH_S, _p.ZOOM_MATCH_S
except Exception:
    pass


def frames(s, fps):
    return int(round(float(s) * fps))


def _span(start, end, fps):
    f = frames(start, fps)
    return f, max(1, frames(end, fps) - f)


def _item(kind, origin, f, d, sec, **kw):
    return {"id": ps.mint(), "type": kind, "from": f, "durationInFrames": d, "origin": origin, "pinned": False,
            "sec": sec, **{k: v for k, v in kw.items() if v is not _MISSING}}


_MISSING = object()


def from_plan(plan, name=None):
    plan = copy.deepcopy(plan)
    fps = int(plan["fps"])
    present = [k for k in MODELED if k in plan]
    doc = {"schema": ps.SCHEMA, "id": ps.mint("prj"), "name": name or Path(plan.get("video", "edit")).stem, "rev": 0,
           "fps": fps, "width": int(plan["width"]), "height": int(plan["height"]),
           "durationInFrames": int(plan["durationInFrames"]), "format": None, "formats": [], "designSystem": None,
           "assets": {}, "tracks": [], "planExtras": {k: v for k, v in plan.items() if k not in MODELED},
           "source": {"plan": "plan.json"}}
    doc["planExtras"]["_present"] = present
    tracks = {r: ps.new_track(r) for r in ps.TRACK_ORDER}
    if "video" in plan:
        doc["assets"]["ast_cut"] = {"kind": "video", "src": plan["video"], "origin": "cut"}
        tracks["main"]["items"].append({"id": ps.mint(), "type": "video", "asset": "ast_cut", "from": 0,
                                        "durationInFrames": int(plan["durationInFrames"]), "trimIn": 0,
                                        "origin": "plan", "pinned": False})
    cap = plan.get("captions")
    if isinstance(cap, dict):
        tracks["captions"]["props"] = {k: v for k, v in cap.items() if k != "chunks"}
        tracks["captions"]["props"]["_chunks"] = "chunks" in cap
        for ch in cap.get("chunks") or []:
            f, d = _span(ch["start"], ch["end"], fps)
            tracks["captions"]["items"].append(_item("caption", "plan", f, d, {"start": ch["start"], "end": ch["end"]},
                                                     props={k: v for k, v in ch.items() if k not in ("start", "end")}))
    elif "captions" in plan:
        tracks["captions"]["props"] = {"_raw": cap}
    for z in plan.get("zooms") or []:
        f, d = _span(z["start"], z["end"], fps)
        tracks["zooms"]["items"].append(_item("zoom", "plan", f, d, {"start": z["start"], "end": z["end"]},
                                              props={k: v for k, v in z.items() if k not in ("start", "end")}))
    for c in plan.get("cards") or []:
        f, d = _span(c["start"], c["end"], fps)
        anim = c.get("anim")
        extra = {k: v for k, v in c.items() if k not in CARD_KEYS}
        if isinstance(anim, dict):
            rest = {k: v for k, v in anim.items() if k not in ("type", "props")}
            extra["_anim"] = {"rest": rest, "props": "props" in anim}
        box = c.get("box", _MISSING)
        it = _item("card", "plan", f, d, {"start": c["start"], "end": c["end"]},
                   src=c.get("src", _MISSING),
                   component=anim.get("type") if isinstance(anim, dict) else _MISSING,
                   props=anim.get("props") if isinstance(anim, dict) and "props" in anim else _MISSING,
                   box={"units": "frame", "x": box[0], "y": box[1], "w": box[2], "h": box[3]}
                   if isinstance(box, list) and len(box) == 4 else box,
                   entrance=c.get("entrance", _MISSING), layout=c.get("layout", _MISSING), lane=c.get("lane", _MISSING),
                   anchor={"word": c["trigger_word"] if "trigger_word" in c else None, "t": c["start"]},
                   extra=extra)
        if "override" in c:   # placed by hand in the old live preview: the user's, so a re-plan never moves it
            it["pinned"] = True
        tracks["cards"]["items"].append(it)
    for q in plan.get("sfx") or []:
        f = frames(q["t"], fps)
        tracks["sfx"]["items"].append(_item("audio", "plan", f, max(1, frames(SFX_LEN_S, fps)), {"start": q["t"]},
                                            src=q.get("src", _MISSING),
                                            props={k: v for k, v in q.items() if k not in ("t", "src")}))
    if isinstance(plan.get("music"), dict):
        m = plan["music"]
        tracks["music"]["items"].append(_item("audio", "plan", 0, max(1, int(plan["durationInFrames"])), None,
                                              src=m.get("src", _MISSING),
                                              props={k: v for k, v in m.items() if k != "src"}))
    elif "music" in plan:
        tracks["music"]["props"] = {"_raw": plan["music"]}
    doc["tracks"] = [tracks[r] for r in ps.TRACK_ORDER]
    for t in doc["tracks"]:
        for it in t["items"]:
            if it.get("sec") is None:
                it.pop("sec", None)
    return doc


def _sec(it, fps, which):
    """The plan's own seconds while the item still sits on them, else the frame in seconds (3 places)."""
    sec = it.get("sec") or {}
    f = it["from"] if which == "start" else it["from"] + it["durationInFrames"]
    if which in sec and frames(sec[which], fps) == f:
        return sec[which]
    return round(f / fps, 3)


def _box_out(box, doc, fmt):
    if not isinstance(box, dict) or box.get("units") not in ("frame", "safe"):
        return box
    if box["units"] == "safe" and fmt:
        l, t, r, b = fmt["safe_pct"]
        return [round(l + box["x"] * (100 - l - r) / 100, 2), round(t + box["y"] * (100 - t - b) / 100, 2),
                round(box["w"] * (100 - l - r) / 100, 2), round(box["h"] * (100 - t - b) / 100, 2)]
    return [box["x"], box["y"], box["w"], box["h"]]


def _format(format_id):
    """{"width", "height", "safe_pct": (l, t, r, b)} from formats.py, or None while it does not exist."""
    if not format_id:
        return None
    try:
        import formats   # Phase 3 (formats.json); absent: keep the project's own size
    except ImportError:
        return None
    try:
        f = formats.get(format_id)
        return {"width": int(f["width"]), "height": int(f["height"]), "safe_pct": tuple(formats.safe_pct(format_id))}
    except Exception:
        return None


def _design_look(sid):
    """The compiled Look of design system `sid` (design.py), or None (unset, unknown or broken: the plan's own look)."""
    if not sid:
        return None
    try:
        from ai_editor import design
    except ImportError:
        try:
            import design
        except ImportError:
            return None
    try:
        return design.compile(sid)
    except Exception:   # noqa: BLE001  a broken user system never stops an export
        return None


def to_plan(doc, format_id=None):
    fps = doc["fps"]
    fmt = _format(format_id or doc.get("format"))
    present = list(doc.get("planExtras", {}).get("_present", []))
    plan = {k: copy.deepcopy(v) for k, v in doc.get("planExtras", {}).items() if k != "_present"}
    by = {t["role"]: t for t in doc["tracks"]}
    # a hidden track exports nothing (the main track stays: it is the footage); a muted one plays silent
    get = lambda r: [it for it in by[r]["items"]] if r in by and (r == "main" or not by[r].get("hidden")) else []
    muted = lambda r: bool(by.get(r, {}).get("muted"))

    def has(key, items):
        return key in present or bool(items)
    main = sorted(get("main"), key=lambda it: it["from"])
    if main:
        first = main[0]
        plan["video"] = doc["assets"].get(first.get("asset"), {}).get("src", first.get("src"))
        if len(main) > 1 or first["from"] or first.get("trimIn") or first.get("fit") not in (None, "cover") or muted("main"):
            plan["clips"] = [{"src": doc["assets"].get(it.get("asset"), {}).get("src", it.get("src")), "from": it["from"],
                              "durationInFrames": it["durationInFrames"], "trimIn": it.get("trimIn", 0),
                              **({"volume": 0} if muted("main") else {"volume": it["volume"]} if "volume" in it else {}),
                              **({"fit": it["fit"]} if "fit" in it else {}),
                              **({"reframe": it["reframe"]} if it.get("reframe") else {})} for it in main]
    plan["width"], plan["height"] = (fmt["width"], fmt["height"]) if fmt else (doc["width"], doc["height"])
    if fmt:   # formats.for_plan / plan_safe_pct read it: the safe zone of this platform, not just the shape
        plan["format"] = format_id or doc.get("format")
    plan["fps"] = fps
    plan["durationInFrames"] = ps.derive_duration(doc)
    look = _design_look(doc.get("designSystem"))
    if look:   # the project's design system wins over the plan's own look (planExtras.look, copied above)
        plan["look"] = look
    ct = by.get("captions", {})
    caps = get("captions")
    if "_raw" in (ct.get("props") or {}):
        plan["captions"] = copy.deepcopy(ct["props"]["_raw"])
    elif has("captions", caps):
        props = {k: copy.deepcopy(v) for k, v in (ct.get("props") or {}).items() if k != "_chunks"}
        chunks = []
        for it in caps:
            ch = copy.deepcopy(it.get("props") or {})
            s0 = (it.get("sec") or {}).get("start")
            ch["start"], ch["end"] = _sec(it, fps, "start"), _sec(it, fps, "end")
            if s0 is not None and ch["start"] != s0 and isinstance(ch.get("words"), list):
                d = ch["start"] - s0   # a moved caption carries its words with it
                for w in ch["words"]:
                    for k in ("start", "end"):
                        if isinstance(w.get(k), (int, float)):
                            w[k] = round(w[k] + d, 3)
            chunks.append(ch)
        if (ct.get("props") or {}).get("_chunks", True) or chunks:
            props["chunks"] = chunks
        plan["captions"] = props
    zs = get("zooms")
    if has("zooms", zs):
        plan["zooms"] = [{**copy.deepcopy(it.get("props") or {}), "start": _sec(it, fps, "start"), "end": _sec(it, fps, "end")}
                         for it in zs]
    cs = get("cards")
    if has("cards", cs):
        out = []
        for it in sorted(cs, key=lambda it: it["from"]) if any(i["origin"] != "plan" for i in cs) else cs:
            extra = copy.deepcopy(it.get("extra") or {})
            ameta = extra.pop("_anim", None)
            c = {**extra}
            if "src" in it:
                c["src"] = it["src"]
            if "component" in it:
                anim = {"type": it["component"], **((ameta or {}).get("rest") or {})}
                if (ameta or {}).get("props", "props" in it) and "props" in it:
                    anim["props"] = copy.deepcopy(it["props"])
                c["anim"] = anim
            c["start"], c["end"] = _sec(it, fps, "start"), _sec(it, fps, "end")
            fb = (it.get("boxByFormat") or {}).get(format_id or doc.get("format") or "")
            if fb is not None or "box" in it:
                c["box"] = _box_out(fb if fb is not None else it["box"], doc, fmt)
            for k in ("entrance", "layout", "lane"):
                if k in it:
                    c[k] = it[k]
            word = (it.get("anchor") or {}).get("word")
            if word is not None:
                c["trigger_word"] = word
            out.append(c)
        plan["cards"] = out
    sx = [] if muted("sfx") else get("sfx")
    if has("sfx", sx):
        plan["sfx"] = [{**copy.deepcopy(it.get("props") or {}), "t": _sec(it, fps, "start"),
                        **({"src": it["src"]} if "src" in it else {})} for it in sx]
    mt, ms = by.get("music", {}), [] if muted("music") else get("music")
    if muted("music") or mt.get("hidden"):
        plan.pop("music", None)
    elif "_raw" in (mt.get("props") or {}):
        plan["music"] = copy.deepcopy(mt["props"]["_raw"])
    elif ms:
        m = ms[0]
        plan["music"] = {**({"src": m["src"]} if "src" in m else {}), **copy.deepcopy(m.get("props") or {})}
    extra_tracks = {r: get(r) for r in ("broll", "generated")}
    for r, its in extra_tracks.items():
        if its:   # read by the renderer from Phase 2 (Footage.tsx); seconds like every other plan list
            plan[r] = [{"src": doc["assets"].get(it.get("asset"), {}).get("src", it.get("src")),
                        "start": _sec(it, fps, "start"), "end": _sec(it, fps, "end"), "trimIn": it.get("trimIn", 0),
                        **({"box": _box_out(it["box"], doc, fmt)} if "box" in it else {}),
                        **({"props": {**(it.get("props") or {}), "volume": 0}} if muted(r)
                           else {"props": it["props"]} if "props" in it else {})} for it in its]
    return plan


def _key(role, it):
    return (it.get("anchor") or {}).get("word"), (it.get("sec") or {}).get("start", it["from"])


def _match(role, old, new, fps):
    if role == "cards":
        a, b = old.get("anchor") or {}, new.get("anchor") or {}
        return a.get("word") == b.get("word") and abs(float(a.get("t", 0)) - float(b.get("t", 0))) < MATCH_S
    t_old = (old.get("sec") or {}).get("start", old["from"] / fps)
    t_new = (new.get("sec") or {}).get("start", new["from"] / fps)
    if role == "zooms":
        return abs(t_old - t_new) < ZOOM_MATCH_S
    if role == "captions":
        return abs(t_old - t_new) < NEAR_S and (old.get("props") or {}).get("text") == (new.get("props") or {}).get("text")
    if role == "sfx":
        return abs(t_old - t_new) < NEAR_S and old.get("src") == new.get("src")
    return True   # main, music: by position


def merge(old, new):
    """new (a fresh from_plan) laid over old (the project the user edited)."""
    doc = copy.deepcopy(new)
    fps = doc["fps"]
    for k in ("id", "name", "rev", "format", "formats", "designSystem"):
        if k in old:
            doc[k] = copy.deepcopy(old[k])
    doc["assets"] = {**{k: v for k, v in old.get("assets", {}).items() if v.get("origin") != "cut"}, **doc["assets"]}
    olds = {t["role"]: t for t in old["tracks"]}
    for t in doc["tracks"]:
        o = olds.get(t["role"])
        if not o:
            continue
        for k in ("id", "name", "muted", "hidden", "locked"):
            t[k] = o.get(k, t[k])
        kept = [it for it in o["items"] if it["origin"] != "plan" or it.get("pinned")]
        free = [it for it in o["items"] if it["origin"] == "plan" and not it.get("pinned")]
        items = []
        for i, it in enumerate(t["items"]):
            pos = t["role"] in ("main", "music")
            pin = None if pos else next((k for k in kept if _match(t["role"], k, it, fps)), None)
            if pin is not None:
                continue   # the user's own version of this item stays (it is in kept)
            hit = (free[i] if i < len(free) else None) if pos else next((f for f in free if _match(t["role"], f, it, fps)), None)
            if hit is not None:
                free.remove(hit)
                it["id"] = hit["id"]
            items.append(it)
        t["items"] = sorted(items + kept, key=lambda it: it["from"]) if kept else items
    roles = {t["role"] for t in doc["tracks"]}
    doc["tracks"] += [copy.deepcopy(t) for t in old["tracks"] if t["role"] not in roles]   # tracks the user added
    doc["durationInFrames"] = ps.derive_duration(doc, new["durationInFrames"])
    return doc


def sync(edit_dir, plan_name="plan.json"):
    """plan.json into project.json (new, or merged over the user's edits through project_store)."""
    import project_store
    import hashlib
    d = Path(edit_dir)
    raw = (d / plan_name).read_bytes()
    plan = json.loads(raw)
    pj = d / "project.json"
    if pj.exists():
        try:
            mine = json.loads((d / "project.export.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            mine = {}
        if hashlib.sha256(raw).hexdigest() in mine.values():
            return json.loads(pj.read_text(encoding="utf-8"))   # the project's own export, not a plan.py run
    if (d / "overrides.json").exists() and not (pj.exists() and json.loads(pj.read_text(encoding="utf-8"))
                                                .get("source", {}).get("overridesMigrated")):
        plan = _preview().apply_overrides(plan, d, plan_name)   # the old live preview's hand placements, once
    new = from_plan(plan, name=d.name)
    new["source"] = {"plan": plan_name, "words": "words.json", "overridesMigrated": (d / "overrides.json").exists()}
    if not pj.exists():
        return project_store.save_new(d, new)
    return project_store.replace(d, lambda old: merge(old, new), author="plan", label=f"sync {plan_name}")


def export(edit_dir, format_ids=(None,)):
    """Write plan.json (no format) or plan-<format>.json from project.json; the files written. Each export's sha256
    goes in project.export.json, so sync knows a plan.json it wrote from one plan.py wrote."""
    import hashlib
    import project_store
    d = Path(edit_dir)
    doc = project_store.load(d)
    f = d / "project.export.json"
    try:
        shas = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        shas = {}
    out = []
    for fid in format_ids or (None,):
        name = f"plan-{fid}.json" if fid else "plan.json"
        raw = json.dumps(to_plan(doc, fid), indent=1).encode("utf-8")
        tmp = d / (name + ".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, d / name)
        shas[name] = hashlib.sha256(raw).hexdigest()
        out.append(d / name)
    f.write_text(json.dumps(shas, indent=1), encoding="utf-8")
    return out


def sample_plan():
    """A plan with every list plan.py writes, and keys the timeline does not model."""
    return {
        "video": "cut.mp4", "width": 1080, "height": 1920, "fps": 30, "durationInFrames": 1800,
        "captions": {"style": {"font_match": "Inter", "y_pct": 72.4, "size_pct": 4.5},
                     "chunks": [{"text": "this is how", "start": 0.1, "end": 0.9, "treat": "shadow",
                                 "words": [{"text": "this", "start": 0.1, "end": 0.3}, {"text": "is", "start": 0.3, "end": 0.5},
                                           {"text": "how", "start": 0.5, "end": 0.9}]},
                                {"text": "notion", "start": 12.37, "end": 12.91, "words": [{"text": "notion", "start": 12.37, "end": 12.91}]}]},
        "zooms": [{"start": 3.2, "end": 7.9, "scale": 1.18, "kind": "punch", "ease_s": 0, "origin": [50, 22]}],
        "cards": [{"src": "images/a.png", "start": 12.4, "end": 15.0, "trigger_word": "notion", "entrance": "pop",
                   "box": [10, 12, 80, 40], "layout": "box", "size": [1200, 800], "highlight": True,
                   "marks": [{"kind": "ring", "rect": [1, 2, 3, 4], "at": 0.8}], "transition_in": "match"},
                  {"anim": {"type": "chat", "props": {"app": "Jev", "messages": [{"from": "user", "text": "small task"}],
                                                      "word_at": 0.1}},
                   "start": 18.0, "end": 20.5, "trigger_word": "faster", "entrance": "pop", "box": [12, 4, 76, 22],
                   "lane": "logo", "layer": "behind", "key": [1, 2, 3, 4]},
                  {"anim": {"type": "flow", "loop": True}, "start": 21.033, "end": 23.0, "layout": "scene", "focus": [50, 30]}],
        "sfx": [{"t": 12.3, "src": ".sfx/pop.wav", "event": 12.4}, {"t": 18.0, "src": ".sfx/whoosh.wav", "event": 18.1, "gain_db": -3}],
        "music": {"src": ".sfx/music.wav", "gain_db": -18},
        "layout": {"mode": "split", "seam": 50, "art": [6, 14, 80, 34]},
        "look": {"ground": "#F2EEE6", "ink": "#111"}, "motion": "snappy", "cutouts": [{"src": "cutout/x", "from": 1, "to": 130}],
        "pans": [], "targets": {"first_graphic_s": 1.2}, "grade": None,
    }


def demo():
    canon = lambda o: json.dumps(o, sort_keys=True)
    p = sample_plan()
    doc = from_plan(p, "demo")
    assert ps.validate(doc) == [], ps.validate(doc)
    assert canon(to_plan(doc)) == canon(p), "round trip"
    roles = {t["role"]: t for t in doc["tracks"]}
    assert [it["type"] for it in roles["cards"]["items"]] == ["card"] * 3 and roles["cards"]["items"][1]["component"] == "chat"
    assert roles["cards"]["items"][0]["box"] == {"units": "frame", "x": 10, "y": 12, "w": 80, "h": 40}
    assert roles["captions"]["items"][1]["from"] == 371 and roles["zooms"]["items"][0]["durationInFrames"] == 141
    for absent in ({"video": "cut.mp4", "width": 1920, "height": 1080, "fps": 25, "durationInFrames": 50},
                   {**sample_plan(), "music": None, "cards": []}):
        assert canon(to_plan(from_plan(absent))) == canon(absent), absent
    # a moved card exports its frame in seconds; a moved caption carries its words
    c0, k1 = roles["cards"]["items"][0], roles["captions"]["items"][1]
    c0["from"] += 15
    k1["from"] += 30
    out = to_plan(doc)
    assert out["cards"][0]["start"] == 12.9 and out["cards"][0]["end"] == 15.5, out["cards"][0]
    assert out["captions"]["chunks"][1]["start"] == 13.367 and out["captions"]["chunks"][1]["words"][0]["start"] == 13.367, out["captions"]["chunks"][1]
    # a named format (formats.json, when it is there): its size and id on the plan
    try:
        import formats
        yt = to_plan(from_plan(sample_plan()), "youtube")
        assert (yt["width"], yt["height"], yt["format"]) == (formats.size("youtube") + ("youtube",)), yt["format"]
    except ImportError:
        pass
    # several clips on the main track
    doc2 = from_plan(sample_plan())
    m = ps.track(doc2, "main")["items"]
    m.append({**m[0], "id": ps.mint(), "from": 1800, "durationInFrames": 300, "trimIn": 120})
    out2 = to_plan(doc2)
    assert out2["durationInFrames"] == 2100 and out2["clips"][1] == {"src": "cut.mp4", "from": 1800, "durationInFrames": 300, "trimIn": 120}
    # re-plan: a card shifted 0.5 s keeps its id; a pinned card and the user's own card survive; a dropped one goes
    old = from_plan(sample_plan(), "demo")
    oc = ps.track(old, "cards")["items"]
    ids = [it["id"] for it in oc]
    oc[1]["pinned"], oc[1]["from"] = True, oc[1]["from"] + 60   # the user moved the chat card
    oc.append({"id": "itm_userown1", "type": "card", "from": 900, "durationInFrames": 60, "origin": "user", "pinned": True,
               "component": "sticker", "props": {}, "box": {"units": "frame", "x": 5, "y": 5, "w": 30, "h": 10}})
    p2 = sample_plan()
    p2["cards"][0]["start"], p2["cards"][0]["end"] = 12.9, 15.5
    p2["cards"][1]["start"] = 18.2
    del p2["cards"][2]
    p2["zooms"][0]["start"] = 3.4
    merged = merge(old, from_plan(p2))
    mc = {it["id"]: it for it in ps.track(merged, "cards")["items"]}
    assert ids[0] in mc and mc[ids[0]]["from"] == 387, "shifted 0.5 s: same id, new time"
    assert ids[1] in mc and mc[ids[1]]["from"] == oc[1]["from"] and mc[ids[1]]["pinned"], "pinned kept as the user left it"
    assert "itm_userown1" in mc and ids[2] not in mc and len(mc) == 3, list(mc)
    assert ps.track(merged, "zooms")["items"][0]["id"] == ps.track(old, "zooms")["items"][0]["id"]
    assert merged["id"] == old["id"] and ps.validate(merged) == [], ps.validate(merged)
    # an old live-preview override (overrides.json) is migrated once and the card it placed is pinned
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "plan.json").write_text(json.dumps(sample_plan()), encoding="utf-8")
        (d / "overrides.json").write_text(json.dumps({"plan": "plan.json", "cards": {"notion@12.400": {"start": 13.0, "end": 15.6}}}),
                                          encoding="utf-8")
        got = sync(d)
        card = next(it for it in ps.track(got, "cards")["items"] if (it.get("anchor") or {}).get("word") == "notion")
        assert card["pinned"] and card["from"] == 390 and got["source"]["overridesMigrated"], card
        again = sync(d)   # plan.py ran again: same ids, nothing duplicated
        assert [it["id"] for it in ps.track(again, "cards")["items"]] == [it["id"] for it in ps.track(got, "cards")["items"]]
        assert again["rev"] == got["rev"] + 1
        # export then sync: the project's own plan.json is not merged back (no duplicates, no new rev)
        import project_store
        project_store.apply(d, {"author": "user", "ops": [{"op": "add", "track": "cards", "item": {
            "type": "card", "from": 60, "durationInFrames": 30, "component": "sticker", "props": {}}}]})
        n = len(ps.track(project_store.load(d), "cards")["items"])
        export(d)
        after = sync(d)
        assert len(ps.track(after, "cards")["items"]) == n and after["rev"] == again["rev"] + 1
        (d / "plan.json").write_text(json.dumps(sample_plan()), encoding="utf-8")   # plan.py ran again
        after = sync(d)
        assert len(ps.track(after, "cards")["items"]) == n, "the user's sticker kept, nothing doubled"
    # a design system's compiled Look replaces the plan's own; an unknown one leaves the plan's look alone
    import design
    ds = from_plan(sample_plan(), "ds")
    ds["designSystem"] = "editorial-dark"
    assert to_plan(ds)["look"] == design.compile("editorial-dark")
    ds["designSystem"] = "no-such-system"
    assert to_plan(ds)["look"] == sample_plan()["look"]
    # updateTrack's flags reach the render: a hidden track exports nothing, a muted one plays silent
    hm = from_plan(sample_plan(), "hm")
    tr = {t["role"]: t for t in hm["tracks"]}
    base = to_plan(hm)
    tr["cards"]["hidden"] = tr["zooms"]["hidden"] = True
    tr["main"]["muted"] = tr["music"]["muted"] = tr["sfx"]["muted"] = True
    out = to_plan(hm)
    assert out["cards"] == [] and out["zooms"] == [] and out["captions"] == base["captions"], out["cards"]
    assert out["clips"] and all(c["volume"] == 0 for c in out["clips"]) and out["video"] == base["video"]
    assert "music" not in out and not out.get("sfx"), (out.get("music"), out.get("sfx"))
    tr["main"]["hidden"] = True
    assert to_plan(hm)["video"] == base["video"], "the main track is the footage: hiding it keeps it"
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        print(__doc__)
        sys.exit(2)
