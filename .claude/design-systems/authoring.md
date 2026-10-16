---
type: Reference
title: "Design systems: tokens files and how to add one"
description: "A design system is a W3C Design Tokens (DTCG 2025.10) file that design.py compiles to the renderer's Look."
---

# Design systems

A design system sets every card's colours, type, corner radius, shadow and texture. It is a W3C Design
Tokens file (DTCG Format Module 2025.10, https://www.designtokens.org/tr/2025.10/format/):

- built-ins: `.claude/design-systems/<id>/tokens.json`, one per look.tsx preset (neutral, editorial,
  editorial-dark, poster-red, poster-green, poster-blue, mono, glass). `design.py port` rewrites them
  from look.tsx; `design.py demo` fails if one drifts.
- the user's own: `<library>/design-systems/<id>/tokens.json`. `brand` is made from the profile's brand
  kit by `design.py brand`.

`lib/ai_editor/design.py compile(<id>)` turns a file into the renderer's Look (the keys of `Look` in
`remotion/src/look.tsx`). The renderer never parses tokens: the project's `designSystem` is compiled into
plan.json's `look` when the project is exported (`project_convert.to_plan`). In the app the picker sends
`setProject {"designSystem": "<id>"}` and the preview takes the compiled Look from
`GET /api/design-systems/look?id=`.

## The file

| tokens | `$type` | Look key |
|---|---|---|
| `color.ground`, `ink`, `muted`, `accent`, `accentInk`, `line`, `mark`, `ring` | color (`{colorSpace: "srgb", components: [r, g, b] 0-1, alpha, hex}`) | ground, ink, muted, accent, accent_ink, line, mark, ring |
| `typography.body.fontFamily`, `.fontWeight` | fontFamily, fontWeight | font, weight |
| `typography.display.fontFamily`, `.fontWeight`, `.letterSpacing` | fontFamily, fontWeight, number (em) | font_display, weight_display, tracking |
| `typography.serif.fontFamily` | fontFamily (`[]` for none) | font_serif |
| `radius.card` | number (% of the card's short side) | radius |
| `shadow.card` | shadow, `$extensions["ai-editor"].style` none / soft / hard | shadow |

What DTCG has no type for sits in the root's `$extensions["ai-editor"]`: `id`, `name`, `preset` (the
look.tsx preset its rules follow), `extends` (another design system it overrides: a file may then set
only the tokens it changes), `surface` (none / card / glass), `case` (as_is / lower / upper), `texture`
(none / grain / paper / print), `textureAmount` (0-1), `decor` (none / blocks), `motion` (a personality:
snappy / smooth / punchy / calm). Fonts are Google Fonts names.

A minimal one:

```json
{
  "$extensions": {"ai-editor": {"name": "Ocean", "extends": "neutral", "motion": "calm"}},
  "color": {"$type": "color", "accent": {"$value": {"colorSpace": "srgb", "components": [0.04, 0.42, 1], "alpha": 1, "hex": "#0A6CFF"}}},
  "typography": {"display": {"fontFamily": {"$type": "fontFamily", "$value": "Fraunces"}}}
}
```

Check it with `python3 .claude/lib/ai_editor/design.py check <file>` and see the result with
`design.py show <id>`. The anti-AI-look rules (style-edit `references/ai-tells.md`) apply to a design
system like any look: no purple-blue gradients, no default grotesk display face.
