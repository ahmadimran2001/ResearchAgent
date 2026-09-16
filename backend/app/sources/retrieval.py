"""Query expansion and multi-source retrieval orchestration."""

import asyncio
import inspect
import re
from collections.abc import Awaitable, Sequence
from typing import Protocol

from .adapters import (
    ArxivSource,
    CrossrefSource,
    LiteratureSource,
    OpenAlexSource,
    SemanticScholarSource,
)
from .models import SearchResponse
from .normalize import deduplicate_papers


class QueryExpansionLLM(Protocol):
    def expand_queries(
        self, query: str, limit: int
    ) -> Sequence[str] | Awaitable[Sequence[str]]: ...


_RELATED = {
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "llm": "large language model",
    "nlp": "natural language processing",
    "cv": "computer vision",
}


async def expand_query(
    query: str, llm: QueryExpansionLLM | None = None, limit: int = 3
) -> list[str]:
    """Expand a query, retaining deterministic behavior if the LLM is absent/fails."""
    query = " ".join(query.split())
    if not query:
        raise ValueError("query must not be empty")
    candidates: Sequence[str] = ()
    if llm is not None:
        try:
            result = llm.expand_queries(query, limit)
            expanded = await result if inspect.isawaitable(result) else result
            candidates = expanded or ()
        except Exception:  # noqa: BLE001 - injected clients may raise arbitrary SDK errors
            candidates = ()
    fallback = [query]
    words = re.findall(r"[A-Za-z0-9-]+", query.casefold())
    expansions = sorted({_RELATED[word] for word in words if word in _RELATED})
    if expansions:
        fallback.append(f"{query} {' '.join(expansions)}")
    if len(words) > 2:
        fallback.append(f'"{query}"')
    output: list[str] = []
    for value in [query, *candidates, *fallback]:
        cleaned = " ".join(str(value).split())
        if cleaned and cleaned.casefold() not in {x.casefold() for x in output}:
            output.append(cleaned)
        if len(output) >= max(1, limit):
            break
    return output


class LiteratureRetriever:
    """FastAPI-friendly service; create once and close at application shutdown."""

    def __init__(
        self,
        sources: Sequence[LiteratureSource] | None = None,
        query_llm: QueryExpansionLLM | None = None,
    ) -> None:
        self.sources: Sequence[LiteratureSource] = (
            (OpenAlexSource(), CrossrefSource(), SemanticScholarSource(), ArxivSource())
            if sources is None else sources
        )
        self.query_llm = query_llm

    async def __aenter__(self) -> "LiteratureRetriever":  # noqa: PYI034
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await asyncio.gather(*(source.aclose() for source in self.sources))

    async def search(
        self,
        query: str,
        *,
        per_source: int = 20,
        expansion_count: int = 3,
        max_results: int = 100,
    ) -> SearchResponse:
        if per_source < 1 or max_results < 1:
            raise ValueError("per_source and max_results must be positive")
        queries = await expand_query(query, self.query_llm, expansion_count)
        calls = [(source, expanded) for expanded in queries for source in self.sources]
        results = await asyncio.gather(
            *(source.search(expanded, per_source) for source, expanded in calls),
            return_exceptions=True,
        )
        papers, errors = [], {}
        for (source, expanded), result in zip(calls, results):
            if isinstance(result, BaseException):
                errors[f"{source.name}:{expanded}"] = f"{type(result).__name__}: {result}"
            else:
                papers.extend(result)
        merged = deduplicate_papers(papers)
        merged.sort(
            key=lambda paper: (
                paper.citation_count is not None,
                paper.citation_count or 0,
                paper.year or 0,
            ),
            reverse=True,
        )
        return SearchResponse(query=query, papers=merged[:max_results], errors=errors)

