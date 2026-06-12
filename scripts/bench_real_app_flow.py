"""
Run a real app-like image/text/image/text flow and save every artifact.

This intentionally keeps the image pipeline resident while text generation runs.
For each text model:
  1. load SDXL pipeline
  2. generate a full two-pass image
  3. generate text with Ollama
  4. generate a second full two-pass image while the text model is still loaded
  5. generate text again

Outputs are copied into outputs/diags/real_app_flow_<timestamp>/.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from f_only_env import (
    F_HF_HOME,
    F_HF_HUB_CACHE,
    F_OLLAMA_EXE,
    F_OLLAMA_MODELS,
    assert_f_only_env,
    configure_f_only_env,
)

configure_f_only_env()
assert_f_only_env()

ROOT_DIR = Path(__file__).resolve().parents[1]
HF_HOME = F_HF_HOME
HF_HUB_CACHE = F_HF_HUB_CACHE
OLLAMA_EXE = F_OLLAMA_EXE
OLLAMA_MODELS = F_OLLAMA_MODELS
OLLAMA_BASE = "http://localhost:11434"
OUT_DIR = ROOT_DIR / "outputs" / "diags"

MODELS_DEFAULT = [
    "qwen-uncensored",
    "dolphin-llama3",
    "dolphin-nemo",
]
DEFAULT_MAX_SAFE_MODEL_GB = 12.0

CHARACTER = {
    "id": 0,
    "slug": "bench-atago-real-flow",
    "display_name": "Atago",
}

NEGATIVE_PROMPT = (
    "lowres, blurry, bad anatomy, bad hands, extra fingers, missing fingers, "
    "extra limbs, deformed, cropped, worst quality, low quality, watermark, text"
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

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import ensure_runtime_dirs, settings  # noqa: E402
from app.services.image_generation import image_service  # noqa: E402


class Tee:
    def __init__(self, path: Path) -> None:
        self.path = path
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


def api_get(path: str, *, timeout: float = 10) -> dict[str, Any]:
    with urllib.request.urlopen(f"{OLLAMA_BASE}{path}", timeout=timeout) as resp:
        return json.loads(resp.read())


def api_post(path: str, payload: dict[str, Any], *, timeout: float = 60) -> dict[str, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body) if body.strip() else {}


def ensure_ollama() -> subprocess.Popen | None:
    try:
        version = api_get("/api/version", timeout=2).get("version")
        print(f"[ollama] existing server: {version}")
        return None
    except Exception:
        pass

    print(f"[ollama] starting {OLLAMA_EXE}")
    proc = subprocess.Popen(
        [str(OLLAMA_EXE), "serve"],
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


def bytes_gib(value: int | float | None) -> float:
    return float(value or 0) / (1024**3)


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


def print_vram(label: str) -> tuple[float, float]:
    used, free = vram_snapshot()
    print(f"[vram] {label}: used={used:.2f} GiB free={free:.2f} GiB")
    return used, free


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
            return item
    return None


def print_model_split(model: str, label: str) -> dict[str, Any] | None:
    item = ollama_ps_entry(model)
    print(f"[ollama ps] {label}: {model}")
    if item is None:
        print("  not loaded")
        return None
    size = item.get("size") or 0
    size_vram = item.get("size_vram") or 0
    split = dict(item)
    split["size_gib"] = bytes_gib(size)
    split["size_vram_gib"] = bytes_gib(size_vram)
    split["size_cpu_gib"] = bytes_gib(max(size - size_vram, 0))
    print(f"  total model size : {split['size_gib']:.2f} GiB")
    print(f"  resident in VRAM : {split['size_vram_gib']:.2f} GiB")
    print(f"  implied CPU/RAM  : {split['size_cpu_gib']:.2f} GiB")
    return split


def listed_model_size_gb(model: str) -> float | None:
    aliases = model_aliases(model)
    try:
        for item in api_get("/api/tags", timeout=10).get("models", []):
            names = {item.get("name", ""), item.get("model", "")}
            names |= {name[:-7] for name in names if name.endswith(":latest")}
            if aliases & names:
                return bytes_gib(item.get("size") or 0)
    except Exception:
        return None
    return None


def assert_models_safe(models: list[str], *, allow_large: bool, max_safe_gb: float) -> None:
    if allow_large:
        return
    unsafe: list[str] = []
    for model in models:
        size_gb = listed_model_size_gb(model)
        if size_gb is not None and size_gb > max_safe_gb:
            unsafe.append(f"{model} ({size_gb:.2f} GiB)")
    if unsafe:
        joined = "\n  - ".join(unsafe)
        raise RuntimeError(
            "Refusing to run real-flow benchmark with large Ollama model(s).\n"
            f"Max safe size: {max_safe_gb:.2f} GiB\n"
            f"  - {joined}\n"
            "Large split models can consume system RAM and destabilize the machine. "
            "Pass --allow-large-models only for an intentional supervised stress test."
        )


def unload_model(model: str) -> None:
    try:
        api_post("/api/generate", {"model": model, "keep_alive": 0, "stream": False}, timeout=30)
    except Exception as exc:
        print(f"[unload warning] {model}: {exc}")


def wait_model_unloaded(model: str, *, timeout_s: float = 30.0) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if ollama_ps_entry(model) is None:
            return
        time.sleep(0.5)
    print(f"[unload warning] {model}: still listed by /api/ps after {timeout_s:.0f}s")


def unload_model_and_wait(model: str, label: str) -> dict[str, Any]:
    resources_before = resource_snapshot(f"before {label}")
    print_resources(resources_before)
    started = time.perf_counter()
    unload_model(model)
    wait_model_unloaded(model)
    elapsed = time.perf_counter() - started
    split_after = print_model_split(model, f"{label} after text unload wait")
    resources_after = resource_snapshot(f"after {label}")
    print_resources(resources_after)
    print(f"[cleanup] {label} elapsed={elapsed:.2f}s")
    return {
        "kind": "cleanup",
        "label": label,
        "operation": "ollama_unload_and_wait",
        "elapsed_s": elapsed,
        "resources_before": resources_before,
        "resources_after": resources_after,
        "split_after": split_after,
    }


def unload_image_and_time(label: str) -> dict[str, Any]:
    resources_before = resource_snapshot(f"before {label}")
    print_resources(resources_before)
    started = time.perf_counter()
    image_service.unload()
    elapsed = time.perf_counter() - started
    resources_after = resource_snapshot(f"after {label}")
    print_resources(resources_after)
    print(f"[cleanup] {label} elapsed={elapsed:.2f}s")
    return {
        "kind": "cleanup",
        "label": label,
        "operation": "image_unload",
        "elapsed_s": elapsed,
        "resources_before": resources_before,
        "resources_after": resources_after,
    }


def gc_collect_and_time(label: str) -> dict[str, Any]:
    resources_before = resource_snapshot(f"before {label}")
    print_resources(resources_before)
    started = time.perf_counter()
    collected = gc.collect()
    elapsed = time.perf_counter() - started
    resources_after = resource_snapshot(f"after {label}")
    print_resources(resources_after)
    print(f"[cleanup] {label} elapsed={elapsed:.2f}s collected={collected}")
    return {
        "kind": "cleanup",
        "label": label,
        "operation": "gc_collect",
        "elapsed_s": elapsed,
        "collected": collected,
        "resources_before": resources_before,
        "resources_after": resources_after,
    }


def generate_text(model: str, prompt: str, *, num_predict: int, text_num_gpu: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {
            "num_gpu": text_num_gpu,
            "temperature": 0.7,
            "num_predict": num_predict,
        },
    }
    started = time.perf_counter()
    try:
        result = api_post("/api/chat", payload, timeout=1200)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc
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


def copy_image_outputs(payload: dict[str, Any], run_dir: Path, prefix: str) -> list[Path]:
    copied: list[Path] = []
    for key in ("stage1_output_path", "output_path"):
        relative = payload.get(key)
        if not relative:
            continue
        src = settings.outputs_dir / relative
        suffix = "stage1" if key == "stage1_output_path" else "final"
        dest = run_dir / f"{run_dir.name}_{prefix}_{suffix}.png"
        shutil.copy2(src, dest)
        copied.append(dest)
        print(f"[save] {key}: {dest}")
    return copied


def generate_image(step: dict[str, str], run_dir: Path, model_slug: str) -> dict[str, Any]:
    label = step["label"]
    prefix = f"{model_slug}_{label}"
    print(f"\n[image] {label} start")
    resources_before = resource_snapshot(f"before {label}")
    print_resources(resources_before)
    started = time.perf_counter()
    payload = image_service.generate(
        character=CHARACTER,
        conversation_id=0,
        message_id=None,
        image_id=None,
        scene_summary=step["scene"],
        positive_prompt=step["positive"],
        negative_prompt=NEGATIVE_PROMPT,
    )
    elapsed = time.perf_counter() - started
    resources_after = resource_snapshot(f"after {label}")
    print_resources(resources_after)
    copied = copy_image_outputs(payload, run_dir, prefix)
    print(f"[image] {label} elapsed={elapsed:.2f}s")
    return {
        "payload": payload,
        "elapsed_s": elapsed,
        "copied": [str(path) for path in copied],
        "resources_before": resources_before,
        "resources_after": resources_after,
    }


def safe_slug(model: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in model).strip("_").lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real app image/text/image/text flow.")
    parser.add_argument("--models", nargs="*", default=MODELS_DEFAULT)
    parser.add_argument("--num-predict", type=int, default=220)
    parser.add_argument(
        "--text-num-gpu",
        type=int,
        default=99,
        help=(
            "Ollama num_gpu value for text generation. 99 means maximize GPU layers; "
            "lower values intentionally keep part of the text model on CPU/RAM."
        ),
    )
    parser.add_argument("--base-width", type=int, default=None)
    parser.add_argument("--base-height", type=int, default=None)
    parser.add_argument("--target-width", type=int, default=None)
    parser.add_argument("--target-height", type=int, default=None)
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--hires-steps", type=int, default=None)
    parser.add_argument("--denoise-strength", type=float, default=None)
    parser.add_argument(
        "--policy",
        choices=("co-resident", "swap"),
        default="co-resident",
        help=(
            "co-resident keeps image/text loaded across steps; "
            "swap unloads text before image and unloads image before text."
        ),
    )
    parser.add_argument("--allow-large-models", action="store_true")
    parser.add_argument("--max-safe-model-gb", type=float, default=DEFAULT_MAX_SAFE_MODEL_GB)
    return parser.parse_args()


def apply_image_overrides(args: argparse.Namespace) -> None:
    """Apply per-run image overrides while preserving the checked-in defaults."""
    overrides: dict[str, Any] = {}
    for arg_name, field_name in (
        ("base_width", "base_width"),
        ("base_height", "base_height"),
        ("target_width", "target_width"),
        ("target_height", "target_height"),
        ("steps", "steps"),
        ("hires_steps", "hires_steps"),
        ("denoise_strength", "denoise_strength"),
    ):
        value = getattr(args, arg_name)
        if value is not None:
            overrides[field_name] = value
    if overrides:
        object.__setattr__(settings, "image", replace(settings.image, **overrides))


def main() -> int:
    args = parse_args()
    apply_image_overrides(args)
    run_started = time.perf_counter()
    run_started_at = datetime.now().isoformat(timespec="seconds")
    ensure_runtime_dirs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / f"real_app_flow_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.txt"
    manifest_path = run_dir / "manifest.json"
    tee = Tee(report_path)
    sys.stdout = tee
    started_ollama: subprocess.Popen | None = None
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir),
        "models": args.models,
        "num_predict": args.num_predict,
        "text_num_gpu": args.text_num_gpu,
        "policy": args.policy,
        "started_at": run_started_at,
        "initial_resources": resource_snapshot("experiment start"),
        "image_config": {
            "base_width": settings.image.base_width,
            "base_height": settings.image.base_height,
            "target_width": settings.image.target_width,
            "target_height": settings.image.target_height,
            "steps": settings.image.steps,
            "hires_steps": settings.image.hires_steps,
            "denoise_strength": settings.image.denoise_strength,
            "scheduler": settings.image.scheduler,
            "upscale_method": settings.image.upscale_method,
        },
        "results": [],
    }

    try:
        print(f"[run dir] {run_dir}")
        print(f"[report] {report_path}")
        print(f"[models] {args.models}")
        print(f"[policy] {args.policy}")
        print(f"[image config] {manifest['image_config']}")
        started_ollama = ensure_ollama()
        assert_models_safe(
            args.models,
            allow_large=args.allow_large_models,
            max_safe_gb=args.max_safe_model_gb,
        )

        for model in args.models:
            model_slug = safe_slug(model)
            print("\n" + "#" * 80)
            print(f"# MODEL FLOW: {model}")
            print("#" * 80)
            model_result: dict[str, Any] = {"model": model, "steps": []}
            manifest["results"].append(model_result)
            model_result["steps"].append(unload_model_and_wait(model, "initial text cleanup"))
            model_result["steps"].append(unload_image_and_time("initial image cleanup"))
            model_result["steps"].append(gc_collect_and_time("initial gc cleanup"))
            print_vram("after clean unload")

            try:
                if args.policy == "swap":
                    model_result["steps"].append(unload_model_and_wait(model, "swap before image1 text cleanup"))
                    model_result["steps"].append(unload_image_and_time("swap before image1 image cleanup"))
                    print_vram("swap before image1 after unloads")
                image1 = generate_image(IMAGE_STEPS[0], run_dir, model_slug)
                model_result["steps"].append({"kind": "image", "label": "image1", **image1})
                if args.policy == "swap":
                    model_result["steps"].append(unload_image_and_time("swap after image1 image cleanup"))
                    print_vram("swap after image1 unload image")

                for index, text_step in enumerate(TEXT_STEPS, start=1):
                    label = text_step["label"]
                    if args.policy == "swap":
                        model_result["steps"].append(unload_image_and_time(f"swap before {label} image cleanup"))
                        print_vram(f"swap before {label} after image unload")
                    print(f"\n[text] {label} start")
                    resources_before = resource_snapshot(f"before {label}")
                    print_resources(resources_before)
                    print(f"[prompt] {text_step['prompt']}")
                    result = generate_text(
                        model,
                        text_step["prompt"],
                        num_predict=args.num_predict,
                        text_num_gpu=args.text_num_gpu,
                    )
                    metrics = text_metrics(result)
                    split = print_model_split(model, f"after {label}")
                    resources_after = resource_snapshot(f"after {label}")
                    print_resources(resources_after)
                    text = (result.get("message") or {}).get("content") or ""
                    text_path = run_dir / f"{model_slug}_{label}.txt"
                    text_path.write_text(text, encoding="utf-8")
                    print(f"[save] text: {text_path}")
                    print(
                        f"[text] {label} output_tokens={metrics['output_tokens']} "
                        f"tok_s={metrics['output_tps']:.1f} load_s={metrics['load_s']:.2f} "
                        f"wall_s={metrics['wall_s']:.2f}"
                    )
                    print("[output]")
                    print(text)
                    model_result["steps"].append(
                        {
                            "kind": "text",
                            "label": label,
                            "text_path": str(text_path),
                            "metrics": metrics,
                            "split": split,
                            "resources_before": resources_before,
                            "resources_after": resources_after,
                        }
                    )

                    if index == 1:
                        if args.policy == "swap":
                            model_result["steps"].append(
                                unload_model_and_wait(model, "swap before image2 text cleanup")
                            )
                            print_vram("swap before image2 after text unload")
                        image2 = generate_image(IMAGE_STEPS[1], run_dir, model_slug)
                        model_result["steps"].append({"kind": "image", "label": "image2", **image2})
                        if args.policy == "swap":
                            model_result["steps"].append(unload_image_and_time("swap after image2 image cleanup"))
                            print_vram("swap after image2 unload image")

            except Exception as exc:
                print(f"[model error] {model}: {exc}")
                model_result["error"] = repr(exc)
            finally:
                model_result["steps"].append(unload_model_and_wait(model, "final text cleanup"))
                model_result["steps"].append(unload_image_and_time("final image cleanup"))
                model_result["steps"].append(gc_collect_and_time("final gc cleanup"))
                print_vram("after model cleanup")

        print("\nSUMMARY")
        for model_result in manifest["results"]:
            print(f"- {model_result['model']}")
            if model_result.get("error"):
                print(f"  ERROR: {model_result['error']}")
            for step in model_result.get("steps", []):
                if step["kind"] == "text":
                    metrics = step["metrics"]
                    print(
                        f"  {step['label']}: {metrics['output_tps']:.1f} tok/s, "
                        f"{metrics['output_tokens']} tokens, saved={step['text_path']}"
                    )
                elif step["kind"] == "image":
                    print(
                        f"  {step['label']}: {step['elapsed_s']:.2f}s, "
                        f"saved={', '.join(step['copied'])}"
                    )
                elif step["kind"] == "cleanup":
                    print(
                        f"  {step['label']}: {step['operation']} "
                        f"{step['elapsed_s']:.2f}s"
                    )
        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["total_wall_s"] = time.perf_counter() - run_started
        manifest["final_resources"] = resource_snapshot("experiment final before cleanup")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"[manifest] {manifest_path}")
        return 0
    finally:
        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["total_wall_s"] = time.perf_counter() - run_started
        manifest["final_resources"] = resource_snapshot("experiment final cleanup")
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass
        try:
            image_service.unload()
            for model in args.models:
                unload_model(model)
                wait_model_unloaded(model, timeout_s=10.0)
        finally:
            if started_ollama is not None:
                started_ollama.terminate()
            tee.close()
            print(f"[report saved] {report_path}")
            print(f"[manifest saved] {manifest_path}")


if __name__ == "__main__":
    raise SystemExit(main())
