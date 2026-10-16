#!/usr/bin/env python3
"""Design systems: W3C Design Tokens (DTCG Format Module 2025.10) files compiled to the renderer's Look
(remotion/src/look.tsx). The renderer never parses tokens: plan.json "look" carries the compiled Look. Stdlib only.

Built-ins: .claude/design-systems/<id>/tokens.json, ported from look.tsx LOOKS (`port` rewrites them).
The user's own: <library>/design-systems/<id>/tokens.json; `brand` is made from the profile's brand kit.

    python3 design.py list                 every design system: id, source, name
    python3 design.py show <id>            its compiled Look (JSON)
    python3 design.py check [<file>]       validate every tokens.json (or one), exit 1 on a problem
    python3 design.py brand                write <library>/design-systems/brand/tokens.json from profile.json's brand kit
    python3 design.py port                 rewrite the built-ins from look.tsx LOOKS (after a preset changes there)
    python3 design.py demo                 self-check: every built-in compiles to exactly its look.tsx preset

A tokens.json: groups color (ground, ink, muted, accent, accentInk, line, mark, ring), typography (body, display,
serif: fontFamily, fontWeight, display.letterSpacing), radius.card, shadow.card, and optional motion (duration,
cubicBezier). $extensions["ai-editor"] at the root holds what DTCG has no type for: id, name, preset (the look.tsx
preset it is read as), extends (another system it overrides), surface, case, texture, textureAmount, decor and
motion (a personality: snappy, smooth, punchy, calm).
"""
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILTIN = HERE.parents[1] / "design-systems"            # .claude/design-systems
LOOK_TSX = HERE.parents[1] / "remotion" / "src" / "look.tsx"
EXT = "ai-editor"
SPEC = "https://www.designtokens.org/tr/2025.10/format/"
LOOK_KEYS = ("preset", "ground", "ink", "muted", "accent", "accent_ink", "line", "surface", "radius", "shadow", "font",
             "font_display", "font_serif", "weight", "weight_display", "tracking", "case", "texture", "texture_amount",
             "decor", "mark", "ring")
COLORS = {"ground": "ground", "ink": "ink", "muted": "muted", "accent": "accent", "accentInk": "accent_ink", "line": "line",
          "mark": "mark", "ring": "ring"}
ENUMS = {"surface": ("none", "card", "glass"), "case": ("as_is", "lower", "upper"), "texture": ("none", "grain", "paper", "print"),
         "decor": ("none", "blocks"), "shadow": ("none", "soft", "hard"), "motion": ("snappy", "smooth", "punchy", "calm")}
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


# ---------- colours ----------
def color_token(css):
    """A CSS colour (#RRGGBB or rgba(r,g,b,a)) -> a DTCG colour value (sRGB components 0-1, alpha, hex)."""
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", css.strip())
    if m:
        n = int(m[1], 16)
        rgb, a = (n >> 16, (n >> 8) & 255, n & 255), 1
    else:
        m = re.fullmatch(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", css.strip())
        if not m:
            raise ValueError(f"not a colour: {css!r}")
        rgb, a = tuple(int(x) for x in m.groups()[:3]), float(m[4]) if m[4] is not None else 1
    hexs = css.strip() if css.strip().startswith("#") else "#%02X%02X%02X" % rgb
    return {"colorSpace": "srgb", "components": [round(c / 255, 6) for c in rgb], "alpha": a, "hex": hexs}


def css_color(v):
    """A DTCG colour value -> the CSS the renderer draws with: its hex when opaque, rgba() otherwise."""
    rgb = [round(c * 255) for c in v["components"]]
    a = v.get("alpha", 1)
    if a == 1:
        return v.get("hex") or "#%02X%02X%02X" % tuple(rgb)
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{a:g})"


SHADOWS = {   # look.tsx shadowOf in DTCG shadow values (offsets in px at a 100 px card unit)
    "soft": [{"color": color_token("rgba(0,0,0,0.22)"), "offsetX": {"value": 0, "unit": "px"}, "offsetY": {"value": 1.2, "unit": "px"},
              "blur": {"value": 4, "unit": "px"}, "spread": {"value": 0, "unit": "px"}},
             {"color": color_token("rgba(0,0,0,0.12)"), "offsetX": {"value": 0, "unit": "px"}, "offsetY": {"value": 0.2, "unit": "px"},
              "blur": {"value": 0.5, "unit": "px"}, "spread": {"value": 0, "unit": "px"}}],
    "hard": [{"color": color_token("#000000"), "offsetX": {"value": 1.1, "unit": "px"}, "offsetY": {"value": 1.1, "unit": "px"},
              "blur": {"value": 0, "unit": "px"}, "spread": {"value": 0, "unit": "px"}}],
    "none": [],
}


# ---------- Look <-> tokens ----------
def tokens_from_look(look, sid, name, description=""):
    """A complete tokens.json for a Look dict (every LOOK_KEYS key)."""
    t = {"$schema": SPEC, "$description": description or f"The {name} design system.",
         "$extensions": {EXT: {"id": sid, "name": name, "preset": look["preset"], "surface": look["surface"], "case": look["case"],
                               "texture": look["texture"], "textureAmount": look["texture_amount"], "decor": look["decor"]}},
         "color": {"$type": "color", **{k: {"$value": color_token(look[v])} for k, v in COLORS.items()}},
         "typography": {
             "body": {"fontFamily": {"$type": "fontFamily", "$value": look["font"]},
                      "fontWeight": {"$type": "fontWeight", "$value": look["weight"]}},
             "display": {"fontFamily": {"$type": "fontFamily", "$value": look["font_display"]},
                         "fontWeight": {"$type": "fontWeight", "$value": look["weight_display"]},
                         "letterSpacing": {"$type": "number", "$value": look["tracking"], "$extensions": {EXT: {"unit": "em"}}}},
             "serif": {"fontFamily": {"$type": "fontFamily", "$value": look["font_serif"] or []},
                       "$description": "the italic emphasis word; [] for none"}},
         "radius": {"card": {"$type": "number", "$value": look["radius"], "$extensions": {EXT: {"unit": "pctShortSide"}},
                             "$description": "corner radius, % of the card's short side"}},
         "shadow": {"card": {"$type": "shadow", "$value": SHADOWS[look["shadow"]], "$extensions": {EXT: {"style": look["shadow"]}}}}}
    return t


def _get(t, *path):
    for p in path:
        if not isinstance(t, dict) or p not in t:
            return None
        t = t[p]
    return t


def look_from_tokens(t):
    """The Look a (complete) tokens.json describes; keys it does not set are left out (for `extends`)."""
    ext = _get(t, "$extensions", EXT) or {}
    out = {}
    for k, v in COLORS.items():
        val = _get(t, "color", k, "$value")
        if val is not None:
            out[v] = css_color(val)
    fam = lambda x: "" if x in ([], None) else (x[0] if isinstance(x, list) else x)
    for path, key, f in ((("typography", "body", "fontFamily"), "font", fam), (("typography", "display", "fontFamily"), "font_display", fam),
                         (("typography", "serif", "fontFamily"), "font_serif", fam), (("typography", "body", "fontWeight"), "weight", None),
                         (("typography", "display", "fontWeight"), "weight_display", None),
                         (("typography", "display", "letterSpacing"), "tracking", None), (("radius", "card"), "radius", None)):
        tok = _get(t, *path)
        if tok is not None and "$value" in tok:
            out[key] = f(tok["$value"]) if f else tok["$value"]
    sh = _get(t, "shadow", "card")
    if sh is not None:
        out["shadow"] = _get(sh, "$extensions", EXT, "style") or ("none" if not sh.get("$value") else "soft")
    for k, key in (("preset", "preset"), ("surface", "surface"), ("case", "case"), ("texture", "texture"),
                   ("textureAmount", "texture_amount"), ("decor", "decor")):
        if k in ext:
            out[key] = ext[k]
    return out


# ---------- the files ----------
def user_dir():
    try:
        sys.path.insert(0, str(HERE.parent))
        from ai_editor import library
        return library.path(make=False) / "design-systems"
    except Exception:
        return None


def files(dirs=None):
    """{id: (path, source)}: the built-ins, then the user's (a user id never replaces a built-in; brand is the brand kit)."""
    out = {}
    roots = [(BUILTIN, "builtin")] + [(Path(d), "user") for d in (dirs if dirs is not None else [user_dir()]) if d]
    for root, source in roots:
        if root.is_dir():
            for d in sorted(root.iterdir()):
                f = d / "tokens.json"
                if f.is_file() and d.name not in out:
                    out[d.name] = (f, "brand" if source == "user" and d.name == "brand" else source)
    return out


def load(sid, dirs=None):
    f = files(dirs).get(sid)
    if not f:
        raise KeyError(f"no design system {sid!r}")
    return json.loads(f[0].read_text(encoding="utf-8"))


def compile(sid, dirs=None, _seen=()):
    """The full Look for a design system, following `extends` (default: the editorial look, like plan.py)."""
    if sid in _seen:
        raise ValueError(f"design system {sid!r} extends itself")
    t = load(sid, dirs)
    own = look_from_tokens(t)
    base_id = _get(t, "$extensions", EXT, "extends")
    if base_id:
        base = compile(base_id, dirs, _seen + (sid,))
    elif all(k in own for k in LOOK_KEYS if k != "preset"):
        base = {}
    else:
        base = compile("editorial", dirs, _seen + (sid,)) if sid != "editorial" else {}
    look = {**base, **own}
    look.setdefault("preset", _get(t, "$extensions", EXT, "preset") or sid)
    missing = [k for k in LOOK_KEYS if k not in look]
    if missing:
        raise ValueError(f"design system {sid!r} leaves out {', '.join(missing)}")
    return {k: look[k] for k in LOOK_KEYS}


def motion(sid, dirs=None):
    """The motion personality a design system names, or None."""
    return _get(load(sid, dirs), "$extensions", EXT, "motion")


def listing(dirs=None):
    """The app's picker rows (/api/design-systems)."""
    rows = []
    for sid, (f, source) in files(dirs).items():
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
            bad = validate(t, sid)
            if bad:
                raise ValueError(bad[0])
            lk = compile(sid, dirs)
        except (ValueError, KeyError, OSError, TypeError) as e:
            rows.append({"id": sid, "name": sid, "source": source, "error": str(e)})
            continue
        rows.append({"id": sid, "name": _get(t, "$extensions", EXT, "name") or sid, "source": source,
                     "description": t.get("$description", ""), "swatch": {k: lk[k] for k in ("ground", "ink", "accent")},
                     "font": lk["font"], "font_display": lk["font_display"], "motion": motion(sid, dirs)})
    return rows


# ---------- validation ----------
def _dim(v, units):
    return isinstance(v, dict) and isinstance(v.get("value"), (int, float)) and v.get("unit") in units


def check_value(typ, v):
    """None when `v` is a valid DTCG value of type `typ`, else why not."""
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    if typ == "color":
        ok = isinstance(v, dict) and v.get("colorSpace") == "srgb" and isinstance(v.get("components"), list) \
            and len(v["components"]) == 3 and all(num(c) and 0 <= c <= 1 for c in v["components"]) \
            and num(v.get("alpha", 1)) and 0 <= v.get("alpha", 1) <= 1
        return None if ok else "a colour is {colorSpace: srgb, components: [r, g, b] 0-1, alpha?, hex?}"
    if typ == "fontFamily":
        return None if isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v)) else "a font family name or a list"
    if typ == "fontWeight":
        return None if (num(v) and 1 <= v <= 1000) or v in ("thin", "light", "normal", "regular", "medium", "bold", "black") else "a weight 1-1000"
    if typ == "number":
        return None if num(v) else "a number"
    if typ == "dimension":
        return None if _dim(v, ("px", "rem")) else "{value, unit: px | rem}"
    if typ == "duration":
        return None if _dim(v, ("ms", "s")) else "{value, unit: ms | s}"
    if typ == "cubicBezier":
        return None if isinstance(v, list) and len(v) == 4 and all(num(x) for x in v) and 0 <= v[0] <= 1 and 0 <= v[2] <= 1 \
            else "[x1, y1, x2, y2] with x in 0-1"
    if typ == "shadow":
        sh = v if isinstance(v, list) else [v]
        ok = all(isinstance(s, dict) and check_value("color", s.get("color")) is None and
                 all(_dim(s.get(k), ("px", "rem")) for k in ("offsetX", "offsetY", "blur", "spread")) for s in sh)
        return None if ok else "a shadow (or list): color, offsetX, offsetY, blur, spread"
    return f"unknown $type {typ!r}"


def validate(t, where="tokens"):
    """Problems with one tokens.json: DTCG structure and the ai-editor extensions."""
    errs = []

    def walk(node, path, inherited):
        typ = node.get("$type", inherited)
        if "$value" in node:
            if not typ:
                errs.append(f"{where}: {path} has no $type")
            else:
                why = check_value(typ, node["$value"])
                if why:
                    errs.append(f"{where}: {path}: {why}")
            return
        for k, v in node.items():
            if not k.startswith("$") and isinstance(v, dict):
                walk(v, f"{path}.{k}" if path else k, typ)
            elif not k.startswith("$"):
                errs.append(f"{where}: {path}.{k} is neither a group nor a token")
    if not isinstance(t, dict):
        return [f"{where}: not a JSON object"]
    walk(t, "", None)
    ext = _get(t, "$extensions", EXT) or {}
    for k, allowed in ENUMS.items():
        if k in ext and ext[k] not in allowed:
            errs.append(f"{where}: $extensions.{EXT}.{k} must be one of {allowed}")
    if "textureAmount" in ext and not (isinstance(ext["textureAmount"], (int, float)) and 0 <= ext["textureAmount"] <= 1):
        errs.append(f"{where}: $extensions.{EXT}.textureAmount must be 0-1")
    sh = _get(t, "shadow", "card", "$extensions", EXT, "style")
    if sh is not None and sh not in ENUMS["shadow"]:
        errs.append(f"{where}: shadow.card style must be one of {ENUMS['shadow']}")
    return errs


def problems(dirs=None):
    errs = []
    for sid, (f, _) in files(dirs).items():
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errs.append(f"{f}: unreadable ({e})")
            continue
        bad = validate(t, str(f))
        errs += bad
        if not ID_RE.match(sid):
            errs.append(f"{f}: folder name must match {ID_RE.pattern}")
        if not bad:
            try:
                compile(sid, dirs)
            except Exception as e:   # noqa: BLE001  a file that validates but cannot compile (a bad extends)
                errs.append(f"{f}: {e}")
    return errs


# ---------- look.tsx and the brand kit ----------
def parse_looks(text=None):
    """look.tsx LOOKS -> {preset: Look dict}, spreads resolved. Parsed, so the built-ins never drift from the renderer."""
    text = text if text is not None else LOOK_TSX.read_text(encoding="utf-8")
    pair = re.compile(r"(\w+):\s*(\"[^\"]*\"|-?\d+(?:\.\d+)?)")
    def body(src):
        d = {"_spread": re.findall(r"\.\.\.(\w+)", src)}
        for k, v in pair.findall(src):
            d[k] = json.loads(v) if v.startswith('"') else (float(v) if "." in v else int(v))
        return d
    consts = {m[1]: body(m[2]) for m in re.finditer(r"const\s+(\w+)\s*:\s*Look\s*=\s*\{([^{}]*)\}", text)}
    block = text[text.index("export const LOOKS"):]
    block = block[block.index("{") + 1:]
    depth, end = 1, 0
    for i, ch in enumerate(block):
        depth += ch == "{"
        depth -= ch == "}"
        if depth == 0:
            end = i
            break
    block = block[:end]
    named = {}
    for m in re.finditer(r"\"?([\w-]+)\"?\s*:\s*(\{[^{}]*\}|[A-Z_]+)", block):
        named[m[1]] = consts[m[2]] if not m[2].startswith("{") else body(m[2])

    def flat(d):
        out = {}
        for s in d.get("_spread", []):
            out.update(flat(consts[s]))
        out.update({k: v for k, v in d.items() if k != "_spread"})
        return out
    return {k: flat(v) for k, v in named.items()}


NAMES = {"neutral": "Neutral", "editorial": "Editorial", "editorial-dark": "Editorial dark", "poster-red": "Poster red",
         "poster-green": "Poster green", "poster-blue": "Poster blue", "mono": "Mono", "glass": "Glass"}


def port(out=BUILTIN):
    """Rewrite the built-in tokens.json files from look.tsx LOOKS."""
    sys.path.insert(0, str(HERE.parent))
    from ai_editor import presets
    about = getattr(presets, "LOOKS", {})
    for sid, look in parse_looks().items():
        d = out / sid
        d.mkdir(parents=True, exist_ok=True)
        t = tokens_from_look(look, sid, NAMES.get(sid, sid), about.get(sid, ""))
        (d / "tokens.json").write_text(json.dumps(t, indent=2) + "\n", encoding="utf-8")
    return sorted(parse_looks())


def from_brand(brand, out_dir=None, base="editorial", dirs=None):
    """The profile's brand kit as a design system: profile.brand_look() over `base`, written to
    <library>/design-systems/brand/tokens.json. Returns the path (None when the kit sets nothing)."""
    sys.path.insert(0, str(HERE.parent))
    from ai_editor import profile
    own = profile.brand_look(brand or {})
    if not own:
        return None
    look = {**compile(base, dirs), **{k: v for k, v in own.items() if k in LOOK_KEYS}}
    out_dir = Path(out_dir) if out_dir else (user_dir() / "brand")
    out_dir.mkdir(parents=True, exist_ok=True)
    t = tokens_from_look(look, "brand", "Brand kit", "Your brand kit's colours and fonts (profile.json brand), over the editorial look.")
    f = out_dir / "tokens.json"
    f.write_text(json.dumps(t, indent=2) + "\n", encoding="utf-8")
    return f


def demo():
    looks = parse_looks()
    assert set(looks) >= {"neutral", "editorial", "editorial-dark", "poster-red", "mono", "glass"}, set(looks)
    assert set(files(dirs=[])) == set(looks), "every look.tsx preset is a built-in design system (design.py port)"
    assert problems(dirs=[]) == [], problems(dirs=[])
    for sid, look in looks.items():
        got = compile(sid, dirs=[])
        assert got == {k: look[k] for k in LOOK_KEYS}, (sid, {k: (got[k], look.get(k)) for k in LOOK_KEYS if got[k] != look.get(k)})
    assert css_color(color_token("rgba(20,20,20,0.14)")) == "rgba(20,20,20,0.14)" and css_color(color_token("#F2EEE6")) == "#F2EEE6"
    with tempfile.TemporaryDirectory() as d:
        u = Path(d)
        # a user system that extends a built-in and changes two tokens
        (u / "ocean").mkdir()
        (u / "ocean" / "tokens.json").write_text(json.dumps({
            "$extensions": {EXT: {"name": "Ocean", "extends": "neutral", "motion": "calm"}},
            "color": {"$type": "color", "accent": {"$value": color_token("#0A6CFF")}},
            "typography": {"display": {"fontFamily": {"$type": "fontFamily", "$value": "Fraunces"}}}}), encoding="utf-8")
        oc = compile("ocean", dirs=[u])
        assert oc["accent"] == "#0A6CFF" and oc["font_display"] == "Fraunces" and oc["ground"] == looks["neutral"]["ground"], oc
        assert oc["preset"] == "neutral" and motion("ocean", dirs=[u]) == "calm"
        # a broken one is reported, never compiled into a plan
        (u / "broken").mkdir()
        (u / "broken" / "tokens.json").write_text(json.dumps({"color": {"ground": {"$type": "color", "$value": "#fff"}},
                                                              "$extensions": {EXT: {"surface": "metal"}}}), encoding="utf-8")
        errs = problems(dirs=[u])
        assert any("colour is" in e for e in errs) and any("surface must be" in e for e in errs), errs
        rows = {r["id"]: r for r in listing(dirs=[u])}
        assert rows["ocean"]["source"] == "user" and rows["ocean"]["swatch"]["accent"] == "#0A6CFF" and "error" in rows["broken"]
        assert rows["editorial"]["source"] == "builtin" and rows["editorial"]["font"] == "IBM Plex Sans"
        # the brand kit becomes a design system
        f = from_brand({"colors": ["#FAF7F0", "#E5482C", "#101010"], "font": "Fraunces"}, out_dir=u / "brand", dirs=[u])
        bl = compile("brand", dirs=[u])
        assert f and bl["ground"] == "#FAF7F0" and bl["ink"] == "#101010" and bl["accent"] == "#E5482C" and bl["font"] == "Fraunces", bl
        assert {r["id"]: r for r in listing(dirs=[u])}["brand"]["source"] == "brand"
        assert from_brand({}, out_dir=u / "none", dirs=[u]) is None
    print("demo ok")


def main():
    a = sys.argv[1:]
    if a[:1] == ["demo"]:
        return demo()
    if a[:1] == ["list"]:
        for r in listing():
            print(f"{r['id']:<16} {r['source']:<8} {r.get('name', '')}" + (f"  ({r['error']})" if r.get("error") else ""))
        return
    if a[:1] == ["show"] and len(a) == 2:
        return print(json.dumps(compile(a[1]), indent=2))
    if a[:1] == ["check"]:
        errs = validate(json.loads(Path(a[1]).read_text(encoding="utf-8")), a[1]) if len(a) > 1 else problems()
        for e in errs:
            print(f"FAIL {e}")
        print("ok" if not errs else f"{len(errs)} problem(s)")
        sys.exit(1 if errs else 0)
    if a[:1] == ["brand"]:
        sys.path.insert(0, str(HERE.parent))
        from ai_editor import profile
        f = from_brand((profile.load() or {}).get("brand") or {})
        return print(f or "the brand kit sets no colours or fonts: nothing written")
    if a[:1] == ["port"]:
        return print("ported: " + ", ".join(port()))
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
