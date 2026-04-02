from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


@contextmanager
def connect() -> Iterable[sqlite3.Connection]:
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                persona_summary TEXT NOT NULL DEFAULT '',
                personality_traits TEXT NOT NULL DEFAULT '',
                speaking_style TEXT NOT NULL DEFAULT '',
                backstory TEXT NOT NULL DEFAULT '',
                relationship_frame TEXT NOT NULL DEFAULT '',
                boundaries TEXT NOT NULL DEFAULT '',
                appearance TEXT NOT NULL DEFAULT '',
                example_dialogue TEXT NOT NULL DEFAULT '',
                default_visual_style TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS memory_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                conversation_id INTEGER,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS image_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                conversation_id INTEGER,
                message_id INTEGER,
                scene_summary TEXT NOT NULL,
                positive_prompt TEXT NOT NULL,
                negative_prompt TEXT NOT NULL,
                base_width INTEGER NOT NULL,
                base_height INTEGER NOT NULL,
                target_width INTEGER NOT NULL,
                target_height INTEGER NOT NULL,
                denoise_strength REAL NOT NULL,
                seed INTEGER NOT NULL,
                stage1_output_path TEXT,
                output_path TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
            );
            """
        )
        image_columns = {row["name"] for row in conn.execute("PRAGMA table_info(image_requests)").fetchall()}
        if "message_id" not in image_columns:
            conn.execute("ALTER TABLE image_requests ADD COLUMN message_id INTEGER")


def list_characters() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM characters WHERE is_active = 1 ORDER BY display_name COLLATE NOCASE"
        ).fetchall()
    return [to_dict(row) for row in rows]


def get_character(character_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()
    return to_dict(row)


def get_first_character() -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM characters WHERE is_active = 1 ORDER BY id ASC LIMIT 1"
        ).fetchone()
    return to_dict(row)


def slug_exists(slug: str, exclude_id: int | None = None) -> bool:
    query = "SELECT 1 FROM characters WHERE slug = ?"
    params: list[Any] = [slug]
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    with connect() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    return row is not None


def save_character(payload: dict[str, Any]) -> int:
    now = utc_now()
    character_id = payload.get("id")
    fields = {
        "slug": payload["slug"],
        "display_name": payload["display_name"],
        "persona_summary": payload.get("persona_summary", ""),
        "personality_traits": payload.get("personality_traits", ""),
        "speaking_style": payload.get("speaking_style", ""),
        "backstory": payload.get("backstory", ""),
        "relationship_frame": payload.get("relationship_frame", ""),
        "boundaries": payload.get("boundaries", ""),
        "appearance": payload.get("appearance", ""),
        "example_dialogue": payload.get("example_dialogue", ""),
        "default_visual_style": payload.get("default_visual_style", ""),
        "is_active": int(payload.get("is_active", True)),
    }
    with connect() as conn:
        if character_id:
            conn.execute(
                """
                UPDATE characters
                SET slug = :slug,
                    display_name = :display_name,
                    persona_summary = :persona_summary,
                    personality_traits = :personality_traits,
                    speaking_style = :speaking_style,
                    backstory = :backstory,
                    relationship_frame = :relationship_frame,
                    boundaries = :boundaries,
                    appearance = :appearance,
                    example_dialogue = :example_dialogue,
                    default_visual_style = :default_visual_style,
                    is_active = :is_active,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                {**fields, "updated_at": now, "id": character_id},
            )
            return int(character_id)
        cur = conn.execute(
            """
            INSERT INTO characters (
                slug, display_name, persona_summary, personality_traits, speaking_style,
                backstory, relationship_frame, boundaries, appearance, example_dialogue,
                default_visual_style, is_active, created_at, updated_at
            ) VALUES (
                :slug, :display_name, :persona_summary, :personality_traits, :speaking_style,
                :backstory, :relationship_frame, :boundaries, :appearance, :example_dialogue,
                :default_visual_style, :is_active, :created_at, :updated_at
            )
            """,
            {**fields, "created_at": now, "updated_at": now},
        )
        return int(cur.lastrowid)


def ensure_conversation(character_id: int) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM conversations
            WHERE character_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (character_id,),
        ).fetchone()
        if row:
            return to_dict(row)  # type: ignore[return-value]
        title = f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        now = utc_now()
        cur = conn.execute(
            """
            INSERT INTO conversations (character_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (character_id, title, now, now),
        )
        new_row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return to_dict(new_row)  # type: ignore[return-value]


def get_conversation(conversation_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    return to_dict(row)


def list_messages(conversation_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()
    return [to_dict(row) for row in rows]


def get_message(message_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    return to_dict(row)


def add_message(conversation_id: int, role: str, content: str) -> int:
    now = utc_now()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, role, content, now),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
    return int(cur.lastrowid)


def delete_message(message_id: int) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT conversation_id FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        if not row:
            return
        now = utc_now()
        conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, row["conversation_id"]),
        )


def count_user_messages(conversation_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM messages WHERE conversation_id = ? AND role = 'user'",
            (conversation_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def get_pinned_memory(character_id: int) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT content FROM memory_snapshots
            WHERE character_id = ? AND kind = 'pinned'
            ORDER BY id DESC LIMIT 1
            """,
            (character_id,),
        ).fetchone()
    return row["content"] if row else ""


def replace_pinned_memory(character_id: int, content: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM memory_snapshots WHERE character_id = ? AND kind = 'pinned'",
            (character_id,),
        )
        if content.strip():
            conn.execute(
                """
                INSERT INTO memory_snapshots (character_id, conversation_id, kind, content, created_at)
                VALUES (?, NULL, 'pinned', ?, ?)
                """,
                (character_id, content.strip(), utc_now()),
            )


def get_latest_summary(character_id: int, conversation_id: int) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT content FROM memory_snapshots
            WHERE character_id = ? AND conversation_id = ? AND kind = 'summary'
            ORDER BY id DESC LIMIT 1
            """,
            (character_id, conversation_id),
        ).fetchone()
    return row["content"] if row else ""


def save_summary(character_id: int, conversation_id: int, content: str) -> None:
    if not content.strip():
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO memory_snapshots (character_id, conversation_id, kind, content, created_at)
            VALUES (?, ?, 'summary', ?, ?)
            """,
            (character_id, conversation_id, content.strip(), utc_now()),
        )


def save_image_request(payload: dict[str, Any]) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO image_requests (
                character_id, conversation_id, message_id, scene_summary, positive_prompt, negative_prompt,
                base_width, base_height, target_width, target_height, denoise_strength,
                seed, stage1_output_path, output_path, status, error, created_at
            ) VALUES (
                :character_id, :conversation_id, :message_id, :scene_summary, :positive_prompt, :negative_prompt,
                :base_width, :base_height, :target_width, :target_height, :denoise_strength,
                :seed, :stage1_output_path, :output_path, :status, :error, :created_at
            )
            """,
            {**payload, "created_at": utc_now()},
        )
    return int(cur.lastrowid)


def get_latest_image_for_character(character_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM image_requests
            WHERE character_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (character_id,),
        ).fetchone()
    return to_dict(row)


def get_image_request(image_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM image_requests
            WHERE id = ?
            """,
            (image_id,),
        ).fetchone()
    return to_dict(row)


def update_image_request(image_id: int, payload: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE image_requests
            SET character_id = :character_id,
                conversation_id = :conversation_id,
                message_id = :message_id,
                scene_summary = :scene_summary,
                positive_prompt = :positive_prompt,
                negative_prompt = :negative_prompt,
                base_width = :base_width,
                base_height = :base_height,
                target_width = :target_width,
                target_height = :target_height,
                denoise_strength = :denoise_strength,
                seed = :seed,
                stage1_output_path = :stage1_output_path,
                output_path = :output_path,
                status = :status,
                error = :error
            WHERE id = :image_id
            """,
            {**payload, "image_id": image_id},
        )


def list_images_for_conversation(conversation_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM image_requests
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()
    return [to_dict(row) for row in rows]


def list_images_for_message(message_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM image_requests
            WHERE message_id = ?
            ORDER BY id ASC
            """,
            (message_id,),
        ).fetchall()
    return [to_dict(row) for row in rows]


def delete_images_for_message(message_id: int) -> list[dict[str, Any]]:
    rows = list_images_for_message(message_id)
    with connect() as conn:
        conn.execute("DELETE FROM image_requests WHERE message_id = ?", (message_id,))
    return rows


def delete_image_request(image_id: int) -> dict[str, Any] | None:
    row = get_image_request(image_id)
    if not row:
        return None
    with connect() as conn:
        conn.execute("DELETE FROM image_requests WHERE id = ?", (image_id,))
    return row


def seed_sample_character() -> None:
    if get_first_character():
        return
    payload = {
        "slug": "sample-companion",
        "display_name": "Astra Vale",
        "persona_summary": "A warm, observant companion with an intimate but grounded presence.",
        "personality_traits": "affectionate, perceptive, teasing, patient, emotionally articulate",
        "speaking_style": "Natural, vivid, emotionally warm, avoids assistant-like phrasing, stays in character.",
        "backstory": "Astra is written as a polished flagship sample companion for the first vertical slice.",
        "relationship_frame": "A recurring companion who remembers emotional details and responds with continuity.",
        "boundaries": "No meta talk unless asked. Avoid sounding like a helpdesk assistant.",
        "appearance": "adult woman, dark hair, soft waves, expressive eyes, elegant features, refined casual style",
        "example_dialogue": "You always notice the little things first, and somehow that makes everything feel calmer.",
        "default_visual_style": "cinematic, intimate, polished anime-inspired realism, soft dramatic lighting",
        "is_active": True,
    }
    character_id = save_character(payload)
    replace_pinned_memory(
        character_id,
        "The companion should feel emotionally consistent, warm, and present across long conversations.",
    )


def dumps_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)
