"""Durable chat persistence layered onto the existing research database."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .database import Database
from .repository import utc_now

MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


def is_allowed_model_id(model_id: str | None) -> bool:
    if not model_id:
        return False
    return bool(MODEL_ID_RE.fullmatch(model_id))


class ChatRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _id() -> str:
        return uuid.uuid4().hex

    def _conversation(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        value["consent_training"] = bool(value["consent_training"])
        value["consent_clone_phi"] = bool(value.get("consent_clone_phi"))
        return value

    def create_conversation(
        self, model_id: str, *, title: str = "New research", compare_model_id: str | None = None
    ) -> dict[str, Any]:
        if not is_allowed_model_id(model_id) or (
            compare_model_id is not None and not is_allowed_model_id(compare_model_id)
        ):
            raise ValueError("Unknown model")
        now, conversation_id = utc_now(), self._id()
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO conversations
                   (id,title,model_id,compare_model_id,created_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (conversation_id, title.strip() or "New research", model_id, compare_model_id, now, now),
            )
        return self.get_conversation(conversation_id) or {}

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT c.*,
                   (SELECT content FROM chat_messages m WHERE m.conversation_id=c.id
                    ORDER BY m.created_at DESC LIMIT 1) AS last_message
                   FROM conversations c WHERE c.id=?""",
                (conversation_id,),
            ).fetchone()
        return self._conversation(row)

    def list_conversations(self, query: str = "", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT c.*,
                   (SELECT content FROM chat_messages m WHERE m.conversation_id=c.id
                    ORDER BY m.created_at DESC LIMIT 1) AS last_message
                   FROM conversations c
                   WHERE (?='' OR c.title LIKE ? OR EXISTS (
                     SELECT 1 FROM chat_messages m
                     WHERE m.conversation_id=c.id AND m.content LIKE ?
                   ))
                   ORDER BY c.updated_at DESC LIMIT ? OFFSET ?""",
                (query.strip(), pattern, pattern, limit, offset),
            ).fetchall()
        return [self._conversation(row) or {} for row in rows]

    def update_conversation(self, conversation_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {"title", "model_id", "compare_model_id", "consent_training", "consent_clone_phi"}
        fields = {key: value for key, value in changes.items() if key in allowed and value is not None}
        if "model_id" in fields and not is_allowed_model_id(fields["model_id"]):
            raise ValueError("Unknown model")
        if "compare_model_id" in fields and not is_allowed_model_id(fields["compare_model_id"]):
            raise ValueError("Unknown compare model")
        if "consent_training" in fields:
            fields["consent_training"] = int(bool(fields["consent_training"]))
        if "consent_clone_phi" in fields:
            fields["consent_clone_phi"] = int(bool(fields["consent_clone_phi"]))
        if not fields:
            return self.get_conversation(conversation_id)
        fields["updated_at"] = utc_now()
        assignment = ", ".join(f"{key}=?" for key in fields)
        with self.database.connection() as connection:
            cursor = connection.execute(
                f"UPDATE conversations SET {assignment} WHERE id=?",
                (*fields.values(), conversation_id),
            )
        return self.get_conversation(conversation_id) if cursor.rowcount else None

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.database.connection() as connection:
            return bool(connection.execute("DELETE FROM conversations WHERE id=?", (conversation_id,)).rowcount)

    def create_branch(self, conversation_id: str, parent_message_id: str | None) -> str:
        branch_id = self._id()
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO chat_branches(id,conversation_id,parent_message_id,created_at) VALUES(?,?,?,?)",
                (branch_id, conversation_id, parent_message_id, utc_now()),
            )
        return branch_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str = "",
        *,
        model_id: str | None = None,
        state: str = "complete",
        branch_id: str | None = None,
        parent_message_id: str | None = None,
    ) -> dict[str, Any]:
        message_id, now = self._id(), utc_now()
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO chat_messages
                   (id,conversation_id,role,content,model_id,state,branch_id,parent_message_id,
                    created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    message_id, conversation_id, role, content, model_id, state, branch_id,
                    parent_message_id, now, now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id)
            )
        return self.get_message(message_id) or {}

    def update_message(
        self, message_id: str, *, content: str | None = None, state: str | None = None,
        error: str | None = None
    ) -> dict[str, Any] | None:
        parts, values = [], []
        for key, value in (("content", content), ("state", state), ("error", error)):
            if value is not None:
                parts.append(f"{key}=?")
                values.append(value)
        if not parts:
            return self.get_message(message_id)
        parts.append("updated_at=?")
        values.append(utc_now())
        with self.database.connection() as connection:
            connection.execute(
                f"UPDATE chat_messages SET {', '.join(parts)} WHERE id=?",
                (*values, message_id),
            )
        return self.get_message(message_id)

    def append_message(self, message_id: str, delta: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE chat_messages SET content=content||?, updated_at=? WHERE id=?",
                (delta, utc_now(), message_id),
            )

    def _message(
        self,
        row: Any,
        citations: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        value.pop("updated_at", None)
        value.pop("error", None)
        value.pop("parent_message_id", None)
        value["citations"] = citations or []
        value["attachments"] = [
            {key: item[key] for key in ("id", "filename", "kind", "media_type") if key in item}
            for item in attachments or []
        ]
        return value

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM chat_messages WHERE id=?", (message_id,)).fetchone()
            citations = self._citations(connection, message_id)
        attachments = []
        if row is not None:
            attachments = self.list_attachments(row["conversation_id"], message_id)
        return self._message(row, citations, attachments)

    def list_messages(self, conversation_id: str, limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM chat_messages WHERE conversation_id=?
                   ORDER BY created_at ASC LIMIT ? OFFSET ?""",
                (conversation_id, limit, offset),
            ).fetchall()
            return [
                self._message(
                    row,
                    self._citations(connection, row["id"]),
                    [
                        {
                            "id": dict(item)["id"],
                            "filename": dict(item)["filename"],
                            "kind": dict(item).get("kind") or "file",
                            "media_type": dict(item).get("media_type"),
                        }
                        for item in connection.execute(
                            """SELECT id, filename, kind, media_type FROM attachments
                               WHERE message_id=? ORDER BY created_at""",
                            (row["id"],),
                        ).fetchall()
                    ],
                )
                or {}
                for row in rows
            ]

    def delete_message(self, message_id: str) -> bool:
        with self.database.connection() as connection:
            return bool(
                connection.execute(
                    "DELETE FROM chat_messages WHERE id=?", (message_id,)
                ).rowcount
            )

    def context_messages(
        self, conversation_id: str, *, before_message_id: str | None = None, limit: int = 40
    ) -> list[dict[str, str]]:
        messages = self.list_messages(conversation_id)
        if before_message_id:
            index = next((i for i, item in enumerate(messages) if item["id"] == before_message_id), len(messages))
            messages = messages[:index]
        usable = [
            {"role": item["role"], "content": item["content"]}
            for item in messages if item["role"] in {"user", "assistant"} and item["state"] != "error"
        ]
        return usable[-limit:]

    def add_citation(self, message_id: str, citation: dict[str, Any]) -> dict[str, Any]:
        citation_id = str(citation.get("id") or self._id())
        with self.database.connection() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO chat_citations
                   (id,message_id,title,url,authors_json,year,excerpt,verified,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    citation_id, message_id, citation["title"], citation["url"],
                    json.dumps(citation.get("authors", [])), citation.get("year"),
                    citation.get("excerpt"), int(bool(citation.get("verified"))), utc_now(),
                ),
            )
        return {**citation, "id": citation_id, "verified": bool(citation.get("verified"))}

    @staticmethod
    def _citations(connection: Any, message_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM chat_citations WHERE message_id=? ORDER BY created_at", (message_id,)
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            output.append({
                "id": item["id"], "title": item["title"], "url": item["url"],
                "authors": json.loads(item["authors_json"]), "year": item["year"],
                "excerpt": item["excerpt"], "verified": bool(item["verified"]),
            })
        return output

    def save_evidence_packet(
        self, conversation_id: str, query: str, payload: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        packet_id = self._id()
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO evidence_packets(id,conversation_id,query,payload_json,created_at) VALUES(?,?,?,?,?)",
                (packet_id, conversation_id, query, json.dumps(payload), utc_now()),
            )
        return packet_id, payload

    def create_compare_run(
        self, conversation_id: str, user_message_id: str, evidence_packet_id: str | None
    ) -> str:
        run_id, now = self._id(), utc_now()
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO compare_runs
                   (id,conversation_id,user_message_id,evidence_packet_id,state,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id, conversation_id, user_message_id, evidence_packet_id, "running", now, now),
            )
        return run_id

    def update_compare_run(self, run_id: str, **changes: Any) -> None:
        allowed = {"primary_message_id", "compare_message_id", "state"}
        fields = {key: value for key, value in changes.items() if key in allowed}
        fields["updated_at"] = utc_now()
        with self.database.connection() as connection:
            connection.execute(
                f"UPDATE compare_runs SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
                (*fields.values(), run_id),
            )

    def add_feedback(
        self, message_id: str, rating: str, correction: str | None, consent_training: bool
    ) -> str:
        feedback_id = self._id()
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO chat_feedback
                   (id,message_id,rating,correction,consent_training,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (feedback_id, message_id, rating, correction, int(consent_training), utc_now()),
            )
        return feedback_id

    def add_attachment(
        self,
        conversation_id: str,
        *,
        filename: str,
        stored_path: str,
        media_type: str | None,
        extracted_text: str,
        kind: str,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        attachment_id = self._id()
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO attachments
                   (id,conversation_id,message_id,filename,media_type,stored_path,
                    extracted_text,kind,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    attachment_id,
                    conversation_id,
                    message_id,
                    filename,
                    media_type,
                    stored_path,
                    extracted_text,
                    kind,
                    utc_now(),
                ),
            )
        return self.get_attachment(attachment_id) or {}

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM attachments WHERE id=?", (attachment_id,)
            ).fetchone()
        return self._attachment(row)

    def list_attachments(
        self, conversation_id: str, message_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            if message_id:
                rows = connection.execute(
                    """SELECT * FROM attachments WHERE conversation_id=? AND message_id=?
                       ORDER BY created_at""",
                    (conversation_id, message_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM attachments WHERE conversation_id=?
                       ORDER BY created_at""",
                    (conversation_id,),
                ).fetchall()
        return [self._attachment(row) or {} for row in rows]

    def bind_attachments(self, message_id: str, attachment_ids: list[str]) -> None:
        if not attachment_ids:
            return
        with self.database.connection() as connection:
            connection.executemany(
                "UPDATE attachments SET message_id=? WHERE id=?",
                [(message_id, item) for item in attachment_ids],
            )

    @staticmethod
    def _attachment(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        return {
            "id": value["id"],
            "conversation_id": value["conversation_id"],
            "message_id": value.get("message_id"),
            "filename": value["filename"],
            "media_type": value.get("media_type"),
            "kind": value.get("kind") or "file",
            "extracted_text": value.get("extracted_text") or "",
            "stored_path": value["stored_path"],
            "created_at": value["created_at"],
        }
