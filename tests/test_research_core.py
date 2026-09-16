from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.app.research.drafting import (
    DocumentType,
    DraftClaim,
    DraftDocument,
    DraftingService,
    DraftRequest,
    DraftSection,
    EvidenceLedger,
    EvidenceSource,
    SearchMethodology,
    SectionDraftResponse,
    UnknownCitationError,
    export_bibtex,
    export_markdown,
)
from backend.app.research.novelty import CandidateResearchIdea, rank_research_ideas
from backend.app.research.stages import drafting_stage, novelty_stage, research_stage
from backend.app.research.workflow import WorkflowContext
from backend.app.sources.cache import CachedLiteratureSource
from backend.app.sources.http import AsyncHTTPTransport
from backend.app.sources.models import Paper, Provenance
from backend.app.sources.normalize import deduplicate_papers, normalize_doi
from backend.app.storage import Database, ResearchRepository


def paper() -> Paper:
    return Paper(
        title="A reproducible study of local research assistants",
        abstract="This study evaluates evidence-grounded local research assistants.",
        authors=["Ada Researcher"],
        year=2025,
        doi="10.1000/example",
        url="https://doi.org/10.1000/example",
        concepts=["research assistants", "reproducibility"],
        provenance=[
            Provenance(
                source="openalex",
                source_id="W1",
                url="https://openalex.org/W1",
                retrieved_at=datetime.now(timezone.utc).isoformat(),
            )
        ],
    )


class FakeLLM:
    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type,
    ) -> Any:
        del system_prompt
        if response_model.__name__ == "IdeaSet":
            return response_model(
                ideas=[
                    CandidateResearchIdea(
                        title=f"Idea {number}",
                        description="Test a bounded research gap with public evidence.",
                        keywords=["evidence", "gap"],
                        feasibility=0.8,
                    )
                    for number in range(1, 4)
                ]
            )
        payload = json.loads(user_prompt)
        source_id = payload["evidence_ledger"]["sources"][0]["id"]
        return SectionDraftResponse(
            content=f"Supported statement [@{source_id}].",
            claims=[DraftClaim(text="Supported statement.", citation_ids=[source_id])],
            citation_ids=[source_id],
        )


def repository(tmp_path: Path) -> ResearchRepository:
    database = Database(tmp_path / "research.sqlite3")
    database.initialize()
    return ResearchRepository(database)


@pytest.mark.asyncio
async def test_integrated_research_novelty_and_drafting(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    project = repo.create_project("Local research assistants", "How can evidence be verified?")
    context = WorkflowContext(
        project=project,
        stage="research",
        repository=repo,
        llm=FakeLLM(),  # type: ignore[arg-type]
        artifacts=[],
    )
    research = await research_stage(context)
    assert len(research.items) == 3
    repo.add_artifact(project["id"], "research", research.model_dump(mode="json"))
    repo.add_artifact(
        project["id"],
        "sources",
        {
            "title": "Sources",
            "summary": "One canonical record",
            "items": [paper().model_dump(mode="json")],
        },
    )
    context.artifacts = repo.list_artifacts(project["id"])

    novelty = await novelty_stage(context)
    assert "does not guarantee" in novelty["summary"]
    assert novelty["coverage"]["records_screened"] == 1

    draft = await drafting_stage(context)
    document = DraftDocument.model_validate(draft["document"])
    assert document.sections
    assert "Draft warning" in export_markdown(document)
    assert "10.1000/example" in export_bibtex(document)


def test_novelty_is_bounded_and_explainable() -> None:
    report = rank_research_ideas(
        "research assistants",
        [
            CandidateResearchIdea(
                title="Evidence-grounded research assistants",
                description="Validate claims against primary sources.",
                feasibility=0.7,
            )
        ],
        [paper()],
    )
    assert report.ranked_ideas[0].nearest_works
    assert "does not guarantee" in report.disclaimer


def test_unknown_citation_is_rejected_from_export() -> None:
    source = EvidenceSource(
        id="known",
        title="Known source",
        evidence_summary="Supported evidence.",
        provenance="fixture",
    )
    document = DraftDocument(
        title="Unsafe draft",
        document_type=DocumentType.PROPOSAL,
        sections=[
            DraftSection(
                heading="Claim",
                content="Invented [@unknown].",
                citation_ids=["unknown"],
            )
        ],
        ledger=EvidenceLedger(sources=[source]),
        search_methodology=SearchMethodology(databases=["fixture"], queries=["test"]),
        citation_keys={"known": "KnownndSource"},
    )
    with pytest.raises(UnknownCitationError):
        export_markdown(document)


def test_normalization_and_deduplication_merge_provenance() -> None:
    first = paper()
    duplicate = first.model_copy(
        update={
            "title": " A reproducible study of local research assistants ",
            "provenance": [
                Provenance(
                    source="crossref",
                    source_id="10.1000/example",
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                )
            ],
        }
    )
    merged = deduplicate_papers([first, duplicate])
    assert normalize_doi("https://doi.org/10.1000/EXAMPLE") == "10.1000/example"
    assert len(merged) == 1
    assert {item.source for item in merged[0].provenance} == {"openalex", "crossref"}


class CountingSource:
    name = "fixture"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, limit: int = 20) -> list[Paper]:
        del query, limit
        self.calls += 1
        return [paper()]

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_scholarly_cache_avoids_duplicate_provider_calls(tmp_path: Path) -> None:
    source = CountingSource()
    cached = CachedLiteratureSource(source, tmp_path)
    first = await cached.search("evidence", 5)
    second = await cached.search("evidence", 5)
    assert first == second
    assert source.calls == 1


@pytest.mark.asyncio
async def test_http_transport_retries_rate_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = AsyncHTTPTransport(
        client=client, min_interval=0, max_retries=1, timeout=1
    )
    response = await transport.get("https://example.test/papers")
    await client.aclose()
    assert response.json() == {"ok": True}
    assert calls == 2


@pytest.mark.asyncio
async def test_imrad_results_reject_scholarly_evidence_as_generated_results() -> None:
    source = EvidenceSource(
        id="scholarly",
        title="Prior work",
        evidence_summary="A prior paper reported a result.",
        provenance="fixture",
    )
    request = DraftRequest(
        title="No fabricated results",
        document_type=DocumentType.IMRAD,
        objective="Test the evidence boundary",
        ledger=EvidenceLedger(sources=[source]),
        search_methodology=SearchMethodology(databases=["fixture"], queries=["boundary"]),
    )
    with pytest.raises(ValueError, match="Results may cite only completed experiment"):
        await DraftingService(FakeLLM()).draft(request)

