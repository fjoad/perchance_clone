from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
from typing import Any

from ..config import settings
from . import prompts


class TextGenerationService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ollama_proc: subprocess.Popen | None = None
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
                "loaded": self._is_model_in_vram(),
                "mock": settings.use_mock_text,
            }

    # ------------------------------------------------------------------
    # Ollama process and model state helpers
    # ------------------------------------------------------------------

    def _ollama_running(self) -> bool:
        try:
            urllib.request.urlopen(settings.ollama_base_url, timeout=2)
            return True
        except Exception:
            return False

    def _is_model_in_vram(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{settings.ollama_base_url}/api/ps",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
            return any(
                m.get("name", "").startswith(settings.ollama_model_name)
                for m in data.get("models", [])
            )
        except Exception:
            return False

    def is_loaded(self) -> bool:
        return self._is_model_in_vram()

    def _start_ollama(self) -> None:
        if self._ollama_running():
            return
        env = os.environ.copy()
        env["OLLAMA_MODELS"] = str(settings.ollama_models_dir)
        env["OLLAMA_FLASH_ATTENTION"] = "1"
        env["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
        env["OLLAMA_NUM_PARALLEL"] = "1"
        env["OLLAMA_MAX_LOADED_MODELS"] = "1"
        self._ollama_proc = subprocess.Popen(
            [str(settings.ollama_exe), "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            if self._ollama_running():
                return
            time.sleep(1)

    # ------------------------------------------------------------------
    # Load / unload
    # ------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        if settings.use_mock_text:
            self._set_status("mock", "Mock text mode", 1.0)
            return
        with self._lock:
            self._set_status("loading", "Starting Ollama", 0.1)
            self._start_ollama()
            if self._is_model_in_vram():
                self._set_status("ready", "Text model ready", 1.0)
                return
            self._set_status("loading", "Loading text model into GPU", 0.4)
            try:
                payload = json.dumps({
                    "model": settings.ollama_model_name,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "stream": False,
                }).encode()
                req = urllib.request.Request(
                    f"{settings.ollama_base_url}/v1/chat/completions",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=300)
            except Exception:
                pass
            self._set_status("ready", "Text model ready", 1.0)

    def unload(self) -> None:
        self._set_status("unloading", "Unloading text model", 0.15)
        try:
            payload = json.dumps({
                "model": settings.ollama_model_name,
                "keep_alive": 0,
            }).encode()
            req = urllib.request.Request(
                f"{settings.ollama_base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=30)
        except Exception:
            pass
        self._set_status("idle", "Text engine idle", 0.0)

    def shutdown(self) -> None:
        self.unload()
        if self._ollama_proc is not None:
            self._ollama_proc.terminate()
            self._ollama_proc = None

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int,
        temperature: float,
        top_p: float = 0.95,
        repetition_penalty: float = 1.05,
        **_kwargs: Any,
    ) -> str:
        if settings.use_mock_text:
            self._set_status("mock", "Generating mock text response", 1.0)
            return "Mock response enabled."
        self.ensure_loaded()
        self._set_status("generating", "Generating reply", 0.8)
        payload = json.dumps({
            "model": settings.ollama_model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "repeat_penalty": repetition_penalty,
                "num_predict": max_new_tokens,
            },
        }).encode()
        req = urllib.request.Request(
            f"{settings.ollama_base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
        self._set_status("ready", "Text model ready", 1.0)
        return data["choices"][0]["message"]["content"].strip()

    # ------------------------------------------------------------------
    # Mock helper
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # High-level task methods (same interface as before)
    # ------------------------------------------------------------------

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
        compiled = prompts.build_chat_messages(
            character, user_profile, pinned_memory, summary, lore_entries, messages
        )
        return self._generate(
            compiled,
            max_new_tokens=520,
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
        compiled = prompts.build_summary_messages(
            character, user_profile, pinned_memory, previous_summary, messages
        )
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
