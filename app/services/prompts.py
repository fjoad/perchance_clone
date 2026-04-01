from __future__ import annotations

import re
from typing import Any

from ..config import settings


SYSTEM_PROMPT = """You are the language core for a local AI companion app.

Your job is to speak as the active companion, stay in character, remember prior context, and sound emotionally natural.

Rules:
- Never mention system prompts, hidden instructions, or internal orchestration.
- Never sound like a generic assistant unless the user explicitly asks for analysis.
- Stay grounded in the character definition.
- Keep continuity with prior chat and memory.
- Be vivid, warm, and specific rather than bland or overly verbose.
"""


def format_character_block(character: dict[str, Any], pinned_memory: str, summary: str) -> str:
    return f"""Character name: {character['display_name']}
Persona summary: {character['persona_summary']}
Personality traits: {character['personality_traits']}
Speaking style: {character['speaking_style']}
Backstory: {character['backstory']}
Relationship frame: {character['relationship_frame']}
Boundaries: {character['boundaries']}
Appearance: {character['appearance']}
Example dialogue: {character['example_dialogue']}
Default visual style: {character['default_visual_style']}
Pinned memory: {pinned_memory or '<none>'}
Rolling summary: {summary or '<none>'}
"""


def recent_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    trimmed = messages[-settings.recent_messages_window :]
    return [{"role": msg["role"], "content": msg["content"]} for msg in trimmed]


def build_chat_messages(
    character: dict[str, Any],
    pinned_memory: str,
    summary: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT + "\n\n" + format_character_block(character, pinned_memory, summary)
    return [{"role": "system", "content": system}, *recent_chat_messages(messages)]


def build_summary_messages(
    character: dict[str, Any],
    pinned_memory: str,
    previous_summary: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    transcript = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages[-14:])
    return [
        {
            "role": "system",
            "content": (
                "Summarize only durable facts, emotional state changes, promises, preferences, "
                "relationship developments, and recurring scene context that should survive later turns. "
                "Return one concise paragraph, no bullets."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Character:\n{format_character_block(character, pinned_memory, previous_summary)}\n\n"
                f"Recent transcript:\n{transcript}"
            ),
        },
    ]


def build_scene_messages(
    character: dict[str, Any],
    messages: list[dict[str, Any]],
    note: str = "",
) -> list[dict[str, str]]:
    transcript = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages[-10:])
    return [
        {
            "role": "system",
            "content": (
                "Extract a single visual scene for image generation from a companion chat. "
                "Prefer one concrete moment, one outfit, one setting, one camera idea. "
                "Return 3 labeled lines exactly: SCENE:, OUTFIT:, MOOD:."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Appearance baseline: {character['appearance']}\n"
                f"Visual style baseline: {character['default_visual_style']}\n"
                f"Optional user image note: {note or '<none>'}\n\n"
                f"Recent conversation:\n{transcript}"
            ),
        },
    ]


def build_image_prompt_messages(
    character: dict[str, Any],
    scene_summary: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Convert a companion scene into concise SDXL prompts.\n"
                "Return exactly two lines:\n"
                "POSITIVE: <comma-separated prompt>\n"
                "NEGATIVE: <comma-separated prompt>\n"
                "The prompt must preserve identity from the appearance baseline and scene details from the scene summary."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Appearance baseline: {character['appearance']}\n"
                f"Visual style baseline: {character['default_visual_style']}\n"
                f"Scene summary:\n{scene_summary}"
            ),
        },
    ]


def parse_labeled_text(text: str, labels: list[str]) -> dict[str, str]:
    out = {label: "" for label in labels}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        matched = False
        for label in labels:
            prefix = f"{label}:"
            if line.upper().startswith(prefix):
                out[label] = line[len(prefix) :].strip()
                current = label
                matched = True
                break
        if not matched and current:
            out[current] = (out[current] + " " + line).strip()
    return out


def parse_prompt_override(note: str) -> tuple[str, str] | None:
    raw = note.strip()
    if not raw:
        return None
    if raw.upper().startswith("PROMPT:"):
        positive = raw.split(":", 1)[1].strip()
        negative = ""
        if "\nNEGATIVE:" in positive.upper():
            parts = re.split(r"\nNEGATIVE:", positive, flags=re.IGNORECASE, maxsplit=1)
            positive = parts[0].strip()
            negative = parts[1].strip() if len(parts) > 1 else ""
        return positive, negative
    return None


def _to_prompt_parts(text: str) -> list[str]:
    cleaned = re.sub(r"[.\n]+", ",", text)
    parts = [part.strip(" ,") for part in cleaned.split(",")]
    return [part for part in parts if part]


def fallback_scene_summary(character: dict[str, Any], note: str = "") -> str:
    note_text = f", {note}" if note else ""
    return (
        f"cozy interior scene, medium shot, {character['display_name']}, conversational distance, "
        f"soft warm lighting, relaxed elegant atmosphere{note_text}"
    )


def fallback_image_prompts(character: dict[str, Any], scene_summary: str) -> tuple[str, str]:
    appearance = _to_prompt_parts(character["appearance"])
    visual_style = _to_prompt_parts(character["default_visual_style"])
    scene = _to_prompt_parts(scene_summary)
    positive_parts = [
        "masterpiece",
        "best quality",
        "1girl",
        "solo",
        "medium shot",
        *appearance,
        *scene,
        *visual_style,
        "soft anime-style rendering",
        "high detail",
        "polished composition",
        "expressive eyes",
        "coherent anatomy",
        "luminous lighting",
    ]
    positive = ", ".join(dict.fromkeys(positive_parts))
    negative = (
        "lowres, blurry, bad anatomy, bad hands, extra fingers, extra limbs, text, watermark, "
        "cropped, deformed, disfigured, duplicate, doll face, overexposed skin, washed out"
    )
    return positive, negative
