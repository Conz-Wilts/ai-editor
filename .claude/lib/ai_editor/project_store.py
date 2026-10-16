#!/usr/bin/env python3
"""The project's command layer: every change to project.json is a batch of ops, applied under a file lock,
logged with its inverse, undoable per author. The app (POST /api/commands) and Claude (project.py apply) both
write through here. Stdlib only.

Batch: {"baseRev": 17, "author": "user|claude|plan", "label": "Move launch card", "propose": false, "ops": [OP]}

    {"op": "add", "track": "<id or role>", "item": {...}, "id"?: "itm_new", "index"?: n}
    {"op": "move", "id", "from": frame, "track"?: "<id or role>"}
    {"op": "trim", "id", "edge": "start|end", "to": frame}
    {"op": "split", "id", "at": frame, "newId"?}
    {"op": "delete", "id"}
    {"op": "update", "id", "set": {"props.label": "x", "box.w": 80}, "unset": ["props.old"]}
    {"op": "addTrack", "track": {"role", "name"?, ...}, "index"?}      {"op": "deleteTrack", "id"}
    {"op": "updateTrack", "id", "set": {"muted"?: bool, "hidden"?: bool, "locked"?: bool, "name"?: str}}
    {"op": "setProject", "set": {"format": "youtube", "designSystem": "brand", "name", "formats", "width", "height"}}
    {"op": "addAsset", "asset": {...}, "id"?}                           {"op": "deleteAsset", "id"}
    {"op": "replace", "id", "item", "track", "index"}                    (undo's own: puts an item back as it was)

Rules:
- A batch based on an older rev is rebased when every id it names still exists, else Conflict (HTTP 409).
- The whole batch applies or nothing does; the result must pass project_schema.validate.
- A user or claude edit to a plan item pins it, so plan.py running again never moves it back.
- A locked track refuses user and claude edits to its items; updateTrack still applies, so it can be unlocked.
- project.log.jsonl gets {rev, author, label, ops, inverse, ts, undoOf?, redoOf?, proposal?}; undo applies an
  entry's inverse as a new rev; redo applies the undo's inverse. Each author has their own undo stack.
- "propose": true writes proposals/<id>.json instead; accept applies it, reject deletes it.

    python3 project_store.py demo
"""
import copy
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fslock  # noqa: E402
import project_schema as ps  # noqa: E402

CHANGED = threading.Condition()   # notified after every write in this process (the app's long-poll wakes on it)
PROJECT_KEYS = ("name", "format", "formats", "designSystem", "width", "height")
EDITS = ("move", "trim", "split", "update")
TRACK_KEYS = {"muted": bool, "hidden": bool, "locked": bool, "name": str}   # what updateTrack may set


class Conflict(Exception):
    """409: the batch names an id that is gone, or was based on a rev it cannot be rebased onto."""
    def __init__(self, msg, rev):
        super().__init__(msg)
        self.rev = rev


class BadBatch(Exception):
    """400: an op that does not make sense (unknown op, bad frame, the result fails validation)."""


def path(edit_dir):
    return Path(edit_dir) / "project.json"


def log_path(edit_dir):
    return Path(edit_dir) / "project.log.jsonl"


def load(edit_dir):
    return json.loads(path(edit_dir).read_text(encoding="utf-8"))


def _write(edit_dir, doc):
    f = path(edit_dir)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    for i in range(40):   # Windows: a reader holding the file open refuses the replace for a moment
        try:
            os.replace(tmp, f)
            break
        except PermissionError:
            time.sleep(0.025)
    else:
        raise PermissionError(f"could not replace {f}")


def _log(edit_dir, entry):
    with open(log_path(edit_dir), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _notify():
    with CHANGED:
        CHANGED.notify_all()


def entries(edit_dir):
    try:
        return [json.loads(x) for x in log_path(edit_dir).read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def since(edit_dir, rev):
    """The log entries after rev, without their inverses: what changed, by whom."""
    return [{k: e[k] for k in ("rev", "author", "label", "ops", "ts", "undoOf", "redoOf", "proposal", "sync") if k in e}
            for e in entries(edit_dir) if e["rev"] > rev]


def save_new(edit_dir, doc):
    with fslock.locked(path(edit_dir)):
        doc = copy.deepcopy(doc)
        doc["rev"] = 0
        errs = ps.validate(doc)
        if errs:
            raise BadBatch("; ".join(errs[:5]))
        _write(edit_dir, doc)
        _log(edit_dir, {"rev": 0, "author": "plan", "label": "new project", "ops": [], "ts": time.time(), "sync": True})
    _notify()
    return doc


def replace(edit_dir, fn, author="plan", label="sync"):
    """A whole-document change (a re-plan merged in): a new rev with no inverse, so undo stops here."""
    with fslock.locked(path(edit_dir)):
        old = load(edit_dir)
        doc = fn(copy.deepcopy(old))
        doc["rev"] = old["rev"] + 1
        errs = ps.validate(doc)
        if errs:
            raise BadBatch("; ".join(errs[:5]))
        _write(edit_dir, doc)
        _log(edit_dir, {"rev": doc["rev"], "author": author, "label": label, "ops": [], "ts": time.time(), "sync": True})
    _notify()
    return doc


# ---- ops ------------------------------------------------------------------------------------------------------

def _set_path(obj, dotted, value, unset=False):
    keys = dotted.split(".")
    for k in keys[:-1]:
        nxt = obj.get(k)
        if not isinstance(nxt, dict):
            if unset:
                return
            nxt = obj[k] = {}
        obj = nxt
    if unset:
        obj.pop(keys[-1], None)
    else:
        obj[keys[-1]] = value


def _need(doc, item_id):
    t, i, it = ps.find(doc, item_id)
    if it is None:
        raise Conflict(f"no item {item_id}", doc["rev"])
    return t, i, it


def _guard(t, author):
    if t.get("locked") and author != "plan":
        raise BadBatch(f"track {t['name']} is locked")


def _frame(v, name):
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise BadBatch(f"{name} must be a frame (a non-negative integer)")
    return v


def _restore(t, i, it):
    return {"op": "replace", "id": it["id"], "item": copy.deepcopy(it), "track": t["id"], "index": i}


def apply_op(doc, op, author):
    """Apply one op to doc in place; return the ops that undo it (applied in order)."""
    kind = op.get("op")
    if kind == "add":
        t = ps.track(doc, op.get("track", ""))
        if t is None:
            raise Conflict(f"no track {op.get('track')}", doc["rev"])
        _guard(t, author)
        it = copy.deepcopy(op.get("item") or {})
        it["id"] = op.get("id") or it.get("id") or ps.mint()
        if ps.find(doc, it["id"])[2] is not None:
            raise Conflict(f"{it['id']} already exists", doc["rev"])
        it.setdefault("origin", "plan" if author == "plan" else author)
        it.setdefault("pinned", author != "plan")
        it.setdefault("from", 0)
        idx = op.get("index", len(t["items"]))
        t["items"].insert(idx, it)
        return [{"op": "delete", "id": it["id"]}]
    if kind == "delete":
        t, i, it = _need(doc, op.get("id"))
        _guard(t, author)
        t["items"].pop(i)
        return [{"op": "add", "track": t["id"], "item": copy.deepcopy(it), "index": i}]
    if kind == "replace":
        t0, i0, cur = ps.find(doc, op["id"])
        undo = [_restore(t0, i0, cur)] if cur is not None else [{"op": "delete", "id": op["id"]}]
        if cur is not None:
            t0["items"].pop(i0)
        t = ps.track(doc, op.get("track", ""))
        if t is None:
            raise Conflict(f"no track {op.get('track')}", doc["rev"])
        t["items"].insert(min(op.get("index", len(t["items"])), len(t["items"])), copy.deepcopy(op["item"]))
        return undo
    if kind in EDITS:
        t, i, it = _need(doc, op.get("id"))
        _guard(t, author)
        undo = [_restore(t, i, it)]
        if kind == "move":
            it["from"] = _frame(op.get("from"), "from")
            if op.get("track") not in (None, t["id"], t["role"]):
                dest = ps.track(doc, op["track"])
                if dest is None:
                    raise Conflict(f"no track {op['track']}", doc["rev"])
                _guard(dest, author)
                t["items"].pop(i)
                dest["items"].append(it)
        elif kind == "trim":
            to, end = _frame(op.get("to"), "to"), ps.end(it)
            if op.get("edge") == "start":
                if to >= end:
                    raise BadBatch("trim start past the item's end")
                d = to - it["from"]
                if "trimIn" in it:
                    if it["trimIn"] + d < 0:
                        raise BadBatch("trim start before the clip's first frame")
                    it["trimIn"] += d
                it["from"], it["durationInFrames"] = to, end - to
            elif op.get("edge") == "end":
                if to <= it["from"]:
                    raise BadBatch("trim end before the item's start")
                it["durationInFrames"] = to - it["from"]
            else:
                raise BadBatch("trim edge is start or end")
        elif kind == "split":
            at = _frame(op.get("at"), "at")
            if not it["from"] < at < ps.end(it):
                raise BadBatch("split inside the item")
            right = copy.deepcopy(it)
            right["id"] = op.get("newId") or ps.mint()
            if ps.find(doc, right["id"])[2] is not None:
                raise Conflict(f"{right['id']} already exists", doc["rev"])
            right["from"], right["durationInFrames"] = at, ps.end(it) - at
            if "trimIn" in right:
                right["trimIn"] += at - it["from"]
            right.pop("sec", None)
            if right.get("anchor"):
                right["anchor"] = {**right["anchor"], "t": round(at / doc["fps"], 3)}
            it["durationInFrames"] = at - it["from"]
            t["items"].insert(i + 1, right)
            undo = [{"op": "delete", "id": right["id"]}] + undo
        else:   # update
            for k, v in (op.get("set") or {}).items():
                if k.split(".")[0] in ("id", "type"):
                    raise BadBatch(f"{k} cannot change")
                _set_path(it, k, copy.deepcopy(v))
            for k in op.get("unset") or []:
                _set_path(it, k, None, unset=True)
        if author != "plan" and it.get("origin") == "plan":
            it["pinned"] = True   # the user's (or Claude's) version now: a re-plan leaves it
        return undo
    if kind == "addTrack":
        spec = copy.deepcopy(op.get("track") or {})
        t = {**ps.new_track(spec.get("role", "broll"), spec.get("name")), **spec}
        t.setdefault("items", [])
        t["id"] = spec.get("id") or t["id"]
        if any(x["id"] == t["id"] for x in doc["tracks"]):
            raise Conflict(f"{t['id']} already exists", doc["rev"])
        doc["tracks"].insert(op.get("index", len(doc["tracks"])), t)
        return [{"op": "deleteTrack", "id": t["id"]}]
    if kind == "deleteTrack":
        i = next((n for n, t in enumerate(doc["tracks"]) if t["id"] == op.get("id")), None)
        if i is None:
            raise Conflict(f"no track {op.get('id')}", doc["rev"])
        t = doc["tracks"].pop(i)
        return [{"op": "addTrack", "track": t, "index": i}]
    if kind == "updateTrack":
        t = next((x for x in doc["tracks"] if x["id"] == op.get("id")), None)
        if t is None:
            raise Conflict(f"no track {op.get('id')}", doc["rev"])
        sets = op.get("set") or {}
        if not isinstance(sets, dict) or not sets:
            raise BadBatch("updateTrack needs a set")
        undo_set = {}
        for k, v in sets.items():
            if k not in TRACK_KEYS:
                raise BadBatch(f"updateTrack cannot set {k}")
            if not isinstance(v, TRACK_KEYS[k]) or (k == "name" and not v.strip()):
                raise BadBatch(f"track {k} must be {'a non-empty string' if k == 'name' else 'true or false'}")
            undo_set[k] = t.get(k, False if k != "name" else t.get("name", ""))
            t[k] = v
        return [{"op": "updateTrack", "id": t["id"], "set": undo_set}]
    if kind == "setProject":
        undo_set, undo_unset = {}, []
        for k, v in (op.get("set") or {}).items():
            if k not in PROJECT_KEYS:
                raise BadBatch(f"setProject cannot set {k}")
            if k in doc:
                undo_set[k] = copy.deepcopy(doc[k])
            else:
                undo_unset.append(k)
            doc[k] = copy.deepcopy(v)
        for k in op.get("unset") or []:
            if k in PROJECT_KEYS and k in doc:
                undo_set[k] = doc.pop(k)
        return [{"op": "setProject", "set": undo_set, "unset": undo_unset}]
    if kind == "addAsset":
        aid = op.get("id") or (op.get("asset") or {}).get("id") or ps.mint("ast")
        if aid in doc["assets"]:
            raise Conflict(f"{aid} already exists", doc["rev"])
        doc["assets"][aid] = {k: v for k, v in copy.deepcopy(op.get("asset") or {}).items() if k != "id"}
        return [{"op": "deleteAsset", "id": aid}]
    if kind == "deleteAsset":
        aid = op.get("id")
        if aid not in doc["assets"]:
            raise Conflict(f"no asset {aid}", doc["rev"])
        if any(it.get("asset") == aid for t in doc["tracks"] for it in t["items"]):
            raise BadBatch(f"{aid} is on the timeline")
        return [{"op": "addAsset", "id": aid, "asset": doc["assets"].pop(aid)}]
    raise BadBatch(f"unknown op {kind!r}")


def named(op):
    """The item / track ids an op needs to exist (the rebase check)."""
    k = op.get("op")
    if k in EDITS or k == "delete":
        return [op.get("id")]
    if k == "updateTrack":
        return [op.get("id")]
    return []


def _apply(edit_dir, batch, extra=None):
    """Under the lock: rebase or refuse, apply all ops, validate, write, log. The new doc and its log entry."""
    author = batch.get("author") or "user"
    if author not in ps.ORIGINS:
        raise BadBatch(f"author {author!r}")
    ops = batch.get("ops")
    if not isinstance(ops, list) or not ops:
        raise BadBatch("ops must be a non-empty list")
    with fslock.locked(path(edit_dir)):
        cur = load(edit_dir)
        base = batch.get("baseRev")
        if base is not None and base != cur["rev"]:
            gone = [i for op in ops for i in named(op) if ps.find(cur, i)[2] is None]
            if gone or base > cur["rev"]:
                raise Conflict(f"rev {cur['rev']} (you had {base}); gone: {', '.join(gone) or 'nothing'}", cur["rev"])
        doc = copy.deepcopy(cur)
        inverse = []
        for op in ops:
            inverse = apply_op(doc, op, author) + inverse
        doc["durationInFrames"] = ps.derive_duration(doc)
        errs = ps.validate(doc)
        if errs:
            raise BadBatch("; ".join(errs[:5]))
        doc["rev"] = cur["rev"] + 1
        _write(edit_dir, doc)
        entry = {"rev": doc["rev"], "author": author, "label": batch.get("label") or ops[0]["op"], "ops": ops,
                 "inverse": inverse, "ts": time.time(), **(extra or {})}
        _log(edit_dir, entry)
    _notify()
    return doc, entry


def apply(edit_dir, batch):
    """{"rev", "doc", "proposal"?}. Raises Conflict (409) or BadBatch (400)."""
    if batch.get("propose"):
        return {"proposal": propose(edit_dir, batch), "rev": load(edit_dir)["rev"]}
    doc, _ = _apply(edit_dir, batch)
    return {"rev": doc["rev"], "doc": doc}


def _stacks(edit_dir, author):
    done, redo, by = [], [], {}
    for e in entries(edit_dir):
        by[e["rev"]] = e
        if e.get("author") != author or e.get("sync"):
            continue
        if "undoOf" in e:
            if e["undoOf"] in done:
                done.remove(e["undoOf"])
            redo.append(e["rev"])
        elif "redoOf" in e:
            if e["redoOf"] in redo:
                redo.remove(e["redoOf"])
            done.append(e["rev"])
        else:
            done.append(e["rev"])
            redo.clear()
    return done, redo, by


def undo(edit_dir, author="user"):
    """Undo this author's last change (a new rev). None when there is nothing to undo."""
    done, _, by = _stacks(edit_dir, author)
    if not done:
        return None
    e = by[done[-1]]
    doc, _ = _apply(edit_dir, {"author": author, "label": f"undo {e['label']}", "ops": e["inverse"]}, {"undoOf": e["rev"]})
    return doc


def redo(edit_dir, author="user"):
    _, red, by = _stacks(edit_dir, author)
    if not red:
        return None
    e = by[red[-1]]
    doc, _ = _apply(edit_dir, {"author": author, "label": e["label"].replace("undo ", "redo ", 1), "ops": e["inverse"]},
                    {"redoOf": e["rev"]})
    return doc


# ---- proposals --------------------------------------------------------------------------------------------------

def _pdir(edit_dir):
    return Path(edit_dir) / "proposals"


def propose(edit_dir, batch):
    pid = ps.mint("prp")
    _pdir(edit_dir).mkdir(exist_ok=True)
    body = {"id": pid, "created": time.time(), "batch": {k: v for k, v in batch.items() if k != "propose"}}
    (_pdir(edit_dir) / f"{pid}.json").write_text(json.dumps(body, indent=1), encoding="utf-8")
    _notify()
    return pid


def proposals(edit_dir):
    out = []
    for f in sorted(_pdir(edit_dir).glob("prp_*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return sorted(out, key=lambda p: p["created"])


def accept(edit_dir, pid):
    f = _pdir(edit_dir) / f"{pid}.json"
    if not f.exists():
        raise Conflict(f"no proposal {pid}", load(edit_dir)["rev"])
    p = json.loads(f.read_text(encoding="utf-8"))
    doc, _ = _apply(edit_dir, p["batch"], {"proposal": pid})
    f.unlink()
    return doc


def reject(edit_dir, pid):
    f = _pdir(edit_dir) / f"{pid}.json"
    if not f.exists():
        return False
    f.unlink()
    _notify()
    return True


def demo():
    import project_convert as pc
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        doc = save_new(d, pc.from_plan(pc.sample_plan(), "demo"))
        cards = ps.track(doc, "cards")
        c0, c1 = cards["items"][0]["id"], cards["items"][1]["id"]
        r = apply(d, {"baseRev": 0, "author": "user", "label": "Move notion", "ops": [{"op": "move", "id": c0, "from": 400}]})
        assert r["rev"] == 1 and ps.find(r["doc"], c0)[2]["from"] == 400 and ps.find(r["doc"], c0)[2]["pinned"]
        # stale base, ids still there: rebased onto rev 1
        r = apply(d, {"baseRev": 0, "author": "claude", "ops": [{"op": "update", "id": c1, "set": {"props.app": "Slack", "box.w": 70}}]})
        it = ps.find(r["doc"], c1)[2]
        assert r["rev"] == 2 and it["props"]["app"] == "Slack" and it["box"]["w"] == 70
        # stale base naming a deleted id: 409
        apply(d, {"author": "user", "ops": [{"op": "delete", "id": c0}]})
        try:
            apply(d, {"baseRev": 1, "author": "user", "ops": [{"op": "move", "id": c0, "from": 10}]})
            raise AssertionError("expected a conflict")
        except Conflict as e:
            assert e.rev == 3
        # all or nothing
        try:
            apply(d, {"author": "user", "ops": [{"op": "move", "id": c1, "from": 5}, {"op": "trim", "id": c1, "edge": "end", "to": 1}]})
            raise AssertionError("expected a bad batch")
        except BadBatch:
            pass
        assert ps.find(load(d), c1)[2]["from"] != 5 and load(d)["rev"] == 3
        # undo / redo per author: the user's delete comes back, Claude's update is untouched
        doc = undo(d, "user")
        assert doc["rev"] == 4 and ps.find(doc, c0)[2] is not None and ps.find(doc, c1)[2]["props"]["app"] == "Slack"
        doc = undo(d, "user")
        assert ps.find(doc, c0)[2]["from"] == 372, "the move undone too"
        doc = redo(d, "user")
        assert ps.find(doc, c0)[2]["from"] == 400
        assert undo(d, "claude")["rev"] == 7 and ps.find(load(d), c1)[2]["props"]["app"] == "Jev"
        # split, trim and add on the main track; the length follows the main track
        main = ps.track(load(d), "main")["items"][0]["id"]
        doc = apply(d, {"author": "user", "ops": [{"op": "split", "id": main, "at": 600, "newId": "itm_rightpart"},
                                                  {"op": "trim", "id": "itm_rightpart", "edge": "start", "to": 660}]})["doc"]
        right = ps.find(doc, "itm_rightpart")[2]
        assert right["trimIn"] == 660 and right["from"] == 660 and doc["durationInFrames"] == 1800
        doc = apply(d, {"author": "user", "ops": [{"op": "move", "id": "itm_rightpart", "from": 600}]})["doc"]
        assert doc["durationInFrames"] == 1740
        assert len(ps.track(undo(d, "user"), "main")["items"]) == 2 and len(ps.track(undo(d, "user"), "main")["items"]) == 1
        # proposals: written aside, accepted as one rev
        before = load(d)["rev"]
        res = apply(d, {"author": "claude", "label": "Add a sticker", "propose": True,
                        "ops": [{"op": "add", "track": "cards", "item": {"type": "card", "from": 30, "durationInFrames": 45,
                                                                         "component": "sticker", "props": {"text": "hi"}}}]})
        assert load(d)["rev"] == before and [p["id"] for p in proposals(d)] == [res["proposal"]]
        doc = accept(d, res["proposal"])
        assert doc["rev"] == before + 1 and not proposals(d)
        added = [it for it in ps.track(doc, "cards")["items"] if it.get("component") == "sticker"][0]
        assert added["origin"] == "claude" and since(d, before)[0]["proposal"] == res["proposal"]
        pid = propose(d, {"author": "claude", "ops": [{"op": "delete", "id": added["id"]}]})
        assert reject(d, pid) and not proposals(d)
        # setProject, assets, tracks
        doc = apply(d, {"author": "user", "ops": [{"op": "setProject", "set": {"format": "youtube", "designSystem": "neutral"}},
                                                  {"op": "addAsset", "id": "ast_up1", "asset": {"kind": "image", "src": "images/u.png", "origin": "upload"}},
                                                  {"op": "addTrack", "track": {"role": "broll", "name": "B-roll 2", "id": "trk_b2"}}]})["doc"]
        assert doc["format"] == "youtube" and "ast_up1" in doc["assets"] and ps.track(doc, "trk_b2")["name"] == "B-roll 2"
        doc = undo(d, "user")
        assert doc["format"] is None and "ast_up1" not in doc["assets"] and ps.track(doc, "trk_b2") is None
        # a locked track refuses edits
        lock = ps.track(load(d), "zooms")
        apply(d, {"author": "plan", "ops": [{"op": "update", "id": lock["items"][0]["id"], "set": {"props.scale": 1.2}}]})
        doc = load(d)
        doc["tracks"][[t["role"] for t in doc["tracks"]].index("zooms")]["locked"] = True
        _write(d, doc)
        try:
            apply(d, {"author": "user", "ops": [{"op": "delete", "id": lock["items"][0]["id"]}]})
            raise AssertionError("locked")
        except BadBatch:
            pass
        # updateTrack still applies on a locked track: unlock, edit, undo the unlock
        zid = ps.track(load(d), "zooms")["id"]
        doc = apply(d, {"author": "user", "ops": [{"op": "updateTrack", "id": zid, "set": {"locked": False, "muted": True}}]})["doc"]
        assert ps.track(doc, "zooms")["locked"] is False and ps.track(doc, "zooms")["muted"] is True
        for bad in ({"color": "red"}, {"hidden": "yes"}, {"name": "  "}, {}):
            try:
                apply(d, {"author": "user", "ops": [{"op": "updateTrack", "id": zid, "set": bad}]})
                raise AssertionError(bad)
            except BadBatch:
                pass
        doc = undo(d, "user")
        assert ps.track(doc, "zooms")["locked"] is True and ps.track(doc, "zooms")["muted"] is False
        # two writers at once: no lost revision
        start = load(d)["rev"]
        cap = ps.track(load(d), "captions")["items"][0]["id"]

        def writer(who):
            for n in range(10):
                apply(d, {"author": who, "ops": [{"op": "update", "id": cap, "set": {f"props.{who}{n}": n}}]})
        ts = [threading.Thread(target=writer, args=(w,)) for w in ("user", "claude")]
        [x.start() for x in ts]
        [x.join() for x in ts]
        end = load(d)
        assert end["rev"] == start + 20 and all(f"{w}{n}" in ps.find(end, cap)[2]["props"] for w in ("user", "claude") for n in range(10))
        revs = [e["rev"] for e in entries(d)]
        assert revs == sorted(revs) and len(revs) == len(set(revs))
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        print(__doc__)
        sys.exit(2)
