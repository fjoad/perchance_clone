from __future__ import annotations

import argparse
import json
import subprocess
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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "research_runs"
OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODELS = ["qwen-uncensored", "dolphin-llama3", "dolphin-nemo"]
DEFAULT_MODES = [
    "direct_character",
    "hybrid_narrator",
    "direct_vn_v2",
    "direct_vn_v3_inline_image",
    "direct_vn_v3_separate_image",
]
DEFAULT_MAX_SAFE_MODEL_GB = 12.0
STOP_MARKERS = [
    "\nUSER:",
    "\nUser:",
    "\nANON:",
    "\nAnon:",
    "\n{{user}}:",
    "\n### USER",
    "\n### User",
    "\n### END",
    "<END_TURN>",
]


def http_json(path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


def ensure_ollama(output_dir: Path) -> subprocess.Popen | None:
    try:
        http_json("/api/version", timeout=3)
        return None
    except Exception:
        pass
    if not F_OLLAMA_EXE.exists():
        raise FileNotFoundError(f"Ollama executable not found: {F_OLLAMA_EXE}")
    log_path = output_dir / "ollama_server.log"
    log = log_path.open("ab")
    env = {
        **dict(__import__("os").environ),
        "OLLAMA_MODELS": str(F_OLLAMA_MODELS),
        "OLLAMA_FLASH_ATTENTION": "1",
        "OLLAMA_KV_CACHE_TYPE": "q8_0",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1",
    }
    proc = subprocess.Popen(
        [str(F_OLLAMA_EXE), "serve"],
        env=env,
        stdout=log,
        stderr=log,
    )
    for _ in range(60):
        try:
            http_json("/api/version", timeout=2)
            return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError(f"Ollama did not start. See {log_path}")


def model_size_gb(model: str) -> float | None:
    aliases = {model}
    if ":" not in model:
        aliases.add(model + ":latest")
    if model.endswith(":latest"):
        aliases.add(model[:-7])
    try:
        for item in http_json("/api/tags", timeout=10).get("models", []):
            names = {item.get("name", ""), item.get("model", "")}
            names |= {name[:-7] for name in names if name.endswith(":latest")}
            if aliases & names:
                return float(item.get("size") or 0) / (1024**3)
    except Exception:
        return None
    return None


def assert_models_safe(models: list[str], *, allow_large: bool, max_safe_gb: float) -> None:
    if allow_large:
        return
    unsafe: list[str] = []
    for model in models:
        size_gb = model_size_gb(model)
        if size_gb is not None and size_gb > max_safe_gb:
            unsafe.append(f"{model} ({size_gb:.2f} GiB)")
    if unsafe:
        joined = "\n  - ".join(unsafe)
        raise RuntimeError(
            "Refusing to benchmark large Ollama model(s) without explicit override.\n"
            f"Max safe size: {max_safe_gb:.2f} GiB\n"
            f"  - {joined}\n"
            "These models can spill into system RAM and destabilize the machine. "
            "Pass --allow-large-models only for an intentional supervised stress test."
        )


def unload_model(model: str) -> None:
    try:
        http_json("/api/generate", {"model": model, "keep_alive": 0}, timeout=60)
    except Exception:
        pass


def load_gold_sample(sample_dir: Path) -> dict[str, Any]:
    turns = json.loads((sample_dir / "turns.json").read_text(encoding="utf-8"))
    return {
        "sample_dir": sample_dir,
        "metadata": json.loads((sample_dir / "metadata.json").read_text(encoding="utf-8")),
        "character_profile": (sample_dir / "character_profile.md").read_text(encoding="utf-8").strip(),
        "protagonist_profile": (sample_dir / "protagonist_profile.md").read_text(encoding="utf-8").strip(),
        "reminder_note": (sample_dir / "reminder_note.md").read_text(encoding="utf-8").strip(),
        "turns": turns,
    }


def build_system_prompt(sample: dict[str, Any], mode: str) -> str:
    character_name = sample["metadata"].get("character_name") or "the character"
    reminder_note = sample["reminder_note"]
    schema_contract = ""
    format_example = ""
    if mode == "direct_character":
        task = (
            f"You are {character_name}. Continue the roleplay as {character_name} in immersive prose and dialogue. "
            "Write only the next reply. Do not speak for the user's protagonist."
        )
    elif mode == "hybrid_narrator":
        task = (
            "You are the narrator and performer for an interactive visual novel scene. "
            "Write third-person narration and dialogue for the active non-user characters. "
            "Do not write the protagonist's dialogue, thoughts, or choices unless the user already stated them."
        )
    elif mode == "direct_vn_v2":
        task = (
            f"You are {character_name}, present inside an interactive visual novel scene. "
            f"Write {character_name}'s next turn only: visible actions, sensory atmosphere, emotional texture, and spoken dialogue. "
            "Use vivid story prose, but keep the camera anchored on what the character does and says right now."
        )
    elif mode == "direct_vn_v3_inline_image":
        task = (
            f"You are {character_name}, present inside an interactive visual novel scene. "
            f"Write {character_name}'s next turn only. Ground the scene in the supplied character and protagonist profiles. "
            "Open with one image tag, then write the in-scene response as prose and dialogue."
        )
        schema_contract = (
            "Required output shape:\n"
            "<image>one concrete visual scene prompt for the current moment, including character, setting, outfit, pose, lighting, mood</image>\n\n"
            "Then 2-4 short paragraphs of immersive roleplay prose and dialogue.\n"
            "Do not use any labels besides the image tag. Do not begin with bullets or markdown."
        )
        format_example = (
            "<image>Echidna kneeling beside Anon's armchair in the dim estate parlor, black gothic dress pooling around her knees, "
            "one pale hand resting near his wrist, firelight catching her green butterfly clip, expression soft and possessive.</image>\n\n"
            "\"Ara ara... my master,\" Echidna murmurs, her voice warm enough to soften the silence around him. "
            "Her thumb moves in a slow circle near his pulse, delicate and deliberate. "
            "\"Let me stay close until that ache in your chest remembers it is not alone.\""
        )
    elif mode == "direct_vn_v3_separate_image":
        task = (
            f"You are {character_name}, present inside an interactive visual novel scene. "
            f"Write {character_name}'s next turn only. Ground the scene in the supplied character and protagonist profiles. "
            "Return a separate image prompt field followed by the in-scene response."
        )
        schema_contract = (
            "Required output shape:\n"
            "IMAGE_PROMPT: one concrete visual scene prompt for the current moment, including character, setting, outfit, pose, lighting, mood\n\n"
            "RESPONSE:\n"
            "2-4 short paragraphs of immersive roleplay prose and dialogue.\n"
            "Do not use <image> tags in this mode. Do not begin with bullets or markdown."
        )
        format_example = (
            "IMAGE_PROMPT: Echidna kneeling beside Anon's armchair in the dim estate parlor, black gothic dress pooling around her knees, "
            "one pale hand resting near his wrist, firelight catching her green butterfly clip, expression soft and possessive.\n\n"
            "RESPONSE:\n"
            "\"Ara ara... my master,\" Echidna murmurs, her voice warm enough to soften the silence around him. "
            "Her thumb moves in a slow circle near his pulse, delicate and deliberate. "
            "\"Let me stay close until that ache in your chest remembers it is not alone.\""
        )
        reminder_note = (
            "Generate a descriptive image prompt in the IMAGE_PROMPT field. "
            "Keep the roleplay prose outside that field. Do not wrap the image prompt in tags."
        )
    else:
        raise ValueError(f"Unknown prompt mode: {mode}")
    blocks = [
        "[TASK]\n" + task,
        "[CHARACTER PROFILE]\n" + sample["character_profile"],
        "[PROTAGONIST PROFILE]\n" + sample["protagonist_profile"],
    ]
    if reminder_note:
        blocks.append("[IMMEDIATE REMINDER]\n" + reminder_note)
    if schema_contract:
        blocks.append("[OUTPUT SCHEMA]\n" + schema_contract)
    if format_example:
        blocks.append("[FORMAT EXAMPLE]\n" + format_example)
    blocks.append(
        "[RESPONSE CONTRACT]\n"
        "Continue the scene naturally. Balance action, expression, atmosphere, and dialogue. "
        "Avoid assistant commentary. Preserve user agency. Make the reply compelling enough that the user wants to continue.\n"
        "Hard turn boundary: write exactly one assistant turn. Do not write the user's next dialogue, thoughts, choices, or major physical actions. "
        "Do not continue from the user's perspective. Stop when the assistant turn is complete.\n"
        "Do not begin with markdown, bullets, dashes, labels, or speaker tags."
    )
    return "\n\n".join(blocks)


def build_messages(sample: dict[str, Any], mode: str, user_turn_index: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    turns = sample["turns"]
    user_indices = [i for i, turn in enumerate(turns) if turn["role"] == "user"]
    selected_index = user_indices[user_turn_index]
    history = turns[: selected_index + 1]
    reference = None
    for turn in turns[selected_index + 1:]:
        if turn["role"] == "assistant":
            reference = turn
            break
    messages = [{"role": "system", "content": build_system_prompt(sample, mode)}]
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["message"]})
    return messages, {
        "user_turn_index": user_turn_index,
        "source_turn_order": turns[selected_index].get("order"),
        "reference_turn_order": reference.get("order") if reference else None,
        "reference_reply": reference.get("message") if reference else "",
    }


def stream_chat(model: str, messages: list[dict[str, str]], *, max_tokens: int, temperature: float) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": False,
        "options": {
            "temperature": temperature,
            "top_p": 0.94,
            "repeat_penalty": 1.03,
            "num_predict": max_tokens,
            "stop": STOP_MARKERS,
        },
    }
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    first_token_at: float | None = None
    content_parts: list[str] = []
    final: dict[str, Any] = {}
    with urllib.request.urlopen(req, timeout=900) as resp:
        for raw_line in resp:
            if not raw_line.strip():
                continue
            chunk = json.loads(raw_line.decode("utf-8"))
            msg = chunk.get("message") or {}
            content = msg.get("content") or ""
            if content and first_token_at is None:
                first_token_at = time.perf_counter()
            if content:
                content_parts.append(content)
            if chunk.get("done"):
                final = chunk
                break
    end = time.perf_counter()
    text = "".join(content_parts)
    eval_count = final.get("eval_count") or 0
    eval_duration = final.get("eval_duration") or 0
    return {
        "reply": text,
        "wall_time_s": end - start,
        "first_token_latency_s": (first_token_at - start) if first_token_at else None,
        "eval_count": eval_count,
        "eval_duration_ns": eval_duration,
        "tokens_per_second": (eval_count / (eval_duration / 1e9)) if eval_count and eval_duration else None,
        "load_duration_ns": final.get("load_duration"),
        "prompt_eval_count": final.get("prompt_eval_count"),
        "prompt_eval_duration_ns": final.get("prompt_eval_duration"),
        "done_reason": final.get("done_reason"),
        "created_at": final.get("created_at"),
    }


def safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value).strip("_") or "item"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run text models against a Perchance gold sample.")
    parser.add_argument("sample_dir", type=Path)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--modes", nargs="+", default=DEFAULT_MODES)
    parser.add_argument("--turns", type=int, default=3, help="Number of user turns to test.")
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--temperature", type=float, default=0.85)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--keep-server", action="store_true")
    parser.add_argument("--allow-large-models", action="store_true")
    parser.add_argument("--max-safe-model-gb", type=float, default=DEFAULT_MAX_SAFE_MODEL_GB)
    args = parser.parse_args()

    configure_f_only_env()
    assert_f_only_env()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sample_name = args.sample_dir.name
    run_dir = args.output_root / stamp / "text_gold" / sample_name
    run_dir.mkdir(parents=True, exist_ok=True)

    sample = load_gold_sample(args.sample_dir)
    proc = ensure_ollama(run_dir)
    assert_models_safe(
        args.models,
        allow_large=args.allow_large_models,
        max_safe_gb=args.max_safe_model_gb,
    )
    summary: list[dict[str, Any]] = []

    try:
        user_turns_available = sum(1 for turn in sample["turns"] if turn["role"] == "user")
        turns_to_run = min(args.turns, user_turns_available)
        for model in args.models:
            for mode in args.modes:
                for turn_index in range(turns_to_run):
                    messages, turn_meta = build_messages(sample, mode, turn_index)
                    out_dir = run_dir / safe_slug(model) / mode / f"turn_{turn_index + 1:03d}"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / "rendered_messages.json").write_text(
                        json.dumps(messages, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    (out_dir / "reference_reply.txt").write_text(turn_meta["reference_reply"], encoding="utf-8")
                    print(f"[run] model={model} mode={mode} turn={turn_index + 1}")
                    try:
                        result = stream_chat(
                            model,
                            messages,
                            max_tokens=args.max_tokens,
                            temperature=args.temperature,
                        )
                        (out_dir / "reply.txt").write_text(result["reply"], encoding="utf-8")
                        metrics = {
                            "model": model,
                            "mode": mode,
                            **turn_meta,
                            **{k: v for k, v in result.items() if k != "reply"},
                        }
                        (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
                        summary.append(metrics)
                    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError) as exc:
                        error = {
                            "model": model,
                            "mode": mode,
                            **turn_meta,
                            "error": repr(exc),
                        }
                        (out_dir / "error.json").write_text(json.dumps(error, indent=2), encoding="utf-8")
                        summary.append(error)
                    finally:
                        unload_model(model)
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({"run_dir": str(run_dir), "runs": len(summary)}, indent=2))
    finally:
        if proc is not None and not args.keep_server:
            proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
