"""Mock-mode smoke test for the streaming chat route.

Verifies that POST /chat/{id}/stream emits NDJSON status/tok events followed by
a done event, that the assistant message and story frame are persisted, and
that the temporary smoke character is cleaned up afterward.

Usage:
    python scripts/smoke_stream_chat.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["COMPANION_USE_MOCK_TEXT"] = "1"
os.environ["COMPANION_USE_MOCK_IMAGE"] = "1"
os.environ["COMPANION_PRELOAD_TEXT_MODEL"] = "0"
os.environ["COMPANION_PRELOAD_IMAGE_BACKEND"] = "0"

from fastapi.testclient import TestClient

from app.config import ensure_runtime_dirs
from app.db import (
    connect,
    get_character_by_slug,
    init_db,
    save_character,
)
from app.main import app

SLUG = "codex-stream-smoke"


def cleanup() -> None:
    row = get_character_by_slug(SLUG)
    if not row:
        return
    character_id = int(row["id"])
    with connect() as conn:
        conversation_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM conversations WHERE character_id = ?", (character_id,)
        ).fetchall()]
        for conversation_id in conversation_ids:
            conn.execute("DELETE FROM story_frames WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM image_requests WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM memory_snapshots WHERE character_id = ?", (character_id,))
        conn.execute("DELETE FROM lore_entries WHERE character_id = ?", (character_id,))
        conn.execute("DELETE FROM conversations WHERE character_id = ?", (character_id,))
        conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))


def main() -> int:
    ensure_runtime_dirs()
    init_db()
    cleanup()
    character_id = save_character(
        {
            "slug": SLUG,
            "display_name": "Stream Smoke",
            "persona_summary": "Temporary streaming smoke-test character.",
            "is_active": True,
        }
    )

    events: list[dict] = []
    try:
        with TestClient(app) as client:
            with client.stream(
                "POST",
                f"/chat/{character_id}/stream",
                data={"message": "Hello there.", "auto_image": "", "resolution_preset": ""},
            ) as response:
                assert response.status_code == 200, response.status_code
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    events.append(json.loads(line))

        kinds = [event.get("t") for event in events]
        toks = [event for event in events if event.get("t") == "tok"]
        done = [event for event in events if event.get("t") == "done"]
        errs = [event for event in events if event.get("t") == "err"]
        assembled = "".join(event.get("v", "") for event in toks).strip()

        print({
            "event_count": len(events),
            "kinds_seen": sorted(set(kinds)),
            "tok_events": len(toks),
            "done": bool(done),
            "errors": [event.get("v") for event in errs],
            "reply_preview": assembled[:90],
        })

        from app.db import get_message, get_story_frame_by_assistant_message

        assert toks and len(toks) > 3, "expected multiple streamed token events"
        assert done, "missing done event"
        assert not errs, f"unexpected error events: {errs}"
        message_id = int(done[0]["message_id"])
        saved = get_message(message_id)
        assert saved and saved["content"].strip() == assembled, "persisted reply != streamed reply"
        frame = get_story_frame_by_assistant_message(message_id)
        assert frame is not None, "story frame missing for streamed reply"
        print({"persisted": True, "frame_index": frame.get("frame_index"), "frame_status": frame.get("status")})
        print("PASS")
        return 0
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
