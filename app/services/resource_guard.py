from __future__ import annotations

import ctypes
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..config import settings


class ResourceGuardError(RuntimeError):
    """Raised when a local generation task crosses unsafe resource limits."""


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


@dataclass(frozen=True)
class ResourceSnapshot:
    free_ram_gb: float
    total_ram_gb: float
    commit_gb: float
    commit_limit_gb: float
    commit_ratio: float
    vram_used_mib: int
    vram_free_mib: int


def _windows_memory_snapshot() -> tuple[float, float, float, float, float]:
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
        raise OSError("GlobalMemoryStatusEx failed")
    total_ram_gb = status.ullTotalPhys / 1024**3
    free_ram_gb = status.ullAvailPhys / 1024**3
    commit_limit_gb = status.ullTotalPageFile / 1024**3
    commit_free_gb = status.ullAvailPageFile / 1024**3
    commit_gb = max(commit_limit_gb - commit_free_gb, 0)
    commit_ratio = commit_gb / commit_limit_gb if commit_limit_gb else 0
    return free_ram_gb, total_ram_gb, commit_gb, commit_limit_gb, commit_ratio


def _vram_snapshot() -> tuple[int, int]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        ).strip()
        used, free = (int(part.strip()) for part in out.split(",", 1))
        return used, free
    except Exception:
        return 0, 0


def resource_snapshot() -> ResourceSnapshot:
    free_ram, total_ram, commit, commit_limit, commit_ratio = _windows_memory_snapshot()
    vram_used, vram_free = _vram_snapshot()
    return ResourceSnapshot(
        free_ram_gb=round(free_ram, 2),
        total_ram_gb=round(total_ram, 2),
        commit_gb=round(commit, 2),
        commit_limit_gb=round(commit_limit, 2),
        commit_ratio=round(commit_ratio, 3),
        vram_used_mib=vram_used,
        vram_free_mib=vram_free,
    )


def unsafe_reason(snapshot: ResourceSnapshot) -> str:
    reasons: list[str] = []
    if snapshot.free_ram_gb < settings.min_free_ram_gb:
        reasons.append(f"free RAM {snapshot.free_ram_gb}GB < {settings.min_free_ram_gb}GB")
    if snapshot.commit_ratio > settings.max_commit_ratio:
        reasons.append(f"commit ratio {snapshot.commit_ratio} > {settings.max_commit_ratio}")
    if snapshot.vram_used_mib > settings.max_vram_used_mib:
        reasons.append(f"VRAM used {snapshot.vram_used_mib}MiB > {settings.max_vram_used_mib}MiB")
    return "; ".join(reasons)


def assert_safe(label: str) -> ResourceSnapshot:
    if not settings.resource_guard_enabled:
        return resource_snapshot()
    snapshot = resource_snapshot()
    reason = unsafe_reason(snapshot)
    if reason:
        raise ResourceGuardError(f"{label} blocked by resource guard: {reason}")
    return snapshot


class ResourceWatchdog:
    def __init__(self, label: str, *, on_trip: Callable[[str], None] | None = None) -> None:
        self.label = label
        self.on_trip = on_trip
        self.tripped = False
        self.reason = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "ResourceWatchdog":
        if not settings.resource_guard_enabled:
            return self
        self._thread = threading.Thread(target=self._loop, name=f"resource-watchdog-{self.label}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self.tripped and exc_type is None:
            raise ResourceGuardError(f"{self.label} stopped by resource guard: {self.reason}")

    def _loop(self) -> None:
        while not self._stop.wait(settings.resource_guard_poll_seconds):
            try:
                snapshot = resource_snapshot()
                reason = unsafe_reason(snapshot)
            except Exception as exc:
                reason = f"resource snapshot failed: {exc}"
            if not reason:
                continue
            self.tripped = True
            self.reason = reason
            if self.on_trip is not None:
                try:
                    self.on_trip(reason)
                except Exception:
                    pass
            self._stop.set()
            return
