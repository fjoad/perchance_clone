# Companion V1 Runbook

This is the first local-first vertical slice for the companion app restart.

## Current Stack

- App code: `app/`
- Runtime data: `runtime/`
- Generated media: `outputs/app/`
- Text model: `Qwen/Qwen2.5-7B-Instruct`
- RP benchmark fallback: `PygmalionAI/Pygmalion-3-12B`
- Image checkpoint: `F:\huggingface\models\novaAnimeXL_ilV120.safetensors`
- HF root: `F:\huggingface\models`
- Python env: `F:\anaconda3\envs\companion_v1`

## Architecture Notes

- Multi-character app from the start
- SQLite persistence under `runtime/`
- Hidden prompt assembly for chat
- Pinned memory plus rolling summary memory
- Companion-aware image generation
- Default image path is a two-stage SDXL hires flow

## Hires Flow

The image path is intentionally not one-pass txt2img.

Current default:

1. Stage 1 txt2img at `512x512`
2. Latent upscale to the target latent size
3. Stage 2 img2img refinement at `1024x1024`

This is the local app's A1111-style hires path for v1.

Implementation note:

- The current default uses the A1111-style `Latent` branch rather than a plain decoded-image resize.
- In A1111's latent upscaler mapping, plain `Latent` corresponds to bilinear latent resize without antialiasing.

## Run The App

From the repo root:

```powershell
.\run_companion_v1.ps1
```

If you are using `Anaconda Prompt` / `cmd`, use:

```cmd
run_companion_v1.cmd
```

Or directly:

```powershell
& "F:\anaconda3\envs\companion_v1\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

## Mock Mode

If you want to test the full app loop without loading the real text model or SDXL checkpoint:

```powershell
$env:COMPANION_USE_MOCK_TEXT = "1"
$env:COMPANION_USE_MOCK_IMAGE = "1"
.\run_companion_v1.ps1
```

Mock mode keeps the UI, DB, memory flow, and image-request flow intact while replacing model inference.

## Standalone Text Model Load Test

Use this to test whether a text model can load outside the app.

From `Anaconda Prompt`:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
set HF_HOME=F:\huggingface\models
set HF_HUB_CACHE=F:\huggingface\models\hub
set HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub
python scripts\test_text_model_load.py --model-id Qwen/Qwen2.5-7B-Instruct --disable-warmup
```

To run one tiny generation after the load succeeds:

```cmd
python scripts\test_text_model_load.py --model-id Qwen/Qwen2.5-7B-Instruct --disable-warmup --generate
```

Control test for the previously used Pygmalion model:

```cmd
python scripts\test_text_model_load.py --model-id PygmalionAI/Pygmalion-3-12B --local-only --disable-warmup
```

## Important Paths

- Database: `runtime/companion_v1_app.sqlite3`
- Logs/temp/cache: `runtime/`
- Output images: `outputs/app/<character-slug>/`

## Notes

- The current UI uses FastAPI + Jinja + HTMX + custom CSS.
- The current app uses a sample seeded character until real Perchance cards are adapted into the native schema.
- The old notebooks remain reference material only.
