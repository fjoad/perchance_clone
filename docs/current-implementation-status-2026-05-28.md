# Current Implementation Status - 2026-05-28

> **Update 2026-06-11:** real token streaming, live A1111 progress, warmup
> retry/sticky readiness, and cold-boot status fixes landed after this note.
> See [streaming-ux-update-2026-06-11.md](streaming-ux-update-2026-06-11.md).

This note captures the current safe baseline after the BSOD recovery and guarded real-flow validation.

## Product Target

Build a local-first illustrated visual-novel companion app:

- Text streams quickly from a local roleplay-capable model.
- The assistant writes immersive VN-style prose.
- After the text reply, the app composes an image prompt.
- A1111 renders a matching SDXL image locally.
- Everything stays offline and on `F:`.

## Current Best Runtime

- Text backend: Ollama `0.21.0`
- Ollama executable: `F:\Programs\Ollama_0.21.0\ollama.exe`
- Ollama models: `F:\ollama\models`
- Text model: `hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M`
- Image backend: A1111 API
- A1111 root: `F:\projects\a1111\stable-diffusion-webui`
- Image checkpoint: `novaAnimeXL_ilV120.safetensors`
- Default image preset: `640x640 -> 1280x1280`
- Speed preset: `512x512 -> 1024x1024`

## Default Cast

- `sample-companion` / Astra Vale: original flagship sample character, not from a canon media property.
- `atago` / Atago: Azur Lane.
- `echidna` / Echidna: Re:Zero, with explicit visual anchors to avoid the earlier Mirajane contamination.
- `mirajane` / Mirajane Strauss: Fairy Tail.

Default seeding is additive and non-destructive. Existing imported or test characters remain in the database unless removed deliberately.

## Current Safe Runtime Policy

- Do not keep text and image models hot together.
- Generate story text first.
- Compose the image prompt with the text model.
- Hard-unload/stop Ollama before A1111 renders.
- Keep A1111 hot where possible.
- Use guarded runner scripts for real backend tests.

## Safety Rules

Before any heavy run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_companion_backends.ps1
```

Use the guarded runner for real A1111/Ollama smoke tests:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_real_app_route_image_guarded.ps1 -MinFreeRamGb 6 -MaxCommitRatio 0.95 -MaxVramUsedMiB 12200 -PollSeconds 2 -ResolutionPreset "640x640:1280x1280" -SmokeScriptRel "scripts\smoke_real_app_chat_auto_image.py" -SmokeSlug "codex-echidna-real-chat-auto-smoke"
```

Do not run large Qwen 35B/27B tests again without a stricter memory plan.

## How To Run The App

Preferred PowerShell launch:

```powershell
.\run_companion_v1.ps1
```

Then open:

```text
http://127.0.0.1:8000
```

The launch script sets F-only cache paths, pre-warms the configured text/image backends, and keeps the hard text-to-image handoff enabled.

If anything feels stuck, stop the local backends:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_companion_backends.ps1
```

To confirm cache/model paths are safe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\audit_storage_paths.py
```

## Latest Passing Evidence

- Non-blocking auto-image route:
  `outputs/diags/real_app_chat_auto_smoke_20260528_054343`

- Browser replay after startup readiness gating:
  `outputs/diags/browser_prompt_replay_20260601_201202`

- Diagnostics drawer browser probe:
  `outputs/diags/diagnostics_drawer_probe_20260601_202901`

- Single-turn real chat + auto-image after prompt cleanup:
  `outputs/diags/real_app_chat_auto_smoke_20260528_053121`
- Two-turn balanced sequence:
  `outputs/diags/real_app_chat_auto_sequence_20260528_052242`
- Two-turn speed sequence:
  `outputs/diags/real_app_chat_auto_sequence_20260528_051941`

Latest non-blocking single-turn balanced run:

- Chat route returned text: `21.95s`
- Image ready: `79.03s`
- A1111 render time: `15.71s`
- Peak VRAM: `12030 MiB`
- Lowest free RAM: `14.85 GiB`
- Final cleanup: about `231 MiB` VRAM used
- Prompt identity: `Echidna from Re:Zero`
- Contamination: no `Mirajane`

Latest readiness-gated browser replay:

- Startup warmup text: `20.72s`
- Startup warmup image: `60.45s`
- Average text visible over five characters: `18.63s`
- Average image visible over five characters: `55.71s`
- Average post-text image wait: `37.08s`
- Prompt strategy: deterministic Speed image prompts
- Resource guard: did not trip
- Final cleanup: about `532 MiB` VRAM used and about `21.8 GiB` free system RAM

Latest lightweight validation after product-backbone changes:

- Python compile passed for changed app/smoke files.
- `scripts/smoke_scene_state.py` passed, including regenerate with scene state.
- `scripts/smoke_scene_locations.py` passed.
- `scripts/smoke_story_export_import.py` passed.
- `scripts/smoke_story_frames.py` passed.
- `scripts/smoke_app_identity_prompt.py` passed.
- `scripts/smoke_frame_error_ui.py` passed.
- `scripts/audit_storage_paths.py` passed; risky C cache/model paths are absent.
- `scripts/stop_companion_backends.ps1` found no orphan companion backend processes after validation.

## Recent Implementation Changes

- Added in-app resource guard for RAM, commit ratio, and VRAM.
- Added guarded A1111 render watchdog with cleanup callback.
- Added A1111 retry on transient connection drop.
- Made A1111 checkpoint/options setup idempotent.
- Added hard Ollama unload before image render.
- Added visual identity filtering for multi-character Perchance-style cards.
- Added image prompt cleanup for dialogue/audio/meta fragments.
- Added run-id-named diagnostic image/settings copies.
- Added storage audit for F-only cache/model/temp paths.
- Updated launch scripts to disable text preload and stop Ollama before image generation.
- Improved status labels so the UI can show story generation, image prompt composition, text-model handoff, and A1111 render as distinct phases.
- Changed auto-image chat submission to return the assistant text first, then render the image in a background job and refresh the timeline when image generation completes.
- Rebuilt the primary UI shell into a visual-novel/stage layout while preserving the proven HTMX/backend contracts.
- Replaced the CDN HTMX dependency with a local vendored copy at `app/static/vendor/htmx.min.js` so the app shell is offline-safe.
- Limited visible image presets to the currently sane app choices: Speed `512 -> 1024`, Balanced `640 -> 1280`, and Detail `704 -> 1408`.
- Added a scene-loop primer and persistent scene status banner so users understand the write/reply/visualize flow.
- Moved rendered visuals into their owning assistant scene beat instead of showing them as detached timeline blocks.
- Added delayed timeline settling and image-load scroll handling so completed visuals are less likely to land off-screen after async refreshes.
- Added default cast seeding for Astra Vale, Atago, Echidna, and Mirajane Strauss, with explicit source-media anchors for canon characters.
- Added a structured `story_frames` layer: every new assistant turn records the user input, assistant prose, image prompt/path, status, model/preset metadata, and text/image timings.
- Added `scripts/backfill_story_frames.py` and backfilled existing assistant turns into story frames.
- Added lightweight frame metadata to assistant beats in the timeline.
- Added editable latest story memory/summary in the right panel, matching the long-story direction used by AI VN tools like DreamRunner.
- Made story generation frame-aware: the prompt now includes a compact `RECENT_STORY_FRAMES` block alongside the raw recent chat transcript.
- Sanitized frame context so legacy `<image>...</image>` tags do not teach the text model to emit image tags again.
- Added `/stories/{character_id}/export` and a right-panel export link for portable JSON containing character, user profile, messages, frames, summaries, images, and lore.
- Added editable conversation scene state: current location, location details, and active character list. This is copied into new story frames and injected into text prompts as `CURRENT_SCENE_STATE`.
- Added story import paired with export. Imported stories create a new character/conversation copy, remap messages, images, story frames, summaries, lore, scene state, and saved locations without overwriting the global user profile.
- Added reusable scene locations in the right panel. Current places can be saved, reused, and restored into active scene state.
- Tuned prompt context around `story_frames`: old turns are represented by compact structured frames, while raw chat history is reduced to the unframed tail, usually the newest user message. This avoids sending duplicate long-history context forever.
- Added smoke coverage for scene state, regeneration with scene state, reusable locations, and export/import roundtrips.
- Replaced the image preset dropdown with a clearer Speed/Balanced/Detail picker in both the main composer and inline visualizer.
- Improved resource-guard error surfacing: image failures now preserve the message id, refresh the timeline on error, show the guard/error reason inline on the affected story frame, and expose a direct `Retry Visual` action.
- Added startup readiness gating: configured launch scripts now pre-warm text/image backends, the UI blocks chat submission while runtime warmup is incomplete, and the browser replay waits for readiness before submitting prompts.
- Added a Runtime diagnostics drawer backed by `/diagnostics`, with live RAM/VRAM/text/image state and recent event-log entries.
- Cached text-model loaded checks so `/status` and `/diagnostics` do not repeatedly block on Ollama `/api/ps` during UI heartbeats.
- Added browser-level replay/probe coverage for the readiness-gated app flow and diagnostics drawer.

## What Is Still Left

- Continue UI/product polish on top of the new VN/stage shell, now using `story_frames` as the product backbone.
- Continue tuning the visible speed/quality preset control after manual use; the first clear Speed/Balanced/Detail picker is now in place.
- Continue refining loading states for text generation, image prompt composition, Ollama handoff, A1111 render, and startup readiness after real use.
- Keep refining recovery UX after guard-trip errors; inline error display and a direct retry action are now in place.
- Do a real-browser manual UI pass, especially narrow/mobile layout. Headless Chrome narrow screenshots still crop because its desktop viewport behavior is not reliable enough as the only mobile signal.
- Use story frames as the source of truth for route/image timings instead of scattered diagnostic files.
- Tune frame-driven context selection further after real story use: current summary + last N story frames + active character/location metadata is now in place, but N and compaction size should be adjusted from real chats.
- Promote saved locations into richer location cards later if needed: current saved locations are intentionally simple name/description/visual-anchor records.
- Add a richer import screen later if JSON paste feels clunky; the underlying import route is working.
- Continue manual image-quality review, especially character identity and camera/framing.

## Current Recommendation

Use the existing repo as the active prototype path. Do not start a new repo yet. The runtime is finally proven enough to productize: A1111 + Dolphin-X1-8B + hard handoff + guarded memory checks.
