# Companion V1 Runbook

This is the practical runbook for the current local visual-novel companion prototype.

For the shortest orientation, start with the top-level `README.md`.

## Current Shape

This is not a new repo and not a separate app. The app is the FastAPI project in:

```text
F:\projects\perchance_clone\perchance_clone\app
```

The repo root contains support scripts, docs, experiments, outputs, and runtime state.

## Current Stack

- App framework: FastAPI.
- Templates: Jinja2.
- UI interactivity: HTMX, vendored locally.
- Styling: custom CSS.
- Database: SQLite.
- Text runtime: Ollama.
- Text model: `hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M`.
- Image runtime: AUTOMATIC1111 API.
- Image checkpoint: `F:\huggingface\models\novaAnimeXL_ilV120.safetensors`.
- Python env: `F:\anaconda3\envs\companion_v1`.

## Paths

- App code: `app/`
- Database: `runtime/companion_v1_app.sqlite3`
- Temp/log/runtime state: `runtime/`
- App-generated images: `outputs/app/`
- Diagnostics/experiments: `outputs/diags/`
- Characters/import examples: `characters/`
- Current status doc: `docs/current-implementation-status-2026-05-28.md`

## Run The App

From PowerShell:

```powershell
cd F:\projects\perchance_clone\perchance_clone
.\run_companion_v1.ps1
```

Then open:

```text
http://127.0.0.1:8000
```

From `cmd` / Anaconda Prompt:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
run_companion_v1.cmd
```

## Mock Mode

Use this for safe UI testing without loading Ollama or A1111:

```powershell
$env:COMPANION_USE_MOCK_TEXT = "1"
$env:COMPANION_USE_MOCK_IMAGE = "1"
.\run_companion_v1.ps1
```

Mock mode is the right first step after code changes.

## Browserless Route Probe

This is the closest automated equivalent to opening the app and clicking through the main flow.

Safe/mock probe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\live_route_probe.py
```

What it does:

- Starts uvicorn in a subprocess.
- Calls `GET /`.
- Calls `GET /?character_id=...`.
- Calls `GET /status`.
- Calls `POST /chat/{character_id}` with auto-image enabled.
- Waits for the background image request to complete.
- Saves the assistant text, prompts, image, route result, and uvicorn log.
- Shuts uvicorn down.

Heavy real-model probe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\live_route_probe.py --real --timeout 1200
```

Use the real probe only when you intentionally want to exercise Ollama + A1111.

## Browser UI Probe

This is the actual browser automation pass. It uses Playwright with installed Microsoft Edge, not a downloaded Chromium binary.

Safe/mock browser probe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\browser_probe_playwright.py
```

What it does:

- Starts uvicorn in a subprocess.
- Opens the app in Edge.
- Selects a test character URL.
- Fills the composer.
- Enables `Generate image after reply`.
- Submits the form.
- Waits for the assistant text to appear.
- Waits for the generated image to appear in the actual browser DOM.
- Saves screenshots, HTML, prompts, output image, console events, page errors, failed network requests, and uvicorn logs.
- Shuts uvicorn down.

Heavy real-model browser probe:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\browser_probe_playwright.py --real --timeout 1200
```

Outputs go under `outputs/diags/browser_probe_YYYYMMDD_HHMMSS/`.

## Safe Cleanup

If the app or local model processes feel stuck:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_companion_backends.ps1
```

This prints resource usage and stops companion-related Ollama/A1111 processes.

## Debug Logs

If the app seems frozen, run:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\dump_recent_app_state.py
```

It prints and saves a combined snapshot with:

- App `/status` response if the server is reachable.
- Current GPU memory/utilization.
- Uvicorn/Ollama/A1111-related processes.
- Latest messages, image requests, and story frames from SQLite.
- Tail of `runtime/logs/app_events.jsonl`.
- Tail of `runtime/logs/a1111_app.log`.

The saved file goes under `runtime/logs/debug_dump_YYYYMMDD_HHMMSS.txt`.

Primary logs:

- `runtime/logs/app_events.jsonl`: structured app events, including request timing, text model load/unload, Ollama stop attempts, image prompt creation, A1111 render timing, and guard trips.
- `runtime/logs/a1111_app.log`: raw A1111 backend output.
- `outputs/app/<character>/*_a1111_settings.json`: exact image prompts/settings/resources for generated images.

On startup, the app now marks old in-flight background image jobs as `image_error` instead of leaving them permanently stuck as pending.

## F-Only Storage Audit

Run this after setup changes, downloads, or model experiments:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\audit_storage_paths.py
```

The important line is:

```json
"risky_c_paths": []
```

## Runtime Policy

Current safe runtime policy:

1. Generate story text with Ollama.
2. Compose an image prompt.
3. Unload/stop Ollama before image rendering.
4. Render image with A1111.
5. Return text first; image appears later in the background.

Do not run large Qwen 35B/27B tests again without a stricter memory plan.

## Manual Browser Pass

Manual browser pass means using the local app in a normal browser, not internet research.

Checklist:

- Open `http://127.0.0.1:8000`.
- Switch characters.
- Send a text-only message.
- Send a message with `Generate image after reply`.
- Try Speed, Balanced, and Detail image presets.
- Save a location, then reuse it.
- Edit current scene state.
- Edit story memory.
- Export a story JSON.
- Import the story JSON as a copy.
- Regenerate/delete a message or image.
- Watch for confusing labels, missing loading states, broken layout, or awkward UX.

## Default Characters

The app seeds these if missing:

- Astra Vale: original sample character.
- Atago: Azur Lane.
- Echidna: Re:Zero.
- Mirajane Strauss: Fairy Tail.

Seeding is additive and does not delete existing characters.

## Lightweight Validation

Useful safe checks:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" -m py_compile app\config.py app\db.py app\main.py app\services\prompts.py app\services\text_generation.py app\services\image_generation.py
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_story_frames.py
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_scene_state.py
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_scene_locations.py
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_story_export_import.py
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_app_identity_prompt.py
& "F:\anaconda3\envs\companion_v1\python.exe" scripts\smoke_frame_error_ui.py
```

These are mock/lightweight checks unless explicitly described otherwise.
