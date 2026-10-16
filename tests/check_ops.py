#!/usr/bin/env python3
"""project_store.apply_op against tests/fixtures/ops-cases.json, the cases the app's ops.ts must also pass
(tests/test_ops.mjs): the app's optimistic edits and the server's never disagree.

    python3 tests/check_ops.py
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "lib" / "ai_editor"))
import project_schema as ps  # noqa: E402
import project_store as st  # noqa: E402


def main():
    fx = json.loads((ROOT / "tests" / "fixtures" / "ops-cases.json").read_text(encoding="utf-8"))
    bad = []
    for c in fx["cases"]:
        doc = copy.deepcopy(fx["base"])
        try:
            for op in c["ops"]:
                st.apply_op(doc, op, c["author"])
            doc["durationInFrames"] = ps.derive_duration(doc)
            got = {"doc": doc}
        except st.Conflict:
            got = {"error": "conflict"}
        except st.BadBatch:
            got = {"error": "bad"}
        if got != c["expect"]:
            bad.append(c["name"])
    for n in bad:
        print(f"FAIL {n}")
    print(f"{len(fx['cases']) - len(bad)}/{len(fx['cases'])} ops cases ok" if not bad else f"{len(bad)} ops case(s) differ")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
