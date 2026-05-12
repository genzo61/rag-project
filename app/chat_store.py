from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data") / "chat_history.sqlite3"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_chat_store() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
            ON chat_messages(session_id, created_at)
            """
        )


def _title_from_message(message: str) -> str:
    title = " ".join((message or "").strip().split())
    if not title:
        return "Yeni sohbet"
    return title[:60]


def _next_chat_title() -> str:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT title
            FROM chat_sessions
            WHERE title GLOB 'Chat [0-9]*'
            """
        ).fetchall()

    max_number = 0
    for row in rows:
        title = str(row["title"] or "")
        try:
            number = int(title.replace("Chat ", "", 1))
        except ValueError:
            continue
        max_number = max(max_number, number)

    return f"Chat {max_number + 1}"


def create_session(title: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    now = _now_iso()
    session_id = session_id or uuid.uuid4().hex
    title = _title_from_message(title or "") if title else _next_chat_title()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, title, now, now),
        )
    return {
        "id": session_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
    }


def ensure_session(session_id: str | None) -> dict[str, Any] | None:
    if session_id:
        existing = get_session(session_id)
        if existing:
            return existing
    return None


def get_session(session_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM chat_sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def list_sessions(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                s.id,
                s.title,
                s.created_at,
                s.updated_at,
                (
                    SELECT content
                    FROM chat_messages m
                    WHERE m.session_id = s.id
                    ORDER BY m.created_at DESC
                    LIMIT 1
                ) AS last_message,
                (
                    SELECT COUNT(*)
                    FROM chat_messages m
                    WHERE m.session_id = s.id
                ) AS message_count
            FROM chat_sessions s
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_message(session_id: str, role: str, content: str) -> dict[str, Any]:
    now = _now_iso()
    message_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (id, session_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (message_id, session_id, role, content, now),
        )
        conn.execute(
            """
            UPDATE chat_sessions
            SET updated_at = ?
            WHERE id = ?
            """,
            (now, session_id),
        )
    return {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": now,
    }


def get_messages(session_id: str, limit: int = 40) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def update_session_title(session_id: str, title: str) -> dict[str, Any] | None:
    cleaned = _title_from_message(title)
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE chat_sessions
            SET title = ?, updated_at = ?
            WHERE id = ?
            """,
            (cleaned, now, session_id),
        )
    return get_session(session_id)


def delete_session(session_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    return cur.rowcount > 0
