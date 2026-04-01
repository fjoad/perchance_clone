# Image Parity Tests

These are the two isolated tests for comparing our local SDXL path against A1111's own Hires.fix path.

## 1. Local "A1111-ish" latent Hires test

This stays inside our Python stack, but uses:
- latent upscaling for stage 2
- `DPM++ 2M`
- A1111-style img2img internal step math

Run:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_nova_hires_repro.py --upscale-mode latent --a1111-img2img-step-math --scheduler dpmpp_2m --steps 20 --hires-steps 20 --cfg 7 --denoise 0.7 --base-width 512 --base-height 512 --width 1024 --height 1024 --clip-skip 2 --prefix nova_latent_a1111ish
```

Outputs go to `outputs\repro\...` and include:
- `stage1.png`
- `final.png`
- `settings.txt`

## 1b. Notebook-style settings, same square resolution

This keeps the stronger notebook-style recipe choices:
- `Euler A`
- `CFG 4.5`
- `denoise 0.45`
- `clip_skip 2`
- plain image-space resize second pass

But keeps the same square `512 -> 1024` resolution as the A1111-style test so you can isolate settings from resolution.

Run:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_nova_hires_repro.py --upscale-mode pil --scheduler euler_a --steps 20 --hires-steps 20 --cfg 4.5 --denoise 0.45 --base-width 512 --base-height 512 --width 1024 --height 1024 --clip-skip 2 --prefix nova_notebook_recipe_square
```

Outputs go to `outputs\repro\...` and include:
- `stage1.png`
- `final.png`
- `settings.txt`

## 1c. Notebook-style square control at `1024 -> 1024`

This is the notebook recipe with a larger square base render and no size increase on the second pass.
It is useful as a control for “what happens if stage 1 itself is already large.”

Run:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_nova_hires_repro.py --upscale-mode pil --scheduler euler_a --steps 20 --hires-steps 20 --cfg 4.5 --denoise 0.45 --base-width 1024 --base-height 1024 --width 1024 --height 1024 --clip-skip 2 --prefix nova_notebook_recipe_1024_control
```

## 1d. Notebook-style square Hires test at `1024 -> 2048`

This keeps the notebook recipe but starts from a larger square base and doubles to a larger square final image.

Run:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_nova_hires_repro.py --upscale-mode pil --scheduler euler_a --steps 20 --hires-steps 20 --cfg 4.5 --denoise 0.45 --base-width 1024 --base-height 1024 --width 2048 --height 2048 --clip-skip 2 --prefix nova_notebook_recipe_2048
```

## 1e. A1111-parameter square control at `1024 -> 1024`

This uses the A1111-style parameter set:
- `DPM++ 2M`
- `CFG 7`
- `denoise 0.7`
- latent second-pass path
- A1111-style img2img step math

Because base and final size are the same, this is a same-size second-pass control rather than a true upscale.

Run:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_nova_hires_repro.py --upscale-mode latent --a1111-img2img-step-math --scheduler dpmpp_2m --steps 20 --hires-steps 20 --cfg 7 --denoise 0.7 --base-width 1024 --base-height 1024 --width 1024 --height 1024 --clip-skip 2 --prefix nova_a1111_params_1024_control
```

## 1f. A1111-parameter square Hires test at `1024 -> 2048`

This uses the same A1111-style parameter set, but with a real 2x upscale on the second pass.

Run:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_nova_hires_repro.py --upscale-mode latent --a1111-img2img-step-math --scheduler dpmpp_2m --steps 20 --hires-steps 20 --cfg 7 --denoise 0.7 --base-width 1024 --base-height 1024 --width 2048 --height 2048 --clip-skip 2 --prefix nova_a1111_params_2048
```

## 1g. A1111-parameter square resolution sweep

This freezes the currently best-looking parameter recipe:
- `DPM++ 2M`
- latent Hires.fix path
- A1111-style img2img step math
- `steps=20`
- `hires_steps=20`
- `CFG=7`
- `denoise=0.7`
- `clip_skip=2`

And sweeps square 2x resolutions from `512 -> 1024` up to `1024 -> 2048`.

Run:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_nova_resolution_sweep.py
```

Default sweep sizes:
- `512 -> 1024`
- `640 -> 1280`
- `768 -> 1536`
- `896 -> 1792`
- `1024 -> 2048`

If you want to see the exact commands without running them:

```cmd
python scripts\test_nova_resolution_sweep.py --dry-run
```

## 2. Direct A1111 API Hires test

This calls your local A1111 backend directly over HTTP, without using the A1111 browser UI.

First, start A1111 with API enabled.

If you launch from `cmd` / `Anaconda Prompt`, one simple way is:

```cmd
cd /d F:\projects\a1111\stable-diffusion-webui
set COMMANDLINE_ARGS=--api
webui-user.bat
```

If your normal launch already uses extra args, keep them and include `--api`.

Then run the API test:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_a1111_api_hires.py --base-url http://127.0.0.1:7860 --checkpoint-name "novaAnimeXL_ilV120.safetensors [6c0ce2aaac]"
```

If you get:
- `WinError 10061`: A1111 is not listening on that port.
- `HTTP 404`: A1111 is running, but not with `--api`, or the base URL/port is wrong.

When `--api` is working, `http://127.0.0.1:7860/docs` should open.

Outputs go to `outputs\a1111_api_repro\...` and include:
- `final.png`
- `settings.txt`
- `response.json`

## Recommendation If Both Look Good

- Use the A1111 API path first if exact parity with your known-good A1111 outputs matters most right now.
- Keep the local latent test as the pure-Python fallback/experimental branch.
- Build the app against one image backend first instead of supporting both in the main flow immediately.

The practical default is:
- short term: A1111 API for image generation
- longer term: replace it only if the pure-Python latent path reaches the same quality consistently
