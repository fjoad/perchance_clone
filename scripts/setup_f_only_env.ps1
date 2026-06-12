$ErrorActionPreference = "Stop"

$pairs = @{
    HF_HOME = "F:\huggingface\models"
    HF_HUB_CACHE = "F:\huggingface\models\hub"
    HUGGINGFACE_HUB_CACHE = "F:\huggingface\models\hub"
    TRANSFORMERS_CACHE = "F:\huggingface\models\hub"
    HF_ASSETS_CACHE = "F:\huggingface\models\assets"
    HF_XET_CACHE = "F:\huggingface\models\xet"
    TORCH_HOME = "F:\huggingface\models\torch"
    XDG_CACHE_HOME = "F:\huggingface\models\xdg_cache"
    PIP_CACHE_DIR = "F:\huggingface\models\pip_cache"
    CUDA_CACHE_PATH = "F:\huggingface\models\cuda_cache"
    TORCH_EXTENSIONS_DIR = "F:\huggingface\models\torch_extensions"
    TORCHINDUCTOR_CACHE_DIR = "F:\huggingface\models\torch_inductor"
    TRITON_CACHE_DIR = "F:\huggingface\models\triton"
    MPLCONFIGDIR = "F:\huggingface\models\matplotlib"
    NUMBA_CACHE_DIR = "F:\huggingface\models\numba_cache"
    TMP = "F:\projects\perchance_clone\perchance_clone\runtime\codex_temp"
    TEMP = "F:\projects\perchance_clone\perchance_clone\runtime\codex_temp"
    TMPDIR = "F:\projects\perchance_clone\perchance_clone\runtime\codex_temp"
    SQLITE_TMPDIR = "F:\projects\perchance_clone\perchance_clone\runtime\codex_temp"
    OLLAMA_MODELS = "F:\ollama\models"
}

foreach ($key in $pairs.Keys) {
    New-Item -ItemType Directory -Force -Path $pairs[$key] | Out-Null
    [Environment]::SetEnvironmentVariable($key, $pairs[$key], "User")
    Set-Item -Path "Env:\$key" -Value $pairs[$key]
}

Write-Host "F-only environment configured for this shell and future user shells:"
foreach ($key in ($pairs.Keys | Sort-Object)) {
    Write-Host "$key=$($pairs[$key])"
}

Write-Host ""
Write-Host "Important: restart Jupyter kernels and terminals that were already open."
