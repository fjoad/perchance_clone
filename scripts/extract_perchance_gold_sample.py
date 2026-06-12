from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "research_gold_samples"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "sample"


def load_tables(path: Path) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        table_blobs = payload["data"]["data"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Not a recognized Perchance export JSON shape.") from exc
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in table_blobs:
        name = table.get("tableName")
        rows = table.get("rows", [])
        if isinstance(name, str) and isinstance(rows, list):
            tables[name] = rows
    return tables


def selected_message_text(row: dict[str, Any]) -> str:
    message = row.get("message")
    if isinstance(message, str) and message.strip():
        return message
    variants = row.get("variants")
    if isinstance(variants, list) and variants:
        first = variants[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for key in ("message", "text", "content"):
                value = first.get(key)
                if isinstance(value, str):
                    return value
    return ""


def write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a Perchance JSON export into a gold-sample folder.")
    parser.add_argument("input", type=Path, help="Path to Perchance JSON export.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--name", help="Optional sample slug/name.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    tables = load_tables(args.input)
    characters = tables.get("characters", [])
    threads = tables.get("threads", [])
    messages = tables.get("messages", [])
    if not characters:
        raise ValueError("No characters table rows found.")
    if not threads:
        raise ValueError("No threads table rows found.")
    if not messages:
        raise ValueError("No messages table rows found.")

    character = characters[0]
    thread = threads[0]
    character_id = character.get("id")
    thread_id = thread.get("id")
    char_name = str(character.get("name") or "character")
    sample_slug = slugify(args.name or char_name)
    out_dir = args.output_root / sample_slug
    if out_dir.exists() and not args.overwrite:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = args.output_root / f"{sample_slug}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    thread_messages = [
        row for row in messages
        if row.get("threadId") == thread_id
    ]
    thread_messages.sort(key=lambda row: row.get("order", 0))

    normalized_turns: list[dict[str, Any]] = []
    for row in thread_messages:
        row_character_id = row.get("characterId")
        role = "assistant" if row_character_id == character_id else "user"
        normalized_turns.append(
            {
                "role": role,
                "name": char_name if role == "assistant" else "user",
                "order": row.get("order"),
                "character_id": row_character_id,
                "message": selected_message_text(row),
                "message_id": row.get("id"),
                "creation_time": row.get("creationTime"),
            }
        )

    protagonist = character.get("userCharacter") if isinstance(character.get("userCharacter"), dict) else {}
    image = {
        "prefix": character.get("imagePromptPrefix", ""),
        "suffix": character.get("imagePromptSuffix", ""),
        "triggers": character.get("imagePromptTriggers", ""),
    }
    metadata = {
        "source_file": str(args.input),
        "format": "perchance-export",
        "character_name": char_name,
        "character_id": character_id,
        "thread_name": thread.get("name"),
        "thread_id": thread_id,
        "model_name": character.get("modelName") or thread.get("modelName"),
        "temperature": character.get("temperature"),
        "max_tokens_per_message": character.get("maxTokensPerMessage"),
        "message_count": len(normalized_turns),
        "assistant_message_count": sum(1 for turn in normalized_turns if turn["role"] == "assistant"),
        "user_message_count": sum(1 for turn in normalized_turns if turn["role"] == "user"),
    }

    write_text(out_dir / "character_profile.md", str(character.get("roleInstruction", "")))
    write_text(out_dir / "protagonist_profile.md", str(protagonist.get("roleInstruction", "")))
    write_text(out_dir / "reminder_note.md", str(character.get("reminderMessage", "")))
    write_text(out_dir / "general_writing_instructions.md", str(character.get("generalWritingInstructions", "")))
    write_text(out_dir / "image_prompt_prefix.txt", str(image["prefix"]))
    write_text(out_dir / "image_prompt_suffix.txt", str(image["suffix"]))
    write_text(out_dir / "image_prompt_triggers.txt", str(image["triggers"]))
    (out_dir / "turns.json").write_text(json.dumps(normalized_turns, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    reference_lines = [f"# Reference Replies: {char_name}", ""]
    for turn in normalized_turns:
        if turn["role"] == "assistant":
            reference_lines.append(f"## Assistant Turn {turn['order']}")
            reference_lines.append("")
            reference_lines.append(turn["message"])
            reference_lines.append("")
    write_text(out_dir / "reference_replies.md", "\n".join(reference_lines))

    print(json.dumps({"output_dir": str(out_dir), **metadata}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
