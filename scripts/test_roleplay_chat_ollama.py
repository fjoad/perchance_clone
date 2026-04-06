"""
Interactive roleplay sandbox using the Ollama HTTP API.
No torch/transformers dependency — drives Ollama directly.

Usage:
    python scripts/test_roleplay_chat_ollama.py
    python scripts/test_roleplay_chat_ollama.py --character atago --model dolphin-llama3

Commands during chat:
    /quit    — exit
    /summary — print the current rolling summary
    /prompt  — print the current system prompt
    /vram    — print current VRAM usage
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
HF_HOME = Path(r"F:\huggingface\models")
OLLAMA_EXE = Path(r"F:\Programs\Ollama\ollama.exe")
OLLAMA_MODELS = r"F:\ollama\models"
OLLAMA_BASE_URL = "http://localhost:11434"

os.environ["HF_HOME"] = str(HF_HOME)
os.environ["HF_HUB_CACHE"] = str(HF_HOME / "hub")
os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_HOME / "hub")
os.environ["OLLAMA_MODELS"] = OLLAMA_MODELS
os.environ["OLLAMA_FLASH_ATTENTION"] = "1"
os.environ["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
os.environ["OLLAMA_NUM_PARALLEL"] = "1"
os.environ["OLLAMA_MAX_LOADED_MODELS"] = "1"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import (
    get_character,
    get_character_by_slug,
    get_first_character,
    get_pinned_memory,
    get_user_profile,
    init_db,
    list_characters,
    seed_atago_character,
    seed_default_user_profile,
    seed_sample_character,
)
from app.services import prompts
from app.services.memory import retrieve_lore_entries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive Ollama roleplay sandbox.")
    parser.add_argument("--character", default="atago", help="Character slug.")
    parser.add_argument("--model", default="dolphin-llama3", help="Ollama model name.")
    parser.add_argument("--summary-every", type=int, default=6, help="Summarize every N user turns.")
    parser.add_argument("--max-tokens", type=int, default=520)
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--top-p", type=float, default=0.94)
    parser.add_argument("--repeat-penalty", type=float, default=1.03)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# VRAM
# ---------------------------------------------------------------------------

def vram_str() -> str:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free,memory.total",
             "--format=csv,noheader,nounits"],
            text=True,
        ).strip().split(",")
        used, free, total = [int(x.strip()) for x in out]
        return f"used={used/1024:.2f} GiB  free={free/1024:.2f} GiB  total={total/1024:.2f} GiB"
    except Exception as e:
        return f"(vram error: {e})"


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

def ollama_running() -> bool:
    try:
        urllib.request.urlopen(OLLAMA_BASE_URL, timeout=2)
        return True
    except Exception:
        return False


def ensure_ollama() -> subprocess.Popen | None:
    if ollama_running():
        return None
    print("[ollama] starting server...")
    env = os.environ.copy()
    proc = subprocess.Popen(
        [str(OLLAMA_EXE), "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        if ollama_running():
            print("[ollama] ready\n")
            return proc
        time.sleep(1)
    raise RuntimeError("Ollama server did not start within 30s")


def chat_completion(
    model: str,
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
    repeat_penalty: float,
    timeout: float = 120,
) -> str:
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "repeat_penalty": repeat_penalty,
            "num_predict": max_tokens,
        },
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Character helpers
# ---------------------------------------------------------------------------

def resolve_character(raw: str) -> dict[str, Any]:
    if raw.isdigit():
        c = get_character(int(raw))
        if c:
            return c
    c = get_character_by_slug(raw)
    if c:
        return c
    target = raw.strip().lower()
    for c in list_characters():
        if c["display_name"].strip().lower() == target:
            return c
    raise RuntimeError(f"Character not found: {raw!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    init_db()
    seed_sample_character()
    seed_default_user_profile()
    seed_atago_character()

    character = resolve_character(args.character)
    user_profile = get_user_profile()
    pinned_memory = get_pinned_memory(character["id"])
    summary = ""
    messages: list[dict[str, str]] = []
    user_turns = 0

    ollama_proc = ensure_ollama()

    print(f"[model]     {args.model}")
    print(f"[character] {character['display_name']}")
    print(f"[user]      {user_profile.get('display_name') or 'Anon'}")
    print(f"[vram]      {vram_str()}")
    print("\nType /quit to exit, /summary for rolling summary, /prompt for system prompt, /vram for GPU memory.\n")

    user_name = user_profile.get("display_name") or "Anon"

    try:
        while True:
            try:
                user_text = input(f"{user_name}> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_text:
                continue
            if user_text == "/quit":
                break
            if user_text == "/summary":
                print(f"\n[summary]\n{summary or '<empty>'}\n")
                continue
            if user_text == "/vram":
                print(f"[vram] {vram_str()}\n")
                continue
            if user_text == "/prompt":
                lore_entries = retrieve_lore_entries(character, messages)
                compiled = prompts.build_chat_messages(
                    character, user_profile, pinned_memory, summary, lore_entries, messages
                )
                print(f"\n[system prompt]\n{compiled[0]['content']}\n")
                continue

            messages.append({"role": "user", "content": user_text})
            user_turns += 1

            lore_entries = retrieve_lore_entries(character, messages)
            compiled = prompts.build_chat_messages(
                character, user_profile, pinned_memory, summary, lore_entries, messages
            )

            est_tokens = sum(len(m["content"]) // 4 for m in compiled)
            print(f"[tokens ~{est_tokens}]  [vram {vram_str()}]")

            t0 = time.perf_counter()
            try:
                reply = chat_completion(
                    args.model,
                    compiled,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    repeat_penalty=args.repeat_penalty,
                )
            except Exception as exc:
                print(f"[error] {exc}\n")
                messages.pop()
                user_turns -= 1
                continue

            elapsed = time.perf_counter() - t0
            words = len(reply.split())
            print(f"[{elapsed:.1f}s  ~{words} words  {words/elapsed:.1f} w/s]\n")
            print(f"{character['display_name']}> {reply}\n")

            messages.append({"role": "assistant", "content": reply})

            if args.summary_every > 0 and user_turns % args.summary_every == 0:
                print("[summarizing...]")
                summary_msgs = prompts.build_summary_messages(
                    character, user_profile, pinned_memory, summary, messages
                )
                try:
                    summary = chat_completion(
                        args.model,
                        summary_msgs,
                        max_tokens=180,
                        temperature=0.2,
                        top_p=0.9,
                        repeat_penalty=1.02,
                    )
                    print(f"[summary updated] {summary}\n")
                except Exception as exc:
                    print(f"[summary error] {exc}\n")

    finally:
        if ollama_proc is not None:
            ollama_proc.terminate()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
