---
type: Skill
name: update
description: Updates ai-editor to its newest version with git. Works out whether this checkout is a plain clone or a fork. A fork the user owns (the power-user route, where they change the editor's own code) gets its new versions pulled from Conz-Wilts/ai-editor and merged with their changes kept, after a backup branch, then the fast self-checks, with a rollback if they fail. A plain clone gets the fork route in three steps. Use when the user says "update the editor", "get the latest version", "sync my fork", "pull the new version", or asks how to stay up to date after changing the editor's code. Not for changing a style or a setting (that is taste or the home page), and not for maintainers turning feedback into fixes (that is improve).
license: MIT
compatibility: Python 3.9+, standard library only, and git. Fork updates run in the user's git checkout of their fork; the self-checks need bash (Git Bash on Windows).
---

# Update

Paths: `${CLAUDE_SKILL_DIR}` means the folder containing this SKILL.md, and `${CLAUDE_SKILL_DIR}/../..` the editor's `.claude/` folder two levels above it.

Every question goes in the question box: the AskUserQuestion tool (2-4 options, recommended first). Only in an agent without it, ask numbered questions in text.

`U="${CLAUDE_SKILL_DIR}/scripts/update.py"`. Run it with `python3` on Mac and Linux, `py` on Windows.
Add `--repo <folder>` when the user's clone is not the folder Claude Code runs in.

Never push, never force-push, never delete a branch, never stash or reset the user's uncommitted
work. Pushing to their fork happens only when they ask for it.

## 1. Which checkout

```bash
python3 "$U" where
```

The editor is a git checkout of the repo: skills, agents and code in `.claude/`, which Claude Code loads
itself (no plugin, no marketplace). Their styles, skills and settings live in their own folder and survive
an update (docs/customise.md).

- **not a git checkout**: ask for the folder of their clone, then use `--repo`. With none, say to download
  the new version from GitHub. Stop here.
- **plain clone**: say the three fork steps it prints (or `git pull` for a clone with no changes). Stop here.
- **a fork, run outside its clone**: ask for the folder of their clone, then use `--repo`.
- **fork, upstream missing**: ask "Add Conz-Wilts/ai-editor as `upstream` so updates
  can come from it?" (**Yes, add it (Recommended)** / **No**). On yes: `python3 "$U" add-upstream`.

## 2. Check

```bash
python3 "$U" check
```

Tell the user in a few lines: how many new commits, the CHANGELOG lines they bring (plain words, the
ones they would notice), and which of their changed files the update also touches. Then ask
**Update now (Recommended)** / **Not now**.

When it prints `layout:`, say it plainly first: upstream still ships the editor as two Claude Code plugins
under `plugins/`, and this copy moved everything into `.claude/`. The merge follows renamed files where git
can match them, but expect many conflicts, each the same file in its old and new place. Resolving one means
taking upstream's change into the `.claude/` copy and deleting the `plugins/` one; the rest by hand. Ask
**Merge anyway and resolve the conflicts (Recommended)** / **Not now**.

## 3. Merge

```bash
python3 "$U" merge
```

- Exit 2, uncommitted changes: show what it printed. Ask **Commit them as "my changes"
  (Recommended)** / **I'll handle it myself**. Commit only on a yes, then merge again. Never stash.
- Exit 0: go to step 4.
- Exit 3, conflicts: resolve them file by file. For each file, keep the user's change and take
  upstream's fix, and say what you did in one line ("captions.tsx: kept your font, took the new
  safe-zone fix"). When the two really clash and the choice is theirs (both changed the same
  setting to different values), ask in the question box with each side as an option, theirs first.
  Then `git add` each file and `git commit --no-edit`.

The backup branch is `before-update-<date>`; say its name once.

## 4. Verify

```bash
python3 "$U" verify
```

It runs `tests/check_plugins.py` and `tests/demos.sh`. Pass: tell them to start a new Claude Code
session to load the new version (and that pushing the branch to their fork on GitHub keeps it there, when
they want). Fail: show the failing
checks and ask **Fix them (Recommended)** / **Go back to before the update**. Going back:

```bash
python3 "$U" rollback
```

It aborts an unfinished merge or moves the branch back to the backup. No branch is deleted.
