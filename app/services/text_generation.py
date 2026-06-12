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
from .event_log import log_event


class TextGenerationService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ollama_proc: subprocess.Popen | None = None
        self._status = {
            "state": "idle",
            "detail": "Text engine idle",
            "progress": 0.0,
        }
        self._loaded_check_at = 0.0
        self._loaded_check_value = False

    def _set_status(self, state: str, detail: str, progress: float) -> None:
        with self._lock:
            self._status = {"state": state, "detail": detail, "progress": progress}

    def snapshot(self) -> dict[str, Any]:
        # Deliberately lock-free: _set_status swaps the dict atomically, and
        # taking self._lock here would block /status while ensure_loaded holds
        # the lock during Ollama start/warmup.
        return {
            **self._status,
            "loaded": self._cached_model_loaded(),
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
            aliases = {settings.ollama_model_name}
            if ":" not in settings.ollama_model_name:
                aliases.add(f"{settings.ollama_model_name}:latest")
            if settings.ollama_model_name.endswith(":latest"):
                aliases.add(settings.ollama_model_name[:-7])
            aliases.add(settings.ollama_model_name.split(":", 1)[0])
            for model in data.get("models", []):
                names = {str(model.get("name", "")), str(model.get("model", ""))}
                names |= {name[:-7] for name in names if name.endswith(":latest")}
                if aliases & names:
                    return True
            return False
        except Exception:
            return False

    def _cache_loaded_state(self, loaded: bool) -> None:
        self._loaded_check_value = loaded
        self._loaded_check_at = time.monotonic()

    def _cached_model_loaded(self, *, max_age_s: float = 3.0) -> bool:
        if settings.use_mock_text:
            return True
        now = time.monotonic()
        if now - self._loaded_check_at < max_age_s:
            return self._loaded_check_value
        loaded = self._is_model_in_vram()
        self._cache_loaded_state(loaded)
        return loaded

    def is_loaded(self) -> bool:
        return self._cached_model_loaded(max_age_s=0.5)

    def _start_ollama(self) -> None:
        if self._ollama_running():
            log_event("ollama_external_backend_detected", base_url=settings.ollama_base_url)
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
        log_event(
            "ollama_backend_started",
            pid=self._ollama_proc.pid,
            exe=str(settings.ollama_exe),
            models_dir=str(settings.ollama_models_dir),
        )
        for _ in range(30):
            if self._ollama_running():
                return
            time.sleep(1)
        log_event("ollama_backend_start_timeout", pid=self._ollama_proc.pid if self._ollama_proc else None)

    # ------------------------------------------------------------------
    # Load / unload
    # ------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        if settings.use_mock_text:
            self._set_status("mock", "Mock text mode", 1.0)
            return
        with self._lock:
            log_event("text_model_load_start", model=settings.ollama_model_name)
            self._set_status("loading", "Starting Ollama", 0.1)
            self._start_ollama()
            if self._is_model_in_vram():
                self._cache_loaded_state(True)
                self._set_status("ready", "Text model ready", 1.0)
                log_event("text_model_load_complete", model=settings.ollama_model_name, already_loaded=True)
                return
            self._set_status("loading", "Loading text model into GPU", 0.4)
            try:
                started = time.perf_counter()
                payload = json.dumps({
                    "model": settings.ollama_model_name,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "think": False,
                    "options": {
                        "num_predict": 1,
                        "num_ctx": settings.ollama_num_ctx,
                        "num_gpu": 99,
                    },
                }).encode()
                req = urllib.request.Request(
                    f"{settings.ollama_base_url}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=300)
                log_event(
                    "text_model_load_complete",
                    model=settings.ollama_model_name,
                    already_loaded=False,
                    elapsed_s=round(time.perf_counter() - started, 3),
                )
                self._cache_loaded_state(True)
            except Exception as exc:
                log_event("text_model_load_error", model=settings.ollama_model_name, error=repr(exc))
                self._cache_loaded_state(False)
                self._set_status("error", "Text model failed to load.", 0.0)
                return
            self._set_status("ready", "Text model ready", 1.0)

    def unload(self) -> None:
        if settings.use_mock_text:
            self._set_status("idle", "Text engine idle", 0.0)
            return
        started = time.perf_counter()
        log_event("text_model_unload_start", model=settings.ollama_model_name, loaded_before=self._is_model_in_vram())
        self._set_status("unloading", "Unloading text model", 0.15)
        try:
            payload = json.dumps({
                "model": settings.ollama_model_name,
                "keep_alive": 0,
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                f"{settings.ollama_base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=30)
        except Exception as exc:
            log_event("text_model_unload_request_error", model=settings.ollama_model_name, error=repr(exc))
        for _ in range(30):
            if not self._is_model_in_vram():
                break
            time.sleep(1)
        loaded_after = self._is_model_in_vram()
        self._cache_loaded_state(loaded_after)
        log_event(
            "text_model_unload_complete",
            model=settings.ollama_model_name,
            loaded_after=loaded_after,
            elapsed_s=round(time.perf_counter() - started, 3),
        )
        self._set_status("idle", "Text engine idle", 0.0)

    def unload_for_image(self) -> None:
        """Create a hard memory boundary before A1111 starts rendering.

        A polite Ollama keep_alive=0 unload is usually enough for chat, but our
        12GB-card route smoke showed unsafe overlap when SDXL starts right after
        text prompt composition. For image turns we can afford a harder stop:
        release the model, then stop Ollama's runner/server so CUDA and commit
        pressure drop before A1111 claims memory.
        """
        log_event("text_model_unload_for_image_start", stop_ollama=settings.stop_ollama_before_image)
        self.unload()
        if settings.stop_ollama_before_image:
            self._set_status("unloading", "Stopping Ollama before image render", 0.3)
            if self._ollama_proc is not None:
                pid = self._ollama_proc.pid
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self._ollama_proc.pid)],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    try:
                        self._ollama_proc.terminate()
                    except Exception:
                        pass
                self._ollama_proc = None
                log_event("ollama_owned_backend_stop_requested", pid=pid)
            self._stop_orphaned_ollama_runners()
            time.sleep(2)
        self._set_status("idle", "Text engine idle", 0.0)
        loaded_after = self._is_model_in_vram()
        self._cache_loaded_state(loaded_after)
        log_event("text_model_unload_for_image_complete", loaded_after=loaded_after)

    def shutdown(self) -> None:
        if settings.use_mock_text:
            self._set_status("idle", "Text engine idle", 0.0)
            return
        log_event("text_backend_shutdown_start", owned_pid=self._ollama_proc.pid if self._ollama_proc else None)
        self.unload()
        if self._ollama_proc is not None:
            pid = self._ollama_proc.pid
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self._ollama_proc.pid)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                self._ollama_proc.terminate()
            self._ollama_proc = None
            log_event("ollama_owned_backend_stop_requested", pid=pid)
        self._stop_orphaned_ollama_runners()
        log_event("text_backend_shutdown_complete")

    def _stop_orphaned_ollama_runners(self) -> None:
        command = (
            "$targets = Get-CimInstance Win32_Process | Where-Object { "
            "$_.Name -eq 'ollama.exe' -and "
            "($_.CommandLine -match 'runner --' -or $_.CommandLine -match ' serve') "
            "}; "
            "$ids = @(); "
            "foreach ($p in $targets) { "
            "$ids += $p.ProcessId; "
            "try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {} "
            "}; "
            "$ids -join ','"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=30,
            )
            stopped = completed.stdout.strip()
            log_event("ollama_orphan_stop_complete", stopped_pids=stopped, returncode=completed.returncode)
        except Exception as exc:
            log_event("ollama_orphan_stop_error", error=repr(exc))

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
        status_detail: str = "Generating reply",
        status_progress: float = 0.8,
        **_kwargs: Any,
    ) -> str:
        if settings.use_mock_text:
            self._set_status("mock", f"Mock: {status_detail}", 1.0)
            return "Mock response enabled."
        self.ensure_loaded()
        self._set_status("generating", status_detail, status_progress)
        started = time.perf_counter()
        log_event(
            "text_generation_start",
            model=settings.ollama_model_name,
            message_count=len(messages),
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            status_detail=status_detail,
        )
        payload = json.dumps({
            "model": settings.ollama_model_name,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "repeat_penalty": repetition_penalty,
                "num_predict": max_new_tokens,
                "num_ctx": settings.ollama_num_ctx,
                "num_gpu": 99,
            },
        }).encode()
        req = urllib.request.Request(
            f"{settings.ollama_base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            log_event(
                "text_generation_error",
                model=settings.ollama_model_name,
                elapsed_s=round(time.perf_counter() - started, 3),
                error=repr(exc),
            )
            raise
        self._set_status("ready", "Text model ready", 1.0)
        log_event(
            "text_generation_complete",
            model=settings.ollama_model_name,
            elapsed_s=round(time.perf_counter() - started, 3),
            eval_count=data.get("eval_count"),
            eval_duration=data.get("eval_duration"),
            load_duration=data.get("load_duration"),
        )
        return data["message"]["content"].strip()

    def _generate_stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int,
        temperature: float,
        top_p: float = 0.95,
        repetition_penalty: float = 1.05,
        status_detail: str = "Generating reply",
    ):
        """Yield reply text chunks as Ollama streams them."""
        self.ensure_loaded()
        self._set_status("generating", status_detail, 0.5)
        started = time.perf_counter()
        log_event(
            "text_generation_stream_start",
            model=settings.ollama_model_name,
            message_count=len(messages),
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
        payload = json.dumps({
            "model": settings.ollama_model_name,
            "messages": messages,
            "stream": True,
            "think": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "repeat_penalty": repetition_penalty,
                "num_predict": max_new_tokens,
                "num_ctx": settings.ollama_num_ctx,
                "num_gpu": 99,
            },
        }).encode()
        req = urllib.request.Request(
            f"{settings.ollama_base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        emitted_chars = 0
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = ((data.get("message") or {}).get("content")) or ""
                    if chunk:
                        emitted_chars += len(chunk)
                        yield chunk
                    if data.get("done"):
                        log_event(
                            "text_generation_stream_complete",
                            model=settings.ollama_model_name,
                            elapsed_s=round(time.perf_counter() - started, 3),
                            eval_count=data.get("eval_count"),
                            chars=emitted_chars,
                        )
                        break
        except Exception as exc:
            log_event(
                "text_generation_stream_error",
                model=settings.ollama_model_name,
                elapsed_s=round(time.perf_counter() - started, 3),
                error=repr(exc),
            )
            raise
        finally:
            self._set_status("ready", "Text model ready", 1.0)

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
        story_frames: list[dict[str, Any]] | None = None,
        conversation_state: dict[str, Any] | None = None,
    ) -> str:
        if settings.use_mock_text:
            return self._mock_story_reply(character, messages)
        compiled = prompts.build_chat_messages(
            character, user_profile, pinned_memory, summary, lore_entries, messages, story_frames, conversation_state
        )
        return self._generate(
            compiled,
            max_new_tokens=520,
            temperature=0.9,
            top_p=0.94,
            repetition_penalty=1.03,
            status_detail="Generating story reply",
            status_progress=0.78,
        )

    def chat_reply_stream(
        self,
        character: dict[str, Any],
        user_profile: dict[str, Any],
        pinned_memory: str,
        summary: str,
        lore_entries: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        story_frames: list[dict[str, Any]] | None = None,
        conversation_state: dict[str, Any] | None = None,
    ):
        """Streaming variant of chat_reply: yields text chunks as they generate."""
        if settings.use_mock_text:
            reply = self._mock_story_reply(character, messages)
            for word in reply.split(" "):
                time.sleep(0.01)
                yield word + " "
            return
        compiled = prompts.build_chat_messages(
            character, user_profile, pinned_memory, summary, lore_entries, messages, story_frames, conversation_state
        )
        yield from self._generate_stream(
            compiled,
            max_new_tokens=520,
            temperature=0.9,
            top_p=0.94,
            repetition_penalty=1.03,
            status_detail="Writing story reply",
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
        return self._generate(
            compiled,
            max_new_tokens=180,
            temperature=0.2,
            top_p=0.9,
            repetition_penalty=1.02,
            status_detail="Summarizing memory",
            status_progress=0.72,
        )

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
        raw = self._generate(
            compiled,
            max_new_tokens=180,
            temperature=0.3,
            top_p=0.9,
            repetition_penalty=1.02,
            status_detail="Extracting visual scene",
            status_progress=0.72,
        )
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
        raw = self._generate(
            compiled,
            max_new_tokens=240,
            temperature=0.35,
            top_p=0.92,
            repetition_penalty=1.02,
            status_detail="Composing image prompt",
            status_progress=0.72,
        )
        parsed = prompts.parse_labeled_text(raw, ["POSITIVE", "NEGATIVE"])
        positive = parsed["POSITIVE"].strip()
        negative = parsed["NEGATIVE"].strip()
        positive, negative = prompts.split_leaked_negative_prompt(positive, negative)
        positive = prompts.clean_positive_image_prompt(positive)
        # The model is useful for scene-positive details, but it often writes
        # narrative "negative" scene variants. Keep negatives technical/static.
        negative = ""
        if not positive:
            return prompts.fallback_image_prompts(character, scene_summary, user_profile)
        if not negative:
            negative = prompts.fallback_image_prompts(character, scene_summary, user_profile)[1]
        return prompts.merge_image_prompt_additions(character, user_profile, positive, negative)


text_service = TextGenerationService()
