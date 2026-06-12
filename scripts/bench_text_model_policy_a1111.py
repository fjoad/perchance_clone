"""Compare text models under the chosen A1111 production runtime policy.

Fixed architecture:
  stream story -> small image prompt call -> unload text -> A1111 image

This intentionally keeps the image backend/settings stable. The goal is to see
which text model gives the best real turn timing and reviewable outputs without
ever keeping multiple text models loaded at once.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bench_architecture_speed_a1111 import (
    DEFAULT_A1111_BASE,
    DEFAULT_CHECKPOINT,
    OUT_DIR,
    Tee,
    a1111_ready,
    build_direct_image_prompt_messages,
    chat_once,
    ensure_ollama,
    final_negative_prompt,
    final_positive_prompt,
    generate_image,
    ollama_get,
    parse_sections,
    resource_snapshot,
    set_a1111_options,
    stream_chat,
    text_metrics,
    unload_model,
    write_text,
)
from bench_runtime_policy_a1111 import USER_MESSAGES, build_story_messages, ollama_ps_entry, timed_unload

DEFAULT_TEXT_MODELS = [
    "hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M",
    "hf.co/mradermacher/Peach-2.0-9B-8k-Roleplay-GGUF:Q5_K_M",
]


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_").lower()


def model_aliases(model: str) -> set[str]:
    aliases = {model}
    if ":" not in model:
        aliases.add(model + ":latest")
    if model.endswith(":latest"):
        aliases.add(model[:-7])
    aliases.add(model.split(":", 1)[0])
    return aliases


def assert_models_present(models: list[str]) -> None:
    tags = ollama_get("/api/tags", timeout=10).get("models", [])
    known: set[str] = set()
    for item in tags:
        known.add(item.get("name", ""))
        known.add(item.get("model", ""))
    known |= {name[:-7] for name in known if name.endswith(":latest")}
    missing = [model for model in models if not (model_aliases(model) & known)]
    if missing:
        raise RuntimeError(
            "Missing local Ollama model(s); refusing to auto-download during benchmark:\n"
            + "\n".join(f"  - {model}" for model in missing)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare candidate text models in the real A1111 flow.")
    parser.add_argument("--character-file", default=str(Path(__file__).resolve().parents[1] / "characters" / "atago.txt"))
    parser.add_argument("--base-url", default=DEFAULT_A1111_BASE)
    parser.add_argument("--text-model", action="append", dest="text_models", default=None)
    parser.add_argument("--checkpoint-name", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--turns", type=int, default=2)
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


def write_experiment(run_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Text Model Policy A1111 Experiment",
        "",
        f"Run ID: `{run_dir.name}`",
        "",
        "Purpose: compare candidate text models under the chosen production policy:",
        "",
        "```text",
        "stream story -> tiny image prompt call -> unload text -> A1111 image",
        "```",
        "",
        "## Summary",
        "",
        "| Model | Turn | First token | Story wall | Story load | Story tok/s | Prompt wall | Unload wall | Image wall | Turn total | Text VRAM split |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for model_record in manifest["models"]:
        for turn in model_record["turns"]:
            story = turn["story_metrics"]
            prompt = turn["image_prompt_metrics"]
            unload = turn["unload"]
            image = turn["image"]
            split = turn.get("story_split") or {}
            lines.append(
                "| "
                f"`{model_record['model']}` | {turn['turn']} | "
                f"{(story.get('first_token_s') or 0):.2f}s | "
                f"{story['wall_s']:.2f}s | "
                f"{story['load_s']:.2f}s | "
                f"{story['output_tps']:.1f} | "
                f"{prompt['wall_s']:.2f}s | "
                f"{unload.get('wall_s', 0):.2f}s | "
                f"{image['elapsed_s']:.2f}s | "
                f"{turn['turn_total_s']:.2f}s | "
                f"{split.get('size_vram_gib', 0):.2f} GiB VRAM / {split.get('size_cpu_gib', 0):.2f} GiB CPU |"
            )
    lines += ["", "## Full Trace", ""]
    for model_record in manifest["models"]:
        lines += [f"## Model: `{model_record['model']}`", ""]
        for turn in model_record["turns"]:
            lines += [
                f"### Turn {turn['turn']}",
                "",
                "User:",
                "",
                "```text",
                Path(turn["user_path"]).read_text(encoding="utf-8"),
                "```",
                "",
                "Story messages:",
                "",
                f"`{Path(turn['story_messages_path']).name}`",
                "",
                "Assistant:",
                "",
                "```text",
                Path(turn["assistant_path"]).read_text(encoding="utf-8"),
                "```",
                "",
                "Image prompt messages:",
                "",
                f"`{Path(turn['image_prompt_messages_path']).name}`",
                "",
                "Raw image prompt:",
                "",
                "```text",
                Path(turn["raw_image_prompt_path"]).read_text(encoding="utf-8"),
                "```",
                "",
                "Final positive prompt:",
                "",
                "```text",
                Path(turn["positive_prompt_path"]).read_text(encoding="utf-8"),
                "```",
                "",
                "Final negative prompt:",
                "",
                "```text",
                Path(turn["negative_prompt_path"]).read_text(encoding="utf-8"),
                "```",
                "",
                f"Image: `{Path(turn['image']['image_path']).name}`",
                "",
            ]
    write_text(run_dir / "EXPERIMENT.md", "\n".join(lines))


def main() -> int:
    args = parse_args()
    text_models = args.text_models or DEFAULT_TEXT_MODELS
    turns = USER_MESSAGES[: max(1, min(args.turns, len(USER_MESSAGES)))]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUT_DIR / f"text_model_policy_a1111_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    tee = Tee(run_dir / "report.txt")
    sys.stdout = tee
    ollama_proc: subprocess.Popen | None = None
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "args": {**vars(args), "text_models": text_models},
        "models": [],
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
        assert_models_present(text_models)

        for model_idx, model in enumerate(text_models, start=1):
            print(f"[model] {model}")
            for candidate in text_models:
                unload_model(candidate)
            model_dir = run_dir / safe_name(model)
            model_dir.mkdir(parents=True, exist_ok=True)
            conversation: list[dict[str, str]] = []
            model_record: dict[str, Any] = {"model": model, "turns": []}
            for turn_idx, user_text in enumerate(turns, start=1):
                turn_started = time.perf_counter()
                turn_dir = model_dir / f"turn{turn_idx}"
                turn_dir.mkdir(parents=True, exist_ok=True)
                write_text(turn_dir / "user.txt", user_text)
                conversation.append({"role": "user", "content": user_text})

                before_story = resource_snapshot(f"before {safe_name(model)} turn{turn_idx} story")
                story_messages = build_story_messages(sections, conversation)
                story_messages_path = turn_dir / "story_messages.json"
                write_text(story_messages_path, json.dumps(story_messages, indent=2, ensure_ascii=False))
                story_result = stream_chat(model, story_messages, num_predict=args.num_predict)
                assistant_text = story_result["content"]
                conversation.append({"role": "assistant", "content": assistant_text})
                assistant_path = turn_dir / "assistant.txt"
                write_text(assistant_path, assistant_text)
                story_metrics = text_metrics(story_result)
                story_split = ollama_ps_entry(model)
                after_story = resource_snapshot(f"after {safe_name(model)} turn{turn_idx} story")
                print(
                    f"[story] {safe_name(model)} turn{turn_idx}: "
                    f"first={story_metrics.get('first_token_s') or 0:.2f}s "
                    f"wall={story_metrics['wall_s']:.2f}s tok/s={story_metrics['output_tps']:.1f}"
                )

                prompt_messages = build_direct_image_prompt_messages(sections, assistant_text)
                image_prompt_messages_path = turn_dir / "image_prompt_messages.json"
                write_text(image_prompt_messages_path, json.dumps(prompt_messages, indent=2, ensure_ascii=False))
                prompt_result = chat_once(model, prompt_messages, num_predict=args.image_prompt_tokens)
                raw_image_prompt = prompt_result["content"]
                image_prompt_metrics = text_metrics(prompt_result)
                positive = final_positive_prompt(sections, raw_image_prompt)
                negative = final_negative_prompt(sections)
                raw_prompt_path = turn_dir / "raw_image_prompt.txt"
                positive_path = turn_dir / "positive_prompt.txt"
                negative_path = turn_dir / "negative_prompt.txt"
                write_text(raw_prompt_path, raw_image_prompt)
                write_text(positive_path, positive)
                write_text(negative_path, negative)
                after_prompt = resource_snapshot(f"after {safe_name(model)} turn{turn_idx} prompt")
                print(f"[prompt] {safe_name(model)} turn{turn_idx}: wall={image_prompt_metrics['wall_s']:.2f}s")

                unload_data = timed_unload(model)
                print(
                    f"[unload] {safe_name(model)} turn{turn_idx}: "
                    f"wall={unload_data['wall_s']:.2f}s absent={unload_data['absent_after_s']}"
                )

                image = generate_image(
                    args.base_url,
                    run_dir,
                    f"{safe_name(model)}_turn{turn_idx}",
                    positive,
                    negative,
                    args,
                    seed=60600 + (model_idx * 100) + turn_idx,
                )
                turn_total_s = time.perf_counter() - turn_started
                record = {
                    "turn": turn_idx,
                    "user_path": str(turn_dir / "user.txt"),
                    "story_messages_path": str(story_messages_path),
                    "assistant_path": str(assistant_path),
                    "image_prompt_messages_path": str(image_prompt_messages_path),
                    "raw_image_prompt_path": str(raw_prompt_path),
                    "positive_prompt_path": str(positive_path),
                    "negative_prompt_path": str(negative_path),
                    "story_metrics": story_metrics,
                    "image_prompt_metrics": image_prompt_metrics,
                    "story_split": story_split,
                    "resources_before_story": before_story,
                    "resources_after_story": after_story,
                    "resources_after_prompt": after_prompt,
                    "unload": unload_data,
                    "image": image,
                    "turn_total_s": turn_total_s,
                }
                write_text(turn_dir / "record.json", json.dumps(record, indent=2, ensure_ascii=False))
                model_record["turns"].append(record)
                print(
                    f"[turn] {safe_name(model)} turn{turn_idx}: "
                    f"total={turn_total_s:.2f}s image={image['elapsed_s']:.2f}s"
                )
            unload_model(model)
            manifest["models"].append(model_record)

        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["final_resources"] = resource_snapshot("experiment final")
        write_text(run_dir / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        write_experiment(run_dir, manifest)
        return 0
    finally:
        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["final_resources"] = resource_snapshot("experiment final cleanup")
        try:
            write_text(run_dir / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            write_experiment(run_dir, manifest)
        except Exception:
            pass
        for model in text_models:
            unload_model(model)
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
