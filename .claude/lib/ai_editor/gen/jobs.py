"""The generation queue of one edit, and the spend ledger. Stdlib only.

    edits/<name>/generated/jobs.json
      {"estimates": {"est_x": {"model", "body", "usd", "credits", "at", "uploads": [...], "confirmed_at"?, "job"?}},
       "jobs": {"gen_x": {"estimate", "model", "request_id", "status", "outputs", "files", "error",
                          "created", "updated", "polls", "next_poll", "added"?}}}
    $AI_EDITOR_HOME/gen-spend.json   {"YYYY-MM": usd submitted that month}, checked against profile.json gen_budget_usd

An estimate is good for ESTIMATE_TTL_S; submitting needs its id, so nothing is spent on a price the user never saw.
Polling backs off from POLL_FIRST_S to POLL_MAX_S. Writes go through a lock file and an atomic replace.
"""
import contextlib
import json
import os
import secrets
import time
from pathlib import Path

ESTIMATE_TTL_S = 30 * 60
POLL_FIRST_S, POLL_MAX_S = 5, 60


def home():
    return Path(os.environ.get("AI_EDITOR_HOME", Path.home() / ".ai-video-editor"))


def new_id(prefix):
    return f"{prefix}_{secrets.token_hex(4)}"


@contextlib.contextmanager
def locked(path):
    try:
        from ai_editor.fslock import locked as lk   # the shared lock, when the project store brought it
    except ImportError:
        from ai_editor.keys import _locked as lk
    with lk(path):
        yield


def _load(f, empty):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty


def _save(f, data):
    f = Path(f)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".{f.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def jobs_file(edit):
    return Path(edit) / "generated" / "jobs.json"


def read(edit):
    return _load(jobs_file(edit), {"estimates": {}, "jobs": {}})


def update(edit, fn):
    """fn(doc) changes the queue in place under the lock; returns what fn returns."""
    f = jobs_file(edit)
    f.parent.mkdir(parents=True, exist_ok=True)
    with locked(f):
        doc = read(edit)
        out = fn(doc)
        _save(f, doc)
    return out


# -- money ---------------------------------------------------------------------------------------------
def budget():
    """profile.json gen_budget_usd (a monthly cap), or None for no cap."""
    b = _load(home() / "profile.json", {}).get("gen_budget_usd")
    return float(b) if b not in (None, "") else None


def spent(month=None):
    return float(_load(home() / "gen-spend.json", {}).get(month or time.strftime("%Y-%m"), 0))


def check_budget(usd):
    """None when usd fits the month's cap, else the reason it does not."""
    cap = budget()
    if cap is None:
        return None
    left = cap - spent()
    return None if usd <= left + 1e-9 else (f"${usd:.2f} is over this month's generation budget: ${left:.2f} of "
                                            f"${cap:.2f} left (profile.json gen_budget_usd)")


def record_spend(usd):
    f = home() / "gen-spend.json"
    with locked(f):
        d = _load(f, {})
        m = time.strftime("%Y-%m")
        d[m] = round(float(d.get(m, 0)) + usd, 4)
        _save(f, d)


# -- estimates and jobs ---------------------------------------------------------------------------------
def add_estimate(edit, model, body, est, uploads=()):
    eid = new_id("est")
    update(edit, lambda d: d["estimates"].__setitem__(eid, {
        "model": model, "body": body, "usd": est.usd, "credits": est.credits, "at": time.time(),
        "uploads": list(uploads)}))
    return eid


def usable_estimate(edit, eid):
    """The estimate, or SystemExit saying why it cannot be spent: unknown, used, or stale."""
    e = read(edit)["estimates"].get(eid)
    if not e:
        raise SystemExit(f"No estimate {eid} for this edit. Run gen.py estimate first and ask the user with its price.")
    if e.get("job"):
        raise SystemExit(f"Estimate {eid} was already spent on {e['job']}. Estimate again for another generation.")
    if time.time() - e["at"] > ESTIMATE_TTL_S:
        raise SystemExit(f"Estimate {eid} is over {ESTIMATE_TTL_S // 60} minutes old. Estimate again and re-ask.")
    return e


def add_job(edit, eid, model, sub):
    jid = new_id("gen")
    now = time.time()

    def fn(d):
        d["estimates"][eid].update(job=jid, confirmed_at=now)
        d["jobs"][jid] = {"estimate": eid, "model": model, "request_id": sub["request_id"],
                          "status": sub.get("status", "queued"), "outputs": [], "files": [], "error": None,
                          "created": now, "updated": now, "polls": 0, "next_poll": now + POLL_FIRST_S}
    update(edit, fn)
    return jid


def poll_delay(polls):
    return min(POLL_MAX_S, POLL_FIRST_S * 2 ** min(polls, 6))


def set_status(edit, jid, st):
    now = time.time()

    def fn(d):
        j = d["jobs"][jid]
        j.update(status=st.status, outputs=st.outputs, error=st.error, updated=now, polls=j["polls"] + 1)
        j["next_poll"] = now + poll_delay(j["polls"])
        return j
    return update(edit, fn)


def due(edit, now=None):
    now = now or time.time()
    from ai_editor.gen.base import TERMINAL
    return [jid for jid, j in read(edit)["jobs"].items() if j["status"] not in TERMINAL and j["next_poll"] <= now]
