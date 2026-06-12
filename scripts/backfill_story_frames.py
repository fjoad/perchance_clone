"""Backfill structured story frames from existing messages/images.

This is intentionally conservative: it creates frames only for assistant
messages that do not already have a story_frame row.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import ensure_runtime_dirs, settings  # noqa: E402
from app.db import (  # noqa: E402
    connect,
    create_story_frame,
    get_story_frame_by_assistant_message,
    init_db,
    list_images_for_message,
    list_messages,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill story_frames for existing conversations.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created without writing.")
    return parser.parse_args()


def list_conversations() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY id ASC"
        ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def main() -> int:
    args = parse_args()
    ensure_runtime_dirs()
    init_db()

    created = 0
    skipped = 0
    for conversation in list_conversations():
        messages = list_messages(int(conversation["id"]))
        previous_user: dict | None = None
        for message in messages:
            if message["role"] == "user":
                previous_user = message
                continue
            if message["role"] != "assistant":
                continue
            if get_story_frame_by_assistant_message(int(message["id"])):
                skipped += 1
                continue

            images = list_images_for_message(int(message["id"]))
            image = images[-1] if images else {}
            payload = {
                "conversation_id": conversation["id"],
                "character_id": conversation["character_id"],
                "user_message_id": previous_user.get("id") if previous_user else None,
                "assistant_message_id": message["id"],
                "image_request_id": image.get("id"),
                "user_input": previous_user.get("content", "") if previous_user else "",
                "assistant_output": message.get("content", ""),
                "scene_summary": image.get("scene_summary", ""),
                "image_positive_prompt": image.get("positive_prompt", ""),
                "image_negative_prompt": image.get("negative_prompt", ""),
                "image_output_path": image.get("output_path", ""),
                "text_model": settings.ollama_model_name,
                "image_backend": "a1111" if image else "",
                "image_preset": (
                    f"{image.get('base_width')}x{image.get('base_height')}"
                    f"->{image.get('target_width')}x{image.get('target_height')}"
                    if image
                    else ""
                ),
                "status": "image_completed" if image else "text_completed",
                "metadata_json": json.dumps({"backfilled": True}, ensure_ascii=False),
            }
            if args.dry_run:
                print(
                    f"would create frame conversation={conversation['id']} "
                    f"assistant_message={message['id']}"
                )
            else:
                create_story_frame(payload)
            created += 1

    action = "Would create" if args.dry_run else "Created"
    print(f"{action} {created} frame(s); skipped {skipped} existing frame(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
