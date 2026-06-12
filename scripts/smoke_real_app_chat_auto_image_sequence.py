"""Run a guarded two-turn real chat + auto-image sequence.

This measures the product loop after the first cold turn:

turn 1: cold text + cold/hot A1111 depending on process state
turn 2: A1111 should already be hot; Ollama reloads after the hard image handoff
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["COMPANION_USE_MOCK_TEXT"] = "0"
os.environ["COMPANION_USE_MOCK_IMAGE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import (  # noqa: E402
    connect,
    ensure_conversation,
    list_images_for_message,
    list_messages,
    replace_pinned_memory,
    save_character,
    save_user_profile,
)
from app.main import app  # noqa: E402

SLUG = os.getenv("COMPANION_SMOKE_SLUG", "codex-echidna-real-chat-sequence-smoke")
RESOLUTION_PRESET = os.getenv("COMPANION_SMOKE_RESOLUTION_PRESET", "")
USER_MESSAGES = [
    "Come sit beside me for a moment. I need to stop pretending this does not bother me.",
    "Don't make it a game yet. Just stay here with me and tell me what you actually see.",
]


def cleanup_db() -> None:
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


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def wait_images_for_message(message_id: int, timeout_s: float = 1200) -> list[dict[str, object]]:
    deadline = time.time() + timeout_s
    rows: list[dict[str, object]] = []
    while time.time() < deadline:
        rows = list_images_for_message(message_id)
        if rows:
            return rows
        time.sleep(1)
    return rows


def create_character() -> int:
    character_id = save_character(
        {
            "slug": SLUG,
            "display_name": "Echidna",
            "source_media": "Re:Zero",
            "character_dossier": (
                "Echidna is the Witch of Greed from Re:Zero: pale skin, long white hair, black eyes, "
                "thick white eyelashes, a green butterfly hair clip, and a softly calculating intimacy. "
                "She speaks as if every feeling is a specimen worth turning in the light, but she can "
                "still sound gentle when Anon is raw."
            ),
            "appearance": (
                "Echidna: long straight white hair, black eyes, thick white eyelashes, green butterfly clip, "
                "porcelain skin, elegant black-and-white dress.\n"
                "Mirajane: silvery-white ponytail, blue eyes, barmaid outfit."
            ),
            "image_anchor_summary": (
                "Echidna: porcelain skin, white eyelashes, elegant black-and-white dress, witch of greed, "
                "Re:Zero accurate design.\n"
                "Mirajane: curvy figure, Fairy Tail guild hall."
            ),
            "image_prompt_positive_additions": (
                "painterly anime artwork, masterpiece, fine details, breathtaking artwork, high quality, "
                "exquisite composition and lighting"
            ),
            "image_prompt_negative_additions": (
                "(worst quality, low quality, blurry:1.3), bad anatomy, extra limbs, extra fingers, text, watermark"
            ),
            "default_visual_style": "painterly anime artwork, fine details, warm candlelight",
            "special_instructions": (
                "Write in immersive visual-novel prose. Keep Echidna's dialogue intimate, observant, and "
                "lightly teasing. Narrate actions in third person and let her spoken dialogue remain first person."
            ),
            "example_dialogue": (
                '{{user}}: "I do not know what I am supposed to do."\n'
                "{{char}}: Echidna's smile softens by a fraction, as though the admission has pleased her "
                "more than any performance could.\n"
                '"Then do nothing for one breath," she murmurs. "Let me observe the honest you before you bury him again."'
            ),
            "is_active": True,
        }
    )
    replace_pinned_memory(
        character_id,
        "Anon is emotionally worn down and tends to dodge pain with dry humor. Echidna is sitting with him "
        "in a candlelit tea room, studying his feelings with possessive curiosity.",
    )
    save_user_profile("Anon", "A tired young man who masks insecurity with dry, evasive humor.")
    return int(character_id)


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT_DIR / "outputs" / "diags" / f"real_app_chat_auto_sequence_{stamp}"
    run_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run_dir] {run_dir}")
    cleanup_db()
    results: list[dict[str, object]] = []

    try:
        with TestClient(app) as client:
            character_id = create_character()
            conversation = ensure_conversation(character_id)
            for turn_index, user_message in enumerate(USER_MESSAGES, start=1):
                turn_dir = run_dir / f"turn{turn_index:03d}"
                turn_dir.mkdir(parents=True, exist_ok=True)
                started = datetime.now()
                response = client.post(
                    f"/chat/{character_id}",
                    data={
                        "message": user_message,
                        "auto_image": "1",
                        "resolution_preset": RESOLUTION_PRESET,
                    },
                    timeout=1200,
                )
                route_elapsed_s = (datetime.now() - started).total_seconds()
                messages = list_messages(conversation["id"])
                assistant = next((dict(row) for row in reversed(messages) if row["role"] == "assistant"), None)
                image_rows = wait_images_for_message(int(assistant["id"])) if assistant else []
                image_ready_elapsed_s = (datetime.now() - started).total_seconds()
                result: dict[str, object] = {
                    "turn": turn_index,
                    "status_code": response.status_code,
                    "elapsed_s": image_ready_elapsed_s,
                    "route_elapsed_s": route_elapsed_s,
                    "image_ready_elapsed_s": image_ready_elapsed_s,
                    "message_count": len(messages),
                    "assistant_id": assistant["id"] if assistant else None,
                    "image_rows": len(image_rows),
                    "response_preview": response.text[:1200],
                }
                (turn_dir / "user.txt").write_text(user_message, encoding="utf-8")
                (turn_dir / "messages.json").write_text(
                    json.dumps([dict(row) for row in messages], indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                if assistant:
                    (turn_dir / "assistant.txt").write_text(str(assistant["content"]), encoding="utf-8")
                if response.status_code != 200 or not assistant or not image_rows:
                    results.append(result)
                    (turn_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                    (run_dir / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
                    print(json.dumps(result, indent=2))
                    return 1

                row = image_rows[-1]
                positive = str(row["positive_prompt"])
                negative = str(row["negative_prompt"])
                output_path = settings.outputs_dir / row["output_path"]
                settings_path = output_path.with_name(output_path.stem.replace("_final", "") + "_a1111_settings.json")
                result |= {
                    "image_row": dict(row),
                    "output_path": str(output_path),
                    "settings_path": str(settings_path),
                    "diag_image_path": str(turn_dir / f"{run_id}_turn{turn_index:03d}_image.png"),
                    "diag_settings_path": str(turn_dir / f"{run_id}_turn{turn_index:03d}_a1111_settings.json"),
                    "positive_has_rezero": "Echidna from Re:Zero" in positive,
                    "positive_has_mirajane": "Mirajane" in positive,
                    "negative_has_scene_narrative": "Echidna sits" in negative or "Anon" in negative,
                }
                (turn_dir / "positive_prompt.txt").write_text(positive, encoding="utf-8")
                (turn_dir / "negative_prompt.txt").write_text(negative, encoding="utf-8")
                (turn_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                copy_if_exists(output_path, turn_dir / "image.png")
                copy_if_exists(settings_path, turn_dir / "a1111_settings.json")
                copy_if_exists(output_path, turn_dir / f"{run_id}_turn{turn_index:03d}_image.png")
                copy_if_exists(settings_path, turn_dir / f"{run_id}_turn{turn_index:03d}_a1111_settings.json")
                results.append(result)
                print(json.dumps(result, indent=2, ensure_ascii=False))

                if not output_path.exists():
                    return 1
                if not result["positive_has_rezero"] or result["positive_has_mirajane"]:
                    return 1
                if result["negative_has_scene_narrative"]:
                    return 1

            (run_dir / "summary.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
            return 0
    finally:
        cleanup_db()


if __name__ == "__main__":
    raise SystemExit(main())
