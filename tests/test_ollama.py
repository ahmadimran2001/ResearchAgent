from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from backend.app.config import Settings
from backend.app.llm import OllamaClient


class StructuredAnswer(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_structured_ollama_request_is_bounded_and_validated() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "phi4-mini:latest"}]}, request=request
            )
        payload = json.loads(request.content)
        assert payload["format"]["properties"]["answer"]["type"] == "string"
        assert sum(len(message["content"]) for message in payload["messages"]) <= 1000
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": '{"answer":"ready"}'}},
            request=request,
        )

    http = httpx.AsyncClient(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    )
    settings = Settings(
        ollama_base_url="http://ollama.test",
        ollama_model="phi4-mini",
        ollama_max_input_chars=1000,
    )
    client = OllamaClient(settings, http)
    result = await client.chat(
        [
            {"role": "system", "content": "Stay grounded."},
            {"role": "user", "content": "old" * 1000},
            {"role": "user", "content": "Return ready."},
        ],
        schema=StructuredAnswer,
    )
    await http.aclose()
    assert result == StructuredAnswer(answer="ready")
    assert [request.url.path for request in requests] == ["/api/tags", "/api/chat"]
    chat_payload = json.loads(requests[-1].content)
    assert chat_payload["keep_alive"] == "30m"
    assert chat_payload["options"]["num_ctx"] == 2048
    assert chat_payload["options"]["num_predict"] == 512
    assert chat_payload["options"]["num_batch"] == 256

