#!/usr/bin/env python3
"""Render on GitHub Actions in this editor's own public repo, with the footage encrypted. Stdlib only (+ gh, age).

    python3 ghrender.py demo     self-check (a fake gh; real age when it is installed)

edit.py drives it: `edit.py render edits/NAME --github` (submit, then wait and fetch), or the two halves
`edit.py github-push edits/NAME` and `edit.py github-fetch edits/NAME`.

The flow, nothing readable ever leaves this computer:
  1. render.mjs bundle (the renderer, its components and the footage) + plan.json + meta.json, as one tar,
     encrypted with age to the repo's recipient (the public half of $AI_EDITOR_HOME/render-key.txt),
     split into parts under 2 GiB (a release file's cap).
  2. `gh release create render-<rid> --draft` with the parts. A draft is only visible with push access.
  3. `gh workflow run render.yml` with render_id, frames, fps, format. The run is named "render <rid>",
     which is how this finds its own run among others.
  4. The workflow (.github/workflows/render.yml) decrypts with the RENDER_KEY secret, renders chunks in
     parallel, joins them, and uploads render-<rid> encrypted to the same recipient.
  5. Here: wait, download, decrypt with the local key, then delete the draft release and the run's artifacts
     (--purge-logs also deletes the run). <rid> is random: no file or video name is ever sent in clear.

Keys: `setup.py gh-render-key` makes the age identity, saves it to $AI_EDITOR_HOME/render-key.txt (0600),
sets the RENDER_KEY secret (from stdin) and the RENDER_RECIPIENT variable on the repo.
"""
import io
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HOME = Path(os.environ.get("AI_EDITOR_HOME", Path.home() / ".ai-video-editor"))
REPO_ROOT = Path(__file__).resolve().parents[3]
KEY_FILE = HOME / "render-key.txt"
DEFAULT_REPO = "Conz-Wilts/ai-editor"
WORKFLOW = "render.yml"
PART_MAX = 1_900_000_000          # a release file is capped at 2 GiB
RID_RE = re.compile(r"^[a-f0-9]{12}$")

# age, pinned: https://github.com/FiloSottile/age/releases/tag/v1.2.1 (sha256 of each download, taken 2026-10-17).
AGE_VERSION = "v1.2.1"
AGE_PINS = {
    ("Linux", "x86_64"): ("linux-amd64.tar.gz", "7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50"),
    ("Linux", "aarch64"): ("linux-arm64.tar.gz", "57fd79a7ece5fe501f351b9dd51a82fbee1ea8db65a8839db17f5c080245e99f"),
    ("Darwin", "x86_64"): ("darwin-amd64.tar.gz", "424e1d64438a730626540b2e01e98d132a64214442ca9465b3e82336d12e633e"),
    ("Darwin", "arm64"): ("darwin-arm64.tar.gz", "cf79875bd5970dc2dac60c87fa50cee1ff1f9a41b0eb273f65e174aff37c367a"),
    ("Windows", "AMD64"): ("windows-amd64.zip", "46db0db71f146061f7c8fffa912cb806aef1bc8450e27a3abc1744f0591b89fb"),
}
EXE = ".exe" if platform.system() == "Windows" else ""


def age_bin(name="age"):
    """The pinned age in $AI_EDITOR_HOME/bin, else one on the PATH, else None."""
    mine = HOME / "bin" / f"{name}{EXE}"
    return str(mine) if mine.is_file() else shutil.which(name)


def need(tool, how):
    if not tool:
        sys.exit(f"ERROR: {how}")
    return tool


def gh(*args, check=True, input=None):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=input)
    if check and r.returncode:
        sys.exit(f"ERROR: gh {args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.strip()[-400:]}")
    return r


def repo_name():
    """AI_EDITOR_RENDER_REPO, else this checkout's GitHub origin, else the editor's home repo."""
    env = os.environ.get("AI_EDITOR_RENDER_REPO")
    if env:
        return env
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else DEFAULT_REPO


def recipient(key_file=KEY_FILE, keygen=None):
    """The public half of the local identity: what everything is encrypted to."""
    if not Path(key_file).is_file():
        sys.exit("ERROR: no render key yet. Run: python3 .claude/skills/setup/scripts/setup.py gh-render-key")
    kg = need(keygen or age_bin("age-keygen"), "age is not installed: python3 .claude/skills/setup/scripts/setup.py age")
    return subprocess.run([kg, "-y", str(key_file)], capture_output=True, text=True, check=True).stdout.strip()


def pack(bundle_dir, plan_path, meta, out_dir, rcpt, age=None):
    """bundle/ + plan.json + meta.json -> one tar -> age -> payload.part-NN files in out_dir. Returns the parts."""
    age = need(age or age_bin(), "age is not installed: python3 .claude/skills/setup/scripts/setup.py age")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    enc = out_dir / "payload.age"
    with open(enc, "wb") as f:
        p = subprocess.Popen([age, "-r", rcpt], stdin=subprocess.PIPE, stdout=f)
        with tarfile.open(fileobj=p.stdin, mode="w|") as tar:
            tar.add(str(bundle_dir), arcname="bundle")
            tar.add(str(plan_path), arcname="plan.json")
            data = json.dumps(meta).encode()
            ti = tarfile.TarInfo("meta.json")
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
        p.stdin.close()
        if p.wait():
            sys.exit("ERROR: age could not encrypt the render payload")
    return split(enc, PART_MAX)


def split(path, size):
    """path -> payload.part-00, -01, ... of at most size bytes beside it (the workflow cats them back)."""
    path = Path(path)
    total, parts = path.stat().st_size, []
    with open(path, "rb") as f:
        while True:
            part = path.with_name(f"payload.part-{len(parts):02d}")
            with open(part, "wb") as out:
                left = size
                while left and (buf := f.read(min(left, 1 << 24))):
                    out.write(buf)
                    left -= len(buf)
            parts.append(part)
            if f.tell() >= total:
                break
    path.unlink()
    return parts


def run_scripts(workflow_text):
    """Every `run:` script in a workflow (block or one line), for the lint in demo()."""
    out, lines = [], workflow_text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run: ?(.*)$", line)
        if not m:
            continue
        if m.group(2).strip() not in ("|", ">"):
            out.append(m.group(2))
            continue
        ind = len(m.group(1))
        body = []
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= ind:
                break
            body.append(nxt)
        out.append("\n".join(body))
    return out


def audio_for(fmt):
    """(sample rate, AAC bitrate) of the format's export settings (formats.py); 48000/320k without one."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from ai_editor import formats
        a = (formats.get(fmt)["export"].get("audio") or {}) if fmt else {}
    except Exception:   # an unknown format id or no formats.json: the defaults
        a = {}
    return str(a.get("sampleRate", 48000)), a.get("bitrate", "320k")


def submit(edit, plan_path, bundle_dir, tag, fmt="", repo=None, gh=gh, age=None, keygen=None, key_file=KEY_FILE):
    """Encrypt, upload as a draft release, start the workflow. Writes edits/NAME/github<tag>.json for fetch."""
    repo = repo or repo_name()
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    rid = secrets.token_hex(6)
    meta = {"render_id": rid, "frames": plan["durationInFrames"], "fps": plan["fps"], "format": fmt}
    with tempfile.TemporaryDirectory(prefix="ghrender-") as t:
        parts = pack(bundle_dir, plan_path, meta, t, recipient(key_file, keygen), age)
        mb = sum(p.stat().st_size for p in parts) / 1e6
        print(f"uploading the encrypted footage ({mb:.0f} MB, {len(parts)} part{'s' * (len(parts) > 1)}) to {repo}", flush=True)
        gh("release", "create", f"render-{rid}", *map(str, parts), "--draft", "-R", repo,
           "--title", f"render-{rid}", "--notes", "Encrypted render payload; deleted after the render.")
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
    rate, bitrate = audio_for(fmt)
    for attempt in range(10):
        r = gh("workflow", "run", WORKFLOW, "-R", repo, "-f", f"render_id={rid}", "-f", f"frames={meta['frames']}",
               "-f", f"fps={meta['fps']}", "-f", f"format={fmt}", "-f", f"audio_rate={rate}",
               "-f", f"audio_bitrate={bitrate}", check=attempt == 9)
        if r.returncode == 0:
            break
        time.sleep(3)
    job = {"repo": repo, "render_id": rid, "release": f"render-{rid}", "started": started, "format": fmt}
    (Path(edit) / f"github{tag}.json").write_text(json.dumps(job), encoding="utf-8")
    print(f"render started on GitHub Actions (render {rid})")
    return job


def find_run(repo, rid, gh=gh, tries=20, wait=3):
    """The run named "render <rid>": never someone else's or an older one."""
    for i in range(tries):
        runs = json.loads(gh("run", "list", "-R", repo, "--workflow", WORKFLOW, "-L", "30",
                             "--json", "databaseId,displayTitle,url,status,conclusion").stdout or "[]")
        mine = [r for r in runs if r.get("displayTitle") == f"render {rid}"]
        if mine:
            return mine[0]
        if i + 1 < tries:
            time.sleep(wait)
    return None


def decrypt(src, dst, key_file=KEY_FILE, age=None):
    age = need(age or age_bin(), "age is not installed: python3 .claude/skills/setup/scripts/setup.py age")
    subprocess.run([age, "-d", "-i", str(key_file), "-o", str(dst), str(src)], check=True)


def cleanup(repo, rid, run_id, purge_logs=False, gh=gh):
    """The draft release (the encrypted footage) and the run's artifacts; with purge_logs the run itself."""
    gh("release", "delete", f"render-{rid}", "-y", "--cleanup-tag", "-R", repo, check=False)
    if run_id:
        arts = gh("api", f"repos/{repo}/actions/runs/{run_id}/artifacts", check=False).stdout
        for a in (json.loads(arts).get("artifacts", []) if arts.strip() else []):
            gh("api", "-X", "DELETE", f"repos/{repo}/actions/artifacts/{a['id']}", check=False)
        if purge_logs:
            gh("run", "delete", str(run_id), "-R", repo, check=False)
    print(f"deleted render {rid} from {repo}: the encrypted footage and the run's artifacts" + (" and its log" if purge_logs else ""))


def fetch(edit, tag, gh=gh, age=None, key_file=KEY_FILE, purge_logs=False, keep=False, watch=True):
    """Wait for the run started by submit, download and decrypt it to edits/NAME/render-github<tag>.mp4."""
    meta = Path(edit) / f"github{tag}.json"
    if not meta.exists():
        sys.exit("ERROR: no GitHub render started for this plan: run edit.py render --github first")
    job = json.loads(meta.read_text(encoding="utf-8"))
    repo, rid = job["repo"], job["render_id"]
    run = find_run(repo, rid, gh)
    if not run:
        sys.exit(f"ERROR: no run named \"render {rid}\" in {repo}: the workflow did not start (gh workflow list -R {repo})")
    print(f"waiting for {run['url']}", flush=True)
    if watch and subprocess.run(["gh", "run", "watch", str(run["databaseId"]), "-R", repo, "--exit-status"]).returncode:
        sys.exit(f"ERROR: the render failed. Open {run['url']} for the log (it never shows the footage).")
    out = Path(edit) / f"render-github{tag}.mp4"
    with tempfile.TemporaryDirectory(prefix="ghfetch-") as t:
        gh("run", "download", str(run["databaseId"]), "-R", repo, "-n", f"render-{rid}", "-D", t)
        decrypt(Path(t) / "render.mp4.age", out, key_file, age)
    if not keep:
        cleanup(repo, rid, run["databaseId"], purge_logs, gh)
    print(f"{out}")
    return out


def demo():
    import hashlib
    # the workflow's age pin is this file's linux pin; the workflow never echoes the payload or a name
    sh = (REPO_ROOT / ".github" / "scripts" / "install-age.sh").read_text(encoding="utf-8")
    assert f"AGE_VERSION={AGE_VERSION}" in sh and f"AGE_SHA256={AGE_PINS[('Linux', 'x86_64')][1]}" in sh
    wf = (REPO_ROOT / ".github" / "workflows" / WORKFLOW).read_text(encoding="utf-8")
    assert "run-name: render ${{ inputs.render_id }}" in wf and "--draft" not in wf
    assert "cat work/plan.json" not in wf and "echo \"$RENDER_KEY" not in wf and "set -x" not in wf
    assert wf.count("retention-days: 1") == 2 and "secrets.RENDER_KEY" in wf and "vars.RENDER_RECIPIENT" in wf
    scripts = run_scripts(wf)   # inputs and secrets reach a shell only through env:, never pasted into a script
    assert len(scripts) >= 8 and not any("${{" in s for s in scripts), [s for s in scripts if "${{" in s]
    assert run_scripts("steps:\n  - run: |\n      echo ${{ inputs.x }}\n  - uses: a\n")[0].strip() == "echo ${{ inputs.x }}"
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        # split: parts under the cap, cat back to the same bytes, exact multiples too
        for n, size in ((2560, 1000), (3000, 1000), (10, 1000), (0, 1000)):
            f = t / "payload.age"
            body = bytes(range(256)) * (n // 256) + bytes(n % 256)
            f.write_bytes(body)
            parts = split(f, size)
            assert b"".join(p.read_bytes() for p in parts) == body and all(p.stat().st_size <= size for p in parts), (n, parts)
            assert [p.name for p in parts][0] == "payload.part-00" and not f.exists()
            for p in parts:
                p.unlink()
        # a fake gh: records calls, lists two runs (another render's first), knows the artifacts
        calls = []

        def fake_gh(*args, check=True, input=None):
            calls.append(args)
            out = ""
            if args[:2] == ("run", "list"):
                out = json.dumps([{"databaseId": 7, "displayTitle": "render 000000000000", "url": "u7", "status": "completed"},
                                  {"databaseId": 8, "displayTitle": f"render {RID}", "url": "u8", "status": "completed"}])
            elif args[:1] == ("api",) and "-X" not in args:
                out = json.dumps({"artifacts": [{"id": 31, "name": f"render-{RID}"}]})
            elif args[:2] == ("run", "download"):
                d = Path(args[args.index("-D") + 1])
                shutil.copyfile(t / "enc.age", d / "render.mp4.age")
            return subprocess.CompletedProcess(args, 0, out, "")

        RID = "abcdef123456"
        assert find_run("me/r", RID, fake_gh, tries=1)["databaseId"] == 8, "found another render's run"
        assert find_run("me/r", "ffffffffffff", fake_gh, tries=1) is None
        cleanup("me/r", RID, 8, purge_logs=True, gh=fake_gh)
        assert ("release", "delete", f"render-{RID}", "-y", "--cleanup-tag", "-R", "me/r") in calls
        assert ("api", "-X", "DELETE", "repos/me/r/actions/artifacts/31") in calls and ("run", "delete", "8", "-R", "me/r") in calls
        assert not any(c[:2] == ("repo", "delete") for c in calls), "never the repo"
        age, keygen = age_bin(), age_bin("age-keygen")
        if age and keygen:   # real encryption: pack, decrypt, untar, the same files; fetch decrypts the download
            key = t / "key.txt"
            subprocess.run([keygen, "-o", str(key)], check=True, capture_output=True)
            rcpt = recipient(key, keygen)
            assert rcpt.startswith("age1"), rcpt
            (t / "b" / "public").mkdir(parents=True)
            (t / "b" / "bundle.js").write_text("x", encoding="utf-8")
            (t / "b" / "public" / "cut.mp4").write_bytes(os.urandom(5000))
            (t / "plan.json").write_text('{"durationInFrames": 30, "fps": 30}', encoding="utf-8")
            parts = pack(t / "b", t / "plan.json", {"render_id": RID}, t / "up", rcpt, age)
            enc = b"".join(p.read_bytes() for p in parts)
            assert b"cut.mp4" not in enc and b"durationInFrames" not in enc, "the payload leaked a name in clear"
            (t / "joined.age").write_bytes(enc)
            decrypt(t / "joined.age", t / "payload.tar", key, age)
            with tarfile.open(t / "payload.tar") as tar:
                names = set(tar.getnames())
                assert {"bundle/bundle.js", "bundle/public/cut.mp4", "plan.json", "meta.json"} <= names, names
                assert json.load(tar.extractfile("meta.json"))["render_id"] == RID
            # submit with the fake gh: a draft release named only by the rid, then the dispatch with the inputs
            calls.clear()
            edit = t / "edit"
            edit.mkdir()
            job = submit(edit, t / "plan.json", t / "b", "", "shorts", "me/r", fake_gh, age, keygen, key)
            rel = next(c for c in calls if c[:2] == ("release", "create"))
            assert RID_RE.match(job["render_id"]) and rel[2] == f"render-{job['render_id']}" and "--draft" in rel
            assert all(Path(a).name.startswith("payload.part-") for a in rel[3:rel.index("--draft")]), rel
            run = next(c for c in calls if c[:2] == ("workflow", "run"))
            assert f"render_id={job['render_id']}" in run and "frames=30" in run and "fps=30" in run and "format=shorts" in run
            assert "audio_rate=48000" in run and "audio_bitrate=320k" in run, run   # from formats.py, shorts' export audio
            assert audio_for("") == ("48000", "320k") and audio_for("no-such-format") == ("48000", "320k")
            assert json.loads((edit / "github.json").read_text(encoding="utf-8"))["release"] == f"render-{job['render_id']}"
            # fetch: the run named after this render, decrypted locally, the release and artifacts deleted
            RID = job["render_id"]
            subprocess.run([age, "-r", rcpt, "-o", str(t / "enc.age"), str(t / "b" / "public" / "cut.mp4")], check=True)
            calls.clear()
            out = fetch(edit, "", fake_gh, age, key, watch=False)
            assert out.read_bytes() == (t / "b" / "public" / "cut.mp4").read_bytes()
            assert ("release", "delete", f"render-{RID}", "-y", "--cleanup-tag", "-R", "me/r") in calls
            print(f"demo ok (real age {AGE_VERSION} round trip)")
        else:
            print("demo ok (age not installed: the encryption round trip was skipped)")
    assert hashlib.sha256(b"").hexdigest()


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        print(__doc__)
        sys.exit(2)
