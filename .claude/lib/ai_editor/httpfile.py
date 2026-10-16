#!/usr/bin/env python3
"""Send a file from a BaseHTTPRequestHandler with byte ranges (206), so a <video> or the Remotion Player can seek.
Stdlib only. Used by preview.py (the live preview) and app_api.py (/api/file).

    send_file(handler, path)

    python3 httpfile.py demo    self-check
"""
import mimetypes
import re
import sys
import tempfile
import threading
from pathlib import Path

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("audio/wav", ".wav")


def send_file(h, path, cache="no-cache"):
    path = Path(path)
    size = path.stat().st_size
    start, end = 0, size - 1
    m = re.match(r"bytes=(\d*)-(\d*)", h.headers.get("Range") or "")
    if m and (m[1] or m[2]) and size:
        start, end = (int(m[1]), int(m[2]) if m[2] else size - 1) if m[1] else (max(0, size - int(m[2])), size - 1)
        end = min(end, size - 1)
        if start > end:
            h.send_response(416)
            h.send_header("Content-Range", f"bytes */{size}")
            h.send_header("Content-Length", "0")
            h.end_headers()
            return
        h.send_response(206)
        h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    else:
        h.send_response(200)
    h.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    h.send_header("Content-Length", str(max(0, end - start + 1)))
    h.send_header("Accept-Ranges", "bytes")
    h.send_header("Cache-Control", cache)
    h.end_headers()
    try:
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(left, 1 << 20))
                if not chunk:
                    break
                h.wfile.write(chunk)
                left -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        pass


def demo():
    import http.client
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "v.mp4"
        f.write_bytes(bytes(range(256)) * 4)

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                send_file(self, f)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def get(rng=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", "/", headers={"Range": rng} if rng else {})
            r = c.getresponse()
            return r.status, r.getheader("Content-Range"), r.read()
        assert get() == (200, None, f.read_bytes())
        assert get("bytes=10-19") == (206, "bytes 10-19/1024", f.read_bytes()[10:20])
        assert get("bytes=-4") == (206, "bytes 1020-1023/1024", f.read_bytes()[-4:])
        assert get("bytes=1000-") == (206, "bytes 1000-1023/1024", f.read_bytes()[1000:])
        assert get("bytes=5000-")[0] == 416
        srv.shutdown()
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        print(__doc__)
        sys.exit(2)
