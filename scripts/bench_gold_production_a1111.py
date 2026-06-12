"""Replay a Perchance gold sample through the current local production loop.

Production policy under test:
  gold-history story call -> small image-prompt call -> unload text -> A1111 image

This is intentionally a benchmark/research harness, not app code. It saves the
full trace so we can compare local text quality against the gold reference while
also measuring the real text/image runtime envelope.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any

from bench_architecture_speed_a1111 import (
    DEFAULT_A1111_BASE,
    DEFAULT_CHECKPOINT,
    OUT_DIR,
    Tee,
    a1111_ready,
    block,
    chat_once,
    comma_join,
    ensure_ollama,
    generate_image,
    resource_snapshot,
    set_a1111_options,
    stream_chat,
    text_metrics,
    unload_model,
    write_text,
)
from bench_runtime_policy_a1111 import ollama_ps_entry, timed_unload
from f_only_env import assert_f_only_env, configure_f_only_env

configure_f_only_env()
assert_f_only_env()

DEFAULT_TEXT_MODEL = "hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M"
STOP_TAG_RE = re.compile(r"</?image>", flags=re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a gold sample through the A1111 production loop.")
    parser.add_argument("--sample-dir", type=Path, default=Path("outputs/research_gold_samples/echidna"))
    parser.add_argument("--base-url", default=DEFAULT_A1111_BASE)
    parser.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--checkpoint-name", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--source-media", default="")
    parser.add_argument("--turns", type=int, default=7)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=520)
    parser.add_argument("--image-prompt-tokens", type=int, default=180)
    parser.add_argument("--temperature", type=float, default=0.85)
    parser.add_argument("--width", type=int, default=704)
    parser.add_argument("--height", type=int, default=704)
    parser.add_argument("--hr-scale", type=float, default=2.0)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--hr-second-pass-steps", type=int, default=10)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--denoise", type=float, default=0.7)
    parser.add_argument("--sampler-name", default="DPM++ 2M")
    parser.add_argument("--scheduler", default="Automatic")
    parser.add_argument("--hr-upscaler", default="Latent")
    parser.add_argument("--clip-skip", type=int, default=2)
    return parser.parse_args()


def load_gold_sample(sample_dir: Path) -> dict[str, Any]:
    return {
        "sample_dir": sample_dir,
        "metadata": json.loads((sample_dir / "metadata.json").read_text(encoding="utf-8")),
        "character_profile": (sample_dir / "character_profile.md").read_text(encoding="utf-8").strip(),
        "protagonist_profile": (sample_dir / "protagonist_profile.md").read_text(encoding="utf-8").strip(),
        "reminder_note": (sample_dir / "reminder_note.md").read_text(encoding="utf-8").strip(),
        "image_prompt_prefix": (sample_dir / "image_prompt_prefix.txt").read_text(encoding="utf-8").strip(),
        "image_prompt_suffix": (sample_dir / "image_prompt_suffix.txt").read_text(encoding="utf-8").strip(),
        "image_prompt_triggers": (sample_dir / "image_prompt_triggers.txt").read_text(encoding="utf-8").strip(),
        "turns": json.loads((sample_dir / "turns.json").read_text(encoding="utf-8")),
    }


def character_label(sample: dict[str, Any]) -> str:
    character_name = sample["metadata"].get("character_name") or "the character"
    source_media = str(sample.get("source_media") or "").strip()
    if source_media:
        return f"{character_name} from {source_media}"
    return character_name


def active_character_name(sample: dict[str, Any]) -> str:
    return str(sample["metadata"].get("character_name") or "").strip()


def filtered_image_prompt_triggers(sample: dict[str, Any]) -> str:
    """Keep only the active character's trigger block from multi-character exports."""
    triggers = sample["image_prompt_triggers"].strip()
    character_name = active_character_name(sample)
    if not triggers or not character_name:
        return triggers

    # Perchance exports can concatenate multiple character visual cards as:
    # "Echidna: ...\nMirajane: ...". Passing all of them to SDXL mixes identities.
    label_matches = list(re.finditer(r"(?m)^\s*([^:\n]{1,80})\s*:\s*", triggers))
    if not label_matches:
        return triggers

    target = character_name.casefold()
    for index, match in enumerate(label_matches):
        label = match.group(1).strip()
        start = match.end()
        end = label_matches[index + 1].start() if index + 1 < len(label_matches) else len(triggers)
        body = triggers[start:end].strip()
        if label.casefold() == target and body:
            return f"{label}: {body}"

    return triggers


def split_suffix_and_negative(suffix: str) -> tuple[str, str]:
    marker = "(negativePrompt:::"
    if marker not in suffix:
        return suffix.strip(" ,"), ""
    positive_suffix, negative_tail = suffix.split(marker, 1)
    negative = negative_tail.rsplit(")", 1)[0]
    return positive_suffix.strip(" ,"), negative.strip(" ,")


def strip_image_tags(text: str) -> str:
    return STOP_TAG_RE.sub("", text).strip()


def clean_generated_reply(text: str) -> str:
    cleaned = text.strip()
    # If the model copies the old Perchance style anyway, keep the prose and remove only the tag wrappers.
    cleaned = strip_image_tags(cleaned)
    return cleaned


def build_story_system(sample: dict[str, Any]) -> str:
    character_name = sample["metadata"].get("character_name") or "the character"
    label = character_label(sample)
    return "\n\n".join(
        [
            block(
                "TASK",
                (
                    f"You are {character_name}, present inside an interactive visual novel scene. "
                    f"Write {character_name}'s next turn only. Use visible third-person action narration "
                    "and first-person quoted dialogue from the character. Match the emotional intensity, "
                    "sensory detail, possessive intimacy, and forward momentum of the reference conversation. "
                    "Do not write the user's next reply. Do not include image tags, labels, markdown, analysis, "
                    "or out-of-character commentary. Aim for 2-4 vivid paragraphs."
                ),
            ),
            block("CHARACTER_IDENTITY_ANCHOR", label),
            block("CHARACTER_PROFILE", sample["character_profile"]),
            block("PROTAGONIST_PROFILE", sample["protagonist_profile"]),
            block("IMMEDIATE_REMINDER", sample["reminder_note"]),
            block(
                "STYLE_TARGET",
                (
                    "The desired style is visual-novel roleplay: actions are narrated externally, "
                    "dialogue is spoken directly by the character, and each reply leaves the user with "
                    "a clear emotional hook to continue."
                ),
            ),
        ]
    )


def build_messages_for_turn(sample: dict[str, Any], user_turn_index: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    turns = sample["turns"]
    user_indices = [i for i, turn in enumerate(turns) if turn["role"] == "user"]
    selected_index = user_indices[user_turn_index]
    history = turns[: selected_index + 1]
    reference = None
    for turn in turns[selected_index + 1 :]:
        if turn["role"] == "assistant":
            reference = turn
            break
    messages = [{"role": "system", "content": build_story_system(sample)}]
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["message"]})
    return messages, {
        "user_turn_index": user_turn_index,
        "source_turn_order": turns[selected_index].get("order"),
        "user_text": turns[selected_index].get("message") or "",
        "reference_turn_order": reference.get("order") if reference else None,
        "reference_reply": reference.get("message") if reference else "",
    }


def build_image_prompt_messages(sample: dict[str, Any], assistant_text: str, user_text: str) -> list[dict[str, str]]:
    label = character_label(sample)
    positive_suffix, _negative = split_suffix_and_negative(sample["image_prompt_suffix"])
    return [
        {
            "role": "system",
            "content": (
                "Create one SDXL positive prompt for the current visual novel still. "
                "Return only comma-separated visual prompt fragments. No labels, no negative prompt, no prose."
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    block("CHARACTER", label),
                    block("CHARACTER_APPEARANCE_TRIGGERS", filtered_image_prompt_triggers(sample)),
                    block("STYLE_PREFIX", sample["image_prompt_prefix"]),
                    block("STYLE_SUFFIX", positive_suffix),
                    block("USER_TURN", user_text),
                    block("ASSISTANT_TURN", assistant_text),
                    block(
                        "RENDERING_RULES",
                        (
                            "Focus on the current visible scene, character pose, outfit, expression, "
                            "setting, lighting, camera framing, and mood. The protagonist may be implied "
                            "or partially visible only if naturally needed."
                        ),
                    ),
                ]
            ),
        },
    ]


def final_positive_prompt(sample: dict[str, Any], model_positive: str) -> str:
    positive_suffix, _negative = split_suffix_and_negative(sample["image_prompt_suffix"])
    return comma_join(
        [
            sample["image_prompt_prefix"],
            character_label(sample),
            filtered_image_prompt_triggers(sample),
            model_positive,
            positive_suffix,
        ]
    )


def final_negative_prompt(sample: dict[str, Any]) -> str:
    _positive_suffix, negative = split_suffix_and_negative(sample["image_prompt_suffix"])
    return comma_join([negative])


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def generate_image_with_error_capture(
    base_url: str,
    run_dir: Path,
    turn_dir: Path,
    label: str,
    positive: str,
    negative: str,
    args: argparse.Namespace,
    seed: int,
) -> dict[str, Any]:
    try:
        return generate_image(base_url, run_dir, label, positive, negative, args, seed)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        write_text(
            turn_dir / "a1111_error.txt",
            "\n".join(
                [
                    f"HTTP {exc.code} {exc.reason}",
                    "",
                    "Response body:",
                    body,
                    "",
                    "Positive prompt:",
                    positive,
                    "",
                    "Negative prompt:",
                    negative,
                ]
            ),
        )
        raise
    except Exception as exc:
        write_text(
            turn_dir / "a1111_error.txt",
            "\n".join(
                [
                    f"{type(exc).__name__}: {exc}",
                    "",
                    "Positive prompt:",
                    positive,
                    "",
                    "Negative prompt:",
                    negative,
                ]
            ),
        )
        raise


def write_experiment(run_dir: Path, manifest: dict[str, Any]) -> None:
    turns = manifest.get("turns", [])
    lines = [
        "# Gold Production A1111 Experiment",
        "",
        f"Run ID: `{run_dir.name}`",
        "",
        "Purpose: replay a Perchance gold sample through the current local production architecture.",
        "",
        f"Character identity anchor: `{character_label(manifest)}`" if manifest.get("metadata") else "",
        "",
        "```text",
        "gold-history story call -> image prompt call -> unload text -> A1111 image",
        "```",
        "",
        "## Aggregate",
        "",
        f"- Turns: {len(turns)}",
        f"- Avg story wall: {average([t['story_metrics']['wall_s'] for t in turns]):.2f}s",
        f"- Avg first token: {average([(t['story_metrics'].get('first_token_s') or 0) for t in turns]):.2f}s",
        f"- Avg story tok/s: {average([t['story_metrics']['output_tps'] for t in turns]):.1f}",
        f"- Avg image prompt wall: {average([t['image_prompt_metrics']['wall_s'] for t in turns]):.2f}s",
        f"- Avg unload wall: {average([t['unload']['wall_s'] for t in turns]):.2f}s",
        f"- Avg image wall: {average([t['image']['elapsed_s'] for t in turns]):.2f}s",
        f"- Avg turn total: {average([t['turn_total_s'] for t in turns]):.2f}s",
        "",
        "## Summary",
        "",
        "| Turn | Prompt tokens | First token | Story wall | Story tok/s | Prompt wall | Unload wall | Image wall | Turn total | Text VRAM split |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for turn in turns:
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
            f"{story['output_tps']:.1f} | "
            f"{prompt['wall_s']:.2f}s | "
            f"{unload.get('wall_s', 0):.2f}s | "
            f"{image['elapsed_s']:.2f}s | "
            f"{turn['turn_total_s']:.2f}s | "
            f"{split.get('size_vram_gib', 0):.2f} GiB VRAM / {split.get('size_cpu_gib', 0):.2f} GiB CPU |"
        )

    lines += ["", "## Full Trace", ""]
    for turn in turns:
        lines += [
            f"## Turn {turn['turn']}",
            "",
            "User prompt:",
            "",
            "```text",
            Path(turn["user_path"]).read_text(encoding="utf-8"),
            "```",
            "",
            "Perchance reference reply:",
            "",
            "```text",
            Path(turn["reference_reply_path"]).read_text(encoding="utf-8"),
            "```",
            "",
            "Local generated reply:",
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
            "Final positive prompt sent to A1111:",
            "",
            "```text",
            Path(turn["positive_prompt_path"]).read_text(encoding="utf-8"),
            "```",
            "",
            "Final negative prompt sent to A1111:",
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = OUT_DIR / f"gold_production_a1111_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    tee = Tee(run_dir / "report.txt")
    sys.stdout = tee
    ollama_proc: subprocess.Popen | None = None
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "args": vars(args) | {"sample_dir": str(args.sample_dir)},
        "turns": [],
        "initial_resources": resource_snapshot("experiment start"),
    }
    try:
        print(f"[run dir] {run_dir}")
        sample = load_gold_sample(args.sample_dir)
        sample["source_media"] = args.source_media.strip()
        manifest["metadata"] = sample["metadata"]
        manifest["source_media"] = sample["source_media"]
        write_text(run_dir / "gold_metadata.json", json.dumps(sample["metadata"], indent=2, ensure_ascii=False))
        write_text(run_dir / "source_media.txt", sample["source_media"])
        write_text(run_dir / "character_profile.md", sample["character_profile"])
        write_text(run_dir / "protagonist_profile.md", sample["protagonist_profile"])
        write_text(run_dir / "image_prompt_prefix.txt", sample["image_prompt_prefix"])
        write_text(run_dir / "image_prompt_suffix.txt", sample["image_prompt_suffix"])
        write_text(run_dir / "image_prompt_triggers.txt", sample["image_prompt_triggers"])
        write_text(run_dir / "image_prompt_triggers_filtered.txt", filtered_image_prompt_triggers(sample))

        a1111_ready(args.base_url)
        set_a1111_options(args.base_url, args.checkpoint_name, args.clip_skip)
        ollama_proc = ensure_ollama(run_dir)
        unload_model(args.text_model)

        user_turns_available = sum(1 for turn in sample["turns"] if turn["role"] == "user")
        turns_to_run = max(1, min(args.turns, user_turns_available))
        for turn_idx in range(turns_to_run):
            turn_started = time.perf_counter()
            turn_num = turn_idx + 1
            turn_dir = run_dir / f"turn{turn_num:03d}"
            turn_dir.mkdir(parents=True, exist_ok=True)
            story_messages, meta = build_messages_for_turn(sample, turn_idx)
            write_text(turn_dir / "story_messages.json", json.dumps(story_messages, indent=2, ensure_ascii=False))
            write_text(turn_dir / "user.txt", meta["user_text"])
            write_text(turn_dir / "reference_reply.txt", meta["reference_reply"])

            before_story = resource_snapshot(f"before turn{turn_num} story")
            story_result = stream_chat(
                args.text_model,
                story_messages,
                num_predict=args.num_predict,
                num_ctx=args.num_ctx,
            )
            assistant_text = clean_generated_reply(story_result["content"])
            write_text(turn_dir / "assistant.txt", assistant_text)
            story_metrics = text_metrics(story_result)
            story_split = ollama_ps_entry(args.text_model)
            after_story = resource_snapshot(f"after turn{turn_num} story")
            print(
                f"[story] turn{turn_num}: prompt_tokens={story_metrics['prompt_tokens']} "
                f"first={story_metrics.get('first_token_s') or 0:.2f}s "
                f"wall={story_metrics['wall_s']:.2f}s tok/s={story_metrics['output_tps']:.1f}"
            )

            prompt_messages = build_image_prompt_messages(sample, assistant_text, meta["user_text"])
            write_text(turn_dir / "image_prompt_messages.json", json.dumps(prompt_messages, indent=2, ensure_ascii=False))
            prompt_result = chat_once(
                args.text_model,
                prompt_messages,
                num_predict=args.image_prompt_tokens,
                num_ctx=args.num_ctx,
            )
            raw_image_prompt = prompt_result["content"].strip()
            image_prompt_metrics = text_metrics(prompt_result)
            positive = final_positive_prompt(sample, raw_image_prompt)
            negative = final_negative_prompt(sample)
            write_text(turn_dir / "raw_image_prompt.txt", raw_image_prompt)
            write_text(turn_dir / "positive_prompt.txt", positive)
            write_text(turn_dir / "negative_prompt.txt", negative)
            after_prompt = resource_snapshot(f"after turn{turn_num} prompt")
            print(f"[prompt] turn{turn_num}: wall={image_prompt_metrics['wall_s']:.2f}s")

            unload_data = timed_unload(args.text_model)
            print(f"[unload] turn{turn_num}: wall={unload_data['wall_s']:.2f}s")

            image = generate_image_with_error_capture(
                args.base_url,
                run_dir,
                turn_dir,
                f"turn{turn_num:03d}_image",
                positive,
                negative,
                args,
                seed=88000 + turn_num,
            )
            turn_total_s = time.perf_counter() - turn_started
            record: dict[str, Any] = {
                "turn": turn_num,
                "gold_meta": meta,
                "user_path": str(turn_dir / "user.txt"),
                "reference_reply_path": str(turn_dir / "reference_reply.txt"),
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
            print(f"[turn] turn{turn_num}: total={turn_total_s:.2f}s image={image['elapsed_s']:.2f}s")

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
