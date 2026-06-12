"""
Run a production-like roleplay -> image flow with A1111 and Ollama.

Flow:
  user1 -> assistant1 -> scene/image prompt/image1
  user2 -> assistant2 -> scene/image prompt/image2

This uses the app's prompt-building code and a full character txt card, but
keeps the benchmark isolated from the web app/database.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from f_only_env import (
    F_OLLAMA_EXE,
    F_OLLAMA_MODELS,
    assert_f_only_env,
    configure_f_only_env,
)

configure_f_only_env()
assert_f_only_env()

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services import prompts  # noqa: E402

OUT_DIR = ROOT_DIR / "outputs" / "diags"
OLLAMA_BASE = "http://localhost:11434"
DEFAULT_A1111_BASE = "http://127.0.0.1:7860"
DEFAULT_TEXT_MODEL = "hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M"
DEFAULT_CHECKPOINT = "novaAnimeXL_ilV120.safetensors"
SECTION_RE = re.compile(r"^\[([A-Z_]+)\]\s*$", re.MULTILINE)

DEFAULT_USER_MESSAGES = [
    (
        "I step through the doorway with rain still clinging to my coat, shoulders sagging "
        "from the road. \"Atago... I think I'm completely exhausted.\""
    ),
    (
        "I accept the tea with both hands and sink into the warmth of the room. "
        "\"I'm tired, but... I'm happy I made it here.\""
    ),
]

HARDENED_IMAGE_NEGATIVE = (
    "separate animal, pet, animal companion, black cat, cat sitting beside her, "
    "extra character, duplicate character, detached tail, extra tail, tail not attached to body, "
    "all fours, crawling, bent over, pin-up pose, provocative pose"
)

STYLE_ANCHOR = (
    "painterly anime artwork, masterpiece, best quality, fine details, soft luminous highlights, "
    "warm ambient lighting, subtle cherry blossom motifs, visual novel CG, solo character, medium shot"
)

BASE_NEGATIVE = (
    "lowres, blurry, bad anatomy, bad hands, extra fingers, extra limbs, text, watermark, "
    "cropped, deformed, disfigured, duplicate, extra character, multiple girls, two girls, "
    "detached tail, wrong ears, wrong tail color, separate animal, black cat"
)

STOP_MARKERS = [
    "\nUSER:",
    "\nUser:",
    "\nANON:",
    "\nAnon:",
    "\n{{user}}:",
    "\n### USER",
    "\n### User",
    "\n### END",
    "<END_TURN>",
]

VISUAL_FIELD_KEYS = [
    "setting",
    "outfit",
    "pose",
    "expression",
    "props",
    "camera",
    "lighting",
    "mood",
]


class Tee:
    def __init__(self, path: Path) -> None:
        self.file = path.open("w", encoding="utf-8")
        self.stdout = sys.stdout

    def write(self, data: str) -> int:
        self.stdout.write(data)
        self.file.write(data)
        return len(data)

    def flush(self) -> None:
        self.stdout.flush()
        self.file.flush()

    def close(self) -> None:
        sys.stdout = self.stdout
        self.file.close()


class MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def bytes_gib(value: int | float | None) -> float:
    return float(value or 0) / (1024**3)


def ram_snapshot() -> dict[str, float]:
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    total = bytes_gib(status.ullTotalPhys)
    available = bytes_gib(status.ullAvailPhys)
    commit_limit = bytes_gib(status.ullTotalPageFile)
    commit_available = bytes_gib(status.ullAvailPageFile)
    return {
        "ram_total_gib": total,
        "ram_available_gib": available,
        "ram_used_gib": max(total - available, 0.0),
        "ram_used_percent": float(status.dwMemoryLoad),
        "commit_limit_gib": commit_limit,
        "commit_available_gib": commit_available,
        "commit_used_gib": max(commit_limit - commit_available, 0.0),
    }


def vram_snapshot() -> tuple[float, float]:
    out = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    ).strip()
    used, free = [int(part.strip()) for part in out.split(",")]
    return used / 1024, free / 1024


def resource_snapshot(label: str) -> dict[str, Any]:
    used, free = vram_snapshot()
    return {
        "label": label,
        "time": datetime.now().isoformat(timespec="seconds"),
        "vram_used_gib": used,
        "vram_free_gib": free,
        **ram_snapshot(),
    }


def print_resources(snapshot: dict[str, Any]) -> None:
    print(
        f"[resources] {snapshot['label']}: "
        f"vram_used={snapshot['vram_used_gib']:.2f} GiB "
        f"vram_free={snapshot['vram_free_gib']:.2f} GiB "
        f"ram_used={snapshot['ram_used_gib']:.2f} GiB "
        f"commit_used={snapshot['commit_used_gib']:.2f} GiB"
    )


def post_json(url: str, payload: dict[str, Any], *, timeout: float = 3600) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body) if body.strip() else {}


def get_json(url: str, *, timeout: float = 10) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def api_get(path: str, *, timeout: float = 10) -> dict[str, Any]:
    return get_json(f"{OLLAMA_BASE}{path}", timeout=timeout)


def api_post(path: str, payload: dict[str, Any], *, timeout: float = 60) -> dict[str, Any]:
    return post_json(f"{OLLAMA_BASE}{path}", payload, timeout=timeout)


def ensure_ollama() -> subprocess.Popen | None:
    try:
        version = api_get("/api/version", timeout=2).get("version")
        print(f"[ollama] existing server: {version}")
        return None
    except Exception:
        pass
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = str(F_OLLAMA_MODELS)
    env["OLLAMA_FLASH_ATTENTION"] = "1"
    env["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
    env["OLLAMA_NUM_PARALLEL"] = "1"
    env["OLLAMA_MAX_LOADED_MODELS"] = "1"
    print(f"[ollama] starting {F_OLLAMA_EXE}")
    proc = subprocess.Popen(
        [str(F_OLLAMA_EXE), "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(45):
        try:
            version = api_get("/api/version", timeout=2).get("version")
            print(f"[ollama] started server: {version}")
            return proc
        except Exception:
            time.sleep(1)
    raise RuntimeError("Ollama did not become ready within 45 seconds.")


def model_aliases(model: str) -> set[str]:
    aliases = {model}
    if ":" not in model:
        aliases.add(model + ":latest")
    if model.endswith(":latest"):
        aliases.add(model[:-7])
    aliases.add(model.split(":", 1)[0])
    return aliases


def ollama_ps_entry(model: str) -> dict[str, Any] | None:
    aliases = model_aliases(model)
    for item in api_get("/api/ps", timeout=10).get("models", []):
        names = {item.get("name", ""), item.get("model", "")}
        names |= {name[:-7] for name in names if name.endswith(":latest")}
        if aliases & names:
            size = item.get("size") or 0
            vram = item.get("size_vram") or 0
            item["size_gib"] = bytes_gib(size)
            item["size_vram_gib"] = bytes_gib(vram)
            item["size_cpu_gib"] = bytes_gib(max(size - vram, 0))
            return item
    return None


def unload_model(model: str) -> None:
    try:
        api_post("/api/generate", {"model": model, "keep_alive": 0, "stream": False}, timeout=30)
    except Exception as exc:
        print(f"[unload warning] {model}: {exc}")


def parse_character_file(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(text))
    for i, match in enumerate(matches):
        key = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[key] = text[start:end].strip()

    name = sections.get("NAME", "").strip() or path.stem.title()
    character = {
        "id": 0,
        "slug": sections.get("SLUG", path.stem).strip() or path.stem,
        "display_name": name,
        "source_media": sections.get("SOURCE_MEDIA", ""),
        "character_dossier": sections.get("DOSSIER", ""),
        "special_instructions": sections.get("REMINDER", ""),
        "example_dialogue": sections.get("EXAMPLE_DIALOGUE", ""),
        "appearance": sections.get("APPEARANCE", ""),
        "image_prompt_positive_additions": sections.get("IMAGE_POSITIVE", ""),
        "image_prompt_negative_additions": sections.get("IMAGE_NEGATIVE", ""),
        "persona_summary": "",
        "personality_traits": "",
        "speaking_style": "",
        "backstory": "",
        "relationship_frame": "",
        "boundaries": "",
        "default_visual_style": sections.get("IMAGE_POSITIVE", ""),
        "image_anchor_summary": sections.get("APPEARANCE", ""),
    }
    return character, sections.get("PINNED_MEMORY", ""), sections


def render_macros(text: str, character_name: str, user_name: str) -> str:
    return (
        text.replace("{{char}}", character_name)
        .replace("{{Char}}", character_name)
        .replace("{{CHAR}}", character_name)
        .replace("{{user}}", user_name)
        .replace("{{User}}", user_name)
        .replace("{{USER}}", user_name)
    )


def prompt_block(name: str, content: str) -> str:
    cleaned = content.strip() if content and content.strip() else "<none>"
    return f"<{name}>\n{cleaned}\n</{name}>"


def build_direct_vn_v2_messages(
    sections: dict[str, str],
    user_profile: dict[str, Any],
    pinned_memory: str,
    conversation: list[dict[str, Any]],
) -> list[dict[str, str]]:
    char_name = sections.get("NAME", "").strip() or "the character"
    user_name = str(user_profile.get("display_name") or "Anon")
    source = sections.get("SOURCE_MEDIA", "").strip()
    dossier = render_macros(sections.get("DOSSIER", ""), char_name, user_name)
    reminder = render_macros(sections.get("REMINDER", ""), char_name, user_name)
    example = render_macros(sections.get("EXAMPLE_DIALOGUE", ""), char_name, user_name)
    pinned = render_macros(pinned_memory, char_name, user_name)
    user_background = render_macros(str(user_profile.get("background") or ""), char_name, user_name)

    task = (
        f"You are {char_name} from {source}, present inside an interactive visual novel scene with {user_name}. "
        f"Write {char_name}'s next turn only: visible actions, sensory atmosphere, emotional texture, and spoken dialogue. "
        "Use vivid story prose, but keep the camera anchored on what the character does and says right now."
    )
    turn_contract = (
        f"Write exactly one plain-prose assistant turn for {char_name}. "
        f"Use third-person narration for {char_name}'s visible actions and double quotes for spoken dialogue. "
        f"Never write {user_name}'s next dialogue, thoughts, choices, or actions. "
        "No markdown, bullets, labels, OOC notes, or analysis. "
        f"{char_name} can offer help, prepare the room, hold out a towel, set tea or food nearby, gesture, invite, "
        f"ask permission, react, and make space for {user_name} to act. "
        f"If support would affect {user_name}'s body, clothing, position, or choices, {char_name} asks or offers instead "
        "of completing the action. "
        "Prefer 2 to 4 paragraphs with a natural final beat that invites continuation. "
        "<END_TURN> is a stop marker, not text to print."
    )
    system = "\n\n".join(
        [
            prompt_block("TASK", task),
            prompt_block("TURN_CONTRACT", turn_contract),
            prompt_block("USER_PROFILE", f"Name: {user_name}\nBackground: {user_background}"),
            prompt_block("CHARACTER_DOSSIER", dossier),
            prompt_block("PINNED_MEMORY", pinned),
            prompt_block("EXAMPLE_DIALOGUE", example),
            prompt_block("REMINDER", reminder),
        ]
    )
    return [{"role": "system", "content": system}, *[
        {"role": msg["role"], "content": msg["content"]} for msg in conversation
    ]]


def truncate_user_continuation(text: str, user_name: str) -> tuple[str, bool, str | None]:
    patterns = [
        rf"\n\s*{re.escape(user_name)}\s*:",
        r"\n\s*User\s*:",
        r"\n\s*\{\{\s*user\s*\}\}\s*:",
        r"\n\s*I\s+(?:pause|step|accept|reply|say|ask|murmur|whisper|think|feel|decide)\b",
        r"\n\s*The\s+.*?\bI\s+should\b",
    ]
    first: tuple[int, str] | None = None
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match and (first is None or match.start() < first[0]):
            first = (match.start(), pattern)
    if first is None:
        return text.strip(), False, None
    return text[: first[0]].strip(), True, first[1]


def generate_chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    num_predict: int,
    json_mode: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "num_gpu": 99,
            "temperature": 0.9,
            "top_p": 0.94,
            "repeat_penalty": 1.03,
            "num_predict": num_predict,
            "stop": STOP_MARKERS,
        },
    }
    if json_mode:
        payload["format"] = "json"
    started = time.perf_counter()
    result = api_post("/api/chat", payload, timeout=1200)
    result["wall_s"] = time.perf_counter() - started
    return result


def text_metrics(result: dict[str, Any]) -> dict[str, Any]:
    output_tokens = int(result.get("eval_count") or 0)
    eval_ns = int(result.get("eval_duration") or 1)
    prompt_tokens = int(result.get("prompt_eval_count") or 0)
    prompt_ns = int(result.get("prompt_eval_duration") or 1)
    return {
        "output_tokens": output_tokens,
        "output_tps": output_tokens / (eval_ns / 1e9) if eval_ns else 0.0,
        "prompt_tokens": prompt_tokens,
        "prompt_tps": prompt_tokens / (prompt_ns / 1e9) if prompt_ns else 0.0,
        "load_s": int(result.get("load_duration") or 0) / 1e9,
        "wall_s": result.get("wall_s") or 0.0,
    }


def a1111_ready(base_url: str) -> dict[str, Any]:
    try:
        return get_json(f"{base_url.rstrip('/')}/sdapi/v1/options", timeout=5)
    except Exception as exc:
        raise RuntimeError(
            f"A1111 is not reachable at {base_url}. Start it with --api first. Error: {exc}"
        ) from exc


def set_a1111_options(base_url: str, checkpoint: str, clip_skip: int) -> None:
    options: dict[str, Any] = {"CLIP_stop_at_last_layers": clip_skip}
    if checkpoint:
        options["sd_model_checkpoint"] = checkpoint
    post_json(f"{base_url.rstrip('/')}/sdapi/v1/options", options, timeout=120)


def parse_labeled_prompt(raw: str, character: dict[str, Any], user_profile: dict[str, Any], scene: str) -> tuple[str, str]:
    parsed = prompts.parse_labeled_text(raw, ["POSITIVE", "NEGATIVE"])
    positive = parsed["POSITIVE"].strip()
    negative = parsed["NEGATIVE"].strip()
    if not positive:
        positive, negative = prompts.fallback_image_prompts(character, scene, user_profile)
    else:
        positive, negative = prompts.merge_image_prompt_additions(
            character,
            user_profile,
            positive,
            negative or prompts.fallback_image_prompts(character, scene, user_profile)[1],
        )
    negative = ", ".join(part for part in [negative, HARDENED_IMAGE_NEGATIVE] if part)
    return positive, negative


def clean_prompt_part(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"^\s*[-*]\s*", "", text)
    return text.strip(" ,")


def cap_text(text: str, limit: int = 420) -> str:
    text = clean_prompt_part(text)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].strip(" ,.;") + "."


def comma_dedupe(parts: list[str]) -> str:
    seen: set[str] = set()
    kept: list[str] = []
    for part in parts:
        for chunk in str(part or "").split(","):
            cleaned = clean_prompt_part(chunk)
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                kept.append(cleaned)
    return ", ".join(kept)


def deterministic_image_prompts(character: dict[str, Any], sections: dict[str, str], scene: str) -> tuple[str, str]:
    name = str(character.get("display_name") or sections.get("NAME") or "character").strip()
    source = str(character.get("source_media") or sections.get("SOURCE_MEDIA") or "").strip()
    identity = f"{name} from {source}" if source else name
    appearance = clean_prompt_part(str(character.get("appearance") or sections.get("APPEARANCE") or ""))
    positive_add = clean_prompt_part(
        str(character.get("image_prompt_positive_additions") or sections.get("IMAGE_POSITIVE") or "")
    )
    negative_add = clean_prompt_part(
        str(character.get("image_prompt_negative_additions") or sections.get("IMAGE_NEGATIVE") or "")
    )
    positive = comma_dedupe(
        [
            identity,
            appearance,
            "1girl, solo, no other people visible, visual novel still, medium shot",
            cap_text(scene),
            positive_add,
            STYLE_ANCHOR,
        ]
    )
    negative = comma_dedupe([negative_add, BASE_NEGATIVE, HARDENED_IMAGE_NEGATIVE])
    return positive, negative


def parse_json_image_prompt(raw: str, character: dict[str, Any], user_profile: dict[str, Any], scene: str) -> tuple[str, str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return parse_labeled_prompt(raw, character, user_profile, scene)
    positive = clean_prompt_part(str(parsed.get("positive") or ""))
    negative = clean_prompt_part(str(parsed.get("negative") or ""))
    if not positive:
        return prompts.fallback_image_prompts(character, scene, user_profile)
    positive, negative = prompts.merge_image_prompt_additions(
        character,
        user_profile,
        positive,
        negative or prompts.fallback_image_prompts(character, scene, user_profile)[1],
    )
    negative = comma_dedupe([negative, HARDENED_IMAGE_NEGATIVE])
    return positive, negative


def build_strict_json_image_messages(character: dict[str, Any], user_profile: dict[str, Any], scene: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You write SDXL prompts for one visual-novel still.\n"
                "Return only valid JSON with exactly these keys: positive, negative.\n"
                "The positive prompt must be comma-separated SDXL tags/fragments, not prose or bullets.\n"
                "Show the named character only. Do not make the user/protagonist visible.\n"
                "Do not put negative concepts in positive. Do not include labels inside values."
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    prompt_block("CHARACTER_NAME", str(character.get("display_name") or "")),
                    prompt_block("SOURCE_MEDIA", str(character.get("source_media") or "")),
                    prompt_block("APPEARANCE", str(character.get("appearance") or "")),
                    prompt_block("STYLE_ADDENDUM", str(character.get("image_prompt_positive_additions") or "")),
                    prompt_block("NEGATIVE_ADDENDUM", str(character.get("image_prompt_negative_additions") or "")),
                    prompt_block("SCENE_SUMMARY", scene),
                    prompt_block(
                        "REQUIREMENTS",
                        "solo character, no Anon visible, no second girl, no separate animal, visual novel CG",
                    ),
                ]
            ),
        },
    ]


def build_visual_fields_messages(
    character: dict[str, Any],
    user_profile: dict[str, Any],
    assistant_text: str,
    scene: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Extract safe visual fields for one solo-character visual novel CG.\n"
                "Return only valid JSON with exactly these string keys: "
                + ", ".join(VISUAL_FIELD_KEYS)
                + ".\n"
                "The image must show only the named character, not the user/protagonist.\n"
                "Translate user-contact actions into camera-safe character-only visuals. "
                "For example, if she touches or helps the user, render her facing the viewer, "
                "holding an object, reaching gently toward camera, or standing nearby.\n"
                "Do not include the words user, Anon, traveler, viewer, protagonist, he, she, they, or them.\n"
                "Do not include sexualized pin-up poses, all-fours poses, crawling, or bent-over poses.\n"
                "Keep each field concise and imageable."
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    prompt_block("CHARACTER_NAME", str(character.get("display_name") or "")),
                    prompt_block("SOURCE_MEDIA", str(character.get("source_media") or "")),
                    prompt_block("APPEARANCE", str(character.get("appearance") or "")),
                    prompt_block("ASSISTANT_TEXT", assistant_text),
                    prompt_block("SCENE_SUMMARY", scene),
                    prompt_block(
                        "OUTPUT_EXAMPLE",
                        json.dumps(
                            {
                                "setting": "warm traditional room with tatami mats",
                                "outfit": "white officer uniform",
                                "pose": "standing at conversational distance, one hand near her chest",
                                "expression": "soft caring smile",
                                "props": "steaming tea cup on a low table",
                                "camera": "medium shot, solo character",
                                "lighting": "golden candlelight",
                                "mood": "cozy, protective, intimate",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ]
            ),
        },
    ]


def sanitize_visual_field(text: str) -> str:
    text = clean_prompt_part(text)
    text = re.sub(
        r"\b(?:anon|user|traveler|protagonist|viewer|master|commander|he|she|they|them|their|him|her)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip(" ,.;")
    return text


def normalize_pose_field(text: str) -> str:
    text = sanitize_visual_field(text)
    risky = re.compile(
        r"\b(?:leaning|bent|bending|kneeling|crawling|all[- ]?fours|lying|reclining|pin[- ]?up|on knees)\b",
        flags=re.IGNORECASE,
    )
    if risky.search(text):
        return "standing at conversational distance, relaxed elegant posture"
    return text


def parse_visual_fields(raw: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    fields: dict[str, str] = {}
    for key in VISUAL_FIELD_KEYS:
        value = str(parsed.get(key) or "")
        fields[key] = normalize_pose_field(value) if key == "pose" else sanitize_visual_field(value)
    return fields


def visual_fields_image_prompts(
    character: dict[str, Any],
    sections: dict[str, str],
    fields: dict[str, str],
    fallback_scene: str,
) -> tuple[str, str]:
    if not any(fields.values()):
        return deterministic_image_prompts(character, sections, fallback_scene)

    name = str(character.get("display_name") or sections.get("NAME") or "character").strip()
    source = str(character.get("source_media") or sections.get("SOURCE_MEDIA") or "").strip()
    identity = f"{name} from {source}" if source else name
    appearance = clean_prompt_part(str(character.get("appearance") or sections.get("APPEARANCE") or ""))
    positive_add = clean_prompt_part(
        str(character.get("image_prompt_positive_additions") or sections.get("IMAGE_POSITIVE") or "")
    )
    negative_add = clean_prompt_part(
        str(character.get("image_prompt_negative_additions") or sections.get("IMAGE_NEGATIVE") or "")
    )
    field_prompt = comma_dedupe(
        [
            fields.get("setting", ""),
            fields.get("outfit", ""),
            fields.get("pose", ""),
            fields.get("expression", ""),
            fields.get("props", ""),
            fields.get("camera", ""),
            fields.get("lighting", ""),
            fields.get("mood", ""),
        ]
    )
    positive = comma_dedupe(
        [
            identity,
            appearance,
            "1girl, solo, no other people visible, visual novel still, medium shot",
            field_prompt,
            positive_add,
            STYLE_ANCHOR,
        ]
    )
    negative = comma_dedupe([negative_add, BASE_NEGATIVE, HARDENED_IMAGE_NEGATIVE])
    return positive, negative


def generate_image(
    base_url: str,
    run_dir: Path,
    label: str,
    positive: str,
    negative: str,
    args: argparse.Namespace,
    seed: int,
) -> dict[str, Any]:
    payload = {
        "prompt": positive,
        "negative_prompt": negative,
        "steps": args.steps,
        "cfg_scale": args.cfg,
        "width": args.width,
        "height": args.height,
        "seed": seed,
        "sampler_name": args.sampler_name,
        "scheduler": args.scheduler,
        "enable_hr": True,
        "hr_scale": args.hr_scale,
        "hr_upscaler": args.hr_upscaler,
        "hr_second_pass_steps": args.hr_second_pass_steps,
        "denoising_strength": args.denoise,
        "save_images": False,
        "send_images": True,
    }
    before = resource_snapshot(f"before {label} image")
    print_resources(before)
    started = time.perf_counter()
    response = post_json(f"{base_url.rstrip('/')}/sdapi/v1/txt2img", payload, timeout=3600)
    elapsed = time.perf_counter() - started
    after = resource_snapshot(f"after {label} image")
    print_resources(after)
    images = response.get("images") or []
    if not images:
        raise RuntimeError("A1111 returned no images.")
    image_path = run_dir / f"{run_dir.name}_{label}_image.png"
    image_path.write_bytes(base64.b64decode(images[0]))
    settings_path = run_dir / f"{run_dir.name}_{label}_image_settings.json"
    settings_path.write_text(json.dumps({"payload": payload, "info": response.get("info", "")}, indent=2), encoding="utf-8")
    print(f"[image] {label} elapsed={elapsed:.2f}s path={image_path}")
    return {
        "kind": "image",
        "label": label,
        "elapsed_s": elapsed,
        "image_path": str(image_path),
        "settings_path": str(settings_path),
        "resources_before": before,
        "resources_after": after,
        "payload": payload,
    }


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"[save] {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run production-like roleplay + A1111 image flow.")
    parser.add_argument("--character-file", default=str(ROOT_DIR / "characters" / "atago.txt"))
    parser.add_argument("--base-url", default=DEFAULT_A1111_BASE)
    parser.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--checkpoint-name", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--prompt-style", choices=["app_current", "direct_vn_v2"], default="app_current")
    parser.add_argument(
        "--image-prompt-strategy",
        choices=["current_labeled", "strict_json", "deterministic_template", "visual_fields_json"],
        default="current_labeled",
    )
    parser.add_argument("--user-name", default="Anon")
    parser.add_argument("--user-background", default="A tired traveler arriving at Atago's home after a long journey.")
    parser.add_argument("--user-message", action="append", dest="user_messages")
    parser.add_argument("--num-predict", type=int, default=520)
    parser.add_argument("--image-prompt-tokens", type=int, default=260)
    parser.add_argument("--scene-tokens", type=int, default=180)
    parser.add_argument("--width", type=int, default=704)
    parser.add_argument("--height", type=int, default=704)
    parser.add_argument("--hr-scale", type=float, default=2.0)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--hr-second-pass-steps", type=int, default=20)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--denoise", type=float, default=0.7)
    parser.add_argument("--sampler-name", default="DPM++ 2M")
    parser.add_argument("--scheduler", default="Automatic")
    parser.add_argument("--hr-upscaler", default="Latent")
    parser.add_argument("--clip-skip", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / f"production_flow_a1111_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.txt"
    manifest_path = run_dir / "manifest.json"
    tee = Tee(report_path)
    sys.stdout = tee
    started_ollama: subprocess.Popen | None = None
    manifest: dict[str, Any] = {
        "run_dir": str(run_dir),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "args": vars(args),
        "initial_resources": resource_snapshot("experiment start"),
        "turns": [],
    }
    try:
        print(f"[run dir] {run_dir}")
        character, pinned_memory, sections = parse_character_file(Path(args.character_file))
        user_profile = {
            "display_name": args.user_name,
            "background": args.user_background,
        }
        user_messages = args.user_messages or DEFAULT_USER_MESSAGES
        if len(user_messages) < 2:
            raise RuntimeError("At least two --user-message values are required.")

        write_text(run_dir / "character_card.txt", Path(args.character_file).read_text(encoding="utf-8"))
        write_text(run_dir / "pinned_memory.txt", pinned_memory)
        write_text(run_dir / "user_profile.json", json.dumps(user_profile, indent=2))

        print(f"[a1111] checking {args.base_url}")
        options = a1111_ready(args.base_url)
        print(f"[a1111] ready current checkpoint={options.get('sd_model_checkpoint')}")
        set_a1111_options(args.base_url, args.checkpoint_name, args.clip_skip)
        started_ollama = ensure_ollama()
        unload_model(args.text_model)

        conversation: list[dict[str, Any]] = []
        for turn_index, user_text in enumerate(user_messages[:2], start=1):
            label = f"turn{turn_index}"
            conversation.append({"role": "user", "content": user_text})
            write_text(run_dir / f"{label}_user.txt", user_text)

            if args.prompt_style == "direct_vn_v2":
                chat_messages = build_direct_vn_v2_messages(
                    sections,
                    user_profile,
                    pinned_memory,
                    conversation,
                )
            else:
                chat_messages = prompts.build_chat_messages(
                    character,
                    user_profile,
                    pinned_memory,
                    summary="",
                    lore_entries=[],
                    messages=conversation,
                )
            write_text(run_dir / f"{label}_chat_messages.json", json.dumps(chat_messages, indent=2))
            before_text = resource_snapshot(f"before {label} text")
            print_resources(before_text)
            text_result = generate_chat(args.text_model, chat_messages, num_predict=args.num_predict)
            text_metrics_data = text_metrics(text_result)
            split = ollama_ps_entry(args.text_model)
            after_text = resource_snapshot(f"after {label} text")
            print_resources(after_text)
            assistant_raw = (text_result.get("message") or {}).get("content", "").strip()
            assistant_text, was_truncated, truncate_pattern = truncate_user_continuation(
                assistant_raw,
                str(user_profile.get("display_name") or "Anon"),
            )
            conversation.append({"role": "assistant", "content": assistant_text})
            write_text(run_dir / f"{label}_assistant_raw.txt", assistant_raw)
            write_text(run_dir / f"{label}_assistant.txt", assistant_text)
            print(f"[text] {label} wall={text_metrics_data['wall_s']:.2f}s tok_s={text_metrics_data['output_tps']:.1f}")
            if was_truncated:
                print(f"[text] {label} truncated continuation via pattern: {truncate_pattern}")
            print(assistant_text)

            scene_messages = prompts.build_scene_messages(character, user_profile, conversation)
            write_text(run_dir / f"{label}_scene_messages.json", json.dumps(scene_messages, indent=2))
            scene_result = generate_chat(args.text_model, scene_messages, num_predict=args.scene_tokens)
            scene_metrics = text_metrics(scene_result)
            scene_raw = (scene_result.get("message") or {}).get("content", "").strip()
            parsed_scene = prompts.parse_labeled_text(scene_raw, ["SCENE", "OUTFIT", "MOOD"])
            scene_summary = ". ".join(part for part in parsed_scene.values() if part).strip() or prompts.fallback_scene_summary(character)
            write_text(run_dir / f"{label}_scene_raw.txt", scene_raw)
            write_text(run_dir / f"{label}_scene_summary.txt", scene_summary)
            print(f"[scene] {label} wall={scene_metrics['wall_s']:.2f}s")
            print(scene_summary)

            if args.image_prompt_strategy == "deterministic_template":
                image_prompt_messages = []
                image_prompt_raw = "<deterministic_template>"
                visual_fields: dict[str, str] | None = None
                image_prompt_metrics = {
                    "output_tokens": 0,
                    "output_tps": 0.0,
                    "prompt_tokens": 0,
                    "prompt_tps": 0.0,
                    "load_s": 0.0,
                    "wall_s": 0.0,
                }
                positive, negative = deterministic_image_prompts(character, sections, scene_summary)
            elif args.image_prompt_strategy == "visual_fields_json":
                image_prompt_messages = build_visual_fields_messages(
                    character,
                    user_profile,
                    assistant_text,
                    scene_summary,
                )
                write_text(run_dir / f"{label}_image_prompt_messages.json", json.dumps(image_prompt_messages, indent=2))
                image_prompt_result = generate_chat(
                    args.text_model,
                    image_prompt_messages,
                    num_predict=args.image_prompt_tokens,
                    json_mode=True,
                )
                image_prompt_metrics = text_metrics(image_prompt_result)
                image_prompt_raw = (image_prompt_result.get("message") or {}).get("content", "").strip()
                visual_fields = parse_visual_fields(image_prompt_raw)
                write_text(run_dir / f"{label}_visual_fields.json", json.dumps(visual_fields, indent=2))
                positive, negative = visual_fields_image_prompts(character, sections, visual_fields, scene_summary)
            elif args.image_prompt_strategy == "strict_json":
                visual_fields = None
                image_prompt_messages = build_strict_json_image_messages(character, user_profile, scene_summary)
                write_text(run_dir / f"{label}_image_prompt_messages.json", json.dumps(image_prompt_messages, indent=2))
                image_prompt_result = generate_chat(
                    args.text_model,
                    image_prompt_messages,
                    num_predict=args.image_prompt_tokens,
                    json_mode=True,
                )
                image_prompt_metrics = text_metrics(image_prompt_result)
                image_prompt_raw = (image_prompt_result.get("message") or {}).get("content", "").strip()
                positive, negative = parse_json_image_prompt(image_prompt_raw, character, user_profile, scene_summary)
            else:
                visual_fields = None
                image_prompt_messages = prompts.build_image_prompt_messages(character, user_profile, scene_summary)
                write_text(run_dir / f"{label}_image_prompt_messages.json", json.dumps(image_prompt_messages, indent=2))
                image_prompt_result = generate_chat(args.text_model, image_prompt_messages, num_predict=args.image_prompt_tokens)
                image_prompt_metrics = text_metrics(image_prompt_result)
                image_prompt_raw = (image_prompt_result.get("message") or {}).get("content", "").strip()
                positive, negative = parse_labeled_prompt(image_prompt_raw, character, user_profile, scene_summary)
            if args.image_prompt_strategy == "deterministic_template":
                write_text(run_dir / f"{label}_image_prompt_messages.json", json.dumps(image_prompt_messages, indent=2))
            write_text(run_dir / f"{label}_image_prompt_raw.txt", image_prompt_raw)
            write_text(run_dir / f"{label}_image_positive.txt", positive)
            write_text(run_dir / f"{label}_image_negative.txt", negative)
            print(f"[image prompt] {label} wall={image_prompt_metrics['wall_s']:.2f}s")
            print(f"POSITIVE: {positive}")
            print(f"NEGATIVE: {negative}")

            image_step = generate_image(
                args.base_url,
                run_dir,
                label,
                positive,
                negative,
                args,
                seed=30300 + turn_index,
            )

            manifest["turns"].append(
                {
                    "label": label,
                    "user_text_path": str(run_dir / f"{label}_user.txt"),
                    "assistant_text_path": str(run_dir / f"{label}_assistant.txt"),
                    "assistant_raw_text_path": str(run_dir / f"{label}_assistant_raw.txt"),
                    "assistant_was_truncated": was_truncated,
                    "assistant_truncate_pattern": truncate_pattern,
                    "chat_metrics": text_metrics_data,
                    "chat_split": split,
                    "chat_resources_before": before_text,
                    "chat_resources_after": after_text,
                    "scene_raw_path": str(run_dir / f"{label}_scene_raw.txt"),
                    "scene_summary_path": str(run_dir / f"{label}_scene_summary.txt"),
                    "scene_metrics": scene_metrics,
                    "image_prompt_raw_path": str(run_dir / f"{label}_image_prompt_raw.txt"),
                    "image_positive_path": str(run_dir / f"{label}_image_positive.txt"),
                    "image_negative_path": str(run_dir / f"{label}_image_negative.txt"),
                    "visual_fields_path": str(run_dir / f"{label}_visual_fields.json") if visual_fields else None,
                    "visual_fields": visual_fields,
                    "image_prompt_metrics": image_prompt_metrics,
                    "image": image_step,
                }
            )

        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["final_resources"] = resource_snapshot("experiment final")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"[manifest] {manifest_path}")
        return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[error] HTTP {exc.code}: {body}")
        manifest["error"] = f"HTTP {exc.code}: {body}"
        return 1
    except Exception as exc:
        print(f"[error] {exc}")
        manifest["error"] = repr(exc)
        return 1
    finally:
        manifest["ended_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["final_resources"] = resource_snapshot("experiment final cleanup")
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass
        unload_model(args.text_model)
        if started_ollama is not None:
            started_ollama.terminate()
            try:
                started_ollama.wait(timeout=10)
            except subprocess.TimeoutExpired:
                started_ollama.kill()
                started_ollama.wait(timeout=10)
        tee.close()
        print(f"[report saved] {report_path}")
        print(f"[manifest saved] {manifest_path}")


if __name__ == "__main__":
    raise SystemExit(main())
