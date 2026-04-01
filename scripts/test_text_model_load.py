from __future__ import annotations

import argparse
import gc
import os
import time
from pathlib import Path


HF_HOME = Path(r"F:\huggingface\models")
HF_HUB_CACHE = HF_HOME / "hub"


def configure_environment() -> None:
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ["TRANSFORMERS_CACHE"] = str(HF_HUB_CACHE)
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


configure_environment()

import torch
import transformers.modeling_utils as modeling_utils
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


def format_mem() -> str:
    if not torch.cuda.is_available():
        return "cuda-unavailable"
    free_bytes, total_bytes = torch.cuda.mem_get_info()
    used_bytes = total_bytes - free_bytes
    gib = 1024**3
    return (
        f"free={free_bytes / gib:.2f} GiB, "
        f"used={used_bytes / gib:.2f} GiB, "
        f"total={total_bytes / gib:.2f} GiB"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone local text-model load test.")
    parser.add_argument("--model-id", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--generate", action="store_true", help="Run one tiny generation after load.")
    parser.add_argument("--prompt", default="Write one short line in character.")
    parser.add_argument("--local-only", action="store_true", help="Do not attempt network download.")
    parser.add_argument("--disable-warmup", action="store_true", help="Bypass transformers CUDA allocator warmup.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(f"[env] HF_HOME={os.environ['HF_HOME']}")
    print(f"[env] HF_HUB_CACHE={os.environ['HF_HUB_CACHE']}")
    print(f"[cuda] available={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"[cuda] device={torch.cuda.get_device_name(0)}")
        print(f"[cuda] before={format_mem()}")

    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    if args.disable_warmup:
        modeling_utils.caching_allocator_warmup = lambda *_, **__: None
        print("[load] disabled transformers caching allocator warmup")

    start = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_id,
        use_fast=True,
        cache_dir=str(HF_HUB_CACHE),
        local_files_only=args.local_only,
    )
    print(f"[load] tokenizer in {time.perf_counter() - start:.1f}s")

    start = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id,
        quantization_config=bnb_cfg,
        device_map="auto",
        trust_remote_code=False,
        cache_dir=str(HF_HUB_CACHE),
        local_files_only=args.local_only,
        low_cpu_mem_usage=True,
    )
    print(f"[load] model in {time.perf_counter() - start:.1f}s")
    if hasattr(model, "hf_device_map"):
        print(f"[load] device_map={model.hf_device_map}")
    if torch.cuda.is_available():
        print(f"[cuda] after_load={format_mem()}")

    if args.generate:
        if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
            tokenizer.pad_token = tokenizer.eos_token
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": args.prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer(prompt, return_tensors="pt", return_token_type_ids=False)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        inputs = {k: v.to(device) for k, v in inputs.items()}
        start = time.perf_counter()
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=32,
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
                repetition_penalty=1.05,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        text = tokenizer.decode(output[0, inputs["input_ids"].shape[1] :], skip_special_tokens=True).strip()
        print(f"[generate] in {time.perf_counter() - start:.1f}s")
        print(f"[generate] output={text}")
        if torch.cuda.is_available():
            print(f"[cuda] after_generate={format_mem()}")

    del model
    del tokenizer
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        print(f"[cuda] after_unload={format_mem()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
