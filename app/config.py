from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "app"
RUNTIME_DIR = ROOT_DIR / "runtime"
TEMP_DIR = RUNTIME_DIR / "codex_temp"
OUTPUTS_DIR = ROOT_DIR / "outputs" / "app"
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

HF_HOME = Path(r"F:\huggingface\models")
HF_HUB_CACHE = HF_HOME / "hub"
HF_ASSETS_CACHE = HF_HOME / "assets"
HF_XET_CACHE = HF_HOME / "xet"
TORCH_HOME = HF_HOME / "torch"
XDG_CACHE_HOME = HF_HOME / "xdg_cache"
PIP_CACHE_DIR = HF_HOME / "pip_cache"
CUDA_CACHE_PATH = HF_HOME / "cuda_cache"
TORCH_EXTENSIONS_DIR = HF_HOME / "torch_extensions"
TORCHINDUCTOR_CACHE_DIR = HF_HOME / "torch_inductor"
TRITON_CACHE_DIR = HF_HOME / "triton"
MPLCONFIGDIR = HF_HOME / "matplotlib"
NUMBA_CACHE_DIR = HF_HOME / "numba_cache"
IMAGE_CHECKPOINT = HF_HOME / "novaAnimeXL_ilV120.safetensors"
OLLAMA_EXE = Path(r"F:\Programs\Ollama_0.21.0\ollama.exe")
OLLAMA_MODELS_DIR = Path(r"F:\ollama\models")
IMAGE_RESOLUTION_PRESETS = (
    (512, 512, 1024, 1024),
    (640, 640, 1280, 1280),
    (704, 704, 1408, 1408),
)


def configure_process_environment() -> None:
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ["TRANSFORMERS_CACHE"] = str(HF_HUB_CACHE)
    os.environ["HF_ASSETS_CACHE"] = str(HF_ASSETS_CACHE)
    os.environ["HF_XET_CACHE"] = str(HF_XET_CACHE)
    os.environ["TORCH_HOME"] = str(TORCH_HOME)
    os.environ["XDG_CACHE_HOME"] = str(XDG_CACHE_HOME)
    os.environ["PIP_CACHE_DIR"] = str(PIP_CACHE_DIR)
    os.environ["CUDA_CACHE_PATH"] = str(CUDA_CACHE_PATH)
    os.environ["TORCH_EXTENSIONS_DIR"] = str(TORCH_EXTENSIONS_DIR)
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = str(TORCHINDUCTOR_CACHE_DIR)
    os.environ["TRITON_CACHE_DIR"] = str(TRITON_CACHE_DIR)
    os.environ["MPLCONFIGDIR"] = str(MPLCONFIGDIR)
    os.environ["NUMBA_CACHE_DIR"] = str(NUMBA_CACHE_DIR)
    os.environ["OLLAMA_MODELS"] = str(OLLAMA_MODELS_DIR)


@dataclass(frozen=True)
class ImageConfig:
    backend: str = "a1111"
    a1111_base_url: str = "http://127.0.0.1:7860"
    a1111_root: Path = Path(r"F:\projects\a1111\stable-diffusion-webui")
    a1111_keep_hot: bool = True
    checkpoint: Path = IMAGE_CHECKPOINT
    base_width: int = 640
    base_height: int = 640
    target_width: int = 1280
    target_height: int = 1280
    steps: int = 20
    hires_steps: int = 10
    guidance_scale: float = 7.0
    denoise_strength: float = 0.7
    clip_skip: int = 2
    upscale_method: str = "latent"
    sampler_name: str = "DPM++ 2M"
    scheduler: str = "Automatic"
    hr_upscaler: str = "Latent"
    a1111_img2img_step_math: bool = True


@dataclass(frozen=True)
class Settings:
    app_name: str = "Companion V1"
    hf_home: Path = HF_HOME
    hf_hub_cache: Path = HF_HUB_CACHE
    hf_assets_cache: Path = HF_ASSETS_CACHE
    hf_xet_cache: Path = HF_XET_CACHE
    torch_home: Path = TORCH_HOME
    xdg_cache_home: Path = XDG_CACHE_HOME
    pip_cache_dir: Path = PIP_CACHE_DIR
    cuda_cache_path: Path = CUDA_CACHE_PATH
    torch_extensions_dir: Path = TORCH_EXTENSIONS_DIR
    torchinductor_cache_dir: Path = TORCHINDUCTOR_CACHE_DIR
    triton_cache_dir: Path = TRITON_CACHE_DIR
    mplconfigdir: Path = MPLCONFIGDIR
    numba_cache_dir: Path = NUMBA_CACHE_DIR
    db_path: Path = RUNTIME_DIR / "companion_v1_app.sqlite3"
    text_model_id: str = "Qwen/Qwen2.5-7B-Instruct"
    qwen_uncensored_model_id: str = "Orion-zhen/Qwen2.5-7B-Instruct-Uncensored"
    qwen_meissa_model_id: str = "Orion-zhen/Meissa-Qwen2.5-7B-Instruct"
    llama_comparison_model_id: str = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    roleplay_benchmark_model_id: str = "PygmalionAI/Pygmalion-3-12B"
    ollama_exe: Path = OLLAMA_EXE
    ollama_models_dir: Path = OLLAMA_MODELS_DIR
    ollama_base_url: str = "http://localhost:11434"
    ollama_model_name: str = "hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M"
    ollama_num_ctx: int = 8192
    preload_text_model: bool = os.getenv("COMPANION_PRELOAD_TEXT_MODEL", "0") == "1"
    preload_image_backend: bool = os.getenv("COMPANION_PRELOAD_IMAGE_BACKEND", "0") == "1"
    stop_ollama_before_image: bool = os.getenv("COMPANION_STOP_OLLAMA_BEFORE_IMAGE", "1") == "1"
    resource_guard_enabled: bool = os.getenv("COMPANION_RESOURCE_GUARD", "1") == "1"
    min_free_ram_gb: float = float(os.getenv("COMPANION_MIN_FREE_RAM_GB", "6"))
    max_commit_ratio: float = float(os.getenv("COMPANION_MAX_COMMIT_RATIO", "0.95"))
    max_vram_used_mib: int = int(os.getenv("COMPANION_MAX_VRAM_USED_MIB", "12200"))
    resource_guard_poll_seconds: float = float(os.getenv("COMPANION_RESOURCE_GUARD_POLL_SECONDS", "2"))
    use_mock_text: bool = os.getenv("COMPANION_USE_MOCK_TEXT", "0") == "1"
    use_mock_image: bool = os.getenv("COMPANION_USE_MOCK_IMAGE", "0") == "1"
    summary_interval_user_turns: int = 6
    recent_messages_window: int = 12
    lore_recent_turns: int = 4
    lore_max_entries: int = 3
    static_dir: Path = STATIC_DIR
    templates_dir: Path = TEMPLATES_DIR
    runtime_dir: Path = RUNTIME_DIR
    temp_dir: Path = TEMP_DIR
    outputs_dir: Path = OUTPUTS_DIR
    image: ImageConfig = ImageConfig()


settings = Settings()
configure_process_environment()


def image_resolution_options() -> list[dict[str, str | int | bool]]:
    current = (
        settings.image.base_width,
        settings.image.base_height,
        settings.image.target_width,
        settings.image.target_height,
    )
    preset_info = {
        (512, 512, 1024, 1024): ("Speed", "Fast draft, lower detail."),
        (640, 640, 1280, 1280): ("Balanced", "Default play quality."),
        (704, 704, 1408, 1408): ("Detail", "Slower guarded render."),
    }
    options: list[dict[str, str | int | bool]] = []
    for base_w, base_h, target_w, target_h in IMAGE_RESOLUTION_PRESETS:
        value = f"{base_w}x{base_h}:{target_w}x{target_h}"
        name, description = preset_info.get(
            (base_w, base_h, target_w, target_h),
            ("Custom", "Custom render size."),
        )
        label = f"{name} - {base_w} to {target_w}"
        options.append(
            {
                "value": value,
                "label": label,
                "name": name,
                "description": description,
                "base_width": base_w,
                "base_height": base_h,
                "target_width": target_w,
                "target_height": target_h,
                "selected": (base_w, base_h, target_w, target_h) == current,
            }
        )
    return options


def ensure_runtime_dirs() -> None:
    temp_dir = settings.temp_dir
    localappdata_dir = settings.runtime_dir / "localappdata"
    cache_dir = settings.runtime_dir / "cache"
    configure_process_environment()
    os.environ["TMP"] = str(temp_dir)
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMPDIR"] = str(temp_dir)
    os.environ["SQLITE_TMPDIR"] = str(temp_dir)
    os.environ["LOCALAPPDATA"] = str(localappdata_dir)
    os.environ["XDG_CACHE_HOME"] = str(cache_dir)
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    (settings.runtime_dir / "logs").mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    localappdata_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
