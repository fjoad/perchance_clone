from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, TypeVar

from ..config import settings
from .image_generation import image_service
from .text_generation import text_service

T = TypeVar("T")


class RuntimeCoordinator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._text_preload_thread: threading.Thread | None = None
        self._startup_thread: threading.Thread | None = None
        self._shutting_down = False
        self._startup_ready = False
        self._startup_state = "idle"
        self._startup_detail = "Runtime has not started."
        self._startup_progress = 0.0

    def _text_loaded(self) -> bool:
        return bool(text_service.snapshot().get("loaded"))

    def _image_loaded(self) -> bool:
        return bool(image_service.snapshot().get("loaded"))

    def _set_startup_status(self, state: str, detail: str, progress: float, *, ready: bool = False) -> None:
        self._startup_state = state
        self._startup_detail = detail
        self._startup_progress = max(0.0, min(1.0, progress))
        self._startup_ready = ready

    def _set_text_error(self, message: str) -> None:
        text_service._set_status("error", message, 0.0)  # noqa: SLF001

    def _background_preload_text(self) -> None:
        try:
            if self._shutting_down:
                return
            with self._lock:
                if self._shutting_down:
                    return
                if self._image_loaded():
                    image_service.unload()
                text_service.ensure_loaded()
        except Exception as exc:  # pragma: no cover - defensive runtime path
            self._set_text_error(f"Text preload failed: {exc}")

    def _startup_warm(self) -> None:
        try:
            if self._shutting_down:
                return
            with self._lock:
                if self._shutting_down:
                    return
                if settings.preload_image_backend and not settings.use_mock_image:
                    self._set_startup_status("loading", "Warming A1111 image backend", 0.18)
                    image_service.ensure_loaded()
                    image_service.unload()
                if settings.preload_text_model and not settings.use_mock_text:
                    self._set_startup_status("loading", "Loading story text model", 0.62)
                    text_loaded = False
                    for attempt in range(1, 4):
                        text_service.ensure_loaded()
                        if text_service.is_loaded():
                            text_loaded = True
                            break
                        self._set_startup_status(
                            "loading",
                            f"Text model load failed; retrying ({attempt}/3)...",
                            0.62,
                        )
                        time.sleep(4)
                    if not text_loaded:
                        self._set_startup_status(
                            "error",
                            "Text model failed to load after 3 attempts. Click Retry Engines.",
                            0.0,
                            ready=False,
                        )
                        return
                self._set_startup_status("ready", "Local engines ready.", 1.0, ready=True)
        except Exception as exc:  # pragma: no cover - startup safety path
            self._set_startup_status("error", f"Runtime warmup failed: {exc}", 0.0, ready=False)
            self._set_text_error(f"Startup warmup failed: {exc}")

    def startup(self) -> None:
        self._shutting_down = False
        self._set_startup_status("loading", "Starting local runtime.", 0.05, ready=False)
        if settings.use_mock_text:
            text_service.ensure_loaded()
        if settings.use_mock_image:
            image_service.ensure_loaded()
        if settings.use_mock_text and settings.use_mock_image:
            self._set_startup_status("ready", "Mock runtime ready.", 1.0, ready=True)
            return
        if not settings.preload_text_model and not settings.preload_image_backend:
            self._set_startup_status("ready", "Runtime ready. Models will load on demand.", 1.0, ready=True)
            return
        thread = threading.Thread(
            target=self._startup_warm,
            name="companion-startup-warmup",
            daemon=True,
        )
        self._startup_thread = thread
        thread.start()

    def shutdown(self) -> None:
        self._shutting_down = True
        startup_thread = self._startup_thread
        if startup_thread is not None and startup_thread.is_alive() and startup_thread is not threading.current_thread():
            startup_thread.join(timeout=5)
        thread = self._text_preload_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._lock:
            image_service.shutdown()
            text_service.shutdown()

    def preload_text_async(self) -> None:
        if self._shutting_down:
            return
        if settings.use_mock_text:
            text_service.ensure_loaded()
            return
        thread = self._text_preload_thread
        if thread is not None and thread.is_alive():
            return
        text_service._set_status("queued", "Queued to reload text model", 0.05)  # noqa: SLF001
        thread = threading.Thread(
            target=self._background_preload_text,
            name="companion-text-preload",
            daemon=True,
        )
        self._text_preload_thread = thread
        thread.start()

    def retry_warmup(self) -> None:
        """Re-run the startup warmup after a failed engine load (user-triggered)."""
        thread = self._startup_thread
        if thread is not None and thread.is_alive():
            return
        self._shutting_down = False
        self._set_startup_status("loading", "Retrying engine warmup.", 0.1, ready=False)
        thread = threading.Thread(
            target=self._startup_warm,
            name="companion-warmup-retry",
            daemon=True,
        )
        self._startup_thread = thread
        thread.start()

    @contextmanager
    def text_stream_session(self):
        """Hold GPU ownership for a streaming text generation.

        Must be entered and exited on the SAME thread (uses an RLock); run the
        whole streaming loop inside a dedicated worker thread, not across
        threadpool hops.
        """
        with self._lock:
            self.ensure_text_ready()
            yield

    def ensure_text_ready(self) -> None:
        with self._lock:
            if self._image_loaded():
                image_service.unload()
            text_service.ensure_loaded()

    def ensure_image_ready(self) -> None:
        with self._lock:
            text_service.unload_for_image()
            image_service.ensure_loaded()

    def run_text_task(self, func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        with self._lock:
            self.ensure_text_ready()
            return func(*args, **kwargs)

    def run_image_task(self, func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        try:
            with self._lock:
                self.ensure_image_ready()
                return func(*args, **kwargs)
        finally:
            with self._lock:
                if self._image_loaded():
                    image_service.unload()
            if not self._shutting_down and settings.preload_text_model:
                self.preload_text_async()

    def snapshot(self) -> dict[str, Any]:
        text = text_service.snapshot()
        image = image_service.snapshot()
        text_required = bool(settings.preload_text_model and not settings.use_mock_text)
        image_required = bool(settings.preload_image_backend and not settings.use_mock_image)
        text_ready = bool(text.get("loaded")) or not text_required or bool(text.get("mock"))
        image_ready = bool(image.get("loaded")) or not image_required or bool(image.get("mock"))
        # Sticky gate: once startup warmup succeeds, the composer stays usable.
        # Steady-state model swaps (e.g. text unloaded during an image render)
        # must NOT re-lock the UI; requests simply queue on the runtime lock.
        ready = bool(self._startup_ready)
        return {
            "state": self._startup_state,
            "detail": self._startup_detail,
            "progress": self._startup_progress,
            "ready": ready,
            "text_required": text_required,
            "image_required": image_required,
            "text_ready": text_ready,
            "image_ready": image_ready,
            "preload_text_model": settings.preload_text_model,
            "preload_image_backend": settings.preload_image_backend,
        }


runtime_coordinator = RuntimeCoordinator()
