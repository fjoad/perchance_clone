"""Benchmark lean text-to-image prompt architectures with A1111.

This intentionally does not judge image quality. It measures:

1. two_call_direct_prompt:
   stream assistant text -> small non-stream image prompt call -> A1111 image
2. inline_image_marker:
   stream assistant text with an internal [[IMAGE_PROMPT: ...]] marker -> A1111 image

All style/negative wrapping is deterministic and F:-drive cache guards are applied
before any model/runtime work.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import re
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
SECTION_RE = re.compile(r"^\[([A-Z_]+)\]\s*$", re.MULTILINE)

IMAGE_PROMPT_PREFIX = "painterly anime artwork"
IMAGE_PROMPT_SUFFIX = (
    "masterpiece, fine details, breathtaking artwork, painterly art style, high quality, "
    "8k, very detailed, high resolution, exquisite composition and lighting"
)
NEGATIVE_PROMPT = (
    "(worst quality, low quality, blurry:1.3), ugly face, ugly body, malformed, "
    "extra limbs, extra fingers, bad anatomy, bad hands, low-quality, deformed, "
    "text, poorly drawn, watermark"
)

USER_MESSAGE = (
    "I step through the doorway with rain still clinging to my coat, shoulders sagging "
    "from the road. \"Atago... I think I'm completely exhausted.\""
)

STOP_MARKERS = [
    "\nUSER:",
    "\nUser:",
    "\nANON:",
    "\nAnon:",
    "\n{{user}}:",
    "\n### USER",
    "\n### User",
    "<END_TURN>",
]


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
        ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
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


def post_json_url(url: str, payload: dict[str, Any], *, timeout: float = 1800) -> dict[str, Any]:
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


def get_json_url(url: str, *, timeout: float = 10) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def ollama_get(path: str, *, timeout: float = 10) -> dict[str, Any]:
    return get_json_url(f"{OLLAMA_BASE}{path}", timeout=timeout)


def ollama_post(path: str, payload: dict[str, Any], *, timeout: float = 1800) -> dict[str, Any]:
    return post_json_url(f"{OLLAMA_BASE}{path}", payload, timeout=timeout)


def ensure_ollama(run_dir: Path) -> subprocess.Popen | None:
    try:
        version = ollama_get("/api/version", timeout=2).get("version")
        print(f"[ollama] existing server: {version}")
        return None
    except Exception:
        pass

    env = os.environ.copy()
    env["OLLAMA_MODELS"] = str(F_OLLAMA_MODELS)
    env["OLLAMA_FLASH_ATTENTION"] = "1"
    env["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
    env["OLLAMA_NUM_PARALLEL"] = "1"
    env["OLLAMA_MAX_LOADED_MODELS"] = "1"
    log = (run_dir / "ollama_server.log").open("ab")
    print(f"[ollama] starting {F_OLLAMA_EXE}")
    proc = subprocess.Popen([str(F_OLLAMA_EXE), "serve"], env=env, stdout=log, stderr=log)
    for _ in range(45):
        try:
            version = ollama_get("/api/version", timeout=2).get("version")
            print(f"[ollama] started server: {version}")
            return proc
        except Exception:
            time.sleep(1)
    raise RuntimeError("Ollama did not become ready within 45 seconds.")


def unload_model(model: str) -> None:
    try:
        ollama_post("/api/generate", {"model": model, "keep_alive": 0, "stream": False}, timeout=30)
    except Exception as exc:
        print(f"[unload warning] {model}: {exc}")


def parse_sections(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(text))
    for i, match in enumerate(matches):
        key = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[key] = text[start:end].strip()
    return sections


def clean_part(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" ,\n\r\t")


def comma_join(parts: list[str]) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        for chunk in str(part or "").split(","):
            cleaned = clean_part(chunk)
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                out.append(cleaned)
    return ", ".join(out)


def render_macros(text: str, character_name: str, user_name: str) -> str:
    return (
        text.replace("{{char}}", character_name)
        .replace("{{Char}}", character_name)
        .replace("{{CHAR}}", character_name)
        .replace("{{user}}", user_name)
        .replace("{{User}}", user_name)
        .replace("{{USER}}", user_name)
    )


def block(name: str, content: str) -> str:
    return f"<{name}>\n{(content or '').strip() or '<none>'}\n</{name}>"


def build_story_messages(sections: dict[str, str], *, inline_image: bool) -> list[dict[str, str]]:
    char_name = sections.get("NAME", "Atago").strip() or "Atago"
    source = sections.get("SOURCE_MEDIA", "").strip()
    user_name = "Anon"
    dossier = render_macros(sections.get("DOSSIER", ""), char_name, user_name)
    reminder = render_macros(sections.get("REMINDER", ""), char_name, user_name)
    examples = render_macros(sections.get("EXAMPLE_DIALOGUE", ""), char_name, user_name)
    inline_rule = ""
    if inline_image:
        inline_rule = (
            "\nAfter the prose, append exactly one hidden image prompt marker on its own line:\n"
            "[[IMAGE_PROMPT: comma-separated visual prompt for the current scene]]\n"
            "The marker is for the renderer and will not be shown to the user."
        )
    system = "\n\n".join(
        [
            block(
                "TASK",
                (
                    f"You are writing {char_name} from {source} in an interactive visual novel. "
                    f"Write only {char_name}'s next turn in vivid prose and dialogue. "
                    "Use third-person narration for visible actions and double quotes for speech. "
                    "No bullets, labels, OOC notes, or analysis. Do not write Anon's next reply. "
                    "Prefer 2-4 paragraphs."
                    + inline_rule
                ),
            ),
            block("CHARACTER_PROFILE", dossier),
            block("EXAMPLE_DIALOGUE", examples),
            block("REMINDER", reminder),
        ]
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": USER_MESSAGE},
    ]


def build_direct_image_prompt_messages(sections: dict[str, str], assistant_text: str) -> list[dict[str, str]]:
    char_name = sections.get("NAME", "Atago").strip() or "Atago"
    source = sections.get("SOURCE_MEDIA", "").strip()
    appearance = sections.get("APPEARANCE", "")
    positive_additions = sections.get("IMAGE_POSITIVE", "")
    return [
        {
            "role": "system",
            "content": (
                "Create one SDXL positive prompt for the current visual novel moment. "
                "Return only comma-separated visual prompt fragments. No labels, no negative prompt, no prose."
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    block("CHARACTER", f"{char_name} from {source}"),
                    block("CHARACTER_APPEARANCE", appearance),
                    block("STYLE_HINTS", positive_additions),
                    block("ASSISTANT_TURN", assistant_text),
                    block(
                        "RENDERING_RULES",
                        "Show the character and current scene. The user/protagonist does not need to be visible unless the prompt naturally requires it.",
                    ),
                ]
            ),
        },
    ]


def stream_chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    num_predict: int,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "num_gpu": 99,
        "temperature": 0.9,
        "top_p": 0.94,
        "repeat_penalty": 1.03,
        "num_predict": num_predict,
        "stop": STOP_MARKERS,
    }
    if num_ctx:
        options["num_ctx"] = num_ctx
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": False,
        "options": options,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_s: float | None = None
    content_parts: list[str] = []
    final: dict[str, Any] = {}
    with urllib.request.urlopen(req, timeout=1800) as response:
        for raw_line in response:
            if not raw_line.strip():
                continue
            item = json.loads(raw_line.decode("utf-8", errors="replace"))
            content = (item.get("message") or {}).get("content") or ""
            if content:
                if first_token_s is None:
                    first_token_s = time.perf_counter() - started
                content_parts.append(content)
            if item.get("done"):
                final = item
                break
    wall_s = time.perf_counter() - started
    final["content"] = "".join(content_parts).strip()
    final["wall_s"] = wall_s
    final["first_token_s"] = first_token_s
    return final


def chat_once(
    model: str,
    messages: list[dict[str, str]],
    *,
    num_predict: int,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "num_gpu": 99,
        "temperature": 0.5,
        "top_p": 0.9,
        "repeat_penalty": 1.03,
        "num_predict": num_predict,
    }
    if num_ctx:
        options["num_ctx"] = num_ctx
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": options,
    }
    started = time.perf_counter()
    result = ollama_post("/api/chat", payload, timeout=900)
    result["wall_s"] = time.perf_counter() - started
    result["content"] = (result.get("message") or {}).get("content", "").strip()
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
        "first_token_s": result.get("first_token_s"),
        "done_reason": result.get("done_reason"),
    }


def split_inline_prompt(text: str) -> tuple[str, str]:
    match = re.search(r"\[\[IMAGE_PROMPT:\s*(.*?)\]\]", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return text.strip(), ""
    story = (text[: match.start()] + text[match.end() :]).strip()
    prompt = clean_part(match.group(1))
    return story, prompt


def final_positive_prompt(sections: dict[str, str], model_positive: str) -> str:
    appearance = sections.get("APPEARANCE", "")
    positive_additions = sections.get("IMAGE_POSITIVE", "")
    return comma_join([IMAGE_PROMPT_PREFIX, appearance, model_positive, positive_additions, IMAGE_PROMPT_SUFFIX])


def final_negative_prompt(sections: dict[str, str]) -> str:
    return comma_join([sections.get("IMAGE_NEGATIVE", ""), NEGATIVE_PROMPT])


def a1111_ready(base_url: str) -> None:
    get_json_url(f"{base_url.rstrip('/')}/sdapi/v1/options", timeout=5)


def set_a1111_options(base_url: str, checkpoint: str, clip_skip: int) -> None:
    post_json_url(
        f"{base_url.rstrip('/')}/sdapi/v1/options",
        {"sd_model_checkpoint": checkpoint, "CLIP_stop_at_last_layers": clip_skip},
        timeout=120,
    )


def generate_image(
    base_url: str,
    run_dir: Path,
    label: str,
    positive: str,
    negative: str,
    args: argparse.Namespace,
    seed: int,
) -> dict[str, Any]:
    payload = {
        "prompt": positive,
        "negative_prompt": negative,
        "steps": args.steps,
        "cfg_scale": args.cfg,
        "width": args.width,
        "height": args.height,
        "seed": seed,
        "sampler_name": args.sampler_name,
        "scheduler": args.scheduler,
        "enable_hr": True,
        "hr_scale": args.hr_scale,
        "hr_upscaler": args.hr_upscaler,
        "hr_second_pass_steps": args.hr_second_pass_steps,
        "denoising_strength": args.denoise,
        "save_images": False,
        "send_images": True,
    }
    before = resource_snapshot(f"before {label} image")
    print_resources(before)
    started = time.perf_counter()
    response = post_json_url(f"{base_url.rstrip('/')}/sdapi/v1/txt2img", payload, timeout=3600)
    elapsed = time.perf_counter() - started
    after = resource_snapshot(f"after {label} image")
    print_resources(after)
    images = response.get("images") or []
    if not images:
        raise RuntimeError("A1111 returned no images.")
    image_path = run_dir / f"{run_dir.name}_{label}.png"
    image_path.write_bytes(base64.b64decode(images[0]))
    settings_path = run_dir / f"{run_dir.name}_{label}_settings.json"
    settings_path.write_text(json.dumps({"payload": payload, "info": response.get("info", "")}, indent=2), encoding="utf-8")
    print(f"[image] {label} elapsed={elapsed:.2f}s path={image_path}")
    return {
        "elapsed_s": elapsed,
        "image_path": str(image_path),
        "settings_path": str(settings_path),
        "resources_before": before,
        "resources_after": after,
        "payload": payload,
    }


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"[save] {path}")


def write_experiment(run_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Lean Architecture Speed Experiment",
        "",
        f"Run ID: `{run_dir.name}`",
        "",
        "Purpose: compare how the image positive prompt is produced, not judge final image quality.",
        "",
        "Fixed code-side wrapping:",
        "",
        f"- Prefix: `{IMAGE_PROMPT_PREFIX}`",
        f"- Suffix: `{IMAGE_PROMPT_SUFFIX}`",
        f"- Negative: `{NEGATIVE_PROMPT}`",
        "",
        "## Summary",
        "",
        "| Architecture | Story wall | First token | Story tok/s | Image prompt wall | Image wall | Total after A1111 ready |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for record in manifest["records"]:
        story = record["story_metrics"]
        prompt = record["image_prompt_metrics"]
        image = record["image"]
        lines.append(
            "| "
            f"`{record['architecture']}` | "
            f"{story['wall_s']:.2f}s | "
            f"{(story.get('first_token_s') or 0):.2f}s | "
            f"{story['output_tps']:.1f} | "
            f"{prompt.get('wall_s', 0):.2f}s | "
            f"{image['elapsed_s']:.2f}s | "
            f"{record['total_after_a1111_ready_s']:.2f}s |"
        )
    lines += ["", "## Full Trace", ""]
    for record in manifest["records"]:
        lines += [
            f"### {record['architecture']}",
            "",
            "Assistant text:",
            "",
            "```text",
            Path(record["assistant_text_path"]).read_text(encoding="utf-8"),
            "```",
            "",
            "Raw image prompt produced by architecture:",
            "",
            "```text",
            Path(record["raw_image_prompt_path"]).read_text(encoding="utf-8"),
            "```",
            "",
            "Final positive prompt sent to A1111:",
            "",
            "```text",
            Path(record["positive_prompt_path"]).read_text(encoding="utf-8"),
            "```",
            "",
            "Final negative prompt sent to A1111:",
            "",
            "```text",
            Path(record["negative_prompt_path"]).read_text(encoding="utf-8"),
            "```",
            "",
            f"Image: `{Path(record['image']['image_path']).name}`",
            "",
        ]
    lines += [
        "## Notes",
        "",
        "This experiment intentionally does not score image quality. The user will judge the images. The relevant engineering question is whether the architecture is fast and stable enough.",
    ]
    write_text(run_dir / "EXPERIMENT.md", "\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark lean image-prompt architectures.")
    parser.add_argument("--character-file", default=str(ROOT_DIR / "characters" / "atago.txt"))
    parser.add_argument("--base-url", default=DEFAULT_A1111_BASE)
    parser.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--checkpoint-name", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--num-predict", type=int, default=520)
    parser.add_argument("--image-prompt-tokens", type=int, default=180)
    parser.add_argument("--width", type=int, default=704)
    parser.add_argument("--height", type=int, default=704)
    parser.add_argument("--hr-scale", type=float, default=2.0)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--hr-second-pass-steps", type=int, default=20)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--denoise", type=float, default=0.7)
    parser.add_argument("--sampler-name", default="DPM++ 2M")
    parser.add_argument("--scheduler", default="Automatic")
    parser.add_argument("--hr-upscaler", default="Latent")
    parser.add_argument("--clip-skip", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUT_DIR / f"architecture_speed_a1111_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    tee = Tee(run_dir / "report.txt")
    sys.stdout = tee
    ollama_proc: subprocess.Popen | None = None
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "args": vars(args),
        "records": [],
        "initial_resources": resource_snapshot("experiment start"),
    }
    try:
        print(f"[run dir] {run_dir}")
        sections = parse_sections(Path(args.character_file))
        write_text(run_dir / "character_card.txt", Path(args.character_file).read_text(encoding="utf-8"))
        print(f"[a1111] checking {args.base_url}")
        a1111_ready(args.base_url)
        set_a1111_options(args.base_url, args.checkpoint_name, args.clip_skip)
        ollama_proc = ensure_ollama(run_dir)
        unload_model(args.text_model)

        # Warm once so architecture timings are not dominated by first-load noise.
        print("[warmup] loading text model")
        chat_once(
            args.text_model,
            [{"role": "user", "content": "Reply with one word: ready."}],
            num_predict=4,
        )

        architectures = ["two_call_direct_prompt", "inline_image_marker"]
        for idx, architecture in enumerate(architectures, start=1):
            label = f"{idx}_{architecture}"
            arch_dir = run_dir / label
            arch_dir.mkdir(parents=True, exist_ok=True)
            start = time.perf_counter()
            before_story = resource_snapshot(f"before {architecture} story")
            print_resources(before_story)

            inline = architecture == "inline_image_marker"
            story_messages = build_story_messages(sections, inline_image=inline)
            write_text(arch_dir / "story_messages.json", json.dumps(story_messages, indent=2, ensure_ascii=False))
            story_result = stream_chat(args.text_model, story_messages, num_predict=args.num_predict)
            story_raw = story_result["content"]
            if inline:
                assistant_text, raw_image_prompt = split_inline_prompt(story_raw)
                image_prompt_metrics = {"wall_s": 0.0, "output_tps": 0.0, "output_tokens": 0}
            else:
                assistant_text = story_raw
                prompt_messages = build_direct_image_prompt_messages(sections, assistant_text)
                write_text(arch_dir / "image_prompt_messages.json", json.dumps(prompt_messages, indent=2, ensure_ascii=False))
                prompt_result = chat_once(
                    args.text_model,
                    prompt_messages,
                    num_predict=args.image_prompt_tokens,
                )
                raw_image_prompt = prompt_result["content"]
                image_prompt_metrics = text_metrics(prompt_result)

            if not raw_image_prompt:
                raw_image_prompt = comma_join([
                    sections.get("NAME", "Atago"),
                    sections.get("APPEARANCE", ""),
                    "warm interior scene, visual novel still",
                ])

            positive = final_positive_prompt(sections, raw_image_prompt)
            negative = final_negative_prompt(sections)
            write_text(arch_dir / "assistant_raw.txt", story_raw)
            write_text(arch_dir / "assistant.txt", assistant_text)
            write_text(arch_dir / "raw_image_prompt.txt", raw_image_prompt)
            write_text(arch_dir / "positive_prompt.txt", positive)
            write_text(arch_dir / "negative_prompt.txt", negative)
            after_prompt = resource_snapshot(f"after {architecture} prompt")
            print_resources(after_prompt)

            image = generate_image(args.base_url, run_dir, label, positive, negative, args, seed=40400 + idx)
            total_after_ready = time.perf_counter() - start
            record = {
                "architecture": architecture,
                "story_metrics": text_metrics(story_result),
                "image_prompt_metrics": image_prompt_metrics,
                "total_after_a1111_ready_s": total_after_ready,
                "assistant_text_path": str(arch_dir / "assistant.txt"),
                "raw_image_prompt_path": str(arch_dir / "raw_image_prompt.txt"),
                "positive_prompt_path": str(arch_dir / "positive_prompt.txt"),
                "negative_prompt_path": str(arch_dir / "negative_prompt.txt"),
                "resources_before_story": before_story,
                "resources_after_prompt": after_prompt,
                "image": image,
            }
            write_text(arch_dir / "record.json", json.dumps(record, indent=2, ensure_ascii=False))
            manifest["records"].append(record)
            print(
                f"[result] {architecture}: story={record['story_metrics']['wall_s']:.2f}s "
                f"first={record['story_metrics'].get('first_token_s') or 0:.2f}s "
                f"prompt={record['image_prompt_metrics'].get('wall_s', 0):.2f}s "
                f"image={image['elapsed_s']:.2f}s"
            )

        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["final_resources"] = resource_snapshot("experiment final")
        write_text(run_dir / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        write_experiment(run_dir, manifest)
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
            write_text(run_dir / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        except Exception:
            pass
        unload_model(args.text_model)
        if ollama_proc is not None:
            ollama_proc.terminate()
            try:
                ollama_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                ollama_proc.kill()
                ollama_proc.wait(timeout=10)
        tee.close()
        print(f"[report saved] {run_dir / 'report.txt'}")
        print(f"[manifest saved] {run_dir / 'manifest.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
