"""Longer winning-policy flow test for local visual novel runtime.

Fixed production policy:
  stream story -> small image prompt call -> unload text -> A1111 image

This answers the practical question: as the conversation grows over several
turns, do first-token latency, output speed, VRAM, and total turn time stay in
the usable range?
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
    parse_sections,
    resource_snapshot,
    set_a1111_options,
    stream_chat,
    text_metrics,
    unload_model,
    write_text,
)
from bench_runtime_policy_a1111 import build_story_messages, ollama_ps_entry, timed_unload

DEFAULT_TEXT_MODEL = "hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M"
IMAGE_PROMPT_MODES = ("model_call", "assistant_digest")

USER_MESSAGES = [
    (
        "I step through the doorway with rain still clinging to my coat, shoulders sagging "
        "from the road. \"Atago... I think I'm completely exhausted.\""
    ),
    (
        "I accept the tea with both hands and sink into the warmth of the room. "
        "\"I'm tired, but... I'm happy I made it here.\""
    ),
    (
        "I glance toward the hallway, then back to her. \"Could you stay with me a little longer? "
        "I don't really want to be alone yet.\""
    ),
    (
        "I let out a slow breath and look down at the blanket around my shoulders. "
        "\"Maybe I pushed myself too hard. I didn't want to worry you.\""
    ),
    (
        "I give her a tired smile. \"If I fall asleep here, promise you won't laugh at me too much?\""
    ),
    (
        "I look toward the rain-streaked window. \"Tomorrow can wait. I just want tonight to feel safe.\""
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a longer A1111/text winning-policy flow.")
    parser.add_argument("--character-file", default=str(Path(__file__).resolve().parents[1] / "characters" / "atago.txt"))
    parser.add_argument("--base-url", default=DEFAULT_A1111_BASE)
    parser.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--checkpoint-name", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--turns", type=int, default=6)
    parser.add_argument("--num-ctx", type=int, default=0)
    parser.add_argument("--num-predict", type=int, default=520)
    parser.add_argument("--image-prompt-tokens", type=int, default=180)
    parser.add_argument("--image-prompt-mode", choices=IMAGE_PROMPT_MODES, default="model_call")
    parser.add_argument("--assistant-digest-chars", type=int, default=700)
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


def assistant_digest_prompt(assistant_text: str, *, max_chars: int) -> str:
    """Cheap deterministic fallback: turn story prose into visual prompt text.

    This is intentionally simple. The experiment is meant to measure whether we
    can skip the second model call at all, not to solve perfect prompt parsing.
    """
    text = assistant_text
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r'"[^"]*"', " ", text)
    text = re.sub(r"“[^”]*”", " ", text)
    text = re.sub(r"\bAtago\s*:\s*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[*_`#>-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].strip()
    return text


def write_experiment(run_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Long Flow A1111 Experiment",
        "",
        f"Run ID: `{run_dir.name}`",
        "",
        "Purpose: test the winning production policy over a longer conversation.",
        "",
        "```text",
        "stream story -> tiny image prompt call -> unload text -> A1111 image",
        "```",
        "",
        "## Summary",
        "",
        "| Turn | Prompt tokens | First token | Story wall | Story load | Story tok/s | Prompt wall | Unload wall | Image wall | Turn total | Text VRAM split |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for turn in manifest["turns"]:
        story = turn["story_metrics"]
        prompt = turn["image_prompt_metrics"]
        unload = turn["unload"]
        image = turn["image"]
        split = turn.get("story_split") or {}
        lines.append(
            "| "
            f"{turn['turn']} | "
            f"{story.get('prompt_tokens', 0)} | "
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
    for turn in manifest["turns"]:
        lines += [
            f"## Turn {turn['turn']}",
            "",
            "User:",
            "",
            "```text",
            Path(turn["user_path"]).read_text(encoding="utf-8"),
            "```",
            "",
            "Assistant:",
            "",
            "```text",
            Path(turn["assistant_path"]).read_text(encoding="utf-8"),
            "```",
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
    turns = USER_MESSAGES[: max(1, min(args.turns, len(USER_MESSAGES)))]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUT_DIR / f"long_flow_a1111_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    tee = Tee(run_dir / "report.txt")
    sys.stdout = tee
    ollama_proc: subprocess.Popen | None = None
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "args": vars(args),
        "image_prompt_mode": args.image_prompt_mode,
        "turns": [],
        "initial_resources": resource_snapshot("experiment start"),
    }
    try:
        print(f"[run dir] {run_dir}")
        sections = parse_sections(Path(args.character_file))
        write_text(run_dir / "character_card.txt", Path(args.character_file).read_text(encoding="utf-8"))
        a1111_ready(args.base_url)
        set_a1111_options(args.base_url, args.checkpoint_name, args.clip_skip)
        ollama_proc = ensure_ollama(run_dir)
        unload_model(args.text_model)

        conversation: list[dict[str, str]] = []
        for turn_idx, user_text in enumerate(turns, start=1):
            turn_started = time.perf_counter()
            turn_dir = run_dir / f"turn{turn_idx}"
            turn_dir.mkdir(parents=True, exist_ok=True)
            write_text(turn_dir / "user.txt", user_text)
            conversation.append({"role": "user", "content": user_text})

            before_story = resource_snapshot(f"before turn{turn_idx} story")
            story_messages = build_story_messages(sections, conversation)
            write_text(turn_dir / "story_messages.json", json.dumps(story_messages, indent=2, ensure_ascii=False))
            story_result = stream_chat(
                args.text_model,
                story_messages,
                num_predict=args.num_predict,
                num_ctx=args.num_ctx or None,
            )
            assistant_text = story_result["content"]
            conversation.append({"role": "assistant", "content": assistant_text})
            write_text(turn_dir / "assistant.txt", assistant_text)
            story_metrics = text_metrics(story_result)
            story_split = ollama_ps_entry(args.text_model)
            after_story = resource_snapshot(f"after turn{turn_idx} story")
            print(
                f"[story] turn{turn_idx}: prompt_tokens={story_metrics['prompt_tokens']} "
                f"first={story_metrics.get('first_token_s') or 0:.2f}s "
                f"wall={story_metrics['wall_s']:.2f}s tok/s={story_metrics['output_tps']:.1f}"
            )

            image_prompt_messages_path = turn_dir / "image_prompt_messages.json"
            if args.image_prompt_mode == "model_call":
                prompt_messages = build_direct_image_prompt_messages(sections, assistant_text)
                write_text(image_prompt_messages_path, json.dumps(prompt_messages, indent=2, ensure_ascii=False))
                prompt_result = chat_once(
                    args.text_model,
                    prompt_messages,
                    num_predict=args.image_prompt_tokens,
                    num_ctx=args.num_ctx or None,
                )
                raw_image_prompt = prompt_result["content"]
                image_prompt_metrics = text_metrics(prompt_result)
            else:
                prompt_started = time.perf_counter()
                raw_image_prompt = assistant_digest_prompt(
                    assistant_text,
                    max_chars=args.assistant_digest_chars,
                )
                write_text(
                    image_prompt_messages_path,
                    json.dumps(
                        {
                            "mode": args.image_prompt_mode,
                            "source": "assistant_text",
                            "assistant_digest_chars": args.assistant_digest_chars,
                        },
                        indent=2,
                    ),
                )
                image_prompt_metrics = {
                    "output_tokens": 0,
                    "output_tps": 0.0,
                    "prompt_tokens": 0,
                    "prompt_tps": 0.0,
                    "load_s": 0.0,
                    "wall_s": time.perf_counter() - prompt_started,
                    "first_token_s": None,
                    "done_reason": "deterministic",
                }
            positive = final_positive_prompt(sections, raw_image_prompt)
            negative = final_negative_prompt(sections)
            write_text(turn_dir / "raw_image_prompt.txt", raw_image_prompt)
            write_text(turn_dir / "positive_prompt.txt", positive)
            write_text(turn_dir / "negative_prompt.txt", negative)
            after_prompt = resource_snapshot(f"after turn{turn_idx} prompt")
            print(f"[prompt] turn{turn_idx}: wall={image_prompt_metrics['wall_s']:.2f}s")

            unload_data = timed_unload(args.text_model)
            print(f"[unload] turn{turn_idx}: wall={unload_data['wall_s']:.2f}s")

            image = generate_image(
                args.base_url,
                run_dir,
                f"turn{turn_idx}",
                positive,
                negative,
                args,
                seed=70700 + turn_idx,
            )
            turn_total_s = time.perf_counter() - turn_started
            record: dict[str, Any] = {
                "turn": turn_idx,
                "user_path": str(turn_dir / "user.txt"),
                "assistant_path": str(turn_dir / "assistant.txt"),
                "raw_image_prompt_path": str(turn_dir / "raw_image_prompt.txt"),
                "positive_prompt_path": str(turn_dir / "positive_prompt.txt"),
                "negative_prompt_path": str(turn_dir / "negative_prompt.txt"),
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
            manifest["turns"].append(record)
            print(f"[turn] turn{turn_idx}: total={turn_total_s:.2f}s image={image['elapsed_s']:.2f}s")

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
