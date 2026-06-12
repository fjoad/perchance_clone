@echo off
set HF_HOME=F:\huggingface\models
set HF_HUB_CACHE=F:\huggingface\models\hub
set HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub
set TRANSFORMERS_CACHE=F:\huggingface\models\hub
set HF_ASSETS_CACHE=F:\huggingface\models\assets
set HF_XET_CACHE=F:\huggingface\models\xet
set TORCH_HOME=F:\huggingface\models\torch
set XDG_CACHE_HOME=F:\huggingface\models\xdg_cache
set PIP_CACHE_DIR=F:\huggingface\models\pip_cache
set CUDA_CACHE_PATH=F:\huggingface\models\cuda_cache
set TORCH_EXTENSIONS_DIR=F:\huggingface\models\torch_extensions
set TORCHINDUCTOR_CACHE_DIR=F:\huggingface\models\torch_inductor
set TRITON_CACHE_DIR=F:\huggingface\models\triton
set MPLCONFIGDIR=F:\huggingface\models\matplotlib
set NUMBA_CACHE_DIR=F:\huggingface\models\numba_cache
set TMP=F:\projects\perchance_clone\perchance_clone\runtime\codex_temp
set TEMP=F:\projects\perchance_clone\perchance_clone\runtime\codex_temp
set TMPDIR=F:\projects\perchance_clone\perchance_clone\runtime\codex_temp
set SQLITE_TMPDIR=F:\projects\perchance_clone\perchance_clone\runtime\codex_temp
set LOCALAPPDATA=F:\projects\perchance_clone\perchance_clone\runtime\localappdata
set OLLAMA_MODELS=F:\ollama\models
set PYTHONDONTWRITEBYTECODE=1
set COMPANION_PRELOAD_TEXT_MODEL=1
set COMPANION_PRELOAD_IMAGE_BACKEND=1
set COMPANION_STOP_OLLAMA_BEFORE_IMAGE=1

"F:\anaconda3\envs\companion_v1\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
