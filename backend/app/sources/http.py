"""Polite asynchronous HTTP transport with per-adapter pacing and retries."""

import asyncio
import email.utils
import random
import time
from datetime import datetime, timezone
from typing import Any

import httpx


class AsyncHTTPTransport:
    def __init__(
        self,
        *,
        min_interval: float = 0.2,
        timeout: float = 20.0,
        max_retries: int = 3,
        user_agent: str = "ResearchAgent/1.0 (literature retrieval)",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.min_interval = max(0.0, min_interval)
        self.max_retries = max(0, max_retries)
        self._client = client or httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        self._owns_client = client is None
        self._lock = asyncio.Lock()
        self._next_request = 0.0

    async def __aenter__(self) -> "AsyncHTTPTransport":  # noqa: PYI034
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _pace(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next_request > now:
                await asyncio.sleep(self._next_request - now)
            self._next_request = time.monotonic() + self.min_interval

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(value)
                return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                return None

    async def get(
        self, url: str, *, params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        retryable = {408, 425, 429, 500, 502, 503, 504}
        for attempt in range(self.max_retries + 1):
            await self._pace()
            try:
                response = await self._client.get(url, params=params, headers=headers)
                if response.status_code not in retryable:
                    response.raise_for_status()
                    return response
                if attempt == self.max_retries:
                    response.raise_for_status()
                delay = self._retry_after(response)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self.max_retries:
                    raise
                delay = None
            if delay is None:
                delay = min(30.0, 0.5 * (2 ** attempt)) + random.uniform(0, 0.2)
            await asyncio.sleep(delay)
        raise RuntimeError("unreachable")

