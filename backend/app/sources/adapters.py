"""Async adapters for public scholarly-literature APIs."""

import re
from datetime import date, datetime, timezone
from functools import partial
from typing import Any, Protocol
from xml.etree import ElementTree

from .http import AsyncHTTPTransport
from .models import Paper, Provenance
from .normalize import normalize_doi, reconstruct_openalex_abstract


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _text(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(re.sub(r"<[^>]+>", " ", value).split()) or None


def _atom_text(entry: ElementTree.Element, namespace: str, tag: str) -> str | None:
    return entry.findtext(f"{namespace}{tag}")


class LiteratureSource(Protocol):
    name: str

    async def search(self, query: str, limit: int = 20) -> list[Paper]: ...
    async def aclose(self) -> None: ...


class _BaseSource:
    name = "base"

    def __init__(self, transport: AsyncHTTPTransport | None, min_interval: float) -> None:
        self.transport = transport or AsyncHTTPTransport(min_interval=min_interval)
        self._owns_transport = transport is None

    async def aclose(self) -> None:
        if self._owns_transport:
            await self.transport.aclose()

    def provenance(self, source_id: str | None, url: str | None, **raw: Any) -> list[Provenance]:
        return [Provenance(
            source=self.name, source_id=source_id, url=url,
            retrieved_at=_now(), raw={k: v for k, v in raw.items() if v is not None},
        )]


class OpenAlexSource(_BaseSource):
    name = "openalex"
    endpoint = "https://api.openalex.org/works"

    def __init__(
        self, api_key: str | None = None, email: str | None = None,
        transport: AsyncHTTPTransport | None = None,
    ) -> None:
        super().__init__(transport, min_interval=0.12)
        self.api_key, self.email = api_key, email

    async def search(self, query: str, limit: int = 20) -> list[Paper]:
        params: dict[str, Any] = {"search": query, "per_page": min(max(limit, 1), 100)}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["mailto"] = self.email
        items = self.transport.get(self.endpoint, params=params)
        payload = (await items).json()
        papers: list[Paper] = []
        for item in payload.get("results", []):
            authors = [
                x.get("author", {}).get("display_name")
                for x in item.get("authorships", [])
                if x.get("author", {}).get("display_name")
            ]
            location = item.get("primary_location") or {}
            source = location.get("source") or {}
            concepts = [
                x["display_name"] for x in item.get("concepts", [])
                if x.get("display_name")
            ]
            papers.append(Paper(
                title=item.get("display_name") or item.get("title") or "Untitled",
                abstract=reconstruct_openalex_abstract(item.get("abstract_inverted_index")),
                authors=authors, year=item.get("publication_year"),
                publication_date=_date(item.get("publication_date")),
                doi=normalize_doi(item.get("doi")),
                url=location.get("landing_page_url") or item.get("id"),
                venue=source.get("display_name"),
                citation_count=item.get("cited_by_count"),
                concepts=concepts[:20],
                provenance=self.provenance(
                    item.get("id"), item.get("id"), type=item.get("type"),
                    updated_date=item.get("updated_date"),
                ),
            ))
        return papers


class CrossrefSource(_BaseSource):
    name = "crossref"
    endpoint = "https://api.crossref.org/works"

    def __init__(
        self, api_key: str | None = None, email: str | None = None,
        transport: AsyncHTTPTransport | None = None,
    ) -> None:
        # Crossref list queries allow 3 requests/second in the polite pool.
        super().__init__(transport, min_interval=0.34 if email else 1.0)
        self.api_key, self.email = api_key, email

    async def search(self, query: str, limit: int = 20) -> list[Paper]:
        params: dict[str, Any] = {"query.bibliographic": query, "rows": min(max(limit, 1), 1000)}
        if self.email:
            params["mailto"] = self.email
        headers = {"Crossref-Plus-API-Token": f"Bearer {self.api_key}"} if self.api_key else None
        payload = (await self.transport.get(self.endpoint, params=params, headers=headers)).json()
        papers: list[Paper] = []
        for item in payload.get("message", {}).get("items", []):
            parts = item.get("published", {}).get("date-parts", [[]])[0]
            publication_date = None
            if parts:
                try:
                    publication_date = date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
                except (TypeError, ValueError):
                    pass
            authors = [
                " ".join(filter(None, (x.get("given"), x.get("family"))))
                for x in item.get("author", [])
            ]
            title = next(iter(item.get("title") or []), "Untitled")
            venue = next(iter(item.get("container-title") or []), None)
            papers.append(Paper(
                title=title, abstract=_text(item.get("abstract")), authors=authors,
                year=parts[0] if parts else None, publication_date=publication_date,
                doi=normalize_doi(item.get("DOI")), url=item.get("URL"),
                venue=venue, citation_count=item.get("is-referenced-by-count"),
                provenance=self.provenance(
                    item.get("DOI"), item.get("URL"), type=item.get("type"),
                    deposited=item.get("deposited"),
                ),
            ))
        return papers


class SemanticScholarSource(_BaseSource):
    name = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(
        self, api_key: str | None = None,
        transport: AsyncHTTPTransport | None = None,
    ) -> None:
        # A standard authenticated Semantic Scholar key is allocated 1 request/second.
        super().__init__(transport, min_interval=1.0)
        self.api_key = api_key

    async def search(self, query: str, limit: int = 20) -> list[Paper]:
        fields = "paperId,title,abstract,authors,year,publicationDate,externalIds,url,venue,citationCount,fieldsOfStudy"
        headers = {"x-api-key": self.api_key} if self.api_key else None
        params = {"query": query, "limit": min(max(limit, 1), 100), "fields": fields}
        payload = (await self.transport.get(self.endpoint, params=params, headers=headers)).json()
        papers: list[Paper] = []
        for item in payload.get("data", []):
            external = item.get("externalIds") or {}
            papers.append(Paper(
                title=item.get("title") or "Untitled",
                abstract=item.get("abstract"),
                authors=[x["name"] for x in item.get("authors", []) if x.get("name")],
                year=item.get("year"), publication_date=_date(item.get("publicationDate")),
                doi=normalize_doi(external.get("DOI")), url=item.get("url"),
                venue=item.get("venue"), citation_count=item.get("citationCount"),
                concepts=item.get("fieldsOfStudy") or [],
                provenance=self.provenance(
                    item.get("paperId"), item.get("url"), external_ids=external,
                ),
            ))
        return papers


class ArxivSource(_BaseSource):
    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"
    _atom = "{http://www.w3.org/2005/Atom}"
    _arxiv = "{http://arxiv.org/schemas/atom}"

    def __init__(self, transport: AsyncHTTPTransport | None = None) -> None:
        super().__init__(transport, min_interval=3.0)

    async def search(self, query: str, limit: int = 20) -> list[Paper]:
        params = {
            "search_query": f"all:{query}", "start": 0,
            "max_results": min(max(limit, 1), 100), "sortBy": "relevance",
        }
        root = ElementTree.fromstring((await self.transport.get(self.endpoint, params=params)).text)
        papers: list[Paper] = []
        for entry in root.findall(f"{self._atom}entry"):
            get = partial(_atom_text, entry, self._atom)
            source_id = get("id")
            published = get("published")
            links = {
                node.attrib.get("rel", "alternate"): node.attrib.get("href")
                for node in entry.findall(f"{self._atom}link")
            }
            doi = entry.findtext(f"{self._arxiv}doi")
            papers.append(Paper(
                title=" ".join((get("title") or "Untitled").split()),
                abstract=" ".join((get("summary") or "").split()) or None,
                authors=[
                    node.findtext(f"{self._atom}name") or ""
                    for node in entry.findall(f"{self._atom}author")
                ],
                year=int(published[:4]) if published else None,
                publication_date=_date(published), doi=normalize_doi(doi),
                url=links.get("alternate") or source_id,
                venue="arXiv",
                concepts=[
                    node.attrib["term"] for node in entry.findall(f"{self._atom}category")
                    if node.attrib.get("term")
                ],
                provenance=self.provenance(
                    source_id.rsplit("/", 1)[-1] if source_id else None,
                    source_id, updated=get("updated"),
                ),
            ))
        return papers

