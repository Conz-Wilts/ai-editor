---
type: Reference
title: ai-editor architecture
description: What every folder holds, how an edit flows from raw footage to a render, and how the app and Claude share one project.
---

# ai-editor architecture

ai-editor is a video editor that Claude Code drives. Claude does the judgement (what to cut, what to show,
when); code does every measurement and the render; a browser app lets you see and change everything on a
timeline. Claude and the app edit the same project document through the same commands.

## The flow of one edit

```
raw takes ──► cut skill ──► words.json, decisions.json, cut.mp4
                               │
                               ▼
style.json ─► style-edit (route.py, plan.py) ──► plan.json ──► project.py sync ──► project.json
                                                                                     ▲      │
                       the app (timeline, inspector, gallery) ── /api/commands ──────┘      │
                       Claude (project.py apply, the overlays skill) ──────────────────────┘
                                                                                            │
                                         project.py export --format <id> ◄──────────────────┘
                                                      │
                                                      ▼
                                       plan[-<format>].json ──► edit.py render
                                                      ├─ laptop (render.mjs local / chunks)
                                                      ├─ GitHub Actions (ghrender.py, encrypted)
                                                      ├─ Modal
                                                      └─ AWS Lambda
```

- `plan.json` is what the renderer reads; `project.json` is what people and Claude edit. `project.py sync`
  folds a fresh plan into the project without losing anything someone moved by hand (items keep stable ids;
  pinned items are never overwritten). `project.py export` writes the plan back for one format.
- Every change is a **command batch** (`add`, `move`, `trim`, `split`, `delete`, `update`, `addTrack`,
  `updateTrack`, `setProject`, `addAsset`) with an author (`user` or `claude`) and a base revision. Each
  apply stores its inverse, so undo and redo work for both authors. Claude can also **propose** a batch,
  which waits in `proposals/` for the user's Accept or Reject in the app.

## Repository layout

| Path | What it holds |
|---|---|
| `CLAUDE.md` | What Claude reads first in this folder: route edit requests to the `start` skill, how to navigate the knowledge bundle, rules for changing the repo. |
| `README.md` | What the editor does and how to use it. |
| `docs/INSTALL.md` | Every install step, written so Claude can run it. |
| `docs/ARCHITECTURE.md` | This file. |
| `docs/customise.md` | Where a user's own changes live so updates never touch them. |
| `docs/BACKLOG.md` | What to build next, ranked. |
| `docs/CONTRACTS.md` | Pointer to the file shapes the skills hand each other. |
| `docs/feedback-matrix.md` | Each rule in PRINCIPLES.md, what enforces it and what tests it. |
| `.claude/` | The whole editor, an Open Knowledge Format bundle (below). Claude Code loads its skills, agents and hooks directly. |
| `.github/workflows/render.yml` | The encrypted render on GitHub Actions: plan, a matrix of chunk renders, join. |
| `.github/scripts/` | `chunks.py` (frame ranges), `join.py` (sample-exact audio join), `install-age.sh` (pinned age). |
| `tests/` | `check_plugins.py` (structure, OKF, hooks), `demos.sh` (every script's self-check), `golden.py` (render regression), `test_app.mjs` (headless app smoke test), `check_ops.py` + `test_ops.mjs` (Python and TypeScript command parity), `evals/` (model behaviour cases), `fixtures/`. |
| `LICENSE`, `THIRD_PARTY_NOTICES.md` | The licences this code is distributed under. |

## `.claude/`: the editor

`.claude/` is an Open Knowledge Format (OKF v0.2) bundle: every markdown file has YAML frontmatter with a
`type` (Skill, Agent, Reference, Principles), every folder has an `index.md` listing what is inside, and
`log.md` records changes. Start reading at `.claude/index.md`. `lib/ai_editor/okf.py` stamps, indexes and
checks the bundle.

| Path | What it holds |
|---|---|
| `settings.json` | Hooks: the setup check at session start, questions shown in the app, Stop, skills used per video. |
| `PRINCIPLES.md` | The rules every video follows (asking, looking real, motion, framing, privacy, cost). |
| `skills/` | One folder per skill (below). Each has `SKILL.md`, optional `references/` and `scripts/`. |
| `agents/` | Subagents the skills launch in parallel: `clip-editor`, `cut-judge`, `cut-reader`, `visual-prep`, `stills-critic`, `storyboard-critic`, `template-filler`, `clip-builder`, `render-watcher`, `video-analyst`. |
| `app/` | The browser app: `index.html`, `build.mjs` (esbuild), `src/` (React). Built into `app/dist/` on first open. |
| `remotion/` | The renderer: a Remotion 4 project. `src/StyleEdit.tsx` (the one composition), `Footage.tsx` (timeline clips, reframe), `Captions.tsx`, `Overlays.tsx`, `Templates.tsx`, `Anims.tsx`, `look.tsx` (the Look type), `formats.json`/`formats.tsx`, `registry.generated.ts`, `product/` (product videos). `render.mjs` renders stills, chunks, whole videos and Lambda jobs. `scripts/gen-registry.mjs` adds user components. |
| `components/` | The motion-graphics component library: one folder per component with `component.json` (props schema, aspects, timing, flags). `authoring.md` explains writing your own. |
| `design-systems/` | Design systems as W3C design tokens (DTCG 2025.10): `neutral`, `editorial`, `editorial-dark`, `poster-*`, `mono`, `glass`. `authoring.md` explains writing your own. |
| `lib/ai_editor/` | Shared Python (below). |
| `preview/` | The older single-edit live preview (`preview.py`), kept for card-by-card fixes. |
| `presets/` | Caption presets and the sample styles (style settings only; no footage ships). |
| `requirements/` | `requirements.in` and the hashed `requirements.lock` for the venv. |

### Skills

| Skill | Does |
|---|---|
| `start` | The front door: a few questions once, then setup, creator breakdown, cut and styled edit in order. |
| `setup` | Installs and checks every tool; keys; the launcher; GitHub render key; Modal and Lambda. |
| `cut` | Transcribes and cuts retakes, false starts, fillers and pauses; the user approves on the review page. |
| `style-edit` | Captions, zooms and visuals in a measured style; stills for approval; render; NLE export. |
| `overlays` | Changes one beat of a rendered edit (move, swap, add a card) and patch-renders. |
| `motion` | Bespoke HyperFrames + GSAP motion clips, one per beat, built by parallel agents and gated. |
| `motion-design` | Motion design reference (timing, easing, choreography). Vendored, MIT. |
| `generate` | Higgsfield generation on top of footage: price first, the user says yes, then spend; results land on the Generated track. |
| `clips` | Long video or podcast to the best 3-5 short clips, each cut and styled. |
| `product-video` | Website URL to a launch or demo film with real recorded click-throughs and its own score. |
| `creator-teardown` | Measures a creator's format from their videos and writes the `style.json` the editor follows. |
| `logo-pack` | Official brand logos for everything named in a video. |
| `taste` | Remembers every correction so it is never given twice. |
| `skill-improver` | Turns a finished video's notes into lasting rules in its style or skill. |
| `skill-maker` | Helps the user build their own editing skill. |
| `update` | Pulls new versions of this repo with git, keeping the user's changes. |
| `improve` | For maintainers: turns feedback into rules, checks and tests here. |

### `lib/ai_editor/` modules

| Module | Role |
|---|---|
| `home.py`, `home.html` | The local server (stdlib, port 47821, token cookie) and the original home page; hands jobs to Claude (`home.py wait`). |
| `app_api.py`, `app_render.py`, `catalog_api.py` | The app's HTTP API: projects, commands, events long-poll, undo/redo, proposals, media with byte ranges, uploads, plans, formats, component gallery, design systems. |
| `project_schema.py`, `project_store.py`, `project_convert.py` | The project document, its command layer (locking, revisions, undo, proposals) and plan.json conversion. |
| `formats.py` | Output formats from `remotion/src/formats.json`: sizes, platform safe zones, keep-outs, export settings. |
| `components.py`, `design.py` | Component manifests (and the tuples plan.py derives from them); design tokens compiled to a Look. |
| `reframe.py` | Face-following crop keyframes for reframing landscape footage to portrait. |
| `ghrender.py` | Encrypted GitHub Actions render: bundle, encrypt, draft release, dispatch, watch, download, decrypt, clean up. |
| `gen/` | Generation providers (`higgsfield.py`), model catalog (`models.json`), job queue and spend ledger (`jobs.py`), CLI (`gen.py`). |
| `review.py`, `review.html` | The review page after every render: notes at moments, transcript cut editing, rounds. |
| `launcher.py` | The `ai-editor` command: opens the app with Claude Code behind it. |
| `askhook.py`, `ask.js`, `toolhook.py`, `live.py`, `progress.py` | Claude's questions in the browser, Stop and skills-used tracking, live reload, progress on the page. |
| `keys.py`, `fslock.py`, `httpfile.py`, `net.py`, `run.py`, `models.py`, `lock.py` | Key store, file locks, range-capable file serving, secure HTTP, venv runner, pinned model downloads, pinned requirement subsets. |
| `library.py`, `profile.py`, `taste.py`, `styleskill.py`, `skillrules.py`, `custom.py`, `presets.py`, `thumbs.py`, `assets.py`, `links.py` | The user's library, profile, taste rules, style skills, custom layer, style presets and pictures, per-video assets, link routing. |
| `okf.py` | The Open Knowledge Format tooling for `.claude/`. |

## Formats

`remotion/src/formats.json` is the single source of truth for output formats; Python reads it through
`formats.py`, TypeScript through `formats.tsx`.

| id | Canvas | Safe zone (px: left, top, right, bottom) | Notes |
|---|---|---|---|
| `vertical` | 1080×1920 | today's measured reels zone | default, unchanged behaviour |
| `shorts` | 1080×1920 | 48, 288, 192, 672 | |
| `tiktok` | 1080×1920 | 120, 240, 120, 660 | right-side button column keep-out |
| `reels` | 1080×1920 | 65, 269, 65, 672 | 1080×1350 feed crop |
| `vertical-all` | 1080×1920 | 120, 288, 192, 672 | strictest of the three |
| `youtube` | 1920×1080 | 3%, 5%, 3%, 10% | |
| `youtube-4k` | 3840×2160 | as youtube | |
| `ig-4x5` | 1080×1350 | 54, 68, 54, 68 | |
| `square` | 1080×1080 | 54, 54, 54, 54 | |

Every format exports H.264 High, yuv420p, BT.709, AAC 48 kHz. `project.py export --format youtube --format
shorts` writes one plan per format from one project; boxes stored in safe-zone units reflow, and `fit:
reframe` follows the face when landscape footage goes portrait.

## The render security model (GitHub Actions)

The repo is public, so nothing readable may leave your computer:

1. `render.mjs bundle` packs the composition, media and user components; with `plan.json` and `meta.json`
   it is tarred and encrypted with `age` to the repo's public recipient (`RENDER_RECIPIENT`).
2. The ciphertext goes up as a **draft** release `render-<random id>` (no tag, not listed).
3. `render.yml` (dispatched with only the id, frame count, fps and format) decrypts inside each runner with
   the `RENDER_KEY` secret, renders its chunk, and encrypts the chunk before uploading it as an artifact.
4. The join job decrypts the chunks, joins them, encrypts the result and uploads it.
5. Your computer downloads and decrypts the video, then deletes the draft release and the artifacts.

Only people with write access can dispatch the workflow, and forks never receive the secret. File names
carry only the random id; the plan is never printed in logs.

## Where your data lives (never in this repo)

| Path | What |
|---|---|
| `~/Movies/AI Editor` (Mac) or `~/Videos/AI Editor` | The library: `videos/`, `edits/<name>/` (project.json, plan.json, renders), `clips/`, `product/`, `creator-teardowns/`, `custom/`, `components/`, `design-systems/`. |
| `~/.ai-video-editor/` | venv, models, the installed renderer, `profile.json`, `taste.md`/`taste.json`, `render-key.txt`, `bin/age`, the home server's state. |
| `~/.config/creator-teardown/.env` | API keys (or `$AI_EDITOR_HOME/.env`). |

## Tests

- `python3 tests/check_plugins.py`: skill and agent frontmatter, hooks, contracts copies, OKF conformance.
- `tests/demos.sh`: every script's stdlib `demo` self-check (run with the venv's Python).
- `node tests/test_app.mjs`: opens the app headless, drops a video, edits, undoes, checks a Claude edit
  arrives live and that media seeks.
- `tests/check_ops.py` and `node tests/test_ops.mjs`: the same command cases through Python and TypeScript.
- `tests/golden.py`: renders reference stills and compares them per OS.
- `tests/run_evals.sh`: model-behaviour evals (cost money).
