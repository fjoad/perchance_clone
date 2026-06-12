from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import ensure_runtime_dirs, settings  # noqa: E402


def run_command(command: list[str], *, timeout: int = 10) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return output.strip() or f"<no output, returncode={completed.returncode}>"
    except Exception as exc:
        return f"<command failed: {exc!r}>"


def fetch_status() -> str:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/status", timeout=5) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return f"<app status unavailable: {exc}>"
    except Exception as exc:
        return f"<app status unavailable: {exc!r}>"


def query_db(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not settings.db_path.exists():
        return [{"error": f"DB not found: {settings.db_path}"}]
    try:
        with sqlite3.connect(settings.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params).fetchall()]
    except Exception as exc:
        return [{"error": repr(exc), "query": query}]


def tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return f"<missing: {path}>"
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(data[-lines:])
    except Exception as exc:
        return f"<could not read {path}: {exc!r}>"


def section(title: str, body: str) -> str:
    return f"\n{'=' * 80}\n{title}\n{'=' * 80}\n{body}\n"


def json_section(title: str, payload: Any) -> str:
    return section(title, json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def main() -> int:
    ensure_runtime_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = settings.runtime_dir / "logs" / f"debug_dump_{stamp}.txt"

    process_query = (
        "$targets = Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -match 'python|ollama|cmd' -and "
        "($_.CommandLine -match 'uvicorn|app.main|ollama|stable-diffusion-webui|webui-user|launch.py') "
        "}; "
        "$targets | Select-Object ProcessId,Name,CommandLine | Format-List | Out-String -Width 4096"
    )
    db_latest_messages = query_db(
        """
        SELECT id, conversation_id, role, substr(content, 1, 500) AS content_preview, created_at
        FROM messages
        ORDER BY id DESC
        LIMIT 10
        """
    )
    db_latest_images = query_db(
        """
        SELECT id, conversation_id, message_id, status, substr(error, 1, 500) AS error_preview,
               output_path, created_at
        FROM image_requests
        ORDER BY id DESC
        LIMIT 10
        """
    )
    db_latest_frames = query_db(
        """
        SELECT id, conversation_id, character_id, frame_index, assistant_message_id,
               image_request_id, status, round(text_elapsed_s, 3) AS text_elapsed_s,
               round(image_elapsed_s, 3) AS image_elapsed_s,
               substr(error, 1, 500) AS error_preview
        FROM story_frames
        ORDER BY id DESC
        LIMIT 10
        """
    )

    report = ""
    report += section("Generated At", datetime.now().isoformat(timespec="seconds"))
    report += section("App Status", fetch_status())
    report += section(
        "GPU",
        run_command(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ]
        ),
    )
    report += section(
        "Relevant Processes",
        run_command(["powershell", "-NoProfile", "-Command", process_query], timeout=15),
    )
    report += json_section("Latest Messages", db_latest_messages)
    report += json_section("Latest Image Requests", db_latest_images)
    report += json_section("Latest Story Frames", db_latest_frames)
    report += section("Tail: runtime/logs/app_events.jsonl", tail(settings.runtime_dir / "logs" / "app_events.jsonl"))
    report += section("Tail: runtime/logs/a1111_app.log", tail(settings.runtime_dir / "logs" / "a1111_app.log"))

    output_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nSaved debug dump to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
