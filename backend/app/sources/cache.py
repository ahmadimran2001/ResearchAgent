"""Small on-disk cache for respectful, repeatable scholarly searches."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .adapters import LiteratureSource
from .models import Paper


class CachedLiteratureSource:
    """Wrap a source and cache canonical responses without credentials."""

    def __init__(
        self,
        source: LiteratureSource,
        cache_dir: Path,
        *,
        ttl_seconds: int = 24 * 60 * 60,
    ) -> None:
        self.source = source
        self.name = source.name
        self.cache_dir = cache_dir
        self.ttl_seconds = max(0, ttl_seconds)

    def _path(self, query: str, limit: int) -> Path:
        key = hashlib.sha256(
            f"{self.name}\0{limit}\0{query.casefold().strip()}".encode()
        ).hexdigest()
        return self.cache_dir / self.name / f"{key}.json"

    async def search(self, query: str, limit: int = 20) -> list[Paper]:
        path = self._path(query, limit)
        if path.exists() and time.time() - path.stat().st_mtime <= self.ttl_seconds:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                return [Paper.model_validate(item) for item in payload]
            except (OSError, ValueError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
        papers = await self.source.search(query, limit)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                [paper.model_dump(mode="json") for paper in papers],
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
        return papers

    async def aclose(self) -> None:
        await self.source.aclose()

