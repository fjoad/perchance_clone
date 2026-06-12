from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from f_only_env import F_OLLAMA_EXE, F_OLLAMA_MODELS, assert_f_only_env, configure_f_only_env


OLLAMA_BASE = "http://localhost:11434"
OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "diags"


def api_get(path: str, *, timeout: float = 10) -> dict[str, Any]:
    with urllib.request.urlopen(f"{OLLAMA_BASE}{path}", timeout=timeout) as resp:
        return json.loads(resp.read())


def ensure_ollama() -> subprocess.Popen | None:
    try:
        version = api_get("/api/version", timeout=2).get("version")
        print(f"[ollama] existing server: {version}")
        return None
    except Exception:
        pass

    if not F_OLLAMA_EXE.exists():
        raise FileNotFoundError(f"Ollama executable not found: {F_OLLAMA_EXE}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = str(F_OLLAMA_MODELS)
    env["OLLAMA_FLASH_ATTENTION"] = "1"
    env["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
    env["OLLAMA_NUM_PARALLEL"] = "1"
    env["OLLAMA_MAX_LOADED_MODELS"] = "1"
    stdout = OUT_DIR / "pull_ollama_stdout.log"
    stderr = OUT_DIR / "pull_ollama_stderr.log"
    print(f"[ollama] starting {F_OLLAMA_EXE}")
    proc = subprocess.Popen(
        [str(F_OLLAMA_EXE), "serve"],
        env=env,
        stdout=stdout.open("w", encoding="utf-8"),
        stderr=stderr.open("w", encoding="utf-8"),
    )
    for _ in range(60):
        try:
            version = api_get("/api/version", timeout=2).get("version")
            print(f"[ollama] started server: {version}")
            return proc
        except Exception:
            time.sleep(1)
    raise RuntimeError("Ollama did not become ready within 60 seconds.")


def list_models() -> set[str]:
    try:
        data = api_get("/api/tags", timeout=10)
    except Exception:
        return set()
    return {item.get("name", "") for item in data.get("models", [])}


def pull_model(model: str) -> None:
    print(f"\n[pull] {model}")
    payload = json.dumps({"model": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/pull",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60 * 60 * 4) as resp:
        last_status = ""
        for raw in resp:
            if not raw.strip():
                continue
            event = json.loads(raw)
            status = event.get("status", "")
            total = event.get("total")
            completed = event.get("completed")
            digest = event.get("digest", "")
            if total and completed:
                pct = (completed / total) * 100
                line = f"{status}: {pct:5.1f}% ({completed / 1e9:.2f}/{total / 1e9:.2f} GB)"
            elif digest:
                line = f"{status}: {digest[:18]}"
            else:
                line = status
            if line != last_status:
                print(line)
                last_status = line
            if event.get("error"):
                raise RuntimeError(event["error"])
    print(f"[pull complete] {model}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Ollama models with F:-only storage guardrails.")
    parser.add_argument("models", nargs="+", help="Model names to pull, e.g. hf.co/org/repo:Q5_K_M")
    parser.add_argument("--skip-existing", action="store_true", help="Skip models already listed by Ollama.")
    return parser.parse_args()


def main() -> int:
    configure_f_only_env()
    assert_f_only_env()
    args = parse_args()
    started = ensure_ollama()
    try:
        existing = list_models() if args.skip_existing else set()
        for model in args.models:
            if model in existing:
                print(f"[skip existing] {model}")
                continue
            pull_model(model)
        print("\n[models]")
        for name in sorted(list_models()):
            print(name)
        print(f"\n[ollama models dir] {F_OLLAMA_MODELS}")
        return 0
    finally:
        if started is not None:
            started.terminate()
            started.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
