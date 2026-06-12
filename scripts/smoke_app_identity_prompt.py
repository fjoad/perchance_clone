"""Smoke-test app image prompt identity anchoring without loading real models.

This test uses FastAPI's TestClient with mock text/image enabled. It verifies
the real route path saves an image prompt that includes the active character's
source media and filters out unrelated visual cards from multi-character imports.
"""
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

from app.db import add_message, connect, ensure_conversation, list_images_for_message, save_character  # noqa: E402
from app.main import app  # noqa: E402

SLUG = "codex-echidna-identity-smoke"


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


def wait_character_images(character_id: int, min_count: int, timeout_s: float = 30) -> list[dict]:
    deadline = time.time() + timeout_s
    rows: list[dict] = []
    while time.time() < deadline:
        with connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM image_requests WHERE character_id = ? ORDER BY id ASC",
                    (character_id,),
                ).fetchall()
            ]
        if len(rows) >= min_count:
            return rows
        time.sleep(0.5)
    return rows


def main() -> int:
    cleanup()
    try:
        with TestClient(app) as client:
            character_id = save_character(
                {
                    "slug": SLUG,
                    "display_name": "Echidna",
                    "source_media": "Re:Zero",
                    "character_dossier": (
                        "Echidna is a pale, white-haired witch with black eyes "
                        "and a calculating, intimate presence."
                    ),
                    "appearance": (
                        "Echidna: long straight white hair, black eyes, green butterfly clip.\n"
                        "Mirajane: silvery-white ponytail, blue eyes."
                    ),
                    "image_anchor_summary": (
                        "Echidna: porcelain skin, white eyelashes, elegant black-and-white dress.\n"
                        "Mirajane: curvy figure, barmaid outfit."
                    ),
                    "image_prompt_positive_additions": (
                        "Echidna: tea room, witch of greed, Re:Zero accurate design.\n"
                        "Mirajane: Fairy Tail guild hall."
                    ),
                    "image_prompt_negative_additions": "bad anatomy",
                    "default_visual_style": "painterly anime artwork, fine details",
                    "is_active": True,
                }
            )
            conversation = ensure_conversation(character_id)
            add_message(conversation["id"], "user", "The girl I keep chasing does not want me.")
            assistant_id = add_message(
                conversation["id"],
                "assistant",
                "Echidna sits beside Anon in a candlelit room, offering tea with a quiet, knowing smile.",
            )
            response = client.post(
                f"/messages/{assistant_id}/image",
                data={"character_id": str(character_id)},
            )
            rows = list_images_for_message(assistant_id)
            if response.status_code != 200 or not rows:
                print(f"FAIL: status={response.status_code}, image_rows={len(rows)}")
                return 1
            positive = str(rows[-1]["positive_prompt"])
            has_identity = "Echidna from Re:Zero" in positive
            has_contamination = "Mirajane" in positive
            print(f"status={response.status_code}")
            print(f"image_rows={len(rows)}")
            print(f"has_identity={has_identity}")
            print(f"has_contamination={has_contamination}")
            print(f"positive={positive}")
            if not has_identity or has_contamination:
                return 1

            auto_response = client.post(
                f"/chat/{character_id}",
                data={
                    "message": "Come sit beside me for a moment.",
                    "auto_image": "1",
                    "resolution_preset": "",
                },
            )
            auto_images = wait_character_images(character_id, min_count=2, timeout_s=30)
            if auto_response.status_code != 200 or len(auto_images) < 2:
                print(f"FAIL auto image: status={auto_response.status_code}, image_rows={len(auto_images)}")
                return 1
            auto_positive = str(auto_images[-1]["positive_prompt"])
            auto_has_identity = "Echidna from Re:Zero" in auto_positive
            auto_has_contamination = "Mirajane" in auto_positive
            print(f"auto_status={auto_response.status_code}")
            print(f"auto_has_identity={auto_has_identity}")
            print(f"auto_has_contamination={auto_has_contamination}")
            print(f"auto_positive={auto_positive}")
            return 0 if auto_has_identity and not auto_has_contamination else 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
