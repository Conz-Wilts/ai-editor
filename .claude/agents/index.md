# agents

# Documents

* [clip-builder](clip-builder.md) - Builds ONE bespoke motion clip for a style-edit beat (a HyperFrames + GSAP composition in edits/<name>/motion/<id>/) from the brief.md the motion skill's `motion.py pick` wrote, runs `motion.py check` (every gate and the render) up to 3 rounds, looks at the sheets, and returns a short JSON.
* [clip-editor](clip-editor.md) - Takes ONE trimmed clip folder (edits/<name>-clip<N>/ from `clips.py trim`) through the cut (spans, build, render, verify, cut page) and style-edit up to its stills sheet, without asking anything, and returns a short JSON summary.
* [cut-judge](cut-judge.md) - Grades ONE cut on paper against the cut skill's judge rubric (references/judge-rubric.md), writes the findings as JSON, has judge_cut.py apply them to spans.json, and loops until nothing is left to apply (2 rounds at most).
* [cut-reader](cut-reader.md) - Answers ONE reader or verifier prompt that read_cut.py wrote for a long take (edits/<name>/read/reader-N.md, or an optional verify-N.md) and writes the JSON answer beside it.
* [render-watcher](render-watcher.md) - Watches a long render (a local edit.py render, a Modal or Lambda render, or a GitHub Actions render run) in the background and reports when it finishes or fails.
* [stills-critic](stills-critic.md) - Reviews ONE contact sheet or still from a style-edit (stills/*.png) against a fixed checklist and returns a pass/fail list.
* [storyboard-critic](storyboard-critic.md) - Reviews ONE product-video animatic sheet (product/<name>/animatic-<tag>/sheet.png, start / middle / end of every beat with its job and words) against a fixed checklist and returns pass/fail with fixes in story.json terms.
* [template-filler](template-filler.md) - Fills the visuals.json beats of a style-edit from beats.json picks and the transcript: the overlay formats (capture shot, browser, sticker, post, logo, logo_cluster, chat, terminal, toasts, side_by_side, video_card, likes, progress, curve, notes) and the flow diagram.
* [video-analyst](video-analyst.md) - Turns ONE video of a creator teardown into a compact JSON beat map (labelled beats with second marks, word counts and WPM, the hook, the close, the graphics and the look notes) from the files the creator-teardown scripts already wrote.
* [visual-prep](visual-prep.md) - Prepares a style-edit's visuals while the user reviews the cut, so the stills sheet is ready the moment they approve.
