from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "app"
RUNTIME_DIR = ROOT_DIR / "runtime"
OUTPUTS_DIR = ROOT_DIR / "outputs" / "app"
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

HF_HOME = Path(r"F:\huggingface\models")
HF_HUB_CACHE = HF_HOME / "hub"
IMAGE_CHECKPOINT = HF_HOME / "novaAnimeXL_ilV120.safetensors"
IMAGE_RESOLUTION_PRESETS = (
    (512, 512, 1024, 1024),
    (640, 640, 1280, 1280),
    (768, 768, 1536, 1536),
    (896, 896, 1792, 1792),
    (1024, 1024, 2048, 2048),
)


def configure_process_environment() -> None:
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_HUB_CACHE)


@dataclass(frozen=True)
class ImageConfig:
    checkpoint: Path = IMAGE_CHECKPOINT
    base_width: int = 768
    base_height: int = 768
    target_width: int = 1536
    target_height: int = 1536
    steps: int = 20
    hires_steps: int = 20
    guidance_scale: float = 7.0
    denoise_strength: float = 0.7
    clip_skip: int = 2
    upscale_method: str = "latent"
    scheduler: str = "dpmpp_2m"
    a1111_img2img_step_math: bool = True


@dataclass(frozen=True)
class Settings:
    app_name: str = "Companion V1"
    hf_home: Path = HF_HOME
    hf_hub_cache: Path = HF_HUB_CACHE
    db_path: Path = RUNTIME_DIR / "companion_v1_app.sqlite3"
    text_model_id: str = "Qwen/Qwen2.5-7B-Instruct"
    roleplay_benchmark_model_id: str = "PygmalionAI/Pygmalion-3-12B"
    use_mock_text: bool = os.getenv("COMPANION_USE_MOCK_TEXT", "0") == "1"
    use_mock_image: bool = os.getenv("COMPANION_USE_MOCK_IMAGE", "0") == "1"
    summary_interval_user_turns: int = 6
    recent_messages_window: int = 12
    static_dir: Path = STATIC_DIR
    templates_dir: Path = TEMPLATES_DIR
    runtime_dir: Path = RUNTIME_DIR
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
    options: list[dict[str, str | int | bool]] = []
    for base_w, base_h, target_w, target_h in IMAGE_RESOLUTION_PRESETS:
        value = f"{base_w}x{base_h}:{target_w}x{target_h}"
        label = f"{base_w} -> {target_w}"
        options.append(
            {
                "value": value,
                "label": label,
                "base_width": base_w,
                "base_height": base_h,
                "target_width": target_w,
                "target_height": target_h,
                "selected": (base_w, base_h, target_w, target_h) == current,
            }
        )
    return options


def ensure_runtime_dirs() -> None:
    temp_dir = settings.runtime_dir / "temp"
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
