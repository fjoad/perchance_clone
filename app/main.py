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
    init_db,
    list_characters,
    list_images_for_conversation,
    list_messages,
    replace_pinned_memory,
    save_character,
    save_image_request,
    save_summary,
    seed_sample_character,
    slug_exists,
    update_image_request,
)
from .services.image_generation import image_service
from .services import prompts
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
    yield
    text_service.unload()
    image_service.unload()


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
            "image_cfg": settings.image,
            "resolution_options": image_resolution_options(),
            "status_message": status_message,
            "error_message": error_message,
        },
    )


def render_character_form(request: Request, character: dict[str, Any] | None = None) -> HTMLResponse:
    pinned_memory = get_pinned_memory(character["id"]) if character else ""
    return templates.TemplateResponse(
        request=request,
        name="partials/character_form.html",
        context={"character": character, "pinned_memory": pinned_memory},
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
    pinned_memory: str,
    status_message: str = "",
    error_message: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="partials/right_panel_v2.html",
        context={
            "active_character": active_character,
            "pinned_memory": pinned_memory,
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
    return templates.TemplateResponse(
        request=request,
        name="partials/image_generation_response.html",
        context={
            "active_character": active_character,
            "messages": messages,
            "images_by_message": images_by_message,
            "latest_assistant_id": latest_assistant_id,
            "pinned_memory": pinned_memory,
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
async def save_character_route(
    request: Request,
    id: int | None = Form(default=None),
    display_name: str = Form(...),
    persona_summary: str = Form(default=""),
    personality_traits: str = Form(default=""),
    speaking_style: str = Form(default=""),
    backstory: str = Form(default=""),
    relationship_frame: str = Form(default=""),
    boundaries: str = Form(default=""),
    appearance: str = Form(default=""),
    example_dialogue: str = Form(default=""),
    default_visual_style: str = Form(default=""),
    pinned_memory: str = Form(default=""),
) -> Response:
    display_name = display_name.strip()
    if not display_name:
        return Response("Display name is required.", status_code=400)
    slug = unique_slug(slugify(display_name), current_id=id)
    character_id = save_character(
        {
            "id": id,
            "slug": slug,
            "display_name": display_name,
            "persona_summary": persona_summary.strip(),
            "personality_traits": personality_traits.strip(),
            "speaking_style": speaking_style.strip(),
            "backstory": backstory.strip(),
            "relationship_frame": relationship_frame.strip(),
            "boundaries": boundaries.strip(),
            "appearance": appearance.strip(),
            "example_dialogue": example_dialogue.strip(),
            "default_visual_style": default_visual_style.strip(),
            "is_active": True,
        }
    )
    replace_pinned_memory(character_id, pinned_memory.strip())
    destination = f"/?character_id={character_id}"
    if request.headers.get("HX-Request") == "true":
        return Response(headers={"HX-Redirect": destination})
    return RedirectResponse(destination, status_code=303)


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
    summary = get_latest_summary(character["id"], conversation["id"])

    error_message = ""
    try:
        image_service.unload()
        reply = await run_in_threadpool(text_service.chat_reply, character, pinned_memory, summary, messages)
        add_message(conversation["id"], "assistant", reply)
        messages = list_messages(conversation["id"])
        if count_user_messages(conversation["id"]) % settings.summary_interval_user_turns == 0:
            new_summary = await run_in_threadpool(
                text_service.summarize_memory,
                character,
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
    status_message = ""
    error_message = ""
    resolution_override = parse_resolution_preset(resolution_preset)

    try:
        override = prompts.parse_prompt_override(image_note)
        if override:
            positive_prompt, negative_prompt = override
            scene_summary = image_note.strip()
        else:
            scene_summary = await run_in_threadpool(text_service.extract_scene, character, messages, image_note.strip())
            positive_prompt, negative_prompt = await run_in_threadpool(
                text_service.compose_image_prompts,
                character,
                scene_summary,
            )
        text_service.unload()
        payload = await run_in_threadpool(
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

    try:
        text_service.unload()
        payload = await run_in_threadpool(
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
            error_message="Only the latest narrator response can be regenerated for now.",
        )

    remove_image_files(delete_images_for_message(message_id))
    delete_message(message_id)
    messages = list_messages(conversation["id"])
    pinned_memory = get_pinned_memory(character["id"])
    summary = get_latest_summary(character["id"], conversation["id"])
    error_message = ""
    status_message = ""
    try:
        image_service.unload()
        reply = await run_in_threadpool(text_service.chat_reply, character, pinned_memory, summary, messages)
        add_message(conversation["id"], "assistant", reply)
        messages = list_messages(conversation["id"])
        status_message = "Narrator response regenerated."
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
