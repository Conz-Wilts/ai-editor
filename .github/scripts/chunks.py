#!/usr/bin/env python3
"""Split a render into frame ranges, one per GitHub Actions runner. Stdlib only.

    python3 chunks.py FRAMES FPS     -> chunks=[{"i": "00", "from": 0, "to": 1325}, ...] for $GITHUB_OUTPUT
    python3 chunks.py demo           self-check

edit.py imports chunk_ranges from here, so the estimate on the laptop and the workflow's plan job agree.
"""
import json
import math
import sys

GH_CHUNK_S = 120          # about 2 min of video per runner
GH_MAX_CHUNKS = 20        # free accounts run 20 jobs at once


def chunk_ranges(frames, fps):
    """Frame ranges [from, to] (inclusive), one per runner."""
    k = max(1, min(GH_MAX_CHUNKS, math.ceil(frames / (fps * GH_CHUNK_S))))
    step = math.ceil(frames / k)
    return [[a, min(frames, a + step) - 1] for a in range(0, frames, step)]


def matrix(frames, fps):
    return [{"i": f"{i:02d}", "from": a, "to": b} for i, (a, b) in enumerate(chunk_ranges(frames, fps))]


def positive(text, kind):
    """The workflow's inputs arrive as strings typed by whoever dispatched it: numbers only, never shell."""
    v = kind(text)
    if not v > 0 or (kind is float and not math.isfinite(v)):
        raise ValueError(text)
    return v


def demo():
    assert chunk_ranges(1326, 30) == [[0, 1325]]
    r = chunk_ranges(40 * 60 * 30, 30)
    assert len(r) == 20 and r[0] == [0, 3599] and r[-1][1] == 71999, r
    assert len(chunk_ranges(3 * 3600 * 30, 30)) == 20                       # capped
    assert all(b - a + 1 > 0 for a, b in chunk_ranges(9, 1))
    m = matrix(72000, 30)
    assert [[c["from"], c["to"]] for c in m] == chunk_ranges(72000, 30) and m[-1]["i"] == "19"
    for bad in ("0", "-3", "nan", "1;rm -rf /", ""):
        try:
            positive(bad, float)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert positive("29.97", float) == 29.97 and positive("900", int) == 900
    print("demo ok")


def main():
    if sys.argv[1:] == ["demo"]:
        return demo()
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    frames, fps = positive(sys.argv[1], int), positive(sys.argv[2], float)
    print("chunks=" + json.dumps(matrix(frames, fps)))


if __name__ == "__main__":
    main()
