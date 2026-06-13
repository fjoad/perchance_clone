# Companion V1

Local-first visual-novel companion prototype.

This is still the same repo. I did **not** make a new app or new repository. The web app lives in `app/`; the surrounding folders are support material, scripts, docs, outputs, and runtime state.

## What This Is

The goal is a fully offline illustrated VN/chat app:

1. You write the next line/action as Anon.
2. A local roleplay text model **streams** the next scene beat token-by-token.
3. The app optionally composes an image prompt.
4. A1111 renders the image locally, with **live step/ETA progress** shown on the beat.
5. The image drops into the same assistant scene beat after the text has already appeared.

Current design intentionally pre-warms the configured local backends, streams text first, and renders images in the background with real progress so the app never feels frozen. Startup warmup retries automatically and exposes a Retry Engines button if a local backend fails to load.

## Tech Stack

- Backend: FastAPI
- Templates: Jinja2
- Frontend interactivity: HTMX, vendored locally at `app/static/vendor/htmx.min.js`
- Styling/behavior: custom CSS and small vanilla JS in `app/static/`
- Database: SQLite at `runtime/companion_v1_app.sqlite3`
- Text backend: Ollama
- Current text model: `hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M`
- Image backend: AUTOMATIC1111 API
- Current image checkpoint: `F:\huggingface\models\novaAnimeXL_ilV120.safetensors`
- Python env: `F:\anaconda3\envs\companion_v1`

## Important Folders

- `app/`: actual FastAPI web app.
- `app/main.py`: routes and app orchestration.
- `app/db.py`: SQLite schema and persistence helpers.
- `app/services/`: text, image, prompt, runtime, and resource-guard services.
- `app/templates/`: Jinja templates for the UI.
- `app/static/`: CSS, JS, vendored frontend dependency.
- `scripts/`: smoke tests, benchmark helpers, cleanup/audit tools.
- `docs/`: project notes, research, current status, runbooks.
- `characters/`: plain-text character import examples.
- `benchmarks/`: Jupyter notebooks from the model/runtime benchmark phase.
- `runtime/`: local DB/temp/log state (gitignored; created on first run).
- `outputs/app/`: app-generated images (gitignored; created on first run).
- `outputs/diags/`: experiment outputs and benchmark artifacts (gitignored).

## Install

Python deps for the web app live in `requirements.txt` (the heavy model
backends are external local services, not pip packages):

```powershell
pip install -r requirements.txt
```

`requirements-freeze.txt` is the exact snapshot of the working
`companion_v1` conda env (Python 3.11) if you need a faithful rebuild.
You also need local installs of [Ollama](https://ollama.com) (text) and
[AUTOMATIC1111 stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
(images); their paths are configured in `app/config.py`.

## How To Run

Easiest: double-click `START_COMPANION_APP.cmd` in the repo root. It starts
the server and opens the browser; keep its terminal window open while using
the app.

Or from a PowerShell prompt at the repo root:

```powershell
cd F:\projects\perchance_clone\perchance_clone
.\run_companion_v1.ps1
```

Then open:

```text
http://127.0.0.1:8000
```

For `cmd` / Anaconda Prompt:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
run_companion_v1.cmd
```

The launch scripts set cache/model/temp paths to `F:` so HuggingFace, Ollama, Torch, temp files, and SQLite temp files should not spill onto `C:`. They also enable startup readiness gating: the app warms the configured text/image backends and disables the chat composer until the runtime is ready.

## Safe Cleanup

If anything feels stuck, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_companion_backends.ps1
```

This stops Ollama/A1111-style companion backend processes and prints RAM/VRAM before and after.

To dump the current app/DB/process/GPU state into one file:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\dump_recent_app_state.py
```

The dump is written to `runtime/logs/debug_dump_YYYYMMDD_HHMMSS.txt`.

Main logs and diagnostics:

- `runtime/logs/app_events.jsonl`: structured app event log for requests, text model load/unload, image jobs, A1111 calls, and failures.
- `runtime/logs/a1111_app.log`: raw A1111 process output.
- `outputs/app/<character>/*_a1111_settings.json`: exact image prompt, negative prompt, render settings, elapsed time, and resource snapshot for each generated image.
- In the app UI, click `Runtime` to open the diagnostics drawer. It shows current runtime readiness, RAM/VRAM, text/image backend state, and recent events.
- API endpoint: `http://127.0.0.1:8000/diagnostics`

To confirm cache/model paths are safe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\audit_storage_paths.py
```

Look for:

```json
"risky_c_paths": []
```

## Mock Mode

Use mock mode when testing UI/app flow without loading Ollama or A1111:

```powershell
$env:COMPANION_USE_MOCK_TEXT = "1"
$env:COMPANION_USE_MOCK_IMAGE = "1"
.\run_companion_v1.ps1
```

Mock mode exercises the web app, DB, prompts, frames, scene state, image-request flow, and UI without touching the heavy models.

## Quick Regression Smokes

Mock-mode smokes that exercise the app routes without loading any model:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_app_identity_prompt.py
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_story_frames.py
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_scene_state.py
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_stream_chat.py
```

The last one validates the token-streaming chat route end to end
(NDJSON events, persistence, story frame) and cleans up after itself.

## Browserless Route Probe

Before doing a manual browser pass, run the live route probe. It starts the real uvicorn server, calls the app over HTTP, posts a chat message with auto-image enabled, waits for the background image row, saves artifacts, and shuts the server down.

Safe/mock route probe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\live_route_probe.py
```

Heavy real-model route probe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\live_route_probe.py --real --timeout 1200
```

Outputs go under `outputs/diags/live_route_probe_YYYYMMDD_HHMMSS/`.

## Browser UI Probe

For the closest automated version of “open the browser and use the app,” run the Playwright probe. It launches installed Microsoft Edge, clicks/fills the real UI, submits a chat with auto-image enabled, waits for the image to appear in the browser DOM, captures screenshots, records console/page/network errors, and shuts everything down.

Safe/mock browser probe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\browser_probe_playwright.py
```

Heavy real-model browser probe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\browser_probe_playwright.py --real --timeout 1200
```

Outputs go under `outputs/diags/browser_probe_YYYYMMDD_HHMMSS/`.

## Current Runtime Policy

The safe production-ish path is:

1. Pre-warm configured backends on launch.
2. Generate text with Ollama.
3. Compose or deterministically build the image prompt.
4. Hard-unload/stop Ollama before image render.
5. Render through A1111.
6. Keep A1111 hot where possible.

This avoids keeping text and image models hot together on the 12 GB GPU.

## Default Characters

On startup, the app seeds these characters if missing:

- Astra Vale: original sample character.
- Atago: Azur Lane.
- Echidna: Re:Zero.
- Mirajane Strauss: Fairy Tail.

Seeding is additive and non-destructive. It does not delete existing imported/test characters.

## Current App Features

- VN/stage-style shell.
- Real token streaming: replies render word-by-word as the model writes (`POST /chat/{id}/stream`).
- Real image progress: live step counts and ETA polled from A1111 during each render.
- Startup readiness panel that blocks chat until the runtime is ready, retries failed warmups, and offers a Retry Engines button.
- Sticky readiness: the composer stays usable during background renders; requests queue on the runtime lock.
- Auto-image toggle and image preset persist across turns and restarts.
- Cache-busted static assets, so UI updates always reach the browser.
- Runtime diagnostics drawer with recent event log.
- Power Off button in the header: unloads all models, stops Ollama and A1111 (including orphaned runners), frees VRAM/RAM, then closes the app server - with live phase narration and a final "safe to close this tab" screen.
- Text-first, background-image flow.
- Speed/Balanced/Detail image preset picker.
- Story frames for each assistant turn.
- Frame metadata: text time, image time, status, location.
- Editable user profile.
- Editable current scene state: location, details, active characters.
- Reusable saved locations.
- Editable rolling story memory.
- Story export/import JSON.
- Inline image errors and retry button if a render fails or guard trips.
- Local HTMX dependency, no CDN dependency for the app shell.

## What "Manual Browser Pass" Means

It means opening `http://127.0.0.1:8000` and using the app like a person would:

- Switch characters.
- Send a text-only message.
- Send a message with auto-image enabled.
- Try Speed/Balanced/Detail presets.
- Save and reuse a location.
- Edit scene state and story memory.
- Export and import a story.
- Delete/regenerate a message or image.
- Check whether the UI feels understandable.

It does **not** mean browsing the internet.

## Current Documentation

Most useful current docs:

- `docs/current-implementation-status-2026-05-28.md`
- `docs/companion-v1-runbook.md`
- `docs/project-master-dossier.md`

Older benchmark/research docs are useful context, but the status doc is the current baseline.
