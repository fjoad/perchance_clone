from __future__ import annotations

import threading
from typing import Any, Callable, TypeVar

from ..config import settings
from .image_generation import image_service
from .text_generation import text_service

T = TypeVar("T")


class RuntimeCoordinator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._text_preload_thread: threading.Thread | None = None

    def _text_loaded(self) -> bool:
        return bool(text_service.snapshot().get("loaded"))

    def _image_loaded(self) -> bool:
        return bool(image_service.snapshot().get("loaded"))

    def _set_text_error(self, message: str) -> None:
        text_service._set_status("error", message, 0.0)  # noqa: SLF001

    def _background_preload_text(self) -> None:
        try:
            with self._lock:
                if self._image_loaded():
                    image_service.unload()
                text_service.ensure_loaded()
        except Exception as exc:  # pragma: no cover - defensive runtime path
            self._set_text_error(f"Text preload failed: {exc}")

    def startup(self) -> None:
        if settings.use_mock_text:
            text_service.ensure_loaded()
            return
        self.preload_text_async()

    def shutdown(self) -> None:
        with self._lock:
            image_service.unload()
            text_service.unload()

    def preload_text_async(self) -> None:
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

    def ensure_text_ready(self) -> None:
        with self._lock:
            if self._image_loaded():
                image_service.unload()
            text_service.ensure_loaded()

    def ensure_image_ready(self) -> None:
        with self._lock:
            if self._text_loaded():
                text_service.unload()
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
            self.preload_text_async()


runtime_coordinator = RuntimeCoordinator()
