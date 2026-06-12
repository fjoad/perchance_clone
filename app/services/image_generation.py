from __future__ import annotations

import base64
import json
import os
import random
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..config import settings
from .event_log import log_event
from .resource_guard import ResourceGuardError, ResourceWatchdog, assert_safe, resource_snapshot


class ImageGenerationService:
    """A1111-backed image generation service.

    The old app path loaded SDXL directly inside the FastAPI process. Our
    production experiments showed the better runtime shape is to keep A1111 hot
    as a separate process, unload Ollama text before the actual render, and call
    the A1111 API for each image.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._a1111_proc: subprocess.Popen | None = None
        self._owns_a1111 = False
        self._checkpoint_configured = False
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
        # Deliberately lock-free: _set_status swaps the dict atomically, and
        # taking self._lock here would block /status for the entire A1111
        # cold boot (ensure_loaded holds the lock for up to 6 minutes).
        status = dict(self._status)
        proc = self._a1111_proc
        proc_alive = proc is not None and proc.poll() is None
        if settings.use_mock_image:
            loaded = True
        elif status.get("state") in {"loading", "ready", "running", "finalizing", "recovering"}:
            loaded = True
        elif proc_alive:
            loaded = True
        else:
            loaded = False
        return {
            **status,
            "loaded": loaded,
            "mock": settings.use_mock_image,
            "backend": settings.image.backend,
        }

    def _relative_output_path(self, path: Path) -> str:
        return path.relative_to(settings.outputs_dir).as_posix()

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

    def _make_url(self, path: str) -> str:
        return f"{settings.image.a1111_base_url.rstrip('/')}{path}"

    def _get_json(self, path: str, *, timeout: float = 10) -> dict[str, Any]:
        with urllib.request.urlopen(self._make_url(path), timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        return json.loads(body) if body.strip() else {}

    def _post_json(self, path: str, payload: dict[str, Any], *, timeout: float = 3600) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._make_url(path),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        return json.loads(body) if body.strip() else {}

    def _start_progress_poller(
        self,
        message_id: int | None,
        image_id: int | None,
        fallback_total: int,
    ) -> tuple[threading.Event, threading.Thread]:
        """Poll A1111's progress endpoint during a render so the UI gets real steps/ETA."""
        stop = threading.Event()

        def poll() -> None:
            while not stop.wait(1.0):
                try:
                    data = self._get_json("/sdapi/v1/progress?skip_current_image=true", timeout=4)
                except Exception:
                    continue
                state = data.get("state") or {}
                step = int(state.get("sampling_step") or 0)
                steps = int(state.get("sampling_steps") or 0) or fallback_total
                progress = float(data.get("progress") or 0.0)
                if progress <= 0 and step <= 0:
                    continue
                eta_raw = data.get("eta_relative")
                try:
                    eta_s = float(eta_raw) if eta_raw is not None else None
                except (TypeError, ValueError):
                    eta_s = None
                detail = f"Rendering image {step}/{steps}"
                if eta_s and eta_s > 0.5:
                    detail += f" - ETA {int(round(eta_s))}s"
                self._set_status(
                    "running",
                    detail,
                    max(0.05, min(progress, 0.99)),
                    stage="render",
                    current_step=step,
                    total_steps=steps,
                    eta_seconds=eta_s,
                    message_id=message_id,
                    image_id=image_id,
                )

        thread = threading.Thread(target=poll, name="a1111-progress-poller", daemon=True)
        thread.start()
        return stop, thread

    def _a1111_ready(self, *, timeout: float = 3) -> bool:
        try:
            self._get_json("/sdapi/v1/options", timeout=timeout)
            return True
        except Exception:
            return False

    def _start_a1111(self) -> None:
        if self._a1111_ready(timeout=2):
            if self._a1111_proc is None:
                self._owns_a1111 = False
                log_event("a1111_external_backend_detected")
            return
        root = settings.image.a1111_root
        launcher = root / "webui-user.bat"
        if not launcher.exists():
            raise FileNotFoundError(f"A1111 launcher not found: {launcher}")
        env = os.environ.copy()
        env["HF_HOME"] = str(settings.hf_home)
        env["HF_HUB_CACHE"] = str(settings.hf_hub_cache)
        env["HUGGINGFACE_HUB_CACHE"] = str(settings.hf_hub_cache)
        env["TORCH_HOME"] = str(settings.torch_home)
        env["CUDA_CACHE_PATH"] = str(settings.cuda_cache_path)
        env["TMP"] = str(settings.temp_dir)
        env["TEMP"] = str(settings.temp_dir)
        # If inherited (some sandboxed shells set it), this var stops cmd.exe
        # from resolving `call webui.bat` relative to the A1111 root and the
        # boot dies instantly with "'webui.bat' is not recognized".
        env.pop("NoDefaultCurrentDirectoryInExePath", None)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log_path = settings.runtime_dir / "logs" / "a1111_app.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("ab")
        self._a1111_proc = subprocess.Popen(
            ["cmd.exe", "/c", str(launcher)],
            cwd=str(root),
            env=env,
            stdout=log,
            stderr=log,
            creationflags=creationflags,
        )
        self._owns_a1111 = True
        log_event("a1111_backend_started", pid=self._a1111_proc.pid, root=str(root), log_path=str(log_path))
        deadline = time.perf_counter() + 360
        while time.perf_counter() < deadline:
            if self._a1111_ready(timeout=3):
                return
            time.sleep(5)
        raise RuntimeError(f"A1111 did not become ready. See {log_path}")

    def _set_a1111_options(self) -> None:
        if self._checkpoint_configured:
            return
        cfg = settings.image
        options = self._get_json("/sdapi/v1/options", timeout=10)
        current_checkpoint = str(options.get("sd_model_checkpoint", ""))
        current_clip_skip = int(options.get("CLIP_stop_at_last_layers") or 0)
        payload: dict[str, Any] = {}
        if cfg.checkpoint.name not in current_checkpoint:
            payload["sd_model_checkpoint"] = cfg.checkpoint.name
        if current_clip_skip != cfg.clip_skip:
            payload["CLIP_stop_at_last_layers"] = cfg.clip_skip
        if payload:
            log_event("a1111_options_update", payload=payload)
            self._post_json("/sdapi/v1/options", payload, timeout=180)
        self._checkpoint_configured = True

    def ensure_loaded(self) -> None:
        if settings.use_mock_image:
            self._set_status("mock", "Mock image mode", 1.0)
            return
        with self._lock:
            if self._checkpoint_configured and self._a1111_ready(timeout=1):
                self._set_status("ready", "A1111 image backend ready", 1.0)
                return
            self._set_status("loading", "Starting A1111 image backend", 0.15, stage="loading")
            self._start_a1111()
            self._set_status("loading", "Selecting A1111 checkpoint", 0.45, stage="checkpoint")
            self._set_a1111_options()
            self._set_status("ready", "A1111 image backend ready", 1.0)

    def unload(self) -> None:
        """Release transient status after an image task.

        For A1111 this intentionally does not stop the server. Keeping A1111 hot
        was the fastest stable policy in the experiments.
        """
        if settings.image.a1111_keep_hot:
            with self._lock:
                status = dict(self._status)
            if status.get("state") == "ready" and status.get("stage") == "completed" and status.get("message_id"):
                return
            self._set_status("ready", "A1111 image backend ready", 1.0)
            return
        self.shutdown()

    def shutdown(self) -> None:
        log_event("image_backend_shutdown_start", owns_a1111=self._owns_a1111, pid=self._a1111_proc.pid if self._a1111_proc else None)
        self._set_status("unloading", "Stopping image backend", 0.15, stage="shutdown")
        proc = self._a1111_proc
        if proc is not None and self._owns_a1111:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
            self._a1111_proc = None
            self._stop_orphaned_a1111_children()
        else:
            self._a1111_proc = None
        self._owns_a1111 = False
        self._checkpoint_configured = False
        self._set_status("idle", "Image engine idle", 0.0)
        log_event("image_backend_shutdown_complete")

    def _stop_orphaned_a1111_children(self) -> None:
        """Best-effort cleanup for webui children that outlive the launcher."""
        root = str(settings.image.a1111_root).replace("\\", "\\\\")
        command = (
            "$targets = Get-CimInstance Win32_Process | Where-Object { "
            "($_.Name -eq 'python.exe' -or $_.Name -eq 'cmd.exe') -and "
            f"$_.CommandLine -match '{root}|stable-diffusion-webui|launch.py|webui-user.bat' "
            "}; "
            "foreach ($p in $targets) { "
            "try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {} "
            "}"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except Exception:
            pass

    def _resource_guard_stop(self, reason: str) -> None:
        with self._lock:
            message_id = self._status.get("message_id")
            image_id = self._status.get("image_id")
        self._set_status(
            "error",
            f"Image render stopped by resource guard: {reason}",
            0.0,
            stage="guard",
            message_id=message_id,
            image_id=image_id,
        )
        self._stop_orphaned_a1111_children()
        self._a1111_proc = None
        self._owns_a1111 = False
        log_event("resource_guard_trip", component="a1111", reason=reason, message_id=message_id, image_id=image_id)
        self._checkpoint_configured = False

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
        stem = f"{stamp}_m{message_id or 'none'}"
        final_path = character_dir / f"{stem}_final.png"
        settings_path = character_dir / f"{stem}_a1111_settings.json"

        if settings.use_mock_image:
            self._set_status("mock", "Generating mock image", 1.0, message_id=message_id, image_id=image_id)
            self._save_mock_image(
                final_path,
                title=f"{character['display_name']} - A1111 Mock",
                subtitle=positive_prompt[:320],
                size=(dims["target_width"], dims["target_height"]),
            )
            return self._payload(
                character,
                conversation_id,
                message_id,
                scene_summary,
                positive_prompt,
                negative_prompt,
                dims,
                seed,
                output_path=final_path,
                stage1_path=None,
            )

        target_width = dims["target_width"]
        target_height = dims["target_height"]
        if dims["base_width"] <= 0 or dims["base_height"] <= 0:
            raise ValueError("Base image dimensions must be positive.")
        hr_scale_w = target_width / dims["base_width"]
        hr_scale_h = target_height / dims["base_height"]
        hr_scale = round((hr_scale_w + hr_scale_h) / 2, 4)
        total_steps = cfg.steps + max(cfg.hires_steps, 1)
        self._set_status(
            "running",
            "Rendering image in A1111",
            0.2,
            stage="txt2img",
            current_step=0,
            total_steps=total_steps,
            message_id=message_id,
            image_id=image_id,
        )
        payload = {
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "steps": cfg.steps,
            "cfg_scale": cfg.guidance_scale,
            "width": dims["base_width"],
            "height": dims["base_height"],
            "seed": seed,
            "sampler_name": cfg.sampler_name,
            "scheduler": cfg.scheduler,
            "enable_hr": True,
            "hr_scale": hr_scale,
            "hr_resize_x": target_width,
            "hr_resize_y": target_height,
            "hr_upscaler": cfg.hr_upscaler,
            "hr_second_pass_steps": cfg.hires_steps,
            "denoising_strength": cfg.denoise_strength,
            "save_images": False,
            "send_images": True,
        }
        pre_render_resources = assert_safe("Before A1111 render")
        started = time.perf_counter()
        response: dict[str, Any] | None = None
        for attempt in range(2):
            watchdog = ResourceWatchdog("A1111 image render", on_trip=self._resource_guard_stop)
            try:
                log_event(
                    "a1111_txt2img_start",
                    attempt=attempt + 1,
                    message_id=message_id,
                    image_id=image_id,
                    dimensions=dims,
                    steps=cfg.steps,
                    hires_steps=cfg.hires_steps,
                    resources_before=pre_render_resources.__dict__,
                )
                poll_stop, poll_thread = self._start_progress_poller(message_id, image_id, total_steps)
                try:
                    with watchdog:
                        response = self._post_json("/sdapi/v1/txt2img", payload, timeout=3600)
                finally:
                    poll_stop.set()
                    poll_thread.join(timeout=2)
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                log_event("a1111_txt2img_http_error", attempt=attempt + 1, code=exc.code, body=body)
                raise RuntimeError(f"A1111 image request failed: HTTP {exc.code}: {body}") from exc
            except ResourceGuardError:
                log_event("a1111_txt2img_resource_guard_error", attempt=attempt + 1)
                raise
            except Exception as exc:
                if watchdog.tripped:
                    log_event("a1111_txt2img_watchdog_trip", attempt=attempt + 1, reason=watchdog.reason)
                    raise ResourceGuardError(
                        f"A1111 image render stopped by resource guard: {watchdog.reason}"
                    ) from exc
                if attempt == 0:
                    log_event("a1111_txt2img_retry", attempt=attempt + 1, error=repr(exc))
                    self._set_status("recovering", "A1111 connection dropped; restarting image backend", 0.1)
                    self.shutdown()
                    self.ensure_loaded()
                    continue
                log_event("a1111_txt2img_error", attempt=attempt + 1, error=repr(exc))
                raise RuntimeError(f"A1111 image request failed after retry: {exc}") from exc
        if response is None:
            raise RuntimeError("A1111 image request failed without a response.")
        elapsed = time.perf_counter() - started
        post_render_resources = resource_snapshot()
        log_event(
            "a1111_txt2img_complete",
            message_id=message_id,
            image_id=image_id,
            elapsed_s=round(elapsed, 3),
            resources_after=post_render_resources.__dict__,
        )
        images = response.get("images") or []
        if not images:
            raise RuntimeError("A1111 returned no images.")
        self._set_status(
            "finalizing",
            "Saving generated image",
            0.97,
            stage="saving",
            current_step=total_steps,
            total_steps=total_steps,
            message_id=message_id,
            image_id=image_id,
        )
        final_path.write_bytes(base64.b64decode(images[0]))
        settings_path.write_text(
            json.dumps(
                {
                    "elapsed_s": elapsed,
                    "payload": payload,
                    "resources_before_render": pre_render_resources.__dict__,
                    "resources_after_render": post_render_resources.__dict__,
                    "info": response.get("info", ""),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self._set_status(
            "ready",
            f"Image generated in {elapsed:.1f}s",
            1.0,
            stage="completed",
            current_step=total_steps,
            total_steps=total_steps,
            message_id=message_id,
            image_id=image_id,
        )
        return self._payload(
            character,
            conversation_id,
            message_id,
            scene_summary,
            positive_prompt,
            negative_prompt,
            dims,
            seed,
            output_path=final_path,
            stage1_path=None,
        )

    def _payload(
        self,
        character: dict[str, Any],
        conversation_id: int,
        message_id: int | None,
        scene_summary: str,
        positive_prompt: str,
        negative_prompt: str,
        dims: dict[str, int],
        seed: int,
        *,
        output_path: Path,
        stage1_path: Path | None,
    ) -> dict[str, Any]:
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
            "denoise_strength": settings.image.denoise_strength,
            "second_pass_steps": settings.image.hires_steps,
            "effective_second_pass_steps": settings.image.hires_steps,
            "seed": seed,
            "stage1_output_path": self._relative_output_path(stage1_path) if stage1_path else "",
            "output_path": self._relative_output_path(output_path),
            "status": "completed",
            "error": "",
        }


image_service = ImageGenerationService()
