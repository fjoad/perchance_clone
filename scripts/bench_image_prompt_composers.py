"""Compare image prompt composer strategies without generating images.

Inputs come from an existing production-flow run folder. The benchmark compares:

1. current_labeled: loose POSITIVE/NEGATIVE text, similar to the current app path.
2. strict_json: model returns a JSON object with positive/negative strings.
3. deterministic_template: no model call; compose from character appearance + scene.

The goal is parseability and visual-novel suitability before spending time on A1111.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
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
DEFAULT_MODEL = "hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M"
SECTION_RE = re.compile(r"^\[([A-Z_]+)\]\s*$", re.MULTILINE)

BASE_NEGATIVE = (
    "lowres, blurry, bad anatomy, bad hands, extra fingers, extra limbs, text, watermark, "
    "cropped, deformed, disfigured, duplicate, extra character, multiple girls, two girls, "
    "extra limbs, detached tail, wrong ears, wrong tail color, separate animal, black cat"
)

STYLE_ANCHOR = (
    "painterly anime artwork, masterpiece, best quality, fine details, soft luminous highlights, "
    "warm ambient lighting, subtle cherry blossom motifs, visual novel CG, solo character, medium shot"
)


def post_json(path: str, payload: dict[str, Any], *, timeout: float = 900) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body) if body.strip() else {}


def get_json(path: str, *, timeout: float = 10) -> dict[str, Any]:
    with urllib.request.urlopen(f"{OLLAMA_BASE}{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def ensure_ollama(run_dir: Path) -> subprocess.Popen | None:
    try:
        version = get_json("/api/version", timeout=2).get("version")
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
    log_path = run_dir / "ollama_server.log"
    log = log_path.open("ab")
    print(f"[ollama] starting {F_OLLAMA_EXE}")
    proc = subprocess.Popen([str(F_OLLAMA_EXE), "serve"], env=env, stdout=log, stderr=log)
    for _ in range(45):
        try:
            version = get_json("/api/version", timeout=2).get("version")
            print(f"[ollama] started server: {version}")
            return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError(f"Ollama did not become ready. See {log_path}")


def unload_model(model: str) -> None:
    try:
        post_json("/api/generate", {"model": model, "keep_alive": 0, "stream": False}, timeout=30)
    except Exception as exc:
        print(f"[unload warning] {model}: {exc}")


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(text))
    for i, match in enumerate(matches):
        key = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[key] = text[start:end].strip()
    return sections


def block(name: str, content: str) -> str:
    return f"<{name}>\n{(content or '').strip() or '<none>'}\n</{name}>"


def run_chat(model: str, messages: list[dict[str, str]], *, json_mode: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "num_gpu": 99,
            "temperature": 0.2 if json_mode else 0.5,
            "top_p": 0.9,
            "repeat_penalty": 1.03,
            "num_predict": 240,
        },
    }
    if json_mode:
        payload["format"] = "json"
    started = time.perf_counter()
    result = post_json("/api/chat", payload, timeout=900)
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
        "done_reason": result.get("done_reason"),
    }


def parse_labeled_loose(raw: str) -> tuple[str, str, bool]:
    positive = ""
    negative = ""
    current: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("positive:"):
            positive = stripped.split(":", 1)[1].strip()
            current = "positive"
            continue
        if lower.startswith("negative:"):
            negative = stripped.split(":", 1)[1].strip()
            current = "negative"
            continue
        if current == "positive":
            positive = (positive + " " + stripped).strip()
        elif current == "negative":
            negative = (negative + " " + stripped).strip()
    leak = "negative:" in positive.lower()
    return positive, negative, leak


def parse_json_prompt(raw: str) -> tuple[str, str, bool, str | None]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return "", "", False, f"json_decode_error: {exc}"
    positive = str(parsed.get("positive") or "").strip()
    negative = str(parsed.get("negative") or "").strip()
    leak = "negative:" in positive.lower()
    return positive, negative, leak, None


def clean_prompt_part(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"^\s*[-*]\s*", "", text)
    return text.strip(" ,")


def deterministic_prompt(sections: dict[str, str], scene: str) -> tuple[str, str]:
    name = sections.get("NAME", "Atago").strip() or "Atago"
    source = sections.get("SOURCE_MEDIA", "").strip()
    appearance = clean_prompt_part(sections.get("APPEARANCE", ""))
    positive_add = clean_prompt_part(sections.get("IMAGE_POSITIVE", ""))
    identity = f"{name} from {source}" if source else name
    scene_clean = clean_prompt_part(scene)
    positive_parts = [
        identity,
        appearance,
        "1girl",
        "solo",
        "no other people visible",
        "visual novel still",
        "medium shot",
        scene_clean,
        positive_add,
        STYLE_ANCHOR,
    ]
    positive = ", ".join(dict.fromkeys(part for part in positive_parts if part))
    negative = ", ".join(
        dict.fromkeys(
            part
            for part in [sections.get("IMAGE_NEGATIVE", ""), BASE_NEGATIVE]
            if part and part.strip()
        )
    )
    return positive, negative


def build_current_labeled_messages(sections: dict[str, str], scene: str, assistant: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Convert the supplied companion scene into concise SDXL prompts for the character.\n\n"
                "Return exactly two lines:\n"
                "POSITIVE: <comma-separated prompt>\n"
                "NEGATIVE: <comma-separated prompt>\n\n"
                "Preserve identity from the supplied context blocks and scene summary."
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    block("CHARACTER_NAME", sections.get("NAME", "")),
                    block("SOURCE_MEDIA", sections.get("SOURCE_MEDIA", "")),
                    block("APPEARANCE", sections.get("APPEARANCE", "")),
                    block("IMAGE_POSITIVE", sections.get("IMAGE_POSITIVE", "")),
                    block("IMAGE_NEGATIVE", sections.get("IMAGE_NEGATIVE", "")),
                    block("ASSISTANT_TEXT", assistant),
                    block("SCENE_SUMMARY", scene),
                ]
            ),
        },
    ]


def build_strict_json_messages(sections: dict[str, str], scene: str, assistant: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You write SDXL prompts for one visual-novel still.\n"
                "Return only valid JSON with exactly these keys: positive, negative.\n"
                "The positive prompt must be comma-separated SDXL tags/fragments, not prose or bullets.\n"
                "The image must show the named character only. Do not make the user/protagonist visible.\n"
                "Do not put negative concepts in positive. Do not include labels inside values."
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    block("CHARACTER_NAME", sections.get("NAME", "")),
                    block("SOURCE_MEDIA", sections.get("SOURCE_MEDIA", "")),
                    block("APPEARANCE", sections.get("APPEARANCE", "")),
                    block("STYLE_ADDENDUM", sections.get("IMAGE_POSITIVE", "")),
                    block("NEGATIVE_ADDENDUM", sections.get("IMAGE_NEGATIVE", "")),
                    block("SCENE_SUMMARY", scene),
                    block("ASSISTANT_TEXT_FOR_CONTEXT_ONLY", assistant),
                    block(
                        "REQUIREMENTS",
                        (
                            "solo character, no Anon visible, no second girl, no separate animal, "
                            "visual novel CG, one clear outfit, one setting, one mood"
                        ),
                    ),
                ]
            ),
        },
    ]


def score_prompt(positive: str, negative: str, *, parse_error: str | None = None, leak: bool = False) -> dict[str, Any]:
    lower_pos = positive.lower()
    score = 100
    flags: list[str] = []
    if parse_error:
        score -= 45
        flags.append(parse_error)
    if not positive:
        score -= 40
        flags.append("missing_positive")
    if not negative:
        score -= 20
        flags.append("missing_negative")
    if leak or "negative:" in lower_pos:
        score -= 25
        flags.append("negative_leak_in_positive")
    if re.search(r"(^|,\s*)[-*]\s+", positive):
        score -= 15
        flags.append("bullet_artifacts")
    if re.search(r"\b(anon|user|master|traveler)\b", lower_pos):
        score -= 25
        flags.append("visible_user_risk")
    if re.search(r"\b(two girls|multiple girls|another girl|second girl|both)\b", lower_pos):
        score -= 30
        flags.append("duplicate_character_risk")
    if "atago" not in lower_pos:
        score -= 20
        flags.append("missing_character_name")
    if len(positive) > 1400:
        score -= 10
        flags.append("too_long")
    if len(positive) < 120:
        score -= 10
        flags.append("too_short")
    return {"score": max(score, 0), "flags": flags}


def read_turns(source_run: Path) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for turn in (1, 2):
        turns.append(
            {
                "turn": str(turn),
                "assistant": (source_run / f"turn{turn}_assistant.txt").read_text(encoding="utf-8"),
                "scene": (source_run / f"turn{turn}_scene_summary.txt").read_text(encoding="utf-8"),
            }
        )
    return turns


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[save] {path}")


def write_report(run_dir: Path, source_run: Path, records: list[dict[str, Any]]) -> None:
    lines = [
        "# Image Prompt Composer Experiment",
        "",
        f"Run ID: `{run_dir.name}`",
        "",
        f"Source production run: `{source_run}`",
        "",
        "Purpose: compare prompt composer strategies before generating images.",
        "",
        "## Summary",
        "",
        "| Strategy | Turn | Score | Flags | Positive chars | Negative chars | tok/s | Wall s |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for record in records:
        metrics = record.get("metrics") or {}
        lines.append(
            "| "
            f"`{record['strategy']}` | {record['turn']} | {record['score']['score']} | "
            f"{', '.join(record['score']['flags']) or 'none'} | "
            f"{len(record['positive'])} | {len(record['negative'])} | "
            f"{metrics.get('output_tps', 0):.1f} | {metrics.get('wall_s', 0):.2f} |"
        )
    lines.extend(["", "## Full Outputs", ""])
    for record in records:
        lines.extend(
            [
                f"### {record['strategy']} / Turn {record['turn']}",
                "",
                "Raw output:",
                "",
                "```text",
                record.get("raw", ""),
                "```",
                "",
                "Positive:",
                "",
                "```text",
                record["positive"],
                "```",
                "",
                "Negative:",
                "",
                "```text",
                record["negative"],
                "```",
                "",
            ]
        )
    best = sorted(records, key=lambda item: item["score"]["score"], reverse=True)[:2]
    lines.extend(
        [
            "## Initial Conclusion",
            "",
            "Best scoring records:",
            "",
        ]
    )
    for record in best:
        lines.append(f"- `{record['strategy']}` turn {record['turn']}: {record['score']['score']}")
    lines.extend(
        [
            "",
            "Use this as a parser/format screen only. Final image quality still needs A1111 generation.",
        ]
    )
    write_text(run_dir / "EXPERIMENT.md", "\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark image prompt composer strategies.")
    parser.add_argument("source_run", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_run = args.source_run.resolve()
    if not source_run.exists():
        raise FileNotFoundError(source_run)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / f"image_prompt_composer_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run dir] {run_dir}")

    character_card = (source_run / "character_card.txt").read_text(encoding="utf-8")
    sections = parse_sections(character_card)
    turns = read_turns(source_run)
    write_text(run_dir / "source_run.txt", str(source_run))
    write_text(run_dir / "character_card.txt", character_card)

    records: list[dict[str, Any]] = []
    ollama_proc = ensure_ollama(run_dir)
    try:
        unload_model(args.model)
        for item in turns:
            turn = item["turn"]
            assistant = item["assistant"]
            scene = item["scene"]
            turn_dir = run_dir / f"turn{turn}"
            turn_dir.mkdir(parents=True, exist_ok=True)
            write_text(turn_dir / "assistant.txt", assistant)
            write_text(turn_dir / "scene_summary.txt", scene)

            strategies = [
                ("current_labeled", build_current_labeled_messages(sections, scene, assistant), False),
                ("strict_json", build_strict_json_messages(sections, scene, assistant), True),
            ]
            for strategy, messages, json_mode in strategies:
                result = run_chat(args.model, messages, json_mode=json_mode)
                raw = (result.get("message") or {}).get("content", "").strip()
                metrics = text_metrics(result)
                if strategy == "strict_json":
                    positive, negative, leak, parse_error = parse_json_prompt(raw)
                else:
                    positive, negative, leak = parse_labeled_loose(raw)
                    parse_error = None
                score = score_prompt(positive, negative, parse_error=parse_error, leak=leak)
                strategy_dir = turn_dir / strategy
                strategy_dir.mkdir(parents=True, exist_ok=True)
                write_text(strategy_dir / "messages.json", json.dumps(messages, indent=2, ensure_ascii=False))
                write_text(strategy_dir / "raw.txt", raw)
                write_text(strategy_dir / "positive.txt", positive)
                write_text(strategy_dir / "negative.txt", negative)
                record = {
                    "strategy": strategy,
                    "turn": turn,
                    "raw": raw,
                    "positive": positive,
                    "negative": negative,
                    "score": score,
                    "metrics": metrics,
                    "paths": {
                        "raw": str(strategy_dir / "raw.txt"),
                        "positive": str(strategy_dir / "positive.txt"),
                        "negative": str(strategy_dir / "negative.txt"),
                    },
                }
                write_text(strategy_dir / "record.json", json.dumps(record, indent=2, ensure_ascii=False))
                records.append(record)
                print(f"[result] {strategy} turn{turn}: score={score['score']} flags={score['flags']}")

            positive, negative = deterministic_prompt(sections, scene)
            score = score_prompt(positive, negative)
            strategy_dir = turn_dir / "deterministic_template"
            strategy_dir.mkdir(parents=True, exist_ok=True)
            write_text(strategy_dir / "raw.txt", "<deterministic template>")
            write_text(strategy_dir / "positive.txt", positive)
            write_text(strategy_dir / "negative.txt", negative)
            record = {
                "strategy": "deterministic_template",
                "turn": turn,
                "raw": "<deterministic template>",
                "positive": positive,
                "negative": negative,
                "score": score,
                "metrics": {"output_tps": 0.0, "wall_s": 0.0},
                "paths": {
                    "raw": str(strategy_dir / "raw.txt"),
                    "positive": str(strategy_dir / "positive.txt"),
                    "negative": str(strategy_dir / "negative.txt"),
                },
            }
            write_text(strategy_dir / "record.json", json.dumps(record, indent=2, ensure_ascii=False))
            records.append(record)
            print(f"[result] deterministic_template turn{turn}: score={score['score']} flags={score['flags']}")

        manifest = {
            "run_dir": str(run_dir),
            "source_run": str(source_run),
            "model": args.model,
            "records": records,
            "ended_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_text(run_dir / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        write_report(run_dir, source_run, records)
        return 0
    finally:
        unload_model(args.model)
        if ollama_proc is not None:
            ollama_proc.terminate()
            try:
                ollama_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                ollama_proc.kill()
                ollama_proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
