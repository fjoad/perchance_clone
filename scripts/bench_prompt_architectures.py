"""Compare roleplay prompt architectures against the same character flow.

This is text-only by design. It does not start A1111 or load image models.
It tests whether the text model can produce clean single-turn visual-novel
roleplay without writing the user's response.
"""
from __future__ import annotations

import argparse
import ctypes
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
DEFAULT_TEXT_MODEL = "hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M"
SECTION_RE = re.compile(r"^\[([A-Z_]+)\]\s*$", re.MULTILINE)

DEFAULT_USER_MESSAGES = [
    (
        "I step through the doorway with rain still clinging to my coat, shoulders sagging "
        "from the road. \"Atago... I think I'm completely exhausted.\""
    ),
    (
        "I accept the tea with both hands and sink into the warmth of the room. "
        "\"I'm tired, but... I'm happy I made it here.\""
    ),
]

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

USER_CONTINUATION_PATTERNS = [
    r"\n\s*Anon\s*:",
    r"\n\s*User\s*:",
    r"\n\s*\{\{\s*user\s*\}\}\s*:",
    r"\n\s*I\s+(?:pause|step|accept|reply|say|ask|murmur|whisper|think|feel|decide)\b",
    r"\bI should\b",
    r"\bI pause\b",
    r"\bI accept\b",
    r"\bI reply\b",
]


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


def parse_character_file(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(text))
    for i, match in enumerate(matches):
        key = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[key] = text[start:end].strip()
    name = sections.get("NAME", "").strip() or path.stem.title()
    sections["NAME"] = name
    return sections, text


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
    cleaned = content.strip() if content and content.strip() else "<none>"
    return f"<{name}>\n{cleaned}\n</{name}>"


def build_system_prompt(
    sections: dict[str, str],
    *,
    style: str,
    user_name: str,
    user_background: str,
) -> str:
    char_name = sections["NAME"]
    dossier = render_macros(sections.get("DOSSIER", ""), char_name, user_name)
    reminder = render_macros(sections.get("REMINDER", ""), char_name, user_name)
    example = render_macros(sections.get("EXAMPLE_DIALOGUE", ""), char_name, user_name)
    pinned = render_macros(sections.get("PINNED_MEMORY", ""), char_name, user_name)
    source = sections.get("SOURCE_MEDIA", "")

    shared_contract = (
        "Hard turn boundary:\n"
        f"- Write exactly one assistant turn for {char_name}.\n"
        f"- Do not write {user_name}'s next dialogue, thoughts, choices, or actions.\n"
        f"- Stop immediately after {char_name}'s turn is complete.\n"
        "- Do not continue the scene from the user's perspective.\n"
        "- No OOC notes, no analysis, no bullets, no labels in the final reply.\n"
        "- Use third-person narration for visible action and double quotes for spoken dialogue.\n"
        "<END_TURN> is a stop marker, not text to print."
    )

    if style == "direct_character":
        task = (
            f"You are {char_name} from {source}. You are not an assistant explaining a roleplay. "
            f"You are {char_name} inside the scene, responding to {user_name}. "
            "Write only your next in-character response with narration and dialogue."
        )
    elif style == "direct_vn_v2":
        task = (
            f"You are {char_name} from {source}, present inside an interactive visual novel scene with {user_name}. "
            f"Write {char_name}'s next turn only: visible actions, sensory atmosphere, emotional texture, and spoken dialogue. "
            "Use vivid story prose, but keep the camera anchored on what the character does and says right now."
        )
        shared_contract += (
            "\n- Do not begin with markdown, bullets, dashes, labels, or speaker tags.\n"
            f"- Do not physically move, reposition, undress, consent for, or decide {user_name}'s body unless {user_name} already did that.\n"
            f"- You may offer, gesture, invite, reach, guide lightly, or react, but {user_name}'s major actions remain theirs.\n"
            "- Prefer 2 to 4 paragraphs with a natural final beat that invites continuation."
        )
    elif style == "writer_narrator":
        task = (
            "You are a skilled visual-novel writer composing the next beat of an interactive scene. "
            f"Write only {char_name}'s visible actions, presence, and dialogue. "
            f"The user controls {user_name}; preserve their agency completely."
        )
    elif style == "hybrid_visual_novel":
        task = (
            "You are the story engine for an interactive visual novel. "
            f"For this turn, the camera follows {char_name}; write only {char_name}'s response to {user_name}. "
            "Make the prose vivid, physical, emotionally specific, and easy to continue."
        )
    else:
        raise ValueError(f"Unknown style: {style}")

    return "\n\n".join(
        [
            block("TASK", task),
            block("TURN_CONTRACT", shared_contract),
            block("USER_PROFILE", f"Name: {user_name}\nBackground: {user_background}"),
            block("CHARACTER_DOSSIER", dossier),
            block("PINNED_MEMORY", pinned),
            block("EXAMPLE_DIALOGUE", example),
            block("REMINDER", reminder),
        ]
    )


def build_messages(system_prompt: str, conversation: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"role": "system", "content": system_prompt}, *conversation]


def stream_chat(model: str, messages: list[dict[str, str]], *, num_predict: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": False,
        "options": {
            "num_gpu": 99,
            "temperature": 0.9,
            "top_p": 0.94,
            "repeat_penalty": 1.03,
            "num_predict": num_predict,
            "stop": STOP_MARKERS,
        },
    }
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_at: float | None = None
    parts: list[str] = []
    final: dict[str, Any] = {}
    with urllib.request.urlopen(req, timeout=900) as response:
        for raw_line in response:
            if not raw_line.strip():
                continue
            chunk = json.loads(raw_line.decode("utf-8", errors="replace"))
            content = (chunk.get("message") or {}).get("content") or ""
            if content and first_token_at is None:
                first_token_at = time.perf_counter()
            if content:
                parts.append(content)
            if chunk.get("done"):
                final = chunk
                break
    ended = time.perf_counter()
    text = "".join(parts)
    eval_count = int(final.get("eval_count") or 0)
    eval_duration = int(final.get("eval_duration") or 0)
    prompt_eval_count = int(final.get("prompt_eval_count") or 0)
    prompt_eval_duration = int(final.get("prompt_eval_duration") or 0)
    return {
        "text": text,
        "wall_s": ended - started,
        "first_token_latency_s": (first_token_at - started) if first_token_at else None,
        "output_tokens": eval_count,
        "output_tps": (eval_count / (eval_duration / 1e9)) if eval_count and eval_duration else 0.0,
        "prompt_tokens": prompt_eval_count,
        "prompt_tps": (prompt_eval_count / (prompt_eval_duration / 1e9)) if prompt_eval_count and prompt_eval_duration else 0.0,
        "load_s": int(final.get("load_duration") or 0) / 1e9,
        "done_reason": final.get("done_reason"),
        "raw_final": final,
    }


def truncate_user_continuation(text: str, user_name: str) -> tuple[str, bool, str | None]:
    patterns = [
        rf"\n\s*{re.escape(user_name)}\s*:",
        r"\n\s*User\s*:",
        r"\n\s*\{\{\s*user\s*\}\}\s*:",
        r"\n\s*I\s+(?:pause|step|accept|reply|say|ask|murmur|whisper|think|feel|decide)\b",
        r"\n\s*The\s+.*?\bI\s+should\b",
    ]
    first: tuple[int, str] | None = None
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match and (first is None or match.start() < first[0]):
            first = (match.start(), pattern)
    if first is None:
        return text.strip(), False, None
    return text[: first[0]].strip(), True, first[1]


def assess_output(raw: str, cleaned: str, user_name: str) -> dict[str, Any]:
    joined = "\n".join(USER_CONTINUATION_PATTERNS)
    has_user_continuation = any(re.search(pattern, raw, re.IGNORECASE) for pattern in USER_CONTINUATION_PATTERNS)
    quoted_dialogue = len(re.findall(r'"[^"\n]{3,}"', cleaned))
    paragraphs = [p for p in re.split(r"\n\s*\n", cleaned.strip()) if p.strip()]
    word_count = len(re.findall(r"\b[\w'-]+\b", cleaned))
    return {
        "has_user_continuation_pattern": has_user_continuation,
        "patterns_checked": joined,
        "quoted_dialogue_count": quoted_dialogue,
        "paragraph_count": len(paragraphs),
        "word_count": word_count,
        "clean_turn": bool(cleaned.strip()) and not has_user_continuation,
    }


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[save] {path}")


def write_experiment_md(run_dir: Path, manifest: dict[str, Any]) -> None:
    lines: list[str] = [
        "# Text Prompt Architecture Experiment",
        "",
        f"Run ID: `{run_dir.name}`",
        "",
        "Purpose: compare roleplay prompt architectures using the same full Atago card, same user turns, same text model, and no image generation.",
        "",
        "## Configuration",
        "",
        f"- Text model: `{manifest['args']['text_model']}`",
        f"- Character file: `{manifest['args']['character_file']}`",
        f"- User: `{manifest['args']['user_name']}`",
        f"- Num predict: `{manifest['args']['num_predict']}`",
        "- Streaming: `true`",
        "- Thinking disabled: `true`",
        "- Stop markers enabled for user-turn boundaries",
        "",
        "## Results Summary",
        "",
        "| Style | Turn | Clean Raw? | Truncated? | Output Tokens | tok/s | First Token s | Wall s | Words |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for result in manifest["results"]:
        metrics = result["metrics"]
        assessment = result["assessment"]
        lines.append(
            "| "
            f"`{result['style']}` | {result['turn']} | "
            f"{'yes' if assessment['clean_turn'] else 'no'} | "
            f"{'yes' if result['was_truncated'] else 'no'} | "
            f"{metrics['output_tokens']} | {metrics['output_tps']:.1f} | "
            f"{(metrics['first_token_latency_s'] or 0):.2f} | {metrics['wall_s']:.2f} | "
            f"{assessment['word_count']} |"
        )

    lines.extend(
        [
            "",
            "## Full Trace",
            "",
        ]
    )
    for result in manifest["results"]:
        lines.extend(
            [
                f"### {result['style']} / Turn {result['turn']}",
                "",
                "User prompt:",
                "",
                "```text",
                result["user_text"],
                "```",
                "",
                "Raw model output:",
                "",
                "```text",
                result["raw_output"],
                "```",
                "",
            ]
        )
        if result["was_truncated"]:
            lines.extend(
                [
                    "Cleaned output after continuation truncation:",
                    "",
                    "```text",
                    result["cleaned_output"],
                    "```",
                    "",
                    f"Truncation pattern: `{result['truncate_pattern']}`",
                    "",
                ]
            )

    lines.extend(
        [
            "## Initial Conclusion",
            "",
            "Use the clean raw outputs first. If a style only works after truncation, it may still be usable in production, but the prompt itself is weaker.",
            "",
            "The next production step should pick the best style, then feed only the cleaned assistant turns into the scene/image pipeline.",
        ]
    )
    write_text(run_dir / "EXPERIMENT.md", "\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark prompt architecture variants.")
    parser.add_argument("--character-file", default=str(ROOT_DIR / "characters" / "atago.txt"))
    parser.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--user-name", default="Anon")
    parser.add_argument("--user-background", default="A tired traveler arriving at Atago's home after a long journey.")
    parser.add_argument("--num-predict", type=int, default=520)
    parser.add_argument(
        "--styles",
        nargs="+",
        default=["direct_character", "writer_narrator", "hybrid_visual_novel"],
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / f"text_prompt_arch_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run dir] {run_dir}")

    sections, character_card = parse_character_file(Path(args.character_file))
    write_text(run_dir / "character_card.txt", character_card)

    manifest: dict[str, Any] = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "args": vars(args),
        "initial_resources": resource_snapshot("experiment start"),
        "results": [],
    }
    print_resources(manifest["initial_resources"])

    ollama_proc = ensure_ollama(run_dir)
    try:
        unload_model(args.text_model)
        for style in args.styles:
            style_dir = run_dir / safe_name(style)
            style_dir.mkdir(parents=True, exist_ok=True)
            system_prompt = build_system_prompt(
                sections,
                style=style,
                user_name=args.user_name,
                user_background=args.user_background,
            )
            write_text(style_dir / "system_prompt.txt", system_prompt)
            conversation: list[dict[str, str]] = []
            for turn, user_text in enumerate(DEFAULT_USER_MESSAGES, start=1):
                conversation.append({"role": "user", "content": user_text})
                messages = build_messages(system_prompt, conversation)
                turn_dir = style_dir / f"turn{turn}"
                turn_dir.mkdir(parents=True, exist_ok=True)
                write_text(turn_dir / "messages.json", json.dumps(messages, indent=2, ensure_ascii=False))
                write_text(turn_dir / "user.txt", user_text)
                before = resource_snapshot(f"before {style} turn{turn}")
                print_resources(before)
                generated = stream_chat(args.text_model, messages, num_predict=args.num_predict)
                after = resource_snapshot(f"after {style} turn{turn}")
                print_resources(after)
                raw_output = generated["text"].strip()
                cleaned, was_truncated, truncate_pattern = truncate_user_continuation(raw_output, args.user_name)
                assessment = assess_output(raw_output, cleaned, args.user_name)
                write_text(turn_dir / "raw_output.txt", raw_output)
                write_text(turn_dir / "cleaned_output.txt", cleaned)
                metrics = {k: v for k, v in generated.items() if k != "text"}
                record = {
                    "style": style,
                    "turn": turn,
                    "user_text": user_text,
                    "raw_output": raw_output,
                    "cleaned_output": cleaned,
                    "was_truncated": was_truncated,
                    "truncate_pattern": truncate_pattern,
                    "metrics": metrics,
                    "assessment": assessment,
                    "resources_before": before,
                    "resources_after": after,
                    "paths": {
                        "messages": str(turn_dir / "messages.json"),
                        "raw_output": str(turn_dir / "raw_output.txt"),
                        "cleaned_output": str(turn_dir / "cleaned_output.txt"),
                    },
                }
                write_text(turn_dir / "metrics.json", json.dumps(record, indent=2, ensure_ascii=False))
                manifest["results"].append(record)
                conversation.append({"role": "assistant", "content": cleaned})
                print(
                    f"[result] {style} turn{turn}: "
                    f"clean_raw={assessment['clean_turn']} truncated={was_truncated} "
                    f"tok_s={metrics['output_tps']:.1f} words={assessment['word_count']}"
                )
            unload_model(args.text_model)

        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["final_resources"] = resource_snapshot("experiment final")
        write_text(run_dir / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        write_experiment_md(run_dir, manifest)
        return 0
    finally:
        unload_model(args.text_model)
        if ollama_proc is not None:
            ollama_proc.terminate()
            try:
                ollama_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                ollama_proc.kill()
                ollama_proc.wait(timeout=10)
        final = resource_snapshot("after cleanup")
        print_resources(final)


if __name__ == "__main__":
    raise SystemExit(main())
