"""SQLite connection and schema management."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    question TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT 'proposal',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_project_kind
    ON artifacts(project_id, kind, created_at);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    rating INTEGER,
    comment TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    model_id TEXT NOT NULL,
    compare_model_id TEXT,
    consent_training INTEGER NOT NULL DEFAULT 0,
    consent_clone_phi INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_branches (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    parent_message_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    model_id TEXT,
    state TEXT NOT NULL,
    branch_id TEXT REFERENCES chat_branches(id) ON DELETE SET NULL,
    parent_message_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation
    ON chat_messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS compare_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    primary_message_id TEXT REFERENCES chat_messages(id) ON DELETE SET NULL,
    compare_message_id TEXT REFERENCES chat_messages(id) ON DELETE SET NULL,
    evidence_packet_id TEXT,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_packets (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_citations (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    authors_json TEXT NOT NULL DEFAULT '[]',
    year INTEGER,
    excerpt TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_feedback (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    rating TEXT NOT NULL,
    correction TEXT,
    consent_training INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES chat_messages(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    media_type TEXT,
    stored_path TEXT NOT NULL,
    extracted_text TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'file',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_checkpoints (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    path TEXT NOT NULL,
    state TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    activated_at TEXT
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "document_type" not in columns:
                connection.execute(
                    "ALTER TABLE projects ADD COLUMN document_type TEXT "
                    "NOT NULL DEFAULT 'proposal'"
                )
            conversation_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
            }
            if "consent_clone_phi" not in conversation_columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN consent_clone_phi "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            attachment_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(attachments)").fetchall()
            }
            if attachment_columns:
                if "extracted_text" not in attachment_columns:
                    connection.execute(
                        "ALTER TABLE attachments ADD COLUMN extracted_text TEXT NOT NULL DEFAULT ''"
                    )
                if "kind" not in attachment_columns:
                    connection.execute(
                        "ALTER TABLE attachments ADD COLUMN kind TEXT NOT NULL DEFAULT 'file'"
                    )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
