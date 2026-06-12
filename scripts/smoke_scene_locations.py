"""Smoke-test reusable scene locations in mock mode."""
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

from app.db import connect, ensure_conversation, get_conversation_state, list_scene_locations, save_character  # noqa: E402
from app.main import app  # noqa: E402

SLUG = "codex-location-smoke"


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
        conn.execute("DELETE FROM scene_locations WHERE character_id = ?", (character_id,))
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
                    "display_name": "Location Smoke",
                    "source_media": "Original",
                    "character_dossier": "A test character for reusable scene locations.",
                    "appearance": "anime woman in a quiet garden",
                    "image_anchor_summary": "Location Smoke in a quiet garden.",
                    "default_visual_style": "painterly anime artwork",
                    "is_active": True,
                }
            )
            save_response = client.post(
                "/locations",
                data={
                    "character_id": str(character_id),
                    "name": "Rain garden",
                    "description": "Wet stone paths, dark leaves, and gold windowlight.",
                    "visual_anchor": "low camera, soft mist, lantern reflections",
                },
            )
            if save_response.status_code != 200:
                print(f"FAIL save status={save_response.status_code}")
                return 1
            locations = list_scene_locations(character_id)
            if len(locations) != 1:
                print(f"FAIL location_count={len(locations)}")
                return 1
            use_response = client.post(
                f"/locations/{locations[0]['id']}/use",
                data={"character_id": str(character_id), "active_characters": "Location Smoke, Anon"},
            )
            if use_response.status_code != 200:
                print(f"FAIL use status={use_response.status_code}")
                return 1
            conversation = ensure_conversation(character_id)
            state = get_conversation_state(conversation["id"])
            checks = {
                "location_count": len(locations),
                "state_location": state.get("current_location_name"),
                "state_details": state.get("current_location_description"),
                "active": state.get("active_characters_json"),
            }
            print(checks)
            ok = (
                checks["location_count"] == 1
                and checks["state_location"] == "Rain garden"
                and "Wet stone paths" in str(checks["state_details"])
                and "Anon" in str(checks["active"])
            )
            return 0 if ok else 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
