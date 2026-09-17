"""Async Ollama chat client with bounded context and structured output support."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)

VISION_HINTS = ("llava", "vision", "moondream", "bakllava", "minicpm-v", "qwen2.5vl")


class OllamaError(RuntimeError):
    """Raised when Ollama cannot produce a usable response."""


class OllamaModelUnavailable(OllamaError):
    """Raised when the configured model is not installed."""


def display_name(model_id: str) -> str:
    stem = model_id.split(":", 1)[0]
    special = {
        "phi4-mini": "Phi-4 Mini",
        "phi4": "Phi-4",
        "llama3.2": "Llama 3.2",
        "llama3.1": "Llama 3.1",
        "mistral": "Mistral",
        "qwen2.5": "Qwen 2.5",
        "gemma3": "Gemma 3",
        "gemma2": "Gemma 2",
    }
    if stem in special:
        return special[stem]
    return stem.replace("-", " ").replace(".", " ").title()


def is_vision_model(model_id: str) -> bool:
    lowered = model_id.casefold()
    return any(hint in lowered for hint in VISION_HINTS)


class OllamaClient:
    """Small provider adapter around Ollama's ``/api/chat`` endpoint."""

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._external_client = client
        self._owned_client: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        if self._owned_client is None or self._owned_client.is_closed:
            self._owned_client = httpx.AsyncClient(
                base_url=self.settings.ollama_base_url.rstrip("/"),
                timeout=httpx.Timeout(
                    self.settings.ollama_read_timeout,
                    connect=self.settings.ollama_connect_timeout,
                ),
            )
        return self._owned_client

    async def list_models(self) -> list[dict[str, Any]]:
        client = self._http_client()
        should_close = False
        try:
            response = await client.get("/api/tags")
            response.raise_for_status()
            items = []
            seen: set[str] = set()
            for raw in response.json().get("models", []):
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get("name") or "")
                if not name:
                    continue
                stem = name.split(":", 1)[0]
                model_id = stem if stem not in seen else name
                if model_id in seen:
                    continue
                seen.add(model_id)
                items.append(
                    {
                        "id": model_id,
                        "name": display_name(model_id),
                        "description": (
                            "Vision-capable Ollama model"
                            if is_vision_model(model_id)
                            else "Local Ollama model"
                        ),
                        "provider": "ollama",
                        "ready": True,
                        "vision": is_vision_model(model_id),
                    }
                )
            return items
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaError(f"Could not query Ollama models: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()

    async def model_available(self, model: str | None = None) -> bool:
        requested = model or self.settings.ollama_model
        try:
            names = {item["id"] for item in await self.list_models()}
        except OllamaError:
            raise
        except Exception as exc:
            raise OllamaError(f"Could not query Ollama models: {exc}") from exc
        return requested in names or any(
            requested == name or requested.split(":", 1)[0] == name for name in names
        )

    def _bounded_messages(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        normalized = []
        for item in messages:
            row: dict[str, Any] = {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
            }
            images = item.get("images")
            if isinstance(images, list) and images:
                row["images"] = [str(image) for image in images if image]
            normalized.append(row)
        limit = self.settings.ollama_max_input_chars
        total = sum(len(item["content"]) for item in normalized)
        while total > limit and len(normalized) > 1:
            removable = next(
                (index for index, item in enumerate(normalized[:-1]) if item["role"] != "system"),
                None,
            )
            if removable is None:
                break
            total -= len(normalized[removable]["content"])
            normalized.pop(removable)
        if total > limit and normalized:
            overflow = total - limit
            normalized[-1]["content"] = normalized[-1]["content"][overflow:]
        return normalized

    def _generation_options(self, temperature: float | None) -> dict[str, Any]:
        return {
            "temperature": self.settings.ollama_temperature if temperature is None else temperature,
            "num_ctx": self.settings.ollama_context_window,
            "num_predict": self.settings.ollama_num_predict,
            "num_batch": self.settings.ollama_num_batch,
        }

    async def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        schema: type[T] | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> str | T:
        chosen = model or self.settings.ollama_model
        if not await self.model_available(chosen):
            raise OllamaModelUnavailable(
                f"Model '{chosen}' is not installed. Run: ollama pull {chosen}"
            )

        payload: dict[str, Any] = {
            "model": chosen,
            "messages": self._bounded_messages(messages),
            "stream": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": self._generation_options(temperature),
        }
        if schema is not None:
            payload["format"] = schema.model_json_schema()

        client = self._http_client()
        should_close = False
        try:
            response: httpx.Response | None = None
            for attempt in range(self.settings.ollama_max_retries + 1):
                try:
                    response = await client.post("/api/chat", json=payload)
                    response.raise_for_status()
                    break
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                    retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                        exc.response.status_code >= 500
                    )
                    if not retryable or attempt >= self.settings.ollama_max_retries:
                        raise OllamaError(f"Ollama chat failed: {exc}") from exc
                    await asyncio.sleep(0.5 * (2**attempt))

            if response is None:
                raise OllamaError("Ollama chat returned no response")
            try:
                content = response.json()["message"]["content"]
            except (ValueError, KeyError, TypeError) as exc:
                raise OllamaError("Ollama returned an invalid chat response") from exc
            if schema is None:
                return str(content)
            try:
                return schema.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise OllamaError(f"Ollama returned invalid structured output: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()

    async def stream(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        cancelled: Callable[[], bool] | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream text deltas from Ollama and stop promptly when cancellation is requested."""
        chosen = model or self.settings.ollama_model
        payload = {
            "model": chosen,
            "messages": self._bounded_messages(messages),
            "stream": True,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": self._generation_options(temperature),
        }
        client = self._http_client()
        should_close = False
        try:
            async with client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if cancelled and cancelled():
                        return
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        delta = item.get("message", {}).get("content", "")
                    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                        raise OllamaError("Ollama returned an invalid stream event") from exc
                    if delta:
                        yield str(delta)
                    if item.get("done"):
                        return
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                raise OllamaModelUnavailable(
                    f"Model '{chosen}' is not installed. Run scripts/install-ollama-phi4.ps1"
                ) from exc
            raise OllamaError(f"Ollama stream failed: {exc}") from exc
        except (httpx.HTTPError, httpx.StreamError) as exc:
            raise OllamaError(f"Ollama stream failed: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Compatibility interface for research modules that inject a structured LLM."""
        result = await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            schema=response_model,
        )
        assert isinstance(result, response_model)
        return result
