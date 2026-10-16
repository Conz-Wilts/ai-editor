#!/usr/bin/env python3
"""Output formats: canvas size, the platform's UI safe zone and export settings, read from the renderer's
remotion/src/formats.json (the one file the TSX and the Python share).

    from ai_editor import formats
    formats.ids()                      ['vertical', 'shorts', 'tiktok', 'reels', 'vertical-all', 'youtube', ...]
    formats.size("shorts")             (1080, 1920)
    formats.safe_pct("shorts")         (left, top, right, bottom) in % of width / height
    formats.safe_px("youtube")         {"left": 57.6, "top": 54.0, "right": 57.6, "bottom": 108.0}
    formats.legacy_aspect("square")    "9:16": the layout logic plan.py runs for it
    formats.for_size(1920, 1080)       "youtube": the default format of that shape
    formats.for_plan(plan)             plan["format"] when set, else for_size(plan width, height)
    formats.export_args("youtube")     ffmpeg output args (H.264 High, yuv420p, BT.709, AAC 48 kHz)

    python3 formats.py list | show <id> | demo

"vertical" (9:16) and "youtube" (16:9) carry today's zones as exact percentages, so a plan made without a
format renders exactly as before. Stdlib only.
"""
import json
import sys
from pathlib import Path

FILE = Path(__file__).resolve().parents[2] / "remotion" / "src" / "formats.json"
SIDES = ("left", "top", "right", "bottom")
_cache = {}


def load(path=FILE):
    key = str(path)
    if key not in _cache:
        _cache[key] = json.loads(Path(path).read_text(encoding="utf-8"))
    return _cache[key]


def ids():
    return list(load()["formats"])


def default():
    return load()["default"]


def get(fid):
    fs = load()["formats"]
    if fid not in fs:
        raise KeyError(f"unknown format {fid!r}; one of: {', '.join(fs)}")
    return {"id": fid, **fs[fid]}


def size(fid):
    f = get(fid)
    return f["width"], f["height"]


def legacy_aspect(fid):
    return get(fid)["legacyAspect"]


def safe_pct(fid):
    """(left, top, right, bottom): % of the width (left, right) and the height (top, bottom) the app's UI covers."""
    f = get(fid)
    if "safePct" in f:
        return tuple(f["safePct"][s] for s in SIDES)
    w, h = f["width"], f["height"]
    s = f.get("safe") or {}
    return tuple(round(100 * s.get(k, 0) / (w if k in ("left", "right") else h), 4) for k in SIDES)


def safe_px(fid):
    f = get(fid)
    if "safe" in f and "safePct" not in f:   # authored in px: exact
        return {k: float(f["safe"].get(k, 0)) for k in SIDES}
    w, h = f["width"], f["height"]
    return {k: round(v * (w if k in ("left", "right") else h) / 100, 2) for k, v in zip(SIDES, safe_pct(fid))}


def keepouts(fid):
    """Extra rects (px) the platform's UI covers inside the safe zone, e.g. TikTok's button column."""
    return list(get(fid).get("keepout") or [])


def keepouts_pct(fid):
    w, h = size(fid)
    return [[100 * k["x"] / w, 100 * k["y"] / h, 100 * k["w"] / w, 100 * k["h"] / h] for k in keepouts(fid)]


def for_size(w, h):
    """The default format of a canvas: exact size first, else the shape (portrait vertical, landscape youtube)."""
    for fid, f in load()["formats"].items():
        if (f["width"], f["height"]) == (w, h) and fid in ("vertical", "youtube", "youtube-4k", "ig-4x5", "square"):
            return fid
    return "vertical" if h > w else "youtube" if w > h else "square"


def for_plan(plan):
    fid = (plan or {}).get("format")
    return fid if fid in load()["formats"] else for_size((plan or {}).get("width", 1080), (plan or {}).get("height", 1920))


def plan_safe_pct(plan, legacy=None):
    """The safe zone a plan draws inside: its format's, else the legacy zone of its shape (plan.SAFE)."""
    fid = (plan or {}).get("format")
    if fid in load()["formats"]:
        return safe_pct(fid)
    if legacy is not None:
        h, w = (plan or {}).get("height", 1920), (plan or {}).get("width", 1080)
        return tuple(legacy["9:16" if h > w else "16:9"])
    return safe_pct(for_plan(plan))


def export_args(fid):
    """ffmpeg output args for the format's delivery encode (video then audio)."""
    e = get(fid)["export"]
    a = e.get("audio") or {}
    v = ["-c:v", "libx264", "-profile:v", e.get("profile", "high"), "-pix_fmt", e.get("pixelFormat", "yuv420p"),
         "-crf", str(e.get("crf", 18)), "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if e.get("maxrate"):
        v += ["-maxrate", e["maxrate"], "-bufsize", e.get("bufsize", e["maxrate"])]
    return v + ["-c:a", "aac", "-ar", str(a.get("sampleRate", 48000)), "-b:a", a.get("bitrate", "320k"),
                "-movflags", "+faststart"]


def demo():
    # the legacy zones are today's plan.py SAFE numbers, to the digit: old plans render as before
    assert safe_pct("vertical") == (5.6, 13.1, 13.0, 25.0), safe_pct("vertical")
    assert safe_pct("youtube") == (3, 5, 3, 10) and size("youtube") == (1920, 1080) and size("vertical") == (1080, 1920)
    assert safe_px("youtube") == {"left": 57.6, "top": 54.0, "right": 57.6, "bottom": 108.0}, safe_px("youtube")
    # platform zones from px: Shorts 288 top, 672 bottom, 48 left, 192 right
    assert safe_pct("shorts") == (4.4444, 15.0, 17.7778, 35.0), safe_pct("shorts")
    assert safe_px("tiktok") == {"left": 120.0, "top": 240.0, "right": 120.0, "bottom": 660.0}, safe_px("tiktok")
    va = safe_px("vertical-all")
    for f in ("shorts", "tiktok", "reels"):   # the strictest zone covers every vertical app's
        assert all(va[k] >= safe_px(f)[k] for k in ("left", "top", "right", "bottom")), (f, va, safe_px(f))
    assert keepouts("tiktok") == [{"x": 900, "y": 840, "w": 180, "h": 420}] and keepouts("youtube") == []
    assert [round(v, 2) for v in keepouts_pct("tiktok")[0]] == [83.33, 43.75, 16.67, 21.88]
    assert legacy_aspect("square") == "9:16" and legacy_aspect("youtube-4k") == "16:9" and size("ig-4x5") == (1080, 1350)
    assert for_size(1080, 1920) == "vertical" and for_size(1920, 1080) == "youtube" and for_size(3840, 2160) == "youtube-4k"
    assert for_size(1080, 1350) == "ig-4x5" and for_size(1080, 1080) == "square" and for_size(720, 1280) == "vertical"
    assert for_plan({"format": "reels", "width": 1080, "height": 1920}) == "reels" and for_plan({"width": 1920, "height": 1080}) == "youtube"
    assert for_plan({"format": "nope", "width": 1080, "height": 1920}) == "vertical"
    legacy = {"9:16": (5.6, 13.1, 13.0, 25.0), "16:9": (3, 5, 3, 10)}
    assert plan_safe_pct({"width": 1080, "height": 1920}, legacy) == (5.6, 13.1, 13.0, 25.0)
    assert plan_safe_pct({"width": 1080, "height": 1920, "format": "shorts"}, legacy) == safe_pct("shorts")
    a = export_args("youtube")
    assert a[a.index("-maxrate") + 1] == "12M" and a[a.index("-pix_fmt") + 1] == "yuv420p" and "bt709" in a
    assert a[a.index("-ar") + 1] == "48000" and export_args("youtube-4k")[export_args("youtube-4k").index("-maxrate") + 1] == "45M"
    for f in ids():   # every format is whole: a canvas, a zone inside it, an export
        g = get(f)
        l, t, r, b = safe_pct(f)
        assert g["width"] > 0 and g["height"] > 0 and l + r < 100 and t + b < 100 and g["export"]["codec"] == "h264", f
        assert g["legacyAspect"] in ("9:16", "16:9"), f
    try:
        get("cinema")
        raise AssertionError("an unknown format must fail")
    except KeyError as e:
        assert "youtube" in str(e)
    print("demo ok")


def main():
    a = sys.argv[1:]
    if a == ["demo"]:
        return demo()
    if a == ["list"]:
        for f in ids():
            g = get(f)
            print(f"{f:13} {g['width']}x{g['height']}  {g['label']}")
        return
    if a[:1] == ["show"] and len(a) == 2:
        return print(json.dumps({**get(a[1]), "safe_pct": safe_pct(a[1]), "safe_px": safe_px(a[1])}, indent=1))
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
