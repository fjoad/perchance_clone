"""Import a research gold sample into the app database as a usable character."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import ensure_runtime_dirs  # noqa: E402
from app.db import (  # noqa: E402
    add_message,
    connect,
    ensure_conversation,
    get_character_by_slug,
    init_db,
    replace_pinned_memory,
    save_character,
    save_user_profile,
    slug_exists,
)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "character"


def unique_slug(base: str, current_id: int | None = None) -> str:
    slug = base
    counter = 2
    while slug_exists(slug, exclude_id=current_id):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def split_suffix_and_negative(suffix: str) -> tuple[str, str]:
    marker = "(negativePrompt:::"
    if marker not in suffix:
        return suffix.strip(" ,"), ""
    positive_suffix, negative_tail = suffix.split(marker, 1)
    negative = negative_tail.rsplit(")", 1)[0]
    return positive_suffix.strip(" ,"), negative.strip(" ,")


def load_sample(sample_dir: Path) -> dict[str, Any]:
    metadata = json.loads((sample_dir / "metadata.json").read_text(encoding="utf-8"))
    return {
        "metadata": metadata,
        "character_profile": (sample_dir / "character_profile.md").read_text(encoding="utf-8").strip(),
        "protagonist_profile": (sample_dir / "protagonist_profile.md").read_text(encoding="utf-8").strip(),
        "reminder_note": (sample_dir / "reminder_note.md").read_text(encoding="utf-8").strip(),
        "image_prompt_prefix": (sample_dir / "image_prompt_prefix.txt").read_text(encoding="utf-8").strip(),
        "image_prompt_suffix": (sample_dir / "image_prompt_suffix.txt").read_text(encoding="utf-8").strip(),
        "image_prompt_triggers": (sample_dir / "image_prompt_triggers.txt").read_text(encoding="utf-8").strip(),
        "turns": json.loads((sample_dir / "turns.json").read_text(encoding="utf-8")),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a research gold sample into the app DB.")
    parser.add_argument("sample_dir", type=Path, help="Path like outputs/research_gold_samples/echidna")
    parser.add_argument("--slug", default="", help="Character slug. Defaults to character name.")
    parser.add_argument("--source-media", default="", help="Source media/franchise, e.g. Re:Zero.")
    parser.add_argument("--user-name", default="Anon")
    parser.add_argument("--import-user-profile", action="store_true")
    parser.add_argument("--import-turns", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sample_dir = args.sample_dir
    if not sample_dir.exists():
        print(f"Sample dir not found: {sample_dir}")
        return 1

    sample = load_sample(sample_dir)
    name = str(sample["metadata"].get("character_name") or sample_dir.name).strip()
    base_slug = args.slug.strip() or slugify(name)
    existing = get_character_by_slug(base_slug)
    current_id = int(existing["id"]) if existing else None
    slug = unique_slug(base_slug, current_id=current_id)
    positive_suffix, negative_prompt = split_suffix_and_negative(sample["image_prompt_suffix"])

    payload = {
        "id": current_id,
        "slug": slug,
        "display_name": name,
        "persona_summary": f"Imported gold sample: {sample['metadata'].get('thread_name') or sample_dir.name}",
        "character_dossier": sample["character_profile"],
        "personality_traits": "",
        "speaking_style": "",
        "backstory": "",
        "relationship_frame": "",
        "boundaries": "",
        "appearance": sample["image_prompt_triggers"],
        "example_dialogue": "",
        "default_visual_style": sample["image_prompt_prefix"],
        "source_media": args.source_media.strip(),
        "special_instructions": sample["reminder_note"],
        "image_anchor_summary": sample["image_prompt_triggers"],
        "image_prompt_positive_additions": positive_suffix,
        "image_prompt_negative_additions": negative_prompt,
        "is_active": True,
    }

    visual_labels = re.findall(r"(?m)^\s*([^:\n]{1,80})\s*:", payload["image_anchor_summary"])
    print(f"{'Would import' if args.dry_run else 'Importing'} {name!r} as slug={slug!r}")
    print(f"source_media={payload['source_media']!r}")
    print(f"image_anchor_has_chars={', '.join(visual_labels)}")
    if args.dry_run:
        return 0

    character_id = save_character(payload)
    replace_pinned_memory(character_id, f"{name} is the active companion imported from {sample_dir.as_posix()}.")

    if args.import_user_profile:
        save_user_profile(args.user_name, sample["protagonist_profile"])
        print(f"Updated user profile: {args.user_name}")

    if args.import_turns:
        conversation = ensure_conversation(character_id)
        with connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation["id"],))
        for turn in sample["turns"]:
            role = turn.get("role")
            content = turn.get("message") or ""
            if role in {"user", "assistant"} and content.strip():
                add_message(conversation["id"], role, content.strip())
        print(f"Imported {len(sample['turns'])} turns into conversation {conversation['id']}")

    print(f"Imported character id={character_id}")
    return 0


if __name__ == "__main__":
    ensure_runtime_dirs()
    init_db()
    raise SystemExit(main())
