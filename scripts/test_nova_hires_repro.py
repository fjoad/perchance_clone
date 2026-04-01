from __future__ import annotations

import argparse
import gc
import math
import os
import random
import re
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT_DIR / "runtime"
OUTPUTS_DIR = ROOT_DIR / "outputs" / "repro"
HF_HOME = Path(r"F:\huggingface\models")
HF_HUB_CACHE = HF_HOME / "hub"
DEFAULT_CHECKPOINT = HF_HOME / "novaAnimeXL_ilV120.safetensors"
DEFAULT_PROMPT = (
    "Atago from azur lane in a sunlit grand estate kitchen, wearing a classic black-and-white maid uniform "
    "with delicate lace trim. Her straight hair is tied in a high side ponytail, loose strands framing her face. "
    "She's holding a silver tea tray with polished china, standing near a marble countertop where golden croissants "
    "rest on a porcelain plate. Sunlight streams through tall arched windows, illuminating copper pots hanging on the "
    "wall and casting warm highlights on her porcelain skin. Her amber eyes sparkle with playful warmth, and she has "
    "a gentle, inviting smile. Soft anime-style rendering, 4K detail, luminous natural lighting."
)
DEFAULT_NEGATIVE = ""


def configure_environment() -> None:
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_HUB_CACHE)
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    temp_dir = RUNTIME_DIR / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(temp_dir)
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMPDIR"] = str(temp_dir)


configure_environment()

import torch
import torch.nn.functional as F
from diffusers import (
    DPMSolverMultistepScheduler,
    EulerAncestralDiscreteScheduler,
    StableDiffusionXLPipeline,
    StableDiffusionXLImg2ImgPipeline,
)
from PIL import Image
from transformers import PreTrainedTokenizerBase


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
    parser = argparse.ArgumentParser(description="Standalone Nova SDXL hires repro test.")
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative", default=DEFAULT_NEGATIVE)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--base-width", type=int, default=512)
    parser.add_argument("--base-height", type=int, default=512)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--hires-steps", type=int, default=20)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--clip-skip", type=int, default=2)
    parser.add_argument("--denoise", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--scheduler", choices=["euler_a", "dpmpp_2m"], default="dpmpp_2m")
    parser.add_argument("--upscale-mode", choices=["pil", "latent"], default="pil")
    parser.add_argument(
        "--a1111-img2img-step-math",
        action="store_true",
        help="Use A1111-style internal img2img step math for the second pass.",
    )
    parser.add_argument("--prefix", default="nova_repro")
    return parser.parse_args()


def apply_scheduler(pipe, scheduler_name: str) -> None:
    if scheduler_name == "euler_a":
        pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
    else:
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config,
            algorithm_type="dpmsolver++",
            solver_order=2,
            use_karras_sigmas=True,
        )


def expand_weights(text: str, *, base_repeats: int = 2) -> str:
    def repl(match: re.Match[str]) -> str:
        phrase = match.group(1).strip()
        weight = float(match.group(2))
        reps = max(1, int(math.ceil(base_repeats * (weight - 1.0))))
        return ", ".join([phrase] * (reps + 1))

    text = re.sub(r"\bBREAK\b", ",", text, flags=re.IGNORECASE)
    return re.sub(r"\(([^():]+):([0-9.]+)\)", repl, text)


def encode_chunks(
    tok: PreTrainedTokenizerBase,
    enc,
    text: str,
    device: torch.device,
    chunk_payload: int = 75,
    clip_skip: int = 2,
) -> tuple[torch.Tensor, torch.Tensor]:
    ids = tok(text, add_special_tokens=False, return_tensors="pt", truncation=False).input_ids[0].tolist()
    chunks = [ids[i : i + chunk_payload] for i in range(0, len(ids), chunk_payload)] or [[]]

    max_len = tok.model_max_length
    bos, eos = tok.bos_token_id, tok.eos_token_id
    pad = tok.pad_token_id if tok.pad_token_id is not None else eos

    hs_list: list[torch.Tensor] = []
    pooled_list: list[torch.Tensor] = []
    for core in chunks:
        core = core[: max_len - 2]
        ids_full = [bos] + core + [eos]
        ids_full += [pad] * (max_len - len(ids_full))
        inputs = {
            "input_ids": torch.tensor([ids_full], device=device, dtype=torch.long),
            "attention_mask": torch.ones(1, max_len, device=device, dtype=torch.long),
        }
        with torch.no_grad():
            out = enc(**inputs, output_hidden_states=True)
            hs = out.hidden_states[-clip_skip]
            pooled = (
                out.text_embeds
                if hasattr(out, "text_embeds") and out.text_embeds is not None
                else out.pooler_output
                if hasattr(out, "pooler_output") and out.pooler_output is not None
                else hs.mean(dim=1)
            )
        hs_list.append(hs)
        pooled_list.append(pooled)

    hs_cat = torch.cat(hs_list, dim=1)
    pooled_avg = torch.mean(torch.stack(pooled_list, dim=0), dim=0)
    return hs_cat, pooled_avg


def blank_chunk_embed(
    tok: PreTrainedTokenizerBase,
    enc,
    device: torch.device,
    clip_skip: int = 2,
) -> tuple[torch.Tensor, torch.Tensor]:
    max_len = tok.model_max_length
    bos, eos = tok.bos_token_id, tok.eos_token_id
    pad = tok.pad_token_id if tok.pad_token_id is not None else eos
    ids_full = [bos] + [pad] * (max_len - 2) + [eos]
    inputs = {
        "input_ids": torch.tensor([ids_full], device=device, dtype=torch.long),
        "attention_mask": torch.ones(1, max_len, device=device, dtype=torch.long),
    }
    with torch.no_grad():
        out = enc(**inputs, output_hidden_states=True)
        hs = out.hidden_states[-clip_skip]
        pooled = (
            out.text_embeds
            if hasattr(out, "text_embeds") and out.text_embeds is not None
            else out.pooler_output
            if hasattr(out, "pooler_output") and out.pooler_output is not None
            else hs.mean(dim=1)
        )
    return hs, pooled


def pad_to_len(hs: torch.Tensor, target_tokens: int, pad_chunk: torch.Tensor) -> torch.Tensor:
    current = hs.shape[1]
    if current >= target_tokens:
        return hs
    need = target_tokens - current
    if need % pad_chunk.shape[1] != 0:
        raise ValueError("Prompt embedding padding is not aligned to CLIP chunk size.")
    reps = need // pad_chunk.shape[1]
    return torch.cat([hs] + [pad_chunk] * reps, dim=1)


def sdxl_encode_long_both(
    pipe: StableDiffusionXLPipeline,
    text: str,
    *,
    clip_skip: int = 2,
    chunk_payload: int = 75,
) -> tuple[torch.Tensor, torch.Tensor]:
    dev = pipe.device
    hs1, _ = encode_chunks(pipe.tokenizer, pipe.text_encoder, text, dev, chunk_payload, clip_skip)
    hs2, pooled2 = encode_chunks(pipe.tokenizer_2, pipe.text_encoder_2, text, dev, chunk_payload, clip_skip)
    pad1, _ = blank_chunk_embed(pipe.tokenizer, pipe.text_encoder, dev, clip_skip)
    pad2, _ = blank_chunk_embed(pipe.tokenizer_2, pipe.text_encoder_2, dev, clip_skip)
    target_tokens = max(hs1.shape[1], hs2.shape[1])
    hs1 = pad_to_len(hs1, target_tokens, pad1)
    hs2 = pad_to_len(hs2, target_tokens, pad2)
    return torch.cat([hs1, hs2], dim=-1), pooled2


def prepare_prompt_embeds(
    pipe: StableDiffusionXLPipeline,
    positive_prompt: str,
    negative_prompt: str,
    *,
    clip_skip: int,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    pe, pooled = sdxl_encode_long_both(pipe, positive_prompt, clip_skip=clip_skip)
    ne, npooled = sdxl_encode_long_both(pipe, negative_prompt or "", clip_skip=clip_skip)
    pad1, _ = blank_chunk_embed(pipe.tokenizer, pipe.text_encoder, pipe.device, clip_skip)
    pad2, _ = blank_chunk_embed(pipe.tokenizer_2, pipe.text_encoder_2, pipe.device, clip_skip)
    pad2048 = torch.cat([pad1, pad2], dim=-1).to(pipe.unet.dtype)
    target_tokens = max(pe.shape[1], ne.shape[1])
    pe = pad_to_len(pe, target_tokens, pad2048).to(pipe.unet.dtype)
    ne = pad_to_len(ne, target_tokens, pad2048).to(pipe.unet.dtype)
    pooled = pooled.to(pipe.unet.dtype)
    npooled = npooled.to(pipe.unet.dtype)
    return pe, pooled, ne, npooled


def decode_latents_to_pil(pipe: StableDiffusionXLPipeline, latents: torch.Tensor) -> Image.Image:
    if latents.ndim == 3:
        latents = latents.unsqueeze(0)
    latents = latents.to(device="cuda", dtype=pipe.vae.dtype)
    latents = latents / pipe.vae.config.scaling_factor
    with torch.no_grad():
        image = pipe.vae.decode(latents, return_dict=False)[0]
    return pipe.image_processor.postprocess(image, output_type="pil")[0]


def upscale_latents(pipe: StableDiffusionXLPipeline, latents: torch.Tensor, target_w: int, target_h: int) -> torch.Tensor:
    if latents.ndim == 3:
        latents = latents.unsqueeze(0)
    latent_height = target_h // pipe.vae_scale_factor
    latent_width = target_w // pipe.vae_scale_factor
    return F.interpolate(latents, size=(latent_height, latent_width), mode="bilinear", align_corners=False)


def compute_second_pass_internal_steps(requested_steps: int, denoise: float, *, use_a1111_math: bool) -> int:
    if not use_a1111_math:
        return requested_steps
    if denoise <= 0:
        return 0
    return int(requested_steps / min(denoise, 0.999))


def main() -> int:
    args = parse_args()
    checkpoint = Path(args.checkpoint)
    if not checkpoint.exists():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this SDXL repro test.")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    seed = args.seed if args.seed >= 0 else random.randint(1, 2**31 - 1)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUTS_DIR / f"{args.prefix}_{stamp}_s{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)

    args.prompt = expand_weights(args.prompt)
    args.negative = expand_weights(args.negative or "")

    print(f"[env] HF_HOME={os.environ['HF_HOME']}")
    print(f"[env] HF_HUB_CACHE={os.environ['HF_HUB_CACHE']}")
    print(f"[cuda] device={torch.cuda.get_device_name(0)}")
    print(f"[cuda] before={format_mem()}")
    print(f"[cfg] checkpoint={checkpoint}")
    print(f"[cfg] scheduler={args.scheduler}")
    print(f"[cfg] upscale_mode={args.upscale_mode}")
    print(f"[cfg] base={args.base_width}x{args.base_height} target={args.width}x{args.height}")
    requested_second_pass_steps = args.hires_steps or args.steps
    internal_second_pass_steps = compute_second_pass_internal_steps(
        requested_second_pass_steps,
        args.denoise,
        use_a1111_math=args.a1111_img2img_step_math,
    )
    print(
        f"[cfg] steps={args.steps} hires_steps={requested_second_pass_steps} "
        f"cfg={args.cfg} denoise={args.denoise} clip_skip={args.clip_skip} seed={seed}"
    )
    print(
        f"[cfg] second_pass_internal_steps={internal_second_pass_steps} "
        f"a1111_img2img_step_math={args.a1111_img2img_step_math}"
    )

    start = time.perf_counter()
    pipe = StableDiffusionXLPipeline.from_single_file(
        str(checkpoint),
        torch_dtype=torch.float16,
        safety_checker=None,
    ).to("cuda")
    apply_scheduler(pipe, args.scheduler)
    pipe.enable_vae_tiling()
    try:
        pipe.enable_xformers_memory_efficient_attention()
    except Exception:
        pass
    print(f"[load] txt2img pipeline in {time.perf_counter() - start:.1f}s")

    start = time.perf_counter()
    pe, pooled, ne, npooled = prepare_prompt_embeds(
        pipe,
        args.prompt,
        args.negative,
        clip_skip=args.clip_skip,
    )
    print(f"[embeds] prepared in {time.perf_counter() - start:.1f}s")

    gen1 = torch.Generator(device="cuda").manual_seed(seed)
    start = time.perf_counter()
    stage1_result = pipe(
        prompt_embeds=pe,
        pooled_prompt_embeds=pooled,
        negative_prompt_embeds=ne,
        negative_pooled_prompt_embeds=npooled,
        num_inference_steps=args.steps,
        guidance_scale=args.cfg,
        clip_skip=args.clip_skip,
        width=args.base_width,
        height=args.base_height,
        generator=gen1,
        output_type="latent" if args.upscale_mode == "latent" else "pil",
    ).images[0]
    print(f"[stage1] in {time.perf_counter() - start:.1f}s")

    if args.upscale_mode == "latent":
        stage1_latents = stage1_result
        img_lo = decode_latents_to_pil(pipe, stage1_latents)
        second_pass_input = upscale_latents(pipe, stage1_latents, args.width, args.height).to(
            device="cuda", dtype=pipe.unet.dtype
        )
    else:
        img_lo = stage1_result
        second_pass_input = img_lo.resize((args.width, args.height), resample=Image.LANCZOS)

    stage1_path = run_dir / "stage1.png"
    img_lo.save(stage1_path)
    print(f"[save] stage1={stage1_path}")

    pipe_i2i = StableDiffusionXLImg2ImgPipeline(**pipe.components).to("cuda")
    apply_scheduler(pipe_i2i, args.scheduler)
    pipe_i2i.enable_vae_tiling()
    try:
        pipe_i2i.enable_xformers_memory_efficient_attention()
    except Exception:
        pass

    gen2 = torch.Generator(device="cuda").manual_seed(seed)
    start = time.perf_counter()
    img_hi = pipe_i2i(
        image=second_pass_input,
        prompt_embeds=pe,
        pooled_prompt_embeds=pooled,
        negative_prompt_embeds=ne,
        negative_pooled_prompt_embeds=npooled,
        strength=args.denoise,
        num_inference_steps=internal_second_pass_steps,
        guidance_scale=args.cfg,
        clip_skip=args.clip_skip,
        generator=gen2,
    ).images[0]
    print(f"[stage2] in {time.perf_counter() - start:.1f}s")

    final_path = run_dir / "final.png"
    final_txt = run_dir / "settings.txt"
    img_hi.save(final_path)
    final_txt.write_text(
        "\n".join(
            [
                f"checkpoint={checkpoint}",
                f"scheduler={args.scheduler}",
                f"upscale_mode={args.upscale_mode}",
                f"base_width={args.base_width}",
                f"base_height={args.base_height}",
                f"width={args.width}",
                f"height={args.height}",
                f"steps={args.steps}",
                f"hires_steps={requested_second_pass_steps}",
                f"second_pass_internal_steps={internal_second_pass_steps}",
                f"cfg={args.cfg}",
                f"denoise={args.denoise}",
                f"clip_skip={args.clip_skip}",
                f"a1111_img2img_step_math={args.a1111_img2img_step_math}",
                f"seed={seed}",
                "",
                "PROMPT:",
                args.prompt,
                "",
                "NEGATIVE:",
                args.negative,
            ]
        ),
        encoding="utf-8",
    )
    print(f"[save] final={final_path}")
    print(f"[save] settings={final_txt}")
    print(f"[cuda] after={format_mem()}")

    del pipe_i2i
    del pipe
    gc.collect()
    torch.cuda.empty_cache()
    print(f"[cuda] after_unload={format_mem()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
