#!/usr/bin/env python3
"""Generate on top of the user's footage with Higgsfield: price first, the user says yes, then spend. Stdlib only.

    gen.py models [--kind video-to-video|text-to-video|image-to-video|text-to-image]
    gen.py setkey                                  save the Higgsfield key (id:secret) in YOUR terminal, hidden
    gen.py estimate EDIT --model ID [--prompt T] [--negative T] [--video FILE|URL --from S --to S]
                         [--image FILE|URL ...] [--param name=value ...] [--at S]
                                                   price it; prints the estimate id, $ and what would be uploaded
    gen.py submit EDIT --confirm EST_ID            only after the user said yes to that price: upload, submit
    gen.py status EDIT [JOB] [--now]               poll what is due (backs off 5 s .. 60 s)
    gen.py wait EDIT JOB [--timeout 1800]          poll until it ends, then fetch
    gen.py fetch EDIT JOB [--no-add]               download into EDIT/generated/, probe, add to the timeline
    gen.py cancel EDIT JOB                         only while queued (started requests are billed)
    gen.py list EDIT
    gen.py demo                                    self-check against a fake Higgsfield server, no network

Nothing is spent without `submit --confirm <estimate id>`, an estimate younger than 30 min, and the month's
profile.json gen_budget_usd (when set) still covering it. A local clip or image is uploaded to Higgsfield only at
submit, after the user agreed; a clip is trimmed to --from/--to and to the model's limits first.
Results land in EDIT/generated/ and on the timeline's "generated" track (project.py apply, author claude);
without project.py the ops are written to generated/<job>.ops.json and printed.
"""
import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

LIB = Path(__file__).resolve().parents[2]          # .claude/lib
sys.path.insert(0, str(LIB))
from ai_editor import keys                          # noqa: E402
from ai_editor.gen import base, jobs                # noqa: E402

EDITOR = LIB.parent                                 # .claude
PROJECT_PY = EDITOR / "skills" / "style-edit" / "scripts" / "project.py"
PENDING = "upload://"                               # an input still on this computer: uploaded at submit


def provider(name="higgsfield"):
    from ai_editor.gen.higgsfield import Higgsfield
    return Higgsfield()


def edit_dir(p):
    d = Path(p).resolve()
    if not d.is_dir():
        raise SystemExit(f"No edit folder {d}")
    return d


# -- inputs -------------------------------------------------------------------------------------------
def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration",
                        "-of", "json", str(f)], capture_output=True, text=True)
    if r.returncode:
        return {}
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    return {"duration": float((j.get("format") or {}).get("duration") or 0), "width": v.get("width"),
            "height": v.get("height"), "fps": round(float(num) / float(den or 1), 3) if float(num or 0) else None}


def trim_clip(src, out, start, end, limits):
    """src[start:end] as a silent H.264 clip inside the model's min/max input length."""
    lo, hi = limits.get("min_input_s"), limits.get("max_input_s")
    if end is None:
        end = probe(src).get("duration") or 0
    length = end - (start or 0)
    if lo and length < lo:
        raise SystemExit(f"The clip is {length:.1f} s; this model needs at least {lo} s. Widen --from/--to.")
    if hi and length > hi:
        end, length = (start or 0) + hi, hi
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start or 0:.3f}", "-to", f"{end:.3f}", "-i", str(src),
                        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"ffmpeg could not cut the clip: {r.stderr[-300:]}")
    return out, round(length, 2)


def local_or_url(v, edit, kind, start=None, end=None, limits=None, tag="in"):
    """(value for the body, upload record or None). A URL passes through; a file becomes upload://<path>."""
    if re.match(r"https?://", v):
        return v, None
    f = Path(v)
    if not f.is_absolute():
        f = (edit / v) if (edit / v).exists() else f.resolve()
    if not f.is_file():
        raise SystemExit(f"No file {v}")
    seconds = None
    if kind == "video":
        f, seconds = trim_clip(f, edit / "generated" / "inputs" / f"{tag}-{jobs.new_id('clip')}.mp4", start, end, limits or {})
    ctype = mimetypes.guess_type(f.name)[0] or ("video/mp4" if kind == "video" else "image/jpeg")
    return PENDING + str(f), {"path": str(f), "kind": kind, "content_type": ctype, "seconds": seconds}


def parse_params(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


# -- commands -----------------------------------------------------------------------------------------
def cmd_models(a):
    for mid, m in base.models().items():
        if a.kind and m["kind"] != a.kind:
            continue
        lim = m.get("limits") or {}
        extra = f" clip {lim.get('min_input_s', 0)}-{lim.get('max_input_s', '?')} s" if lim else ""
        print(f"{mid:52} {m['kind']:15} {m['use']}{extra}")


def valid_key(k):
    return bool(re.fullmatch(r"[A-Za-z0-9_\-.]{2,}:[A-Za-z0-9_\-.]{8,}", k or ""))


def cmd_setkey(a):
    import getpass
    print("Higgsfield key: the key id and the secret from https://console.higgsfield.ai, joined as id:secret.")
    k = (getpass.getpass("Paste it and press Enter (it stays hidden): ") if sys.stdin.isatty() else sys.stdin.readline()).strip()
    if not valid_key(k):
        raise SystemExit("Nothing saved: that is not id:secret. Copy the key id, a colon, then the secret.")
    ok, msg = keys.verify("higgsfield", k)
    if not ok and not msg.startswith("no connection"):
        raise SystemExit(f"Not saved: {msg}")
    print(f"Saved to {keys.save('higgsfield', k)}." + ("" if ok else f" Not tested ({msg})."))


def cmd_estimate(a):
    edit, m = edit_dir(a.edit), base.model(a.model)
    uploads, video, images = [], None, []
    if a.video:
        video, up = local_or_url(a.video, edit, "video", a.start, a.end, m.get("limits"), "video")
        uploads += [up] if up else []
    for i in a.image or []:
        v, up = local_or_url(i, edit, "image")
        images.append(v)
        uploads += [up] if up else []
    body = base.build_body(a.model, a.prompt, a.negative, video, images, parse_params(a.param))
    est = provider().estimate(base.Req(a.model, priced(body)))
    eid = jobs.add_estimate(edit, a.model, body, est, uploads)
    jobs.update(edit, lambda d: d["estimates"][eid].update(at_s=a.at if a.at is not None else (a.start or 0)))
    secs = sum(u["seconds"] or 0 for u in uploads if u["kind"] == "video")
    over = jobs.check_budget(est.usd)
    sent = ", ".join(f"{Path(u['path']).name}" + (f" ({u['seconds']} s of your video)" if u["seconds"] else "") for u in uploads)
    print(json.dumps({"estimate": eid, "model": a.model, "usd": est.usd, "credits": est.credits,
                      "uploads": [u["path"] for u in uploads], "over_budget": over}, indent=1))
    print(f"ASK: {m['name']} would cost about ${est.usd:.2f}" + (f" ({est.credits} credits)" if est.credits is not None else "")
          + (f" and uploads {sent} to Higgsfield" if uploads else "") + ". Go ahead?"
          + (f"  NOTE: {over}" if over else ""))


def priced(body):
    """The body as priced: an input still on this computer is named, not uploaded, at estimate time."""
    return {k: ([placeholder(x) for x in v] if isinstance(v, list) else placeholder(v)) for k, v in body.items()}


def placeholder(v):
    return f"https://example.com/pending/{Path(v[len(PENDING):]).name}" if isinstance(v, str) and v.startswith(PENDING) else v


def cmd_submit(a):
    edit = edit_dir(a.edit)
    e = jobs.usable_estimate(edit, a.confirm)
    over = jobs.check_budget(e["usd"])
    if over:
        raise SystemExit(f"Not submitted: {over}.")
    p = provider()
    body, sent = e["body"], {}
    for up in e.get("uploads") or []:
        sent[PENDING + up["path"]] = p.upload(Path(up["path"]), up["content_type"])
    if sent:
        body = {k: ([sent.get(x, x) for x in v] if isinstance(v, list) else sent.get(v, v)) for k, v in body.items()}
        again = p.estimate(base.Req(e["model"], body))   # priced with the real inputs: never spend more than was agreed
        if again.usd > e["usd"] * 1.05 + 0.01:
            eid = jobs.add_estimate(edit, e["model"], body, again)
            raise SystemExit(f"Not submitted: with the uploaded inputs the price is ${again.usd:.2f}, not ${e['usd']:.2f}. "
                             f"Ask again; if yes: gen.py submit {a.edit} --confirm {eid}")
    sub = p.submit(base.Req(e["model"], body))
    jobs.record_spend(e["usd"])
    jid = jobs.add_job(edit, a.confirm, e["model"], sub)
    print(json.dumps({"job": jid, "request_id": sub["request_id"], "status": sub.get("status")}, indent=1))


def poll(edit, jid, p):
    st = p.status(read_job(edit, jid)["request_id"])
    return jobs.set_status(edit, jid, st)


def read_job(edit, jid):
    j = jobs.read(edit)["jobs"].get(jid)
    if not j:
        raise SystemExit(f"No job {jid} in {edit}")
    return j


def cmd_status(a):
    edit = edit_dir(a.edit)
    ids = [a.job] if a.job else (list(jobs.read(edit)["jobs"]) if a.now else jobs.due(edit))
    p = provider() if ids else None
    for jid in ids:
        j = read_job(edit, jid)
        if j["status"] not in base.TERMINAL:
            j = poll(edit, jid, p)
        print(f"{jid} {j['status']}" + (f" error: {j['error']}" if j.get("error") else "")
              + (f" outputs: {len(j['outputs'])}" if j["outputs"] else ""))
    if not ids:
        print("nothing due")


def cmd_wait(a, sleep=time.sleep):
    edit, p = edit_dir(a.edit), provider()
    end = time.time() + a.timeout
    while True:
        j = poll(edit, a.job, p)
        if j["status"] in base.TERMINAL:
            break
        if time.time() > end:
            raise SystemExit(f"{a.job} still {j['status']} after {a.timeout} s; run gen.py status later")
        sleep(jobs.poll_delay(j["polls"]))
    if j["status"] != "completed":
        raise SystemExit(f"{a.job} ended {j['status']}" + (f": {j['error']}" if j.get("error") else "")
                         + " (failed and nsfw requests are not billed)")
    a.no_add = getattr(a, "no_add", False)
    cmd_fetch(a, p)


def cmd_fetch(a, p=None):
    edit = edit_dir(a.edit)
    j = read_job(edit, a.job)
    if j["status"] != "completed":
        raise SystemExit(f"{a.job} is {j['status']}, not completed")
    p = p or provider()
    files = []
    for n, o in enumerate(j["outputs"]):
        ext = Path(o["url"].split("?")[0]).suffix or {"video": ".mp4", "image": ".png", "audio": ".mp3"}[o["kind"]]
        f = p.fetch(o["url"], edit / "generated" / f"{a.job}-{n}{ext}")
        files.append({"path": str(f.relative_to(edit).as_posix()), "kind": o["kind"], **(probe(f) if o["kind"] != "image" else {})})
    jobs.update(edit, lambda d: d["jobs"][a.job].update(files=files))
    print(json.dumps({"job": a.job, "files": files}, indent=1))
    if not getattr(a, "no_add", False):
        add_to_timeline(edit, a.job, files)


def timeline_ops(edit, jid, files):
    """addAsset + add on the "generated" track (addTrack first when the project has none), in frames."""
    pj = jobs._load(edit / "project.json", {})
    fps = pj.get("fps") or 30
    track = next((t["id"] for t in pj.get("tracks", []) if t.get("role") == "generated"), None)
    ops = [] if track else [{"op": "addTrack", "track": {"id": "trk_gen", "kind": "video", "role": "generated",
                                                          "name": "Generated", "items": []}}]
    track = track or "trk_gen"
    doc = jobs.read(edit)
    j = doc["jobs"][jid]
    e = doc["estimates"].get(j["estimate"], {})
    at = round(float(e.get("at_s") or 0) * fps)
    for n, f in enumerate(files):
        if f["kind"] not in ("video", "image"):
            continue
        aid = f"ast_{jid}_{n}"
        dur = round((f.get("duration") or 3) * fps)
        ops.append({"op": "addAsset", "asset": {
            "id": aid, "kind": f["kind"], "src": f["path"], "width": f.get("width"), "height": f.get("height"),
            "fps": f.get("fps"), "durationInFrames": dur if f["kind"] == "video" else None, "origin": "generated",
            "generation": {"provider": "higgsfield", "model": j["model"], "request_id": j["request_id"], "usd": e.get("usd")}}})
        ops.append({"op": "add", "track": track, "item": {"type": "generated", "asset": aid, "from": at,
                                                         "durationInFrames": dur, "trimIn": 0, "origin": "claude"}})
        at += dur
    return {"author": "claude", "label": f"Add generated {'clip' if len(files) == 1 else 'clips'} ({j['model'].split('/')[0]})",
            "ops": ops}


def add_to_timeline(edit, jid, files):
    batch = timeline_ops(edit, jid, files)
    opsf = edit / "generated" / f"{jid}.ops.json"
    opsf.write_text(json.dumps(batch, indent=1), encoding="utf-8")
    if PROJECT_PY.is_file():
        r = subprocess.run([sys.executable, str(PROJECT_PY), "apply", str(edit), str(opsf)], capture_output=True, text=True)
        if r.returncode == 0:
            jobs.update(edit, lambda d: d["jobs"][jid].update(added=True))
            return print(f"added to the timeline: {r.stdout.strip()[-200:]}")
        print(f"project.py apply did not take it ({r.stderr.strip()[-200:]}); the ops are in {opsf}", file=sys.stderr)
    else:
        print(f"no project.py yet: apply {opsf} to the timeline when it exists")
    print(json.dumps(batch, indent=1))


def cmd_cancel(a):
    edit = edit_dir(a.edit)
    ok = provider().cancel(read_job(edit, a.job)["request_id"])
    print("canceled (not billed)" if ok else "already started: it runs to the end and is billed")


def cmd_list(a):
    doc = jobs.read(edit_dir(a.edit))
    for jid, j in doc["jobs"].items():
        e = doc["estimates"].get(j["estimate"], {})
        print(f"{jid} {j['status']:11} ${e.get('usd', 0):.2f} {j['model']} files={len(j.get('files') or [])}")
    pend = [k for k, e in doc["estimates"].items() if not e.get("job")]
    if pend:
        print("estimates not submitted: " + ", ".join(pend))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("models"); s.add_argument("--kind"); s.set_defaults(fn=cmd_models)
    sub.add_parser("setkey").set_defaults(fn=cmd_setkey)
    s = sub.add_parser("estimate")
    s.add_argument("edit"); s.add_argument("--model", required=True); s.add_argument("--prompt"); s.add_argument("--negative")
    s.add_argument("--video"); s.add_argument("--from", dest="start", type=float); s.add_argument("--to", dest="end", type=float)
    s.add_argument("--image", action="append"); s.add_argument("--param", action="append"); s.add_argument("--at", type=float)
    s.set_defaults(fn=cmd_estimate)
    s = sub.add_parser("submit"); s.add_argument("edit"); s.add_argument("--confirm", required=True); s.set_defaults(fn=cmd_submit)
    s = sub.add_parser("status"); s.add_argument("edit"); s.add_argument("job", nargs="?"); s.add_argument("--now", action="store_true")
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("wait"); s.add_argument("edit"); s.add_argument("job"); s.add_argument("--timeout", type=int, default=1800)
    s.add_argument("--no-add", action="store_true"); s.set_defaults(fn=cmd_wait)
    s = sub.add_parser("fetch"); s.add_argument("edit"); s.add_argument("job"); s.add_argument("--no-add", action="store_true")
    s.set_defaults(fn=cmd_fetch)
    s = sub.add_parser("cancel"); s.add_argument("edit"); s.add_argument("job"); s.set_defaults(fn=cmd_cancel)
    s = sub.add_parser("list"); s.add_argument("edit"); s.set_defaults(fn=cmd_list)
    sub.add_parser("demo").set_defaults(fn=lambda a: __import__("ai_editor.gen.demo_server", fromlist=["demo"]).demo())
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
