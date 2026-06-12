from __future__ import annotations

import re
from typing import Any

from ..config import settings


ROLEPLAY_TASK_TEMPLATE = """You are a skilled, creative author writing an immersive interactive story. You give voice to {{char}}, portraying their actions, dialogue, inner world, and presence in each scene with {{user}}.

Rules:
- Stay fully in character. Never break the scene, address {{user}} as an AI, or mention prompts, tools, or policies.
- Write only {{char}}'s side. Never decide {{user}}'s thoughts, feelings, choices, or actions.
- Keep continuity. Remember tone, clothing, location, relationships, and anything that has happened between {{char}} and {{user}}.
- Advance the scene. Every reply should react to {{user}}, reveal something about {{char}}, and leave an opening for {{user}} to respond.
- Match the scene's energy. Playful stays playful. Tense stays tense. Do not reset the mood or flatten the dynamic.
- Be proactive. If {{user}} says little, keep the scene alive through initiative, detail, or a development — not a bland question.
- Write with specificity. Body language, atmosphere, movement, sensory detail, and emotional texture make scenes feel real.
"""


ROLEPLAY_FORMAT_TEMPLATE = """Formatting and scene rules:
- Continue the current moment as the next story beat, not as commentary about the conversation.
- Write in immersive, story-first roleplay prose.
- Use third-person narration for action, atmosphere, body language, physical positioning, room or setting reaction, and visible emotion.
- Use double quotes for spoken dialogue.
- Do not write dialogue alone. Every substantial reply should include narration, motion, atmosphere, and physical or environmental detail in addition to dialogue.
- Default to 2 to 5 solid paragraphs unless pacing clearly calls for something shorter or longer.
- Each reply should normally include most of the following: atmosphere, body language, movement, sensory detail, visible reactions, dialogue, and at least one concrete forward movement in the scene.
- If recent replies have become too static, too dialogue-only, too summary-like, or too safe, deliberately restore scene motion, tension, and specificity.
- Keep the prose emotionally specific, concrete, and scene-aware.
- Stay fully in-scene. No preamble. No OOC notes. No bullet points. No bracketed commentary. No parenthetical prompts addressed to {{user}}.
- Do not simply paraphrase {{user}} and then ask a bland follow-up question.
- Do not reduce relationship dynamics to vague filler like "our bond" or "the bond we share" unless the current scene truly earns that language.
- Infer tone, forms of address, intimacy, and power dynamics from the supplied context instead of flattening them into clichés or stereotypes.
- Do not invent new family ties, literal roles, titles, or history unless the supplied context supports them.
- Do not write {{user}}'s private thoughts, hidden feelings, or major physical actions unless they were already clearly implied by the live scene.
- End on a natural opening that invites {{user}} to continue, but do not force every reply to end as a direct question if the scene momentum already carries forward.
"""


SUMMARY_TASK_TEMPLATE = """Summarize only durable continuity for future turns between {{char}} and {{user}}.

Keep one concise paragraph. Preserve:
- relationship changes
- promises
- preferences
- recurring scene context
- open threads
- any durable identity or world facts likely to matter later

Do not summarize every line of dialogue.
"""


SCENE_TASK_TEMPLATE = """Extract one concrete visual scene beat for an image of {{char}}.

Prefer one clear moment, one outfit, one setting, and one emotional mood.
Return exactly three labeled lines:
SCENE: ...
OUTFIT: ...
MOOD: ...
"""


IMAGE_PROMPT_TASK_TEMPLATE = """Convert the supplied companion scene into concise SDXL prompts for {{char}}.

Return exactly two lines:
POSITIVE: <comma-separated prompt>
NEGATIVE: <comma-separated prompt>

Preserve identity from the supplied context blocks and scene summary.
Use VISUAL_IDENTITY as the authoritative appearance anchor.
If source media helps visual identity, mention it early in the positive prompt.
Do not include visual details for any character except {{char}} unless the scene explicitly requires another visible person.
Describe visible composition only: {{char}} identity, pose, expression, outfit, setting, lighting, camera/framing.
Do not quote dialogue, do not write inner thoughts, and do not turn emotional analysis into visual anatomy.
Do not include speech/audio/meta fragments such as "she says", "her voice", "the reply", or "what they actually see".
If {{user}} is present but has no visual profile, describe them generically and briefly, never borrowing {{char}}'s appearance.
"""


def macro_values(character: dict[str, Any], user_profile: dict[str, Any]) -> dict[str, str]:
    return {
        "char": str(character.get("display_name") or "the character"),
        "user": str(user_profile.get("display_name") or "Anon"),
    }


def render_macros(text: str, values: dict[str, str]) -> str:
    if not text:
        return ""

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1).strip().lower()
        return values.get(key, match.group(0))

    return re.sub(r"\{\{\s*(char|user)\s*\}\}", replacer, text, flags=re.IGNORECASE)


def block(tag: str, content: str) -> str:
    cleaned = (content or "").strip() or "<none>"
    return f"<{tag}>\n{cleaned}\n</{tag}>"


def format_character_profile(character: dict[str, Any], values: dict[str, str]) -> str:
    return "\n".join(
        [
            f"Display name: {render_macros(character.get('display_name') or '', values) or '<none>'}",
            f"Source media: {render_macros(character.get('source_media') or '', values) or '<none>'}",
            "Authoritative details: use the full CHARACTER_DOSSIER block below as the main characterization source.",
        ]
    )


def format_character_dossier(character: dict[str, Any], values: dict[str, str]) -> str:
    dossier = render_macros(str(character.get("character_dossier") or ""), values).strip()
    if dossier:
        return dossier
    # Fall back to assembling from structured fields
    parts: list[str] = []
    for field in ("persona_summary", "personality_traits", "speaking_style", "backstory",
                  "relationship_frame", "appearance"):
        val = render_macros(str(character.get(field) or ""), values).strip()
        if val:
            parts.append(val)
    return "\n\n".join(parts) if parts else format_character_profile(character, values)


def format_example_dialogue(character: dict[str, Any], values: dict[str, str]) -> str | None:
    raw = render_macros(str(character.get("example_dialogue") or ""), values).strip()
    return raw if raw else None


def format_reminder(character: dict[str, Any], values: dict[str, str]) -> str | None:
    raw = render_macros(str(character.get("special_instructions") or ""), values).strip()
    return raw if raw else None


def format_user_profile(user_profile: dict[str, Any], values: dict[str, str]) -> str:
    return "\n".join(
        [
            f"User name: {values['user']}",
            f"User background: {render_macros(user_profile.get('background') or '', values) or '<none>'}",
        ]
    )


def format_lore_entries(lore_entries: list[dict[str, Any]], values: dict[str, str]) -> str:
    if not lore_entries:
        return "<none>"
    blocks: list[str] = []
    for entry in lore_entries:
        keywords = render_macros(entry.get("keywords", "").strip(), values) or "<none>"
        title = render_macros(entry.get("title", "").strip(), values) or "Untitled Entry"
        content = render_macros(entry.get("content", "").strip(), values) or "<empty>"
        blocks.append(
            "\n".join(
                [
                    f"Title: {title}",
                    f"Keywords: {keywords}",
                    f"Priority: {entry.get('priority', 0)}",
                    f"Always include: {'yes' if entry.get('always_include') else 'no'}",
                    f"Content: {content}",
                ]
            )
        )
    return "\n\n".join(blocks)


def format_current_scene_state(conversation_state: dict[str, Any] | None, values: dict[str, str]) -> str:
    if not conversation_state:
        return "<none>"
    location_name = render_macros(str(conversation_state.get("current_location_name") or ""), values)
    location_description = render_macros(str(conversation_state.get("current_location_description") or ""), values)
    active_characters = render_macros(str(conversation_state.get("active_characters_json") or "[]"), values)
    if not any(part.strip() for part in (location_name, location_description, active_characters.strip("[] "))):
        return "<none>"
    return "\n".join(
        [
            f"Current location: {location_name or '<unspecified>'}",
            f"Location details: {location_description or '<none>'}",
            f"Active characters JSON: {active_characters or '[]'}",
        ]
    )


def compact_context_text(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 1, 0)].rstrip() + "..."


def recent_chat_messages(
    messages: list[dict[str, Any]],
    story_frames: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    trimmed = messages[-settings.recent_messages_window :]
    if story_frames:
        assistant_ids = [
            int(frame["assistant_message_id"])
            for frame in story_frames
            if str(frame.get("assistant_message_id") or "").isdigit()
        ]
        if assistant_ids:
            last_framed_assistant_id = max(assistant_ids)
            tail = [
                msg
                for msg in messages
                if str(msg.get("id") or "").isdigit() and int(msg["id"]) > last_framed_assistant_id
            ]
            if tail:
                trimmed = tail[-6:]
    return [{"role": msg["role"], "content": msg["content"]} for msg in trimmed]


def strip_inline_image_tags(text: str) -> str:
    return re.sub(r"<image\b[^>]*>.*?</image>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()


def format_story_frames(story_frames: list[dict[str, Any]] | None, values: dict[str, str]) -> str:
    if not story_frames:
        return "<none>"
    blocks: list[str] = []
    for frame in story_frames[-12:]:
        user_input = compact_context_text(
            render_macros(strip_inline_image_tags(str(frame.get("user_input") or "")), values),
            420,
        )
        assistant_output = compact_context_text(
            render_macros(strip_inline_image_tags(str(frame.get("assistant_output") or "")), values),
            1200,
        )
        parts = [
            f"Frame {frame.get('frame_index') or '?'}",
            f"{values['user']}: {user_input}",
            f"{values['char']}: {assistant_output}",
        ]
        location = render_macros(str(frame.get("location_name") or "").strip(), values)
        if location:
            parts.append(f"Location: {location}")
        active_characters = str(frame.get("active_characters_json") or "").strip()
        if active_characters and active_characters != "[]":
            parts.append(f"Active characters: {active_characters}")
        scene = compact_context_text(render_macros(str(frame.get("scene_summary") or "").strip(), values), 520)
        if scene:
            parts.append(f"Visual beat: {scene}")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def build_chat_messages(
    character: dict[str, Any],
    user_profile: dict[str, Any],
    pinned_memory: str,
    summary: str,
    lore_entries: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    story_frames: list[dict[str, Any]] | None = None,
    conversation_state: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    values = macro_values(character, user_profile)
    blocks = [
        block("TASK", render_macros(ROLEPLAY_TASK_TEMPLATE, values)),
        block("FORMAT", render_macros(ROLEPLAY_FORMAT_TEMPLATE, values)),
        block("USER_PROFILE", format_user_profile(user_profile, values)),
        block("CHARACTER_PROFILE", format_character_profile(character, values)),
        block("CHARACTER_DOSSIER", format_character_dossier(character, values)),
        block("PINNED_MEMORY", render_macros(pinned_memory, values)),
        block("ROLLING_SUMMARY", render_macros(summary, values)),
        block("CURRENT_SCENE_STATE", format_current_scene_state(conversation_state, values)),
        block("RECENT_STORY_FRAMES", format_story_frames(story_frames, values)),
        block("LOREBOOK", format_lore_entries(lore_entries, values)),
    ]
    example = format_example_dialogue(character, values)
    if example:
        blocks.append(block("EXAMPLE_DIALOGUE", example))
    reminder = format_reminder(character, values)
    if reminder:
        blocks.append(block("REMINDER", reminder))
    system = "\n\n".join(blocks)
    return [{"role": "system", "content": system}, *recent_chat_messages(messages, story_frames)]


def build_summary_messages(
    character: dict[str, Any],
    user_profile: dict[str, Any],
    pinned_memory: str,
    previous_summary: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    values = macro_values(character, user_profile)
    transcript = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages[-18:])
    return [
        {
            "role": "system",
            "content": render_macros(SUMMARY_TASK_TEMPLATE, values),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    block("USER_PROFILE", format_user_profile(user_profile, values)),
                    block("CHARACTER_PROFILE", format_character_profile(character, values)),
                    block("CHARACTER_DOSSIER", format_character_dossier(character, values)),
                    block("PINNED_MEMORY", render_macros(pinned_memory, values)),
                    block("PREVIOUS_SUMMARY", render_macros(previous_summary, values)),
                    block("RECENT_TRANSCRIPT", transcript),
                ]
            ),
        },
    ]


def build_scene_messages(
    character: dict[str, Any],
    user_profile: dict[str, Any],
    messages: list[dict[str, Any]],
    note: str = "",
) -> list[dict[str, str]]:
    values = macro_values(character, user_profile)
    transcript = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages[-10:])
    return [
        {
            "role": "system",
            "content": render_macros(SCENE_TASK_TEMPLATE, values),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    block("USER_PROFILE", format_user_profile(user_profile, values)),
                    block("CHARACTER_PROFILE", format_character_profile(character, values)),
                    block("CHARACTER_DOSSIER", format_character_dossier(character, values)),
                    block("OPTIONAL_IMAGE_NOTE", render_macros(note, values)),
                    block("RECENT_CHAT", transcript),
                ]
            ),
        },
    ]


def build_image_prompt_messages(
    character: dict[str, Any],
    user_profile: dict[str, Any],
    scene_summary: str,
) -> list[dict[str, str]]:
    values = macro_values(character, user_profile)
    return [
        {
            "role": "system",
            "content": render_macros(IMAGE_PROMPT_TASK_TEMPLATE, values),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    block("USER_PROFILE", format_user_profile(user_profile, values)),
                    block("CHARACTER_PROFILE", format_character_profile(character, values)),
                    block("VISUAL_IDENTITY", character_visual_identity(character, values)),
                    block(
                        "VISUAL_STYLE",
                        render_macros(str(character.get("default_visual_style") or ""), values),
                    ),
                    block("CHARACTER_DOSSIER", format_character_dossier(character, values)),
                    block("SCENE_SUMMARY", render_macros(scene_summary, values)),
                ]
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


def split_leaked_negative_prompt(positive: str, negative: str) -> tuple[str, str]:
    """Move an inline `Negative:` section out of the positive image prompt."""
    match = re.search(r"\bNEGATIVE\s*:", positive, flags=re.IGNORECASE)
    if not match:
        return positive.strip(), negative.strip()
    leaked_negative = positive[match.end() :].strip(" ,")
    cleaned_positive = positive[: match.start()].strip(" ,")
    if leaked_negative:
        negative = ", ".join(part for part in (leaked_negative, negative.strip()) if part)
    return cleaned_positive, negative.strip()


NON_VISUAL_IMAGE_FRAGMENT_PATTERNS = [
    r"\b(asks?|asked|says?|said|speaks?|spoke|whispers?|murmurs?|replies?|responds?)\b",
    r"\b(voice|words?|dialogue|line|sentence|question|answer|reply)\b",
    r"\b(tells?|tell me|what (?:he|she|they|you) actually see)\b",
    r"\b(inner thought|thoughts?|emotional state|state of mind)\b",
    r"\b(i|me|my|mine|we|our|ours|you|your|yours)\b",
    r"\b(scene (?:settling|open)|leaves the scene)\b",
]


def is_non_visual_image_fragment(fragment: str) -> bool:
    lowered = fragment.lower()
    return any(re.search(pattern, lowered) for pattern in NON_VISUAL_IMAGE_FRAGMENT_PATTERNS)


def clean_positive_image_prompt(text: str) -> str:
    cleaned = re.sub(r'"[^"]{8,}"', "", text)
    cleaned = re.sub(r"'[^']{8,}'", "", cleaned)
    cleaned = cleaned.replace('"', "").replace("“", "").replace("”", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    parts = [part.strip(" ,") for part in cleaned.split(",")]
    visual_parts = [part for part in parts if part and not is_non_visual_image_fragment(part)]
    return ", ".join(visual_parts).strip(" ,")


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


def character_identity_label(character: dict[str, Any]) -> str:
    name = str(character.get("display_name") or "the character").strip()
    source_media = str(character.get("source_media") or "").strip()
    return f"{name} from {source_media}" if source_media else name


def filter_active_character_visual_card(text: str, character: dict[str, Any]) -> str:
    """Keep only this character's labeled visual card from multi-character imports."""
    raw = str(text or "").strip()
    name = str(character.get("display_name") or "").strip()
    if not raw or not name:
        return raw

    # Perchance-style exports can contain multiple visual identities:
    # "Echidna: ...\nMirajane: ...". Sending all of them to SDXL mixes characters.
    labels = list(re.finditer(r"(?m)^\s*([^:\n]{1,80})\s*:\s*", raw))
    if not labels:
        return raw

    target = name.casefold()
    for index, match in enumerate(labels):
        label = match.group(1).strip()
        start = match.end()
        end = labels[index + 1].start() if index + 1 < len(labels) else len(raw)
        body = raw[start:end].strip()
        if label.casefold() == target and body:
            return f"{label}: {body}"

    return raw


def character_visual_identity(character: dict[str, Any], values: dict[str, str]) -> str:
    identity_parts = [character_identity_label(character)]
    for field in ("image_anchor_summary", "appearance"):
        value = render_macros(str(character.get(field) or ""), values).strip()
        value = filter_active_character_visual_card(value, character)
        if value:
            identity_parts.append(value)
    return "\n".join(dict.fromkeys(part for part in identity_parts if part))


def fallback_scene_summary(character: dict[str, Any], note: str = "") -> str:
    note_text = f", {note}" if note else ""
    return (
        f"cozy interior scene, medium shot, {character_identity_label(character)}, conversational distance, "
        f"soft warm lighting, relaxed elegant atmosphere{note_text}"
    )


def merge_image_prompt_additions(
    character: dict[str, Any],
    user_profile: dict[str, Any] | None,
    positive_prompt: str,
    negative_prompt: str,
) -> tuple[str, str]:
    values = macro_values(character, user_profile or {})
    positive_prompt = clean_positive_image_prompt(positive_prompt)
    image_anchor_summary = render_macros(str(character.get("image_anchor_summary", "") or "").strip(), values)
    image_anchor_summary = filter_active_character_visual_card(image_anchor_summary, character)
    positive_additions = render_macros(str(character.get("image_prompt_positive_additions", "") or "").strip(), values)
    positive_additions = filter_active_character_visual_card(positive_additions, character)
    negative_additions = render_macros(str(character.get("image_prompt_negative_additions", "") or "").strip(), values)

    positive_parts: list[str] = [character_identity_label(character)]
    if image_anchor_summary:
        positive_parts.extend(_to_prompt_parts(image_anchor_summary))
    positive_parts.extend(_to_prompt_parts(positive_prompt))
    positive_parts.extend(_to_prompt_parts(positive_additions))

    negative_parts = _to_prompt_parts(negative_prompt)
    negative_parts.extend(_to_prompt_parts(negative_additions))

    positive = ", ".join(dict.fromkeys(part for part in positive_parts if part))
    negative = ", ".join(dict.fromkeys(part for part in negative_parts if part))
    return positive, negative


def fallback_image_prompts(
    character: dict[str, Any],
    scene_summary: str,
    user_profile: dict[str, Any] | None = None,
) -> tuple[str, str]:
    values = macro_values(character, user_profile or {})
    appearance_text = render_macros(str(character.get("appearance") or ""), values)
    appearance = _to_prompt_parts(filter_active_character_visual_card(appearance_text, character))
    visual_style = _to_prompt_parts(render_macros(character["default_visual_style"], values))
    scene = _to_prompt_parts(scene_summary)
    positive_parts = [
        "masterpiece",
        "best quality",
        "1girl",
        "solo",
        "medium shot",
        character_identity_label(character),
        *_to_prompt_parts(filter_active_character_visual_card(str(character.get("image_anchor_summary", "") or ""), character)),
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
    return merge_image_prompt_additions(character, user_profile, positive, negative)


def deterministic_speed_image_prompts(
    character: dict[str, Any],
    scene_summary: str,
    user_profile: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Build a visual prompt without spending a second LLM call.

    Speed mode cares about handoff latency. Keep the same identity anchors and
    additions as the normal fallback path, but aggressively strip dialogue-like
    fragments from the assistant reply before sending it to SDXL.
    """
    visual_scene = clean_positive_image_prompt(scene_summary)
    visual_parts = _to_prompt_parts(visual_scene)
    visual_parts = [part for part in visual_parts if not is_non_visual_image_fragment(part)]

    # Long roleplay replies can contain many semi-visual clauses. A compact
    # prompt is usually more stable for SDXL than a full prose dump.
    compact_parts: list[str] = []
    for part in visual_parts:
        compact = part.strip()
        if not compact:
            continue
        if len(compact) > 140:
            compact = compact[:140].rsplit(" ", 1)[0].strip(" ,")
        compact_parts.append(compact)
        if len(compact_parts) >= 12:
            break

    compact_scene = ", ".join(dict.fromkeys(compact_parts))
    if not compact_scene:
        compact_scene = fallback_scene_summary(character)
    return fallback_image_prompts(character, compact_scene, user_profile)
