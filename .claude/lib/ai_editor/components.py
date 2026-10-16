#!/usr/bin/env python3
"""The motion-graphics component library: one manifest per component, read by plan.py, the renderer's registry
(remotion/scripts/gen-registry.mjs) and the app's gallery (/api/components). Stdlib only.

Built-ins live in .claude/components/<id>/component.json and point at the renderer's own code ("builtin:Shot").
A user's own components live in <library>/components/<id>/ with a component.json and an index.tsx whose default
export is a React.FC<TP> (src/component-api.ts); gen-registry.mjs copies them into the render bundle.

    python3 components.py list              id, kind and name of every component (built-in, then the user's)
    python3 components.py show <id>         its manifest
    python3 components.py check [<dir>]     validate every manifest (or the ones under <dir>), exit 1 on a problem
    python3 components.py props <id> <json> validate props against the component's schema
    python3 components.py demo              self-check: the derived tuples equal plan.py's old literals

Manifest keys: id, name, description, kind (overlay | template | scene | alias | image-format), entry
("builtin:<Export>", "alias:<id>" or "./index.tsx"), order (sort key, keeps plan.py's tuple order), aspects,
defaultDurationS, entrance (null: the plan's own), floating, moving, contentAspect (width / height or null),
fixedBox, boxOk, imageFormat, legacy, scene, splitFirst, wantsPicture, tags, preview, propsSchema (JSON Schema
2020-12), example (props for the gallery still), aliasOf.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILTIN = HERE.parents[1] / "components"          # .claude/components
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,40}$")
KINDS = ("overlay", "template", "scene", "alias", "image-format")
ENTRANCES = ("pop", "slide", "fade", "scale")
BOOLS = ("floating", "moving", "fixedBox", "boxOk", "imageFormat", "legacy", "scene", "splitFirst", "wantsPicture")


def user_dir():
    """<library>/components, or None when the library cannot be found."""
    try:
        sys.path.insert(0, str(HERE.parent))
        from ai_editor import library
        return library.path(make=False) / "components"
    except Exception:
        return None


def _read(d, source):
    f = d / "component.json"
    try:
        m = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, [f"{f}: unreadable ({e})"]
    m["_source"], m["_dir"] = source, str(d)
    return m, check_manifest(m, d)


def load_all(dirs=None, user=True):
    """{id: manifest} sorted by order: the built-ins, then each user folder's (a user id never replaces a built-in).
    Broken manifests are left out; problems() lists them."""
    out, seen = {}, set()
    roots = [(BUILTIN, "builtin")] + ([(Path(d), "user") for d in dirs] if dirs is not None
                                      else [(user_dir(), "user")] if user else [])
    for root, source in roots:
        if not root or not Path(root).is_dir():
            continue
        for d in sorted(p for p in Path(root).iterdir() if (p / "component.json").is_file()):
            m, errs = _read(d, source)
            if m is None or errs or m["id"] in seen:
                continue
            seen.add(m["id"])
            out[m["id"]] = m
    return dict(sorted(out.items(), key=lambda kv: (kv[1]["_source"] != "builtin", kv[1].get("order", 1000), kv[0])))


def problems(dirs=None):
    errs = []
    for root in [BUILTIN] + [Path(d) for d in (dirs if dirs is not None else [user_dir()]) if d]:
        if root.is_dir():
            for d in sorted(p for p in root.iterdir() if p.is_dir()):
                errs += _read(d, "builtin" if root == BUILTIN else "user")[1]
    return errs


def check_manifest(m, d=None):
    """Problems with one manifest, as strings ([] when it is fine)."""
    where = f"{d}/component.json" if d else m.get("id", "?")
    errs = []
    if not isinstance(m.get("id"), str) or not ID_RE.match(m["id"]):
        errs.append(f"{where}: id must match {ID_RE.pattern}")
    if d is not None and m.get("id") != Path(d).name:
        errs.append(f"{where}: id {m.get('id')!r} differs from its folder name")
    if m.get("kind") not in KINDS:
        errs.append(f"{where}: kind must be one of {KINDS}")
    entry = m.get("entry") or ""
    if not (entry.startswith(("builtin:", "alias:")) or entry.endswith((".tsx", ".ts"))):
        errs.append(f"{where}: entry must be builtin:<Export>, alias:<id> or a .tsx file")
    if entry.endswith((".tsx", ".ts")) and d is not None and not (Path(d) / entry).is_file():
        errs.append(f"{where}: entry {entry} not found")
    if m.get("entrance") is not None and m["entrance"] not in ENTRANCES:
        errs.append(f"{where}: entrance must be one of {ENTRANCES} or null")
    for k in BOOLS:
        if not isinstance(m.get(k, False), bool):
            errs.append(f"{where}: {k} must be true or false")
    if m.get("contentAspect") is not None and not isinstance(m["contentAspect"], (int, float)):
        errs.append(f"{where}: contentAspect must be a number or null")
    if not isinstance(m.get("defaultDurationS", 2.5), (int, float)) or m.get("defaultDurationS", 2.5) <= 0:
        errs.append(f"{where}: defaultDurationS must be a positive number")
    if not set(m.get("aspects") or []) <= {"9:16", "16:9"}:
        errs.append(f"{where}: aspects lists the layout shapes it works in: 9:16 and/or 16:9")
    ps = m.get("propsSchema")
    if not isinstance(ps, dict) or ps.get("type") != "object":
        errs.append(f"{where}: propsSchema must be a JSON Schema of type object")
    elif "example" in m:
        errs += [f"{where}: example: {e}" for e in validate(m["example"], ps)]
    return errs


_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "object": dict, "array": list,
          "null": type(None)}


def _is(v, t):
    if t in ("number", "integer") and isinstance(v, bool):
        return False
    return isinstance(v, _TYPES.get(t, object))


def validate(value, schema, path="props"):
    """The subset of JSON Schema 2020-12 the manifests use: type (or a list), enum, properties, required,
    additionalProperties (bool), items, minItems, maxItems. Returns a list of problems."""
    errs = []
    t = schema.get("type")
    if t is not None and not any(_is(value, x) for x in ([t] if isinstance(t, str) else t)):
        return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        errs += [f"{path}.{k}: required" for k in schema.get("required") or [] if k not in value]
        for k, v in value.items():
            if k in props:
                errs += validate(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}.{k}: not allowed")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: at most {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for i, v in enumerate(value):
                errs += validate(v, schema["items"], f"{path}[{i}]")
    return errs


def validate_props(cid, props, comps=None):
    comps = comps if comps is not None else load_all()
    if cid not in comps:
        return [f"unknown component {cid!r}"]
    return validate(props, comps[cid]["propsSchema"])


def tuples(comps=None):
    """What plan.py used to spell out by hand, derived from the manifests, in the old order."""
    comps = load_all() if comps is None else comps
    ms = list(comps.values())
    ids = lambda pred: tuple(m["id"] for m in ms if pred(m))
    return {
        "TEMPLATES": ids(lambda m: m["kind"] in ("template", "scene")),
        "OVERLAYS": ids(lambda m: m["kind"] == "overlay"),
        "MOVING": ids(lambda m: m.get("moving")),
        "FORMATS": ids(lambda m: m.get("imageFormat")),
        "FIXED_BOX": ids(lambda m: m.get("fixedBox")),
        "BOX_OK": ids(lambda m: m.get("boxOk")),
        "LEGACY": ids(lambda m: m.get("legacy")),
        "SCENES": ids(lambda m: m.get("scene")),
        "SPLIT_FIRST": ids(lambda m: m.get("splitFirst")),
        "FLOATING": ids(lambda m: m.get("floating")),
        "ASPECT": {m["id"]: m["contentAspect"] for m in ms if m.get("contentAspect") is not None},
        "FORMAT_ENTRANCE": {m["id"]: m["entrance"] for m in ms if m.get("entrance")},
        "DURATION": {m["id"]: m.get("defaultDurationS", 2.5) for m in ms},
    }


def catalog(comps=None, preview_url=None):
    """The app's gallery rows (/api/components)."""
    comps = load_all() if comps is None else comps
    keep = ("id", "name", "description", "kind", "aspects", "defaultDurationS", "entrance", "propsSchema", "tags", "example")
    return [{**{k: m.get(k) for k in keep}, "source": m["_source"],
             "preview": preview_url(m) if preview_url else m.get("preview")}
            for m in comps.values() if m["kind"] != "alias"]


def manifest_hash(m):
    import hashlib
    body = {k: v for k, v in m.items() if not k.startswith("_")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


# plan.py's hand-written tuples before they came from the manifests (2026-10-17): the demo holds the derived ones to them.
OLD = {
    "TEMPLATES": ("flow", "logo_sting", "social_post", "arrow_callout", "icon_burst", "caption_page"),
    "OVERLAYS": ("shot", "browser", "sticker", "chat", "terminal", "toasts", "logo_cluster", "side_by_side", "video_card",
                 "likes", "progress", "curve", "notes"),
    "MOVING": ("chat", "terminal", "toasts", "logo_cluster", "side_by_side", "video_card", "likes", "progress", "curve", "notes", "flow"),
    "FORMATS": ("shot", "browser", "sticker", "plain"),
    "FIXED_BOX": ("logo", "logo_sting", "arrow_callout", "caption_page"),
    "BOX_OK": ("logo", "logo_sting", "arrow_callout", "caption_page"),
    "LEGACY": ("logo", "flow"),
    "SCENES": ("flow",),
    "SPLIT_FIRST": ("icon_burst",),
    "ASPECT": {"browser": 1.45, "chat": 1.9, "terminal": 1.8, "toasts": 3.2, "social_post": 2.2, "side_by_side": 2.6,
               "video_card": 16 / 9, "flow": 2.4, "icon_burst": 1.6, "likes": 2.6, "progress": 2.2, "curve": 2.0, "notes": 2.2},
    "FORMAT_ENTRANCE": {"shot": "scale", "browser": "slide", "sticker": "pop", "plain": "scale", "social_post": "slide", "chat": "slide",
                        "terminal": "fade", "toasts": "slide", "logo_cluster": "pop", "side_by_side": "slide", "video_card": "scale",
                        "logo": "pop", "logo_sting": "pop", "likes": "pop", "progress": "scale", "curve": "scale", "notes": "slide"},
}
# Templates.tsx FLOATING + every overlay + social_post (Anims.tsx)
OLD_FLOATING = {"arrow_callout", "caption_page", "flow", "social_post"} | set(OLD["OVERLAYS"])


def demo():
    import tempfile
    assert problems(dirs=[]) == [], problems(dirs=[])
    b = load_all(dirs=[])
    t = tuples(b)
    for k, v in OLD.items():
        assert t[k] == v, (k, t[k], v)
    assert set(t["FLOATING"]) == OLD_FLOATING, set(t["FLOATING"]) ^ OLD_FLOATING
    assert all(m["entry"].startswith(("builtin:", "alias:")) for m in b.values())
    # a user component: found after the built-ins, its props checked against its schema, never replacing a built-in
    fixture = HERE.parents[2] / "tests" / "fixtures" / "components"
    with tempfile.TemporaryDirectory() as d:
        u = Path(d)
        (u / "shot").mkdir()
        (u / "shot" / "component.json").write_text(json.dumps({**b["shot"], "name": "Mine"}, default=str), encoding="utf-8")
        (u / "bad").mkdir()
        (u / "bad" / "component.json").write_text(json.dumps({"id": "bad", "kind": "nope"}), encoding="utf-8")
        both = load_all(dirs=[u, fixture])
        assert both["shot"]["name"] == "Screenshot" and "bad" not in both, "a user id never replaces a built-in"
        assert any("kind must be one of" in e for e in problems(dirs=[u]))
        if fixture.is_dir():
            ids = [m["id"] for m in both.values() if m["_source"] == "user"]
            assert ids == ["quote_badge"], ids
            q = both["quote_badge"]
            assert validate_props("quote_badge", {"text": "Ship it", "tone": "accent"}, both) == []
            assert validate_props("quote_badge", {"tone": "loud"}, both) == ["props.text: required",
                                                                            "props.tone: 'loud' is not one of ['ink', 'accent']"]
            assert "quote_badge" in tuples(both)["OVERLAYS"] and list(both)[-1] == "quote_badge", "user components sort last"
            assert {r["id"] for r in catalog(both)} >= {"quote_badge", "shot"} and "logo" not in {r["id"] for r in catalog(both)}
            assert len(manifest_hash(q)) == 16
    assert validate([1, "x"], {"type": "array", "items": {"type": "number"}}) == ["props[1]: expected number, got str"]
    assert validate(True, {"type": "number"}) == ["props: expected number, got bool"]
    print("demo ok")


def main():
    a = sys.argv[1:]
    if a[:1] == ["demo"]:
        return demo()
    if a[:1] == ["list"]:
        for m in load_all().values():
            print(f"{m['id']:<14} {m['kind']:<13} {m['_source']:<8} {m['name']}")
        return
    if a[:1] == ["show"] and len(a) == 2:
        m = load_all().get(a[1])
        if not m:
            sys.exit(f"no component {a[1]!r}")
        return print(json.dumps({k: v for k, v in m.items() if not k.startswith("_")}, indent=2))
    if a[:1] == ["check"]:
        errs = problems(dirs=[a[1]] if len(a) > 1 else None)
        for e in errs:
            print(f"FAIL {e}")
        print("ok" if not errs else f"{len(errs)} problem(s)")
        sys.exit(1 if errs else 0)
    if a[:1] == ["props"] and len(a) == 3:
        errs = validate_props(a[1], json.loads(a[2]))
        print("\n".join(errs) or "ok")
        sys.exit(1 if errs else 0)
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
