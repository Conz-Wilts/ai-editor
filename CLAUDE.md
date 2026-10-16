# ai-editor

Most people who open this folder want to edit a video. When the user asks for an edit, drops a
video, pastes a link, names a creator, or asks how to start, use the `start` skill. It asks its own
questions and runs setup, the creator breakdown, the cut and the styled edit in order.

The editor is this folder's `.claude/`: Claude Code loads its skills (`.claude/skills/`), agents
(`.claude/agents/`) and hooks (`.claude/settings.json`) directly. There is no plugin to install. If
`start` is not in your skill list, the folder is not trusted yet: tell the user to restart Claude Code
here and pick **Yes, I trust this folder**.

## The knowledge bundle

`.claude/` is an Open Knowledge Format (OKF v0.2) bundle. To find a skill, agent or reference, read
`.claude/index.md`, then the `index.md` of the folder you need, rather than searching the tree. Every
document's frontmatter has a `type` (Skill, Agent, Reference, Principles) and a `description`.

## Working on this repo

If the user is changing this repo itself (skills, scripts, tests, docs), follow these rules,
`docs/BACKLOG.md` and the `improve` skill.

- Never ask the user to paste an API key into the chat. Keys are saved with the commands the
  skills give, in the user's own terminal.
- Ask before creating a GitHub repo or spending money on AWS.
- Keep the layout: the skills share code in `.claude/lib/` and the renderer in `.claude/remotion/`.
- After adding, moving or renaming a document under `.claude/`, run
  `python3 .claude/lib/ai_editor/okf.py stamp` and `python3 .claude/lib/ai_editor/okf.py index`,
  and add a dated line to `.claude/log.md`.
- Self-checks: `python3 tests/check_plugins.py` (it includes `okf.py check`) and `tests/demos.sh`
  (every script's `demo`).
- The rules every video follows: `.claude/PRINCIPLES.md`.
