"""
Import a character from a plain-text file into the app database.

File format (see characters/ahri.txt for a full example):

    [NAME]
    Ahri

    [SLUG]
    ahri

    [SOURCE_MEDIA]
    League of Legends (custom)

    [DOSSIER]
    Paste the full character description here.
    Can be multiple paragraphs.

    [REMINDER]
    Paste the character reminder note here (shown to model every turn).
    Keep under 200 words.

    [EXAMPLE_DIALOGUE]
    {{user}}: "You know you're making it hard to focus."
    {{char}}: Ahri smiles slowly...

    [APPEARANCE]
    Short visual description for image prompts.

    [IMAGE_POSITIVE]
    comma, separated, positive, prompt, additions

    [IMAGE_NEGATIVE]
    comma, separated, negative, prompt, additions

    [PINNED_MEMORY]
    One paragraph of persistent context injected every turn.

Sections not present are left empty.
All sections support {{char}} and {{user}} macros.

Usage:
    python scripts/import_character.py characters/ahri.txt
    python scripts/import_character.py characters/ahri.txt --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import ensure_runtime_dirs
from app.db import (
    get_character_by_slug,
    init_db,
    replace_pinned_memory,
    save_character,
    slug_exists,
)


SECTION_RE = re.compile(r"^\[([A-Z_]+)\]\s*$", re.MULTILINE)


def parse_file(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(text))
    for i, match in enumerate(matches):
        key = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[key] = text[start:end].strip()
    return sections


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a character from a txt file.")
    parser.add_argument("file", help="Path to the character txt file.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print without writing to DB.")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    sections = parse_file(path)

    name = sections.get("NAME", "").strip()
    if not name:
        print("ERROR: [NAME] section is required.")
        return 1

    slug_raw = sections.get("SLUG", "").strip() or slugify(name)
    existing = get_character_by_slug(slug_raw)
    current_id = int(existing["id"]) if existing else None
    slug = unique_slug(slug_raw, current_id=current_id)

    payload: dict = {
        "id": current_id,
        "slug": slug,
        "display_name": name,
        "source_media": sections.get("SOURCE_MEDIA", ""),
        "character_dossier": sections.get("DOSSIER", ""),
        "special_instructions": sections.get("REMINDER", ""),
        "example_dialogue": sections.get("EXAMPLE_DIALOGUE", ""),
        "appearance": sections.get("APPEARANCE", ""),
        "image_prompt_positive_additions": sections.get("IMAGE_POSITIVE", ""),
        "image_prompt_negative_additions": sections.get("IMAGE_NEGATIVE", ""),
        # Fields not in txt format — preserved if updating, empty if new
        "persona_summary": existing.get("persona_summary", "") if existing else "",
        "personality_traits": existing.get("personality_traits", "") if existing else "",
        "speaking_style": existing.get("speaking_style", "") if existing else "",
        "backstory": existing.get("backstory", "") if existing else "",
        "relationship_frame": existing.get("relationship_frame", "") if existing else "",
        "boundaries": existing.get("boundaries", "") if existing else "",
        "default_visual_style": existing.get("default_visual_style", "") if existing else "",
        "image_anchor_summary": existing.get("image_anchor_summary", "") if existing else "",
        "is_active": True,
    }

    pinned_memory = sections.get("PINNED_MEMORY", "")

    if args.dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN — would {'update' if current_id else 'create'} character:")
        print(f"{'='*60}")
        for k, v in payload.items():
            preview = (v[:80] + "...") if isinstance(v, str) and len(v) > 80 else v
            print(f"  {k}: {preview!r}")
        if pinned_memory:
            print(f"  pinned_memory: {pinned_memory[:80]!r}")
        print()
        return 0

    character_id = save_character(payload)
    if pinned_memory:
        replace_pinned_memory(character_id, pinned_memory)

    action = "Updated" if current_id else "Created"
    print(f"{action} character '{name}' (slug={slug}, id={character_id})")
    return 0


if __name__ == "__main__":
    ensure_runtime_dirs()
    init_db()
    raise SystemExit(main())
