"""Generation on top of the user's footage: providers (Higgsfield today), the model catalog, the job queue.

    from ai_editor.gen import base, higgsfield, jobs
    base.models()                      # gen/models.json "models"
    p = higgsfield.Higgsfield()        # key from keys.get("higgsfield")

The CLI is gen.py beside this file; the generate skill drives it.
"""
