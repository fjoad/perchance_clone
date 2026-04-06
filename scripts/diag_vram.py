"""
Non-interactive VRAM diagnostic.
Runs 5 preset messages through the full prompt pipeline and prints
VRAM stats before and after each generation to identify where memory goes.
"""
from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

HF_HOME = Path(r"F:\huggingface\models")
HF_HUB_CACHE = HF_HOME / "hub"
ROOT_DIR = Path(__file__).resolve().parents[1]

os.environ["HF_HOME"] = str(HF_HOME)
os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_HUB_CACHE)

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import torch
import transformers.modeling_utils as modeling_utils
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from app.config import settings
from app.db import (
    get_pinned_memory,
    get_user_profile,
    init_db,
    seed_atago_character,
    seed_default_user_profile,
    seed_sample_character,
    get_character_by_slug,
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

VRAM_SAFETY_THRESHOLD_GIB = 11.2  # stop before OOM


def mem() -> dict:
    if not torch.cuda.is_available():
        return {}
    free, total = torch.cuda.mem_get_info()
    used = total - free
    peak = torch.cuda.max_memory_reserved()
    gib = 1024 ** 3
    return {
        "free_gib": free / gib,
        "used_gib": used / gib,
        "peak_gib": peak / gib,
        "total_gib": total / gib,
    }


def print_mem(label: str) -> None:
    m = mem()
    if not m:
        print(f"[{label}] no cuda")
        return
    print(
        f"[{label}] "
        f"used={m['used_gib']:.2f} GiB  "
        f"free={m['free_gib']:.2f} GiB  "
        f"peak={m['peak_gib']:.2f} GiB  "
        f"total={m['total_gib']:.2f} GiB"
    )


def reset_peak() -> None:
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()


def main() -> None:
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
    print(f"VRAM DIAGNOSTIC — Qwen 2.5 7B NF4 4-bit")
    print(f"Character: {character['display_name']}")
    print(f"Model: {settings.text_model_id}")
    print(f"{'='*60}\n")

    if torch.cuda.is_available():
        reset_peak()
        print_mem("before_load")

    # Load model
    print("\n[loading model...]\n")
    modeling_utils.caching_allocator_warmup = lambda *_, **__: None
    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        settings.text_model_id,
        use_fast=True,
        cache_dir=str(HF_HUB_CACHE),
        local_files_only=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        settings.text_model_id,
        quantization_config=bnb_cfg,
        device_map="auto",
        trust_remote_code=False,
        cache_dir=str(HF_HUB_CACHE),
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
        tokenizer.pad_token = tokenizer.eos_token

    num_layers = getattr(model.config, "num_hidden_layers", 32)
    num_heads = getattr(model.config, "num_attention_heads", 32)
    print(f"[model config] layers={num_layers}  attention_heads={num_heads}")

    if torch.cuda.is_available():
        reset_peak()
        print_mem("after_load")

    # Run 5 turns
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

        # Tokenize to measure context length
        token_ids = tokenizer.apply_chat_template(
            compiled, tokenize=True, add_generation_prompt=True
        )
        n_tok = len(token_ids)
        attn_peak_gb = (num_heads * n_tok * n_tok * 2) / (1024 ** 3)
        print(f"[tokens]  input_tokens={n_tok}  predicted_attn_matrix={attn_peak_gb:.3f} GiB")

        if torch.cuda.is_available():
            reset_peak()
            print_mem("before_generate")
            m = mem()
            if m.get("used_gib", 0) > VRAM_SAFETY_THRESHOLD_GIB:
                print(f"[SAFETY] VRAM already at {m['used_gib']:.2f} GiB — stopping to avoid OOM")
                break

        import time as _time
        import threading as _threading

        TURN_TIMEOUT_SECS = 90
        _t0 = _time.perf_counter()
        _result = {"output": None, "error": None}

        # Generate in a thread so we can enforce a wall-clock timeout
        prompt_str = tokenizer.apply_chat_template(
            compiled, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(prompt_str, return_tensors="pt", return_token_type_ids=False)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        inputs = {k: v.to(device) for k, v in inputs.items()}

        def _run():
            try:
                with torch.no_grad():
                    _result["output"] = model.generate(
                        **inputs,
                        max_new_tokens=520,
                        min_new_tokens=150,
                        do_sample=True,
                        temperature=0.9,
                        top_p=0.94,
                        repetition_penalty=1.03,
                        pad_token_id=tokenizer.eos_token_id,
                        eos_token_id=tokenizer.eos_token_id,
                    )
            except Exception as e:
                _result["error"] = e

        t = _threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=TURN_TIMEOUT_SECS)
        _elapsed = _time.perf_counter() - _t0

        output = None
        reply = ""
        timed_out = False
        try:
            if t.is_alive():
                timed_out = True
                print(f"[TIMEOUT] Turn {turn} exceeded {TURN_TIMEOUT_SECS}s — generation still running on GPU")
                if torch.cuda.is_available():
                    print_mem("vram_at_timeout")
                print(f"[timing]  >{_elapsed:.0f}s — STALLED (shared memory spillage)")
                break
            if _result["error"]:
                print(f"[ERROR] {_result['error']}")
                break

            output = _result["output"]
            new_ids = output[0, inputs["input_ids"].shape[1]:]
            reply = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
            n_generated = len(tokenizer.encode(reply))

            if torch.cuda.is_available():
                print_mem("peak_during_generate")
            print(f"[timing]  {_elapsed:.1f}s  ({n_generated} tokens generated,  {n_generated/_elapsed:.1f} tok/s)")

        finally:
            del output
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                try:
                    torch.cuda.ipc_collect()
                except Exception:
                    pass

        if torch.cuda.is_available():
            print_mem("after_cleanup")

        print(f"[reply]   {reply[:120]}{'...' if len(reply) > 120 else ''}")
        messages.append({"role": "assistant", "content": reply})

    print(f"\n{'='*60}")
    print("DIAGNOSTIC COMPLETE")
    print(f"{'='*60}\n")

    del model
    del tokenizer
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        print_mem("after_unload")


if __name__ == "__main__":
    main()
