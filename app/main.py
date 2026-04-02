from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import ensure_runtime_dirs, image_resolution_options, settings
from .db import (
    add_message,
    count_user_messages,
    delete_lore_entry,
    delete_image_request,
    delete_images_for_message,
    delete_message,
    ensure_conversation,
    get_character,
    get_conversation,
    get_first_character,
    get_image_request,
    get_latest_summary,
    get_message,
    get_pinned_memory,
    get_user_profile,
    init_db,
    latest_summary_is_stale,
    list_characters,
    list_images_for_conversation,
    list_lore_entries,
    list_messages,
    mark_latest_summary_stale,
    replace_pinned_memory,
    save_character,
    save_image_request,
    save_lore_entry,
    save_summary,
    save_user_profile,
    seed_atago_character,
    seed_default_user_profile,
    seed_sample_character,
    slug_exists,
    update_image_request,
)
from .services.image_generation import image_service
from .services import prompts
from .services.memory import retrieve_lore_entries
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
    init_db()
    seed_sample_character()
    seed_default_user_profile()
    seed_atago_character()
    runtime_coordinator.startup()
    yield
    runtime_coordinator.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
app.mount("/media", StaticFiles(directory=str(settings.outputs_dir)), name="media")
templates = Jinja2Templates(directory=str(settings.templates_dir))


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
    return templates.TemplateResponse(
        request=request,
        name="partials/right_panel_v2.html",
        context={
            "active_character": active_character,
            "user_profile": user_profile,
            "pinned_memory": pinned_memory,
            "lore_entries": lore_entries,
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, character_id: int | None = None) -> HTMLResponse:
    return render_index(request, character_id=character_id)


@app.get("/status")
async def status() -> dict[str, Any]:
    return {
        "text": text_service.snapshot(),
        "image": image_service.snapshot(),
    }


@app.get("/status/stream")
async def status_stream() -> StreamingResponse:
    async def event_stream():
        last_payload = ""
        while True:
            payload = json.dumps({"text": text_service.snapshot(), "image": image_service.snapshot()})
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


@app.post("/chat/{character_id}", response_class=HTMLResponse)
async def send_message(
    request: Request,
    character_id: int,
    message: str = Form(...),
) -> HTMLResponse:
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
    add_message(conversation["id"], "user", cleaned)
    messages = list_messages(conversation["id"])
    pinned_memory = get_pinned_memory(character["id"])
    user_profile = get_user_profile()
    summary = await ensure_summary_context(character, user_profile, conversation["id"], pinned_memory, messages)
    lore_entries = retrieve_lore_entries(character, messages)

    error_message = ""
    text_service._set_status("preparing", "Reply request received", 0.04)  # noqa: SLF001
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
        )
        add_message(conversation["id"], "assistant", reply)
        messages = list_messages(conversation["id"])
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
    except Exception as exc:  # pragma: no cover - runtime safety path
        error_message = f"Text generation error: {exc}"
    return render_story_timeline(
        request,
        active_character=character,
        messages=messages,
        images_by_message=build_images_by_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(messages),
        error_message=error_message,
    )


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
        override = prompts.parse_prompt_override(image_note)
        if override:
            positive_prompt, negative_prompt = override
            scene_summary = image_note.strip()
        else:
            text_service._set_status("preparing", "Preparing scene context", 0.08)  # noqa: SLF001
            scene_summary = await run_in_threadpool(
                runtime_coordinator.run_text_task,
                text_service.extract_scene,
                character,
                user_profile,
                messages,
                image_note.strip(),
            )
            positive_prompt, negative_prompt = await run_in_threadpool(
                runtime_coordinator.run_text_task,
                text_service.compose_image_prompts,
                character,
                user_profile,
                scene_summary,
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
        save_image_request(payload)
        status_message = "Image generated for this scene beat."
    except Exception as exc:  # pragma: no cover - runtime safety path
        error_message = f"Image generation error: {exc}"
        image_service._set_status("error", "Image generation failed", 0.0)

    return render_story_timeline(
        request,
        active_character=character,
        messages=all_messages,
        images_by_message=build_images_by_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(all_messages),
        status_message=status_message,
        error_message=error_message,
    )


@app.post("/images/{image_id}/delete", response_class=HTMLResponse)
async def delete_image_block(request: Request, image_id: int, character_id: int = Form(...)) -> HTMLResponse:
    character = get_active_character(character_id)
    image_row = delete_image_request(image_id)
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
        image_service._set_status("error", "Image regeneration failed", 0.0)

    return render_story_timeline(
        request,
        active_character=character,
        messages=messages,
        images_by_message=build_images_by_message(conversation["id"]),
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
        latest_assistant_id=latest_assistant_message_id(messages),
        status_message="Scene block deleted.",
    )


@app.post("/messages/{message_id}/regenerate", response_class=HTMLResponse)
async def regenerate_message_block(request: Request, message_id: int, character_id: int = Form(...)) -> HTMLResponse:
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
    error_message = ""
    status_message = ""
    text_service._set_status("preparing", "Regenerating latest reply", 0.04)  # noqa: SLF001
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
        )
        add_message(conversation["id"], "assistant", reply)
        messages = list_messages(conversation["id"])
        status_message = f"{character['display_name']} response regenerated."
    except Exception as exc:  # pragma: no cover - runtime safety path
        error_message = f"Text generation error: {exc}"

    return render_story_timeline(
        request,
        active_character=character,
        messages=messages,
        images_by_message=build_images_by_message(conversation["id"]),
        latest_assistant_id=latest_assistant_message_id(messages),
        status_message=status_message,
        error_message=error_message,
    )
