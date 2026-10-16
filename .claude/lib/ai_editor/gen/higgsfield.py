"""Higgsfield's API (https://docs.higgsfield.ai/docs). Stdlib only, through the editor's net.py.

    Authorization: Key <key id>:<key secret>             every API call (never sent to upload or output URLs)
    POST /files/generate-upload-url {content_type}       -> {upload_url, upload_headers, public_url}; PUT the bytes
    POST /estimate/<model>   same body as the submit      -> {credits, usd}
    POST /<model>            the model's inputs          -> {status: queued, request_id, status_url, cancel_url}
    GET  /requests/<id>/status                           -> {status, error, images[].url | video.url | audio.url | audios[].url}
    POST /requests/<id>/cancel                           -> 202 while queued, 400 once it started

Over the account's concurrency the API answers 400 "Maximum number of concurrent requests"; that, 429 and
5xx are retried with backoff and jitter (the API sends no Retry-After). AI_EDITOR_HIGGSFIELD_BASE points the
client at another server (the demo's fake one).
"""
import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from ai_editor import keys, net
    from ai_editor.gen import base
except ImportError:   # run from .claude/lib
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ai_editor import keys, net
    from ai_editor.gen import base

BACKOFF = (2, 5, 10, 20, 40)   # seconds before each retry


class HiggsfieldError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(f"Higgsfield HTTP {code}: {msg}")
        self.code = code


def retryable(code, body):
    return code == 0 or code == 429 or code >= 500 or (code == 400 and "concurrent requests" in body.lower())


class Higgsfield:
    name = "higgsfield"

    def __init__(self, key=None, base_url=None, sleep=time.sleep):
        self.key = key or keys.get("higgsfield")[0]
        if not self.key:
            raise SystemExit("No Higgsfield key. The user saves it in their own terminal (never in this chat):\n"
                             "  python3 .claude/lib/ai_editor/gen/gen.py setkey\n"
                             "with the key id and secret from https://console.higgsfield.ai joined as id:secret.")
        self.base = (base_url or os.environ.get("AI_EDITOR_HIGGSFIELD_BASE")
                     or base.catalog()["providers"]["higgsfield"]["base_url"]).rstrip("/")
        self.sleep = sleep

    # -- HTTP --------------------------------------------------------------------------------------------
    def _once(self, method, url, body=None, headers=None, auth=True, data=None):
        h = {"User-Agent": "ai-editor", **(headers or {})}
        if auth:
            h["Authorization"] = f"Key {self.key}"
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with net.urlopen(req, 120) as r:
                raw = r.read()
                return r.status, raw.decode(errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except (urllib.error.URLError, OSError) as e:
            return 0, net.friendly(e)

    def call(self, method, path_or_url, body=None, **kw):
        """JSON in, JSON out, retried with backoff on 429, 5xx, no connection and the concurrency 400."""
        url = path_or_url if path_or_url.startswith("http") else f"{self.base}/{path_or_url.lstrip('/')}"
        for i in range(len(BACKOFF) + 1):
            code, text = self._once(method, url, body, **kw)
            if 200 <= code < 300:
                try:
                    return json.loads(text) if text.strip() else {}
                except ValueError:
                    return {"text": text}
            if i < len(BACKOFF) and retryable(code, text):
                self.sleep(BACKOFF[i] * (0.8 + 0.4 * random.random()))
                continue
            if code in (401, 403):
                raise HiggsfieldError(code, "the key was refused. Save it again with gen.py setkey.")
            raise HiggsfieldError(code, text[:300])

    # -- the provider ------------------------------------------------------------------------------------
    def upload(self, path, content_type):
        """A local file into Higgsfield's storage; returns the public_url a model input takes."""
        r = self.call("POST", "/files/generate-upload-url", {"content_type": content_type})
        data = Path(path).read_bytes()
        code, text = self._once("PUT", r["upload_url"], headers=dict(r.get("upload_headers") or {"Content-Type": content_type}),
                                auth=False, data=data)
        if not 200 <= code < 300:
            raise HiggsfieldError(code, f"upload of {Path(path).name} failed: {text[:200]}")
        return r["public_url"]

    def estimate(self, req):
        r = self.call("POST", f"/estimate/{req.model}", req.body)
        return base.Estimate(usd=float(r.get("usd") or 0), credits=r.get("credits"), raw=r)

    def submit(self, req):
        r = self.call("POST", f"/{req.model}", req.body)
        if not r.get("request_id"):
            raise HiggsfieldError(200, f"no request_id in {str(r)[:200]}")
        return r

    def status(self, request_id):
        r = self.call("GET", f"/requests/{request_id}/status")
        return base.Status(request_id, r.get("status", "unknown"), outputs(r), r.get("error"))

    def cancel(self, request_id):
        try:
            self.call("POST", f"/requests/{request_id}/cancel")
            return True
        except HiggsfieldError as e:
            if e.code == 400:   # already started: it runs to the end and is billed
                return False
            raise

    def fetch(self, url, dest):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        net.retrieve(url, tmp, timeout=300)   # output URLs are public: no key sent
        os.replace(tmp, dest)
        return dest


def outputs(r):
    """[{"kind", "url"}] from a status response (or a webhook's payload)."""
    out = [{"kind": "image", "url": i["url"]} for i in r.get("images") or [] if i.get("url")]
    if (r.get("video") or {}).get("url"):
        out.append({"kind": "video", "url": r["video"]["url"]})
    seen = set()
    for a in [r.get("audio") or {}, *(r.get("audios") or [])]:
        if a.get("url") and a["url"] not in seen:
            seen.add(a["url"])
            out.append({"kind": "audio", "url": a["url"]})
    return out
