from __future__ import annotations

import gc
import math
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from diffusers import (
    DPMSolverMultistepScheduler,
    EulerAncestralDiscreteScheduler,
    StableDiffusionXLPipeline,
    StableDiffusionXLImg2ImgPipeline,
)
from PIL import Image, ImageDraw
from transformers import PreTrainedTokenizerBase

from ..config import settings


class ImageGenerationService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pipe = None
        self._pipe_i2i = None
        self._status = {
            "state": "idle",
            "detail": "Image engine idle",
            "progress": 0.0,
            "stage": "",
            "current_step": 0,
            "total_steps": 0,
            "eta_seconds": None,
            "message_id": None,
            "image_id": None,
        }

    def _set_status(
        self,
        state: str,
        detail: str,
        progress: float,
        *,
        stage: str = "",
        current_step: int = 0,
        total_steps: int = 0,
        eta_seconds: float | None = None,
        message_id: int | None = None,
        image_id: int | None = None,
    ) -> None:
        with self._lock:
            self._status = {
                "state": state,
                "detail": detail,
                "progress": progress,
                "stage": stage,
                "current_step": current_step,
                "total_steps": total_steps,
                "eta_seconds": eta_seconds,
                "message_id": message_id,
                "image_id": image_id,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._status,
                "loaded": self._pipe is not None and self._pipe_i2i is not None,
                "mock": settings.use_mock_image,
            }

    def _compute_second_pass_steps(self, requested_steps: int) -> int:
        cfg = settings.image
        if not cfg.a1111_img2img_step_math:
            return requested_steps
        if cfg.denoise_strength <= 0:
            return 0
        return int(requested_steps / min(cfg.denoise_strength, 0.999))

    def _merged_dimensions(self, override: dict[str, int] | None) -> dict[str, int]:
        if not override:
            return {
                "base_width": settings.image.base_width,
                "base_height": settings.image.base_height,
                "target_width": settings.image.target_width,
                "target_height": settings.image.target_height,
            }
        return {
            "base_width": int(override["base_width"]),
            "base_height": int(override["base_height"]),
            "target_width": int(override["target_width"]),
            "target_height": int(override["target_height"]),
        }

    def _release_working_set(self, *items: Any) -> None:
        for item in items:
            try:
                del item
            except Exception:
                pass
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass

    def _format_eta(self, eta_seconds: float | None) -> str:
        if eta_seconds is None or eta_seconds <= 0:
            return ""
        seconds = int(round(eta_seconds))
        minutes, seconds = divmod(seconds, 60)
        if minutes:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    def _make_progress_callback(
        self,
        *,
        stage_label: str,
        completed_before: int,
        total_steps: int,
        total_combined_steps: int,
        message_id: int | None,
        image_id: int | None,
    ):
        started_at = time.perf_counter()

        def callback(_pipe, step: int, _timestep: int, callback_kwargs: dict[str, Any]) -> dict[str, Any]:
            current_step = min(step + 1, total_steps)
            elapsed = time.perf_counter() - started_at
            eta = None
            if current_step > 0 and current_step < total_steps:
                eta = (elapsed / current_step) * (total_steps - current_step)
            overall_progress = (completed_before + current_step) / max(total_combined_steps, 1)
            detail = f"{stage_label} {current_step}/{total_steps}"
            eta_text = self._format_eta(eta)
            if eta_text:
                detail = f"{detail} · ETA {eta_text}"
            self._set_status(
                "running",
                detail,
                overall_progress,
                stage=stage_label.lower().replace(" ", "_"),
                current_step=current_step,
                total_steps=total_steps,
                eta_seconds=eta,
                message_id=message_id,
                image_id=image_id,
            )
            return callback_kwargs

        return callback

    def unload(self) -> None:
        with self._lock:
            self._set_status("unloading", "Unloading image pipeline", 0.15)
            if self._pipe_i2i is not None:
                del self._pipe_i2i
                self._pipe_i2i = None
            if self._pipe is not None:
                del self._pipe
                self._pipe = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            self._set_status("idle", "Image engine idle", 0.0)

    def _relative_output_path(self, path: Path) -> str:
        return path.relative_to(settings.outputs_dir).as_posix()

    def _save_mock_image(
        self,
        path: Path,
        *,
        title: str,
        subtitle: str,
        size: tuple[int, int],
    ) -> None:
        image = Image.new("RGB", size, color=(14, 20, 34))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((18, 18, size[0] - 18, size[1] - 18), radius=22, outline=(90, 138, 255), width=2)
        draw.text((36, 36), title, fill=(238, 242, 255))
        draw.multiline_text((36, 86), subtitle, fill=(154, 166, 197), spacing=6)
        image.save(path)

    def _decode_latents_to_pil(self, latents: torch.Tensor) -> Image.Image:
        if latents.ndim == 3:
            latents = latents.unsqueeze(0)
        latents = latents.to(device="cuda", dtype=self._pipe.vae.dtype)
        latents = latents / self._pipe.vae.config.scaling_factor
        with torch.no_grad():
            image = self._pipe.vae.decode(latents, return_dict=False)[0]
        return self._pipe.image_processor.postprocess(image, output_type="pil")[0]

    def _upscale_latents(self, latents: torch.Tensor) -> torch.Tensor:
        if latents.ndim == 3:
            latents = latents.unsqueeze(0)
        cfg = settings.image
        scale_kwargs: dict[str, Any] = {"mode": "bilinear"}
        if cfg.upscale_method == "latent":
            scale_kwargs["antialias"] = False
            scale_kwargs["align_corners"] = False
        latent_height = cfg.target_height // self._pipe.vae_scale_factor
        latent_width = cfg.target_width // self._pipe.vae_scale_factor
        return F.interpolate(latents, size=(latent_height, latent_width), **scale_kwargs)

    def _apply_scheduler(self, pipe) -> None:
        if settings.image.scheduler == "euler_a":
            pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
        else:
            pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                pipe.scheduler.config,
                algorithm_type="dpmsolver++",
                solver_order=2,
                use_karras_sigmas=True,
            )

    def _expand_weights(self, text: str, *, base_repeats: int = 2) -> str:
        def repl(match: re.Match[str]) -> str:
            phrase = match.group(1).strip()
            weight = float(match.group(2))
            reps = max(1, int(math.ceil(base_repeats * (weight - 1.0))))
            return ", ".join([phrase] * (reps + 1))

        text = re.sub(r"\bBREAK\b", ",", text, flags=re.IGNORECASE)
        return re.sub(r"\(([^():]+):([0-9.]+)\)", repl, text)

    def _encode_chunks(
        self,
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

    def _blank_chunk_embed(
        self,
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

    def _pad_to_len(self, hs: torch.Tensor, target_tokens: int, pad_chunk: torch.Tensor) -> torch.Tensor:
        current = hs.shape[1]
        if current >= target_tokens:
            return hs
        need = target_tokens - current
        if need % pad_chunk.shape[1] != 0:
            raise ValueError("Prompt embedding padding is not aligned to CLIP chunk size.")
        reps = need // pad_chunk.shape[1]
        return torch.cat([hs] + [pad_chunk] * reps, dim=1)

    def _sdxl_encode_long_both(
        self,
        pipe: StableDiffusionXLPipeline,
        text: str,
        *,
        clip_skip: int = 2,
        chunk_payload: int = 75,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        device = pipe.device
        hs1, _ = self._encode_chunks(pipe.tokenizer, pipe.text_encoder, text, device, chunk_payload, clip_skip)
        hs2, pooled2 = self._encode_chunks(pipe.tokenizer_2, pipe.text_encoder_2, text, device, chunk_payload, clip_skip)
        pad1, _ = self._blank_chunk_embed(pipe.tokenizer, pipe.text_encoder, device, clip_skip)
        pad2, _ = self._blank_chunk_embed(pipe.tokenizer_2, pipe.text_encoder_2, device, clip_skip)
        target_tokens = max(hs1.shape[1], hs2.shape[1])
        hs1 = self._pad_to_len(hs1, target_tokens, pad1)
        hs2 = self._pad_to_len(hs2, target_tokens, pad2)
        cat = torch.cat([hs1, hs2], dim=-1)
        return cat, pooled2

    def _prepare_prompt_embeds(
        self,
        pipe: StableDiffusionXLPipeline,
        positive_prompt: str,
        negative_prompt: str,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        cfg = settings.image
        pe, pooled = self._sdxl_encode_long_both(pipe, positive_prompt, clip_skip=cfg.clip_skip)
        ne, npooled = self._sdxl_encode_long_both(pipe, negative_prompt or "", clip_skip=cfg.clip_skip)
        pad1, _ = self._blank_chunk_embed(pipe.tokenizer, pipe.text_encoder, pipe.device, cfg.clip_skip)
        pad2, _ = self._blank_chunk_embed(pipe.tokenizer_2, pipe.text_encoder_2, pipe.device, cfg.clip_skip)
        pad2048 = torch.cat([pad1, pad2], dim=-1).to(pipe.unet.dtype)
        target_tokens = max(pe.shape[1], ne.shape[1])
        pe = self._pad_to_len(pe, target_tokens, pad2048).to(pipe.unet.dtype)
        ne = self._pad_to_len(ne, target_tokens, pad2048).to(pipe.unet.dtype)
        pooled = pooled.to(pipe.unet.dtype)
        npooled = npooled.to(pipe.unet.dtype)
        return pe, pooled, ne, npooled

    def ensure_loaded(self) -> None:
        if settings.use_mock_image:
            self._set_status("mock", "Mock image mode", 1.0)
            return
        if self._pipe is not None and self._pipe_i2i is not None:
            self._set_status("ready", "Image pipeline ready", 1.0)
            return
        if not settings.image.checkpoint.exists():
            raise FileNotFoundError(f"Image checkpoint not found: {settings.image.checkpoint}")
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for the default SDXL image pipeline.")
        with self._lock:
            if self._pipe is not None and self._pipe_i2i is not None:
                self._set_status("ready", "Image pipeline ready", 1.0)
                return
            self._set_status("loading", "Loading image pipeline", 0.15)
            pipe = StableDiffusionXLPipeline.from_single_file(
                str(settings.image.checkpoint),
                torch_dtype=torch.float16,
                safety_checker=None,
            ).to("cuda")
            self._apply_scheduler(pipe)
            pipe.enable_vae_tiling()
            try:
                pipe.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
            pipe_i2i = StableDiffusionXLImg2ImgPipeline(**pipe.components).to("cuda")
            self._apply_scheduler(pipe_i2i)
            pipe_i2i.enable_vae_tiling()
            try:
                pipe_i2i.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
            self._pipe = pipe
            self._pipe_i2i = pipe_i2i
            self._set_status("ready", "Image pipeline ready", 1.0)

    def generate(
        self,
        character: dict[str, Any],
        conversation_id: int,
        message_id: int | None,
        image_id: int | None,
        scene_summary: str,
        positive_prompt: str,
        negative_prompt: str,
        resolution_override: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        self._set_status("preparing", "Preparing image request", 0.05, message_id=message_id, image_id=image_id)
        self.ensure_loaded()
        cfg = settings.image
        dims = self._merged_dimensions(resolution_override)
        seed = random.randint(1, 2**31 - 1)
        character_dir = settings.outputs_dir / character["slug"]
        character_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stage1_path = character_dir / f"{stamp}_stage1.png"
        final_path = character_dir / f"{stamp}_final.png"

        if settings.use_mock_image:
            self._set_status("mock", "Generating mock image", 1.0, message_id=message_id, image_id=image_id)
            self._save_mock_image(
                stage1_path,
                title=f"{character['display_name']} - Stage 1",
                subtitle=scene_summary[:220],
                size=(cfg.base_width, cfg.base_height),
            )
            self._save_mock_image(
                final_path,
                title=f"{character['display_name']} - Hires",
                subtitle=positive_prompt[:320],
                size=(cfg.target_width, cfg.target_height),
            )
            return {
                "character_id": character["id"],
                "conversation_id": conversation_id,
                "message_id": message_id,
                "scene_summary": scene_summary,
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "base_width": dims["base_width"],
                "base_height": dims["base_height"],
                "target_width": dims["target_width"],
                "target_height": dims["target_height"],
                "denoise_strength": cfg.denoise_strength,
                "seed": seed,
                "stage1_output_path": self._relative_output_path(stage1_path),
                "output_path": self._relative_output_path(final_path),
                "status": "completed",
                "error": "",
            }

        generator_1 = torch.Generator(device="cuda").manual_seed(seed)
        self._set_status("conditioning", "Encoding prompt conditioning", 0.12, message_id=message_id)
        positive_prompt = self._expand_weights(positive_prompt)
        negative_prompt = self._expand_weights(negative_prompt or "")
        pe, pooled, ne, npooled = self._prepare_prompt_embeds(self._pipe, positive_prompt, negative_prompt)
        requested_second_pass_steps = cfg.hires_steps or cfg.steps
        second_pass_steps = self._compute_second_pass_steps(requested_second_pass_steps)
        total_combined_steps = cfg.steps + max(second_pass_steps, 1)
        self._set_status(
            "running",
            f"Base pass 0/{cfg.steps}",
            0.15,
                stage="base_pass",
                current_step=0,
                total_steps=cfg.steps,
                message_id=message_id,
                image_id=image_id,
            )
        stage1_result = self._pipe(
            prompt_embeds=pe,
            pooled_prompt_embeds=pooled,
            negative_prompt_embeds=ne,
            negative_pooled_prompt_embeds=npooled,
            num_inference_steps=cfg.steps,
            guidance_scale=cfg.guidance_scale,
            width=dims["base_width"],
            height=dims["base_height"],
            generator=generator_1,
            clip_skip=cfg.clip_skip,
            output_type="latent" if cfg.upscale_method == "latent" else "pil",
            callback_on_step_end=self._make_progress_callback(
                stage_label="Base pass",
                completed_before=0,
                total_steps=cfg.steps,
                total_combined_steps=total_combined_steps,
                message_id=message_id,
                image_id=image_id,
            ),
        ).images[0]

        if cfg.upscale_method == "latent":
            stage1_latents = stage1_result
            img_lo = self._decode_latents_to_pil(stage1_latents)
            second_pass_input = self._upscale_latents(stage1_latents).to(
                device="cuda", dtype=self._pipe_i2i.unet.dtype
            )
        else:
            img_lo = stage1_result
            second_pass_input = img_lo.resize((dims["target_width"], dims["target_height"]), resample=Image.LANCZOS)
        img_lo.save(stage1_path)

        generator_2 = torch.Generator(device="cuda").manual_seed(seed)
        self._set_status(
            "running",
            f"Hires pass 0/{second_pass_steps}",
            cfg.steps / max(total_combined_steps, 1),
            stage="hires_pass",
            current_step=0,
            total_steps=second_pass_steps,
            message_id=message_id,
            image_id=image_id,
        )
        img_hi = self._pipe_i2i(
            image=second_pass_input,
            prompt_embeds=pe,
            pooled_prompt_embeds=pooled,
            negative_prompt_embeds=ne,
            negative_pooled_prompt_embeds=npooled,
            strength=cfg.denoise_strength,
            num_inference_steps=second_pass_steps,
            guidance_scale=cfg.guidance_scale,
            generator=generator_2,
            clip_skip=cfg.clip_skip,
            callback_on_step_end=self._make_progress_callback(
                stage_label="Hires pass",
                completed_before=cfg.steps,
                total_steps=second_pass_steps,
                total_combined_steps=total_combined_steps,
                message_id=message_id,
                image_id=image_id,
            ),
        ).images[0]
        img_hi.save(final_path)
        self._set_status("ready", "Image pipeline ready", 1.0)

        return {
            "character_id": character["id"],
            "conversation_id": conversation_id,
            "message_id": message_id,
            "scene_summary": scene_summary,
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "base_width": dims["base_width"],
            "base_height": dims["base_height"],
            "target_width": dims["target_width"],
            "target_height": dims["target_height"],
            "denoise_strength": cfg.denoise_strength,
            "second_pass_steps": second_pass_steps,
            "seed": seed,
            "stage1_output_path": self._relative_output_path(stage1_path),
            "output_path": self._relative_output_path(final_path),
            "status": "completed",
            "error": "",
        }
    def _release_working_set(self, *items: Any) -> None:
        for item in items:
            try:
                del item
            except Exception:
                pass
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

    def _make_progress_callback(
        self,
        *,
        stage_label: str,
        completed_before: int,
        total_steps: int,
        total_combined_steps: int,
        message_id: int | None,
        image_id: int | None,
    ):
        started_at = time.perf_counter()

        def callback(_pipe, step: int, _timestep: int, callback_kwargs: dict[str, Any]) -> dict[str, Any]:
            current_step = min(step + 1, total_steps)
            elapsed = time.perf_counter() - started_at
            eta = None
            if current_step > 0 and current_step < total_steps:
                eta = (elapsed / current_step) * (total_steps - current_step)
            overall_progress = (completed_before + current_step) / max(total_combined_steps, 1)
            detail = f"{stage_label} {current_step}/{total_steps}"
            eta_text = self._format_eta(eta)
            if eta_text:
                detail = f"{detail} - ETA {eta_text}"
            self._set_status(
                "running",
                detail,
                overall_progress,
                stage=stage_label.lower().replace(" ", "_"),
                current_step=current_step,
                total_steps=total_steps,
                eta_seconds=eta,
                message_id=message_id,
                image_id=image_id,
            )
            return callback_kwargs

        return callback

    def _upscale_latents(self, latents: torch.Tensor, *, target_width: int, target_height: int) -> torch.Tensor:
        if latents.ndim == 3:
            latents = latents.unsqueeze(0)
        cfg = settings.image
        scale_kwargs: dict[str, Any] = {"mode": "bilinear"}
        if cfg.upscale_method == "latent":
            scale_kwargs["antialias"] = False
            scale_kwargs["align_corners"] = False
        latent_height = target_height // self._pipe.vae_scale_factor
        latent_width = target_width // self._pipe.vae_scale_factor
        return F.interpolate(latents, size=(latent_height, latent_width), **scale_kwargs)

    def generate(
        self,
        character: dict[str, Any],
        conversation_id: int,
        message_id: int | None,
        image_id: int | None,
        scene_summary: str,
        positive_prompt: str,
        negative_prompt: str,
        resolution_override: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        self._set_status("preparing", "Preparing image request", 0.05, message_id=message_id, image_id=image_id)
        self.ensure_loaded()
        cfg = settings.image
        dims = self._merged_dimensions(resolution_override)
        seed = random.randint(1, 2**31 - 1)
        character_dir = settings.outputs_dir / character["slug"]
        character_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stage1_path = character_dir / f"{stamp}_stage1.png"
        final_path = character_dir / f"{stamp}_final.png"

        generator_1 = None
        generator_2 = None
        pe = None
        pooled = None
        ne = None
        npooled = None
        stage1_result = None
        stage1_latents = None
        img_lo = None
        second_pass_input = None
        img_hi = None

        try:
            if settings.use_mock_image:
                self._set_status("mock", "Generating mock image", 1.0, message_id=message_id, image_id=image_id)
                self._save_mock_image(
                    stage1_path,
                    title=f"{character['display_name']} - Stage 1",
                    subtitle=scene_summary[:220],
                    size=(dims["base_width"], dims["base_height"]),
                )
                self._save_mock_image(
                    final_path,
                    title=f"{character['display_name']} - Hires",
                    subtitle=positive_prompt[:320],
                    size=(dims["target_width"], dims["target_height"]),
                )
                return {
                    "character_id": character["id"],
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "scene_summary": scene_summary,
                    "positive_prompt": positive_prompt,
                    "negative_prompt": negative_prompt,
                    "base_width": dims["base_width"],
                    "base_height": dims["base_height"],
                    "target_width": dims["target_width"],
                    "target_height": dims["target_height"],
                    "denoise_strength": cfg.denoise_strength,
                    "seed": seed,
                    "stage1_output_path": self._relative_output_path(stage1_path),
                    "output_path": self._relative_output_path(final_path),
                    "status": "completed",
                    "error": "",
                }

            generator_1 = torch.Generator(device="cuda").manual_seed(seed)
            self._set_status(
                "conditioning",
                "Encoding prompt conditioning",
                0.12,
                message_id=message_id,
                image_id=image_id,
            )
            positive_prompt = self._expand_weights(positive_prompt)
            negative_prompt = self._expand_weights(negative_prompt or "")
            pe, pooled, ne, npooled = self._prepare_prompt_embeds(self._pipe, positive_prompt, negative_prompt)
            requested_second_pass_steps = cfg.hires_steps or cfg.steps
            second_pass_steps = self._compute_second_pass_steps(requested_second_pass_steps)
            total_combined_steps = cfg.steps + max(second_pass_steps, 1)
            self._set_status(
                "running",
                f"Base pass 0/{cfg.steps}",
                0.15,
                stage="base_pass",
                current_step=0,
                total_steps=cfg.steps,
                message_id=message_id,
                image_id=image_id,
            )
            stage1_result = self._pipe(
                prompt_embeds=pe,
                pooled_prompt_embeds=pooled,
                negative_prompt_embeds=ne,
                negative_pooled_prompt_embeds=npooled,
                num_inference_steps=cfg.steps,
                guidance_scale=cfg.guidance_scale,
                width=dims["base_width"],
                height=dims["base_height"],
                generator=generator_1,
                clip_skip=cfg.clip_skip,
                output_type="latent" if cfg.upscale_method == "latent" else "pil",
                callback_on_step_end=self._make_progress_callback(
                    stage_label="Base pass",
                    completed_before=0,
                    total_steps=cfg.steps,
                    total_combined_steps=total_combined_steps,
                    message_id=message_id,
                    image_id=image_id,
                ),
            ).images[0]

            if cfg.upscale_method == "latent":
                stage1_latents = stage1_result
                img_lo = self._decode_latents_to_pil(stage1_latents)
                second_pass_input = self._upscale_latents(
                    stage1_latents,
                    target_width=dims["target_width"],
                    target_height=dims["target_height"],
                ).to(device="cuda", dtype=self._pipe_i2i.unet.dtype)
            else:
                img_lo = stage1_result
                second_pass_input = img_lo.resize(
                    (dims["target_width"], dims["target_height"]),
                    resample=Image.LANCZOS,
                )
            img_lo.save(stage1_path)

            generator_2 = torch.Generator(device="cuda").manual_seed(seed)
            self._set_status(
                "running",
                f"Hires pass 0/{second_pass_steps}",
                cfg.steps / max(total_combined_steps, 1),
                stage="hires_pass",
                current_step=0,
                total_steps=second_pass_steps,
                message_id=message_id,
                image_id=image_id,
            )
            img_hi = self._pipe_i2i(
                image=second_pass_input,
                prompt_embeds=pe,
                pooled_prompt_embeds=pooled,
                negative_prompt_embeds=ne,
                negative_pooled_prompt_embeds=npooled,
                strength=cfg.denoise_strength,
                num_inference_steps=second_pass_steps,
                guidance_scale=cfg.guidance_scale,
                generator=generator_2,
                clip_skip=cfg.clip_skip,
                callback_on_step_end=self._make_progress_callback(
                    stage_label="Hires pass",
                    completed_before=cfg.steps,
                    total_steps=second_pass_steps,
                    total_combined_steps=total_combined_steps,
                    message_id=message_id,
                    image_id=image_id,
                ),
            ).images[0]
            img_hi.save(final_path)
            self._set_status("ready", "Image pipeline ready", 1.0)

            return {
                "character_id": character["id"],
                "conversation_id": conversation_id,
                "message_id": message_id,
                "scene_summary": scene_summary,
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "base_width": dims["base_width"],
                "base_height": dims["base_height"],
                "target_width": dims["target_width"],
                "target_height": dims["target_height"],
                "denoise_strength": cfg.denoise_strength,
                "second_pass_steps": second_pass_steps,
                "seed": seed,
                "stage1_output_path": self._relative_output_path(stage1_path),
                "output_path": self._relative_output_path(final_path),
                "status": "completed",
                "error": "",
            }
        finally:
            self._release_working_set(
                generator_1,
                generator_2,
                pe,
                pooled,
                ne,
                npooled,
                stage1_result,
                stage1_latents,
                img_lo,
                second_pass_input,
                img_hi,
            )


image_service = ImageGenerationService()
