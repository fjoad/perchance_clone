from __future__ import annotations

import gc
import threading
from typing import Any

from ..config import settings

import torch
import transformers.modeling_utils as modeling_utils
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from . import prompts


class TextGenerationService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model = None
        self._tokenizer = None
        self._status = {
            "state": "idle",
            "detail": "Text engine idle",
            "progress": 0.0,
        }

    def _set_status(self, state: str, detail: str, progress: float) -> None:
        with self._lock:
            self._status = {"state": state, "detail": detail, "progress": progress}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._status,
                "loaded": self._model is not None and self._tokenizer is not None,
                "mock": settings.use_mock_text,
            }

    def is_loaded(self) -> bool:
        with self._lock:
            return self._model is not None and self._tokenizer is not None

    def unload(self) -> None:
        with self._lock:
            self._set_status("unloading", "Unloading text model", 0.15)
            if self._model is not None:
                del self._model
                self._model = None
            if self._tokenizer is not None:
                del self._tokenizer
                self._tokenizer = None
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
            self._set_status("idle", "Text engine idle", 0.0)

    def ensure_loaded(self) -> None:
        if settings.use_mock_text:
            self._set_status("mock", "Mock text mode", 1.0)
            return
        if self._model is not None and self._tokenizer is not None:
            self._set_status("ready", "Text model ready", 1.0)
            return
        with self._lock:
            if self._model is not None and self._tokenizer is not None:
                self._set_status("ready", "Text model ready", 1.0)
                return
            self._set_status("loading", "Loading text model", 0.2)
            if torch.cuda.is_available():
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
            bnb_cfg = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
            modeling_utils.caching_allocator_warmup = lambda *_, **__: None
            self._tokenizer = AutoTokenizer.from_pretrained(
                settings.text_model_id,
                use_fast=True,
                cache_dir=str(settings.hf_hub_cache),
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                settings.text_model_id,
                quantization_config=bnb_cfg,
                device_map="auto",
                trust_remote_code=False,
                cache_dir=str(settings.hf_hub_cache),
                low_cpu_mem_usage=True,
            )
            if self._tokenizer.pad_token_id is None and self._tokenizer.eos_token_id is not None:
                self._tokenizer.pad_token = self._tokenizer.eos_token
            self._set_status("ready", "Text model ready", 1.0)

    def _generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int,
        temperature: float,
        min_new_tokens: int = 0,
        top_p: float = 0.95,
        repetition_penalty: float = 1.05,
    ) -> str:
        if settings.use_mock_text:
            self._set_status("mock", "Generating mock text response", 1.0)
            return "Mock response enabled."
        self.ensure_loaded()
        self._set_status("preparing", "Preparing reply", 0.45)
        prompt = None
        inputs = None
        output = None
        new_ids = None
        try:
            prompt = self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
            inputs = self._tokenizer(
                prompt,
                return_tensors="pt",
                return_token_type_ids=False,
            )
            device = "cuda" if torch.cuda.is_available() else "cpu"
            inputs = {k: v.to(device) for k, v in inputs.items()}
            self._set_status("generating", "Generating reply", 0.8)
            with torch.no_grad():
                output = self._model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    min_new_tokens=min_new_tokens,
                    do_sample=True,
                    temperature=temperature,
                    top_p=top_p,
                    repetition_penalty=repetition_penalty,
                    pad_token_id=self._tokenizer.eos_token_id,
                    eos_token_id=self._tokenizer.eos_token_id,
                )
            new_ids = output[0, inputs["input_ids"].shape[1] :]
            return self._tokenizer.decode(new_ids, skip_special_tokens=True).strip()
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
            self._set_status("ready", "Text model ready", 1.0)

    def _mock_story_reply(self, character: dict[str, Any], messages: list[dict[str, Any]]) -> str:
        latest_user = next((msg["content"] for msg in reversed(messages) if msg["role"] == "user"), "").strip()
        cue = latest_user or "the moment between you"
        return (
            f"{character['display_name']} lets the silence soften around {cue}, the scene settling into that "
            "charged little pause where attention feels almost physical.\n\n"
            f'"Oh my~" she says at last, warm amusement threading through the moment as she steps naturally back '
            f"into the rhythm between you. \"If we're going to linger here together, then let me make this worth "
            f"remembering.\"\n\n"
            "Her reply leaves the scene open instead of closing it off, giving the user a natural next beat to answer."
        )

    def chat_reply(
        self,
        character: dict[str, Any],
        user_profile: dict[str, Any],
        pinned_memory: str,
        summary: str,
        lore_entries: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> str:
        if settings.use_mock_text:
            return self._mock_story_reply(character, messages)
        compiled = prompts.build_chat_messages(character, user_profile, pinned_memory, summary, lore_entries, messages)
        return self._generate(
            compiled,
            max_new_tokens=520,
            min_new_tokens=150,
            temperature=0.9,
            top_p=0.94,
            repetition_penalty=1.03,
        )

    def summarize_memory(
        self,
        character: dict[str, Any],
        user_profile: dict[str, Any],
        pinned_memory: str,
        previous_summary: str,
        messages: list[dict[str, Any]],
    ) -> str:
        if settings.use_mock_text:
            return previous_summary or "Mock summary: maintain tone, continuity, and relationship context."
        compiled = prompts.build_summary_messages(character, user_profile, pinned_memory, previous_summary, messages)
        return self._generate(compiled, max_new_tokens=180, temperature=0.2, top_p=0.9, repetition_penalty=1.02)

    def extract_scene(
        self,
        character: dict[str, Any],
        user_profile: dict[str, Any],
        messages: list[dict[str, Any]],
        note: str = "",
    ) -> str:
        if settings.use_mock_text:
            return prompts.fallback_scene_summary(character, note)
        compiled = prompts.build_scene_messages(character, user_profile, messages, note)
        raw = self._generate(compiled, max_new_tokens=180, temperature=0.3, top_p=0.9, repetition_penalty=1.02)
        parsed = prompts.parse_labeled_text(raw, ["SCENE", "OUTFIT", "MOOD"])
        parts = [parsed["SCENE"], parsed["OUTFIT"], parsed["MOOD"]]
        scene = ". ".join(part for part in parts if part)
        return scene or prompts.fallback_scene_summary(character, note)

    def compose_image_prompts(
        self,
        character: dict[str, Any],
        user_profile: dict[str, Any],
        scene_summary: str,
    ) -> tuple[str, str]:
        if settings.use_mock_text:
            return prompts.fallback_image_prompts(character, scene_summary, user_profile)
        compiled = prompts.build_image_prompt_messages(character, user_profile, scene_summary)
        raw = self._generate(compiled, max_new_tokens=240, temperature=0.35, top_p=0.92, repetition_penalty=1.02)
        parsed = prompts.parse_labeled_text(raw, ["POSITIVE", "NEGATIVE"])
        positive = parsed["POSITIVE"].strip()
        negative = parsed["NEGATIVE"].strip()
        if not positive:
            return prompts.fallback_image_prompts(character, scene_summary, user_profile)
        if not negative:
            negative = prompts.fallback_image_prompts(character, scene_summary, user_profile)[1]
        return prompts.merge_image_prompt_additions(character, user_profile, positive, negative)


text_service = TextGenerationService()
