from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import ensure_runtime_dirs, settings
from .db import (
    add_message,
    count_user_messages,
    ensure_conversation,
    get_character,
    get_first_character,
    get_latest_image_for_character,
    get_latest_summary,
    get_pinned_memory,
    init_db,
    list_characters,
    list_messages,
    replace_pinned_memory,
    save_character,
    save_image_request,
    save_summary,
    seed_sample_character,
    slug_exists,
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
    latest_image = with_image_urls(get_latest_image_for_character(active_character["id"]))
    pinned_memory = get_pinned_memory(active_character["id"])
    return templates.TemplateResponse(
        request=request,
        name="index_v2.html",
        context={
            "app_name": settings.app_name,
            "characters": characters,
            "active_character": active_character,
            "conversation": conversation,
            "messages": messages,
            "latest_image": latest_image,
            "pinned_memory": pinned_memory,
            "image_cfg": settings.image,
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
    messages: list[dict[str, Any]],
    latest_image: dict[str, Any] | None = None,
    error_message: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="partials/story_timeline.html",
        context={"messages": messages, "latest_image": latest_image, "error_message": error_message},
    )


def render_right_panel(
    request: Request,
    *,
    active_character: dict[str, Any],
    latest_image: dict[str, Any] | None,
    pinned_memory: str,
    status_message: str = "",
    error_message: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="partials/right_panel_v2.html",
        context={
            "active_character": active_character,
            "latest_image": with_image_urls(latest_image),
            "pinned_memory": pinned_memory,
            "status_message": status_message,
            "error_message": error_message,
            "image_cfg": settings.image,
        },
    )


def render_image_response(
    request: Request,
    *,
    active_character: dict[str, Any],
    messages: list[dict[str, Any]],
    latest_image: dict[str, Any] | None,
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
            "latest_image": latest_image,
            "pinned_memory": pinned_memory,
            "status_message": status_message,
            "error_message": error_message,
            "image_cfg": settings.image,
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
            messages=list_messages(conversation["id"]),
            latest_image=with_image_urls(get_latest_image_for_character(character["id"])),
            error_message="Message cannot be empty.",
        )
    add_message(conversation["id"], "user", cleaned)
    messages = list_messages(conversation["id"])
    pinned_memory = get_pinned_memory(character["id"])
    summary = get_latest_summary(character["id"], conversation["id"])

    error_message = ""
    try:
        image_service.unload()
        reply = text_service.chat_reply(character, pinned_memory, summary, messages)
        add_message(conversation["id"], "assistant", reply)
        messages = list_messages(conversation["id"])
        if count_user_messages(conversation["id"]) % settings.summary_interval_user_turns == 0:
            new_summary = text_service.summarize_memory(character, pinned_memory, summary, messages)
            save_summary(character["id"], conversation["id"], new_summary)
    except Exception as exc:  # pragma: no cover - runtime safety path
        error_message = f"Text generation error: {exc}"
    return render_story_timeline(
        request,
        messages=messages,
        latest_image=with_image_urls(get_latest_image_for_character(character["id"])),
        error_message=error_message,
    )


@app.post("/images/{character_id}", response_class=HTMLResponse)
async def generate_image(
    request: Request,
    character_id: int,
    image_note: str = Form(default=""),
) -> HTMLResponse:
    character = get_active_character(character_id)
    conversation = ensure_conversation(character["id"])
    messages = list_messages(conversation["id"])
    pinned_memory = get_pinned_memory(character["id"])
    latest_image = with_image_urls(get_latest_image_for_character(character["id"]))
    status_message = ""
    error_message = ""

    try:
        override = prompts.parse_prompt_override(image_note)
        if override:
            positive_prompt, negative_prompt = override
            scene_summary = image_note.strip()
        else:
            scene_summary = text_service.extract_scene(character, messages, image_note.strip())
            positive_prompt, negative_prompt = text_service.compose_image_prompts(character, scene_summary)
        text_service.unload()
        payload = image_service.generate(
            character,
            conversation["id"],
            scene_summary,
            positive_prompt,
            negative_prompt,
        )
        save_image_request(payload)
        latest_image = with_image_urls(get_latest_image_for_character(character["id"]))
        status_message = "Image generated with the two-stage hires workflow."
    except Exception as exc:  # pragma: no cover - runtime safety path
        error_message = f"Image generation error: {exc}"
        image_service._set_status("error", "Image generation failed", 0.0)

    return render_image_response(
        request,
        active_character=character,
        messages=messages,
        latest_image=latest_image,
        pinned_memory=pinned_memory,
        status_message=status_message,
        error_message=error_message,
    )
