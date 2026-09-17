"""Conversation orchestration, branching, streaming, and durable run state."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.llm.registry import ModelRegistry
from backend.app.storage.chat_repository import ChatRepository, is_allowed_model_id

from .ingest import attachment_prompt
from .policy import CASUAL_POLICY, SYSTEM_POLICY
from .tools import ResearchToolRouter, evidence_context


@dataclass
class ChatRun:
    id: str
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    message_ids: list[str] = field(default_factory=list)


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        registry: ModelRegistry,
        tools: ResearchToolRouter,
    ):
        self.repository = repository
        self.registry = registry
        self.tools = tools
        self._runs: dict[str, ChatRun] = {}

    def new_run(self) -> ChatRun:
        run = ChatRun(uuid.uuid4().hex)
        self._runs[run.id] = run
        return run

    def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.cancelled.set()
        for message_id in run.message_ids:
            message = self.repository.get_message(message_id)
            if message and message["state"] == "streaming":
                self.repository.update_message(message_id, state="cancelled")
        return True

    @staticmethod
    def _event(payload: dict[str, Any]) -> bytes:
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    async def stream(self, run: ChatRun, payload: Any) -> AsyncIterator[bytes]:
        compare_run_id: str | None = None
        active_message: str | None = None
        try:
            conversation = self.repository.get_conversation(payload.conversation_id)
            if conversation is None:
                yield self._event({"type": "error", "code": "not_found", "message": "Conversation not found"})
                return
            if not is_allowed_model_id(payload.model_id) or (
                payload.compare_model_id is not None
                and not is_allowed_model_id(payload.compare_model_id)
            ):
                yield self._event({"type": "error", "code": "invalid_model", "message": "Unknown model"})
                return

            branch_id = None
            if payload.regenerate_message_id or payload.parent_message_id:
                parent = payload.regenerate_message_id or payload.parent_message_id
                branch_id = self.repository.create_branch(payload.conversation_id, parent)

            user_message = None
            if payload.regenerate_message_id:
                existing = self.repository.list_messages(payload.conversation_id)
                target_index = next(
                    (
                        index
                        for index, item in enumerate(existing)
                        if item["id"] == payload.regenerate_message_id
                    ),
                    -1,
                )
                user_message = next(
                    (
                        item
                        for item in reversed(existing[:target_index])
                        if item["role"] == "user"
                    ),
                    None,
                )
                if user_message is None:
                    yield self._event(
                        {
                            "type": "error",
                            "code": "invalid_regeneration",
                            "message": "Regeneration target has no preceding user message",
                        }
                    )
                    return
            else:
                user_message = self.repository.add_message(
                    payload.conversation_id,
                    "user",
                    payload.content.strip(),
                    branch_id=branch_id,
                    parent_message_id=payload.parent_message_id,
                )
                attachment_ids = list(getattr(payload, "attachment_ids", None) or [])
                if attachment_ids:
                    self.repository.bind_attachments(user_message["id"], attachment_ids)
                if not payload.content.strip() and attachment_ids:
                    payload.content = "Please read the attached files."
                    self.repository.update_message(user_message["id"], content=payload.content)
            if conversation["title"] == "New research":
                title = " ".join(payload.content.split())[:80]
                self.repository.update_conversation(payload.conversation_id, title=title)
            self.repository.update_conversation(
                payload.conversation_id,
                model_id=payload.model_id,
                compare_model_id=payload.compare_model_id,
            )

            packet = await self.tools.build_evidence_packet(payload.content)
            packet_id = None
            if packet.get("tool"):
                packet_id, packet = self.repository.save_evidence_packet(
                    payload.conversation_id, payload.content, packet
                )
            if payload.compare_model_id:
                compare_run_id = self.repository.create_compare_run(
                    payload.conversation_id, user_message["id"], packet_id
                )

            history = self.repository.context_messages(
                payload.conversation_id, before_message_id=user_message["id"], limit=6
            )
            research = bool(packet.get("tool") or getattr(payload, "attachment_ids", None))
            messages = [
                {"role": "system", "content": SYSTEM_POLICY if research else CASUAL_POLICY}
            ]
            evidence = evidence_context(packet)
            if evidence:
                messages.append({"role": "system", "content": evidence})
            attachments = self.repository.list_attachments(
                payload.conversation_id, user_message["id"]
            )
            files_prompt = attachment_prompt(attachments)
            if files_prompt:
                messages.append({"role": "system", "content": files_prompt})
            messages.extend(history)
            user_turn: dict[str, Any] = {"role": "user", "content": payload.content.strip()}
            images = []
            for item in attachments:
                if item.get("kind") != "image":
                    continue
                path = Path(item["stored_path"])
                if path.is_file():
                    images.append(base64.b64encode(path.read_bytes()).decode("ascii"))
            if images:
                user_turn["images"] = images
            messages.append(user_turn)

            lanes = [("primary", payload.model_id)]
            if payload.compare_model_id:
                lanes.append(("compare", payload.compare_model_id))
            for lane, model_id in lanes:  # Deliberately sequential for low-memory machines.
                if run.cancelled.is_set():
                    break
                assistant = self.repository.add_message(
                    payload.conversation_id,
                    "assistant",
                    model_id=model_id,
                    state="streaming",
                    branch_id=branch_id,
                    parent_message_id=user_message["id"],
                )
                active_message = assistant["id"]
                run.message_ids.append(active_message)
                if compare_run_id:
                    self.repository.update_compare_run(
                        compare_run_id,
                        **{f"{lane}_message_id": active_message},
                    )
                yield self._event(
                    {"type": "message.started", "message": assistant, "lane": lane}
                )
                for citation in packet.get("citations", []):
                    stored = self.repository.add_citation(active_message, citation)
                    yield self._event(
                        {
                            "type": "citation",
                            "message_id": active_message,
                            "citation": stored,
                            "lane": lane,
                        }
                    )
                pending = ""
                last_flush = 0.0

                def flush_delta() -> bytes | None:
                    nonlocal pending, last_flush
                    if not pending:
                        return None
                    chunk, pending = pending, ""
                    last_flush = time.monotonic()
                    self.repository.append_message(active_message, chunk)
                    return self._event(
                        {
                            "type": "message.delta",
                            "message_id": active_message,
                            "delta": chunk,
                            "lane": lane,
                        }
                    )

                async for delta in self.registry.stream(
                    model_id, messages, cancelled=run.cancelled.is_set
                ):
                    if run.cancelled.is_set():
                        break
                    pending += delta
                    if last_flush == 0.0 or len(pending) >= 32 or time.monotonic() - last_flush >= 0.05:
                        event = flush_delta()
                        if event:
                            yield event
                leftover = flush_delta()
                if leftover:
                    yield leftover
                state = "cancelled" if run.cancelled.is_set() else "complete"
                self.repository.update_message(active_message, state=state)
                yield self._event(
                    {
                        "type": "message.cancelled" if state == "cancelled" else "message.completed",
                        "message_id": active_message,
                        "lane": lane,
                    }
                )
                active_message = None
            if compare_run_id:
                self.repository.update_compare_run(
                    compare_run_id,
                    state="cancelled" if run.cancelled.is_set() else "complete",
                )
        except asyncio.CancelledError:
            run.cancelled.set()
            raise
        except Exception as exc:  # noqa: BLE001 - stream boundary persists failures
            if active_message:
                self.repository.update_message(active_message, state="error", error=str(exc))
            if compare_run_id:
                self.repository.update_compare_run(compare_run_id, state="error")
            yield self._event(
                {"type": "error", "code": "generation_failed", "message": str(exc)}
            )
        finally:
            if run.cancelled.is_set():
                for message_id in run.message_ids:
                    message = self.repository.get_message(message_id)
                    if message and message["state"] == "streaming":
                        self.repository.update_message(message_id, state="cancelled")
            self._runs.pop(run.id, None)
