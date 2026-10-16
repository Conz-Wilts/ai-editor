#!/usr/bin/env python3
"""edits/<name>/project.json: the one timeline document the app and Claude both edit. Stdlib only.

    {"schema": "ai-editor/project@1", "id": "prj_...", "name", "rev", "fps", "width", "height",
     "durationInFrames",                       # the main track's end (or the plan's, when it is empty)
     "format", "formats", "designSystem",      # ids in formats.json / design-systems (null: the plan's own)
     "assets": {"ast_...": {"kind": "video|image|audio", "src", "width"?, "height"?, "fps"?, "durationInFrames"?,
                            "hasAudio"?, "origin": "cut|upload|generated|plan", "generation"?}},
     "tracks": [{"id": "trk_...", "kind": "video|overlay|effect|caption|audio", "role", "name", "muted", "hidden",
                 "locked", "props"?, "items": [ITEM]}],
     "planExtras": {...},                      # plan.json keys the timeline does not model, kept as they were
     "source": {"plan", "planSha"?, "words"?}}

    ITEM: {"id": "itm_...", "type": "video|image|audio|caption|card|zoom|generated", "from", "durationInFrames",
           "trimIn"?, "asset"?, "src"?, "component"?, "props"?, "box"?, "boxByFormat"?, "entrance"?, "layout"?,
           "lane"?, "anchor"?: {"word", "t"}, "origin": "plan|user|claude", "pinned": bool,
           "sec"?: {"start", "end"},              # the plan's own seconds, so an untouched item exports exactly
           "extra"?: {...}}                        # its other plan keys, untouched

Times are integer frames at the project's fps. Ids never change once minted.

    python3 project_schema.py demo
"""
import secrets
import sys

SCHEMA = "ai-editor/project@1"
ROLES = {"main": "video", "broll": "video", "generated": "video", "cards": "overlay", "zooms": "effect",
         "captions": "caption", "music": "audio", "sfx": "audio"}
TRACK_ORDER = ("main", "broll", "generated", "cards", "zooms", "captions", "music", "sfx")
TYPES = ("video", "image", "audio", "caption", "card", "zoom", "generated")
ORIGINS = ("plan", "user", "claude")
_B32 = "abcdefghijklmnopqrstuvwxyz234567"


def mint(prefix="itm"):
    return f"{prefix}_" + "".join(secrets.choice(_B32) for _ in range(8))


def new_track(role, name=None, **kw):
    return {"id": mint("trk"), "kind": ROLES.get(role, "video"), "role": role,
            "name": name or role.capitalize(), "muted": False, "hidden": False, "locked": False, "items": [], **kw}


def find(doc, item_id):
    """(track, index, item) for an item id, or (None, None, None)."""
    for t in doc["tracks"]:
        for i, it in enumerate(t["items"]):
            if it["id"] == item_id:
                return t, i, it
    return None, None, None


def track(doc, ref):
    """A track by id or by role."""
    return next((t for t in doc["tracks"] if t["id"] == ref), None) or next((t for t in doc["tracks"] if t["role"] == ref), None)


def end(it):
    return it["from"] + it["durationInFrames"]


def derive_duration(doc, fallback=None):
    """The main track's end; the stored length when the main track is empty."""
    main = [it for t in doc["tracks"] if t["role"] == "main" and not t.get("hidden") for it in t["items"]]
    return max((end(it) for it in main), default=fallback if fallback is not None else doc.get("durationInFrames", 0))


def validate(doc):
    """[] or a list of problems."""
    errs = []
    if doc.get("schema") != SCHEMA:
        errs.append(f"schema is {doc.get('schema')!r}, not {SCHEMA}")
    for k in ("fps", "width", "height", "durationInFrames", "rev"):
        if not isinstance(doc.get(k), int) or doc[k] < 0:
            errs.append(f"{k} must be a non-negative integer")
    if not isinstance(doc.get("tracks"), list):
        return errs + ["tracks must be a list"]
    seen = set()
    for t in doc["tracks"]:
        if t.get("id") in seen:
            errs.append(f"duplicate id {t.get('id')}")
        seen.add(t.get("id"))
        for it in t.get("items", []):
            where = f"{t.get('role')}/{it.get('id')}"
            if it.get("id") in seen:
                errs.append(f"duplicate id {it.get('id')}")
            seen.add(it.get("id"))
            if it.get("type") not in TYPES:
                errs.append(f"{where}: type {it.get('type')!r}")
            for k in ("from", "durationInFrames"):
                if not isinstance(it.get(k), int) or it[k] < 0:
                    errs.append(f"{where}: {k} must be a non-negative integer")
            if it.get("durationInFrames") == 0 and it.get("type") not in ("audio",):
                errs.append(f"{where}: zero length")
            if it.get("origin") not in ORIGINS:
                errs.append(f"{where}: origin {it.get('origin')!r}")
            if it.get("asset") and it["asset"] not in doc.get("assets", {}):
                errs.append(f"{where}: unknown asset {it['asset']}")
            if "trimIn" in it and (not isinstance(it["trimIn"], int) or it["trimIn"] < 0):
                errs.append(f"{where}: trimIn must be a non-negative integer")
    return errs


def demo():
    a, b = mint(), mint()
    assert a != b and a.startswith("itm_") and len(a) == 12 and set(a[4:]) <= set(_B32)
    doc = {"schema": SCHEMA, "id": mint("prj"), "name": "t", "rev": 0, "fps": 30, "width": 1080, "height": 1920,
           "durationInFrames": 90, "assets": {"ast_cut": {"kind": "video", "src": "cut.mp4", "origin": "cut"}},
           "tracks": [new_track("main"), new_track("cards")], "planExtras": {}, "source": {"plan": "plan.json"}}
    doc["tracks"][0]["items"].append({"id": a, "type": "video", "asset": "ast_cut", "from": 0, "durationInFrames": 90,
                                      "trimIn": 0, "origin": "plan", "pinned": False})
    assert validate(doc) == [], validate(doc)
    assert derive_duration(doc) == 90 and find(doc, a)[1] == 0 and track(doc, "cards")["role"] == "cards"
    doc["tracks"][1]["items"].append({"id": a, "type": "card", "from": -1, "durationInFrames": 3, "origin": "x", "pinned": False})
    errs = validate(doc)
    assert any("duplicate" in e for e in errs) and any("from" in e for e in errs) and any("origin" in e for e in errs), errs
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        print(__doc__)
        sys.exit(2)
