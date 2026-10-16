#!/usr/bin/env python3
"""The app (.claude/app) on the home server, and the routes only the app uses. app_api.py has the project
commands; home.py hands these here after the same token-cookie check (and, for POST, the same-origin check).

    GET  /app/                         the editor: index.html, then app.js / app.css (built by build.mjs from
                                       .claude/app/src and .claude/remotion/src whenever their sources change)
    GET  /api/media/<edit>/<path>      a file inside the edit, for the Player's staticFile() (byte ranges); a
                                       video with a proxy (proxy/, made on import) is served from the proxy
    GET  /api/plan?edit=&format=       the plan the timeline makes (project_convert.to_plan): the Player's props
    GET  /api/formats                  formats.json (the format bar)
    POST /api/new        {name, format}        a new, empty project in the library: {edit, name}
    POST /api/upload?edit=&name=       the raw file as the body, into <edit>/media/; probed: {asset}
    POST /api/reframe    {edit, id}            fit=reframe with keyframes from face.json (reframe.py)

`edit` is the edit folder's name or path; only folders library.edit_dirs() knows are served (app_api.resolve).

    python3 app_render.py build        build the app now (node .claude/app/build.mjs)
    python3 app_render.py demo
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app_api  # noqa: E402
import httpfile  # noqa: E402

EDITOR = Path(__file__).resolve().parents[2]          # .claude
APP = EDITOR / "app"
DIST = APP / "dist"
FORMATS = EDITOR / "remotion" / "src" / "formats.json"
HOME = Path(os.environ.get("AI_EDITOR_HOME", Path.home() / ".ai-video-editor"))
VIDEO = (".mp4", ".mov", ".m4v", ".mkv", ".webm")
IMAGE = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif")
AUDIO = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
MAX_UPLOAD = 20 << 30      # 20 GB
PROXY_SHORT = 720          # the Player's copy of a big video: this many pixels on the short side
_build = threading.Lock()
_proxying = set()


# ---------------------------------------------------------------- the bundle
def sources_hash():
    """One hash over everything the bundle is made from (the app and the renderer's source it imports)."""
    h = hashlib.sha1()
    files = [APP / "index.html", APP / "build.mjs"]
    for d in (APP / "src", EDITOR / "remotion" / "src"):
        files += sorted(p for p in d.rglob("*") if p.is_file())
    for f in files:
        try:
            h.update(f.relative_to(EDITOR).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
        except OSError:
            pass
    return h.hexdigest()


def ensure_built(force=False):
    """None when dist/ is current (building it first when the sources changed), else why it could not build."""
    with _build:
        want = sources_hash()
        stamp = DIST / ".hash"
        if not force and (DIST / "app.js").exists() and stamp.exists() and stamp.read_text(encoding="utf-8") == want:
            return None
        if not (HOME / "remotion" / "node_modules").is_dir():
            return "The renderer is not installed yet. Run setup (python3 .claude/skills/setup/scripts/setup.py remotion)."
        r = subprocess.run(["node", str(APP / "build.mjs")], capture_output=True, text=True, timeout=300,
                           env={**os.environ, "AI_EDITOR_HOME": str(HOME)})
        if r.returncode:
            return "The app did not build:\n" + (r.stderr or r.stdout)[-1500:]
        stamp.write_text(sources_hash(), encoding="utf-8")   # after the build: it writes the components registry into src
        return None


# ---------------------------------------------------------------- media
def probe_media(f):
    """{kind, width?, height?, fps?, duration?, hasAudio?} for a file, or {} when ffprobe cannot read it."""
    ext = f.suffix.lower()
    kind = "image" if ext in IMAGE else "audio" if ext in AUDIO else "video"
    if ext == ".svg":
        return {"kind": "image"}
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt:stream_tags=rotate:format=duration",
                            "-of", "json", str(f)], capture_output=True, text=True, timeout=60)
        j = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    streams = j.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    out = {"kind": kind, "hasAudio": any(s.get("codec_type") == "audio" for s in streams)}
    dur = float((j.get("format") or {}).get("duration") or 0)
    if dur and kind != "image":
        out["duration"] = round(dur, 3)
    if v:
        w, h = v.get("width"), v.get("height")
        if str((v.get("tags") or {}).get("rotate", "0")) in ("90", "-90", "270"):
            w, h = h, w
        out.update(width=w, height=h, codec=v.get("codec_name"), pixFmt=v.get("pix_fmt"))
        try:
            n, d = (v.get("r_frame_rate") or "30/1").split("/")
            fps = float(n) / float(d)
            if kind == "video" and fps > 0:
                out["fps"] = round(fps, 3)
                out["durationInFrames"] = int(round(dur * fps))
        except (ValueError, ZeroDivisionError):
            pass
    elif kind == "video":
        out["kind"] = "audio"   # an .mp4 with only sound
    return out


def proxy_path(edit, rel):
    return Path(edit) / "proxy" / (rel.replace("/", "__") + ".mp4")


def needs_proxy(meta):
    """A video the browser plays badly at full size: past 1080p, over 10 minutes, or not H.264 4:2:0."""
    if meta.get("kind") != "video" or not meta.get("width"):
        return False
    return (max(meta["width"], meta["height"]) > 1920 or meta.get("duration", 0) > 600
            or meta.get("codec") not in ("h264",) or meta.get("pixFmt") not in ("yuv420p", "yuvj420p"))


def proxy_size(w, h):
    k = min(1.0, PROXY_SHORT / min(w, h))
    return int(w * k) // 2 * 2, int(h * k) // 2 * 2


def make_proxy(edit, rel, meta, wait=False):
    """The Player's copy of a big video in <edit>/proxy/ (a keyframe every 15 frames: seeking stays instant). Renders
    never read it."""
    src, out = Path(edit) / rel, proxy_path(edit, rel)
    key = str(out)
    if key in _proxying or (out.exists() and out.stat().st_mtime >= src.stat().st_mtime):
        return out

    def run():
        try:
            pw, ph = proxy_size(meta["width"], meta["height"])
            try:
                sys.path.insert(0, str(EDITOR / "skills" / "style-edit" / "scripts"))
                from edit import proxy_filter   # same shape: a plain scale
                vf = proxy_filter(meta["width"], meta["height"], pw, ph)
            except Exception:
                vf = f"scale={pw}:{ph},setsar=1"
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.stem + ".part.mp4")
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                                "-crf", "28", "-g", "15", "-keyint_min", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                                "-movflags", "+faststart", str(tmp)], capture_output=True)
            if r.returncode == 0:
                os.replace(tmp, out)
            else:
                tmp.unlink(missing_ok=True)
        finally:
            _proxying.discard(key)
    _proxying.add(key)
    if wait:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()
    return out


def safe_name(name):
    stem, ext = os.path.splitext(Path(str(name)).name)
    stem = re.sub(r"[^A-Za-z0-9._ -]", "", stem).strip().replace(" ", "-")[:80] or "file"
    return stem + re.sub(r"[^A-Za-z0-9.]", "", ext)[:8].lower()


def unique(folder, name):
    f, n = folder / name, 1
    while f.exists():
        n += 1
        f = folder / f"{Path(name).stem}-{n}{Path(name).suffix}"
    return f


def upload(h, q):
    """POST /api/upload?edit=&name=: the body is the file. Streams to <edit>/media/<name>, probes it, starts a proxy
    when it needs one. 200 {asset} (src relative to the edit; the app sends addAsset with it)."""
    d = app_api.resolve(q.get("edit"))
    if d is None:
        return h.send(404, {"error": "no such edit in the library"})
    n = int(h.headers.get("Content-Length") or 0)
    if not n or n > MAX_UPLOAD:
        return h.send(400, {"error": "empty or too large"})
    name = safe_name(q.get("name") or "upload.mp4")
    if not name.lower().endswith(VIDEO + IMAGE + AUDIO):
        return h.send(400, {"error": "Drop a video, a picture or a sound file."})
    folder = d / "media"
    folder.mkdir(exist_ok=True)
    out = unique(folder, name)
    tmp = out.with_name(out.name + ".part")
    left = n
    try:
        with open(tmp, "wb") as f:
            while left:
                b = h.rfile.read(min(1 << 20, left))
                if not b:
                    break
                f.write(b)
                left -= len(b)
        if left:
            tmp.unlink(missing_ok=True)
            return h.send(400, {"error": "The upload stopped part way. Drop it again."})
        os.replace(tmp, out)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return h.send(500, {"error": f"could not save it: {e}"})
    meta = probe_media(out)
    if not meta:
        out.unlink(missing_ok=True)
        return h.send(400, {"error": "That file could not be read."})
    rel = out.relative_to(d).as_posix()
    if needs_proxy(meta):
        make_proxy(d, rel, meta)
    asset = {"src": rel, "origin": "upload", "name": out.name,
             **{k: v for k, v in meta.items() if k not in ("codec", "pixFmt")}}
    return h.send(200, {"asset": asset, "proxy": needs_proxy(meta)})


def media(h, rest):
    """/api/media/<edit name>/<path>: the edit's file (its proxy for a big video), ranges included."""
    name, _, rel = rest.partition("/")
    d = app_api.resolve(unquote(name))
    if d is None or not rel:
        return h.send(404, {"error": "no such edit in the library"})
    f = (d / unquote(rel)).resolve()
    if d not in f.parents or not f.is_file():
        return h.send(404, {"error": "no such file in this edit"})
    if f.suffix.lower() in VIDEO:
        p = proxy_path(d, f.relative_to(d).as_posix())
        if p.exists() and p.stat().st_mtime >= f.stat().st_mtime:
            f = p
    return httpfile.send_file(h, f)


# ---------------------------------------------------------------- new projects
def new_project(home, name, fmt):
    import project_schema as ps
    import project_store as store
    try:
        import formats
        spec = formats.get(fmt)
        w, hgt = int(spec["width"]), int(spec["height"])
    except Exception:
        fmt, w, hgt = "youtube" if fmt == "youtube" else "vertical", 1920 if fmt == "youtube" else 1080, 1080 if fmt == "youtube" else 1920
    root = Path(home.read()["root"])
    edit = home.new_edit(root, (str(name or "").strip() or "Untitled video") + ".mp4")
    doc = {"schema": ps.SCHEMA, "id": ps.mint("prj"), "name": str(name or edit.name).strip() or edit.name, "rev": 0,
           "fps": 30, "width": w, "height": hgt, "durationInFrames": 0, "format": fmt, "formats": [fmt],
           "designSystem": None, "assets": {}, "tracks": [ps.new_track(r) for r in ps.TRACK_ORDER],
           "planExtras": {}, "source": {}}
    store.save_new(edit, doc)
    return edit


# ---------------------------------------------------------------- routing
def route(h, method, path, q, body=None, home=None):
    """True when this module answered (GET /app..., GET/POST /api/... it owns)."""
    if method == "GET" and (path == "/app" or path.startswith("/app/")):
        if path in ("/app", "/app/", "/app/index.html"):
            err = ensure_built()
            if err:
                return h.send(500, f"<pre>{err}</pre>", "text/html; charset=utf-8", cookie=True) or True
            h.send(200, (APP / "index.html").read_bytes(), "text/html; charset=utf-8", cookie=True)
            return True
        name = path[len("/app/"):]
        if name in ("app.js", "app.css", "app.js.map"):
            f = DIST / name
            if not f.exists():
                ensure_built()
            if f.exists():
                ctype = {"js": "text/javascript", "css": "text/css", "map": "application/json"}[name.rsplit(".", 1)[1]]
                h.send(200, f.read_bytes(), ctype + "; charset=utf-8")
                return True
        h.send(404, {"error": "not found"})
        return True
    if method == "GET" and path.startswith("/api/media/"):
        media(h, path[len("/api/media/"):])
        return True
    if method == "GET" and path == "/api/plan":
        import project_convert as pc
        import project_store as store
        d = app_api.resolve(q.get("edit"))
        if d is None or not store.path(d).exists():
            h.send(404, {"error": "no project"})
            return True
        doc = store.load(d)
        h.send(200, {"rev": doc["rev"], "plan": pc.to_plan(doc, q.get("format") or None)})
        return True
    if method == "GET" and path == "/api/formats":
        try:
            h.send(200, json.loads(FORMATS.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            h.send(404, {"error": "no formats.json"})
        return True
    if method != "POST":
        return False
    b = body or {}
    if path == "/api/new":
        if home is None:
            h.send(500, {"error": "no library"})
            return True
        edit = new_project(home, b.get("name"), str(b.get("format") or "vertical"))
        h.send(200, {"edit": str(edit), "name": edit.name})
        return True
    if path == "/api/reframe":
        import project_store as store
        import reframe
        d = app_api.resolve(b.get("edit"))
        if d is None:
            h.send(404, {"error": "no such edit in the library"})
            return True
        try:
            res = store.apply(d, reframe.for_item(d, store.load(d), str(b.get("id") or "")))
        except ValueError as e:
            h.send(400, {"error": str(e)})
            return True
        except store.Conflict as e:
            h.send(409, {"error": str(e), "rev": e.rev})
            return True
        h.send(200, res)
        return True
    return False


# ---------------------------------------------------------------- self-check
def demo():
    import http.client
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, quote, urlsplit
    import project_store as store
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        lib = root / "edits"
        lib.mkdir()

        class FakeHome:
            @staticmethod
            def read():
                return {"root": str(root)}

            @staticmethod
            def new_edit(r, name):
                e = Path(r) / "edits" / Path(name).stem.replace(" ", "-").lower()
                e.mkdir(parents=True)
                return e
        app_api.EDIT_DIRS = lambda: [p for p in lib.iterdir() if p.is_dir()]

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, obj, ctype="application/json", cookie=False):
                raw = obj if isinstance(obj, bytes) else obj.encode() if isinstance(obj, str) else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def q(self):
                return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query, keep_blank_values=True).items()}

            def do_GET(self):
                p = urlsplit(self.path).path
                if not (route(self, "GET", p, self.q(), home=FakeHome) or app_api.route(self, "GET", p, self.q())):
                    self.send(404, {"error": "nf"})

            def do_POST(self):
                p = urlsplit(self.path).path
                if p == "/api/upload":
                    return upload(self, self.q())
                b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if not (route(self, "POST", p, self.q(), b, home=FakeHome) or app_api.route(self, "POST", p, self.q(), b)):
                    self.send(404, {"error": "nf"})
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def call(m, p, body=None, raw=None, headers=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
            c.request(m, p, data, headers or {})
            r = c.getresponse()
            out = r.read()
            try:
                return r.status, json.loads(out), r
            except ValueError:
                return r.status, out, r
        # a new, empty project: every track, the format's size, rev 0, openable by the project API
        s, j, _ = call("POST", "/api/new", {"name": "My launch", "format": "youtube"})
        assert s == 200 and j["name"] == "my-launch", j
        e = j["name"]
        doc = store.load(lib / e)
        assert (doc["width"], doc["height"], doc["format"]) == (1920, 1080, "youtube") and doc["rev"] == 0
        assert [t["role"] for t in doc["tracks"]][:2] == ["main", "broll"] and not doc["assets"]
        s, j, _ = call("GET", f"/api/plan?edit={e}")
        assert s == 200 and j["plan"]["width"] == 1920 and "video" not in j["plan"], j
        # upload a real (tiny) video: streamed into media/, probed, no proxy for a small h264
        clip = root / "c.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=1:r=30", "-f", "lavfi",
                        "-i", "sine=d=1", "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(clip)], check=True)
        s, j, _ = call("POST", f"/api/upload?edit={e}&name=My%20Take.MP4", raw=clip.read_bytes())
        a = j["asset"]
        assert s == 200 and a["src"] == "media/My-Take.mp4" and a["kind"] == "video" and a["fps"] == 30, j
        assert a["durationInFrames"] == 30 and a["hasAudio"] and a["width"] == 320 and not j["proxy"], a
        assert call("POST", f"/api/upload?edit={e}&name=x.exe", raw=b"x")[0] == 400
        # the timeline uses it: addAsset + add on the main track, then the Player's plan has it
        store.apply(lib / e, {"author": "user", "ops": [{"op": "addAsset", "id": "ast_take", "asset": a},
                                                       {"op": "add", "track": "main", "item": {"type": "video", "asset": "ast_take",
                                                        "from": 0, "durationInFrames": 30, "trimIn": 0}}]})
        s, j, _ = call("GET", f"/api/plan?edit={e}&format=shorts")
        assert j["plan"]["video"] == "media/My-Take.mp4" and j["plan"]["height"] == 1920, j
        # media for the Player: ranges, nothing outside the edit
        s, data, r = call("GET", f"/api/media/{quote(e)}/media/My-Take.mp4", headers={"Range": "bytes=0-99"})
        assert s == 206 and len(data) == 100, s
        assert call("GET", f"/api/media/{quote(e)}/../../c.mp4")[0] == 404
        # a proxy, once made, is what the Player gets
        meta = probe_media(lib / e / "media" / "My-Take.mp4")
        make_proxy(lib / e, "media/My-Take.mp4", meta, wait=True)
        p = proxy_path(lib / e, "media/My-Take.mp4")
        assert p.exists() and probe_media(p)["height"] == 240
        assert int(call("GET", f"/api/media/{quote(e)}/media/My-Take.mp4")[2].getheader("Content-Length")) == p.stat().st_size
        assert needs_proxy({"kind": "video", "width": 3840, "height": 2160, "codec": "h264", "pixFmt": "yuv420p"})
        assert needs_proxy({"kind": "video", "width": 1080, "height": 1920, "codec": "hevc", "pixFmt": "yuv420p"})
        assert proxy_size(3840, 2160) == (1280, 720) and proxy_size(1080, 1920) == (720, 1280)
        # reframe needs a face track
        it = [x for x in store.load(lib / e)["tracks"][0]["items"]][0]
        s, j, _ = call("POST", "/api/reframe", {"edit": e, "id": it["id"]})
        assert s == 400 and "face" in j["error"], j
        s, j, _ = call("GET", "/api/formats")
        assert s == 200 and "youtube" in j.get("formats", j), list(j)[:5]
        assert safe_name("../../x y?.MOV") == "x-y.mov" and safe_name("") == "file"
        srv.shutdown()
        app_api.EDIT_DIRS = None
    print("demo ok")


def main():
    if sys.argv[1:] == ["demo"]:
        return demo()
    if sys.argv[1:] == ["build"]:
        err = ensure_built(force=True)
        print(err or f"built {DIST / 'app.js'}")
        sys.exit(1 if err else 0)
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
