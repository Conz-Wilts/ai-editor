#!/usr/bin/env python3
"""/api/* on the home server: the app's view of the projects in the library. home.py hands every /api/ request
here after its token-cookie check (and, for POST, its same-origin check). Stdlib only.

    GET  /api/projects                         edit folders with a plan.json or project.json
    GET  /api/project?edit=                    project.json (made from plan.json on first open) + open proposals
    POST /api/commands?edit=   {batch}         project_store.apply: 200 {rev, doc} | 409 {error, rev} | 400 {error}
    GET  /api/events?edit=&since=&wait=25      long-poll: returns at once when rev > since (or proposals changed),
                                               else when a write lands (this process, or Claude's CLI by mtime)
    POST /api/undo?edit=  {author}             POST /api/redo?edit=  {author}
    POST /api/proposal/accept?edit=  {id}      POST /api/proposal/reject?edit=  {id}
    GET  /api/file?edit=&p=<path in the edit>  any file inside the edit folder, with byte ranges (206)

    GET  /api/components, /api/components/preview?id=, /api/design-systems, /api/design-systems/look?id=
                                               the component gallery and design systems (catalog_api.py)

`edit` is the edit folder's path (or its name); only folders library.edit_dirs() knows are served.

    python3 app_api.py demo
"""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import httpfile  # noqa: E402
import project_convert as pc  # noqa: E402
import project_store as store  # noqa: E402

WAIT_S = 25
EDIT_DIRS = None   # a function returning the allowed edit folders; None: library.edit_dirs()


def allowed():
    if EDIT_DIRS is not None:
        return [Path(p).resolve() for p in EDIT_DIRS()]
    import library
    return library.edit_dirs()


def resolve(ref):
    """The edit folder for ?edit= (a path or a folder name), or None when the library does not know it."""
    if not ref:
        return None
    dirs = allowed()
    try:
        p = Path(ref).resolve()
        if p in dirs:
            return p
    except OSError:
        pass
    named = [d for d in dirs if d.name == ref]
    return named[0] if len(named) == 1 else None


def project(d):
    """project.json, made from plan.json the first time the app opens an edit."""
    if not store.path(d).exists():
        if not (d / "plan.json").exists():
            return None
        pc.sync(d)
    return store.load(d)


def _rev(d):
    try:
        return store.load(d)["rev"]
    except (OSError, ValueError, KeyError):
        return -1


def _pids(d):
    return sorted(p.stem for p in (d / "proposals").glob("prp_*.json"))


def events(d, since, known=None, wait=WAIT_S):
    """{"rev", "entries", "proposals"} once something is newer than since (or the proposal list changed)."""
    deadline = time.time() + wait
    while True:
        rev, pids = _rev(d), _pids(d)
        if rev > since or (known is not None and pids != known):
            return {"rev": rev, "entries": store.since(d, since), "proposals": store.proposals(d)}
        left = deadline - time.time()
        if left <= 0:
            return {"rev": rev, "entries": [], "proposals": store.proposals(d)}
        with store.CHANGED:   # a write in this server wakes us at once; Claude's CLI write is seen on the next look
            store.CHANGED.wait(min(0.5, left))


def route(h, method, path, q, body=None):
    """Handle one /api/ request with h (the home handler: h.send(code, obj)). False when the path is not ours."""
    if path.startswith(("/api/components", "/api/design-systems")):   # the gallery and the design-system picker
        import catalog_api
        return catalog_api.route(h, method, path, q)
    if path == "/api/projects" and method == "GET":
        out = []
        for d in allowed():
            if (d / "project.json").exists() or (d / "plan.json").exists():
                out.append({"edit": str(d), "name": d.name, "project": (d / "project.json").exists(), "rev": _rev(d)})
        h.send(200, {"projects": out})
        return True
    if not path.startswith("/api/"):
        return False
    d = resolve(q.get("edit") or (body or {}).get("edit"))
    if path in ("/api/project", "/api/commands", "/api/events", "/api/undo", "/api/redo", "/api/file",
                "/api/proposal/accept", "/api/proposal/reject") and d is None:
        h.send(404, {"error": "no such edit in the library"})
        return True
    try:
        if path == "/api/project" and method == "GET":
            doc = project(d)
            if doc is None:
                h.send(404, {"error": "this edit has no plan yet"})
            else:
                h.send(200, {"doc": doc, "proposals": store.proposals(d)})
            return True
        if path == "/api/file" and method == "GET":
            rel = q.get("p") or ""
            f = (d / rel).resolve()
            if d not in f.parents or not f.is_file():
                h.send(404, {"error": "no such file in this edit"})
            else:
                httpfile.send_file(h, f)
            return True
        if path == "/api/events" and method == "GET":
            known = q["proposals"].split(",") if q.get("proposals") else ([] if "proposals" in q else None)
            wait = min(WAIT_S, float(q.get("wait", WAIT_S)))
            h.send(200, events(d, int(q.get("since", -1)), sorted(x for x in (known or []) if x) if known is not None else None, wait))
            return True
        if method != "POST":
            return False
        b = body or {}
        if path == "/api/commands":
            project(d)
            res = store.apply(d, b)
            h.send(200, res)
            return True
        if path in ("/api/undo", "/api/redo"):
            doc = (store.undo if path == "/api/undo" else store.redo)(d, b.get("author") or "user")
            h.send(200, {"rev": doc["rev"], "doc": doc} if doc else {"rev": _rev(d), "doc": None, "nothing": True})
            return True
        if path == "/api/proposal/accept":
            doc = store.accept(d, b.get("id", ""))
            h.send(200, {"rev": doc["rev"], "doc": doc})
            return True
        if path == "/api/proposal/reject":
            h.send(200, {"rejected": store.reject(d, b.get("id", "")), "rev": _rev(d)})
            return True
    except store.Conflict as e:
        h.send(409, {"error": str(e), "rev": e.rev})
        return True
    except store.BadBatch as e:
        h.send(400, {"error": str(e)})
        return True
    return False


def demo():
    import http.client
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlsplit, quote
    global EDIT_DIRS
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "edits" / "demo-video"
        d.mkdir(parents=True)
        (d / "plan.json").write_text(json.dumps(pc.sample_plan()), encoding="utf-8")
        (d / "cut.mp4").write_bytes(bytes(range(256)) * 8)
        (Path(t) / "secret.txt").write_text("no", encoding="utf-8")
        EDIT_DIRS = lambda: [d]

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _q(self):
                return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query, keep_blank_values=True).items()}

            def do_GET(self):
                if not route(self, "GET", urlsplit(self.path).path, self._q()):
                    self.send(404, {"error": "not found"})

            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if not route(self, "POST", urlsplit(self.path).path, self._q(), b):
                    self.send(404, {"error": "not found"})
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port, e = srv.server_address[1], quote(str(d))

        def call(m, p, body=None, headers=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            raw = json.dumps(body).encode() if body is not None else None
            c.request(m, p, raw, {**({"Content-Type": "application/json"} if raw else {}), **(headers or {})})
            r = c.getresponse()
            data = r.read()
            try:
                return r.status, json.loads(data), r
            except ValueError:
                return r.status, data, r
        s, j, _ = call("GET", "/api/projects")
        assert s == 200 and j["projects"][0]["name"] == "demo-video" and not j["projects"][0]["project"], j
        s, j, _ = call("GET", f"/api/project?edit={e}")
        assert s == 200 and j["doc"]["rev"] == 0 and (d / "project.json").exists(), "made from plan.json on first open"
        assert call("GET", "/api/project?edit=demo-video")[1]["doc"]["id"] == j["doc"]["id"], "by name too"
        assert call("GET", "/api/project?edit=" + quote(str(Path(t))))[0] == 404, "only library edits"
        card = [x for x in j["doc"]["tracks"] if x["role"] == "cards"][0]["items"][0]["id"]
        s, j, _ = call("POST", f"/api/commands?edit={e}", {"baseRev": 0, "author": "user", "ops": [{"op": "move", "id": card, "from": 420}]})
        assert s == 200 and j["rev"] == 1, j
        s, j, _ = call("POST", f"/api/commands?edit={e}", {"author": "user", "ops": [{"op": "delete", "id": card}]})
        s, j, _ = call("POST", f"/api/commands?edit={e}", {"baseRev": 1, "author": "user", "ops": [{"op": "move", "id": card, "from": 1}]})
        assert s == 409 and j["rev"] == 2, (s, j)
        assert call("POST", f"/api/commands?edit={e}", {"author": "user", "ops": [{"op": "nope"}]})[0] == 400
        # events: nothing new waits; a write from another writer (Claude's CLI) wakes it
        t0 = time.time()
        s, j, _ = call("GET", f"/api/events?edit={e}&since=2&wait=0.3")
        assert s == 200 and j["entries"] == [] and time.time() - t0 >= 0.25
        zoom = [x for x in store.load(d)["tracks"] if x["role"] == "zooms"][0]["items"][0]["id"]
        threading.Timer(0.4, lambda: store.apply(d, {"author": "claude", "label": "nudge", "ops": [
            {"op": "update", "id": zoom, "set": {"props.scale": 1.3}}]})).start()
        s, j, _ = call("GET", f"/api/events?edit={e}&since=2&wait=5")
        assert j["rev"] == 3 and j["entries"][0]["author"] == "claude" and j["entries"][0]["label"] == "nudge", j
        # undo the user's delete, propose + accept, propose + reject
        s, j, _ = call("POST", f"/api/undo?edit={e}", {"author": "user"})
        assert s == 200 and j["rev"] == 4 and any(it["id"] == card for t2 in j["doc"]["tracks"] for it in t2["items"])
        s, j, _ = call("POST", f"/api/commands?edit={e}", {"author": "claude", "propose": True,
                                                          "ops": [{"op": "move", "id": card, "from": 500}]})
        pid = j["proposal"]
        s, j, _ = call("GET", f"/api/events?edit={e}&since=4&proposals=&wait=1")
        assert [p["id"] for p in j["proposals"]] == [pid], j
        s, j, _ = call("POST", f"/api/proposal/accept?edit={e}", {"id": pid})
        assert s == 200 and j["rev"] == 5
        assert call("POST", f"/api/proposal/accept?edit={e}", {"id": pid})[0] == 409
        # files: ranges inside the edit, nothing outside it
        s, data, r = call("GET", f"/api/file?edit={e}&p=cut.mp4", headers={"Range": "bytes=0-9"})
        assert s == 206 and data == bytes(range(10)) and r.getheader("Content-Range") == "bytes 0-9/2048"
        assert call("GET", f"/api/file?edit={e}&p=../../secret.txt")[0] == 404
        assert call("GET", "/api/elsewhere")[0] == 404
        srv.shutdown()
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        print(__doc__)
        sys.exit(2)
