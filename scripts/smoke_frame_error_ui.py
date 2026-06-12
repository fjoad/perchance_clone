"""Smoke-test that failed image/frame errors are visible in the timeline."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["COMPANION_USE_MOCK_TEXT"] = "1"
os.environ["COMPANION_USE_MOCK_IMAGE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import add_message, connect, create_story_frame, ensure_conversation, save_character  # noqa: E402
from app.main import app  # noqa: E402

SLUG = "codex-frame-error-smoke"
ERROR_TEXT = "Image render stopped by resource guard: free RAM 2.0GB < 6GB"


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


def main() -> int:
    cleanup()
    try:
        with TestClient(app) as client:
            character_id = save_character(
                {
                    "slug": SLUG,
                    "display_name": "Error Smoke",
                    "source_media": "Original",
                    "character_dossier": "A test character for visible frame errors.",
                    "appearance": "anime woman in a workshop",
                    "is_active": True,
                }
            )
            conversation = ensure_conversation(character_id)
            user_id = add_message(conversation["id"], "user", "Try to render this scene.")
            assistant_id = add_message(conversation["id"], "assistant", "She gestures toward the half-lit canvas.")
            create_story_frame(
                {
                    "conversation_id": conversation["id"],
                    "character_id": character_id,
                    "frame_index": 1,
                    "user_message_id": user_id,
                    "assistant_message_id": assistant_id,
                    "user_input": "Try to render this scene.",
                    "assistant_output": "She gestures toward the half-lit canvas.",
                    "status": "image_error",
                    "error": ERROR_TEXT,
                }
            )
            response = client.get(f"/timeline/{character_id}")
            checks = {
                "status_code": response.status_code,
                "has_error": "Image render stopped by resource guard" in response.text and "free RAM" in response.text,
                "has_frame_error_class": "frame-error" in response.text,
                "has_retry_button": "Retry Visual" in response.text,
            }
            print(checks)
            return 0 if all(checks.values()) else 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
