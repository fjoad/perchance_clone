from __future__ import annotations

import re
from typing import Any

from ..config import settings
from ..db import list_lore_entries


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "you",
    "your",
}


def split_keywords(raw: str) -> list[str]:
    if not raw.strip():
        return []
    parts = re.split(r"[,;\n]+", raw)
    return [part.strip() for part in parts if part.strip()]


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9']+", text.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def _lore_haystack(character: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    recent_window = messages[-settings.lore_recent_turns :]
    conversation_bits = "\n".join(message["content"] for message in recent_window)
    character_bits = "\n".join(
        [
            character.get("display_name", ""),
            character.get("persona_summary", ""),
            character.get("personality_traits", ""),
            character.get("backstory", ""),
            character.get("relationship_frame", ""),
        ]
    )
    return f"{character_bits}\n{conversation_bits}".lower()


def retrieve_lore_entries(character: dict[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_entries = list_lore_entries(character["id"], include_global=True, enabled_only=True)
    if not all_entries:
        return []

    haystack = _lore_haystack(character, messages)
    haystack_tokens = _tokenize(haystack)
    scored: list[tuple[int, int, int, dict[str, Any]]] = []

    for entry in all_entries:
        always_include = int(entry.get("always_include") or 0)
        priority = int(entry.get("priority") or 0)
        keyword_hits = 0
        for keyword in split_keywords(entry.get("keywords", "")):
            lowered = keyword.lower()
            if not lowered:
                continue
            if " " in lowered:
                if lowered in haystack:
                    keyword_hits += 2
            elif lowered in haystack_tokens:
                keyword_hits += 1

        if not always_include and keyword_hits <= 0:
            continue
        scored.append((always_include, keyword_hits, priority, entry))

    scored.sort(key=lambda item: (item[0], item[1], item[2], int(item[3]["id"])), reverse=True)
    return [entry for _, _, _, entry in scored[: settings.lore_max_entries]]
