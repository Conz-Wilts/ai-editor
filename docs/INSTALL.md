---
type: Reference
title: Install ai-editor
description: Every step to set up ai-editor on Mac, Windows or Linux, written so Claude can run it.
---

# Install ai-editor

Claude can run every step here. Say **set up the editor** in Claude Code, opened in this folder, and the
`setup` skill does it, asking before anything that needs your password or money. Run the commands by
hand if you prefer; on Windows use `py` wherever it says `python3`.

## 1. Tools you need first

| Tool | Version | Check | Install |
|---|---|---|---|
| Claude Code | latest | `claude --version` | Mac/Linux: `curl -fsSL https://claude.ai/install.sh \| bash`. Windows: `irm https://claude.ai/install.ps1 \| iex` |
| Python | 3.10+ (3.11+ recommended) | `python3 --version` | Mac: `brew install python`. Windows: `winget install -e --id Python.Python.3.13`. Linux: `sudo apt install -y python3 python3-venv` |
| Node.js | 22+ (20 works except motion clips) | `node --version` | Mac: `brew install node@22`. Windows: `winget install -e --id OpenJS.NodeJS.LTS`. Linux: NodeSource 22.x |
| ffmpeg | 4.4+ | `ffmpeg -version` | Mac: `brew install ffmpeg`. Windows: `winget install -e --id Gyan.FFmpeg`. Linux: `sudo apt install -y ffmpeg` |
| git | any | `git --version` | Mac: Xcode tools. Windows: `winget install -e --id Git.Git`. Linux: `sudo apt install -y git` |
| GitHub CLI | 2.40+ | `gh --version` | Mac: `brew install gh`. Windows: `winget install -e --id GitHub.cli`. Linux: see cli.github.com |

`python3 .claude/skills/setup/scripts/setup.py doctor` prints one line per tool: `ok`, or `FIX` with the
exact command for this computer.

## 2. The editor's own install (one command)

```
python3 .claude/skills/setup/scripts/setup.py install-all --report
```

Safe to re-run. Everything lands in `~/.ai-video-editor/` (move it with `AI_EDITOR_HOME`), never in this
repo:

| Step | What | Size |
|---|---|---|
| `venv` | Python packages from the hashed lock `.claude/requirements/requirements.lock` (numpy, OpenCV, faster-whisper...) | ~500 MB |
| `model` | the free transcription model (faster-whisper small), sha256 checked | ~480 MB |
| `remotion` | the renderer: `.claude/remotion` copied to `~/.ai-video-editor/remotion`, then `npm ci` and Remotion's headless browser | ~1.9 GB |
| `motion` | HyperFrames CLI and GSAP for bespoke motion clips (needs Node 22) | ~130 MB |
| `warm` | pays the first edit's one-time costs | |
| `matte` | the person-cutout model for graphics behind the speaker | 15 MB |

Then put the `ai-editor` command on your PATH:

```
python3 .claude/skills/setup/scripts/setup.py install-launcher
```

## 3. Remotion (the renderer)

The renderer is a Remotion 4 project in `.claude/remotion/` (versions pinned in its `package-lock.json`).
`setup.py remotion` installs it; to do it by hand:

```
mkdir -p ~/.ai-video-editor/remotion
cp -r .claude/remotion/* ~/.ai-video-editor/remotion/
cd ~/.ai-video-editor/remotion && npm ci && npx remotion browser ensure
```

Licence: Remotion is free for individuals and companies of up to 3 people. A bigger company needs a
Remotion company licence (remotion.dev/license).

## 4. Rendering on GitHub Actions (free, encrypted)

Renders can run on this repo's GitHub Actions, free on a public repo. Your footage never leaves your
computer unencrypted: it is encrypted with `age` before upload, decrypted only inside the runner,
and the finished video comes back encrypted and is decrypted on your computer.

```
gh auth login                      # scopes: repo, workflow
python3 .claude/skills/setup/scripts/setup.py age              # installs age, pinned and checked
python3 .claude/skills/setup/scripts/setup.py gh-render-key    # makes the key, sets RENDER_KEY + RENDER_RECIPIENT
```

The private key stays in `~/.ai-video-editor/render-key.txt`. Then any edit renders with
`edit.py render edits/<name> --github` (the app's Render panel does the same). GitHub's terms ask that
Actions relate to the repo's software; renders use this repo's own renderer, but if you are unsure,
render on your laptop or Modal instead.

## 5. Optional keys

Never paste a key into the Claude chat. Each command asks for it in your own terminal and hides it.

| Key | For | Command |
|---|---|---|
| ElevenLabs | verbatim transcripts (every "um" and retake) | `setup.py setkey elevenlabs` |
| Higgsfield | AI generation on top of your footage (`id:secret`) | `python3 .claude/lib/ai_editor/gen/gen.py setkey` |
| Modal | fast cloud renders | `setup.py modal-connect` |
| AWS | Lambda renders on your own account | `setup.py awskey` |

Keys live in `~/.config/creator-teardown/.env` (or `$AI_EDITOR_HOME/.env`).

## 6. Open it

```
ai-editor
```

opens the editor in your browser with Claude Code behind it. Or open Claude Code in this folder, trust
it, and say **edit my video**.

## 7. Check the install

```
python3 tests/check_plugins.py                 # skills, agents, hooks, OKF bundle
PY=~/.ai-video-editor/venv/bin/python tests/demos.sh   # every script's self-check (Windows: venv/Scripts/python.exe)
```

## Windows notes

- Run the commands in Git Bash or PowerShell; Claude Code uses Git Bash for its shell.
- Some self-checks create symlinks; without Developer Mode they skip or fail that one case.
- A tool installed with `winget` is only found in a new terminal: close and reopen Claude Code.
