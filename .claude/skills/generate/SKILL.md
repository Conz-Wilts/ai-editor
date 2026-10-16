---
type: Skill
name: generate
description: Generates new footage with Higgsfield and puts it on the edit's timeline. Prices every generation first, asks the user with the dollar amount (and, for their own footage, whether it may be uploaded to Higgsfield), then submits, waits, downloads into the edit's generated/ folder and adds the result to the timeline's Generated track. Covers motion transfer on a clip of the user's video (their moves onto a character or styled look), b-roll from a sentence (text to video), a still brought to life (image to video) and stills for cards (text to image). Use when the user says "generate b-roll", "make a shot of", "AI b-roll", "generate a clip", "use Higgsfield", "motion transfer", "put my moves on", "restyle this part with AI", or asks for footage they did not film. Not for animated diagrams or motion graphics (motion), not for real screenshots and logos (overlays, logo-pack), and not for the cut (cut).
license: MIT
compatibility: Python 3.9+ (standard library), ffmpeg and ffprobe for clips. A Higgsfield API key (console.higgsfield.ai) with credit; every generation is paid and priced first. Runs from this repo's `.claude/` folder (uses its lib/).
---

# Generate

Paths: `${CLAUDE_SKILL_DIR}` means the folder containing this SKILL.md, and `${CLAUDE_SKILL_DIR}/../..` the editor folder (this repo's `.claude/`) two levels above it.

Every question to the user goes in the question box: call the AskUserQuestion tool (2-4 options, the recommended one first). Only in an agent without that tool, ask numbered questions in text.

`G="${CLAUDE_SKILL_DIR}/../../lib/ai_editor/gen/gen.py"`. Run it with `python3` (`py` on Windows). Every
model, its inputs and limits are in `gen.py models` (from `lib/ai_editor/gen/models.json`); never guess a model
id or a parameter. API facts and what is unverified: `references/higgsfield-api.md`.

## Rules

- **Money is spent only after a yes to that price.** Always `estimate` first, ask with the dollar amount it
  printed (its `ASK:` line), and run `submit --confirm <estimate id>` only after the user picked yes. A new
  price (the estimate is over 30 minutes old, or `submit` says the price changed) is a new question.
- **The user's footage leaves their computer only with consent.** A clip or a frame of their video is uploaded
  to Higgsfield at `submit`. Say so in the same question as the price.
- **Never ask for the key in the chat.** No key: tell them to run `python3 "$G" setkey` in their own terminal
  (it asks for the key id and secret from console.higgsfield.ai, joined as `id:secret`, and hides what they type).
- `profile.json` `gen_budget_usd` caps a month's spend; `submit` refuses over it. Say what is left and stop.
- Failed and `nsfw` results are not billed. Say so if one fails, and offer to change the prompt.

## Steps

1. **What and where.** From the user's words and the edit (`edits/<name>/`): the kind (motion transfer, b-roll
   from words, a still brought to life, a still for a card), the moment it covers (seconds on the timeline,
   from the transcript in `words.json`), and for motion transfer the stretch of their video (4 s or more; the
   model keeps at most 30 s). Pick the model with `python3 "$G" models --kind <kind>`.
2. **The prompt.** Write it yourself from the line being said: the subject, the setting, the camera, the light,
   in under 40 words. B-roll matches the video's format (a vertical edit gets a vertical-feeling shot).
   Motion transfer takes 1-8 reference images (`--image`, files or URLs): the look to put the moves on.
3. **Price it.**
   ```bash
   python3 "$G" estimate edits/<name> --model <id> --prompt "<prompt>" [--video raw.mp4 --from 12.0 --to 18.0] \
     [--image ref.png] [--param duration=5] --at <timeline seconds>
   ```
   It cuts the clip (silent, H.264) into `generated/inputs/`, prices the request without uploading anything,
   and prints the estimate id, `usd`, `credits`, `over_budget` and an `ASK:` line.
4. **Ask.** One question box: the `ASK:` line as the question (price, model, and what gets uploaded), options
   "Yes, generate it (Recommended)" / "Change the prompt" / "No". Over budget: say so instead and stop.
5. **Submit** on yes only: `python3 "$G" submit edits/<name> --confirm <estimate id>`. It uploads the inputs,
   re-prices with them, submits and prints the job id.
6. **Wait** in the background (generations take minutes): `python3 "$G" wait edits/<name> <job>`. It polls
   with backoff, downloads the result into `edits/<name>/generated/`, probes it and adds it to the timeline's
   Generated track at `--at` as Claude's change (through `project.py apply`; without the project document yet,
   it writes `generated/<job>.ops.json` and prints it). `status` / `list` show progress; `cancel` works only
   while it is still queued.
7. **Hand over.** Say what was added, where, and what it cost. The user moves, trims or deletes it on the
   timeline like any clip. A correction to how generations should look goes to `taste`.

## If a command stops

| message | do |
|---|---|
| `No Higgsfield key` | ask them to run `python3 "$G" setkey` in their own terminal, then continue |
| `needs at least 4 s` | widen `--from`/`--to`, or pick a text or image model |
| `over this month's generation budget` | tell them what is left; they can raise `gen_budget_usd` |
| `the price is $X, not $Y` | ask again with the new price, then `submit --confirm` the new id it printed |
| `Maximum number of concurrent requests` | the client already retried; wait for a running job, then submit |
| `ended failed` / `ended nsfw` | not billed; offer a changed prompt (a new estimate and question) |

## Files

- `lib/ai_editor/gen/gen.py`: the commands above, `demo` self-check (a fake Higgsfield, no network).
- `lib/ai_editor/gen/higgsfield.py`: the API client. `base.py`: the provider interface and catalog.
- `lib/ai_editor/gen/jobs.py`: `edits/<name>/generated/jobs.json` and the month's spend.
- `references/higgsfield-api.md`: the API as documented, with sources.
