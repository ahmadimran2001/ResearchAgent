"""Repository used by HTTP routes and independently implemented workflow stages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .database import Database


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class ResearchRepository:
    def __init__(self, database: Database):
        self.database = database

    def create_project(
        self, topic: str, question: str = "", document_type: str = "proposal"
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.connection() as connection:
            cursor = connection.execute(
                """INSERT INTO projects
                   (topic, question, document_type, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (topic.strip(), question.strip(), document_type, now, now),
            )
            project_id = int(cursor.lastrowid)
        return self.get_project(project_id) or {}

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            return _row(connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())

    def list_projects(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def set_project_status(self, project_id: int, status: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), project_id),
            )

    def create_job(self, job_id: str, project_id: int, stage: str) -> dict[str, Any]:
        now = utc_now()
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO jobs
                   (id, project_id, stage, status, progress, created_at, updated_at)
                   VALUES (?, ?, ?, 'queued', 0, ?, ?)""",
                (job_id, project_id, stage, now, now),
            )
        return self.get_job(job_id) or {}

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        progress: int | None = None,
        message: str = "",
        error: str | None = None,
    ) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """UPDATE jobs SET status = ?, progress = COALESCE(?, progress),
                   message = ?, error = ?, updated_at = ? WHERE id = ?""",
                (status, progress, message, error, utc_now(), job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            return _row(connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def add_artifact(
        self,
        project_id: int,
        kind: str,
        content: Any,
        *,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        serialized = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        with self.database.connection() as connection:
            cursor = connection.execute(
                """INSERT INTO artifacts(project_id, kind, title, content, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (project_id, kind, title, serialized, json.dumps(metadata or {}), utc_now()),
            )
            return int(cursor.lastrowid)

    def list_artifacts(self, project_id: int, kind: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM artifacts WHERE project_id = ?"
        params: list[Any] = [project_id]
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY created_at DESC"
        with self.database.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            item["metadata"] = json.loads(item.pop("metadata_json"))
        return result

    def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            item = _row(
                connection.execute(
                    "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
                ).fetchone()
            )
        if item is not None:
            item["metadata"] = json.loads(item.pop("metadata_json"))
        return item

    def add_feedback(
        self, comment: str, project_id: int | None = None, rating: int | None = None
    ) -> int:
        with self.database.connection() as connection:
            cursor = connection.execute(
                "INSERT INTO feedback(project_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                (project_id, rating, comment.strip(), utc_now()),
            )
            return int(cursor.lastrowid)
