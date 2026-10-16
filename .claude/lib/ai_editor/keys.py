"""One key store for every skill.

    from ai_editor import keys
    key, where = keys.get("elevenlabs")        # (None, None) when there is none
    keys.save("elevenlabs", "sk_...")          # keeps the other keys in the file
    ok, msg = keys.verify("elevenlabs", key)   # one free request

The file is ~/.config/creator-teardown/.env (KEY=value lines, chmod 600), the same one
creator-teardown's `fetch.py setkey` writes, so a key saved by either plugin works in both.
With AI_EDITOR_HOME set, the file is $AI_EDITOR_HOME/.env instead and the shared one is never
read or written, so an isolated test run never finds or spends real keys.
An environment variable of the same name wins over the file. A .env in the working folder is never
read: it belongs to whatever project Claude Code started in. Lines for other keys (creator-teardown's,
or an old TYPESAFE_API_KEY) are kept as they are and never read here.
"""
import contextlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from ai_editor import net
except ImportError:   # run as a script from this folder
    import net

KEY_FILE = Path.home() / ".config" / "creator-teardown" / ".env"


def key_file():
    """$AI_EDITOR_HOME/.env when AI_EDITOR_HOME is set, else the shared KEY_FILE."""
    home = os.environ.get("AI_EDITOR_HOME", "").strip()
    return Path(home) / ".env" if home else KEY_FILE
VARS = {"elevenlabs": "ELEVENLABS_API_KEY", "higgsfield": "HIGGSFIELD_API_KEY"}
NAMES = {"elevenlabs": "ElevenLabs", "higgsfield": "Higgsfield"}
# Higgsfield keys are "<key id>:<key secret>" from console.higgsfield.ai (one string, saved together).


def get(name):
    """(key, where it came from) or (None, None). `name` is elevenlabs or higgsfield.
    Never a .env in the working folder: that is another project's, and its key would be billed."""
    var, p = VARS[name], key_file()
    if os.environ.get(var, "").strip():
        return os.environ[var].strip(), f"the {var} variable"
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    for line in lines:
        if line.startswith(f"{var}="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if key:
                return key, str(p)
    return None, None


def write_private(path, text):
    """Write a secrets file readable by this user only: a 0600 temp file beside it, then os.replace, so a
    reader never sees it half written and the file is never readable by others, not even for a moment."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


try:   # one writer at a time: a lock file beside the key file (fslock.py, shared with project_store.py)
    from fslock import locked as _locked
except ImportError:
    from ai_editor.fslock import locked as _locked


def _rewrite(name, key, path):
    """Drop VAR= from the file and add VAR=key (None: only drop), keeping every other line, under the lock."""
    var, path = VARS[name], Path(path or key_file())
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        keep = [ln for ln in (path.read_text(encoding="utf-8").splitlines() if path.exists() else [])
                if ln.strip() and not ln.startswith(f"{var}=")]
        lines = keep + ([f"{var}={key}"] if key is not None else [])
        return write_private(path, "\n".join(lines) + "\n" if lines else "")


def save(name, key, path=None):
    """Write VAR=key, keeping every other line. Readable by this user only."""
    return _rewrite(name, key, path)


def remove(name, path=None):
    """Delete VAR= from the key file, keeping every other line. The file is shared with creator-teardown."""
    return _rewrite(name, None, path)


def _get(url, headers):
    req = urllib.request.Request(url, headers={"User-Agent": "ai-video-editor", **headers})
    try:
        with net.urlopen(req, 20) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, net.friendly(e)


HIGGSFIELD_PROBE = "https://api.higgsfield.ai/requests/00000000-0000-0000-0000-000000000000/status"


def verify(name, key):
    """(ok, message). The check is a free account call: nothing is billed."""
    if name == "higgsfield":
        # The status of a request that cannot exist: 404 proves the key was accepted, 401 that it was not.
        if ":" not in key:
            return False, "a Higgsfield key is the key id and the secret joined by a colon (id:secret)"
        code, body = _get(os.environ.get("AI_EDITOR_HIGGSFIELD_PROBE", HIGGSFIELD_PROBE), {"Authorization": f"Key {key}"})
        if code in (200, 404):
            return True, "key works"
        if code == 0:
            return False, body if body == net.FIX else f"no connection ({body[:80]})"
        if code in (401, 403):
            return False, "Higgsfield rejected this key. Copy the id and secret again from console.higgsfield.ai."
        return False, f"HTTP {code}: {body[:120]}"
    code, body = _get("https://api.elevenlabs.io/v1/user", {"xi-api-key": key})
    # A key restricted to Speech to Text (what setup asks for) may not read /v1/user.
    # That refusal still proves the key exists.
    if code == 401 and "missing_permissions" in body:
        code = 200
    if code == 200:
        return True, "key works"
    if code == 0:
        return False, body if body == net.FIX else f"no connection ({body[:80]})"
    if code in (401, 403) or (code == 400 and "key" in body.lower()):
        return False, "the service rejected this key. Copy it again, or make a new one."
    return False, f"HTTP {code}: {body[:120]}"


if __name__ == "__main__":   # self-check: saving one key keeps the others
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / ".env"
        f.write_text(f"TYPESAFE_API_KEY={'t' * 24}\n", encoding="utf-8")  # a key no longer used
        save("elevenlabs", "a" * 24, f)
        save("elevenlabs", "c" * 24, f)
        assert f.read_text(encoding="utf-8") == (f"TYPESAFE_API_KEY={'t' * 24}\n"
                                                 f"ELEVENLABS_API_KEY={'c' * 24}\n")   # the old line is kept, never read
        assert os.name == "nt" or f.stat().st_mode & 0o777 == 0o600
        # AI_EDITOR_HOME isolates: its .env is read first, the shared file never
        os.environ["AI_EDITOR_HOME"] = d
        os.environ.pop("ELEVENLABS_API_KEY", None)
        assert key_file() == f and get("elevenlabs") == ("c" * 24, str(f))
        assert save("elevenlabs", "d" * 24) == f
        f.unlink()
        # many threads saving different keys at once: every key survives, no temp or lock file is left
        names = sorted(VARS) * 10   # whichever keys this plugin has
        ts = [threading.Thread(target=save, args=(n, n[0] * 24 + str(i), f)) for i, n in enumerate(names)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        got = dict(ln.split("=", 1) for ln in f.read_text(encoding="utf-8").splitlines())
        assert set(got) == set(VARS.values()), got
        assert sorted(x.name for x in Path(d).iterdir()) == [".env"], list(Path(d).iterdir())
        f.write_text(f.read_text(encoding="utf-8") + f"TYPESAFE_API_KEY={'t' * 24}\n", encoding="utf-8")
        remove("elevenlabs", f)
        assert "ELEVENLABS_API_KEY" not in f.read_text(encoding="utf-8") and "TYPESAFE_API_KEY" in f.read_text(encoding="utf-8")
        assert os.name == "nt" or f.stat().st_mode & 0o777 == 0o600
        f.unlink()
        # a key restricted to Speech to Text cannot read /v1/user: that refusal still proves it works
        real_get, sent = _get, []
        globals()["_get"] = lambda *a: sent.append(a) or (401, '{"detail":{"status":"missing_permissions"}}')
        try:
            assert verify("elevenlabs", "x" * 32)[0] and len(sent) == 1
        finally:
            globals()["_get"] = real_get
        # Higgsfield: id:secret in one string; a 404 on a request that cannot exist proves the key, 401 refuses it
        real_get, sent = _get, []
        try:
            globals()["_get"] = lambda url, h: sent.append(h) or (404, '{"detail":"not found"}')
            assert verify("higgsfield", "kid:" + "s" * 24) == (True, "key works") and sent[-1] == {"Authorization": "Key kid:" + "s" * 24}
            assert not verify("higgsfield", "nocolon" * 4)[0] and len(sent) == 1, "no request without id:secret"
            globals()["_get"] = lambda url, h: (401, '{"detail":"bad"}')
            assert not verify("higgsfield", "kid:secret")[0]
        finally:
            globals()["_get"] = real_get
        save("higgsfield", "kid:" + "s" * 24, f)
        os.environ.pop("HIGGSFIELD_API_KEY", None)
        assert get("higgsfield") == ("kid:" + "s" * 24, str(f))
        remove("higgsfield", f)
        cwd = os.getcwd()
        work = Path(d) / "another-project"
        work.mkdir()
        (work / ".env").write_text(f"ELEVENLABS_API_KEY={'e' * 24}\n", encoding="utf-8")
        os.chdir(work)   # the folder Claude Code started in: its .env is another project's, never read
        try:
            os.environ.pop("ELEVENLABS_API_KEY", None)
            assert get("elevenlabs") == (None, None), "read a key from the working folder's .env"
        finally:
            os.chdir(cwd)
        # a new key file is 0600 from its first byte: with chmod doing nothing, the mode is still 0600
        if os.name != "nt":
            real, old_mask = os.chmod, os.umask(0)
            os.chmod = lambda *a, **k: None
            try:
                g = save("elevenlabs", "f" * 24, Path(d) / "new" / ".env")
            finally:
                os.chmod, _ = real, os.umask(old_mask)
            assert g.stat().st_mode & 0o777 == 0o600, oct(g.stat().st_mode)
    print("keys ok")
