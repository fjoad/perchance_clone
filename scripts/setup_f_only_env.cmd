@echo off
set "HF_HOME=F:\huggingface\models"
set "HF_HUB_CACHE=F:\huggingface\models\hub"
set "HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub"
set "TRANSFORMERS_CACHE=F:\huggingface\models\hub"
set "HF_ASSETS_CACHE=F:\huggingface\models\assets"
set "HF_XET_CACHE=F:\huggingface\models\xet"
set "TORCH_HOME=F:\huggingface\models\torch"
set "XDG_CACHE_HOME=F:\huggingface\models\xdg_cache"
set "PIP_CACHE_DIR=F:\huggingface\models\pip_cache"
set "CUDA_CACHE_PATH=F:\huggingface\models\cuda_cache"
set "TORCH_EXTENSIONS_DIR=F:\huggingface\models\torch_extensions"
set "TORCHINDUCTOR_CACHE_DIR=F:\huggingface\models\torch_inductor"
set "TRITON_CACHE_DIR=F:\huggingface\models\triton"
set "MPLCONFIGDIR=F:\huggingface\models\matplotlib"
set "NUMBA_CACHE_DIR=F:\huggingface\models\numba_cache"
set "TMP=F:\projects\perchance_clone\perchance_clone\runtime\codex_temp"
set "TEMP=F:\projects\perchance_clone\perchance_clone\runtime\codex_temp"
set "TMPDIR=F:\projects\perchance_clone\perchance_clone\runtime\codex_temp"
set "SQLITE_TMPDIR=F:\projects\perchance_clone\perchance_clone\runtime\codex_temp"
set "OLLAMA_MODELS=F:\ollama\models"

mkdir "%HF_HOME%" 2>nul
mkdir "%HF_HUB_CACHE%" 2>nul
mkdir "%HF_ASSETS_CACHE%" 2>nul
mkdir "%HF_XET_CACHE%" 2>nul
mkdir "%TORCH_HOME%" 2>nul
mkdir "%XDG_CACHE_HOME%" 2>nul
mkdir "%PIP_CACHE_DIR%" 2>nul
mkdir "%CUDA_CACHE_PATH%" 2>nul
mkdir "%TORCH_EXTENSIONS_DIR%" 2>nul
mkdir "%TORCHINDUCTOR_CACHE_DIR%" 2>nul
mkdir "%TRITON_CACHE_DIR%" 2>nul
mkdir "%MPLCONFIGDIR%" 2>nul
mkdir "%NUMBA_CACHE_DIR%" 2>nul
mkdir "%TMP%" 2>nul
mkdir "%OLLAMA_MODELS%" 2>nul

setx HF_HOME "%HF_HOME%" >nul
setx HF_HUB_CACHE "%HF_HUB_CACHE%" >nul
setx HUGGINGFACE_HUB_CACHE "%HUGGINGFACE_HUB_CACHE%" >nul
setx TRANSFORMERS_CACHE "%TRANSFORMERS_CACHE%" >nul
setx HF_ASSETS_CACHE "%HF_ASSETS_CACHE%" >nul
setx HF_XET_CACHE "%HF_XET_CACHE%" >nul
setx TORCH_HOME "%TORCH_HOME%" >nul
setx XDG_CACHE_HOME "%XDG_CACHE_HOME%" >nul
setx PIP_CACHE_DIR "%PIP_CACHE_DIR%" >nul
setx CUDA_CACHE_PATH "%CUDA_CACHE_PATH%" >nul
setx TORCH_EXTENSIONS_DIR "%TORCH_EXTENSIONS_DIR%" >nul
setx TORCHINDUCTOR_CACHE_DIR "%TORCHINDUCTOR_CACHE_DIR%" >nul
setx TRITON_CACHE_DIR "%TRITON_CACHE_DIR%" >nul
setx MPLCONFIGDIR "%MPLCONFIGDIR%" >nul
setx NUMBA_CACHE_DIR "%NUMBA_CACHE_DIR%" >nul
setx TMP "%TMP%" >nul
setx TEMP "%TEMP%" >nul
setx TMPDIR "%TMPDIR%" >nul
setx SQLITE_TMPDIR "%SQLITE_TMPDIR%" >nul
setx OLLAMA_MODELS "%OLLAMA_MODELS%" >nul

echo F-only environment configured for this cmd session and future user shells.
echo HF_HOME=%HF_HOME%
echo HF_HUB_CACHE=%HF_HUB_CACHE%
echo HUGGINGFACE_HUB_CACHE=%HUGGINGFACE_HUB_CACHE%
echo TRANSFORMERS_CACHE=%TRANSFORMERS_CACHE%
echo HF_ASSETS_CACHE=%HF_ASSETS_CACHE%
echo HF_XET_CACHE=%HF_XET_CACHE%
echo TORCH_HOME=%TORCH_HOME%
echo XDG_CACHE_HOME=%XDG_CACHE_HOME%
echo PIP_CACHE_DIR=%PIP_CACHE_DIR%
echo CUDA_CACHE_PATH=%CUDA_CACHE_PATH%
echo TORCH_EXTENSIONS_DIR=%TORCH_EXTENSIONS_DIR%
echo TORCHINDUCTOR_CACHE_DIR=%TORCHINDUCTOR_CACHE_DIR%
echo TRITON_CACHE_DIR=%TRITON_CACHE_DIR%
echo MPLCONFIGDIR=%MPLCONFIGDIR%
echo NUMBA_CACHE_DIR=%NUMBA_CACHE_DIR%
echo TMP=%TMP%
echo TEMP=%TEMP%
echo TMPDIR=%TMPDIR%
echo SQLITE_TMPDIR=%SQLITE_TMPDIR%
echo OLLAMA_MODELS=%OLLAMA_MODELS%
echo.
echo Important: restart Jupyter kernels and terminals that were already open.
