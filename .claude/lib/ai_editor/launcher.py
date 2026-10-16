#!/usr/bin/env python3
"""ai-editor: open the ai-editor window, with Claude Code behind it. Stdlib only.

    ai-editor                 open the window (the same address every time), with a listening Claude behind it
    ai-editor --window-only   open the window only, never start Claude
    ai-editor --dry-run [--os Darwin|Linux|Windows]   print what it would run, and where
    open_claude(folder, prompt)     a Claude of its own for each new video (home.py claude_for): a new terminal window
    connect(folder)                 the home page's "Connect Claude": a new terminal with a listening Claude
    python3 launcher.py demo        self-check

`setup.py install-launcher` puts the `ai-editor` command on the PATH; `uninstall-launcher` takes
it off. Inside Claude Code the same thing is `/start`.

When the home page is already served (a Claude Code session has it open), its address opens again in
the browser, and when no Claude is listening (`home.py wait`), connect() opens one in a new terminal
window. Otherwise Claude Code starts in the library folder (library.py)
with one first prompt, PROMPT, and opens the page there, so Claude is listening behind it. The editor's
repo is added with --add-dir, which loads its .claude/skills and .claude/agents; its hooks come in one extra
settings layer (--settings, session_settings: <AI_EDITOR_HOME>/session-settings.json), with the editor's own
commands allowed without a prompt (allow_rules) and nothing else. The user's permission settings apply as
always: nothing is bypassed.
"""
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home  # noqa: E402
import library  # noqa: E402

EDITOR = Path(__file__).resolve().parents[2]          # the repo's .claude: skills, agents, lib, renderer
PROMPT = "/start open the home page"
LISTEN = "/start listen for jobs"   # serve --no-open + wait: takes the queued jobs, not one video
CONNECT_S = 60   # how long a connect counts as pending: the page shows "Opening Claude..." and no second terminal opens


MARK = "installed by ai-editor setup.py install-launcher"

def launcher_text(os_name=None, launcher=EDITOR / "lib" / "ai_editor" / "launcher.py", py=sys.executable):
    """The ai-editor file: runs this checkout's launcher.py (home.py serve rewrites it if the checkout moves)."""
    os_name = os_name or platform.system()
    if os_name == "Windows":
        return (f"@echo off\r\nrem ai-editor: opens ai-editor {MARK}; remove with setup.py uninstall-launcher\r\n"
                f'set "L={launcher}"\r\nset "PY={py}"\r\nif not exist "%PY%" set "PY=py"\r\n'
                'if not exist "%L%" (echo ai-editor moved, maybe an update. In Claude Code, say: set up the editor. & exit /b 1)\r\n'
                '"%PY%" "%L%" %*\r\n')
    return (f"#!/bin/sh\n# ai-editor: opens ai-editor {MARK}; remove with setup.py uninstall-launcher\n"
            f"L={shlex.quote(str(launcher))}\nPY={shlex.quote(str(py))}\n[ -x \"$PY\" ] || PY=python3\n"
            'if [ ! -f "$L" ]; then echo "ai-editor moved, maybe an update. In Claude Code, say: set up the editor."; exit 1; fi\n'
            'exec "$PY" "$L" "$@"\n')


def refresh():
    """Rewrite an installed ai-editor that points at another copy of the editor (run by home.py serve).
    Only files the editor wrote (MARK); never installs one."""
    home_dir = Path.home()
    names = ["ai-editor.cmd"] if platform.system() == "Windows" else ["ai-editor"]
    dirs = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p] + [home_dir / ".local" / "bin"]
    for d in dict.fromkeys(dirs):
        for n in names:
            f = d / n
            try:
                old = f.read_text(encoding="utf-8")
            except OSError:
                continue
            want = launcher_text()
            if MARK in old and old != want:
                with open(f, "w", encoding="utf-8", newline="") as fh:
                    fh.write(want)


def allow_rules(editor=EDITOR):
    """The narrowest Allow rules for what the skills run: the editor's own scripts (python3 / py / node, the path
    quoted or not), ffmpeg, ffprobe and the Remotion CLI. Never Bash on its own, never another folder."""
    root = Path(editor).as_posix()
    own = [f"Bash({exe} {q}{root}/*)" for exe in ("python3", "py", "node") for q in ("", '"')]
    return own + ["Bash(ffmpeg *)", "Bash(ffprobe *)", "Bash(npx remotion *)"]


def hooks(editor=EDITOR):
    """The repo's .claude/settings.json hooks for a session whose project is another folder (the library):
    ${CLAUDE_PROJECT_DIR}/.claude becomes this editor's own path."""
    try:
        h = json.loads((Path(editor) / "settings.json").read_text(encoding="utf-8")).get("hooks") or {}
    except (OSError, ValueError):
        return {}
    return json.loads(json.dumps(h).replace("${CLAUDE_PROJECT_DIR}/.claude", Path(editor).as_posix()))


def session_settings(editor=EDITOR, write=True):
    """The one extra settings layer: Allow rules and hooks, saved to <AI_EDITOR_HOME>/session-settings.json
    (a file: the hooks are too long for a Windows command line). Returns its path."""
    f = home.home() / "session-settings.json"
    if write:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"permissions": {"allow": allow_rules(editor)}, "hooks": hooks(editor)}, indent=1),
                     encoding="utf-8")
    return f


def plan(os_name=None, editor=EDITOR, claude=None, prompt=PROMPT, write=True):
    """The Claude Code command: the editor's repo added (--add-dir loads its .claude/skills and .claude/agents)
    and the settings layer with its hooks."""
    os_name = os_name or platform.system()
    claude = claude or shutil.which("claude") or ("claude.exe" if os_name == "Windows" else "claude")
    return [claude, "--add-dir", str(Path(editor).parent), "--settings", str(session_settings(editor, write)), prompt]


def show(cmd, os_name):
    return subprocess.list2cmdline(cmd) if os_name == "Windows" else shlex.join(cmd)


def terminal(folder, cmd, os_name):
    """The command that opens a new terminal window running cmd in folder, or None when this computer has no
    terminal to open (Linux without x-terminal-emulator): the page then shows the command to copy."""
    if os_name == "Darwin":
        line = f"cd {shlex.quote(str(folder))} && {shlex.join(cmd)}"
        esc = line.replace("\\", "\\\\").replace('"', '\\"')   # inside an AppleScript string
        return ["osascript", "-e", f'tell application "Terminal" to do script "{esc}"',
                "-e", 'tell application "Terminal" to activate']
    if os_name == "Windows":
        # a console of its own (CREATE_NEW_CONSOLE) started in folder, so the folder is never quoted for cmd. One
        # string, not a list: a list would escape the inner quotes as \" (cmd reads them literally); cmd /k
        # strips the outer pair and runs what is inside as typed.
        return f'cmd /k "{subprocess.list2cmdline(cmd)}"'
    xte = shutil.which("x-terminal-emulator")
    if not xte:
        return None
    return [xte, "-e", "sh", "-c", f'cd {shlex.quote(str(folder))} && {shlex.join(cmd)}; exec "${{SHELL:-sh}}"']


def start(argv, folder, os_name):
    """Run terminal()'s command. True only when the window opened (as far as the OS says)."""
    try:
        if os_name == "Darwin":   # osascript returns once Terminal has the window, non-zero when it is refused
            return subprocess.run(argv, capture_output=True, timeout=60).returncode == 0
        if os_name == "Windows":
            subprocess.Popen(argv, cwd=str(folder), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10))
            return True
        p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:   # a terminal that cannot start exits at once
            return p.wait(timeout=2) == 0
        except subprocess.TimeoutExpired:
            return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def open_claude(folder, prompt, os_name=None, run=start):
    """(opened, the command as the user would type it, for the page to show when nothing opened).
    run(argv, folder, os_name) -> bool; the demos pass a recorder so no real window opens."""
    os_name = os_name or platform.system()
    cmd = plan(os_name, prompt=prompt)
    # the window's own folders: a Terminal opened by osascript does not inherit them, so the new Claude would
    # listen on another home. Windows and x-terminal-emulator start as children and inherit them.
    pairs = [f"{k}={os.environ[k]}" for k in ("AI_EDITOR_HOME", "AI_EDITOR_LIBRARY") if os.environ.get(k)]
    if pairs and os_name != "Windows":
        cmd = ["env", *pairs] + cmd
    text = (f"cd /d {show([str(folder)], os_name)} && " if os_name == "Windows" else f"cd {show([str(folder)], os_name)} && ") \
        + show(cmd, os_name)
    argv = terminal(folder, cmd, os_name)
    return (bool(argv) and run(argv, folder, os_name)), text


def connect(folder, now=None):
    """The page's "Connect Claude" and ai-editor: a new terminal running Claude with LISTEN, one at a time.
    (status, command to copy): "listening" (one already is), "pending" (one opened under CONNECT_S ago),
    "opened", or "manual" (no terminal opened: the command is for the user to run)."""
    if home.listening():
        return "listening", ""
    now = now or time.time()

    def claim(d):
        if now - (d.get("connect") or 0) < CONNECT_S:
            return False
        d["connect"] = now   # the page reads it; home.py wait clears it once Claude listens
        return True
    if not home.update(claim):
        return "pending", ""
    opened, text = open_claude(folder, LISTEN)
    if not opened:
        home.update(lambda d: d.pop("connect", None))
    return ("opened" if opened else "manual"), text


CONNECTED = {"listening": "Claude is already listening.", "pending": "Claude is already starting in another Terminal window.",
             "opened": "Claude is starting in a new Terminal window. It picks up what you make in the window."}


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    dry, window_only = "--dry-run" in a, "--window-only" in a
    os_name = a[a.index("--os") + 1] if "--os" in a else platform.system()
    lib = library.path(make=not dry)
    url = home.running()
    if url:
        print(f"Opening your editor...\n  Already open at {url.split('?')[0]}")
        if not dry:
            webbrowser.open(url)
        if not window_only:
            st, text = ("listening" if home.listening() else "opened", "") if dry else connect(lib)
            print("  " + CONNECTED.get(st, f"Run this in a new Terminal window so Claude picks up your jobs:\n  {text}"))
        return 0
    if window_only:   # the page alone, served from this terminal; jobs wait until a Claude listens
        serve = [sys.executable, str(Path(home.__file__)), "serve"]
        if dry:
            print(show(serve, os_name))
            return 0
        print("Opening your editor...\n  Window only: Claude is not started. Keep this terminal open while you use it.", flush=True)
        return subprocess.call(serve)
    cmd = plan(os_name, write=not dry)
    if dry:
        print(f"cd {show([str(lib)], os_name)}\n{show(cmd, os_name)}")
        return 0
    if not shutil.which(cmd[0]) and not Path(cmd[0]).is_file():
        print("Claude Code is not installed yet. Install it from https://claude.com/claude-code, then run this again.")
        return 1
    print(f"Opening your editor...\n  Your videos: {lib}\n  Claude Code is starting. The window opens in a moment.\n"
          "  If Claude Code asks whether you trust this folder, press the down arrow to pick \"Yes, I trust this folder\",\n"
          "  then Enter (Enter alone picks \"No, exit\"). It is your videos folder.",
          flush=True)
    os.chdir(lib)
    if os_name == "Windows":
        return subprocess.call(cmd)
    os.execvp(cmd[0], cmd)   # hand the terminal to Claude Code


def demo():
    global open_claude
    import contextlib
    import io
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="launcher_demo_"))
    os.environ["AI_EDITOR_HOME"] = str(tmp / "home")
    os.environ["AI_EDITOR_LIBRARY"] = str(tmp / "My Videos")
    for os_name in ("Darwin", "Linux", "Windows"):
        ed = tmp / "repo" / ".claude"
        ed.mkdir(parents=True, exist_ok=True)
        (ed / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command",
            "command": 'python3 "${CLAUDE_PROJECT_DIR}/.claude/lib/ai_editor/toolhook.py" stop'}]}]}}), encoding="utf-8")
        cmd = plan(os_name, editor=ed, claude="claude")
        assert cmd[:3] == ["claude", "--add-dir", str(tmp / "repo")] and cmd[-1] == PROMPT, cmd
        assert not any("dangerously" in c or "bypass" in c.lower() for c in cmd), "never bypass permissions"
        layer = json.loads(Path(cmd[cmd.index("--settings") + 1]).read_text(encoding="utf-8"))
        assert set(layer) == {"permissions", "hooks"}, "only Allow rules and the editor's hooks"
        rules = layer["permissions"]["allow"]
        assert f"Bash(python3 {ed.as_posix()}/*)" in rules and "Bash(ffmpeg *)" in rules, rules
        assert all(r.startswith("Bash(") and r != "Bash(*)" and len(r) > 12 for r in rules), "never broad Bash"
        hook = layer["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert hook == f'python3 "{ed.as_posix()}/lib/ai_editor/toolhook.py" stop', hook   # the library is the project
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            assert main(["--dry-run", "--os", os_name]) == 0
        lines = o.getvalue().splitlines()
        q = '"' if os_name == "Windows" else "'"
        assert lines[0] == f"cd {q}{library.path(make=False)}{q}" and lines[1].endswith(f"{q}{PROMPT}{q}"), lines
        print(f"{os_name:<8} {lines[0]}  &&  {lines[1]}")
    assert not (tmp / "My Videos").exists(), "a dry run makes nothing"
    # a Claude of its own for a new video: the window it would open, per OS (recorded, never run)
    for os_name in ("Darwin", "Windows", "Linux"):
        ran = []
        opened, text = open_claude(Path("/lib/My Videos"), "/start take job video-2", os_name,
                                   run=lambda w, f, o: ran.append((w, f)) or True)
        assert "take job video-2" in text and "My Videos" in text, text
        if ran:
            assert opened and len(ran) == 1
            w, f = ran[0]
            flat = w if isinstance(w, str) else " ".join(w)
            assert "take job video-2" in flat and (os_name == "Windows" or "My Videos" in flat), flat
            assert os_name != "Darwin" or w[0] == "osascript", w
            assert os_name != "Windows" or (w.startswith('cmd /k "') and "My Videos" not in w and text.startswith("cd /d ")), (w, text)
        else:
            assert os_name == "Linux" and not opened and not shutil.which("x-terminal-emulator"), "no terminal: copy it"
        print(f"{os_name:<8} new Claude: {text}")
        assert open_claude(Path("/lib/My Videos"), "x", os_name, run=lambda w, f, o: False)[0] is False, "nothing opened"
    # a page already served: its address opens again, Claude Code is not started a second time
    opened, real = [], (home.running, webbrowser.open)
    home.running, webbrowser.open = (lambda: "http://127.0.0.1:47821/?t=x"), opened.append
    try:
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            assert main(["--window-only"]) == 0   # Claude's side is checked below, with the terminal faked
        assert opened == ["http://127.0.0.1:47821/?t=x"] and "Already open at http://127.0.0.1:47821/" in o.getvalue()
        assert "t=x" not in o.getvalue(), "the token is not printed"
    finally:
        home.running, webbrowser.open = real
    # "Connect Claude": the start prompt and the narrow settings layer, one terminal at a time (recorded, never run)
    real_open, ran = open_claude, []
    open_claude = lambda f, p: real_open(f, p, "Darwin", run=lambda w, fo, o: ran.append(w) or True)
    try:
        st, text = connect(tmp)
        assert st == "opened" and len(ran) == 1 and text.endswith(shlex.quote(LISTEN)), (st, text)
        script = ran[0][2]   # osascript -e '<the Terminal script>'
        assert LISTEN in script and "--add-dir" in script and "session-settings.json" in script, script
        rules = json.loads(session_settings(write=False).read_text(encoding="utf-8"))["permissions"]["allow"]
        assert "Bash(ffmpeg *)" in rules and "Bash(*)" not in rules, rules
        os.environ["AI_EDITOR_HOME"] = str(tmp / "home")
        assert " && env " + shlex.quote(f"AI_EDITOR_HOME={tmp / 'home'}") + " " in open_claude(tmp, LISTEN)[1], "the new Claude uses the window's home"
        assert "dangerously" not in script and "bypass" not in script.lower(), "never bypass permissions"
        ran.clear()
        assert connect(tmp) == ("pending", "") and not ran, "no second terminal while one is pending"
        assert connect(tmp, now=time.time() + CONNECT_S + 1)[0] == "opened" and len(ran) == 1, "retry after the minute"
        home.update(lambda d: d.pop("connect", None))
        (home.home() / ".listening").write_text("sess-A", encoding="utf-8")
        ran.clear()
        assert connect(tmp) == ("listening", "") and not ran, "one is listening: nothing opens"
        # ai-editor with the window open: Claude only when nobody listens, never with --window-only
        home.running, webbrowser.open = (lambda: "http://127.0.0.1:47821/?t=x"), (lambda u: None)
        for args, listen, want, n in (([], True, "already listening", 0), (["--window-only"], False, None, 0),
                                       ([], False, "starting in a new Terminal", 1)):
            home.update(lambda d: d.pop("connect", None))
            (home.home() / ".listening").unlink(missing_ok=True)
            if listen:
                (home.home() / ".listening").write_text("sess-A", encoding="utf-8")
            ran.clear()
            o = io.StringIO()
            with contextlib.redirect_stdout(o):
                assert main(args) == 0
            assert len(ran) == n and (want in o.getvalue() if want else "Claude" not in o.getvalue()), (args, o.getvalue())
        o = io.StringIO()
        home.running = lambda: None
        with contextlib.redirect_stdout(o):
            assert main(["--window-only", "--dry-run"]) == 0
        assert o.getvalue().strip().endswith("home.py serve") and "--settings" not in o.getvalue(), o.getvalue()
        print("connect  ok: start prompt, narrow Allow rules, one at a time, --window-only")
    finally:
        open_claude, (home.running, webbrowser.open) = real_open, real
    shutil.rmtree(tmp, ignore_errors=True)
    print("launcher demo ok")


if __name__ == "__main__":
    if sys.argv[1:2] == ["demo"]:
        demo()
    else:
        sys.exit(main())
