"""Streaming registry for locally installed Ollama models."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from backend.app.config import Settings, get_settings

from .ollama import OllamaClient


class ModelRegistry:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        ollama: OllamaClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.ollama = ollama or OllamaClient(self.settings)

    async def models(self) -> list[dict[str, Any]]:
        try:
            installed = await self.ollama.list_models()
        except Exception:  # noqa: BLE001 - status endpoint remains available offline
            installed = []
        default = self.settings.ollama_model.split(":", 1)[0]
        if default and all(item["id"] != default for item in installed):
            installed.insert(
                0,
                {
                    "id": default,
                    "name": default,
                    "description": "Configured Ollama model (not installed yet)",
                    "provider": "ollama",
                    "ready": False,
                    "vision": False,
                },
            )
        preferred = [item for item in installed if item["id"] == default]
        others = [item for item in installed if item["id"] != default]
        return preferred + others

    async def stream(
        self,
        model_id: str,
        messages: Sequence[dict[str, Any]],
        *,
        cancelled: Callable[[], bool],
    ) -> AsyncIterator[str]:
        async for delta in self.ollama.stream(messages, cancelled=cancelled, model=model_id):
            yield delta
