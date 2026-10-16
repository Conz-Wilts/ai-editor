#!/usr/bin/env python3
"""The editor's docs as an Open Knowledge Format (OKF v0.2) bundle rooted at .claude/.

Every markdown file under .claude/ is a concept with YAML frontmatter and a `type`
(Skill, Agent, Reference, Principles); index.md files list each folder for progressive
disclosure and log.md records changes (both reserved names, never concepts).
Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

    python3 okf.py stamp    give every concept without frontmatter `type`, `title`, `description`
    python3 okf.py index    rewrite every index.md from the concepts' frontmatter
    python3 okf.py check    exit 1 when the bundle is not conformant (or an index.md is stale)
    python3 okf.py demo     self-check on a temporary bundle

Stdlib only.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # .claude
VERSION = "0.2"
RESERVED = ("index.md", "log.md")
SKIP = ("node_modules", "results", "__pycache__")   # installed or generated, not knowledge
TYPES = {"SKILL.md": "Skill", "PRINCIPLES.md": "Principles"}


def concepts(root):
    """Every concept document in the bundle, sorted."""
    return sorted(p for p in root.rglob("*.md")
                  if p.name not in RESERVED and not set(p.relative_to(root).parts) & set(SKIP))


def frontmatter(text):
    """{key: value} of a top-level YAML block (flat keys; quoted strings unquoted), or None."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    out = {}
    for line in text[4:end].splitlines():
        m = re.match(r"([A-Za-z_][\w-]*):\s?(.*)$", line)
        if m:
            v = m[2].strip()
            if v[:1] == '"':
                try:
                    v = json.loads(v)
                except ValueError:
                    pass
            out[m[1]] = v
    return out


def kind(path, root):
    rel = path.relative_to(root).parts
    return TYPES.get(path.name) or ("Agent" if rel[0] == "agents" else "Reference")


def summary(body):
    """The first sentence of the first paragraph that is prose (not a heading, list, table or code)."""
    para, fence = [], False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
            continue
        if fence or s.startswith(("#", "|", "<", ">", "-", "*", "!")) or re.match(r"\d+\.", s):
            if para:
                break
            continue
        if not s:
            if para:
                break
            continue
        para.append(s)
    text = re.sub(r"\s+", " ", " ".join(para))
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    text = (m[1] if m else text)
    return text if len(text) <= 200 else text[:197].rsplit(" ", 1)[0] + "..."


def stamp(root=ROOT):
    """Add frontmatter to concepts without it; add `type` to SKILL.md and agent files that lack it."""
    done = []
    for p in concepts(root):
        text = p.read_text(encoding="utf-8")
        nl = "\r\n" if "\r\n" in text else "\n"
        text = text.replace("\r\n", "\n")
        fm = frontmatter(text)
        if fm is not None:
            if fm.get("type"):
                continue
            new = text.replace("---\n", f"---\ntype: {kind(p, root)}\n", 1)   # first key: Claude reads the rest as before
        else:
            h1 = re.search(r"^# (.+)$", text, re.M)
            title = h1[1].strip() if h1 else p.stem.replace("-", " ").replace("_", " ").capitalize()
            desc = summary(text[h1.end():] if h1 else text)
            head = f"---\ntype: {kind(p, root)}\ntitle: {json.dumps(title, ensure_ascii=False)}\n"
            head += f"description: {json.dumps(desc, ensure_ascii=False)}\n" if desc else ""
            new = head + "---\n\n" + text.lstrip("\n")
        p.write_text(new.replace("\n", nl), encoding="utf-8", newline="")
        done.append(p)
    return done


def first_sentence(s):
    m = re.match(r"(.+?[.!?])(\s|$)", s or "")
    return (m[1] if m else s or "").strip()


def entry(p, root, here):
    fm = frontmatter(p.read_text(encoding="utf-8").replace("\r\n", "\n")) or {}
    name = fm.get("title") or fm.get("name") or p.stem
    d = first_sentence(fm.get("description", ""))
    return f"* [{name}]({p.relative_to(here).as_posix()})" + (f" - {d}" if d else "")


def build(here, root):
    """The index.md text for one folder: its concepts, then its subfolders that hold any."""
    docs = [p for p in sorted(here.glob("*.md")) if p.name not in RESERVED]
    subs = [d for d in sorted(here.iterdir()) if d.is_dir() and d.name not in SKIP
            and any(q for q in concepts(d))]
    skill = here / "SKILL.md"
    if here == root:
        lines = [f'---\nokf_version: "{VERSION}"\n---\n', "# ai-editor knowledge bundle", "",
                 "The editor's skills, agents and rules as OKF concepts. Start with a skill below;",
                 "each folder's index.md lists what is inside. Changes: [log.md](log.md).", ""]
    else:
        title = (frontmatter(skill.read_text(encoding="utf-8").replace("\r\n", "\n")) or {}).get("name") \
            if skill.exists() else here.name
        lines = [f"# {title}", ""]
    if docs:
        lines += ["# Documents", ""] if here != root else ["# Rules", ""]
        lines += [entry(p, root, here) for p in docs] + [""]
    if subs:
        lines += ["# Folders", ""]
        for d in subs:
            s = d / "SKILL.md"
            fm = frontmatter(s.read_text(encoding="utf-8").replace("\r\n", "\n")) if s.exists() else None
            desc = first_sentence((fm or {}).get("description", "")) or f"{len(concepts(d))} documents"
            lines.append(f"* [{d.name}]({d.name}/) - {desc}")
        lines.append("")
    return "\n".join(lines)


def folders(root):
    """Every folder that gets an index.md: the root and each folder holding concepts below it."""
    out = {root}
    for p in concepts(root):
        out.update(q for q in p.parents if q != root and root in q.parents)
    return sorted(out)


def index(root=ROOT):
    wrote = []
    for d in folders(root):
        f, text = d / "index.md", build(d, root)
        if not f.exists() or f.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
            f.write_text(text, encoding="utf-8", newline="\n")
            wrote.append(f)
    return wrote


def check(root=ROOT):
    """OKF v0.2 conformance (spec section 11), plus every index.md matching what `index` would write."""
    errs = []
    for p in concepts(root):
        fm = frontmatter(p.read_text(encoding="utf-8").replace("\r\n", "\n"))
        if fm is None:
            errs.append(f"{p}: no YAML frontmatter")
        elif not fm.get("type"):
            errs.append(f"{p}: frontmatter has no type")
    for d in folders(root):
        f = d / "index.md"
        if not f.exists() or f.read_text(encoding="utf-8").replace("\r\n", "\n") != build(d, root):
            errs.append(f"{f}: missing or stale; run okf.py index")
    log = root / "log.md"
    if log.exists():
        for h in re.findall(r"^## (.+)$", log.read_text(encoding="utf-8"), re.M):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", h.strip()):
                errs.append(f"{log}: date heading {h!r} is not YYYY-MM-DD")
    return errs


def demo():
    with tempfile.TemporaryDirectory() as t:
        r = Path(t)
        (r / "skills" / "cut" / "references").mkdir(parents=True)
        (r / "agents").mkdir()
        (r / "skills" / "cut" / "SKILL.md").write_text("---\nname: cut\ndescription: Cuts a take. Use when asked.\n---\n# Cut\n", encoding="utf-8")
        (r / "skills" / "cut" / "references" / "rubric.md").write_text(
            "# The judge rubric\n\n| a | b |\n\nGrades one cut: what stays. More here.\n", encoding="utf-8")
        (r / "agents" / "judge.md").write_text("---\nname: judge\ndescription: Grades a cut.\n---\nBody\n", encoding="utf-8")
        (r / "PRINCIPLES.md").write_text("# Principles\n\nThe rules every video follows.\n", encoding="utf-8")
        (r / "remotion" / "node_modules" / "x").mkdir(parents=True)
        (r / "remotion" / "node_modules" / "x" / "README.md").write_text("# x\n", encoding="utf-8")
        assert len(check(r)) >= 4
        assert len(stamp(r)) == 4 and stamp(r) == []
        fm = frontmatter((r / "skills" / "cut" / "references" / "rubric.md").read_text(encoding="utf-8"))
        assert fm == {"type": "Reference", "title": "The judge rubric", "description": "Grades one cut: what stays."}, fm
        sk = (r / "skills" / "cut" / "SKILL.md").read_text(encoding="utf-8")
        assert sk.startswith("---\ntype: Skill\nname: cut\n"), sk
        assert frontmatter((r / "agents" / "judge.md").read_text(encoding="utf-8"))["type"] == "Agent"
        assert frontmatter((r / "PRINCIPLES.md").read_text(encoding="utf-8"))["type"] == "Principles"
        index(r)
        assert check(r) == [], check(r)
        top = (r / "index.md").read_text(encoding="utf-8")
        assert top.startswith('---\nokf_version: "0.2"\n---\n') and "* [skills](skills/)" in top and "node_modules" not in top, top
        assert "* [Principles](PRINCIPLES.md) - The rules every video follows." in top, top
        assert "* [cut](cut/) - Cuts a take." in (r / "skills" / "index.md").read_text(encoding="utf-8")
        assert "* [The judge rubric](rubric.md) - Grades one cut: what stays." in \
            (r / "skills" / "cut" / "references" / "index.md").read_text(encoding="utf-8")
        assert not (r / "remotion" / "index.md").exists()
        (r / "skills" / "cut" / "references" / "new.md").write_text("---\ntype: Reference\n---\n", encoding="utf-8")
        assert any("stale" in e for e in check(r)), "a new concept makes its index stale"
        (r / "log.md").write_text("# Log\n\n## yesterday\n", encoding="utf-8")
        assert any("YYYY-MM-DD" in e for e in check(r))
    print("demo ok")


def main():
    cmd = sys.argv[1:2]
    if cmd == ["stamp"]:
        return print(f"stamped {len(stamp())} documents")
    if cmd == ["index"]:
        return print(f"wrote {len(index())} index.md files")
    if cmd == ["check"]:
        errs = check()
        for e in errs:
            print(f"FAIL {e}")
        print(f"{len(concepts(ROOT))} concepts, {len(folders(ROOT))} folders: " + ("ok" if not errs else f"{len(errs)} problem(s)"))
        sys.exit(1 if errs else 0)
    if cmd == ["demo"]:
        return demo()
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
