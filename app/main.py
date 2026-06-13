from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import signal
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import ensure_runtime_dirs, image_resolution_options, settings
from .db import (
    add_message,
    count_user_messages,
    clear_story_frame_image,
    create_conversation,
    create_story_frame,
    delete_lore_entry,
    delete_scene_location,
    delete_image_request,
    delete_images_for_message,
    delete_message,
    ensure_conversation,
    get_character,
    get_conversation,
    get_conversation_state,
    get_first_character,
    get_image_request,
    get_latest_summary,
    get_message,
    get_pinned_memory,
    get_scene_location,
    get_story_frame_by_assistant_message,
    get_user_profile,
    init_db,
    latest_summary_is_stale,
    list_characters,
    list_images_for_conversation,
    list_lore_entries,
    list_messages,
    list_scene_locations,
    list_summaries,
    list_story_frames,
    mark_interrupted_image_jobs,
    mark_latest_summary_stale,
    replace_pinned_memory,
    save_character,
    save_conversation_state,
    save_image_request,
    save_lore_entry,
    save_scene_location,
    save_summary,
    save_user_profile,
    seed_ahri_character,
    seed_atago_character,
    seed_default_user_profile,
    seed_echidna_character,
    seed_mirajane_character,
    seed_sample_character,
    slug_exists,
    update_story_frame,
    update_story_frame_for_assistant_message,
    utc_now,
    update_image_request,
    update_summary,
)
from .services.image_generation import image_service
from .services.event_log import configure_event_logging, log_event
from .services import prompts
from .services.memory import retrieve_lore_entries
from .services.resource_guard import resource_snapshot
from .services.runtime_coordinator import runtime_coordinator
from .services.text_generation import text_service


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "character"


def unique_slug(base_slug: str, current_id: int | None = None) -> str:
    slug = base_slug
    counter = 2
    while slug_exists(slug, exclude_id=current_id):
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_runtime_dirs()
    configure_event_logging()
    log_event("app_startup")
    init_db()
    interrupted = mark_interrupted_image_jobs("Interrupted by app restart before image job completed.")
    if interrupted:
        log_event("interrupted_image_jobs_recovered", count=interrupted)
    seed_sample_character()
    seed_default_user_profile()
    seed_atago_character()
    seed_ahri_character()
    seed_echidna_character()
    seed_mirajane_character()
    runtime_coordinator.startup()
    yield
    log_event("app_shutdown")
    runtime_coordinator.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
app.mount("/media", StaticFiles(directory=str(settings.outputs_dir)), name="media")
templates = Jinja2Templates(directory=str(settings.templates_dir))


def _static_asset_version() -> str:
    """Cache-busting version derived from static asset mtimes (per request)."""
    stamps = []
    for name in ("app.js", "style.css", "vendor/htmx.min.js"):
        try:
            stamps.append(int((settings.static_dir / name).stat().st_mtime))
        except OSError:
            continue
    return str(max(stamps)) if stamps else "1"


templates.env.globals["asset_version"] = _static_asset_version


def request_body_preview(raw: bytes, content_type: str) -> dict[str, Any] | str:
    text = raw.decode("utf-8", errors="replace")
    if "application/x-www-form-urlencoded" in content_type:
        parsed = parse_qs(text, keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}
    if len(text) > 1200:
        return text[:1200] + "...<truncated>"
    return text


@app.middleware("http")
async def event_logging_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith(("/static", "/media")) or path == "/status/stream":
        return await call_next(request)
    started = time.perf_counter()
    body_preview: dict[str, Any] | str = ""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        raw = await request.body()
        body_preview = request_body_preview(raw, request.headers.get("content-type", ""))
    log_event(
        "request_start",
        method=request.method,
        path=path,
        query=str(request.url.query),
        body=body_preview,
    )
    try:
        response = await call_next(request)
    except Exception as exc:
        log_event(
            "request_error",
            method=request.method,
            path=path,
            elapsed_s=round(time.perf_counter() - started, 3),
            error=repr(exc),
        )
        raise
    log_event(
        "request_end",
        method=request.method,
        path=path,
        status_code=response.status_code,
        elapsed_s=round(time.perf_counter() - started, 3),
    )
    return response


def get_active_character(character_id: int | None = None) -> dict[str, Any]:
    character = get_character(character_id) if character_id else None
    if character:
        return character
    first = get_first_character()
    if not first:
        seed_sample_character()
        first = get_first_character()
    if not first:
        raise RuntimeError("No character is available.")
    return first


def media_url_from_output_path(output_path: str | None) -> str | None:
    if not output_path:
        return None
    path = Path(output_path)
    if path.is_absolute():
        try:
            path = path.relative_to(settings.outputs_dir)
        except ValueError:
            marker = "outputs\\app\\"
            raw = output_path
            if marker in raw:
                normalized = raw.split(marker, 1)[-1].replace("\\", "/")
                return f"/media/{normalized}"
            return None
    return f"/media/{path.as_posix()}"


def with_image_urls(image_row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not image_row:
        return None
    enriched = dict(image_row)
    enriched["media_url"] = media_url_from_output_path(enriched.get("output_path"))
    enriched["stage1_media_url"] = media_url_from_output_path(enriched.get("stage1_output_path"))
    return enriched


def build_images_by_message(conversation_id: int) -> dict[int, list[dict[str, Any]]]:
    images_by_message: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in list_images_for_conversation(conversation_id):
        enriched = with_image_urls(row)
        if not enriched or enriched.get("message_id") is None:
            continue
        images_by_message[int(enriched["message_id"])].append(enriched)
    return dict(images_by_message)


def build_frames_by_assistant_message(conversation_id: int) -> dict[int, dict[str, Any]]:
    frames_by_message: dict[int, dict[str, Any]] = {}
    for frame in list_story_frames(conversation_id):
        message_id = frame.get("assistant_message_id")
        if message_id is not None:
            frames_by_message[int(message_id)] = frame
    return frames_by_message


def latest_assistant_message_id(messages: list[dict[str, Any]]) -> int | None:
    for message in reversed(messages):
        if message["role"] == "assistant":
            return int(message["id"])
    return None


def parse_resolution_preset(raw: str | None) -> dict[str, int] | None:
    if not raw:
        return None
    match = re.fullmatch(r"(\d+)x(\d+):(\d+)x(\d+)", raw.strip())
    if not match:
        return None
    base_width, base_height, target_width, target_height = (int(group) for group in match.groups())
    return {
        "base_width": base_width,
        "base_height": base_height,
        "target_width": target_width,
        "target_height": target_height,
    }


def format_resolution_preset(resolution_override: dict[str, int] | None) -> str:
    if resolution_override:
        return (
            f"{resolution_override['base_width']}x{resolution_override['base_height']}"
            f"->{resolution_override['target_width']}x{resolution_override['target_height']}"
        )
    return (
        f"{settings.image.base_width}x{settings.image.base_height}"
        f"->{settings.image.target_width}x{settings.image.target_height}"
    )


def is_speed_resolution_preset(resolution_override: dict[str, int] | None) -> bool:
    dims = resolution_override or {
        "base_width": settings.image.base_width,
        "base_height": settings.image.base_height,
        "target_width": settings.image.target_width,
        "target_height": settings.image.target_height,
    }
    return (
        int(dims["base_width"]) == 512
        and int(dims["base_height"]) == 512
        and int(dims["target_width"]) == 1024
        and int(dims["target_height"]) == 1024
    )


def merged_story_frame_metadata(message_id: int, additions: dict[str, Any]) -> str:
    frame = get_story_frame_by_assistant_message(message_id)
    metadata: dict[str, Any] = {}
    if frame:
        try:
            metadata = json.loads(str(frame.get("metadata_json") or "{}"))
        except json.JSONDecodeError:
            metadata = {}
    metadata.update(additions)
    return json.dumps(metadata, ensure_ascii=False)


def active_characters_to_json(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return "[]"
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return json.dumps([str(item).strip() for item in parsed if str(item).strip()], ensure_ascii=False)
    except json.JSONDecodeError:
        pass
    names = [part.strip() for part in re.split(r"[,;\n]+", cleaned) if part.strip()]
    return json.dumps(names, ensure_ascii=False)


def active_characters_from_state(conversation_state: dict[str, Any]) -> str:
    raw = str(conversation_state.get("active_characters_json") or "[]")
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return ", ".join(str(item) for item in parsed)
    except json.JSONDecodeError:
        return raw
    return raw


def as_list(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def int_map_lookup(mapping: dict[int, int], value: Any) -> int | None:
    try:
        return mapping[int(value)]
    except (KeyError, TypeError, ValueError):
        return None


def import_story_export_payload(data: dict[str, Any]) -> int:
    if not isinstance(data, dict) or int(data.get("export_version", 0) or 0) < 1:
        raise ValueError("Unsupported story export format.")
    source_character = data.get("character") if isinstance(data.get("character"), dict) else {}
    display_name = str(source_character.get("display_name") or "Imported Character").strip()
    source_slug = str(source_character.get("slug") or display_name).strip()
    character_id = save_character(
        {
            "slug": unique_slug(slugify(source_slug)),
            "display_name": display_name,
            "persona_summary": source_character.get("persona_summary", ""),
            "character_dossier": source_character.get("character_dossier", ""),
            "personality_traits": source_character.get("personality_traits", ""),
            "speaking_style": source_character.get("speaking_style", ""),
            "backstory": source_character.get("backstory", ""),
            "relationship_frame": source_character.get("relationship_frame", ""),
            "boundaries": source_character.get("boundaries", ""),
            "appearance": source_character.get("appearance", ""),
            "example_dialogue": source_character.get("example_dialogue", ""),
            "default_visual_style": source_character.get("default_visual_style", ""),
            "source_media": source_character.get("source_media", ""),
            "special_instructions": source_character.get("special_instructions", ""),
            "image_anchor_summary": source_character.get("image_anchor_summary", ""),
            "image_prompt_positive_additions": source_character.get("image_prompt_positive_additions", ""),
            "image_prompt_negative_additions": source_character.get("image_prompt_negative_additions", ""),
            "is_active": True,
        }
    )

    source_conversation = data.get("conversation") if isinstance(data.get("conversation"), dict) else {}
    conversation = create_conversation(
        character_id,
        title=f"{str(source_conversation.get('title') or display_name).strip()} (Imported)",
    )

    state = data.get("conversation_state") if isinstance(data.get("conversation_state"), dict) else {}
    save_conversation_state(
        conversation["id"],
        current_location_name=str(state.get("current_location_name") or ""),
        current_location_description=str(state.get("current_location_description") or ""),
        active_characters_json=str(state.get("active_characters_json") or "[]"),
    )

    message_id_map: dict[int, int] = {}
    for message in as_list(data.get("messages")):
        role = str(message.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        new_id = add_message(
            conversation["id"],
            role,
            str(message.get("content") or ""),
            created_at=str(message.get("created_at") or "") or None,
        )
        if message.get("id") is not None:
            message_id_map[int(message["id"])] = new_id

    for summary in reversed(as_list(data.get("summaries"))):
        save_summary(character_id, conversation["id"], str(summary.get("content") or ""))

    for lore in as_list(data.get("lore_entries")):
        save_lore_entry(
            {
                "character_id": character_id,
                "title": lore.get("title", ""),
                "content": lore.get("content", ""),
                "keywords": lore.get("keywords", ""),
                "priority": lore.get("priority", 0),
                "enabled": bool(lore.get("enabled", True)),
                "always_include": bool(lore.get("always_include", False)),
            }
        )

    for location in as_list(data.get("scene_locations")):
        save_scene_location(
            {
                "character_id": character_id,
                "name": location.get("name", ""),
                "description": location.get("description", ""),
                "visual_anchor": location.get("visual_anchor", ""),
            }
        )

    image_id_map: dict[int, int] = {}
    for image in as_list(data.get("images")):
        new_image_id = save_image_request(
            {
                "character_id": character_id,
                "conversation_id": conversation["id"],
                "message_id": int_map_lookup(message_id_map, image.get("message_id")),
                "scene_summary": str(image.get("scene_summary") or ""),
                "positive_prompt": str(image.get("positive_prompt") or ""),
                "negative_prompt": str(image.get("negative_prompt") or ""),
                "base_width": int(image.get("base_width") or settings.image.base_width),
                "base_height": int(image.get("base_height") or settings.image.base_height),
                "target_width": int(image.get("target_width") or settings.image.target_width),
                "target_height": int(image.get("target_height") or settings.image.target_height),
                "denoise_strength": float(image.get("denoise_strength") or settings.image.denoise_strength),
                "seed": int(image.get("seed") or -1),
                "stage1_output_path": image.get("stage1_output_path"),
                "output_path": image.get("output_path"),
                "status": str(image.get("status") or "imported"),
                "error": str(image.get("error") or ""),
            }
        )
        if image.get("id") is not None:
            image_id_map[int(image["id"])] = new_image_id

    for frame in as_list(data.get("story_frames")):
        create_story_frame(
            {
                "conversation_id": conversation["id"],
                "character_id": character_id,
                "frame_index": int(frame.get("frame_index") or 0),
                "user_message_id": int_map_lookup(message_id_map, frame.get("user_message_id")),
                "assistant_message_id": int_map_lookup(message_id_map, frame.get("assistant_message_id")),
                "image_request_id": int_map_lookup(image_id_map, frame.get("image_request_id")),
                "user_input": frame.get("user_input", ""),
                "assistant_output": frame.get("assistant_output", ""),
                "scene_summary": frame.get("scene_summary", ""),
                "image_positive_prompt": frame.get("image_positive_prompt", ""),
                "image_negative_prompt": frame.get("image_negative_prompt", ""),
                "image_output_path": frame.get("image_output_path", ""),
                "location_name": frame.get("location_name", ""),
                "active_characters_json": frame.get("active_characters_json", "[]"),
                "story_summary_before": frame.get("story_summary_before", ""),
                "story_summary_after": frame.get("story_summary_after", ""),
                "text_model": frame.get("text_model", ""),
                "image_backend": frame.get("image_backend", ""),
                "image_preset": frame.get("image_preset", ""),
                "text_started_at": frame.get("text_started_at", ""),
                "text_completed_at": frame.get("text_completed_at", ""),
                "image_started_at": frame.get("image_started_at", ""),
                "image_completed_at": frame.get("image_completed_at", ""),
                "text_elapsed_s": frame.get("text_elapsed_s", 0),
                "image_elapsed_s": frame.get("image_elapsed_s", 0),
                "route_elapsed_s": frame.get("route_elapsed_s", 0),
                "status": frame.get("status", "imported"),
                "error": frame.get("error", ""),
                "metadata_json": frame.get("metadata_json", "{}"),
            }
        )
    return character_id


def parse_lore_entries_from_form(form: Any) -> list[dict[str, Any]]:
    indices: set[int] = set()
    for key in form.keys():
        match = re.match(r"^lore_title_(\d+)$", key)
        if match:
            indices.add(int(match.group(1)))

    parsed: list[dict[str, Any]] = []
    for index in sorted(indices):
        entry_id = str(form.get(f"lore_id_{index}", "") or "").strip()
        title = str(form.get(f"lore_title_{index}", "") or "").strip()
        content = str(form.get(f"lore_content_{index}", "") or "").strip()
        keywords = str(form.get(f"lore_keywords_{index}", "") or "").strip()
        priority_raw = str(form.get(f"lore_priority_{index}", "0") or "0").strip()
        delete_flag = str(form.get(f"lore_delete_{index}", "0") or "0").strip() == "1"
        enabled = f"lore_enabled_{index}" in form
        always_include = f"lore_always_include_{index}" in form
        try:
            priority = int(priority_raw or "0")
        except ValueError:
            priority = 0

        if delete_flag:
            if entry_id:
                parsed.append({"id": int(entry_id), "delete": True})
            continue

        if not (title or content or keywords):
            if entry_id:
                parsed.append({"id": int(entry_id), "delete": True})
            continue

        parsed.append(
            {
                "id": int(entry_id) if entry_id else None,
                "title": title or "Untitled Entry",
                "content": content,
                "keywords": keywords,
                "priority": priority,
                "enabled": enabled,
                "always_include": always_include,
            }
        )
    return parsed


def sync_character_lore_entries(character_id: int, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        if entry.get("delete"):
            delete_lore_entry(int(entry["id"]))
            continue
        save_lore_entry({**entry, "character_id": character_id})


def image_row_sort_key(image: dict[str, Any]) -> tuple[str, int]:
    return (image.get("created_at", ""), int(image.get("id", 0)))


def remove_image_files(image_rows: list[dict[str, Any]]) -> None:
    for row in image_rows:
        for key in ("stage1_output_path", "output_path"):
            raw_path = row.get(key)
            if not raw_path:
                continue
            path = Path(raw_path)
            if not path.is_absolute():
                path = settings.outputs_dir / path
            try:
                path.resolve().relative_to(settings.outputs_dir.resolve())
            except ValueError:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


async def ensure_summary_context(
    character: dict[str, Any],
    user_profile: dict[str, Any],
    conversation_id: int,
    pinned_memory: str,
    messages: list[dict[str, Any]],
) -> str:
    summary = get_latest_summary(character["id"], conversation_id)
    if not latest_summary_is_stale(character["id"], conversation_id):
        return summary

    rebuilt = await run_in_threadpool(
        runtime_coordinator.run_text_task,
        text_service.summarize_memory,
        character,
        user_profile,
        pinned_memory,
        summary,
        messages,
    )
    save_summary(character["id"], conversation_id, rebuilt)
    return rebuilt


def render_index(
    request: Request,
    *,
    character_id: int | None = None,
    status_message: str = "",
    error_message: str = "",
) -> HTMLResponse:
    characters = list_characters()
    active_character = get_active_character(character_id)
    conversation = ensure_conversation(active_character["id"])
    messages = list_messages(conversation["id"])
    pinned_memory = get_pinned_memory(active_character["id"])
    lore_entries = list_lore_entries(active_character["id"], include_global=False)
    user_profile = get_user_profile()
    images_by_message = build_images_by_message(conversation["id"])
    frames_by_message = build_frames_by_assistant_message(conversation["id"])
    story_summaries = list_summaries(active_character["id"], conversation["id"])
    conversation_state = get_conversation_state(conversation["id"])
    return templates.TemplateResponse(
        request=request,
        name="index_v2.html",
        context={
            "app_name": settings.app_name,
            "characters": characters,
            "active_character": active_character,
            "conversation": conversation,
            "messages": messages,
            "images_by_message": images_by_message,
            "frames_by_message": frames_by_message,
            "story_summaries": story_summaries,
            "conversation_state": conversation_state,
            "active_characters_text": active_characters_from_state(conversation_state),
            "scene_locations": list_scene_locations(active_character["id"]),
            "latest_assistant_id": latest_assistant_message_id(messages),
            "pinned_memory": pinned_memory,
            "lore_entries": lore_entries,
            "user_profile": user_profile,
            "image_cfg": settings.image,
            "resolution_options": image_resolution_options(),
            "status_message": status_message,
            "error_message": error_message,
        },
    )


def render_character_form(request: Request, character: dict[str, Any] | None = None) -> HTMLResponse:
    pinned_memory = get_pinned_memory(character["id"]) if character else ""
    lore_entries = list_lore_entries(character["id"], include_global=False) if character else []
    return templates.TemplateResponse(
        request=request,
        name="partials/character_form.html",
        context={"character": character, "pinned_memory": pinned_memory, "lore_entries": lore_entries},
    )


def render_story_timeline(
    request: Request,
    *,
    active_character: dict[str, Any],
    messages: list[dict[str, Any]],
    images_by_message: dict[int, list[dict[str, Any]]],
    latest_assistant_id: int | None,
    frames_by_message: dict[int, dict[str, Any]] | None = None,
    status_message: str = "",
    error_message: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="partials/story_timeline.html",
        context={
            "active_character": active_character,
            "messages": messages,
            "images_by_message": images_by_message,
            "frames_by_message": frames_by_message or {},
            "latest_assistant_id": latest_assistant_id,
            "image_cfg": settings.image,
            "resolution_options": image_resolution_options(),
            "status_message": status_message,
            "error_message": error_message,
        },
    )


def render_right_panel(
    request: Request,
    *,
    active_character: dict[str, Any],
    user_profile: dict[str, Any],
    pinned_memory: str,
    lore_entries: list[dict[str, Any]],
    status_message: str = "",
    error_message: str = "",
) -> HTMLResponse:
    conversation = ensure_conversation(active_character["id"])
    conversation_state = get_conversation_state(conversation["id"])
    return templates.TemplateResponse(
        request=request,
        name="partials/right_panel_v2.html",
        context={
            "active_character": active_character,
            "conversation": conversation,
            "conversation_state": conversation_state,
            "active_characters_text": active_characters_from_state(conversation_state),
            "scene_locations": list_scene_locations(active_character["id"]),
            "user_profile": user_profile,
            "pinned_memory": pinned_memory,
            "lore_entries": lore_entries,
            "story_summaries": list_summaries(active_character["id"], conversation["id"]),
            "status_message": status_message,
            "error_message": error_message,
            "image_cfg": settings.image,
            "resolution_options": image_resolution_options(),
        },
    )


def render_image_response(
    request: Request,
    *,
    active_character: dict[str, Any],
    messages: list[dict[str, Any]],
    images_by_message: dict[int, list[dict[str, Any]]],
    latest_assistant_id: int | None,
    pinned_memory: str,
    status_message: str = "",
    error_message: str = "",
) -> HTMLResponse:
    lore_entries = list_lore_entries(active_character["id"], include_global=False)
    user_profile = get_user_profile()
    return templates.TemplateResponse(
        request=request,
        name="partials/image_generation_response.html",
        context={
            "active_character": active_character,
            "messages": messages,
            "images_by_message": images_by_message,
            "latest_assistant_id": latest_assistant_id,
            "pinned_memory": pinned_memory,
            "lore_entries": lore_entries,
            "user_profile": user_profile,
            "status_message": status_message,
            "error_message": error_message,
            "image_cfg": settings.image,
            "resolution_options": image_resolution_options(),
        },
    )


def recent_event_log_entries(limit: int = 16) -> list[dict[str, Any]]:
    log_path = settings.runtime_dir / "logs" / "app_events.jsonl"
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"event": "unparseable_log_line", "raw": line[:500]})
    return entries


async def create_image_for_message(
    *,
    character: dict[str, Any],
    conversation: dict[str, Any],
    message_id: int,
    messages: list[dict[str, Any]],
    user_profile: dict[str, Any],
    image_note: str = "",
    resolution_override: dict[str, int] | None = None,
) -> dict[str, Any]:
    image_started_at = utc_now()
    image_start = time.perf_counter()
    log_event(
        "image_job_start",
        character_id=character["id"],
        conversation_id=conversation["id"],
        message_id=message_id,
        resolution=format_resolution_preset(resolution_override),
        image_note=bool(image_note.strip()),
    )
    update_story_frame_for_assistant_message(
        message_id,
        {
            "image_started_at": image_started_at,
            "image_backend": "a1111",
            "image_preset": format_resolution_preset(resolution_override),
            "status": "image_prompting",
        },
    )
    override = prompts.parse_prompt_override(image_note)
    prompt_strategy = "manual_override" if override else "llm_composer"
    if override:
        positive_prompt, negative_prompt = override
        scene_summary = image_note.strip()
    else:
        latest_assistant = next(
            (str(row.get("content", "") or "").strip() for row in reversed(messages) if row.get("role") == "assistant"),
            "",
        )
        scene_summary = "\n\n".join(part for part in (image_note.strip(), latest_assistant) if part).strip()
        if not scene_summary:
            scene_summary = prompts.fallback_scene_summary(character, image_note.strip())
        if is_speed_resolution_preset(resolution_override):
            prompt_strategy = "deterministic_speed"
            image_service._set_status(  # noqa: SLF001
                "preparing",
                "Building fast visual prompt",
                0.08,
                stage="prompt",
                message_id=message_id,
            )
            positive_prompt, negative_prompt = prompts.deterministic_speed_image_prompts(
                character,
                scene_summary,
                user_profile,
            )
        else:
            image_service._set_status(  # noqa: SLF001
                "preparing",
                "Composing visual prompt",
                0.08,
                stage="prompt",
                message_id=message_id,
            )
            positive_prompt, negative_prompt = await run_in_threadpool(
                runtime_coordinator.run_text_task,
                text_service.compose_image_prompts,
                character,
                user_profile,
                scene_summary,
            )
    log_event(
        "image_prompt_ready",
        character_id=character["id"],
        conversation_id=conversation["id"],
        message_id=message_id,
        prompt_strategy=prompt_strategy,
        scene_summary=scene_summary,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
    )
    image_service._set_status(  # noqa: SLF001
        "preparing",
        "Releasing text model for image render",
        0.12,
        stage="handoff",
        message_id=message_id,
    )
    payload = await run_in_threadpool(
        runtime_coordinator.run_image_task,
        image_service.generate,
        character,
        conversation["id"],
        message_id,
        None,
        scene_summary,
        positive_prompt,
        negative_prompt,
        resolution_override,
    )
    image_id = save_image_request(payload)
    log_event(
        "image_job_complete",
        character_id=character["id"],
        conversation_id=conversation["id"],
        message_id=message_id,
        image_id=image_id,
        elapsed_s=round(time.perf_counter() - image_start, 3),
        output_path=payload.get("output_path", ""),
    )
    update_story_frame_for_assistant_message(
        message_id,
        {
            "image_request_id": image_id,
            "scene_summary": scene_summary,
            "image_positive_prompt": positive_prompt,
            "image_negative_prompt": negative_prompt,
            "image_output_path": payload.get("output_path", ""),
            "image_completed_at": utc_now(),
            "image_elapsed_s": time.perf_counter() - image_start,
            "status": "image_completed",
            "error": "",
            "metadata_json": merged_story_frame_metadata(
                message_id,
                {
                    "image_prompt_strategy": prompt_strategy,
                    "image_note": bool(image_note.strip()),
                },
            ),
        },
    )
    return payload


def start_background_image_job(
    *,
    character: dict[str, Any],
    conversation: dict[str, Any],
    message_id: int,
    messages: list[dict[str, Any]],
    user_profile: dict[str, Any],
    image_note: str = "",
    resolution_override: dict[str, int] | None = None,
) -> None:
    def worker() -> None:
        try:
            asyncio.run(
                create_image_for_message(
                    character=character,
                    conversation=conversation,
                    message_id=message_id,
                    messages=messages,
                    user_profile=user_profile,
                    image_note=image_note,
                    resolution_override=resolution_override,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive background path
            log_event(
                "background_image_job_error",
                character_id=character["id"],
                conversation_id=conversation["id"],
                message_id=message_id,
                error=repr(exc),
            )
            update_story_frame_for_assistant_message(
                message_id,
                {
                    "status": "image_error",
                    "error": str(exc),
                    "image_completed_at": utc_now(),
                },
            )
            image_service._set_status(  # noqa: SLF001
                "error",
                f"Background image generation failed: {exc}",
                0.0,
                stage="error",
                message_id=message_id,
            )

    thread = threading.Thread(
        target=worker,
        name=f"companion-auto-image-message-{message_id}",
        daemon=True,
    )
    thread.start()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, character_id: int | None = None) -> HTMLResponse:
    return render_index(request, character_id=character_id)


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/timeline/{character_id}", response_class=HTMLResponse)
async def timeline_fragment(request: Request, character_id: int) -> HTMLResponse:
    character = get_active_character(character_id)
    conversation = ensure_conversation(character["id"])
    messages = list_messages(conversation["id"])
    return render_story_timeline(
        request,
        active_character=character,
        messages=messages,
        images_by_message=build_images_by_message(conversation["id"]),
        frames_by_message=build_frames_by_assistant_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(messages),
    )


@app.get("/status")
async def status() -> dict[str, Any]:
    return {
        "text": text_service.snapshot(),
        "image": image_service.snapshot(),
        "runtime": runtime_coordinator.snapshot(),
    }


@app.get("/diagnostics")
async def diagnostics() -> dict[str, Any]:
    resources = resource_snapshot()
    return {
        "runtime": runtime_coordinator.snapshot(),
        "text": text_service.snapshot(),
        "image": image_service.snapshot(),
        "resources": resources.__dict__,
        "settings": {
            "text_model": settings.ollama_model_name,
            "num_ctx": settings.ollama_num_ctx,
            "preload_text_model": settings.preload_text_model,
            "preload_image_backend": settings.preload_image_backend,
            "stop_ollama_before_image": settings.stop_ollama_before_image,
            "image_backend": settings.image.backend,
            "image_keep_hot": settings.image.a1111_keep_hot,
            "image_preset": (
                f"{settings.image.base_width}->{settings.image.target_width}, "
                f"{settings.image.steps}+{settings.image.hires_steps} steps"
            ),
        },
        "recent_events": recent_event_log_entries(),
    }


@app.get("/stories/{character_id}/export")
async def export_story(character_id: int) -> JSONResponse:
    character = get_active_character(character_id)
    conversation = ensure_conversation(character["id"])
    return JSONResponse(
        {
            "export_version": 1,
            "character": character,
            "user_profile": get_user_profile(),
            "conversation": conversation,
            "conversation_state": get_conversation_state(conversation["id"]),
            "scene_locations": list_scene_locations(character["id"]),
            "messages": list_messages(conversation["id"]),
            "story_frames": list_story_frames(conversation["id"]),
            "summaries": list_summaries(character["id"], conversation["id"]),
            "images": list_images_for_conversation(conversation["id"]),
            "lore_entries": list_lore_entries(character["id"], include_global=False),
        }
    )


@app.post("/stories/import")
async def import_story(request: Request) -> Response:
    form = await request.form()
    current_character_id_raw = str(form.get("character_id", "") or "").strip()
    current_character_id = int(current_character_id_raw) if current_character_id_raw.isdigit() else None
    current_character = get_active_character(current_character_id)
    raw_json = str(form.get("story_json", "") or "").strip()
    if not raw_json:
        return render_right_panel(
            request,
            active_character=current_character,
            user_profile=get_user_profile(),
            pinned_memory=get_pinned_memory(current_character["id"]),
            lore_entries=list_lore_entries(current_character["id"], include_global=False),
            error_message="Paste a story export JSON payload first.",
        )
    try:
        imported_character_id = import_story_export_payload(json.loads(raw_json))
    except Exception as exc:
        return render_right_panel(
            request,
            active_character=current_character,
            user_profile=get_user_profile(),
            pinned_memory=get_pinned_memory(current_character["id"]),
            lore_entries=list_lore_entries(current_character["id"], include_global=False),
            error_message=f"Story import failed: {exc}",
        )
    return RedirectResponse(url=f"/?character_id={imported_character_id}", status_code=303)


@app.get("/status/stream")
async def status_stream() -> StreamingResponse:
    async def event_stream():
        last_payload = ""
        while True:
            payload = json.dumps(
                {
                    "text": text_service.snapshot(),
                    "image": image_service.snapshot(),
                    "runtime": runtime_coordinator.snapshot(),
                }
            )
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/characters/new-form", response_class=HTMLResponse)
async def character_new_form(request: Request) -> HTMLResponse:
    return render_character_form(request, None)


@app.get("/characters/{character_id}/edit-form", response_class=HTMLResponse)
async def character_edit_form(request: Request, character_id: int) -> HTMLResponse:
    return render_character_form(request, get_character(character_id))


@app.post("/characters")
async def save_character_route(request: Request) -> Response:
    form = await request.form()
    raw_id = str(form.get("id", "") or "").strip()
    character_id_input = int(raw_id) if raw_id else None
    display_name = str(form.get("display_name", "") or "").strip()
    persona_summary = str(form.get("persona_summary", "") or "").strip()
    character_dossier = str(form.get("character_dossier", "") or "").strip()
    personality_traits = str(form.get("personality_traits", "") or "").strip()
    speaking_style = str(form.get("speaking_style", "") or "").strip()
    backstory = str(form.get("backstory", "") or "").strip()
    relationship_frame = str(form.get("relationship_frame", "") or "").strip()
    boundaries = str(form.get("boundaries", "") or "").strip()
    appearance = str(form.get("appearance", "") or "").strip()
    example_dialogue = str(form.get("example_dialogue", "") or "").strip()
    default_visual_style = str(form.get("default_visual_style", "") or "").strip()
    source_media = str(form.get("source_media", "") or "").strip()
    special_instructions = str(form.get("special_instructions", "") or "").strip()
    image_anchor_summary = str(form.get("image_anchor_summary", "") or "").strip()
    image_prompt_positive_additions = str(form.get("image_prompt_positive_additions", "") or "").strip()
    image_prompt_negative_additions = str(form.get("image_prompt_negative_additions", "") or "").strip()
    pinned_memory = str(form.get("pinned_memory", "") or "").strip()
    lore_entries = parse_lore_entries_from_form(form)

    if not display_name:
        return Response("Display name is required.", status_code=400)
    slug = unique_slug(slugify(display_name), current_id=character_id_input)
    character_id = save_character(
        {
            "id": character_id_input,
            "slug": slug,
            "display_name": display_name,
            "persona_summary": persona_summary,
            "character_dossier": character_dossier,
            "personality_traits": personality_traits,
            "speaking_style": speaking_style,
            "backstory": backstory,
            "relationship_frame": relationship_frame,
            "boundaries": boundaries,
            "appearance": appearance,
            "example_dialogue": example_dialogue,
            "default_visual_style": default_visual_style,
            "source_media": source_media,
            "special_instructions": special_instructions,
            "image_anchor_summary": image_anchor_summary,
            "image_prompt_positive_additions": image_prompt_positive_additions,
            "image_prompt_negative_additions": image_prompt_negative_additions,
            "is_active": True,
        }
    )
    replace_pinned_memory(character_id, pinned_memory)
    sync_character_lore_entries(character_id, lore_entries)
    destination = f"/?character_id={character_id}"
    if request.headers.get("HX-Request") == "true":
        return Response(headers={"HX-Redirect": destination})
    return RedirectResponse(destination, status_code=303)


@app.post("/user-profile", response_class=HTMLResponse)
async def save_user_profile_route(
    request: Request,
    character_id: int = Form(...),
    display_name: str = Form(...),
    background: str = Form(default=""),
) -> HTMLResponse:
    save_user_profile(display_name, background)
    character = get_active_character(character_id)
    pinned_memory = get_pinned_memory(character["id"])
    lore_entries = list_lore_entries(character["id"], include_global=False)
    return render_right_panel(
        request,
        active_character=character,
        user_profile=get_user_profile(),
        pinned_memory=pinned_memory,
        lore_entries=lore_entries,
        status_message="User profile updated.",
    )


@app.post("/summaries/{summary_id}", response_class=HTMLResponse)
async def save_story_summary_route(
    request: Request,
    summary_id: int,
    character_id: int = Form(...),
    content: str = Form(default=""),
) -> HTMLResponse:
    character = get_active_character(character_id)
    update_summary(summary_id, content, is_stale=False)
    return render_right_panel(
        request,
        active_character=character,
        user_profile=get_user_profile(),
        pinned_memory=get_pinned_memory(character["id"]),
        lore_entries=list_lore_entries(character["id"], include_global=False),
        status_message="Story memory updated.",
    )


@app.post("/conversation-state", response_class=HTMLResponse)
async def save_conversation_state_route(
    request: Request,
    character_id: int = Form(...),
    current_location_name: str = Form(default=""),
    current_location_description: str = Form(default=""),
    active_characters: str = Form(default=""),
) -> HTMLResponse:
    character = get_active_character(character_id)
    conversation = ensure_conversation(character["id"])
    save_conversation_state(
        conversation["id"],
        current_location_name=current_location_name,
        current_location_description=current_location_description,
        active_characters_json=active_characters_to_json(active_characters),
    )
    return render_right_panel(
        request,
        active_character=character,
        user_profile=get_user_profile(),
        pinned_memory=get_pinned_memory(character["id"]),
        lore_entries=list_lore_entries(character["id"], include_global=False),
        status_message="Scene state updated.",
    )


@app.post("/locations", response_class=HTMLResponse)
async def save_scene_location_route(
    request: Request,
    character_id: int = Form(...),
    name: str = Form(default=""),
    description: str = Form(default=""),
    visual_anchor: str = Form(default=""),
) -> HTMLResponse:
    character = get_active_character(character_id)
    status_message = ""
    error_message = ""
    try:
        save_scene_location(
            {
                "character_id": character["id"],
                "name": name,
                "description": description,
                "visual_anchor": visual_anchor,
            }
        )
        status_message = "Location saved."
    except Exception as exc:
        error_message = f"Location save failed: {exc}"
    return render_right_panel(
        request,
        active_character=character,
        user_profile=get_user_profile(),
        pinned_memory=get_pinned_memory(character["id"]),
        lore_entries=list_lore_entries(character["id"], include_global=False),
        status_message=status_message,
        error_message=error_message,
    )


@app.post("/locations/{location_id}/use", response_class=HTMLResponse)
async def use_scene_location_route(
    request: Request,
    location_id: int,
    character_id: int = Form(...),
    active_characters: str = Form(default=""),
) -> HTMLResponse:
    character = get_active_character(character_id)
    conversation = ensure_conversation(character["id"])
    location = get_scene_location(location_id)
    if location and int(location["character_id"]) == int(character["id"]):
        save_conversation_state(
            conversation["id"],
            current_location_name=location["name"],
            current_location_description=location["description"],
            active_characters_json=active_characters_to_json(active_characters),
        )
        status_message = f"Scene moved to {location['name']}."
        error_message = ""
    else:
        status_message = ""
        error_message = "That location could not be found."
    return render_right_panel(
        request,
        active_character=character,
        user_profile=get_user_profile(),
        pinned_memory=get_pinned_memory(character["id"]),
        lore_entries=list_lore_entries(character["id"], include_global=False),
        status_message=status_message,
        error_message=error_message,
    )


@app.post("/locations/{location_id}/delete", response_class=HTMLResponse)
async def delete_scene_location_route(
    request: Request,
    location_id: int,
    character_id: int = Form(...),
) -> HTMLResponse:
    character = get_active_character(character_id)
    location = get_scene_location(location_id)
    if location and int(location["character_id"]) == int(character["id"]):
        delete_scene_location(location_id)
        status_message = "Location deleted."
        error_message = ""
    else:
        status_message = ""
        error_message = "That location could not be found."
    return render_right_panel(
        request,
        active_character=character,
        user_profile=get_user_profile(),
        pinned_memory=get_pinned_memory(character["id"]),
        lore_entries=list_lore_entries(character["id"], include_global=False),
        status_message=status_message,
        error_message=error_message,
    )


@app.post("/chat/{character_id}", response_class=HTMLResponse)
async def send_message(
    request: Request,
    character_id: int,
    message: str = Form(...),
    auto_image: str = Form(default=""),
    resolution_preset: str = Form(default=""),
) -> HTMLResponse:
    route_start = time.perf_counter()
    character = get_active_character(character_id)
    conversation = ensure_conversation(character["id"])
    cleaned = message.strip()
    if not cleaned:
        return render_story_timeline(
            request,
            active_character=character,
            messages=list_messages(conversation["id"]),
            images_by_message=build_images_by_message(conversation["id"]),
            latest_assistant_id=latest_assistant_message_id(list_messages(conversation["id"])),
            error_message="Message cannot be empty.",
        )
    user_message_id = add_message(conversation["id"], "user", cleaned)
    log_event(
        "chat_user_message_saved",
        character_id=character["id"],
        conversation_id=conversation["id"],
        user_message_id=user_message_id,
        auto_image=bool(auto_image),
        resolution_preset=resolution_preset,
        content=cleaned,
    )
    messages = list_messages(conversation["id"])
    pinned_memory = get_pinned_memory(character["id"])
    user_profile = get_user_profile()
    summary = await ensure_summary_context(character, user_profile, conversation["id"], pinned_memory, messages)
    lore_entries = retrieve_lore_entries(character, messages)
    story_frames = list_story_frames(conversation["id"])
    conversation_state = get_conversation_state(conversation["id"])

    error_message = ""
    status_message = ""
    text_service._set_status("preparing", "Reply request received", 0.04)  # noqa: SLF001
    text_started_at = utc_now()
    text_start = time.perf_counter()
    frame_id: int | None = None
    try:
        reply = await run_in_threadpool(
            runtime_coordinator.run_text_task,
            text_service.chat_reply,
            character,
            user_profile,
            pinned_memory,
            summary,
            lore_entries,
            messages,
            story_frames,
            conversation_state,
        )
        text_elapsed_s = time.perf_counter() - text_start
        assistant_message_id = add_message(conversation["id"], "assistant", reply)
        log_event(
            "chat_assistant_reply_saved",
            character_id=character["id"],
            conversation_id=conversation["id"],
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            text_elapsed_s=round(text_elapsed_s, 3),
            content=reply,
        )
        messages = list_messages(conversation["id"])
        frame_id = create_story_frame(
            {
                "conversation_id": conversation["id"],
                "character_id": character["id"],
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "user_input": cleaned,
                "assistant_output": reply,
                "story_summary_before": summary,
                "location_name": conversation_state.get("current_location_name", ""),
                "active_characters_json": conversation_state.get("active_characters_json", "[]"),
                "text_model": settings.ollama_model_name,
                "text_started_at": text_started_at,
                "text_completed_at": utc_now(),
                "text_elapsed_s": text_elapsed_s,
                "route_elapsed_s": time.perf_counter() - route_start,
                "status": "image_queued" if auto_image else "text_completed",
                "metadata_json": json.dumps(
                    {
                        "auto_image": bool(auto_image),
                        "resolution_preset": resolution_preset,
                        "lore_entry_count": len(lore_entries),
                    },
                    ensure_ascii=False,
                ),
            }
        )
        if auto_image:
            log_event(
                "chat_auto_image_queued",
                character_id=character["id"],
                conversation_id=conversation["id"],
                assistant_message_id=assistant_message_id,
                resolution_preset=resolution_preset,
            )
            image_service._set_status(  # noqa: SLF001
                "preparing",
                "Auto image request received",
                0.03,
                stage="queued",
                message_id=assistant_message_id,
            )
            start_background_image_job(
                character=character,
                conversation=conversation,
                message_id=assistant_message_id,
                messages=messages,
                user_profile=user_profile,
                resolution_override=parse_resolution_preset(resolution_preset),
            )
            status_message = "Reply generated. Image is rendering in the background."
        if count_user_messages(conversation["id"]) % settings.summary_interval_user_turns == 0:
            new_summary = await run_in_threadpool(
                runtime_coordinator.run_text_task,
                text_service.summarize_memory,
                character,
                user_profile,
                pinned_memory,
                summary,
                messages,
            )
            save_summary(character["id"], conversation["id"], new_summary)
            if frame_id:
                update_story_frame(
                    frame_id,
                    {
                        "story_summary_after": new_summary,
                        "status": "summary_completed" if not auto_image else "image_queued",
                    },
                )
    except Exception as exc:  # pragma: no cover - runtime safety path
        error_message = f"Text generation error: {exc}"
        log_event(
            "chat_text_error",
            character_id=character["id"],
            conversation_id=conversation["id"],
            user_message_id=user_message_id,
            error=repr(exc),
        )
    return render_story_timeline(
        request,
        active_character=character,
        messages=messages,
        images_by_message=build_images_by_message(conversation["id"]),
        frames_by_message=build_frames_by_assistant_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(messages),
        status_message=status_message,
        error_message=error_message,
    )


def _ndjson_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _run_streaming_chat_turn(
    events: "queue.Queue[dict[str, Any] | None]",
    character: dict[str, Any],
    conversation: dict[str, Any],
    cleaned: str,
    auto_image: str,
    resolution_preset: str,
) -> None:
    """Worker thread for one streaming chat turn.

    Owns the runtime lock for the whole generation so RLock acquire/release
    stay on one thread; the HTTP response generator only drains `events`.
    """
    route_start = time.perf_counter()
    try:
        user_message_id = add_message(conversation["id"], "user", cleaned)
        log_event(
            "chat_user_message_saved",
            character_id=character["id"],
            conversation_id=conversation["id"],
            user_message_id=user_message_id,
            auto_image=bool(auto_image),
            resolution_preset=resolution_preset,
            content=cleaned,
            streaming=True,
        )
        events.put({"t": "status", "v": "Preparing scene context..."})
        messages = list_messages(conversation["id"])
        pinned_memory = get_pinned_memory(character["id"])
        user_profile = get_user_profile()
        summary = get_latest_summary(character["id"], conversation["id"])
        if latest_summary_is_stale(character["id"], conversation["id"]):
            events.put({"t": "status", "v": "Rebuilding story memory..."})
            summary = runtime_coordinator.run_text_task(
                text_service.summarize_memory,
                character,
                user_profile,
                pinned_memory,
                summary,
                messages,
            )
            save_summary(character["id"], conversation["id"], summary)
        lore_entries = retrieve_lore_entries(character, messages)
        story_frames = list_story_frames(conversation["id"])
        conversation_state = get_conversation_state(conversation["id"])

        text_service._set_status("preparing", "Reply request received", 0.04)  # noqa: SLF001
        text_started_at = utc_now()
        text_start = time.perf_counter()
        reply_parts: list[str] = []
        events.put({"t": "status", "v": "Waking the story engine..."})
        with runtime_coordinator.text_stream_session():
            events.put({"t": "status", "v": f"{character['display_name']} is writing..."})
            for chunk in text_service.chat_reply_stream(
                character,
                user_profile,
                pinned_memory,
                summary,
                lore_entries,
                messages,
                story_frames,
                conversation_state,
            ):
                reply_parts.append(chunk)
                events.put({"t": "tok", "v": chunk})
        reply = "".join(reply_parts).strip()
        if not reply:
            events.put({"t": "err", "v": "The story engine returned an empty reply."})
            return
        text_elapsed_s = time.perf_counter() - text_start
        assistant_message_id = add_message(conversation["id"], "assistant", reply)
        log_event(
            "chat_assistant_reply_saved",
            character_id=character["id"],
            conversation_id=conversation["id"],
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            text_elapsed_s=round(text_elapsed_s, 3),
            content=reply,
            streaming=True,
        )
        create_story_frame(
            {
                "conversation_id": conversation["id"],
                "character_id": character["id"],
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "user_input": cleaned,
                "assistant_output": reply,
                "story_summary_before": summary,
                "location_name": conversation_state.get("current_location_name", ""),
                "active_characters_json": conversation_state.get("active_characters_json", "[]"),
                "text_model": settings.ollama_model_name,
                "text_started_at": text_started_at,
                "text_completed_at": utc_now(),
                "text_elapsed_s": text_elapsed_s,
                "route_elapsed_s": time.perf_counter() - route_start,
                "status": "image_queued" if auto_image else "text_completed",
                "metadata_json": json.dumps(
                    {
                        "auto_image": bool(auto_image),
                        "resolution_preset": resolution_preset,
                        "lore_entry_count": len(lore_entries),
                        "streaming": True,
                    },
                    ensure_ascii=False,
                ),
            }
        )
        if auto_image:
            log_event(
                "chat_auto_image_queued",
                character_id=character["id"],
                conversation_id=conversation["id"],
                assistant_message_id=assistant_message_id,
                resolution_preset=resolution_preset,
                streaming=True,
            )
            image_service._set_status(  # noqa: SLF001
                "preparing",
                "Auto image request received",
                0.03,
                stage="queued",
                message_id=assistant_message_id,
            )
            start_background_image_job(
                character=character,
                conversation=conversation,
                message_id=assistant_message_id,
                messages=list_messages(conversation["id"]),
                user_profile=user_profile,
                resolution_override=parse_resolution_preset(resolution_preset),
            )
        events.put(
            {
                "t": "done",
                "message_id": assistant_message_id,
                "auto_image": bool(auto_image),
                "text_elapsed_s": round(text_elapsed_s, 1),
            }
        )
        if count_user_messages(conversation["id"]) % settings.summary_interval_user_turns == 0:
            try:
                new_summary = runtime_coordinator.run_text_task(
                    text_service.summarize_memory,
                    character,
                    user_profile,
                    pinned_memory,
                    summary,
                    list_messages(conversation["id"]),
                )
                save_summary(character["id"], conversation["id"], new_summary)
            except Exception as exc:  # pragma: no cover - cadence safety path
                log_event("summary_cadence_error", error=repr(exc), streaming=True)
    except Exception as exc:  # pragma: no cover - runtime safety path
        log_event(
            "chat_text_error",
            character_id=character["id"],
            conversation_id=conversation["id"],
            error=repr(exc),
            streaming=True,
        )
        events.put({"t": "err", "v": f"Text generation error: {exc}"})
    finally:
        events.put(None)


@app.post("/chat/{character_id}/stream")
async def send_message_stream(
    character_id: int,
    message: str = Form(...),
    auto_image: str = Form(default=""),
    resolution_preset: str = Form(default=""),
) -> StreamingResponse:
    character = get_active_character(character_id)
    conversation = ensure_conversation(character["id"])
    cleaned = message.strip()

    events: "queue.Queue[dict[str, Any] | None]" = queue.Queue()

    def event_gen():
        if not cleaned:
            yield _ndjson_line({"t": "err", "v": "Message cannot be empty."})
            return
        worker = threading.Thread(
            target=_run_streaming_chat_turn,
            args=(events, character, conversation, cleaned, auto_image, resolution_preset),
            name="companion-chat-stream",
            daemon=True,
        )
        worker.start()
        while True:
            try:
                item = events.get(timeout=600)
            except queue.Empty:
                yield _ndjson_line({"t": "err", "v": "Timed out waiting for the story engine."})
                return
            if item is None:
                return
            yield _ndjson_line(item)

    return StreamingResponse(
        event_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/runtime/retry-warmup")
async def retry_warmup_route() -> dict[str, Any]:
    runtime_coordinator.retry_warmup()
    return {"ok": True}


@app.post("/runtime/shutdown")
async def shutdown_app_route() -> dict[str, Any]:
    """Full power-off: unload models, stop Ollama and A1111, then exit the server.

    Responds immediately; the work happens in a background thread so the UI
    can watch the unload phases through /status until the server goes away.
    If a generation is mid-flight, the runtime lock makes shutdown wait for
    it to finish rather than corrupting state.
    """
    log_event("user_shutdown_requested")

    def _shutdown_worker() -> None:
        try:
            runtime_coordinator.shutdown()
        except Exception as exc:  # pragma: no cover - shutdown safety path
            log_event("user_shutdown_error", error=repr(exc))
        try:
            # Power-off means the whole companion stack, including backends
            # this process did not start itself.
            image_service._stop_orphaned_a1111_children()  # noqa: SLF001
        except Exception:
            pass
        try:
            # Second sweep: an Ollama runner can outlive the first sweep if it
            # was still winding down when its parent server was killed.
            time.sleep(2)
            text_service._stop_orphaned_ollama_runners()  # noqa: SLF001
        except Exception:
            pass
        log_event("user_shutdown_backends_done")
        time.sleep(0.7)
        try:
            signal.raise_signal(signal.SIGINT)
        except Exception:
            os._exit(0)
        time.sleep(8)
        os._exit(0)

    threading.Thread(target=_shutdown_worker, name="companion-shutdown", daemon=True).start()
    return {
        "ok": True,
        "detail": "Unloading models and stopping local engines; the server will close itself.",
    }


@app.post("/messages/{message_id}/image", response_class=HTMLResponse)
async def generate_image(
    request: Request,
    message_id: int,
    character_id: int = Form(...),
    image_note: str = Form(default=""),
    resolution_preset: str = Form(default=""),
) -> HTMLResponse:
    character = get_active_character(character_id)
    message = get_message(message_id)
    if not message:
        conversation = ensure_conversation(character["id"])
        return render_story_timeline(
            request,
            active_character=character,
            messages=list_messages(conversation["id"]),
            images_by_message=build_images_by_message(conversation["id"]),
            latest_assistant_id=latest_assistant_message_id(list_messages(conversation["id"])),
            error_message="That response could not be found.",
        )
    conversation = get_conversation(message["conversation_id"])
    if not conversation:
        conversation = ensure_conversation(character["id"])
    all_messages = list_messages(conversation["id"])
    messages = [row for row in all_messages if row["id"] <= message_id]
    pinned_memory = get_pinned_memory(character["id"])
    user_profile = get_user_profile()
    status_message = ""
    error_message = ""
    resolution_override = parse_resolution_preset(resolution_preset)
    image_service._set_status(  # noqa: SLF001
        "preparing",
        "Image request received",
        0.03,
        stage="queued",
        message_id=message_id,
    )

    try:
        await create_image_for_message(
            character=character,
            conversation=conversation,
            message_id=message_id,
            messages=messages,
            user_profile=user_profile,
            image_note=image_note,
            resolution_override=resolution_override,
        )
        status_message = "Image generated for this scene beat."
    except Exception as exc:  # pragma: no cover - runtime safety path
        error_message = f"Image generation error: {exc}"
        update_story_frame_for_assistant_message(
            message_id,
            {
                "status": "image_error",
                "error": str(exc),
                "image_completed_at": utc_now(),
            },
        )
        image_service._set_status(  # noqa: SLF001
            "error",
            f"Image generation failed: {exc}",
            0.0,
            stage="error",
            message_id=message_id,
        )

    return render_story_timeline(
        request,
        active_character=character,
        messages=all_messages,
        images_by_message=build_images_by_message(conversation["id"]),
        frames_by_message=build_frames_by_assistant_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(all_messages),
        status_message=status_message,
        error_message=error_message,
    )


@app.post("/images/{image_id}/delete", response_class=HTMLResponse)
async def delete_image_block(request: Request, image_id: int, character_id: int = Form(...)) -> HTMLResponse:
    character = get_active_character(character_id)
    image_row = delete_image_request(image_id)
    clear_story_frame_image(image_id)
    conversation = ensure_conversation(character["id"])
    if image_row and image_row.get("conversation_id"):
        conversation = get_conversation(int(image_row["conversation_id"])) or conversation
        remove_image_files([image_row])
    messages = list_messages(conversation["id"])
    return render_story_timeline(
        request,
        active_character=character,
        messages=messages,
        images_by_message=build_images_by_message(conversation["id"]),
        frames_by_message=build_frames_by_assistant_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(messages),
        status_message="Image block deleted.",
    )


@app.post("/images/{image_id}/regenerate", response_class=HTMLResponse)
async def regenerate_image_block(request: Request, image_id: int, character_id: int = Form(...)) -> HTMLResponse:
    character = get_active_character(character_id)
    image_row = get_image_request(image_id)
    conversation = ensure_conversation(character["id"])
    if not image_row:
        messages = list_messages(conversation["id"])
        return render_story_timeline(
            request,
            active_character=character,
            messages=messages,
            images_by_message=build_images_by_message(conversation["id"]),
            latest_assistant_id=latest_assistant_message_id(messages),
            error_message="That image could not be found.",
        )

    conversation = get_conversation(int(image_row["conversation_id"])) or conversation
    messages = list_messages(conversation["id"])
    old_stage1 = image_row.get("stage1_output_path")
    old_final = image_row.get("output_path")
    status_message = ""
    error_message = ""
    image_service._set_status(  # noqa: SLF001
        "preparing",
        "Image regeneration requested",
        0.03,
        stage="queued",
        message_id=image_row.get("message_id"),
        image_id=image_id,
    )

    try:
        image_started_at = utc_now()
        image_start = time.perf_counter()
        if image_row.get("message_id"):
            update_story_frame_for_assistant_message(
                int(image_row["message_id"]),
                {
                    "image_started_at": image_started_at,
                    "image_backend": "a1111",
                    "image_preset": (
                        f"{int(image_row['base_width'])}x{int(image_row['base_height'])}"
                        f"->{int(image_row['target_width'])}x{int(image_row['target_height'])}"
                    ),
                    "status": "image_regenerating",
                },
            )
        payload = await run_in_threadpool(
            runtime_coordinator.run_image_task,
            image_service.generate,
            character,
            int(image_row["conversation_id"]),
            image_row.get("message_id"),
            image_id,
            image_row["scene_summary"],
            image_row["positive_prompt"],
            image_row["negative_prompt"],
            {
                "base_width": int(image_row["base_width"]),
                "base_height": int(image_row["base_height"]),
                "target_width": int(image_row["target_width"]),
                "target_height": int(image_row["target_height"]),
            },
        )
        update_image_request(image_id, payload)
        if image_row.get("message_id"):
            update_story_frame_for_assistant_message(
                int(image_row["message_id"]),
                {
                    "image_request_id": image_id,
                    "scene_summary": payload.get("scene_summary", image_row["scene_summary"]),
                    "image_positive_prompt": payload.get("positive_prompt", image_row["positive_prompt"]),
                    "image_negative_prompt": payload.get("negative_prompt", image_row["negative_prompt"]),
                    "image_output_path": payload.get("output_path", ""),
                    "image_completed_at": utc_now(),
                    "image_elapsed_s": time.perf_counter() - image_start,
                    "status": "image_completed",
                    "error": "",
                },
            )
        remove_image_files(
            [
                {
                    "stage1_output_path": old_stage1,
                    "output_path": old_final,
                }
            ]
        )
        status_message = "Image regenerated."
    except Exception as exc:  # pragma: no cover - runtime safety path
        error_message = f"Image regeneration error: {exc}"
        if image_row.get("message_id"):
            update_story_frame_for_assistant_message(
                int(image_row["message_id"]),
                {
                    "status": "image_error",
                    "error": str(exc),
                    "image_completed_at": utc_now(),
                },
            )
        image_service._set_status(  # noqa: SLF001
            "error",
            f"Image regeneration failed: {exc}",
            0.0,
            stage="error",
            message_id=image_row.get("message_id"),
            image_id=image_id,
        )

    return render_story_timeline(
        request,
        active_character=character,
        messages=messages,
        images_by_message=build_images_by_message(conversation["id"]),
        frames_by_message=build_frames_by_assistant_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(messages),
        status_message=status_message,
        error_message=error_message,
    )


@app.post("/messages/{message_id}/delete", response_class=HTMLResponse)
async def delete_message_block(request: Request, message_id: int, character_id: int = Form(...)) -> HTMLResponse:
    character = get_active_character(character_id)
    message = get_message(message_id)
    conversation = ensure_conversation(character["id"])
    if message:
        conversation = get_conversation(message["conversation_id"]) or conversation
        removed_images = delete_images_for_message(message_id)
        remove_image_files(removed_images)
        mark_latest_summary_stale(character["id"], conversation["id"])
        delete_message(message_id)
    messages = list_messages(conversation["id"])
    return render_story_timeline(
        request,
        active_character=character,
        messages=messages,
        images_by_message=build_images_by_message(conversation["id"]),
        frames_by_message=build_frames_by_assistant_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(messages),
        status_message="Scene block deleted.",
    )


@app.post("/messages/{message_id}/regenerate", response_class=HTMLResponse)
async def regenerate_message_block(request: Request, message_id: int, character_id: int = Form(...)) -> HTMLResponse:
    route_start = time.perf_counter()
    character = get_active_character(character_id)
    message = get_message(message_id)
    conversation = ensure_conversation(character["id"])
    if not message:
        messages = list_messages(conversation["id"])
        return render_story_timeline(
            request,
            active_character=character,
            messages=messages,
            images_by_message=build_images_by_message(conversation["id"]),
            latest_assistant_id=latest_assistant_message_id(messages),
            error_message="That response could not be found.",
        )

    conversation = get_conversation(message["conversation_id"]) or conversation
    messages = list_messages(conversation["id"])
    latest_id = latest_assistant_message_id(messages)
    if latest_id != message_id:
        return render_story_timeline(
            request,
            active_character=character,
            messages=messages,
            images_by_message=build_images_by_message(conversation["id"]),
            latest_assistant_id=latest_id,
            error_message="Only the latest response can be regenerated for now.",
        )

    remove_image_files(delete_images_for_message(message_id))
    delete_message(message_id)
    messages = list_messages(conversation["id"])
    pinned_memory = get_pinned_memory(character["id"])
    user_profile = get_user_profile()
    mark_latest_summary_stale(character["id"], conversation["id"])
    summary = await ensure_summary_context(character, user_profile, conversation["id"], pinned_memory, messages)
    lore_entries = retrieve_lore_entries(character, messages)
    story_frames = list_story_frames(conversation["id"])
    conversation_state = get_conversation_state(conversation["id"])
    error_message = ""
    status_message = ""
    text_service._set_status("preparing", "Regenerating latest reply", 0.04)  # noqa: SLF001
    latest_user = next((row for row in reversed(messages) if row["role"] == "user"), None)
    text_started_at = utc_now()
    text_start = time.perf_counter()
    try:
        reply = await run_in_threadpool(
            runtime_coordinator.run_text_task,
            text_service.chat_reply,
            character,
            user_profile,
            pinned_memory,
            summary,
            lore_entries,
            messages,
            story_frames,
            conversation_state,
        )
        text_elapsed_s = time.perf_counter() - text_start
        assistant_message_id = add_message(conversation["id"], "assistant", reply)
        create_story_frame(
            {
                "conversation_id": conversation["id"],
                "character_id": character["id"],
                "user_message_id": latest_user.get("id") if latest_user else None,
                "assistant_message_id": assistant_message_id,
                "user_input": latest_user.get("content", "") if latest_user else "",
                "assistant_output": reply,
                "story_summary_before": summary,
                "location_name": conversation_state.get("current_location_name", ""),
                "active_characters_json": conversation_state.get("active_characters_json", "[]"),
                "text_model": settings.ollama_model_name,
                "text_started_at": text_started_at,
                "text_completed_at": utc_now(),
                "text_elapsed_s": text_elapsed_s,
                "route_elapsed_s": time.perf_counter() - route_start,
                "status": "text_completed",
                "metadata_json": json.dumps(
                    {
                        "regenerated_from_message_id": message_id,
                        "lore_entry_count": len(lore_entries),
                    },
                    ensure_ascii=False,
                ),
            }
        )
        messages = list_messages(conversation["id"])
        status_message = f"{character['display_name']} response regenerated."
    except Exception as exc:  # pragma: no cover - runtime safety path
        error_message = f"Text generation error: {exc}"

    return render_story_timeline(
        request,
        active_character=character,
        messages=messages,
        images_by_message=build_images_by_message(conversation["id"]),
        frames_by_message=build_frames_by_assistant_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(messages),
        status_message=status_message,
        error_message=error_message,
    )
