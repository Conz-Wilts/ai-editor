#!/usr/bin/env python3
"""Face-following reframe for a main-track clip: keyframes [{f, cx, cy}] (clip frames, % of the source) that the
renderer's Footage.tsx eases between when the clip's fit is "reframe", so a wide take cut to 9:16 (or a tall one
to 16:9) keeps the speaker in shot instead of a fixed centre crop. Stdlib only.

face.json (face.py, the head every 0.5 s on cut.mp4) drives it, so it works for clips of the edit's cut. The frame
holds still until the head moves more than DEAD_PCT, then eases to it over EASE_S: a locked-off camera, never
a jittery one.

    python3 reframe.py <edit> <item id>     set fit=reframe + keyframes on that item (project.py apply, author user)
    python3 reframe.py demo
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEAD_PCT = 6.0    # the head must move this far (% of the source) before the frame follows
EASE_S = 0.6      # how long the frame takes to follow
EYE_Y = 0.4       # where in the head box the frame aims (the eyes, not the hair)


def centre(box):
    x, y, w, h = box
    return round(x + w / 2, 2), round(y + h * EYE_Y, 2)


def keyframes(face, fps, trim_in, dur):
    """Keyframes for the clip that plays source frames [trim_in, trim_in + dur) of the cut."""
    heads = [h for h in face.get("heads") or [] if h.get("box")]
    t0, t1 = trim_in / fps, (trim_in + dur) / fps
    inside = [h for h in heads if t0 - 0.5 <= h["t"] <= t1]
    if not inside:
        return []
    ease = max(1, round(EASE_S * fps))
    cur = centre(inside[0]["box"])
    out = [{"f": 0, "cx": cur[0], "cy": cur[1]}]
    for h in inside[1:]:
        c = centre(h["box"])
        if max(abs(c[0] - cur[0]), abs(c[1] - cur[1])) <= DEAD_PCT:
            continue
        f = max(0, round(h["t"] * fps) - trim_in)
        if f >= dur:
            break
        if f > out[-1]["f"]:
            out.append({"f": f, "cx": cur[0], "cy": cur[1]})   # hold until here ...
        out.append({"f": min(dur - 1, f + ease), "cx": c[0], "cy": c[1]})   # ... then ease over
        cur = c
    dedup = []
    for k in out:   # keep frames increasing (a jump right at the end can land on the frame before)
        if dedup and k["f"] <= dedup[-1]["f"]:
            dedup[-1] = k if k["f"] == dedup[-1]["f"] else dedup[-1]
            continue
        dedup.append(k)
    return dedup


def for_item(edit, doc, item_id):
    """The ops batch that turns item_id into a face-following clip. ValueError with a plain reason otherwise."""
    import project_schema as ps
    t, _, it = ps.find(doc, item_id)
    if it is None or t["role"] != "main" or it.get("type") != "video":
        raise ValueError("Reframe works on a clip on the main track.")
    src = doc["assets"].get(it.get("asset"), {}).get("src", it.get("src"))
    f = Path(edit) / "face.json"
    if src != "cut.mp4" or not f.exists():
        raise ValueError("No face track for this clip yet: run face.py on the edit (it reads cut.mp4).")
    kf = keyframes(json.loads(f.read_text(encoding="utf-8")), doc["fps"], it.get("trimIn", 0), it["durationInFrames"])
    if not kf:
        raise ValueError("No face was found in this clip, so it stays centred.")
    return {"author": "user", "label": "Reframe on the speaker",
            "ops": [{"op": "update", "id": item_id, "set": {"fit": "reframe", "reframe": kf}}]}


def demo():
    face = {"step_s": 0.5, "heads": [{"t": i * 0.5, "box": [40, 20, 20, 30]} for i in range(6)]
            + [{"t": 3.0, "box": None}] + [{"t": 3.5 + i * 0.5, "box": [60, 20, 20, 30]} for i in range(4)]}
    kf = keyframes(face, 30, 0, 180)
    assert kf[0] == {"f": 0, "cx": 50.0, "cy": 32.0}, kf
    assert kf[1] == {"f": 105, "cx": 50.0, "cy": 32.0} and kf[2] == {"f": 123, "cx": 70.0, "cy": 32.0}, kf
    assert all(a["f"] < b["f"] for a, b in zip(kf, kf[1:])), "frames increase"
    # a small sway inside the dead zone never moves the frame
    sway = {"heads": [{"t": i * 0.5, "box": [40 + (i % 2) * 3, 20, 20, 30]} for i in range(10)]}
    assert len(keyframes(sway, 30, 0, 150)) == 1
    # a trimmed clip: frames are the clip's own, from its first frame
    kt = keyframes(face, 30, 60, 120)
    assert kt[0]["f"] == 0 and kt[1]["f"] == 105 - 60, kt
    assert keyframes({"heads": []}, 30, 0, 90) == []
    import tempfile
    import project_schema as ps
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "face.json").write_text(json.dumps(face), encoding="utf-8")
        doc = {"fps": 30, "assets": {"ast_cut": {"kind": "video", "src": "cut.mp4"}},
               "tracks": [{"id": "trk_m", "role": "main", "items": [{"id": "itm_a", "type": "video", "asset": "ast_cut",
                                                                    "from": 0, "durationInFrames": 180, "trimIn": 0}]},
                          {"id": "trk_c", "role": "cards", "items": [{"id": "itm_c", "type": "card", "from": 0, "durationInFrames": 9}]}]}
        b = for_item(d, doc, "itm_a")
        assert b["ops"][0]["set"]["fit"] == "reframe" and b["ops"][0]["set"]["reframe"] == kf
        for bad in ("itm_c", "itm_none"):
            try:
                for_item(d, doc, bad)
                raise AssertionError("only main-track clips")
            except ValueError:
                pass
        assert ps.find(doc, "itm_a")[2]["type"] == "video"
    print("demo ok")


def main():
    if sys.argv[1:] == ["demo"]:
        return demo()
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    import project_store as store
    edit = Path(sys.argv[1])
    try:
        batch = for_item(edit, store.load(edit), sys.argv[2])
    except ValueError as e:
        sys.exit(str(e))
    print(json.dumps({"rev": store.apply(edit, batch)["rev"]}))


if __name__ == "__main__":
    main()
