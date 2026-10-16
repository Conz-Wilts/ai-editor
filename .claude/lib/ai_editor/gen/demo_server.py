"""gen.py demo: the whole flow against a fake Higgsfield on localhost. No network, no key, nothing billed.

Checks the auth header on every API call and none on upload or output URLs, retries (503, the concurrency 400),
the estimate -> confirm -> submit gate, the monthly budget, the price re-check after uploading, the status states,
cancel, the download and probe, and the timeline ops.
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KEY = "kid:" + "s" * 24


class Fake:
    def __init__(self):
        self.calls, self.uploads, self.estimates, self.slots = [], {}, [], 0
        self.usd, self.usd_after_upload = 1.25, None
        self.submit_faults = [503, 400]          # then queued
        self.states = {}                          # request_id -> remaining states
        self.out = b"not a video"


def handler(fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def send(self, code, obj=None, raw=None):
            data = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
            self.send_response(code)
            self.send_header("Content-Type", "application/json" if raw is None else "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def api_auth(self):
            fake.calls.append((self.command, self.path, self.headers.get("Authorization")))
            if self.headers.get("Authorization") != f"Key {KEY}":
                self.send(401, {"detail": "Invalid credentials"})
                return False
            return True

        def do_PUT(self):
            fake.calls.append(("PUT", self.path, self.headers.get("Authorization")))
            assert self.headers.get("x-amz-tagging") == "src=api", "the presigned headers are sent as given"
            fake.uploads[self.path] = self.body()
            self.send(200)

        def do_GET(self):
            if self.path.startswith("/out/"):
                fake.calls.append(("GET", self.path, self.headers.get("Authorization")))
                return self.send(200, raw=fake.out)
            if not self.api_auth():
                return
            rid = self.path.split("/")[2]
            left = fake.states.get(rid)
            if left is None:
                return self.send(404, {"detail": "Request not found"})
            st = left.pop(0) if len(left) > 1 else left[0]
            r = {"status": st, "request_id": rid, "error": None,
                 "status_url": f"http://{self.headers['Host']}/requests/{rid}/status"}
            if st == "completed":
                r["video"] = {"url": f"http://{self.headers['Host']}/out/{rid}.mp4"}
            self.send(200, r)

        def do_POST(self):
            if not self.api_auth():
                return
            b = json.loads(self.body() or b"{}")
            host = f"http://{self.headers['Host']}"
            if self.path.startswith("/estimate/"):
                fake.estimates.append(b)
                pending = any("example.com/pending" in json.dumps(v) for v in b.values())
                usd = fake.usd_after_upload if (fake.usd_after_upload and not pending) else fake.usd
                return self.send(200, {"credits": usd * 16, "usd": usd})
            if self.path == "/files/generate-upload-url":
                n, fake.slots = fake.slots, fake.slots + 1
                return self.send(200, {"upload_url": f"{host}/upload/{n}", "public_url": f"{host}/public/{n}",
                                       "content_type": b["content_type"],
                                       "upload_headers": {"Content-Type": b["content_type"], "x-amz-tagging": "src=api"}})
            if self.path.endswith("/cancel"):
                rid = self.path.split("/")[2]
                if fake.states.get(rid, ["x"])[0] == "queued":
                    fake.states[rid] = ["canceled"]
                    return self.send(202)
                return self.send(400, {"detail": "Request is already being processed"})
            if fake.submit_faults:
                code = fake.submit_faults.pop(0)
                return self.send(code, {"detail": "Maximum number of concurrent requests (4) has been reached"
                                        if code == 400 else "upstream busy"})
            rid = f"00000000-0000-0000-0000-{len(fake.states):012d}"
            fake.states[rid] = ["queued", "in_progress", "completed"]
            fake.last_body = b
            return self.send(200, {"status": "queued", "request_id": rid, "status_url": f"{host}/requests/{rid}/status",
                                   "cancel_url": f"{host}/requests/{rid}/cancel"})
    return H


def ns(**kw):
    return argparse.Namespace(**kw)


def demo():
    from ai_editor.gen import base, gen, higgsfield, jobs
    fake = Fake()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler(fake))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    saved = {k: os.environ.get(k) for k in ("AI_EDITOR_HOME", "AI_EDITOR_HIGGSFIELD_BASE", "HIGGSFIELD_API_KEY")}
    higgsfield.BACKOFF, project_py = (0, 0, 0, 0, 0), gen.PROJECT_PY
    gen.PROJECT_PY = Path("/nonexistent/project.py")   # the ops are written and printed, not applied
    tmp = Path(tempfile.mkdtemp(prefix="gen_demo_"))
    try:
        demo_in(fake, srv, tmp, base, gen, higgsfield, jobs)
    finally:
        srv.shutdown()
        gen.PROJECT_PY = project_py
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(tmp, ignore_errors=True)


def demo_in(fake, srv, tmp, base, gen, higgsfield, jobs):
    if True:
        os.environ.update(AI_EDITOR_HOME=str(tmp / "home"), AI_EDITOR_HIGGSFIELD_BASE=f"http://127.0.0.1:{srv.server_port}",
                          HIGGSFIELD_API_KEY=KEY)
        (tmp / "home").mkdir()
        edit = tmp / "edits" / "take"
        edit.mkdir(parents=True)

        # the catalog builds bodies and refuses what a model does not take
        b = base.build_body("kling-video/v2.5-turbo/pro/text-to-video", "a city at dusk", params={"duration": 10})
        assert b == {"prompt": "a city at dusk", "duration": 10, "cfg_scale": 0.5}, b
        for bad in (lambda: base.build_body("kling-video/v2.5-turbo/pro/text-to-video", None),
                    lambda: base.build_body("kling-video/v2.5-turbo/pro/text-to-video", "x", params={"duration": 7}),
                    lambda: base.build_body("kling-video/v2.5-turbo/pro/text-to-video", "x", params={"seed": 1}),
                    lambda: base.build_body("higgsfield/genjutsu/motion-transfer/v1.0", None, video_url="u", image_urls=["i"] * 9)):
            try:
                bad()
                raise AssertionError("accepted a bad request")
            except SystemExit:
                pass
        assert set(base.models()) >= {"higgsfield/genjutsu/motion-transfer/v1.0"}
        assert higgsfield.outputs({"images": [{"url": "i1"}], "audio": {"url": "a"}, "audios": [{"url": "a"}]}) == \
            [{"kind": "image", "url": "i1"}, {"kind": "audio", "url": "a"}]

        have_ff = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        if have_ff:
            src = edit / "raw.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x568:d=8:r=30", "-f", "lavfi",
                            "-i", "sine=d=8", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
            out = tmp / "out.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x568:d=2:r=24",
                            "-pix_fmt", "yuv420p", str(out)], check=True)
            fake.out = out.read_bytes()
    if True:
        (edit / "ref.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        mt = "higgsfield/genjutsu/motion-transfer/v1.0"
        if have_ff:
            # a clip shorter than the model's 4 s minimum is refused before anything is priced or uploaded
            try:
                gen.cmd_estimate(ns(edit=str(edit), model=mt, prompt=None, negative=None, video="raw.mp4", start=0, end=2,
                                    image=["ref.png"], param=None, at=None))
                raise AssertionError("priced a 2 s clip")
            except SystemExit as e:
                assert "at least 4 s" in str(e), e
            gen.cmd_estimate(ns(edit=str(edit), model=mt, prompt="the same moves, in a red suit", negative=None,
                                video="raw.mp4", start=1.0, end=6.0, image=["ref.png"], param=["resolution=\"1080p\""], at=12.5))
            est = fake.estimates[-1]
            assert est["video_url"].startswith("https://example.com/pending/") and est["resolution"] == "1080p", \
                "nothing is uploaded to price it"
            assert not fake.uploads
            eid, e = next(iter(jobs.read(edit)["estimates"].items()))
            assert e["usd"] == 1.25 and len(e["uploads"]) == 2 and abs(e["uploads"][0]["seconds"] - 5.0) < 0.01
            assert abs(gen.probe(e["uploads"][0]["path"])["duration"] - 5.0) < 0.1, "the clip was cut to --from/--to"

            # no spending without the estimate id, within the budget
            for bad_id in ("est_nope",):
                try:
                    gen.cmd_submit(ns(edit=str(edit), confirm=bad_id))
                    raise AssertionError("submitted without an estimate")
                except SystemExit as x:
                    assert "No estimate" in str(x)
            (tmp / "home" / "profile.json").write_text(json.dumps({"gen_budget_usd": 1.0}), encoding="utf-8")
            try:
                gen.cmd_submit(ns(edit=str(edit), confirm=eid))
                raise AssertionError("went over the budget")
            except SystemExit as x:
                assert "over this month's generation budget" in str(x) and not fake.uploads
            (tmp / "home" / "profile.json").write_text(json.dumps({"gen_budget_usd": 5.0}), encoding="utf-8")

            gen.cmd_submit(ns(edit=str(edit), confirm=eid))
            assert len(fake.uploads) == 2, "the clip and the image went up only now"
            assert all(c[2] is None for c in fake.calls if c[0] == "PUT"), "no key sent to the presigned URL"
            assert fake.last_body["video_url"].endswith("/public/0") and fake.last_body["image_urls"][0].endswith("/public/1")
            assert fake.estimates[-1]["video_url"].endswith("/public/0"), "re-priced with the real inputs"
            assert not fake.submit_faults, "503 and the concurrency 400 were retried"
            assert jobs.spent() == 1.25
            jid, j = next(iter(jobs.read(edit)["jobs"].items()))
            try:
                gen.cmd_submit(ns(edit=str(edit), confirm=eid))
                raise AssertionError("spent one estimate twice")
            except SystemExit as x:
                assert "already spent" in str(x)

            gen.cmd_wait(ns(edit=str(edit), job=jid, timeout=60, no_add=False), sleep=lambda s: None)
            j = jobs.read(edit)["jobs"][jid]
            assert j["status"] == "completed" and j["polls"] >= 3 and len(j["files"]) == 1, j
            f = j["files"][0]
            assert (edit / f["path"]).read_bytes() == fake.out and abs(f["duration"] - 2.0) < 0.1 and f["width"] == 320
            assert all(c[2] is None for c in fake.calls if c[1].startswith("/out/")), "no key sent to the output URL"
            ops = json.loads((edit / "generated" / f"{jid}.ops.json").read_text(encoding="utf-8"))
            assert ops["author"] == "claude" and [o["op"] for o in ops["ops"]] == ["addTrack", "addAsset", "add"], ops
            item = ops["ops"][2]["item"]
            assert ops["ops"][2]["track"] == "trk_gen" and item["from"] == round(12.5 * 30) and item["durationInFrames"] == 60
            assert ops["ops"][1]["asset"]["generation"]["usd"] == 1.25 and ops["ops"][1]["asset"]["origin"] == "generated"
            (edit / "project.json").write_text(json.dumps({"fps": 25, "tracks": [{"id": "trk_x", "role": "generated"}]}),
                                               encoding="utf-8")
            again = gen.timeline_ops(edit, jid, j["files"])
            assert [o["op"] for o in again["ops"]] == ["addAsset", "add"] and again["ops"][1]["track"] == "trk_x"
            assert again["ops"][1]["item"]["from"] == round(12.5 * 25), "frames at the project's own fps"

            # the price rose once the real inputs were uploaded: not submitted, a new estimate to ask about
            gen.cmd_estimate(ns(edit=str(edit), model=mt, prompt=None, negative=None, video="raw.mp4", start=0, end=5,
                                image=["ref.png"], param=None, at=None))
            eid2 = [k for k, v in jobs.read(edit)["estimates"].items() if not v.get("job")][0]
            fake.usd_after_upload = 2.0
            try:
                gen.cmd_submit(ns(edit=str(edit), confirm=eid2))
                raise AssertionError("spent more than was agreed")
            except SystemExit as x:
                assert "$2.00, not $1.25" in str(x)
            fake.usd_after_upload = None

        # text to video: no uploads; stale estimates refuse; cancel while queued, not once started
        tv = "kling-video/v2.5-turbo/pro/text-to-video"
        gen.cmd_estimate(ns(edit=str(edit), model=tv, prompt="drone over a harbour at dawn", negative=None, video=None,
                            start=None, end=None, image=None, param=None, at=3))
        doc = jobs.read(edit)
        e3 = [k for k, v in doc["estimates"].items() if v["model"] == tv][0]
        jobs.update(edit, lambda d: d["estimates"][e3].update(at=time.time() - jobs.ESTIMATE_TTL_S - 1))
        try:
            gen.cmd_submit(ns(edit=str(edit), confirm=e3))
            raise AssertionError("spent a stale price")
        except SystemExit as x:
            assert "minutes old" in str(x)
        jobs.update(edit, lambda d: d["estimates"][e3].update(at=time.time()))
        (tmp / "home" / "profile.json").write_text(json.dumps({"gen_budget_usd": 5.0}), encoding="utf-8")
        gen.cmd_submit(ns(edit=str(edit), confirm=e3))
        j3 = [k for k, v in jobs.read(edit)["jobs"].items() if v["model"] == tv][0]
        p = higgsfield.Higgsfield()
        rid = jobs.read(edit)["jobs"][j3]["request_id"]
        assert p.cancel(rid) is True and p.status(rid).status == "canceled"
        fake.states[rid] = ["in_progress"]
        assert p.cancel(rid) is False, "a started request cannot be canceled"
        assert jobs.poll_delay(0) == 5 and jobs.poll_delay(10) == 60

        # a wrong key: a clear message, never the key itself
        bad = higgsfield.Higgsfield(key="kid:wrong")
        try:
            bad.status(rid)
            raise AssertionError("a wrong key passed")
        except higgsfield.HiggsfieldError as x:
            assert x.code == 401 and "wrong" not in str(x)
        assert gen.valid_key(KEY) and not gen.valid_key("nocolon") and not gen.valid_key("a:b")
        assert all(c[2] == f"Key {KEY}" for c in fake.calls if c[0] in ("POST",) and "/upload/" not in c[1]
                   and c[2] != "Key kid:wrong"), "every API call carries Key id:secret"
        print("gen demo ok" + ("" if have_ff else " (no ffmpeg: the clip steps were skipped)"))
