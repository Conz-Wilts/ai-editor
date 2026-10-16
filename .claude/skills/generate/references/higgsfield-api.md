---
type: Reference
title: "Higgsfield API: what the client relies on"
description: "The Higgsfield endpoints, auth, request lifecycle, uploads, pricing and models gen.py uses, each with its source, and what is not verified."
---

# Higgsfield API: what the client relies on

Read from docs.higgsfield.ai on 2026-10-17. `gen/higgsfield.py` implements exactly this; `gen/models.json`
holds the models. Re-check the sources before changing either.

## Verified

| Fact | Source |
|---|---|
| Base URL `https://api.higgsfield.ai` (OpenAPI `servers`, "Higgsfield API" 2.0.0) | https://docs.higgsfield.ai/docs/openapi.json |
| Auth header `Authorization: Key <key id>:<key secret>`; keys from the console | https://docs.higgsfield.ai/docs |
| Submit: `POST /<model id>` with the model's JSON inputs; answer `{status: "queued", request_id, status_url, cancel_url}` | https://docs.higgsfield.ai/docs |
| Status: `GET /requests/<id>/status`; 401 bad credentials, 404 unknown request, both `{detail}` | https://docs.higgsfield.ai/docs/api-reference/requests/get-request-status.md |
| States: `queued`, `in_progress` (no longer cancelable), `completed`, `failed` (may carry `error`), `nsfw`, `canceled` | https://docs.higgsfield.ai/docs/concepts/requests |
| Outputs on completion: `images[].url`, `video.url`, `audio.url`, `audios[].url` | same |
| Cancel: `POST /requests/<id>/cancel`, 202 empty while queued, 400 once processing started | same |
| Upload: `POST /files/generate-upload-url {content_type}` -> `{upload_url, upload_headers, public_url, content_type}`; `PUT` the bytes with every `upload_headers` entry and no API key; pass `public_url` as the input; the URL expires in 1 h | https://docs.higgsfield.ai/docs/concepts/file-uploads |
| Upload types: JPEG, PNG, WebP, GIF, WAV, MP4 | same |
| Estimate: `POST /estimate/<model>` with the same parameters as the submit -> `credits` and `usd` | https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md |
| Only successful generations are billed; `failed` and `nsfw` refund reserved credits; a cancel refunds only before processing starts | same |
| Outputs are kept at least 7 days: download them (gen.py does) | same |
| Concurrency over the account's limit: `400` "Maximum number of concurrent requests (N) has been reached"; no `Retry-After` or rate-limit headers; back off with jitter | https://docs.higgsfield.ai/docs/concepts/rate-limits.md |
| Webhook: the `hf_webhook` query parameter, `POST` of `{request_id, status, error, payload}` (not used: the editor runs on localhost, so it polls) | https://docs.higgsfield.ai/docs/how-to/webhooks.md |
| Motion transfer `higgsfield/genjutsu/motion-transfer/v1.0`: `video_url` (required), `image_urls` 1-8 (required), `prompt` up to 10,000 chars, `resolution` 480p/720p/1080p (default 720p); source at least 4 s, trimmed to 30 s | https://docs.higgsfield.ai/docs/models/genjutsu/motion-transfer |
| Kling 2.5 Turbo Pro text/image to video, Kling 2.5 Turbo Standard image to video: `prompt`, `duration` 5 or 10, `cfg_scale` 0-1 (0.5), `negative_prompt`, `image_url` for image to video | https://docs.higgsfield.ai/docs/openapi.json |
| Hailuo 2.3 Standard text/image to video: `prompt`, `duration` 6 or 10, `prompt_optimizer` (true) | same |
| Soul standard (text to image): `prompt`, `num_images` 1-4, `resolution` 2K/4K, `aspect_ratio` (1:1 ... 9:16, 21:9) | same |

## Not verified

- **Whether `/estimate/<model>` needs the real input URLs.** gen.py prices a not-yet-uploaded file with a
  placeholder URL (so nothing leaves the computer before the user agrees), then re-prices with the uploaded URLs at
  `submit` and refuses when the price rose more than 5%. If the estimate turns out to read the media, the first
  price could be wrong; the second check still stops a surprise.
- **The exact estimate response shape** beyond `credits` and `usd` (the docs' sample values are illustrative).
- **Upload size limits** (not documented). Clips are cut to the model's limit before upload, which keeps them small.
- **Prices per model**: always read from the estimate, never from this file or models.json.
- **More models**: the docs index says to discover models in the console; models.json lists only the ones whose
  inputs are documented in the OpenAPI file or a model page. Add a model there with its source when it is.
- Higgsfield's consumer features (Speak, lipsync, upscale, effects) are not in the API documentation.
