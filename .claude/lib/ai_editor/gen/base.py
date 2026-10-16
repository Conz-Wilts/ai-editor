"""What every generation provider offers, and the model catalog (models.json). Stdlib only.

A provider takes a Req (a model id plus its inputs and params, already in the provider's own names),
prices it first (estimate), then submits it, reports its status and downloads its outputs. Money is only
spent by submit, and gen.py only calls submit with an estimate the user confirmed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

CATALOG = Path(__file__).with_name("models.json")
TERMINAL = ("completed", "failed", "nsfw", "canceled")   # Higgsfield's terminal states; others are queued, in_progress


def catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def models():
    return catalog()["models"]


def model(mid):
    m = models().get(mid)
    if not m:
        raise SystemExit(f"Unknown model {mid!r}. Run: gen.py models")
    return m


@dataclass
class Req:
    """One generation. `body` is what the provider's model endpoint takes (input URLs already uploaded)."""
    model: str
    body: dict = field(default_factory=dict)


@dataclass
class Estimate:
    usd: float
    credits: float | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class Status:
    request_id: str
    status: str                                        # queued | in_progress | completed | failed | nsfw | canceled
    outputs: list = field(default_factory=list)         # [{"kind": "video"|"image"|"audio", "url": ...}]
    error: str | None = None

    @property
    def done(self):
        return self.status in TERMINAL


class Provider(Protocol):
    name: str

    def upload(self, path: Path, content_type: str) -> str: ...      # a public URL the model can read
    def estimate(self, req: Req) -> Estimate: ...
    def submit(self, req: Req) -> dict: ...                           # {"request_id", "status", ...}
    def status(self, request_id: str) -> Status: ...
    def fetch(self, url: str, dest: Path) -> Path: ...
    def cancel(self, request_id: str) -> bool: ...


def build_body(mid, prompt=None, negative_prompt=None, video_url=None, image_urls=(), params=None):
    """The model's request body from the catalog: inputs mapped by their "from", params checked against
    their enum or range and defaulted. Raises SystemExit naming what is missing or out of range."""
    m, params = model(mid), dict(params or {})
    src = {"prompt": prompt, "negative_prompt": negative_prompt, "video": video_url,
           "image": image_urls[0] if image_urls else None, "images": list(image_urls) or None}
    body = {}
    for name, spec in m["inputs"].items():
        v = src.get(spec["from"])
        if v in (None, "", []):
            if spec.get("required"):
                raise SystemExit(f"{mid} needs {spec['from']} ({name})")
            continue
        if isinstance(v, list) and not spec.get("min", 1) <= len(v) <= spec.get("max", len(v)):
            raise SystemExit(f"{mid}: {name} takes {spec.get('min', 1)}-{spec['max']} items, got {len(v)}")
        if isinstance(v, str) and len(v) > spec.get("max_chars", 10 ** 9):
            raise SystemExit(f"{mid}: {name} is over {spec['max_chars']} characters")
        body[name] = v
    for name, spec in m.get("params", {}).items():
        v = params.pop(name, spec.get("default"))
        if v is None:
            continue
        if "enum" in spec and v not in spec["enum"]:
            raise SystemExit(f"{mid}: {name} must be one of {spec['enum']}, got {v!r}")
        if "min" in spec and not spec["min"] <= v <= spec["max"]:
            raise SystemExit(f"{mid}: {name} must be {spec['min']}-{spec['max']}, got {v!r}")
        body[name] = v
    if params:
        raise SystemExit(f"{mid} has no params {sorted(params)}; it takes {sorted(m.get('params', {}))}")
    return body
