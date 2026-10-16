"""Join rendered chunks into one video. Run in a folder holding chunks/chunk-<i>.mkv; writes out/render.mp4.

    CHUNKS='[{"i": "00", "from": 0, "to": 1325}]' FPS=30 [AUDIO_RATE=48000 AUDIO_BITRATE=320k] python3 join.py

AUDIO_RATE and AUDIO_BITRATE are the format's export audio (lib/ai_editor/formats.py, sent by ghrender.py);
without them, 48 kHz AAC at 320k as before. Chunks carry PCM audio that runs a few samples past the last frame (16 at 30 fps). Each chunk's audio is cut to
exactly its frames, the pieces laid end to end and encoded to AAC once; the video is copied. Measured on a 3-chunk
render: no gap or step at the joins, sync held to the sample. Used by the GitHub Actions workflow, the laptop's
chunked fallback and Modal (edit.py reads this file as JOIN).
"""
import json, os, re, subprocess
fps, sr = float(os.environ["FPS"]), int(os.environ.get("AUDIO_RATE") or 48000)
bitrate = os.environ.get("AUDIO_BITRATE") or "320k"
if sr not in (44100, 48000) or not re.fullmatch(r"\d{2,3}k", bitrate):   # workflow inputs: never trusted as ffmpeg args
    raise SystemExit(f"join.py: unsupported audio {sr} Hz / {bitrate!r}")
chunks = json.loads(os.environ["CHUNKS"])
os.makedirs("out", exist_ok=True)
with open("list.txt", "w") as lst, open("audio.raw", "wb") as pcm:
    for c in chunks:
        f = os.path.abspath(f"chunks/chunk-{c['i']}.mkv")
        lst.write(f"file '{f}'\n")
        n = 4 * (round((c["to"] + 1) * sr / fps) - round(c["from"] * sr / fps))
        a = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-map", "0:a", "-f", "s16le", "-ac", "2",
                            "-ar", str(sr), "-"], capture_output=True, check=True).stdout
        pcm.write(a[:n].ljust(n, b"\0"))
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
                "-f", "s16le", "-ar", str(sr), "-ac", "2", "-i", "audio.raw", "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", bitrate, "-movflags", "+faststart", "out/render.mp4"], check=True)
