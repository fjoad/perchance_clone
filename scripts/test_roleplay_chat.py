from __future__ import annotations

import argparse
import gc
import os
import sys
import time
from pathlib import Path
from typing import Any


HF_HOME = Path(r"F:\huggingface\models")
HF_HUB_CACHE = HF_HOME / "hub"
ROOT_DIR = Path(__file__).resolve().parents[1]


def configure_environment() -> None:
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


configure_environment()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import torch
import transformers.modeling_utils as modeling_utils
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from app.config import settings
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
    parser = argparse.ArgumentParser(description="Interactive standalone roleplay chat test.")
    parser.add_argument("--model-id", default=settings.text_model_id)
    parser.add_argument("--character", default="atago", help="Character slug, id, or display name.")
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--disable-warmup", action="store_true")
    parser.add_argument("--summary-every", type=int, default=settings.summary_interval_user_turns)
    parser.add_argument("--show-system-prompt", action="store_true")
    parser.add_argument("--max-new-tokens", type=int, default=520)
    parser.add_argument("--min-new-tokens", type=int, default=150)
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--top-p", type=float, default=0.94)
    parser.add_argument("--repetition-penalty", type=float, default=1.03)
    return parser.parse_args()


def format_mem() -> str:
    if not torch.cuda.is_available():
        return "cuda-unavailable"
    free_bytes, total_bytes = torch.cuda.mem_get_info()
    used_bytes = total_bytes - free_bytes
    peak_bytes = torch.cuda.max_memory_reserved()
    gib = 1024**3
    return (
        f"free={free_bytes / gib:.2f} GiB, "
        f"used={used_bytes / gib:.2f} GiB, "
        f"total={total_bytes / gib:.2f} GiB, "
        f"peak={peak_bytes / gib:.2f} GiB"
    )


def reset_peak_mem() -> None:
    if not torch.cuda.is_available():
        return
    try:
        torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass


def flush_console_typeahead() -> None:
    if os.name != "nt":
        return
    try:
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getwch()
    except Exception:
        pass


def resolve_character(raw: str) -> dict[str, Any]:
    if raw.isdigit():
        by_id = get_character(int(raw))
        if by_id:
            return by_id
    by_slug = get_character_by_slug(raw)
    if by_slug:
        return by_slug
    target = raw.strip().lower()
    for character in list_characters():
        if character["display_name"].strip().lower() == target:
            return character
    first = get_first_character()
    if first and first["display_name"].strip().lower() == target:
        return first
    raise RuntimeError(f"Could not find character: {raw}")


def load_model(model_id: str, *, local_only: bool, disable_warmup: bool):
    if disable_warmup:
        modeling_utils.caching_allocator_warmup = lambda *_, **__: None

    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        model_id,
        use_fast=True,
        cache_dir=str(HF_HUB_CACHE),
        local_files_only=local_only,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_cfg,
        device_map="auto",
        trust_remote_code=False,
        cache_dir=str(HF_HUB_CACHE),
        local_files_only=local_only,
        low_cpu_mem_usage=True,
    )
    if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer, model


def generate_text(
    tokenizer,
    model,
    messages: list[dict[str, str]],
    *,
    max_new_tokens: int,
    min_new_tokens: int,
    temperature: float,
    top_p: float,
    repetition_penalty: float,
) -> str:
    prompt = None
    inputs = None
    output = None
    new_ids = None
    try:
        reset_peak_mem()
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt", return_token_type_ids=False)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                min_new_tokens=min_new_tokens,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
                repetition_penalty=repetition_penalty,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        new_ids = output[0, inputs["input_ids"].shape[1] :]
        result = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
        if torch.cuda.is_available():
            print(f"[diag] vram_peak_during_generate={format_mem()}")
        return result
    finally:
        del output
        del new_ids
        del inputs
        del prompt
        gc.collect()
        if torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass


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

    print(f"[model] {args.model_id}")
    print(f"[character] {character['display_name']}")
    print(f"[user] {user_profile.get('display_name') or 'Anon'}")
    if torch.cuda.is_available():
        reset_peak_mem()
        print(f"[cuda] before_load={format_mem()}")

    tokenizer, model = load_model(
        args.model_id,
        local_only=args.local_only,
        disable_warmup=args.disable_warmup,
    )

    if torch.cuda.is_available():
        print(f"[cuda] after_load={format_mem()}")
    flush_console_typeahead()
    print("Type '/quit' to exit, '/prompt' to print the current system prompt, or '/summary' to print the current summary.\n")

    try:
        while True:
            flush_console_typeahead()
            user_text = input(f"{user_profile.get('display_name') or 'Anon'}> ").strip()
            if not user_text:
                continue
            if user_text == "/quit":
                break
            if user_text == "/summary":
                print(f"\n[summary]\n{summary or '<empty>'}\n")
                continue
            if user_text == "/prompt":
                lore_entries = retrieve_lore_entries(character, messages)
                compiled = prompts.build_chat_messages(character, user_profile, pinned_memory, summary, lore_entries, messages)
                print(f"\n[system prompt]\n{compiled[0]['content']}\n")
                continue

            messages.append({"role": "user", "content": user_text})
            user_turns += 1
            lore_entries = retrieve_lore_entries(character, messages)
            compiled = prompts.build_chat_messages(character, user_profile, pinned_memory, summary, lore_entries, messages)

            if args.show_system_prompt:
                print(f"\n[system prompt]\n{compiled[0]['content']}\n")

            # --- VRAM diagnostics ---
            token_ids = tokenizer.apply_chat_template(compiled, tokenize=True, add_generation_prompt=True)
            n_tok = len(token_ids)
            num_layers = getattr(model.config, "num_hidden_layers", 32)
            num_heads = getattr(model.config, "num_attention_heads", 32)
            attn_peak_gb = (num_heads * n_tok * n_tok * 2) / (1024 ** 3)
            print(f"[diag] input_tokens={n_tok}  layers={num_layers}  heads={num_heads}  predicted_attn_peak={attn_peak_gb:.2f} GB")
            if torch.cuda.is_available():
                print(f"[diag] vram_before_generate={format_mem()}")
            # --- end diagnostics ---

            started = time.perf_counter()
            reply = generate_text(
                tokenizer,
                model,
                compiled,
                max_new_tokens=args.max_new_tokens,
                min_new_tokens=args.min_new_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                repetition_penalty=args.repetition_penalty,
            )
            elapsed = time.perf_counter() - started
            print(f"\n{character['display_name']}> {reply}\n")
            print(f"[timing] {elapsed:.1f}s")
            if torch.cuda.is_available():
                print(f"[cuda] after_reply={format_mem()}\n")

            messages.append({"role": "assistant", "content": reply})

            if args.summary_every > 0 and user_turns % args.summary_every == 0:
                summary_messages = prompts.build_summary_messages(
                    character,
                    user_profile,
                    pinned_memory,
                    summary,
                    messages,
                )
                summary = generate_text(
                    tokenizer,
                    model,
                    summary_messages,
                    max_new_tokens=180,
                    min_new_tokens=0,
                    temperature=0.2,
                    top_p=0.9,
                    repetition_penalty=1.02,
                )
                print(f"[summary updated] {summary}\n")
    finally:
        reset_peak_mem()
        del model
        del tokenizer
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print(f"[cuda] after_unload={format_mem()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
