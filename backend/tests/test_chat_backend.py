from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.chat.service import ChatService
from backend.app.storage import ChatRepository, Database


class FakeRegistry:
    async def models(self):
        return []

    async def stream(self, model_id, messages, *, cancelled):
        for value in (f"{model_id}:", " grounded"):
            if cancelled():
                return
            yield value
            await asyncio.sleep(0)


class FakeTools:
    async def build_evidence_packet(self, prompt):
        return {
            "tool": "literature_search",
            "query": prompt,
            "evidence": [{"citation_id": "source-1", "title": "Paper", "year": 2026, "abstract": "Evidence", "url": "https://example.test/paper"}],
            "citations": [{"id": "source-1", "title": "Paper", "url": "https://example.test/paper", "authors": ["A"], "year": 2026, "excerpt": "Evidence", "verified": True}],
        }


class SlowRegistry:
    async def stream(self, model_id, messages, *, cancelled):
        while not cancelled():
            yield "partial"
            await asyncio.sleep(0)


def test_database_migration_preserves_research_data_and_adds_chat(tmp_path: Path) -> None:
    database = Database(tmp_path / "history.sqlite3")
    database.initialize()
    with database.connection() as connection:
        connection.execute(
            """INSERT INTO projects(topic,question,document_type,status,created_at,updated_at)
               VALUES('existing','','proposal','created','now','now')"""
        )
    database.initialize()
    conversation = ChatRepository(database).create_conversation("phi4-mini")
    with database.connection() as connection:
        assert connection.execute("SELECT topic FROM projects").fetchone()["topic"] == "existing"
    assert conversation["consent_training"] is False
    assert conversation["consent_clone_phi"] is False


def test_crud_search_branch_feedback_and_citations(tmp_path: Path) -> None:
    database = Database(tmp_path / "chat.sqlite3")
    database.initialize()
    repo = ChatRepository(database)
    conversation = repo.create_conversation("phi4-mini")
    user = repo.add_message(conversation["id"], "user", "quantum retrieval")
    branch = repo.create_branch(conversation["id"], user["id"])
    assistant = repo.add_message(
        conversation["id"], "assistant", "answer", model_id="phi4-mini", branch_id=branch
    )
    repo.add_citation(
        assistant["id"],
        {"title": "Source", "url": "https://example.test", "verified": True},
    )
    repo.add_feedback(assistant["id"], "up", None, False)
    assert repo.list_conversations("quantum")[0]["id"] == conversation["id"]
    assert repo.get_message(assistant["id"])["citations"][0]["verified"] is True
    assert repo.update_conversation(conversation["id"], title="Renamed")["title"] == "Renamed"
    assert repo.delete_conversation(conversation["id"]) is True


@pytest.mark.asyncio
async def test_compare_stream_is_sequential_linked_and_uses_shared_packet(tmp_path: Path) -> None:
    database = Database(tmp_path / "compare.sqlite3")
    database.initialize()
    repo = ChatRepository(database)
    conversation = repo.create_conversation("phi4-mini")
    service = ChatService(repo, FakeRegistry(), FakeTools())
    payload = SimpleNamespace(
        conversation_id=conversation["id"],
        content="find literature",
        model_id="phi4-mini",
        compare_model_id="llama3.2",
        parent_message_id=None,
        regenerate_message_id=None,
    )
    events = [
        json.loads(chunk)
        async for chunk in service.stream(service.new_run(), payload)
    ]
    starts = [event for event in events if event["type"] == "message.started"]
    assert [event["lane"] for event in starts] == ["primary", "compare"]
    assert starts[0]["message"]["state"] == "streaming"
    with database.connection() as connection:
        linked = connection.execute("SELECT * FROM compare_runs").fetchone()
        assert linked["primary_message_id"] == starts[0]["message"]["id"]
        assert linked["compare_message_id"] == starts[1]["message"]["id"]
        assert linked["evidence_packet_id"]
        assert connection.execute("SELECT COUNT(*) AS n FROM evidence_packets").fetchone()["n"] == 1


@pytest.mark.asyncio
async def test_stream_cancellation_persists_partial_state(tmp_path: Path) -> None:
    database = Database(tmp_path / "cancel.sqlite3")
    database.initialize()
    repo = ChatRepository(database)
    conversation = repo.create_conversation("phi4-mini")
    service = ChatService(repo, SlowRegistry(), FakeTools())
    payload = SimpleNamespace(
        conversation_id=conversation["id"],
        content="find literature",
        model_id="phi4-mini",
        compare_model_id=None,
        parent_message_id=None,
        regenerate_message_id=None,
    )
    run = service.new_run()
    stream = service.stream(run, payload)
    started = json.loads(await anext(stream))
    delta = json.loads(await anext(stream))
    assert started["type"] == "message.started"
    assert delta["type"] == "citation"
    while delta["type"] != "message.delta":
        delta = json.loads(await anext(stream))
    assert service.cancel(run.id)
    remainder = [json.loads(item) async for item in stream]
    assert remainder[-1]["type"] == "message.cancelled"
    stored = repo.get_message(started["message"]["id"])
    assert stored["state"] == "cancelled"
    assert stored["content"].startswith("partial")


def test_chat_api_contract_and_token_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main.settings.database_path = tmp_path / "api.sqlite3"
    main.settings.literature_cache_path = tmp_path / "cache"
    main.settings.training_path = tmp_path / "training"
    main.settings.training_records_path = tmp_path / "training" / "feedback.jsonl"
    monkeypatch.setenv("RESEARCH_AGENT_IPC_TOKEN", "secret-token")
    headers = {"Authorization": "Bearer secret-token"}
    with TestClient(main.app) as client:
        assert client.get("/api/chat/conversations").status_code == 401
        created = client.post(
            "/api/chat/conversations", json={"model_id": "phi4-mini"}, headers=headers
        )
        assert created.status_code == 201
        conversation_id = created.json()["id"]
        main.app.state.chat.registry = FakeRegistry()
        main.app.state.chat.tools = FakeTools()
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={
                "conversation_id": conversation_id,
                "content": "find literature",
                "model_id": "phi4-mini",
            },
            headers=headers,
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/x-ndjson")
            assert response.headers["x-run-id"]
            events = [json.loads(line) for line in response.iter_lines()]
        assert events[0]["type"] == "message.started"
        assert events[-1]["type"] == "message.completed"
        restored = client.get(
            f"/api/chat/conversations/{conversation_id}/messages", headers=headers
        ).json()
        assert restored[-1]["content"] == "phi4-mini: grounded"
        assert restored[-1]["state"] == "complete"
        consent = client.patch(
            f"/api/chat/conversations/{conversation_id}/consent",
            json={"consent_training": True},
            headers=headers,
        )
        assert consent.status_code == 204
        feedback = client.post(
            "/api/chat/feedback",
            json={
                "message_id": restored[-1]["id"],
                "rating": "up",
                "consent_training": True,
            },
            headers=headers,
        )
        assert feedback.status_code == 204
        created_llama = client.post(
            "/api/chat/conversations", json={"model_id": "llama3.2"}, headers=headers
        )
        assert created_llama.status_code == 201
        upload = client.post(
            f"/api/chat/conversations/{created_llama.json()['id']}/attachments",
            files={"file": ("notes.md", b"# Notes\nLocal PDF-like text.", "text/markdown")},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert upload.status_code == 201
        assert upload.json()["kind"] == "text"
        blocked = client.post(
            f"/api/chat/conversations/{created_llama.json()['id']}/attachments",
            files={"file": ("bad.exe", b"MZ", "application/octet-stream")},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert blocked.status_code == 415
