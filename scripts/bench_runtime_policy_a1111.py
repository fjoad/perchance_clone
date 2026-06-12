"""Benchmark text/image runtime policies for the chosen two-call architecture.

Architecture is fixed:
  stream story -> tiny image prompt call -> deterministic prefix/suffix/negative -> A1111 image

Runtime policy varies:
  keep_text_hot: keep Ollama model loaded during image generation.
  unload_text_before_image: unload Ollama after image prompt, then generate image.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bench_architecture_speed_a1111 import (
    DEFAULT_A1111_BASE,
    DEFAULT_CHECKPOINT,
    DEFAULT_TEXT_MODEL,
    OUT_DIR,
    Tee,
    a1111_ready,
    block,
    build_direct_image_prompt_messages,
    chat_once,
    ensure_ollama,
    final_negative_prompt,
    final_positive_prompt,
    generate_image,
    ollama_get,
    parse_sections,
    render_macros,
    resource_snapshot,
    set_a1111_options,
    stream_chat,
    text_metrics,
    unload_model,
    write_text,
)

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
]


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
    for item in ollama_get("/api/ps", timeout=10).get("models", []):
        names = {item.get("name", ""), item.get("model", "")}
        names |= {name[:-7] for name in names if name.endswith(":latest")}
        if aliases & names:
            size = int(item.get("size") or 0)
            vram = int(item.get("size_vram") or 0)
            item["size_gib"] = size / (1024**3)
            item["size_vram_gib"] = vram / (1024**3)
            item["size_cpu_gib"] = max(size - vram, 0) / (1024**3)
            return item
    return None


def timed_unload(model: str) -> dict[str, Any]:
    started = time.perf_counter()
    unload_model(model)
    absent_after_s: float | None = None
    for _ in range(30):
        if ollama_ps_entry(model) is None:
            absent_after_s = time.perf_counter() - started
            break
        time.sleep(1)
    return {
        "wall_s": time.perf_counter() - started,
        "absent_after_s": absent_after_s,
        "resources_after": resource_snapshot("after text unload"),
    }


def build_story_messages(
    sections: dict[str, str],
    conversation: list[dict[str, str]],
) -> list[dict[str, str]]:
    char_name = sections.get("NAME", "Atago").strip() or "Atago"
    source = sections.get("SOURCE_MEDIA", "").strip()
    user_name = "Anon"
    dossier = render_macros(sections.get("DOSSIER", ""), char_name, user_name)
    reminder = render_macros(sections.get("REMINDER", ""), char_name, user_name)
    examples = render_macros(sections.get("EXAMPLE_DIALOGUE", ""), char_name, user_name)
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
                ),
            ),
            block("CHARACTER_PROFILE", dossier),
            block("EXAMPLE_DIALOGUE", examples),
            block("REMINDER", reminder),
        ]
    )
    return [{"role": "system", "content": system}, *conversation]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark keep-hot vs unload-before-image runtime policies.")
    parser.add_argument("--character-file", default=str(Path(__file__).resolve().parents[1] / "characters" / "atago.txt"))
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


def write_experiment(run_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Runtime Policy A1111 Experiment",
        "",
        f"Run ID: `{run_dir.name}`",
        "",
        "Purpose: with the two-call architecture fixed, compare whether text should stay hot during image generation or unload before each image.",
        "",
        "## Summary",
        "",
        "| Policy | Turn | First token | Story wall | Story load | Story tok/s | Prompt wall | Unload wall | Image wall | Turn total | Text VRAM split |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for policy in manifest["policies"]:
        for turn in policy["turns"]:
            story = turn["story_metrics"]
            prompt = turn["image_prompt_metrics"]
            unload = turn.get("unload") or {}
            image = turn["image"]
            split = turn.get("story_split") or {}
            lines.append(
                "| "
                f"`{policy['policy']}` | {turn['turn']} | "
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
    for policy in manifest["policies"]:
        lines += [f"## Policy: `{policy['policy']}`", ""]
        for turn in policy["turns"]:
            lines += [
                f"### Turn {turn['turn']}",
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
                f"Image: `{Path(turn['image']['image_path']).name}`",
                "",
            ]
    write_text(run_dir / "EXPERIMENT.md", "\n".join(lines))


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUT_DIR / f"runtime_policy_a1111_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    tee = Tee(run_dir / "report.txt")
    sys.stdout = tee
    ollama_proc: subprocess.Popen | None = None
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "args": vars(args),
        "policies": [],
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

        for policy_name in ("keep_text_hot", "unload_text_before_image"):
            print(f"[policy] {policy_name}")
            unload_model(args.text_model)
            policy_dir = run_dir / policy_name
            policy_dir.mkdir(parents=True, exist_ok=True)
            conversation: list[dict[str, str]] = []
            policy_record: dict[str, Any] = {"policy": policy_name, "turns": []}
            for turn_idx, user_text in enumerate(USER_MESSAGES, start=1):
                turn_started = time.perf_counter()
                turn_dir = policy_dir / f"turn{turn_idx}"
                turn_dir.mkdir(parents=True, exist_ok=True)
                write_text(turn_dir / "user.txt", user_text)
                conversation.append({"role": "user", "content": user_text})

                before_story = resource_snapshot(f"before {policy_name} turn{turn_idx} story")
                story_messages = build_story_messages(sections, conversation)
                write_text(turn_dir / "story_messages.json", json.dumps(story_messages, indent=2, ensure_ascii=False))
                story_result = stream_chat(args.text_model, story_messages, num_predict=args.num_predict)
                assistant_text = story_result["content"]
                conversation.append({"role": "assistant", "content": assistant_text})
                write_text(turn_dir / "assistant.txt", assistant_text)
                story_metrics = text_metrics(story_result)
                story_split = ollama_ps_entry(args.text_model)
                after_story = resource_snapshot(f"after {policy_name} turn{turn_idx} story")
                print(
                    f"[story] {policy_name} turn{turn_idx}: "
                    f"first={story_metrics.get('first_token_s') or 0:.2f}s "
                    f"wall={story_metrics['wall_s']:.2f}s tok/s={story_metrics['output_tps']:.1f}"
                )

                prompt_messages = build_direct_image_prompt_messages(sections, assistant_text)
                write_text(turn_dir / "image_prompt_messages.json", json.dumps(prompt_messages, indent=2, ensure_ascii=False))
                prompt_result = chat_once(args.text_model, prompt_messages, num_predict=args.image_prompt_tokens)
                raw_image_prompt = prompt_result["content"]
                image_prompt_metrics = text_metrics(prompt_result)
                positive = final_positive_prompt(sections, raw_image_prompt)
                negative = final_negative_prompt(sections)
                write_text(turn_dir / "raw_image_prompt.txt", raw_image_prompt)
                write_text(turn_dir / "positive_prompt.txt", positive)
                write_text(turn_dir / "negative_prompt.txt", negative)
                after_prompt = resource_snapshot(f"after {policy_name} turn{turn_idx} prompt")
                print(
                    f"[prompt] {policy_name} turn{turn_idx}: "
                    f"wall={image_prompt_metrics['wall_s']:.2f}s"
                )

                unload_data = None
                if policy_name == "unload_text_before_image":
                    unload_data = timed_unload(args.text_model)
                    print(
                        f"[unload] {policy_name} turn{turn_idx}: "
                        f"wall={unload_data['wall_s']:.2f}s absent={unload_data['absent_after_s']}"
                    )

                image = generate_image(
                    args.base_url,
                    run_dir,
                    f"{policy_name}_turn{turn_idx}",
                    positive,
                    negative,
                    args,
                    seed=50500 + (100 * (policy_name == "unload_text_before_image")) + turn_idx,
                )
                turn_total_s = time.perf_counter() - turn_started
                record = {
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
                policy_record["turns"].append(record)
                print(
                    f"[turn] {policy_name} turn{turn_idx}: total={turn_total_s:.2f}s "
                    f"image={image['elapsed_s']:.2f}s"
                )
            manifest["policies"].append(policy_record)

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
