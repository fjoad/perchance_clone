"""Smoke-test structured story export and import roundtrip in mock mode."""
from __future__ import annotations

import json
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

from app.db import connect, ensure_conversation, list_messages, list_story_frames, save_character  # noqa: E402
from app.main import app  # noqa: E402

SLUG_PREFIX = "codex-export-import-smoke"


def cleanup() -> None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, slug FROM characters WHERE slug = ? OR slug LIKE ?",
            (SLUG_PREFIX, f"{SLUG_PREFIX}-%"),
        ).fetchall()
        for row in rows:
            character_id = int(row["id"])
            conn.execute("DELETE FROM image_requests WHERE character_id = ?", (character_id,))
            conn.execute(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE character_id = ?)",
                (character_id,),
            )
            conn.execute("DELETE FROM conversations WHERE character_id = ?", (character_id,))
            conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
            output_dir = ROOT_DIR / "outputs" / "app" / str(row["slug"])
            if output_dir.exists():
                shutil.rmtree(output_dir)


def latest_smoke_character_id(excluding: int) -> int | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM characters
            WHERE (slug = ? OR slug LIKE ?) AND id != ?
            ORDER BY id DESC LIMIT 1
            """,
            (SLUG_PREFIX, f"{SLUG_PREFIX}-%", excluding),
        ).fetchone()
    return int(row["id"]) if row else None


def wait_for_frame_image(character_id: int, timeout_s: float = 30) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        conversation = ensure_conversation(character_id)
        frames = list_story_frames(conversation["id"])
        if frames and frames[-1].get("status") == "image_completed":
            return True
        time.sleep(0.5)
    return False


def main() -> int:
    cleanup()
    try:
        with TestClient(app) as client:
            character_id = save_character(
                {
                    "slug": SLUG_PREFIX,
                    "display_name": "Roundtrip Smoke",
                    "source_media": "Original",
                    "character_dossier": "A concise export/import test character.",
                    "appearance": "silver-haired anime woman in a lantern-lit archive",
                    "image_anchor_summary": "Roundtrip Smoke in a lantern-lit archive.",
                    "default_visual_style": "painterly anime artwork",
                    "is_active": True,
                }
            )
            state_response = client.post(
                "/conversation-state",
                data={
                    "character_id": str(character_id),
                    "current_location_name": "Lantern archive",
                    "current_location_description": "Tall shelves, amber lamps, and rain ticking against old windows.",
                    "active_characters": "Roundtrip Smoke, Anon",
                },
            )
            location_response = client.post(
                "/locations",
                data={
                    "character_id": str(character_id),
                    "name": "Lantern archive",
                    "description": "Tall shelves, amber lamps, and rain ticking against old windows.",
                    "visual_anchor": "warm lamps, vertical bookshelves, wet window glass",
                },
            )
            chat_response = client.post(
                f"/chat/{character_id}",
                data={
                    "message": "Begin with a soft line about the rain.",
                    "auto_image": "1",
                    "resolution_preset": "512x512:1024x1024",
                },
            )
            if state_response.status_code != 200 or location_response.status_code != 200 or chat_response.status_code != 200:
                print(
                    "FAIL route status "
                    f"state={state_response.status_code} "
                    f"location={location_response.status_code} "
                    f"chat={chat_response.status_code}"
                )
                return 1
            if not wait_for_frame_image(character_id):
                print("FAIL original frame image did not complete")
                return 1

            export_response = client.get(f"/stories/{character_id}/export")
            if export_response.status_code != 200:
                print(f"FAIL export status={export_response.status_code}")
                return 1
            exported = export_response.json()
            import_response = client.post(
                "/stories/import",
                data={"character_id": str(character_id), "story_json": json.dumps(exported)},
                follow_redirects=False,
            )
            if import_response.status_code != 303:
                print(f"FAIL import status={import_response.status_code}")
                return 1

            imported_id = latest_smoke_character_id(excluding=character_id)
            if imported_id is None:
                print("FAIL no imported character found")
                return 1
            imported_conversation = ensure_conversation(imported_id)
            imported_messages = list_messages(imported_conversation["id"])
            imported_frames = list_story_frames(imported_conversation["id"])
            imported_export = client.get(f"/stories/{imported_id}/export").json()
            checks = {
                "message_count": len(imported_messages),
                "frame_count": len(imported_frames),
                "image_count": len(imported_export.get("images", [])),
                "location_count": len(imported_export.get("scene_locations", [])),
                "state_location": imported_export.get("conversation_state", {}).get("current_location_name"),
                "character_slug": imported_export.get("character", {}).get("slug"),
            }
            print(checks)
            ok = (
                checks["message_count"] >= 2
                and checks["frame_count"] >= 1
                and checks["image_count"] >= 1
                and checks["location_count"] >= 1
                and checks["state_location"] == "Lantern archive"
                and checks["character_slug"] != SLUG_PREFIX
            )
            return 0 if ok else 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
