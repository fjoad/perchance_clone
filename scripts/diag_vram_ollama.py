"""
Ollama VRAM diagnostic — same 8-turn test as diag_vram.py but using
the Ollama HTTP API instead of loading the model directly in Python.
Writes output to both console and a timestamped log file.
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
HF_HOME = Path(r"F:\huggingface\models")
OLLAMA_EXE = Path(r"F:\Programs\Ollama\ollama.exe")
OLLAMA_MODELS = r"F:\ollama\models"
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL_NAME = "dolphin-llama3"

DIAG_OUT_DIR = ROOT_DIR / "outputs" / "diags"


class Tee:
    """Writes to both a file and the original stdout simultaneously."""
    def __init__(self, filepath: Path):
        self._file = open(filepath, "w", encoding="utf-8")
        self._stdout = sys.stdout

    def write(self, data: str) -> int:
        self._stdout.write(data)
        self._file.write(data)
        return len(data)

    def flush(self) -> None:
        self._stdout.flush()
        self._file.flush()

    def close(self) -> None:
        sys.stdout = self._stdout
        self._file.close()

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

import urllib.request

from app.config import settings
from app.db import (
    get_character_by_slug,
    get_pinned_memory,
    get_user_profile,
    init_db,
    seed_atago_character,
    seed_default_user_profile,
    seed_sample_character,
)
from app.services import prompts
from app.services.memory import retrieve_lore_entries


PRESET_MESSAGES = [
    "Hello.",
    "What do you like to do?",
    "Tell me more.",
    "Interesting. And what about the place we are in?",
    "I see. What happens next?",
    "Tell me about yourself.",
    "What do you think about us?",
    "Let's continue the story.",
]

TURN_TIMEOUT_SECS = 90


def vram() -> dict:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free,memory.total",
             "--format=csv,noheader,nounits"],
            text=True,
        ).strip().split(",")
        used_mib, free_mib, total_mib = [int(x.strip()) for x in out]
        return {
            "used_gib": used_mib / 1024,
            "free_gib": free_mib / 1024,
            "total_gib": total_mib / 1024,
        }
    except Exception as e:
        return {"error": str(e)}


def print_vram(label: str) -> None:
    m = vram()
    if "error" in m:
        print(f"[{label}] vram error: {m['error']}")
        return
    print(f"[{label}] used={m['used_gib']:.2f} GiB  free={m['free_gib']:.2f} GiB  total={m['total_gib']:.2f} GiB")


def start_ollama() -> subprocess.Popen:
    env = os.environ.copy()
    proc = subprocess.Popen(
        [str(OLLAMA_EXE), "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # wait until API is up
    for _ in range(30):
        try:
            urllib.request.urlopen("http://localhost:11434", timeout=1)
            break
        except Exception:
            time.sleep(1)
    return proc


def chat_completion(messages: list[dict], timeout: float = TURN_TIMEOUT_SECS) -> str | None:
    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return None


def main() -> None:
    DIAG_OUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = DIAG_OUT_DIR / f"diag_vram_ollama_{MODEL_NAME}_{timestamp}.txt"
    tee = Tee(log_path)
    sys.stdout = tee
    print(f"[log] writing to {log_path}\n")

    try:
        _main()
    finally:
        tee.close()


def _main() -> None:
    init_db()
    seed_sample_character()
    seed_default_user_profile()
    seed_atago_character()

    character = get_character_by_slug("atago")
    if not character:
        raise RuntimeError("atago character not found in DB")
    user_profile = get_user_profile()
    pinned_memory = get_pinned_memory(character["id"])

    print(f"\n{'='*60}")
    print(f"VRAM DIAGNOSTIC (OLLAMA) - {MODEL_NAME} Q5_K_M")
    print(f"flash_attention=ON  kv_cache=q8_0  ctx=8192")
    print(f"{'='*60}\n")

    print("[starting Ollama server...]")
    ollama_proc = start_ollama()
    print("[Ollama ready]\n")
    print_vram("after_server_start")

    messages: list[dict] = []
    summary = ""

    for turn, user_text in enumerate(PRESET_MESSAGES, start=1):
        print(f"\n{'-'*60}")
        print(f"TURN {turn}: \"{user_text}\"")
        print(f"{'-'*60}")

        messages.append({"role": "user", "content": user_text})
        lore_entries = retrieve_lore_entries(character, messages)
        compiled = prompts.build_chat_messages(
            character, user_profile, pinned_memory, summary, lore_entries, messages
        )

        # count tokens via tokenizer-free estimate (chars / 4 approx) for context
        system_len = len(compiled[0]["content"]) // 4
        chat_len = sum(len(m["content"]) // 4 for m in compiled[1:])
        print(f"[tokens]  system~{system_len}  chat~{chat_len}  total~{system_len + chat_len}")

        print_vram("before_generate")

        t0 = time.perf_counter()
        result = {"reply": None}
        timed_out = False

        def _run():
            result["reply"] = chat_completion(compiled, timeout=TURN_TIMEOUT_SECS)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=TURN_TIMEOUT_SECS + 5)
        elapsed = time.perf_counter() - t0

        if t.is_alive() or result["reply"] is None:
            timed_out = True
            print(f"[TIMEOUT] Turn {turn} exceeded {TURN_TIMEOUT_SECS}s")
            print_vram("vram_at_timeout")
            print(f"[timing]  >{elapsed:.0f}s -- STALLED")
            break

        reply = result["reply"]
        print_vram("after_generate")
        # rough token count from reply length
        reply_tokens = len(reply.split())
        print(f"[timing]  {elapsed:.1f}s  (~{reply_tokens} words generated,  ~{reply_tokens/elapsed:.1f} w/s)")
        print(f"\n[reply]\n{reply}\n")

        messages.append({"role": "assistant", "content": reply})

    print(f"\n{'='*60}")
    print("DIAGNOSTIC COMPLETE")
    print(f"{'='*60}\n")

    print_vram("final")
    ollama_proc.terminate()
    time.sleep(2)
    print_vram("after_shutdown")


if __name__ == "__main__":
    main()

