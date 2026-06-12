"""Central F:-drive cache/bootstrap guard for local experiments.

Import and call configure_f_only_env() before importing torch, diffusers,
transformers, huggingface_hub, or anything that may create model caches.
"""
from __future__ import annotations

import os
from pathlib import Path


F_HF_HOME = Path(r"F:\huggingface\models")
F_HF_HUB_CACHE = F_HF_HOME / "hub"
F_HF_ASSETS_CACHE = F_HF_HOME / "assets"
F_HF_XET_CACHE = F_HF_HOME / "xet"
F_TORCH_HOME = F_HF_HOME / "torch"
F_XDG_CACHE_HOME = F_HF_HOME / "xdg_cache"
F_PIP_CACHE_DIR = F_HF_HOME / "pip_cache"
F_CUDA_CACHE_PATH = F_HF_HOME / "cuda_cache"
F_TORCH_EXTENSIONS_DIR = F_HF_HOME / "torch_extensions"
F_TORCHINDUCTOR_CACHE_DIR = F_HF_HOME / "torch_inductor"
F_TRITON_CACHE_DIR = F_HF_HOME / "triton"
F_MPLCONFIGDIR = F_HF_HOME / "matplotlib"
F_NUMBA_CACHE_DIR = F_HF_HOME / "numba_cache"
F_OLLAMA_MODELS = Path(r"F:\ollama\models")
F_OLLAMA_EXE = Path(r"F:\Programs\Ollama_0.21.0\ollama.exe")
F_PROJECT_ROOT = Path(__file__).resolve().parents[1]
F_TEMP_DIR = F_PROJECT_ROOT / "runtime" / "codex_temp"


def configure_f_only_env() -> None:
    """Force model/cache paths onto F: for this Python process."""
    paths = {
        "HF_HOME": F_HF_HOME,
        "HF_HUB_CACHE": F_HF_HUB_CACHE,
        "HUGGINGFACE_HUB_CACHE": F_HF_HUB_CACHE,
        "TRANSFORMERS_CACHE": F_HF_HUB_CACHE,
        "HF_ASSETS_CACHE": F_HF_ASSETS_CACHE,
        "HF_XET_CACHE": F_HF_XET_CACHE,
        "TORCH_HOME": F_TORCH_HOME,
        "XDG_CACHE_HOME": F_XDG_CACHE_HOME,
        "PIP_CACHE_DIR": F_PIP_CACHE_DIR,
        "CUDA_CACHE_PATH": F_CUDA_CACHE_PATH,
        "TORCH_EXTENSIONS_DIR": F_TORCH_EXTENSIONS_DIR,
        "TORCHINDUCTOR_CACHE_DIR": F_TORCHINDUCTOR_CACHE_DIR,
        "TRITON_CACHE_DIR": F_TRITON_CACHE_DIR,
        "MPLCONFIGDIR": F_MPLCONFIGDIR,
        "NUMBA_CACHE_DIR": F_NUMBA_CACHE_DIR,
        "TMP": F_TEMP_DIR,
        "TEMP": F_TEMP_DIR,
        "TMPDIR": F_TEMP_DIR,
        "SQLITE_TMPDIR": F_TEMP_DIR,
        "OLLAMA_MODELS": F_OLLAMA_MODELS,
    }
    for value in paths.values():
        value.mkdir(parents=True, exist_ok=True)
    for key, value in paths.items():
        os.environ[key] = str(value)


def assert_f_only_env() -> None:
    """Fail loudly if critical cache/model paths are not on F:."""
    required = {
        "HF_HOME": F_HF_HOME,
        "HF_HUB_CACHE": F_HF_HUB_CACHE,
        "HUGGINGFACE_HUB_CACHE": F_HF_HUB_CACHE,
        "TORCH_HOME": F_TORCH_HOME,
        "PIP_CACHE_DIR": F_PIP_CACHE_DIR,
        "CUDA_CACHE_PATH": F_CUDA_CACHE_PATH,
        "TORCH_EXTENSIONS_DIR": F_TORCH_EXTENSIONS_DIR,
        "TORCHINDUCTOR_CACHE_DIR": F_TORCHINDUCTOR_CACHE_DIR,
        "TRITON_CACHE_DIR": F_TRITON_CACHE_DIR,
        "TMP": F_TEMP_DIR,
        "TEMP": F_TEMP_DIR,
        "SQLITE_TMPDIR": F_TEMP_DIR,
        "OLLAMA_MODELS": F_OLLAMA_MODELS,
    }
    bad: list[str] = []
    for key, expected in required.items():
        actual = os.environ.get(key)
        if actual is None:
            bad.append(f"{key}=<missing>, expected {expected}")
            continue
        try:
            actual_path = Path(actual).resolve()
            expected_path = expected.resolve()
        except OSError:
            bad.append(f"{key}={actual!r}, expected {expected}")
            continue
        if actual_path != expected_path or actual_path.drive.upper() != "F:":
            bad.append(f"{key}={actual_path}, expected {expected_path}")
    if bad:
        raise RuntimeError("Unsafe cache/model paths:\n" + "\n".join(bad))


def print_f_only_env() -> None:
    for key in (
        "HF_HOME",
        "HF_HUB_CACHE",
        "HUGGINGFACE_HUB_CACHE",
        "TRANSFORMERS_CACHE",
        "HF_ASSETS_CACHE",
        "HF_XET_CACHE",
        "TORCH_HOME",
        "XDG_CACHE_HOME",
        "PIP_CACHE_DIR",
        "CUDA_CACHE_PATH",
        "TORCH_EXTENSIONS_DIR",
        "TORCHINDUCTOR_CACHE_DIR",
        "TRITON_CACHE_DIR",
        "MPLCONFIGDIR",
        "NUMBA_CACHE_DIR",
        "TMP",
        "TEMP",
        "TMPDIR",
        "SQLITE_TMPDIR",
        "OLLAMA_MODELS",
    ):
        print(f"{key}={os.environ.get(key, '<missing>')}")


configure_f_only_env()
