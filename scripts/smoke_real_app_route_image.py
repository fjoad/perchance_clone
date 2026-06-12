"""Run one real app-route text-to-image request and save a small audit bundle.

This intentionally uses the FastAPI route path, not just lower-level services.
Run it through scripts/run_real_app_route_image_guarded.ps1 so a watchdog can
terminate the process tree if system RAM/commit/VRAM gets unsafe.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure this script never accidentally uses mock services.
os.environ["COMPANION_USE_MOCK_TEXT"] = "0"
os.environ["COMPANION_USE_MOCK_IMAGE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import add_message, connect, ensure_conversation, list_images_for_message, save_character  # noqa: E402
from app.main import app  # noqa: E402

SLUG = os.getenv("COMPANION_SMOKE_SLUG", "codex-echidna-real-route-smoke")
RESOLUTION_PRESET = os.getenv("COMPANION_SMOKE_RESOLUTION_PRESET", "")


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


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT_DIR / "outputs" / "diags" / f"real_app_route_smoke_{stamp}"
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
                        "Echidna is a pale, white-haired witch with black eyes, thick white lashes, "
                        "a green butterfly clip, and a calculating, intimate presence. She is seated "
                        "in a warm candlelit tea room with Anon."
                    ),
                    "appearance": (
                        "Echidna: long straight white hair, black eyes, thick white eyelashes, "
                        "green butterfly clip, porcelain skin.\n"
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
                    "is_active": True,
                }
            )
            conversation = ensure_conversation(character_id)
            add_message(conversation["id"], "user", "The girl I keep chasing does not want me.")
            assistant_text = (
                "Echidna sits beside Anon in a candlelit tea room, her long white hair falling over "
                "one shoulder as she offers him a porcelain cup and watches him with quiet, possessive sympathy."
            )
            assistant_id = add_message(conversation["id"], "assistant", assistant_text)
            (run_dir / "assistant_input.txt").write_text(assistant_text, encoding="utf-8")

            response = client.post(
                f"/messages/{assistant_id}/image",
                data={"character_id": str(character_id), "resolution_preset": RESOLUTION_PRESET},
                timeout=900,
            )
            rows = list_images_for_message(assistant_id)
            result = {
                "status_code": response.status_code,
                "image_rows": len(rows),
                "response_preview": response.text[:1000],
            }
            if response.status_code != 200 or not rows:
                (run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(result, indent=2))
                return 1

            row = rows[-1]
            positive = str(row["positive_prompt"])
            negative = str(row["negative_prompt"])
            output_path = settings.outputs_dir / row["output_path"]
            settings_path = output_path.with_name(output_path.stem.replace("_final", "") + "_a1111_settings.json")
            result |= {
                "image_row": row,
                "output_path": str(output_path),
                "settings_path": str(settings_path),
                "diag_image_path": str(run_dir / f"{run_id}_image.png"),
                "diag_settings_path": str(run_dir / f"{run_id}_a1111_settings.json"),
                "positive_has_rezero": "Echidna from Re:Zero" in positive,
                "positive_has_mirajane": "Mirajane" in positive,
            }
            (run_dir / "positive_prompt.txt").write_text(positive, encoding="utf-8")
            (run_dir / "negative_prompt.txt").write_text(negative, encoding="utf-8")
            (run_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            copy_if_exists(output_path, run_dir / "image.png")
            copy_if_exists(settings_path, run_dir / "a1111_settings.json")
            copy_if_exists(output_path, run_dir / f"{run_id}_image.png")
            copy_if_exists(settings_path, run_dir / f"{run_id}_a1111_settings.json")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if not result["positive_has_rezero"] or result["positive_has_mirajane"] or not output_path.exists():
                return 1
            return 0
    finally:
        cleanup_db()


if __name__ == "__main__":
    raise SystemExit(main())
