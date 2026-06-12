"""Run one real chat route request with auto-image enabled.

This exercises the product loop through FastAPI:

user message -> real text reply -> real image prompt composition -> hard Ollama
handoff -> real A1111 render.

Run through scripts/run_real_app_route_image_guarded.ps1 so the watchdog can
terminate backends if RAM, commit, or VRAM become unsafe.
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

SLUG = os.getenv("COMPANION_SMOKE_SLUG", "codex-echidna-real-chat-auto-smoke")
RESOLUTION_PRESET = os.getenv("COMPANION_SMOKE_RESOLUTION_PRESET", "")
USER_MESSAGE = os.getenv(
    "COMPANION_SMOKE_USER_MESSAGE",
    "Come sit beside me for a moment. I need to stop pretending this does not bother me.",
)


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


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT_DIR / "outputs" / "diags" / f"real_app_chat_auto_smoke_{stamp}"
    run_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run_dir] {run_dir}")
    cleanup_db()

    try:
        with TestClient(app) as client:
            character_id = save_character(
                {
                    "slug": SLUG,
                    "display_name": "Echidna",
                    "source_media": "Re:Zero",
                    "character_dossier": (
                        "Echidna is the Witch of Greed from Re:Zero: pale skin, long white hair, "
                        "black eyes, thick white eyelashes, a green butterfly hair clip, and a "
                        "softly calculating intimacy. She speaks as if every feeling is a specimen "
                        "worth turning in the light, but she can still sound gentle when Anon is raw."
                    ),
                    "appearance": (
                        "Echidna: long straight white hair, black eyes, thick white eyelashes, "
                        "green butterfly clip, porcelain skin, elegant black-and-white dress.\n"
                        "Mirajane: silvery-white ponytail, blue eyes, barmaid outfit."
                    ),
                    "image_anchor_summary": (
                        "Echidna: porcelain skin, white eyelashes, elegant black-and-white dress, "
                        "witch of greed, Re:Zero accurate design.\n"
                        "Mirajane: curvy figure, Fairy Tail guild hall."
                    ),
                    "image_prompt_positive_additions": (
                        "painterly anime artwork, masterpiece, fine details, breathtaking artwork, "
                        "high quality, exquisite composition and lighting"
                    ),
                    "image_prompt_negative_additions": (
                        "(worst quality, low quality, blurry:1.3), bad anatomy, extra limbs, "
                        "extra fingers, text, watermark"
                    ),
                    "default_visual_style": "painterly anime artwork, fine details, warm candlelight",
                    "special_instructions": (
                        "Write in immersive visual-novel prose. Keep Echidna's dialogue intimate, "
                        "observant, and lightly teasing. Narrate actions in third person and let her "
                        "spoken dialogue remain first person."
                    ),
                    "example_dialogue": (
                        '{{user}}: "I do not know what I am supposed to do."\n'
                        "{{char}}: Echidna's smile softens by a fraction, as though the admission "
                        "has pleased her more than any performance could.\n"
                        '"Then do nothing for one breath," she murmurs. "Let me observe the honest '
                        'you before you bury him again."'
                    ),
                    "is_active": True,
                }
            )
            replace_pinned_memory(
                character_id,
                "Anon is emotionally worn down and tends to dodge pain with dry humor. Echidna is sitting "
                "with him in a candlelit tea room, studying his feelings with possessive curiosity.",
            )
            save_user_profile("Anon", "A tired young man who masks insecurity with dry, evasive humor.")
            conversation = ensure_conversation(character_id)

            started = datetime.now()
            response = client.post(
                f"/chat/{character_id}",
                data={
                    "message": USER_MESSAGE,
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

            result = {
                "status_code": response.status_code,
                "elapsed_s": image_ready_elapsed_s,
                "route_elapsed_s": route_elapsed_s,
                "image_ready_elapsed_s": image_ready_elapsed_s,
                "message_count": len(messages),
                "assistant_id": assistant["id"] if assistant else None,
                "image_rows": len(image_rows),
                "response_preview": response.text[:1200],
            }
            (run_dir / "user.txt").write_text(USER_MESSAGE, encoding="utf-8")
            (run_dir / "messages.json").write_text(
                json.dumps([dict(row) for row in messages], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            if assistant:
                (run_dir / "assistant.txt").write_text(str(assistant["content"]), encoding="utf-8")

            if response.status_code != 200 or not assistant or not image_rows:
                (run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
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
                "diag_image_path": str(run_dir / f"{run_id}_image.png"),
                "diag_settings_path": str(run_dir / f"{run_id}_a1111_settings.json"),
                "positive_has_rezero": "Echidna from Re:Zero" in positive,
                "positive_has_mirajane": "Mirajane" in positive,
                "negative_has_scene_narrative": "Echidna sits" in negative or "Anon" in negative,
            }
            (run_dir / "positive_prompt.txt").write_text(positive, encoding="utf-8")
            (run_dir / "negative_prompt.txt").write_text(negative, encoding="utf-8")
            (run_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            copy_if_exists(output_path, run_dir / "image.png")
            copy_if_exists(settings_path, run_dir / "a1111_settings.json")
            copy_if_exists(output_path, run_dir / f"{run_id}_image.png")
            copy_if_exists(settings_path, run_dir / f"{run_id}_a1111_settings.json")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if not output_path.exists():
                return 1
            if not result["positive_has_rezero"] or result["positive_has_mirajane"]:
                return 1
            if result["negative_has_scene_narrative"]:
                return 1
            return 0
    finally:
        cleanup_db()


if __name__ == "__main__":
    raise SystemExit(main())
