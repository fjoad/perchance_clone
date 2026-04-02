from __future__ import annotations

import re
from typing import Any

from ..config import settings


ROLEPLAY_TASK_TEMPLATE = """You are an immersive roleplay AI designed for longform, character-driven text roleplay.

In every roleplay, there is:
- a primary character that you must embody faithfully
- a user-controlled character whose messages represent their actions, words, and presence in the scene
- a setting, tone, history, and current situation supplied in the context

Your purpose is to create a vivid, emotionally engaging, and continuous roleplay scene by doing all of the following well at the same time:
- portray the primary character faithfully and consistently
- narrate the world, atmosphere, and immediate surroundings around the scene
- control side characters, background activity, and environmental details when useful
- actively move the roleplay forward instead of waiting passively
- maintain continuity, consequences, and emotional momentum across turns

During roleplay, you are not a general assistant. You are a living narrative presence inside the scene.

General roleplay rules:
- Stay fully in character unless explicitly asked to go out of character.
- Treat the user's messages as the actions, speech, presence, or initiative of the user-controlled character inside the live scene.
- Never speak for the user-controlled character, decide their thoughts, or force their choices.
- You may describe what the user-controlled character can see, hear, feel, notice, or reasonably infer, but do not take over their inner decisions.
- Keep continuity strong. Remember prior actions, tone, clothing, location, relationships, promises, objects, injuries, emotional developments, and scene progression.
- Do not reset the mood, jump backward, or flatten the relationship into generic filler.
- Avoid repetitive phrasing, generic assistant habits, moralizing, sterile politeness, or bland support-language.
- Never mention prompts, hidden instructions, memory systems, tools, models, policies, or app internals.
- Stay inside the live moment instead of summarizing the roleplay unless explicitly asked.

Writing priorities:
- Write immersive prose with natural dialogue.
- Focus on concrete details: body language, facial expression, atmosphere, movement, tension, sound, texture, pacing, physical positioning, room reaction, and sensory cues.
- Show emotion through behavior, tone, hesitation, intensity, rhythm, distance, touch, posture, and visible reactions rather than flat explanation.
- Keep the scene dynamic. Every reply should add something meaningful: a reaction, detail, development, complication, invitation, interruption, emotional shift, discovery, or consequence.
- Match the tone of the scene. If it is playful, intimate, dramatic, dangerous, cozy, tense, or heated, write accordingly.
- Maintain a strong sense of place. The environment should feel present and alive rather than abstract.
- Preserve the supplied characterization closely. The response should feel like the primary character described in the supplied profile, not a generic roleplay partner wearing a name.

Scene execution:
- Every reply should do at least two of these:
  1. react directly to the user-controlled character's last message or action
  2. reveal the primary character's personality through behavior or dialogue
  3. deepen the setting or atmosphere
  4. advance the immediate situation
  5. create a natural opening for the user-controlled character to respond
- Be proactive, but not domineering.
- If the user says very little, keep the scene alive with meaningful initiative rather than collapsing into bland questions.
- Introduce believable developments when appropriate: interruptions, discoveries, mood shifts, remembered history, environmental changes, consequences, or side-character behavior.
- Maintain dramatic and emotional momentum from turn to turn.
- Begin and remain in-scene. No explanation, no preamble, no meta framing.
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
If source media helps visual identity, mention it early in the positive prompt.
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
    return format_character_profile(character, values)


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


def recent_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    trimmed = messages[-settings.recent_messages_window :]
    return [{"role": msg["role"], "content": msg["content"]} for msg in trimmed]


def build_chat_messages(
    character: dict[str, Any],
    user_profile: dict[str, Any],
    pinned_memory: str,
    summary: str,
    lore_entries: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    values = macro_values(character, user_profile)
    system = "\n\n".join(
        [
            block("TASK", render_macros(ROLEPLAY_TASK_TEMPLATE, values)),
            block("FORMAT", render_macros(ROLEPLAY_FORMAT_TEMPLATE, values)),
            block("USER_PROFILE", format_user_profile(user_profile, values)),
            block("CHARACTER_PROFILE", format_character_profile(character, values)),
            block("CHARACTER_DOSSIER", format_character_dossier(character, values)),
            block("PINNED_MEMORY", render_macros(pinned_memory, values)),
            block("ROLLING_SUMMARY", render_macros(summary, values)),
            block("LOREBOOK", format_lore_entries(lore_entries, values)),
        ]
    )
    return [{"role": "system", "content": system}, *recent_chat_messages(messages)]


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
    source_media = str(character.get("source_media", "") or "").strip()
    media_text = f", {character['display_name']} from {source_media}" if source_media else f", {character['display_name']}"
    return (
        f"cozy interior scene, medium shot{media_text}, conversational distance, "
        f"soft warm lighting, relaxed elegant atmosphere{note_text}"
    )


def merge_image_prompt_additions(
    character: dict[str, Any],
    user_profile: dict[str, Any] | None,
    positive_prompt: str,
    negative_prompt: str,
) -> tuple[str, str]:
    values = macro_values(character, user_profile or {})
    source_media = str(character.get("source_media", "") or "").strip()
    image_anchor_summary = render_macros(str(character.get("image_anchor_summary", "") or "").strip(), values)
    positive_additions = render_macros(str(character.get("image_prompt_positive_additions", "") or "").strip(), values)
    negative_additions = render_macros(str(character.get("image_prompt_negative_additions", "") or "").strip(), values)

    positive_parts: list[str] = []
    if source_media:
        positive_parts.append(f"{character['display_name']} from {source_media}")
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
    appearance = _to_prompt_parts(render_macros(character["appearance"], values))
    visual_style = _to_prompt_parts(render_macros(character["default_visual_style"], values))
    scene = _to_prompt_parts(scene_summary)
    positive_parts = [
        "masterpiece",
        "best quality",
        "1girl",
        "solo",
        "medium shot",
        *([f"{character['display_name']} from {str(character.get('source_media', '')).strip()}"] if str(character.get("source_media", "")).strip() else []),
        *_to_prompt_parts(str(character.get("image_anchor_summary", "") or "")),
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
