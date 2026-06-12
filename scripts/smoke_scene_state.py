"""Smoke-test editable scene state propagation into frames and prompts."""
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

from app.db import (  # noqa: E402
    connect,
    ensure_conversation,
    get_conversation_state,
    get_latest_summary,
    get_pinned_memory,
    get_user_profile,
    list_messages,
    list_story_frames,
    save_character,
)
from app.main import app  # noqa: E402
from app.services.prompts import build_chat_messages  # noqa: E402

SLUG = "codex-scene-state-smoke"


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
                    "display_name": "Echidna",
                    "source_media": "Re:Zero",
                    "character_dossier": "A white-haired witch speaking in intimate visual-novel prose.",
                    "appearance": "Echidna from Re:Zero, long white hair, black eyes, elegant dress",
                    "image_anchor_summary": "Echidna from Re:Zero in a candlelit study.",
                    "default_visual_style": "painterly anime artwork",
                    "is_active": True,
                }
            )
            conversation = ensure_conversation(character_id)

            state_response = client.post(
                "/conversation-state",
                data={
                    "character_id": str(character_id),
                    "current_location_name": "Candlelit tea room",
                    "current_location_description": (
                        "A quiet mansion chamber with black tea, low firelight, and rain at the window."
                    ),
                    "active_characters": "Echidna, Anon",
                },
            )
            if state_response.status_code != 200:
                print(f"FAIL scene-state status={state_response.status_code}")
                return 1

            chat_response = client.post(
                f"/chat/{character_id}",
                data={
                    "message": "Keep the conversation quiet and close.",
                    "auto_image": "",
                    "resolution_preset": "",
                },
            )
            if chat_response.status_code != 200:
                print(f"FAIL chat status={chat_response.status_code}")
                return 1

            frames = list_story_frames(conversation["id"])
            if not frames:
                print("FAIL no frame created")
                return 1
            frame = frames[-1]
            state = get_conversation_state(conversation["id"])
            messages = list_messages(conversation["id"])
            user_profile = get_user_profile()
            prompt_messages = build_chat_messages(
                {"id": character_id, "display_name": "Echidna", "source_media": "Re:Zero"},
                user_profile,
                get_pinned_memory(character_id),
                get_latest_summary(character_id, conversation["id"]),
                [],
                messages,
                frames,
                state,
            )
            system_prompt = prompt_messages[0]["content"]
            checks = {
                "state_location": state.get("current_location_name"),
                "frame_location": frame.get("location_name"),
                "frame_active": frame.get("active_characters_json"),
                "prompt_has_location": "Candlelit tea room" in system_prompt,
                "prompt_has_details": "low firelight" in system_prompt,
                "prompt_has_active": "Echidna" in system_prompt and "Anon" in system_prompt,
            }
            print(checks)
            ok = (
                checks["state_location"] == "Candlelit tea room"
                and checks["frame_location"] == "Candlelit tea room"
                and checks["prompt_has_location"]
                and checks["prompt_has_details"]
                and checks["prompt_has_active"]
            )
            if not ok:
                return 1

            latest_assistant = next((row for row in reversed(messages) if row["role"] == "assistant"), None)
            if not latest_assistant:
                print("FAIL no assistant message before regenerate")
                return 1
            regen_response = client.post(
                f"/messages/{latest_assistant['id']}/regenerate",
                data={"character_id": str(character_id)},
            )
            if regen_response.status_code != 200:
                print(f"FAIL regenerate status={regen_response.status_code}")
                return 1
            regen_frames = list_story_frames(conversation["id"])
            regen_frame = regen_frames[-1] if regen_frames else {}
            regen_checks = {
                "regen_frame_location": regen_frame.get("location_name"),
                "regen_status": regen_frame.get("status"),
            }
            print(regen_checks)
            return 0 if regen_checks["regen_frame_location"] == "Candlelit tea room" else 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
