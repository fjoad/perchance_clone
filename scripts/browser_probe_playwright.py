"""Run an actual browser UI probe with Playwright.

Default is safe/mock mode and uses the installed Microsoft Edge executable, so
it does not download Playwright browser binaries.

Safe UI probe:
    python scripts/browser_probe_playwright.py

Heavy real-model UI probe:
    python scripts/browser_probe_playwright.py --real --timeout 1200
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import ensure_runtime_dirs, settings  # noqa: E402
from app.db import (  # noqa: E402
    connect,
    ensure_conversation,
    list_images_for_message,
    list_messages,
    replace_pinned_memory,
    save_character,
    save_user_profile,
)

APP_URL = "http://127.0.0.1:8000"
PYTHON_EXE = Path(r"F:\anaconda3\envs\companion_v1\python.exe")
EDGE_EXE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
CHROME_EXE = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
SLUG = "codex-browser-probe"


def cleanup_db() -> None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM characters WHERE slug = ?", (SLUG,)).fetchone()
        if not row:
            return
        character_id = int(row["id"])
        conn.execute("DELETE FROM image_requests WHERE character_id = ?", (character_id,))
        conn.execute("DELETE FROM story_frames WHERE character_id = ?", (character_id,))
        conn.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE character_id = ?)",
            (character_id,),
        )
        conn.execute("DELETE FROM conversations WHERE character_id = ?", (character_id,))
        conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))


def create_probe_character() -> int:
    character_id = save_character(
        {
            "slug": SLUG,
            "display_name": "Browser Probe Echidna",
            "source_media": "Re:Zero",
            "character_dossier": (
                "Browser Probe Echidna is Echidna from Re:Zero for browser UI testing: pale skin, long white hair, "
                "black eyes, thick white eyelashes, a green butterfly hair clip, and a calm, observant tone."
            ),
            "appearance": (
                "Echidna from Re:Zero, long straight white hair, black eyes, thick white eyelashes, "
                "green butterfly hair clip, porcelain skin, elegant black-and-white dress."
            ),
            "image_anchor_summary": (
                "Echidna from Re:Zero: porcelain skin, long white hair, black eyes, white eyelashes, "
                "green butterfly hair clip, elegant black-and-white dress."
            ),
            "image_prompt_positive_additions": (
                "painterly anime artwork, masterpiece, best quality, fine details, polished composition"
            ),
            "image_prompt_negative_additions": (
                "lowres, blurry, bad anatomy, bad hands, extra fingers, extra limbs, text, watermark"
            ),
            "default_visual_style": "painterly anime artwork, warm candlelit tea room",
            "special_instructions": (
                "Write immersive visual-novel prose. Narrate actions in third person and dialogue in first person."
            ),
            "example_dialogue": (
                '{{user}}: "Stay with me for a minute."\n'
                "{{char}}: Echidna's eyes soften by the smallest degree as she settles beside him.\n"
                '"Then I will observe you carefully," she says. "That is my nature, after all."'
            ),
            "is_active": True,
        }
    )
    replace_pinned_memory(
        character_id,
        "Anon is tired and trying to sound casual. Echidna is seated with him in a candlelit tea room.",
    )
    save_user_profile("Anon", "A tired young man who masks stress with dry humor.")
    ensure_conversation(character_id)
    return int(character_id)


def request_text(url: str, *, timeout: float = 10) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def wait_for_server(timeout_s: float = 90) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            request_text(f"{APP_URL}/", timeout=8)
            return True
        except Exception:
            time.sleep(1)
    return False


def stop_process_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except Exception:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def wait_for_image_row(message_id: int, timeout_s: float) -> list[dict[str, Any]]:
    deadline = time.time() + timeout_s
    rows: list[dict[str, Any]] = []
    while time.time() < deadline:
        rows = list_images_for_message(message_id)
        if rows:
            return rows
        time.sleep(1)
    return rows


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copy2(src, dst)


def browser_exe() -> Path:
    if EDGE_EXE.exists():
        return EDGE_EXE
    if CHROME_EXE.exists():
        return CHROME_EXE
    raise FileNotFoundError("No installed Edge/Chrome executable found.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Playwright browser probe against the local app.")
    parser.add_argument("--real", action="store_true", help="Use real Ollama/A1111 instead of mock services.")
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument("--timeout", type=float, default=180, help="Seconds to wait for image completion.")
    parser.add_argument("--resolution-preset", default="512x512:1024x1024")
    parser.add_argument("--message", default="Come sit beside me for a moment. I need a quiet answer.")
    args = parser.parse_args()

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print("Playwright is not installed in this Python environment.")
        print(f"Import error: {exc!r}")
        return 2

    ensure_runtime_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT_DIR / "outputs" / "diags" / f"browser_probe_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    uvicorn_log = (run_dir / "uvicorn.log").open("wb")
    print(f"[run_dir] {run_dir}")

    cleanup_db()
    character_id = create_probe_character()
    conversation = ensure_conversation(character_id)

    env = os.environ.copy()
    env["COMPANION_USE_MOCK_TEXT"] = "0" if args.real else "1"
    env["COMPANION_USE_MOCK_IMAGE"] = "0" if args.real else "1"
    env["COMPANION_PRELOAD_TEXT_MODEL"] = "0"
    env["COMPANION_RESOURCE_GUARD"] = "1"
    env["HF_HOME"] = str(settings.hf_home)
    env["HF_HUB_CACHE"] = str(settings.hf_hub_cache)
    env["HUGGINGFACE_HUB_CACHE"] = str(settings.hf_hub_cache)
    env["PLAYWRIGHT_BROWSERS_PATH"] = r"F:\playwright\browsers"
    env["OLLAMA_MODELS"] = str(settings.ollama_models_dir)
    env["TMP"] = str(settings.temp_dir)
    env["TEMP"] = str(settings.temp_dir)
    env["TMPDIR"] = str(settings.temp_dir)
    env["SQLITE_TMPDIR"] = str(settings.temp_dir)

    proc = subprocess.Popen(
        [
            str(PYTHON_EXE),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=str(ROOT_DIR),
        env=env,
        stdout=uvicorn_log,
        stderr=subprocess.STDOUT,
    )

    console_events: list[dict[str, str]] = []
    page_errors: list[str] = []
    request_failures: list[dict[str, str]] = []
    result: dict[str, Any] = {
        "mode": "real" if args.real else "mock",
        "run_dir": str(run_dir),
        "character_id": character_id,
        "conversation_id": conversation["id"],
        "resolution_preset": args.resolution_preset,
        "browser_executable": str(browser_exe()),
    }
    exit_code = 1
    try:
        if not wait_for_server(timeout_s=90):
            result["error"] = "server did not become ready"
            return 1

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(browser_exe()),
                headless=not args.headed,
                args=["--disable-gpu"] if not args.headed else [],
            )
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.on("console", lambda msg: console_events.append({"type": msg.type, "text": msg.text}))
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on(
                "requestfailed",
                lambda req: request_failures.append(
                    {
                        "url": req.url,
                        "method": req.method,
                        "failure": req.failure or "",
                    }
                ),
            )

            page.goto(f"{APP_URL}/?character_id={character_id}", wait_until="domcontentloaded", timeout=60000)
            page.screenshot(path=str(run_dir / "01_loaded.png"), full_page=True)
            page.locator("textarea#message").fill(args.message)
            page.locator("input[name='auto_image']").check()
            radio = page.locator(f"input[name='resolution_preset'][value='{args.resolution_preset}']")
            if radio.count():
                radio.check(force=True)
            page.screenshot(path=str(run_dir / "02_before_submit.png"), full_page=True)

            submitted_at = time.perf_counter()
            page.locator("form[data-action='chat'] button[type='submit']").click()
            page.wait_for_selector(".story-block.assistant", timeout=int(args.timeout * 1000))
            text_elapsed = time.perf_counter() - submitted_at
            page.screenshot(path=str(run_dir / "03_text_returned.png"), full_page=True)

            messages = list_messages(conversation["id"])
            assistant = next((dict(row) for row in reversed(messages) if row["role"] == "assistant"), None)
            image_rows = wait_for_image_row(int(assistant["id"]), args.timeout) if assistant else []
            image_elapsed = time.perf_counter() - submitted_at

            image_visible = False
            if image_rows:
                try:
                    page.wait_for_selector("#timeline img", timeout=30000)
                    image_visible = True
                except PlaywrightTimeoutError:
                    image_visible = False
            page.screenshot(path=str(run_dir / "04_after_image_wait.png"), full_page=True)
            (run_dir / "page.html").write_text(page.content(), encoding="utf-8")
            browser.close()

        output_path = None
        settings_path = None
        if image_rows:
            row = dict(image_rows[-1])
            output_path = settings.outputs_dir / str(row.get("output_path", ""))
            settings_path = output_path.with_name(output_path.stem.replace("_final", "") + "_a1111_settings.json")
            result["image_row"] = row
            result["output_path"] = str(output_path)
            result["settings_path"] = str(settings_path)
            result["output_exists"] = output_path.exists()
            (run_dir / "positive_prompt.txt").write_text(str(row.get("positive_prompt", "")), encoding="utf-8")
            (run_dir / "negative_prompt.txt").write_text(str(row.get("negative_prompt", "")), encoding="utf-8")
            copy_if_exists(output_path, run_dir / "image.png")
            copy_if_exists(settings_path, run_dir / "a1111_settings.json")

        result.update(
            {
                "text_visible_elapsed_s": round(text_elapsed, 3),
                "image_ready_elapsed_s": round(image_elapsed, 3),
                "message_count": len(list_messages(conversation["id"])),
                "assistant_id": assistant["id"] if assistant else None,
                "image_rows": len(image_rows),
                "image_visible_in_browser": image_visible,
                "console_events": console_events,
                "page_errors": page_errors,
                "request_failures": request_failures,
            }
        )
        if assistant:
            (run_dir / "assistant.txt").write_text(str(assistant["content"]), encoding="utf-8")
        (run_dir / "messages.json").write_text(
            json.dumps([dict(row) for row in list_messages(conversation["id"])], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "user.txt").write_text(args.message, encoding="utf-8")
        exit_code = 0 if assistant and image_rows and image_visible and not page_errors else 1
        return exit_code
    finally:
        result["exit_code"] = exit_code
        (run_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        stop_process_tree(proc)
        uvicorn_log.close()
        cleanup_db()


if __name__ == "__main__":
    raise SystemExit(main())
