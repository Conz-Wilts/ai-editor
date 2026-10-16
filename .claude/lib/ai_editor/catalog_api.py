#!/usr/bin/env python3
"""/api/components and /api/design-systems: the app's component gallery and design-system picker (app_api.py hands
these paths here). Stdlib only.

    GET /api/components                     {"components": [{id, name, kind, aspects, defaultDurationS, entrance,
                                             propsSchema, tags, example, source, preview}]}   preview: a URL or null
    GET /api/components/preview?id=         the gallery still (JPEG), cached by manifest hash in
                                             $AI_EDITOR_HOME/component-previews/; 202 {"pending": true} while
                                             render.mjs many makes the missing ones, 404 when it has no example props
    GET /api/design-systems                 {"systems": [{id, name, source: builtin|user|brand, swatch: {ground, ink,
                                             accent}, font, font_display, motion, description}]}
    GET /api/design-systems/look?id=        {"id", "look": the compiled Look, "motion"}

    python3 catalog_api.py demo
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import components  # noqa: E402
import design  # noqa: E402
import httpfile  # noqa: E402

PATHS = ("/api/components", "/api/components/preview", "/api/design-systems", "/api/design-systems/look")
_BUSY = threading.Lock()
RENDER = None   # a function(jobs: list, cache: Path) that makes the stills; None: render.mjs many in the renderer


def home():
    return Path(os.environ.get("AI_EDITOR_HOME", "").strip() or Path.home() / ".ai-video-editor")


def cache_dir():
    d = home() / "component-previews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def still_path(m):
    return cache_dir() / f"{m['id']}-{components.manifest_hash(m)}.jpg"


def preview_url(m):
    if "example" not in m:
        return None
    return f"/api/components/preview?id={m['id']}"


def job(m):
    """One render.mjs many job: the component alone on a dark ground in the Preview composition, mid-life."""
    dur = float(m.get("defaultDurationS") or 2.5)
    a = m.get("contentAspect") or 2.0
    w = 84
    h = max(12, min(60, w * 1080 / a / 1920))
    plan = {"composition": "Preview", "width": 1080, "height": 1920, "dur": dur, "bg": "#2B2B2B", "look": {"preset": "editorial"},
            "card": {"anim": {"type": m["id"], "props": m["example"]}, "start": 0, "end": dur, "entrance": m.get("entrance") or "pop",
                     "box": [8, round((100 - h) / 2, 1), w, round(h, 1)]}}
    return {"plan": plan, "frame": int(min(dur * 30 - 1, 45)), "out": str(still_path(m))}


def render_many(jobs, cache):
    """The stills through the installed renderer (after copying the registry generator alongside it)."""
    remotion = home() / "remotion"
    if not (remotion / "node_modules" / "remotion").exists():
        raise RuntimeError("the renderer is not installed (the setup skill installs it)")
    try:   # the renderer copy runs this checkout's src/ (edit.py sync_renderer) and finds the user's components
        sys.path.insert(0, str(HERE.parents[1] / "skills" / "style-edit" / "scripts"))
        import edit
        edit.sync_renderer()
    except Exception:   # noqa: BLE001  a stale copy still renders the built-ins
        pass
    gen = HERE.parents[1] / "remotion" / "scripts" / "gen-registry.mjs"
    (remotion / "scripts").mkdir(exist_ok=True)
    shutil.copyfile(gen, remotion / "scripts" / "gen-registry.mjs")
    with tempfile.TemporaryDirectory(prefix="ave-previews-") as t:
        (Path(t) / "pub").mkdir()
        jf = Path(t) / "jobs.json"
        jf.write_text(json.dumps(jobs), encoding="utf-8")
        subprocess.run(["node", str(remotion / "render.mjs"), "many", str(Path(t) / "pub"), str(jf)], cwd=remotion,
                       capture_output=True, timeout=900)


def make_missing():
    """Render every gallery still that is not cached yet, one batch at a time (a second call while one runs waits)."""
    if not _BUSY.acquire(blocking=False):
        return False
    try:
        todo = [job(m) for m in components.load_all().values() if "example" in m and not still_path(m).exists()]
        if todo:
            (RENDER or render_many)(todo, cache_dir())
        return True
    finally:
        _BUSY.release()


def route(h, method, path, q):
    """h.send(code, obj) answers; False when the path is not ours."""
    if method != "GET" or path not in PATHS:
        return False
    if path == "/api/components":
        h.send(200, {"components": components.catalog(preview_url=preview_url)})
        return True
    if path == "/api/components/preview":
        m = components.load_all().get(q.get("id", ""))
        if not m or "example" not in m:
            h.send(404, {"error": "no preview for this component"})
            return True
        f = still_path(m)
        if f.exists():
            httpfile.send_file(h, f)
            return True
        threading.Thread(target=make_missing, daemon=True).start()
        h.send(202, {"pending": True})
        return True
    if path == "/api/design-systems":
        h.send(200, {"systems": design.listing()})
        return True
    sid = q.get("id", "")
    try:
        h.send(200, {"id": sid, "look": design.compile(sid), "motion": design.motion(sid)})
    except (KeyError, ValueError) as e:
        h.send(404, {"error": str(e)})
    return True


def demo():
    import http.client
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlsplit
    global RENDER
    with tempfile.TemporaryDirectory() as t:
        os.environ["AI_EDITOR_HOME"] = str(Path(t) / "home")
        made = []

        def fake(jobs, cache):   # stands in for render.mjs many: writes a tiny JPEG per job
            made.extend(j["plan"]["card"]["anim"]["type"] for j in jobs)
            for j in jobs:
                Path(j["out"]).write_bytes(b"\xff\xd8\xff\xe0fake\xff\xd9")
        RENDER = fake

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urlsplit(self.path)
                if not route(self, "GET", u.path, {k: v[0] for k, v in parse_qs(u.query).items()}):
                    self.send(404, {"error": "not ours"})
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        def get(p):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request("GET", p)
            r = c.getresponse()
            return r.status, r.read(), r.getheader("Content-Type")
        st, body, _ = get("/api/components")
        rows = {r["id"]: r for r in json.loads(body)["components"]}
        assert st == 200 and {"shot", "terminal", "flow"} <= set(rows) and "logo" not in rows, sorted(rows)
        assert rows["terminal"]["preview"] == "/api/components/preview?id=terminal" and rows["shot"]["preview"] is None
        assert rows["terminal"]["propsSchema"]["required"] == ["lines"] and rows["terminal"]["source"] == "builtin"
        assert get("/api/components/preview?id=shot")[0] == 404, "no example props, no still"
        assert get("/api/components/preview?id=terminal")[0] == 202, "made in the background"
        for _ in range(100):
            if not _BUSY.locked() and made:
                break
            time.sleep(0.05)
        st, body, ctype = get("/api/components/preview?id=terminal")
        assert st == 200 and body.startswith(b"\xff\xd8") and ctype == "image/jpeg", (st, ctype)
        assert "terminal" in made and "shot" not in made
        st, body, _ = get("/api/design-systems")
        sy = {s["id"]: s for s in json.loads(body)["systems"]}
        assert st == 200 and sy["editorial"]["swatch"] == {"ground": "#F2EEE6", "ink": "#141414", "accent": "#E5482C"}, sy["editorial"]
        assert sy["neutral"]["source"] == "builtin"
        st, body, _ = get("/api/design-systems/look?id=poster-red")
        lk = json.loads(body)
        assert st == 200 and lk["look"]["case"] == "upper" and lk["look"]["preset"] == "poster-red", lk
        assert get("/api/design-systems/look?id=nope")[0] == 404
        srv.shutdown()
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        print(__doc__)
        sys.exit(2)
