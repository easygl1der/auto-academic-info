from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "auto_academic.db")

MEETING_FIELDS = (
    "source_page_url",
    "source_url",
    "title",
    "start_time",
    "location",
    "speaker",
    "topic",
    "abstract",
    "mode",
    "online_link",
    "speaker_intro",
    "speaker_intro_url",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection() -> Iterable[sqlite3.Connection]:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS monitored_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                last_checked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_page_url TEXT NOT NULL,
                source_url TEXT NOT NULL UNIQUE,
                title TEXT,
                start_time TEXT,
                location TEXT,
                speaker TEXT,
                topic TEXT,
                abstract TEXT,
                mode TEXT,
                online_link TEXT,
                speaker_intro TEXT,
                speaker_intro_url TEXT,
                data_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meeting_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id INTEGER NOT NULL,
                recorded_at TEXT NOT NULL,
                data_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
            );
            """
        )


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row) if row else {}


def list_monitored_pages() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, url, created_at, last_checked_at FROM monitored_pages ORDER BY id DESC"
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_monitored_page(page_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, url, created_at, last_checked_at FROM monitored_pages WHERE id = ?",
            (page_id,),
        ).fetchone()
    return row_to_dict(row) if row else None


def get_page_by_url(url: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, url, created_at, last_checked_at FROM monitored_pages WHERE url = ?",
            (url,),
        ).fetchone()
    return row_to_dict(row) if row else None


def create_monitored_page(url: str) -> Dict[str, Any]:
    created_at = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO monitored_pages (url, created_at) VALUES (?, ?)",
            (url, created_at),
        )
        row = conn.execute(
            "SELECT id, url, created_at, last_checked_at FROM monitored_pages WHERE url = ?",
            (url,),
        ).fetchone()
    return row_to_dict(row)


def update_page_checked(page_id: int, timestamp: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE monitored_pages SET last_checked_at = ? WHERE id = ?",
            (timestamp, page_id),
        )


def list_meetings(limit: int = 200) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, source_page_url, source_url, title, start_time, location, speaker,
                   topic, abstract, mode, online_link, speaker_intro, speaker_intro_url,
                   data_hash, created_at, last_seen_at, last_updated_at
            FROM meetings
            ORDER BY last_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_meeting(meeting_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, source_page_url, source_url, title, start_time, location, speaker,
                   topic, abstract, mode, online_link, speaker_intro, speaker_intro_url,
                   data_hash, created_at, last_seen_at, last_updated_at
            FROM meetings
            WHERE id = ?
            """,
            (meeting_id,),
        ).fetchone()
    return row_to_dict(row) if row else None


def get_meeting_history(meeting_id: int) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, meeting_id, recorded_at, data_hash, payload_json
            FROM meeting_history
            WHERE meeting_id = ?
            ORDER BY recorded_at DESC
            """,
            (meeting_id,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def upsert_meeting(record: Dict[str, Any]) -> Dict[str, Any]:
    required_keys = {"source_page_url", "source_url", "data_hash"}
    missing = required_keys - record.keys()
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    now = utc_now_iso()
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, source_page_url, source_url, title, start_time, location, speaker,
                   topic, abstract, mode, online_link, speaker_intro, speaker_intro_url,
                   data_hash, created_at, last_seen_at, last_updated_at
            FROM meetings
            WHERE source_url = ?
            """,
            (record["source_url"],),
        ).fetchone()

        if not existing:
            payload = {field: record.get(field) for field in MEETING_FIELDS}
            conn.execute(
                """
                INSERT INTO meetings (
                    source_page_url, source_url, title, start_time, location, speaker,
                    topic, abstract, mode, online_link, speaker_intro, speaker_intro_url,
                    data_hash, created_at, last_seen_at, last_updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.get("source_page_url"),
                    record.get("source_url"),
                    record.get("title"),
                    record.get("start_time"),
                    record.get("location"),
                    record.get("speaker"),
                    record.get("topic"),
                    record.get("abstract"),
                    record.get("mode"),
                    record.get("online_link"),
                    record.get("speaker_intro"),
                    record.get("speaker_intro_url"),
                    record.get("data_hash"),
                    now,
                    now,
                    now,
                ),
            )
            meeting_id = conn.execute(
                "SELECT id FROM meetings WHERE source_url = ?",
                (record["source_url"],),
            ).fetchone()["id"]
            return {"meeting_id": meeting_id, "created": True, "changed": True}

        existing_dict = row_to_dict(existing)
        if existing_dict.get("data_hash") != record.get("data_hash"):
            history_payload = {
                field: existing_dict.get(field) for field in MEETING_FIELDS
            }
            conn.execute(
                """
                INSERT INTO meeting_history (meeting_id, recorded_at, data_hash, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    existing_dict["id"],
                    now,
                    existing_dict.get("data_hash"),
                    json.dumps(history_payload, ensure_ascii=True),
                ),
            )
            conn.execute(
                """
                UPDATE meetings
                SET source_page_url = ?, title = ?, start_time = ?, location = ?,
                    speaker = ?, topic = ?, abstract = ?, mode = ?, online_link = ?,
                    speaker_intro = ?, speaker_intro_url = ?, data_hash = ?,
                    last_seen_at = ?, last_updated_at = ?
                WHERE id = ?
                """,
                (
                    record.get("source_page_url"),
                    record.get("title"),
                    record.get("start_time"),
                    record.get("location"),
                    record.get("speaker"),
                    record.get("topic"),
                    record.get("abstract"),
                    record.get("mode"),
                    record.get("online_link"),
                    record.get("speaker_intro"),
                    record.get("speaker_intro_url"),
                    record.get("data_hash"),
                    now,
                    now,
                    existing_dict["id"],
                ),
            )
            return {"meeting_id": existing_dict["id"], "created": False, "changed": True}

        conn.execute(
            "UPDATE meetings SET last_seen_at = ? WHERE id = ?",
            (now, existing_dict["id"]),
        )
    return {"meeting_id": existing_dict["id"], "created": False, "changed": False}
