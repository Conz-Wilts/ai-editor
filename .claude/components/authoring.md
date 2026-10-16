---
type: Reference
title: "Components: the motion-graphics library and how to add one"
description: "Every card the editor can draw is a component with a manifest; a user's own lives in <library>/components/<id>/."
---

# Components

Every card the editor can draw over the footage is a component: a manifest (`component.json`) that says
what it is, which props it takes and how plan.py treats it, plus the React code that draws it. The
built-ins are in this folder and point at the renderer's own code (`"entry": "builtin:Shot"`); a user's
own live in `<library>/components/<id>/` with their own `index.tsx`.

Who reads the manifests:

- `lib/ai_editor/components.py`: loads and validates them; `tuples()` gives plan.py its registry
  (which ids are overlays, which move, entrances, content aspects, fixed boxes...). `components.py demo`
  holds the built-ins to the lists plan.py used to spell out by hand.
- `remotion/scripts/gen-registry.mjs`: copies the user's components into `src/user-components/` and writes
  `src/registry.generated.ts` before every bundle (render.mjs and the preview build run it).
- The app: `GET /api/components` (the gallery) and `GET /api/components/preview?id=` (a still, made once
  per manifest version from the `example` props).

## The manifest

```json
{
  "id": "quote_badge",                 // the folder's name: [a-z][a-z0-9_-]{1,40}, never a built-in's
  "name": "Quote badge",
  "description": "One line for the gallery.",
  "kind": "overlay",                   // overlay | template | scene | alias | image-format
  "entry": "./index.tsx",              // builtin:<Export> for the built-ins
  "order": 100,                        // sort key (built-ins keep plan.py's old order)
  "aspects": ["9:16", "16:9"],         // the layout shapes it works in (4:5 and 1:1 plan as 9:16)
  "defaultDurationS": 2.5,
  "entrance": "pop",                   // pop | slide | fade | scale | null
  "floating": true,                    // drawn without a surface card under it
  "moving": false,                     // a card edit prefers moving cards over static captures
  "contentAspect": 3.0,                // width / height, picks the free region round the head; null: 1.6
  "fixedBox": false, "boxOk": false,   // keeps its own box / may sit as a box over the footage
  "imageFormat": false, "legacy": false, "scene": false, "splitFirst": false, "wantsPicture": false,
  "tags": ["quote"],
  "example": {"text": "Ship it today"},   // props for the gallery still (optional; no still without it)
  "propsSchema": { "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
                   "properties": {"text": {"type": "string"}}, "required": ["text"] }
}
```

`propsSchema` describes the props the code reads. The app's Inspector builds its form from it, and
`components.py props <id> '<json>'` checks a card against it (type, enum, required, items, minItems,
maxItems, additionalProperties). plan.py fills `word_at`, `enter`, `exit` and `ambient` on every card.

## The code

`index.tsx` default-exports a `React.FC<TP>` and imports only from `../../component-api` and its own
folder: `TP` is `{p, w, h, look, m, fonts, dur, id}`: its props, the card box in px, the design system's
Look, the motion personality, loaded fonts, the seconds it is up. Animate with one GSAP timeline through
`useTl` so the frame the renderer asks for is the frame you see (`dropIn`, `punch`, `exitUp`, `camera`
are there too). Colours and type come from `look` only, so the card follows the project's design
system. The sample is `tests/fixtures/components/quote_badge/`.

Check a new component:

```bash
python3 .claude/lib/ai_editor/components.py check "<library>/components"
node .claude/remotion/scripts/gen-registry.mjs          # prints the user components it found
```

Then drag it from the app's gallery onto the timeline, or name it in visuals.json as
`{"kind": "anim", "type": "<id>", "props": {...}}`.

## Design systems

A project's colours, type, corner radius, shadow and texture come from its design system: a W3C Design
Tokens file (DTCG Format Module 2025.10) in `.claude/design-systems/<id>/tokens.json` or
`<library>/design-systems/<id>/tokens.json`. See [the design-system reference](../design-systems/authoring.md).
