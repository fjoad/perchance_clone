"""
Benchmark Ollama text models while the SDXL image pipeline is resident in VRAM.

The goal is to answer one practical question:
which text models still produce usable tokens/sec while the image model is loaded?

This script is intentionally standalone and does not import the app services.
"""
from __future__ import annotations

import argparse
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
IMAGE_CHECKPOINT = HF_HOME / "novaAnimeXL_ilV120.safetensors"
OLLAMA_EXE = F_OLLAMA_EXE
OLLAMA_MODELS = F_OLLAMA_MODELS
OLLAMA_BASE = "http://localhost:11434"
OUT_DIR = ROOT_DIR / "outputs" / "diags"

DEFAULT_MODELS = [
    "qwen-uncensored",
    "dolphin-llama3",
    "dolphin-nemo",
    "fredrezones55/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:IQ4_XS",
]

PROMPT = (
    "You are Atago, a warm and doting woman. "
    "A tired traveler just walked through your door. Welcome them."
)


os.environ["OLLAMA_FLASH_ATTENTION"] = "1"
os.environ["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
os.environ["OLLAMA_NUM_PARALLEL"] = "1"
os.environ["OLLAMA_MAX_LOADED_MODELS"] = "1"


class Tee:
    def __init__(self, path: Path):
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

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stdout = OUT_DIR / "bench_ollama_stdout.log"
    stderr = OUT_DIR / "bench_ollama_stderr.log"
    print(f"[ollama] starting {OLLAMA_EXE}")
    proc = subprocess.Popen(
        [str(OLLAMA_EXE), "serve"],
        env=os.environ.copy(),
        stdout=stdout.open("w", encoding="utf-8"),
        stderr=stderr.open("w", encoding="utf-8"),
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


def print_vram(label: str) -> tuple[float, float]:
    used, free = vram_snapshot()
    print(f"[vram] {label}: used={used:.2f} GiB free={free:.2f} GiB")
    return used, free


def print_gpu_processes(label: str) -> None:
    print(f"[gpu processes] {label}")
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except subprocess.CalledProcessError as exc:
        print(f"  unavailable: {exc.output.strip()}")
        return
    if not out:
        print("  none")
        return
    for line in out.splitlines():
        print(f"  {line}")


def model_aliases(model: str) -> set[str]:
    aliases = {model}
    if ":" not in model:
        aliases.add(model + ":latest")
    if model.endswith(":latest"):
        aliases.add(model[:-7])
    aliases.add(model.split(":", 1)[0])
    return aliases


def ollama_ps_models() -> list[dict[str, Any]]:
    return api_get("/api/ps", timeout=10).get("models", [])


def ollama_ps_entry(model: str) -> dict[str, Any] | None:
    aliases = model_aliases(model)
    for item in ollama_ps_models():
        names = {item.get("name", ""), item.get("model", "")}
        names |= {name[:-7] for name in names if name.endswith(":latest")}
        if aliases & names:
            return item
    return None


def print_model_split(model: str, label: str) -> dict[str, Any] | None:
    item = ollama_ps_entry(model)
    print(f"[ollama ps] {label}: {model}")
    if not item:
        listed = ollama_ps_models()
        if listed:
            print("  model was not matched. /api/ps lists:")
            for other in listed:
                print(f"  - name={other.get('name')} model={other.get('model')}")
        else:
            print("  /api/ps lists no loaded models")
        return None

    size = item.get("size") or 0
    size_vram = item.get("size_vram") or 0
    size_cpu = max(size - size_vram, 0)
    print(f"  api name         : {item.get('name') or item.get('model')}")
    print(f"  total model size : {bytes_gib(size):.2f} GiB")
    print(f"  resident in VRAM : {bytes_gib(size_vram):.2f} GiB")
    print(f"  implied CPU/RAM  : {bytes_gib(size_cpu):.2f} GiB")
    if item.get("processor"):
        print(f"  processor        : {item['processor']}")
    return item


def unload_model(model: str) -> None:
    try:
        api_post("/api/generate", {"model": model, "keep_alive": 0}, timeout=30)
    except Exception as exc:
        print(f"[unload warning] {model}: {exc}")


def unload_models(models: list[str]) -> None:
    for model in models:
        unload_model(model)


def gpu_candidates(model: str) -> list[int]:
    if "Qwen3.6" in model or "qwen3.6" in model:
        return [99, 48, 40, 32, 24, 16, 8, 0]
    return [99]


def chat_stream(
    model: str,
    prompt: str,
    *,
    num_predict: int,
    num_gpu: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "think": False,
            "options": {
                "num_gpu": num_gpu,
                "temperature": 0.7,
                "num_predict": num_predict,
            },
        }
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    final: dict[str, Any] = {}
    first_split: dict[str, Any] | None = None
    first_chunk = True

    try:
        with urllib.request.urlopen(req, timeout=1200) as resp:
            for raw_line in resp:
                if not raw_line.strip():
                    continue
                chunk = json.loads(raw_line)
                if first_chunk:
                    first_chunk = False
                    first_split = print_model_split(model, "first stream chunk")
                    print_vram("first stream chunk")
                    print_gpu_processes("first stream chunk")
                message = chunk.get("message", {})
                if message.get("content"):
                    text_parts.append(message["content"])
                if message.get("thinking"):
                    thinking_parts.append(message["thinking"])
                if chunk.get("done"):
                    final = chunk
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc

    final.setdefault("message", {})
    final["message"]["content"] = "".join(text_parts)
    if thinking_parts:
        final["message"]["thinking"] = "".join(thinking_parts)
    return final, first_split


def print_result(model: str, result: dict[str, Any]) -> dict[str, Any]:
    message = result.get("message", {})
    text = message.get("content") or ""
    thinking = message.get("thinking") or ""
    output_tokens = int(result.get("eval_count") or 0)
    eval_ns = int(result.get("eval_duration") or 1)
    load_ns = int(result.get("load_duration") or 0)
    prompt_tokens = int(result.get("prompt_eval_count") or 0)
    prompt_ns = int(result.get("prompt_eval_duration") or 0)
    output_tps = output_tokens / (eval_ns / 1e9) if eval_ns else 0.0
    prompt_tps = prompt_tokens / (prompt_ns / 1e9) if prompt_ns else 0.0

    print("=" * 72)
    print(f"MODEL       : {model}")
    print(f"DONE REASON : {result.get('done_reason')}")
    print(f"LOAD TIME   : {load_ns / 1e9:.2f}s")
    print(f"PROMPT TOKS : {prompt_tokens} | {prompt_tps:.1f} tok/s")
    print(f"OUTPUT TOKS : {output_tokens} | {output_tps:.1f} tok/s")
    print("OUTPUT:")
    print(text or "<empty>")
    if thinking:
        print("\nTHINKING FIELD:")
        print(thinking)
    print("=" * 72)
    return {
        "model": model,
        "done_reason": result.get("done_reason"),
        "load_s": load_ns / 1e9,
        "prompt_tokens": prompt_tokens,
        "prompt_tps": prompt_tps,
        "output_tokens": output_tokens,
        "output_tps": output_tps,
        "output_preview": text[:160].replace("\n", " "),
    }


def load_image_pipeline() -> tuple[Any, Any]:
    import torch
    from diffusers import StableDiffusionXLPipeline, StableDiffusionXLImg2ImgPipeline

    print(f"[image] loading {IMAGE_CHECKPOINT}")
    pipe = StableDiffusionXLPipeline.from_single_file(
        str(IMAGE_CHECKPOINT),
        torch_dtype=torch.float16,
        safety_checker=None,
        cache_dir=str(F_HF_HUB_CACHE),
        local_files_only=True,
    ).to("cuda")
    pipe.enable_vae_tiling()
    try:
        pipe.enable_xformers_memory_efficient_attention()
    except Exception as exc:
        print(f"[image] xformers unavailable: {exc}")

    pipe_i2i = StableDiffusionXLImg2ImgPipeline(**pipe.components).to("cuda")
    pipe_i2i.enable_vae_tiling()
    try:
        pipe_i2i.enable_xformers_memory_efficient_attention()
    except Exception:
        pass
    return pipe, pipe_i2i


def free_image_pipeline(pipe: Any, pipe_i2i: Any) -> None:
    import gc
    import torch

    del pipe_i2i
    del pipe
    gc.collect()
    torch.cuda.empty_cache()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark text models with image model loaded.")
    parser.add_argument("--num-predict", type=int, default=180)
    parser.add_argument("--skip-qwen36", action="store_true")
    parser.add_argument("--models", nargs="*", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    models = args.models or DEFAULT_MODELS
    if args.skip_qwen36:
        models = [m for m in models if "Qwen3.6" not in m and "qwen3.6" not in m]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = OUT_DIR / f"bench_image_text_split_{stamp}.txt"
    tee = Tee(report)
    sys.stdout = tee
    started_ollama: subprocess.Popen | None = None
    pipe = None
    pipe_i2i = None

    try:
        print(f"[report] {report}")
        print(f"[prompt] {PROMPT}")
        print(f"[models] {models}")
        print(f"[num_predict] {args.num_predict}")
        print(f"[ollama exe] {OLLAMA_EXE}")
        print(f"[ollama models] {OLLAMA_MODELS}")

        started_ollama = ensure_ollama()
        unload_models(models)
        print_vram("after text unload")
        print_gpu_processes("after text unload")

        pipe, pipe_i2i = load_image_pipeline()
        print_vram("after image load")
        print_gpu_processes("after image load")

        summaries: list[dict[str, Any]] = []
        for model in models:
            print("\n" + "#" * 72)
            print(f"# {model}")
            print("#" * 72)
            print_vram("before text generation")
            print_gpu_processes("before text generation")
            result = None
            first_split = None
            chosen_num_gpu = None
            started = time.perf_counter()
            for candidate in gpu_candidates(model):
                print(f"[attempt] num_gpu={candidate}")
                try:
                    result, first_split = chat_stream(
                        model,
                        PROMPT,
                        num_predict=args.num_predict,
                        num_gpu=candidate,
                    )
                    chosen_num_gpu = candidate
                    break
                except Exception as exc:
                    print(f"[attempt failed] num_gpu={candidate}: {exc}")
                    unload_model(model)
                    time.sleep(1)
            if result is None:
                print(f"[model failed] no num_gpu candidate worked for {model}")
                summaries.append(
                    {
                        "model": model,
                        "output_tps": 0.0,
                        "load_s": 0.0,
                        "wall_s": time.perf_counter() - started,
                        "num_gpu": None,
                    }
                )
                continue
            wall_s = time.perf_counter() - started
            print_vram("after text generation")
            print_gpu_processes("after text generation")
            final_split = print_model_split(model, "after generation before unload")
            summary = print_result(model, result)
            summary["wall_s"] = wall_s
            summary["num_gpu"] = chosen_num_gpu
            if first_split:
                summary["first_size_vram_gib"] = bytes_gib(first_split.get("size_vram"))
                summary["first_size_cpu_gib"] = bytes_gib(
                    max((first_split.get("size") or 0) - (first_split.get("size_vram") or 0), 0)
                )
            if final_split:
                summary["final_size_vram_gib"] = bytes_gib(final_split.get("size_vram"))
                summary["final_size_cpu_gib"] = bytes_gib(
                    max((final_split.get("size") or 0) - (final_split.get("size_vram") or 0), 0)
                )
            summaries.append(summary)
            unload_model(model)
            print_vram("after text unload")

        print("\nSUMMARY")
        print("model | num_gpu | output tok/s | load s | wall s | first VRAM GiB | first CPU/RAM GiB")
        for row in summaries:
            print(
                f"{row['model']} | {row.get('num_gpu')} | {row['output_tps']:.1f} | "
                f"{row['load_s']:.2f} | "
                f"{row['wall_s']:.2f} | {row.get('first_size_vram_gib', 0):.2f} | "
                f"{row.get('first_size_cpu_gib', 0):.2f}"
            )
        return 0
    finally:
        if pipe is not None and pipe_i2i is not None:
            try:
                free_image_pipeline(pipe, pipe_i2i)
                pipe = None
                pipe_i2i = None
                import gc
                import torch

                gc.collect()
                torch.cuda.empty_cache()
                print_vram("after image free")
            except Exception as exc:
                print(f"[cleanup warning] image free failed: {exc}")
        unload_models(models)
        if started_ollama is not None:
            started_ollama.terminate()
        tee.close()
        print(f"[report saved] {report}")


if __name__ == "__main__":
    raise SystemExit(main())
