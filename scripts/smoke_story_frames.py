"""Smoke-test structured story frame creation in mock mode."""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["COMPANION_USE_MOCK_TEXT"] = "1"
os.environ["COMPANION_USE_MOCK_IMAGE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import connect, save_character  # noqa: E402
from app.main import app  # noqa: E402

SLUG = "codex-frame-smoke"


def cleanup() -> None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM characters WHERE slug = ?", (SLUG,)).fetchone()
        if not row:
            return
        character_id = int(row["id"])
        conn.execute("DELETE FROM image_requests WHERE character_id = ?", (character_id,))
        conn.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE character_id = ?)",
            (character_id,),
        )
        conn.execute("DELETE FROM conversations WHERE character_id = ?", (character_id,))
        conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
    output_dir = ROOT_DIR / "outputs" / "app" / SLUG
    if output_dir.exists():
        shutil.rmtree(output_dir)


def fetch_frame(character_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM story_frames
            WHERE character_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (character_id,),
        ).fetchone()
    return dict(row) if row else None


def main() -> int:
    cleanup()
    try:
        with TestClient(app) as client:
            character_id = save_character(
                {
                    "slug": SLUG,
                    "display_name": "Frame Smoke",
                    "source_media": "Original",
                    "character_dossier": "A concise test character for frame persistence.",
                    "appearance": "white-haired anime woman in a quiet study",
                    "image_anchor_summary": "Frame Smoke: white-haired anime woman in a quiet study.",
                    "default_visual_style": "painterly anime artwork, fine details",
                    "is_active": True,
                }
            )
            response = client.post(
                f"/chat/{character_id}",
                data={
                    "message": "Open the scene with a quiet greeting.",
                    "auto_image": "1",
                    "resolution_preset": "512x512:1024x1024",
                },
            )
            if response.status_code != 200:
                print(f"FAIL status={response.status_code}")
                return 1

            frame = None
            deadline = time.time() + 30
            while time.time() < deadline:
                frame = fetch_frame(character_id)
                if frame and frame.get("status") == "image_completed":
                    break
                time.sleep(0.5)

            if not frame:
                print("FAIL no frame created")
                return 1
            checks = {
                "has_user_input": bool(frame.get("user_input")),
                "has_assistant_output": bool(frame.get("assistant_output")),
                "has_text_elapsed": float(frame.get("text_elapsed_s") or 0) >= 0,
                "has_image_prompt": bool(frame.get("image_positive_prompt")),
                "has_image_path": bool(frame.get("image_output_path")),
                "status": frame.get("status"),
            }
            print(checks)
            ok = (
                checks["has_user_input"]
                and checks["has_assistant_output"]
                and checks["has_image_prompt"]
                and checks["has_image_path"]
                and checks["status"] == "image_completed"
            )
            return 0 if ok else 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
