# Local VN Environment Inventory

Status: active reference
Date: May 23, 2026

## Rule

Do not create a new Python or Conda environment for this project unless the existing environments fail a concrete experiment requirement.

Use the existing `companion_v1` environment by default:

```powershell
F:\anaconda3\envs\companion_v1\python.exe
```

## Existing Environments

### `companion_v1`

Path:

```text
F:\anaconda3\envs\companion_v1
```

Use for:

- app server
- Ollama text harness
- image generation experiments
- diffusers/SDXL benchmarks
- Perchance export extraction
- all current local VN experiments

Verified packages:

- Python 3.11.13
- torch 2.8.0+cu126
- CUDA available
- RTX 3080 detected
- diffusers 0.35.1
- transformers 4.57.0
- huggingface_hub 0.35.3
- fastapi present
- Pillow present
- numpy present

### `perchance`

Path:

```text
F:\anaconda3\envs\perchance
```

Use only as fallback for ML experiments if `companion_v1` breaks.

Verified packages:

- Python 3.11.13
- torch 2.8.0+cu126
- CUDA available
- RTX 3080 detected
- diffusers 0.35.1
- transformers 4.57.0
- huggingface_hub 0.35.3
- fastapi missing

### `a1111`

Path:

```text
F:\anaconda3\envs\a1111
```

Do not use for current experiments.

Observed state:

- Python 3.10.11
- torch missing
- diffusers missing
- transformers missing
- huggingface_hub missing
- fastapi missing
- Pillow missing
- numpy missing

## F-Only Storage Rule

Before running model downloads, app server, Jupyter, or benchmarks, ensure these variables point to `F:`.

Preferred setup:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_f_only_env.ps1
```

The experiment scripts also import `scripts/f_only_env.py`, which sets process-level guardrails before importing `torch`, `diffusers`, `transformers`, or `huggingface_hub`.

## Current Decision

Use `F:\anaconda3\envs\companion_v1\python.exe` for all experiment scripts and app runs.

Do not install packages, run `conda create`, or make a new venv until a test fails due to a missing dependency that cannot safely be added to `companion_v1`.
