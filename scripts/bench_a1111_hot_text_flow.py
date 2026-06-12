"""
Benchmark A1111 image generation while an Ollama text model stays hot.

This script assumes A1111 is already running with --api on http://127.0.0.1:7860.
It keeps the text model loaded across:
  warm text -> image1 -> text1 -> image2 -> text2

All cache/temp paths are forced to F: via f_only_env before anything else.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from f_only_env import (
    F_OLLAMA_EXE,
    F_OLLAMA_MODELS,
    assert_f_only_env,
    configure_f_only_env,
)

configure_f_only_env()
assert_f_only_env()

ROOT_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT_DIR / "outputs" / "diags"
OLLAMA_BASE = "http://localhost:11434"
DEFAULT_A1111_BASE = "http://127.0.0.1:7860"
DEFAULT_TEXT_MODEL = "hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M"
DEFAULT_CHECKPOINT = "novaAnimeXL_ilV120.safetensors"

CHARACTER_PROMPT = (
    "Atago from Azur Lane, tall voluptuous kemonomimi woman, long glossy jet-black hair, "
    "white ribbon, warm amber-brown eyes, beauty mark under left eye, expressive black catlike ears, "
    "fluffy black tail, white officer uniform with gold trim, black thigh-high stockings"
)
NEGATIVE_PROMPT = (
    "lowres, blurry, bad anatomy, bad hands, extra fingers, missing fingers, "
    "extra limbs, deformed, cropped, worst quality, low quality, watermark, text"
)
HARDENED_NEGATIVE_PROMPT = (
    NEGATIVE_PROMPT
    + ", separate animal, pet, animal companion, black cat, cat sitting beside her, "
    "extra character, duplicate character, detached tail, extra tail, tail not attached to body"
)

IMAGE_STEPS = [
    {
        "label": "image1",
        "scene": (
            "Atago welcomes a tired traveler into a warm luxury lounge at night. "
            "Cherry blossom motifs, amber lamplight, polished floor, soft domestic calm."
        ),
        "positive": (
            "Atago from Azur Lane, tall voluptuous kemonomimi woman, long glossy jet-black hair, "
            "white ribbon, warm amber-brown eyes, beauty mark under left eye, expressive black catlike ears, "
            "fluffy black tail, white officer uniform with gold trim, black thigh-high stockings, "
            "warm luxury lounge, night, amber lamplight, cherry blossom motifs, welcoming expression, "
            "painterly anime artwork, masterpiece, fine details, soft luminous highlights, 4k"
        ),
    },
    {
        "label": "image2",
        "scene": (
            "After a quiet conversation, Atago kneels near a low table with tea and snacks, "
            "smiling protectively while her tail curls beside the traveler."
        ),
        "positive": (
            "Atago from Azur Lane, elegant onee-san, tall curvy kemonomimi woman, glossy black hair, "
            "white ribbon, warm honey-brown eyes, black catlike ears, fluffy black tail, white officer uniform, "
            "kneeling beside low tea table, tea set, snacks, protective affectionate smile, cozy upscale room, "
            "warm ambient lighting, cherry blossom accents, painterly anime artwork, masterpiece, fine details"
        ),
    },
]

IMAGE_STEPS_HARDENED = [
    {
        "label": "image1",
        "scene": IMAGE_STEPS[0]["scene"],
        "positive": (
            "solo Atago from Azur Lane, one woman only, tall voluptuous kemonomimi woman, "
            "long glossy jet-black hair, white ribbon, warm amber-brown eyes, beauty mark under left eye, "
            "black animal ears attached to her head, single fluffy black tail attached to her lower back, "
            "white officer uniform with gold trim, black thigh-high stockings, warm luxury lounge, night, "
            "amber lamplight, cherry blossom motifs, welcoming expression, painterly anime artwork, "
            "masterpiece, fine details, soft luminous highlights, 4k"
        ),
    },
    {
        "label": "image2",
        "scene": IMAGE_STEPS[1]["scene"],
        "positive": (
            "solo Atago from Azur Lane, one woman only, elegant onee-san, tall curvy kemonomimi woman, "
            "glossy black hair, white ribbon, warm honey-brown eyes, black animal ears attached to her head, "
            "single fluffy black tail attached to her lower back, white officer uniform, kneeling beside low tea table, "
            "tea set, snacks, protective affectionate smile, cozy upscale room, warm ambient lighting, "
            "cherry blossom accents, painterly anime artwork, masterpiece, fine details"
        ),
    },
]

TEXT_STEPS = [
    {
        "label": "text1",
        "prompt": (
            "You are Atago, a warm and doting woman. A tired traveler just walked through your door. "
            "Welcome them in character with physical detail and affectionate onee-san warmth."
        ),
    },
    {
        "label": "text2",
        "prompt": (
            "Continue as Atago after serving tea. The traveler admits they are exhausted but happy to be here. "
            "Reply in character with tenderness, teasing, and a clear next moment."
        ),
    },
]

os.environ["OLLAMA_FLASH_ATTENTION"] = "1"
os.environ["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
os.environ["OLLAMA_NUM_PARALLEL"] = "1"
os.environ["OLLAMA_MAX_LOADED_MODELS"] = "1"
os.environ["OLLAMA_MODELS"] = str(F_OLLAMA_MODELS)


class Tee:
    def __init__(self, path: Path) -> None:
        self.file = path.open("w", encoding="utf-8")
        self.stdout = sys.stdout

    def write(self, data: str) -> int:
        self.stdout.write(data)
        self.file.write(data)
        return len(data)

    def flush(self) -> None:
        self.stdout.flush()
        self.file.flush()

    def close(self) -> None:
        sys.stdout = self.stdout
        self.file.close()


class MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def bytes_gib(value: int | float | None) -> float:
    return float(value or 0) / (1024**3)


def ram_snapshot() -> dict[str, float]:
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    total = bytes_gib(status.ullTotalPhys)
    available = bytes_gib(status.ullAvailPhys)
    commit_limit = bytes_gib(status.ullTotalPageFile)
    commit_available = bytes_gib(status.ullAvailPageFile)
    return {
        "ram_total_gib": total,
        "ram_available_gib": available,
        "ram_used_gib": max(total - available, 0.0),
        "ram_used_percent": float(status.dwMemoryLoad),
        "commit_limit_gib": commit_limit,
        "commit_available_gib": commit_available,
        "commit_used_gib": max(commit_limit - commit_available, 0.0),
    }


def vram_snapshot() -> tuple[float, float]:
    out = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    ).strip()
    used, free = [int(part.strip()) for part in out.split(",")]
    return used / 1024, free / 1024


def resource_snapshot(label: str) -> dict[str, Any]:
    used, free = vram_snapshot()
    return {
        "label": label,
        "time": datetime.now().isoformat(timespec="seconds"),
        "vram_used_gib": used,
        "vram_free_gib": free,
        **ram_snapshot(),
    }


def print_resources(snapshot: dict[str, Any]) -> None:
    print(
        f"[resources] {snapshot['label']}: "
        f"vram_used={snapshot['vram_used_gib']:.2f} GiB "
        f"vram_free={snapshot['vram_free_gib']:.2f} GiB "
        f"ram_used={snapshot['ram_used_gib']:.2f} GiB "
        f"commit_used={snapshot['commit_used_gib']:.2f} GiB"
    )


def post_json(url: str, payload: dict[str, Any], *, timeout: float = 3600) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body) if body.strip() else {}


def get_json(url: str, *, timeout: float = 10) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def api_get(path: str, *, timeout: float = 10) -> dict[str, Any]:
    return get_json(f"{OLLAMA_BASE}{path}", timeout=timeout)


def api_post(path: str, payload: dict[str, Any], *, timeout: float = 60) -> dict[str, Any]:
    return post_json(f"{OLLAMA_BASE}{path}", payload, timeout=timeout)


def ensure_ollama() -> subprocess.Popen | None:
    try:
        version = api_get("/api/version", timeout=2).get("version")
        print(f"[ollama] existing server: {version}")
        return None
    except Exception:
        pass
    print(f"[ollama] starting {F_OLLAMA_EXE}")
    proc = subprocess.Popen(
        [str(F_OLLAMA_EXE), "serve"],
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(45):
        try:
            version = api_get("/api/version", timeout=2).get("version")
            print(f"[ollama] started server: {version}")
            return proc
        except Exception:
            time.sleep(1)
    raise RuntimeError("Ollama did not become ready within 45 seconds.")


def model_aliases(model: str) -> set[str]:
    aliases = {model}
    if ":" not in model:
        aliases.add(model + ":latest")
    if model.endswith(":latest"):
        aliases.add(model[:-7])
    aliases.add(model.split(":", 1)[0])
    return aliases


def ollama_ps_entry(model: str) -> dict[str, Any] | None:
    aliases = model_aliases(model)
    for item in api_get("/api/ps", timeout=10).get("models", []):
        names = {item.get("name", ""), item.get("model", "")}
        names |= {name[:-7] for name in names if name.endswith(":latest")}
        if aliases & names:
            size = item.get("size") or 0
            vram = item.get("size_vram") or 0
            item["size_gib"] = bytes_gib(size)
            item["size_vram_gib"] = bytes_gib(vram)
            item["size_cpu_gib"] = bytes_gib(max(size - vram, 0))
            return item
    return None


def unload_model(model: str) -> None:
    try:
        api_post("/api/generate", {"model": model, "keep_alive": 0, "stream": False}, timeout=30)
    except Exception as exc:
        print(f"[unload warning] {model}: {exc}")


def generate_text(model: str, prompt: str, *, num_predict: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {
            "num_gpu": 99,
            "temperature": 0.7,
            "num_predict": num_predict,
        },
    }
    started = time.perf_counter()
    result = api_post("/api/chat", payload, timeout=1200)
    result["wall_s"] = time.perf_counter() - started
    return result


def text_metrics(result: dict[str, Any]) -> dict[str, Any]:
    output_tokens = int(result.get("eval_count") or 0)
    eval_ns = int(result.get("eval_duration") or 1)
    prompt_tokens = int(result.get("prompt_eval_count") or 0)
    prompt_ns = int(result.get("prompt_eval_duration") or 1)
    return {
        "output_tokens": output_tokens,
        "output_tps": output_tokens / (eval_ns / 1e9) if eval_ns else 0.0,
        "prompt_tokens": prompt_tokens,
        "prompt_tps": prompt_tokens / (prompt_ns / 1e9) if prompt_ns else 0.0,
        "load_s": int(result.get("load_duration") or 0) / 1e9,
        "wall_s": result.get("wall_s") or 0.0,
    }


def a1111_ready(base_url: str) -> dict[str, Any]:
    try:
        return get_json(f"{base_url.rstrip('/')}/sdapi/v1/options", timeout=5)
    except Exception as exc:
        raise RuntimeError(
            f"A1111 is not reachable at {base_url}. Start it with --api first. Error: {exc}"
        ) from exc


def set_a1111_options(base_url: str, checkpoint: str, clip_skip: int) -> None:
    options: dict[str, Any] = {"CLIP_stop_at_last_layers": clip_skip}
    if checkpoint:
        options["sd_model_checkpoint"] = checkpoint
    post_json(f"{base_url.rstrip('/')}/sdapi/v1/options", options, timeout=120)


def image_steps_for_style(prompt_style: str) -> list[dict[str, str]]:
    if prompt_style == "hardened":
        return IMAGE_STEPS_HARDENED
    return IMAGE_STEPS


def negative_prompt_for_style(prompt_style: str) -> str:
    if prompt_style == "hardened":
        return HARDENED_NEGATIVE_PROMPT
    return NEGATIVE_PROMPT


def generate_image(
    base_url: str,
    step: dict[str, str],
    run_dir: Path,
    *,
    width: int,
    height: int,
    hr_scale: float,
    steps: int,
    hr_second_pass_steps: int,
    cfg: float,
    denoise: float,
    sampler_name: str,
    scheduler: str,
    hr_upscaler: str,
    seed: int,
    negative_prompt: str,
) -> dict[str, Any]:
    label = step["label"]
    prompt = step.get("positive") or (
        f"{CHARACTER_PROMPT}, {step['scene']}, painterly anime artwork, masterpiece, "
        "fine details, soft luminous highlights, 4k"
    )
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "steps": steps,
        "cfg_scale": cfg,
        "width": width,
        "height": height,
        "seed": seed,
        "sampler_name": sampler_name,
        "scheduler": scheduler,
        "enable_hr": True,
        "hr_scale": hr_scale,
        "hr_upscaler": hr_upscaler,
        "hr_second_pass_steps": hr_second_pass_steps,
        "denoising_strength": denoise,
        "save_images": False,
        "send_images": True,
    }
    before = resource_snapshot(f"before {label}")
    print_resources(before)
    print(f"[a1111 image] {label} prompt={prompt}")
    started = time.perf_counter()
    response = post_json(f"{base_url.rstrip('/')}/sdapi/v1/txt2img", payload, timeout=3600)
    elapsed = time.perf_counter() - started
    after = resource_snapshot(f"after {label}")
    print_resources(after)
    images = response.get("images") or []
    if not images:
        raise RuntimeError("A1111 returned no images.")
    image_path = run_dir / f"{run_dir.name}_{label}_final.png"
    image_path.write_bytes(base64.b64decode(images[0]))
    settings_path = run_dir / f"{run_dir.name}_{label}_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "payload": payload,
                "info": response.get("info", ""),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[save] image={image_path}")
    print(f"[a1111 image] {label} elapsed={elapsed:.2f}s")
    return {
        "kind": "image",
        "label": label,
        "elapsed_s": elapsed,
        "image_path": str(image_path),
        "settings_path": str(settings_path),
        "payload": payload,
        "resources_before": before,
        "resources_after": after,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark A1111 images with hot Ollama text.")
    parser.add_argument("--base-url", default=DEFAULT_A1111_BASE)
    parser.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--checkpoint-name", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--num-predict", type=int, default=220)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--hr-scale", type=float, default=2.0)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--hr-second-pass-steps", type=int, default=0)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--denoise", type=float, default=0.7)
    parser.add_argument("--sampler-name", default="DPM++ 2M")
    parser.add_argument("--scheduler", default="Automatic")
    parser.add_argument("--hr-upscaler", default="Latent")
    parser.add_argument("--clip-skip", type=int, default=2)
    parser.add_argument(
        "--prompt-style",
        choices=("baseline", "hardened"),
        default="baseline",
        help=(
            "baseline uses the Diffusers comparison prompts; hardened anchors ears/tail "
            "and negatives common failures such as a separate black cat."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / f"a1111_hot_text_flow_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.txt"
    manifest_path = run_dir / "manifest.json"
    tee = Tee(report_path)
    sys.stdout = tee
    started_ollama: subprocess.Popen | None = None
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "a1111_base_url": args.base_url,
        "text_model": args.text_model,
        "image_config": vars(args),
        "prompt_style": args.prompt_style,
        "initial_resources": resource_snapshot("experiment start"),
        "steps": [],
    }
    try:
        print(f"[run dir] {run_dir}")
        print(f"[report] {report_path}")
        print(f"[a1111] checking {args.base_url}")
        options = a1111_ready(args.base_url)
        print(f"[a1111] ready current checkpoint={options.get('sd_model_checkpoint')}")
        started_ollama = ensure_ollama()
        unload_model(args.text_model)
        print("[a1111] setting options")
        set_a1111_options(args.base_url, args.checkpoint_name, args.clip_skip)
        image_steps = image_steps_for_style(args.prompt_style)
        negative_prompt = negative_prompt_for_style(args.prompt_style)
        print(f"[prompt style] {args.prompt_style}")
        print(f"[negative prompt] {negative_prompt}")

        print("[text warmup] loading text model before images")
        warm = generate_text(args.text_model, "Say ready in character as Atago.", num_predict=16)
        warm_metrics = text_metrics(warm)
        warm_split = ollama_ps_entry(args.text_model)
        manifest["steps"].append(
            {
                "kind": "text_warmup",
                "metrics": warm_metrics,
                "split": warm_split,
                "resources_after": resource_snapshot("after text warmup"),
            }
        )
        print(
            f"[text warmup] load={warm_metrics['load_s']:.2f}s "
            f"tok_s={warm_metrics['output_tps']:.1f}"
        )

        image1 = generate_image(
            args.base_url,
            image_steps[0],
            run_dir,
            width=args.width,
            height=args.height,
            hr_scale=args.hr_scale,
            steps=args.steps,
            hr_second_pass_steps=args.hr_second_pass_steps,
            cfg=args.cfg,
            denoise=args.denoise,
            sampler_name=args.sampler_name,
            scheduler=args.scheduler,
            hr_upscaler=args.hr_upscaler,
            seed=10101,
            negative_prompt=negative_prompt,
        )
        manifest["steps"].append(image1)

        for index, text_step in enumerate(TEXT_STEPS, start=1):
            label = text_step["label"]
            before = resource_snapshot(f"before {label}")
            print_resources(before)
            print(f"[text] {label} prompt={text_step['prompt']}")
            result = generate_text(args.text_model, text_step["prompt"], num_predict=args.num_predict)
            metrics = text_metrics(result)
            split = ollama_ps_entry(args.text_model)
            after = resource_snapshot(f"after {label}")
            print_resources(after)
            text = (result.get("message") or {}).get("content") or ""
            text_path = run_dir / f"{run_dir.name}_{label}.txt"
            text_path.write_text(text, encoding="utf-8")
            print(
                f"[text] {label} load={metrics['load_s']:.2f}s "
                f"wall={metrics['wall_s']:.2f}s tok_s={metrics['output_tps']:.1f}"
            )
            print(text)
            manifest["steps"].append(
                {
                    "kind": "text",
                    "label": label,
                    "text_path": str(text_path),
                    "metrics": metrics,
                    "split": split,
                    "resources_before": before,
                    "resources_after": after,
                }
            )
            if index == 1:
                image2 = generate_image(
                    args.base_url,
                    image_steps[1],
                    run_dir,
                    width=args.width,
                    height=args.height,
                    hr_scale=args.hr_scale,
                    steps=args.steps,
                    hr_second_pass_steps=args.hr_second_pass_steps,
                    cfg=args.cfg,
                    denoise=args.denoise,
                    sampler_name=args.sampler_name,
                    scheduler=args.scheduler,
                    hr_upscaler=args.hr_upscaler,
                    seed=20202,
                    negative_prompt=negative_prompt,
                )
                manifest["steps"].append(image2)

        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["final_resources"] = resource_snapshot("experiment final")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"[manifest] {manifest_path}")
        return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[error] HTTP {exc.code}: {body}")
        manifest["error"] = f"HTTP {exc.code}: {body}"
        return 1
    except Exception as exc:
        print(f"[error] {exc}")
        manifest["error"] = repr(exc)
        return 1
    finally:
        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["final_resources"] = resource_snapshot("experiment final cleanup")
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass
        unload_model(args.text_model)
        if started_ollama is not None:
            started_ollama.terminate()
            try:
                started_ollama.wait(timeout=10)
            except subprocess.TimeoutExpired:
                started_ollama.kill()
                started_ollama.wait(timeout=10)
        tee.close()
        print(f"[report saved] {report_path}")
        print(f"[manifest saved] {manifest_path}")


if __name__ == "__main__":
    raise SystemExit(main())
