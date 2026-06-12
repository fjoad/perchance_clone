"""Replay existing app conversations through the real browser UI.

This is the heavier end-to-end regression harness:
- starts the FastAPI app
- opens Edge through Playwright
- creates fresh conversations for several existing characters
- copies user prompts from the older conversations
- submits through the real composer with auto-image enabled
- records text timing, image timing, screenshots, prompts, outputs, and resources

Default mode is mock/safe. Use --real for actual Ollama + A1111.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import ensure_runtime_dirs, settings  # noqa: E402
from app.db import (  # noqa: E402
    connect,
    create_conversation,
    get_character_by_slug,
    get_conversation,
    get_story_frame_by_assistant_message,
    list_images_for_message,
    list_messages,
)

APP_HOST = "127.0.0.1"
APP_PORT = 8765
APP_URL = f"http://{APP_HOST}:{APP_PORT}"
PYTHON_EXE = Path(r"F:\anaconda3\envs\companion_v1\python.exe")
EDGE_EXE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
CHROME_EXE = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
TEST_TITLE_PREFIX = "Browser Replay"

DEFAULT_SLUGS = ["sample-companion", "atago", "ahri", "echidna", "mirajane"]
FALLBACK_PROMPTS = {
    "sample-companion": ["hello?", "do you know me?"],
    "atago": ["hello?", "do you know who i am?"],
    "ahri": ["hello?", "Come sit beside me for a minute."],
    "echidna": ["The girl I keep chasing... She doesn't want me"],
    "mirajane": ["hello?", "what if i want you?"],
}


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


def memory_snapshot() -> dict[str, float]:
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    total_ram_gb = status.ullTotalPhys / (1024**3)
    free_ram_gb = status.ullAvailPhys / (1024**3)
    total_commit_gb = status.ullTotalPageFile / (1024**3)
    free_commit_gb = status.ullAvailPageFile / (1024**3)
    commit_ratio = 1.0 - (free_commit_gb / total_commit_gb) if total_commit_gb else 0.0
    return {
        "ram_total_gb": round(total_ram_gb, 3),
        "ram_free_gb": round(free_ram_gb, 3),
        "commit_total_gb": round(total_commit_gb, 3),
        "commit_free_gb": round(free_commit_gb, 3),
        "commit_used_ratio": round(commit_ratio, 4),
    }


def gpu_snapshot() -> dict[str, int | str]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            text=True,
            timeout=10,
        ).strip()
        used, free = [int(part.strip()) for part in out.split(",")[:2]]
        return {"vram_used_mib": used, "vram_free_mib": free}
    except Exception as exc:
        return {"vram_error": repr(exc)}


def resource_snapshot() -> dict[str, Any]:
    data = memory_snapshot()
    data.update(gpu_snapshot())
    return data


@dataclass
class ResourceMonitor:
    out_dir: Path
    min_free_ram_gb: float = 5.0
    max_commit_ratio: float = 0.97
    max_vram_used_mib: int = 12200
    interval_s: float = 2.0
    samples: list[dict[str, Any]] = field(default_factory=list)
    tripped_reason: str | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="resource-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        (self.out_dir / "resource_samples.json").write_text(
            json.dumps(self.samples, indent=2), encoding="utf-8"
        )

    def assert_safe(self) -> None:
        if self.tripped_reason:
            raise RuntimeError(self.tripped_reason)

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = {"elapsed_s": round(time.perf_counter(), 3), **resource_snapshot()}
            self.samples.append(sample)
            reason = self._trip_reason(sample)
            if reason and not self.tripped_reason:
                self.tripped_reason = reason
                self._emergency_cleanup(reason)
            time.sleep(self.interval_s)

    def _trip_reason(self, sample: dict[str, Any]) -> str | None:
        free_ram = float(sample.get("ram_free_gb", 999))
        commit_ratio = float(sample.get("commit_used_ratio", 0))
        vram_used = int(sample.get("vram_used_mib", 0) or 0)
        if free_ram < self.min_free_ram_gb:
            return f"free system RAM dropped below {self.min_free_ram_gb} GB: {free_ram:.2f} GB"
        if commit_ratio > self.max_commit_ratio:
            return f"commit ratio exceeded {self.max_commit_ratio}: {commit_ratio:.3f}"
        if vram_used > self.max_vram_used_mib:
            return f"VRAM usage exceeded {self.max_vram_used_mib} MiB: {vram_used} MiB"
        return None

    def _emergency_cleanup(self, reason: str) -> None:
        (self.out_dir / "RESOURCE_GUARD_TRIPPED.txt").write_text(reason, encoding="utf-8")
        cleanup = ROOT_DIR / "scripts" / "stop_companion_backends.ps1"
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(cleanup)],
            cwd=str(ROOT_DIR),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )


def browser_exe() -> Path:
    if EDGE_EXE.exists():
        return EDGE_EXE
    if CHROME_EXE.exists():
        return CHROME_EXE
    raise FileNotFoundError("No installed Edge/Chrome executable found.")


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
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )


def safe_name(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", ".", ":"}:
            chars.append("_" if char == ":" else char)
        else:
            chars.append("_")
    text = "".join(chars).strip("_")
    while "__" in text:
        text = text.replace("__", "_")
    return text or "artifact"


def latest_source_prompts(slug: str, limit: int) -> tuple[int | None, list[str]]:
    character = get_character_by_slug(slug)
    if not character:
        return None, FALLBACK_PROMPTS.get(slug, ["hello?"])[:limit]
    with connect() as conn:
        conversations = conn.execute(
            """
            SELECT id, title FROM conversations
            WHERE character_id = ?
              AND title NOT LIKE ?
            ORDER BY updated_at DESC
            """,
            (int(character["id"]), f"{TEST_TITLE_PREFIX}%"),
        ).fetchall()
    for row in conversations:
        messages = [m["content"] for m in list_messages(int(row["id"])) if m["role"] == "user"]
        if messages:
            return int(row["id"]), messages[:limit]
    return None, FALLBACK_PROMPTS.get(slug, ["hello?"])[:limit]


def start_app(run_dir: Path, *, real: bool, port: int) -> tuple[subprocess.Popen[bytes], Any]:
    uvicorn_log = (run_dir / "uvicorn.log").open("wb")
    env = os.environ.copy()
    env["COMPANION_USE_MOCK_TEXT"] = "0" if real else "1"
    env["COMPANION_USE_MOCK_IMAGE"] = "0" if real else "1"
    env["COMPANION_PRELOAD_TEXT_MODEL"] = "1" if real else "0"
    env["COMPANION_PRELOAD_IMAGE_BACKEND"] = "1" if real else "0"
    env["COMPANION_RESOURCE_GUARD"] = "1"
    env["COMPANION_STOP_OLLAMA_BEFORE_IMAGE"] = "1"
    env["HF_HOME"] = str(settings.hf_home)
    env["HF_HUB_CACHE"] = str(settings.hf_hub_cache)
    env["HUGGINGFACE_HUB_CACHE"] = str(settings.hf_hub_cache)
    env["PLAYWRIGHT_BROWSERS_PATH"] = r"F:\playwright\browsers"
    env["OLLAMA_MODELS"] = str(settings.ollama_models_dir)
    env["TMP"] = str(settings.temp_dir)
    env["TEMP"] = str(settings.temp_dir)
    env["TMPDIR"] = str(settings.temp_dir)
    env["SQLITE_TMPDIR"] = str(settings.temp_dir)
    env["LOCALAPPDATA"] = str(settings.runtime_dir / "localappdata")
    proc = subprocess.Popen(
        [
            str(PYTHON_EXE),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            APP_HOST,
            "--port",
            str(port),
        ],
        cwd=str(ROOT_DIR),
        env=env,
        stdout=uvicorn_log,
        stderr=subprocess.STDOUT,
    )
    return proc, uvicorn_log


def wait_for_assistant_count(page: Any, expected: int, timeout_s: float) -> None:
    page.wait_for_function(
        "(expected) => document.querySelectorAll('.story-block.assistant').length >= expected",
        arg=expected,
        timeout=int(timeout_s * 1000),
    )


def wait_for_image_count(page: Any, expected: int, timeout_s: float) -> None:
    page.wait_for_function(
        "(expected) => document.querySelectorAll('#timeline .scene-visual img').length >= expected",
        arg=expected,
        timeout=int(timeout_s * 1000),
    )


def wait_for_runtime_ready(page: Any, timeout_s: float) -> None:
    page.wait_for_function(
        "() => document.body.dataset.runtimeReady === '1'",
        timeout=int(timeout_s * 1000),
    )


def copy_image_artifacts(row: dict[str, Any], turn_dir: Path, artifact_prefix: str) -> dict[str, Any]:
    output_rel = str(row.get("output_path", "") or "")
    output_path = settings.outputs_dir / output_rel
    settings_path = output_path.with_name(output_path.stem.replace("_final", "") + "_a1111_settings.json")
    copied: dict[str, Any] = {
        "output_path": str(output_path),
        "settings_path": str(settings_path),
        "output_exists": output_path.exists(),
        "settings_exists": settings_path.exists(),
    }
    if output_path.exists():
        dst = turn_dir / f"{artifact_prefix}_image.png"
        shutil.copy2(output_path, dst)
        copied["copied_image"] = str(dst)
    if settings_path.exists():
        dst = turn_dir / f"{artifact_prefix}_image_settings.json"
        shutil.copy2(settings_path, dst)
        copied["copied_settings"] = str(dst)
    return copied


def run_browser_turn(
    *,
    page: Any,
    character_id: int,
    conversation_id: int,
    prompt: str,
    turn_dir: Path,
    artifact_prefix: str,
    resolution_preset: str,
    timeout_s: float,
    expected_assistant_count: int,
    expected_image_count: int,
    monitor: ResourceMonitor,
) -> dict[str, Any]:
    monitor.assert_safe()
    page.goto(f"{APP_URL}/?character_id={character_id}", wait_until="domcontentloaded", timeout=60000)
    wait_for_runtime_ready(page, timeout_s)
    page.locator("textarea#message").fill(prompt)
    auto = page.locator("input[name='auto_image']")
    if auto.count() and not auto.is_checked():
        auto.check(force=True)
    radio = page.locator(f"input[name='resolution_preset'][value='{resolution_preset}']")
    if radio.count():
        radio.check(force=True)
    page.screenshot(path=str(turn_dir / f"{artifact_prefix}_before_submit.png"), full_page=True)

    start = time.perf_counter()
    page.locator("form[data-action='chat'] button[type='submit']").click()
    wait_for_assistant_count(page, expected_assistant_count, timeout_s)
    text_elapsed = time.perf_counter() - start
    page.screenshot(path=str(turn_dir / f"{artifact_prefix}_text_visible.png"), full_page=True)

    image_visible = False
    image_error = None
    try:
        wait_for_image_count(page, expected_image_count, timeout_s)
        image_visible = True
    except Exception as exc:
        image_error = repr(exc)
    image_elapsed = time.perf_counter() - start
    page.screenshot(path=str(turn_dir / f"{artifact_prefix}_after_image_wait.png"), full_page=True)
    (turn_dir / "page.html").write_text(page.content(), encoding="utf-8")

    messages = list_messages(conversation_id)
    assistant_messages = [dict(row) for row in messages if row["role"] == "assistant"]
    assistant = assistant_messages[-1] if assistant_messages else None
    story_frame = get_story_frame_by_assistant_message(int(assistant["id"])) if assistant else None
    image_rows = list_images_for_message(int(assistant["id"])) if assistant else []

    result: dict[str, Any] = {
        "prompt": prompt,
        "text_visible_elapsed_s": round(text_elapsed, 3),
        "image_visible_elapsed_s": round(image_elapsed, 3),
        "image_visible_in_browser": image_visible,
        "image_error": image_error,
        "assistant_id": assistant["id"] if assistant else None,
        "assistant_text": assistant["content"] if assistant else "",
        "story_frame": dict(story_frame) if story_frame else None,
        "image_rows": [dict(row) for row in image_rows],
        "resource_after_turn": resource_snapshot(),
    }
    (turn_dir / "user.txt").write_text(prompt, encoding="utf-8")
    if assistant:
        (turn_dir / "assistant.txt").write_text(str(assistant["content"]), encoding="utf-8")
    if image_rows:
        image_row = dict(image_rows[-1])
        result["image_artifacts"] = copy_image_artifacts(image_row, turn_dir, artifact_prefix)
        (turn_dir / "positive_prompt.txt").write_text(str(image_row.get("positive_prompt", "")), encoding="utf-8")
        (turn_dir / "negative_prompt.txt").write_text(str(image_row.get("negative_prompt", "")), encoding="utf-8")
    (turn_dir / "turn_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    monitor.assert_safe()
    return result


def write_experiment_markdown(run_dir: Path, result: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Browser Prompt Replay")
    lines.append("")
    lines.append(f"- Mode: {result['mode']}")
    lines.append(f"- Resolution preset: {result['resolution_preset']}")
    lines.append(f"- Slugs: {', '.join(result['slugs'])}")
    lines.append(f"- Turns per conversation: {result['turns_per_conversation']}")
    lines.append(f"- Warmup: {result['warmup_enabled']}")
    lines.append(f"- Started: {result['started_at']}")
    lines.append(f"- Finished: {result.get('finished_at', '')}")
    lines.append(f"- Exit code: {result.get('exit_code')}")
    lines.append("")
    if result.get("resource_guard_tripped"):
        lines.append(f"Resource guard tripped: {result['resource_guard_tripped']}")
        lines.append("")
    if result.get("warmup"):
        lines.append("## Warmup")
        warm = result["warmup"]
        lines.append(f"- Character: {warm.get('slug')}")
        lines.append(f"- Text visible: {warm.get('text_visible_elapsed_s')}s")
        lines.append(f"- Image visible: {warm.get('image_visible_elapsed_s')}s")
        lines.append("")
    lines.append("## Conversations")
    for conversation in result.get("conversations", []):
        lines.append("")
        lines.append(f"### {conversation['slug']} / {conversation['display_name']}")
        lines.append(f"- Source conversation: {conversation.get('source_conversation_id')}")
        lines.append(f"- New conversation: {conversation.get('conversation_id')}")
        for turn in conversation.get("turns", []):
            lines.append("")
            lines.append(f"#### Turn {turn['turn_index']}")
            lines.append(f"- Text visible: {turn.get('text_visible_elapsed_s')}s")
            lines.append(f"- Image visible: {turn.get('image_visible_elapsed_s')}s")
            lines.append(f"- Image visible in browser: {turn.get('image_visible_in_browser')}")
            frame = turn.get("story_frame") or {}
            metadata: dict[str, Any] = {}
            try:
                metadata = json.loads(str(frame.get("metadata_json") or "{}"))
            except json.JSONDecodeError:
                metadata = {}
            if metadata.get("image_prompt_strategy"):
                lines.append(f"- Image prompt strategy: {metadata['image_prompt_strategy']}")
            lines.append("")
            lines.append("User prompt:")
            lines.append("")
            lines.append("```text")
            lines.append(str(turn.get("prompt", "")))
            lines.append("```")
            lines.append("")
            lines.append("Assistant output:")
            lines.append("")
            lines.append("```text")
            lines.append(str(turn.get("assistant_text", "")))
            lines.append("```")
            rows = turn.get("image_rows") or []
            if rows:
                image_row = rows[-1]
                lines.append("")
                lines.append("Image positive prompt:")
                lines.append("")
                lines.append("```text")
                lines.append(str(image_row.get("positive_prompt", "")))
                lines.append("```")
                lines.append("")
                lines.append("Image negative prompt:")
                lines.append("")
                lines.append("```text")
                lines.append(str(image_row.get("negative_prompt", "")))
                lines.append("```")
    (run_dir / "EXPERIMENT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay existing conversations through the browser UI.")
    parser.add_argument("--real", action="store_true", help="Use real Ollama/A1111.")
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument("--timeout", type=float, default=600, help="Seconds per turn image timeout.")
    parser.add_argument("--port", type=int, default=APP_PORT, help="Local test server port.")
    parser.add_argument("--resolution-preset", default="512x512:1024x1024")
    parser.add_argument("--slugs", default=",".join(DEFAULT_SLUGS))
    parser.add_argument("--turns-per-conversation", type=int, default=1)
    parser.add_argument("--no-warmup", action="store_true", help="Skip the excluded warmup turn.")
    args = parser.parse_args()
    global APP_URL
    APP_URL = f"http://{APP_HOST}:{args.port}"

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print("Playwright is not installed in this Python environment.")
        print(f"Import error: {exc!r}")
        return 2

    ensure_runtime_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"browser_prompt_replay_{stamp}"
    run_dir = ROOT_DIR / "outputs" / "diags" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run_dir] {run_dir}")

    result: dict[str, Any] = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "mode": "real" if args.real else "mock",
        "started_at": datetime.now().isoformat(),
        "resolution_preset": args.resolution_preset,
        "slugs": [slug.strip() for slug in args.slugs.split(",") if slug.strip()],
        "turns_per_conversation": args.turns_per_conversation,
        "warmup_enabled": not args.no_warmup,
        "browser_executable": str(browser_exe()),
        "initial_resources": resource_snapshot(),
        "conversations": [],
    }

    monitor = ResourceMonitor(out_dir=run_dir)
    monitor.start()
    proc: subprocess.Popen[bytes] | None = None
    uvicorn_log = None
    console_events: list[dict[str, str]] = []
    page_errors: list[str] = []
    request_failures: list[dict[str, str]] = []
    exit_code = 1
    try:
        proc, uvicorn_log = start_app(run_dir, real=args.real, port=args.port)
        if not wait_for_server(timeout_s=120):
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
                    {"url": req.url, "method": req.method, "failure": req.failure or ""}
                ),
            )

            if not args.no_warmup and result["slugs"]:
                warm_slug = result["slugs"][0]
                character = get_character_by_slug(warm_slug)
                if character:
                    warm_conversation = create_conversation(
                        int(character["id"]), title=f"{TEST_TITLE_PREFIX} {stamp} warmup"
                    )
                    warm_dir = run_dir / "warmup"
                    warm_dir.mkdir(parents=True, exist_ok=True)
                    warm_prompt = "Quick warmup: answer in character in one short paragraph."
                    warm = run_browser_turn(
                        page=page,
                        character_id=int(character["id"]),
                        conversation_id=int(warm_conversation["id"]),
                        prompt=warm_prompt,
                        turn_dir=warm_dir,
                        artifact_prefix=f"{run_id}_warmup",
                        resolution_preset=args.resolution_preset,
                        timeout_s=args.timeout,
                        expected_assistant_count=1,
                        expected_image_count=1,
                        monitor=monitor,
                    )
                    warm["slug"] = warm_slug
                    result["warmup"] = warm

            for slug in result["slugs"]:
                monitor.assert_safe()
                character = get_character_by_slug(slug)
                if not character:
                    result["conversations"].append({"slug": slug, "error": "character not found"})
                    continue
                source_conversation_id, prompts = latest_source_prompts(slug, args.turns_per_conversation)
                conversation = create_conversation(
                    int(character["id"]), title=f"{TEST_TITLE_PREFIX} {stamp} {slug}"
                )
                conversation_dir = run_dir / safe_name(slug)
                conversation_dir.mkdir(parents=True, exist_ok=True)
                conversation_result: dict[str, Any] = {
                    "slug": slug,
                    "display_name": character["display_name"],
                    "character_id": int(character["id"]),
                    "source_conversation_id": source_conversation_id,
                    "conversation_id": int(conversation["id"]),
                    "turns": [],
                }
                expected_assistant_count = 0
                expected_image_count = 0
                for turn_index, prompt in enumerate(prompts, start=1):
                    turn_dir = conversation_dir / f"turn{turn_index:03d}"
                    turn_dir.mkdir(parents=True, exist_ok=True)
                    expected_assistant_count += 1
                    expected_image_count += 1
                    turn = run_browser_turn(
                        page=page,
                        character_id=int(character["id"]),
                        conversation_id=int(conversation["id"]),
                        prompt=prompt,
                        turn_dir=turn_dir,
                        artifact_prefix=f"{run_id}_{safe_name(slug)}_turn{turn_index:03d}",
                        resolution_preset=args.resolution_preset,
                        timeout_s=args.timeout,
                        expected_assistant_count=expected_assistant_count,
                        expected_image_count=expected_image_count,
                        monitor=monitor,
                    )
                    turn["turn_index"] = turn_index
                    conversation_result["turns"].append(turn)
                    print(
                        f"[{slug} turn {turn_index}] text={turn['text_visible_elapsed_s']}s "
                        f"image={turn['image_visible_elapsed_s']}s visible={turn['image_visible_in_browser']}"
                    )
                conversation_result["final_conversation"] = get_conversation(int(conversation["id"]))
                conversation_result["messages"] = list_messages(int(conversation["id"]))
                (conversation_dir / "conversation_result.json").write_text(
                    json.dumps(conversation_result, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                result["conversations"].append(conversation_result)

            browser.close()

        exit_code = 0
        if page_errors or monitor.tripped_reason:
            exit_code = 1
        return exit_code
    except Exception as exc:
        result["error"] = repr(exc)
        print(f"[error] {exc!r}")
        return 1
    finally:
        result["exit_code"] = exit_code
        result["finished_at"] = datetime.now().isoformat()
        result["final_resources"] = resource_snapshot()
        result["resource_guard_tripped"] = monitor.tripped_reason
        result["console_events"] = console_events
        result["page_errors"] = page_errors
        result["request_failures"] = request_failures
        (run_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        write_experiment_markdown(run_dir, result)
        monitor.stop()
        if proc is not None:
            stop_process_tree(proc)
        if uvicorn_log is not None:
            uvicorn_log.close()
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
