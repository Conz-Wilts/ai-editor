#!/usr/bin/env python3
"""The look pass in words: what code cannot measure, named by Claude from frame sheets.

  prompt           prints the prompt and schema for the haiku agent that reads each video's
                   sheets/<id>.jpg and writes video/<id>.look-ai.json (references/look-pass.md).
  merge <handle>   folds every video/<id>.look-ai.json into style.json "look" (majority
                   per field), sets captions.font_match, rewrites look.md.
  demo             self-check. No network.

Numbers never come from here: size, place, colours, timings are look.py's. Only the
categories the model names land in style.json, plus captions.font_match.

Usage:
  ~/.ai-video-editor/venv/bin/python scripts/lookpass.py prompt
  ~/.ai-video-editor/venv/bin/python scripts/lookpass.py merge <handle>

Exit codes: 0 ok - 1 error - 2 usage
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import OUT_ROOT, slug  # noqa: E402

SOURCE = "sheet"   # look.source when the per-video files name none
FONTS = ["Montserrat", "Poppins", "Inter", "Roboto", "TikTok Sans", "Archivo Black", "Anton",
         "Bebas Neue", "Oswald", "Nunito", "Playfair Display", "DM Serif Display", "Caveat",
         "Permanent Marker", "JetBrains Mono"]
WEIGHT = {"regular": 400, "medium": 500, "semibold": 600, "bold": 700, "extra bold": 800, "black": 900}


def enum(*v):
    return {"type": "STRING", "enum": list(v)}


def many(*v):
    return {"type": "ARRAY", "items": enum(*v)}


SCHEMA = {"type": "OBJECT", "properties": {
    "font_class": enum("geometric sans", "grotesk", "serif", "condensed", "handwritten", "mono",
                       "rounded", "no captions"),
    "closest_google_font": enum(*FONTS),
    "font_confidence": enum("high", "medium", "low"),
    "weight_class": enum(*WEIGHT),
    "caption_case": enum("lower", "upper", "sentence"),
    "caption_animation": enum("pop", "word_highlight", "slide", "typewriter", "fade", "none"),
    "graphics_style": many("real screenshots", "screen recordings", "logos", "stock footage",
                           "stock photos", "illustrated", "3D", "memes", "text cards", "charts",
                           "none"),
    "motion_personality": enum("snappy", "smooth", "punchy", "calm"),
    "transitions": many("hard cut", "jump cut", "zoom punch", "whip", "slide", "fade", "glitch",
                        "none"),
    "broll_types": many("screen recording", "product UI", "app screenshot", "website", "article",
                        "social post", "stock video", "photo", "meme", "news clip", "green screen",
                        "animation", "none"),
    "not_generic": {"type": "ARRAY", "items": {"type": "STRING"}},
}, "required": ["font_class", "closest_google_font", "font_confidence", "weight_class", "caption_case",
                "caption_animation", "graphics_style", "motion_personality", "transitions",
                "broll_types", "not_generic"]}

PROMPT = """You are describing the editing look of a short-form video so another editor can copy it.
Judge only what is on screen. Captions are the words burned in that follow the speech.
- font_class, closest_google_font, weight_class, caption_case, caption_animation: the captions.
  closest_google_font is the nearest free font in the list, by letter shapes. font_confidence: high only
  when the letter shapes (a, g, t, R) clearly match that font, low when it is a generic sans guess.
- graphics_style: every kind of visual laid over or cut in, besides the speaker.
- motion_personality: snappy (fast, instant), smooth (eased, gliding), punchy (hard hits, zooms
  on beats), calm (few cuts, long holds).
- not_generic: 3 to 5 short, specific things that set this look apart from a default captioned
  talking head (a colour, a placement, a recurring device). Concrete, under 15 words each."""


def mode(xs):
    xs = [x for x in xs if x]
    return Counter(xs).most_common(1)[0][0] if xs else None


def merge_rows(rows, source):
    """Majority per field; list fields keep what at least half the videos show."""
    n = len(rows)
    look = {"source": source, "videos": n}
    for k in ("font_class", "closest_google_font", "weight_class", "caption_case",
              "caption_animation", "motion_personality"):
        look[k] = mode(r.get(k) for r in rows)
    for k in ("graphics_style", "transitions", "broll_types"):
        c = Counter(x for r in rows for x in set(r.get(k) or []))
        look[k] = [x for x, m in c.most_common() if m >= n / 2 and x != "none"] or \
                  [x for x, _ in c.most_common(2)]
    seen, ng = set(), []
    for r in rows:
        for x in r.get("not_generic") or []:
            if x.lower() not in seen:
                seen.add(x.lower())
                ng.append(x)
    look["not_generic"] = ng[:6]
    # The font is a guess by eye. It counts as measured only when 3+ videos agree on it (75%) and most of
    # those say high confidence; report.py words a font tell as a guess otherwise.
    font = look["closest_google_font"]
    agree = [r for r in rows if r.get("closest_google_font") == font]
    look["font_votes"] = len(agree)
    look["font_confident"] = bool(font) and n >= 3 and len(agree) >= 0.75 * n and \
        sum(r.get("font_confidence") == "high" for r in agree) > len(agree) / 2
    return look


def apply(style, look):
    """Puts the words into style.json. Numbers from look.py are never overwritten."""
    style["look"] = look
    cap = style.setdefault("captions", {})
    if cap.get("present") is not False and look.get("font_class") != "no captions":
        cap["font_match"] = look.get("closest_google_font") or cap.get("font_match")
        cap.setdefault("weight", WEIGHT.get(look.get("weight_class")))
        if cap.get("present") is None:  # no OCR ran: the model's categories stand in
            cap["case"] = cap.get("case") or look.get("caption_case")
            cap["animation"] = cap.get("animation") or look.get("caption_animation")
        cap["source"] = {**(cap.get("source") or {}), "font": look["source"]}
    return style


def cmd_merge(a):
    outdir = OUT_ROOT / slug(a.handle)
    files = sorted((outdir / "video").glob("*.look-ai.json"))
    if not files:
        sys.exit("no video/*.look-ai.json yet. Run the sheet pass first (references/look-pass.md).")
    rows = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    source = mode(r.get("_source") for r in rows) or SOURCE
    sp = outdir / "style.json"
    style = apply(json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"handle": slug(a.handle)},
                  merge_rows(rows, source))
    sp.write_text(json.dumps(style, indent=2), encoding="utf-8")
    from look import write_summary
    print(write_summary(outdir))
    print(f"-> {sp}")


def demo():
    r1 = {"font_class": "grotesk", "closest_google_font": "TikTok Sans", "weight_class": "bold",
          "caption_case": "lower", "caption_animation": "pop", "graphics_style": ["real screenshots", "logos"],
          "motion_personality": "punchy", "transitions": ["jump cut"], "broll_types": ["screen recording"],
          "not_generic": ["white one-word captions low on the chest"]}
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])
    r2 = dict(r1, closest_google_font="Inter", graphics_style=["real screenshots"],
              not_generic=["White one-word captions low on the chest", "screenshots slide up"])
    r3 = dict(r1, graphics_style=["memes"])
    look = merge_rows([r1, r2, r3], SOURCE)
    assert look["closest_google_font"] == "TikTok Sans" and look["graphics_style"] == ["real screenshots"]
    # a font counts as measured only when 3+ videos agree (75%) and most say high confidence
    assert look["font_votes"] == 2 and look["videos"] == 3 and look["font_confident"] is False, look
    sure = merge_rows([dict(r1, font_confidence="high")] * 3 + [dict(r1, closest_google_font="Inter")], SOURCE)
    assert sure["font_votes"] == 3 and sure["font_confident"] is True, sure
    unsure = merge_rows([dict(r1, font_confidence="low")] * 4, SOURCE)
    assert unsure["font_confident"] is False, unsure
    assert "font_confidence" in SCHEMA["required"]
    assert look["not_generic"] == ["white one-word captions low on the chest", "screenshots slide up"]
    style = apply({"captions": {"present": True, "weight": 600, "size_pct": 4.4}}, look)
    c = style["captions"]
    assert c["font_match"] == "TikTok Sans" and c["weight"] == 600 and c["size_pct"] == 4.4, c
    style = apply({"captions": {"present": False}}, look)
    assert "font_match" not in style["captions"]
    print("ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("merge")
    p.add_argument("handle")
    p.set_defaults(fn=cmd_merge)
    sub.add_parser("prompt").set_defaults(fn=lambda a: print(
        PROMPT + "\n\nAnswer with JSON only, matching this schema:\n" + json.dumps(SCHEMA, indent=1)))
    sub.add_parser("demo").set_defaults(fn=lambda a: demo())
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
