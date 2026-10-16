#!/usr/bin/env python3
"""The project (edits/NAME/project.json) from the command line: how Claude edits the same timeline the app shows.
Every change goes through project_store (ops, undo, the change log the app watches). Stdlib only.

    python3 project.py init  edits/NAME [--plan plan.json]        project.json from plan.json (refuses if it exists)
    python3 project.py sync  edits/NAME [--plan plan.json]        after plan.py: merge the new plan, keep the user's edits
    python3 project.py apply edits/NAME ops.json [--propose] [--author claude] [--label "..."]
                                                                  ops.json: a batch {"ops": [...]} or a list of ops; - is stdin
    python3 project.py accept edits/NAME <proposal id>           python3 project.py reject edits/NAME <proposal id>
    python3 project.py undo  edits/NAME [--author claude]         python3 project.py redo edits/NAME [--author claude]
    python3 project.py export edits/NAME [--format youtube --format shorts]
                                                                  plan.json (no --format) or plan-<format>.json, for edit.py render
    python3 project.py show  edits/NAME [--json]                  tracks, items and rev at a glance
    python3 project.py demo

Ops and their rules: lib/ai_editor/project_store.py. Shapes: references/contracts.md "project.json".
Exit codes: 0 ok, 1 conflict or bad batch (the message says which), 2 usage.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib" / "ai_editor"))
import project_convert as pc  # noqa: E402
import project_schema as ps  # noqa: E402
import project_store as store  # noqa: E402


def show(doc):
    lines = [f"{doc['name']}  rev {doc['rev']}  {doc['width']}x{doc['height']} @ {doc['fps']} fps  "
             f"{doc['durationInFrames'] / doc['fps']:.1f} s  format {doc.get('format') or '-'}"]
    for t in doc["tracks"]:
        flags = "".join(c for c, k in (("H", "hidden"), ("M", "muted"), ("L", "locked")) if t.get(k))
        mine = sum(1 for it in t["items"] if it["origin"] != "plan" or it.get("pinned"))
        lines.append(f"  {t['role']:<10} {t['id']}  {len(t['items'])} item(s)" + (f", {mine} yours" if mine else "") +
                     (f" [{flags}]" if flags else ""))
        for it in t["items"][:6]:
            what = it.get("component") or it.get("src") or (it.get("props") or {}).get("text") or it.get("asset") or ""
            lines.append(f"      {it['id']}  {it['from'] / doc['fps']:7.2f}s +{it['durationInFrames'] / doc['fps']:.2f}s  {what}"[:110])
        if len(t["items"]) > 6:
            lines.append(f"      ... {len(t['items']) - 6} more")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "sync", "apply", "accept", "reject", "undo", "redo", "export", "show", "demo"])
    ap.add_argument("edit", nargs="?")
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--plan", default="plan.json")
    ap.add_argument("--propose", action="store_true")
    ap.add_argument("--author", default="claude", choices=list(ps.ORIGINS))
    ap.add_argument("--label")
    ap.add_argument("--format", action="append", dest="formats")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "demo":
        return demo()
    if not a.edit:
        ap.error("edits/NAME is needed")
    d = Path(a.edit)
    try:
        if a.cmd == "init":
            if store.path(d).exists():
                sys.exit(f"{store.path(d)} exists; use sync to merge a new plan")
            doc = store.save_new(d, pc.from_plan(json.loads((d / a.plan).read_text(encoding="utf-8")), d.name))
            print(f"project.json rev {doc['rev']}: {sum(len(t['items']) for t in doc['tracks'])} items")
        elif a.cmd == "sync":
            doc = pc.sync(d, a.plan)
            print(f"project.json rev {doc['rev']}: {sum(len(t['items']) for t in doc['tracks'])} items")
        elif a.cmd == "apply":
            src = sys.stdin.read() if a.arg in (None, "-") else Path(a.arg).read_text(encoding="utf-8")
            body = json.loads(src)
            batch = {"ops": body} if isinstance(body, list) else body
            batch.setdefault("author", a.author)
            if a.label:
                batch["label"] = a.label
            if a.propose:
                batch["propose"] = True
            res = store.apply(d, batch)
            print(f"proposal {res['proposal']} (the user accepts or rejects it in the app)" if "proposal" in res
                  else f"rev {res['rev']}")
        elif a.cmd in ("accept", "reject"):
            if not a.arg:
                ap.error("the proposal id is needed")
            print(f"rev {store.accept(d, a.arg)['rev']}" if a.cmd == "accept" else
                  ("rejected" if store.reject(d, a.arg) else "no such proposal"))
        elif a.cmd in ("undo", "redo"):
            doc = (store.undo if a.cmd == "undo" else store.redo)(d, a.author)
            print(f"rev {doc['rev']}" if doc else f"nothing to {a.cmd} for {a.author}")
        elif a.cmd == "export":
            for f in pc.export(d, a.formats or [None]):
                print(f)
        elif a.cmd == "show":
            doc = store.load(d)
            print(json.dumps(doc, indent=1) if a.json else show(doc))
    except (store.Conflict, store.BadBatch) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


def demo():
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "edits" / "v"
        d.mkdir(parents=True)
        (d / "plan.json").write_text(json.dumps(pc.sample_plan()), encoding="utf-8")

        def run(*args, stdin=None):
            buf = io.StringIO()
            old = sys.stdin
            if stdin is not None:
                sys.stdin = io.StringIO(stdin)
            try:
                with contextlib.redirect_stdout(buf):
                    main(list(args))
            finally:
                sys.stdin = old
            return buf.getvalue()
        assert run("init", str(d)).startswith("project.json rev 0")
        card = ps.track(store.load(d), "cards")["items"][0]["id"]
        ops = Path(t) / "ops.json"
        ops.write_text(json.dumps([{"op": "move", "id": card, "from": 450}]), encoding="utf-8")
        assert run("apply", str(d), str(ops)).strip() == "rev 1"
        out = run("apply", str(d), "-", "--propose", stdin=json.dumps({"ops": [{"op": "delete", "id": card}]}))
        pid = out.split()[1]
        assert run("accept", str(d), pid).strip() == "rev 2" and ps.find(store.load(d), card)[2] is None
        assert run("undo", str(d)).strip() == "rev 3" and ps.find(store.load(d), card)[2]["from"] == 450
        assert "nothing to redo" in run("redo", str(d), "--author", "user")
        exp = run("export", str(d)).strip()
        plan = json.loads(Path(exp).read_text(encoding="utf-8"))
        assert Path(exp).name == "plan.json" and plan["cards"][0]["start"] == 15.0, plan["cards"][0]
        assert "cards" in run("show", str(d)) and "1 yours" in run("show", str(d))
        assert run("sync", str(d)).startswith("project.json rev 3"), "its own export: no new rev"
        try:
            run("apply", str(d), "-", stdin=json.dumps([{"op": "move", "id": "itm_missing0", "from": 1}]))
            raise AssertionError("expected exit 1")
        except SystemExit as e:
            assert e.code == 1
    print("demo ok")


if __name__ == "__main__":
    main()
