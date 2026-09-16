"""Integrated workflow handlers for evidence-first research."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from backend.app.config import get_settings
from backend.app.llm import OllamaError
from backend.app.research.drafting import (
    DocumentType,
    DraftingService,
    DraftRequest,
    EvidenceKind,
    EvidenceLedger,
    EvidenceSource,
    SearchMethodology,
)
from backend.app.research.novelty import CandidateResearchIdea, rank_research_ideas
from backend.app.research.workflow import StageResult, WorkflowContext
from backend.app.sources import (
    ArxivSource,
    CrossrefSource,
    LiteratureRetriever,
    OpenAlexSource,
    Paper,
    SemanticScholarSource,
)
from backend.app.sources.cache import CachedLiteratureSource


class IdeaSet(BaseModel):
    ideas: list[CandidateResearchIdea] = Field(min_length=3, max_length=8)


def _artifact_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    content = artifact.get("content", "{}")
    if isinstance(content, dict):
        return content
    try:
        value = json.loads(content)
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _latest_payload(context: WorkflowContext, kind: str) -> dict[str, Any] | None:
    for artifact in context.artifacts:
        if artifact.get("kind") == kind:
            return _artifact_payload(artifact)
    return None


def _paper_id(paper: Paper, index: int) -> str:
    if paper.doi:
        return "doi:" + re.sub(r"[^A-Za-z0-9_.:/-]", "", paper.doi)
    for item in paper.provenance:
        if item.source_id:
            safe = re.sub(r"[^A-Za-z0-9_.:/-]", "-", item.source_id)
            return f"{item.source}:{safe}"
    return f"paper:{index}"


async def research_stage(context: WorkflowContext) -> StageResult:
    """Generate testable candidate directions, explicitly pending literature screening."""

    prompt = {
        "topic": context.project["topic"],
        "question": context.project.get("question", ""),
        "requirements": [
            "Return 3 to 5 specific, testable research ideas.",
            "Do not claim any idea is novel before literature screening.",
            "Prefer feasible computational or literature-based studies.",
            "Provide keywords useful for falsifying the proposed novelty.",
        ],
    }
    try:
        generated = await context.llm.generate_structured(
            system_prompt=(
                "You propose candidate research directions for later evidence screening. "
                "Do not invent prior work, citations, novelty, or results."
            ),
            user_prompt=json.dumps(prompt, ensure_ascii=False),
            response_model=IdeaSet,
        )
        ideas = generated.ideas
    except OllamaError:
        topic = context.project["topic"].strip()
        ideas = [
            CandidateResearchIdea(
                title=f"Boundary conditions for {topic}",
                description=(
                    f"Systematically identify contexts where established findings about {topic} "
                    "do not generalize."
                ),
                keywords=[topic, "boundary conditions", "generalizability"],
                feasibility=0.7,
            ),
            CandidateResearchIdea(
                title=f"Reproducibility map of {topic}",
                description=(
                    f"Compare reported methods, datasets, and outcomes concerning {topic} and "
                    "test reproducibility where public data permit."
                ),
                keywords=[topic, "reproducibility", "systematic review"],
                feasibility=0.8,
            ),
            CandidateResearchIdea(
                title=f"Cross-domain transfer in {topic}",
                description=(
                    f"Evaluate whether methods used for {topic} transfer to an adjacent domain "
                    "under a predefined benchmark."
                ),
                keywords=[topic, "cross-domain", "benchmark"],
                feasibility=0.6,
            ),
        ]
    return StageResult(
        title="Candidate research directions",
        summary=(
            "These are hypotheses for screening, not claims of novelty. Run Sources and Novelty "
            "before selecting a direction."
        ),
        items=[idea.model_dump(mode="json") for idea in ideas],
    )


async def sources_stage(context: WorkflowContext) -> StageResult:
    settings = get_settings()
    query = " ".join(
        part
        for part in (
            context.project["topic"],
            context.project.get("question", ""),
        )
        if part
    )
    cache = settings.resolved_literature_cache_path
    sources = tuple(
        CachedLiteratureSource(source, cache)
        for source in (
            OpenAlexSource(settings.openalex_api_key, settings.scholarly_email),
            CrossrefSource(settings.crossref_api_key, settings.scholarly_email),
            SemanticScholarSource(settings.semantic_scholar_api_key),
            ArxivSource(),
        )
    )
    async with LiteratureRetriever(sources=sources) as retriever:
        response = await retriever.search(
            query,
            per_source=settings.literature_per_source,
            expansion_count=2,
            max_results=settings.literature_max_results,
        )
    databases = sorted(
        {
            provenance.source
            for paper in response.papers
            for provenance in paper.provenance
        }
    )
    return StageResult(
        title="Scholarly search results",
        summary=(
            f"Retrieved and deduplicated {len(response.papers)} records from "
            f"{', '.join(databases) or 'configured sources'}. "
            f"{len(response.errors)} bounded provider/query calls failed."
        ),
        items=[paper.model_dump(mode="json") for paper in response.papers],
    ).model_copy(
        update={
            "items": [paper.model_dump(mode="json") for paper in response.papers]
            + ([{"retrieval_errors": response.errors}] if response.errors else [])
        }
    )


async def novelty_stage(context: WorkflowContext) -> dict[str, Any]:
    source_payload = _latest_payload(context, "sources")
    if not source_payload:
        raise ValueError("Run the Sources stage before Novelty")
    papers = [
        Paper.model_validate(item)
        for item in source_payload.get("items", [])
        if isinstance(item, dict) and "title" in item
    ]
    research_payload = _latest_payload(context, "research")
    if research_payload:
        ideas = [
            CandidateResearchIdea.model_validate(item)
            for item in research_payload.get("items", [])
            if isinstance(item, dict) and "description" in item
        ]
    else:
        ideas = []
    if not ideas:
        ideas = (await _fallback_ideas(context)).ideas
    query = " ".join(
        filter(None, (context.project["topic"], context.project.get("question", "")))
    )
    report = rank_research_ideas(query, ideas, papers)
    return {
        "title": "Bounded novelty assessment",
        "summary": report.disclaimer,
        "items": [item.model_dump(mode="json") for item in report.ranked_ideas],
        "coverage": {
            "records_screened": len(papers),
            "searched_as_of": report.as_of.isoformat(),
            "databases": sorted(
                {
                    source.source
                    for paper in papers
                    for source in paper.provenance
                }
            ),
            "query": query,
        },
    }


async def _fallback_ideas(context: WorkflowContext) -> IdeaSet:
    result = await research_stage(context)
    return IdeaSet(ideas=[CandidateResearchIdea.model_validate(item) for item in result.items])


async def drafting_stage(context: WorkflowContext) -> dict[str, Any]:
    source_payload = _latest_payload(context, "sources")
    if not source_payload:
        raise ValueError("Run the Sources stage before Drafting")
    papers = [
        Paper.model_validate(item)
        for item in source_payload.get("items", [])
        if isinstance(item, dict) and "title" in item
    ]
    if not papers:
        raise ValueError("No scholarly evidence is available for drafting")
    evidence = []
    for index, paper in enumerate(papers[:30], 1):
        provenance = "; ".join(
            f"{item.source}:{item.source_id or item.url or 'record'}"
            for item in paper.provenance
        )
        evidence.append(
            EvidenceSource(
                id=_paper_id(paper, index),
                title=paper.title,
                authors=paper.authors,
                year=paper.year,
                abstract=paper.abstract,
                evidence_summary=(paper.abstract or paper.title)[:2000],
                doi=paper.doi,
                url=paper.url,
                venue=paper.venue,
                retrieved_at=datetime.now(timezone.utc),
                provenance=provenance or "scholarly search",
            )
        )
    experiment_count = 0
    for artifact in context.artifacts:
        if artifact.get("kind") != "experiments":
            continue
        payload = _artifact_payload(artifact)
        for item in payload.get("items", []):
            if not isinstance(item, dict) or item.get("state") != "succeeded":
                continue
            experiment_count += 1
            experiment_id = str(item.get("experiment_id", f"experiment-{experiment_count}"))
            metrics = item.get("metrics", {})
            evidence.append(
                EvidenceSource(
                    id=f"experiment:{experiment_id}",
                    title=f"Completed experiment: {experiment_id}",
                    kind=EvidenceKind.EXPERIMENT,
                    evidence_summary=json.dumps(
                        {"metrics": metrics, "input_sha256": item.get("input_sha256")},
                        ensure_ascii=False,
                        sort_keys=True,
                    )[:2000],
                    provenance="Local bounded experiment artifact",
                    experiment_completed=True,
                    metadata={
                        "input_sha256": item.get("input_sha256"),
                        "environment": item.get("environment", {}),
                    },
                )
            )
    query = " ".join(
        filter(None, (context.project["topic"], context.project.get("question", "")))
    )
    databases = sorted(
        {
            item.source
            for paper in papers
            for item in paper.provenance
        }
    )
    request = DraftRequest(
        title=context.project["topic"],
        document_type=DocumentType(context.project.get("document_type", "proposal")),
        objective=context.project.get("question") or context.project["topic"],
        ledger=EvidenceLedger(sources=evidence),
        search_methodology=SearchMethodology(
            databases=databases or ["configured scholarly sources"],
            queries=[query],
            records_retrieved=len(papers),
            result_limit=get_settings().literature_max_results,
            deduplication="DOI, then normalized title/author/year",
            limitations=[
                "This is a bounded metadata and abstract search, not an exhaustive review.",
                "Paywalled and unindexed full text may not have been searched.",
            ],
            provenance=[
                "Generated from canonical records retained by the local ResearchAgent workflow"
            ],
        ),
    )
    document = await DraftingService(context.llm).draft(request)
    return {
        "title": document.title,
        "summary": document.warning,
        "items": [
            {"heading": section.heading, "content": section.content}
            for section in document.sections
        ],
        "document": document.model_dump(mode="json"),
    }


async def experiments_stage(context: WorkflowContext) -> StageResult:
    return StageResult(
        title="Experiment approval required",
        summary=(
            "Upload a CSV and submit an allow-listed experiment specification. No generated "
            "code is executed; descriptive statistics, statistical tests, and small "
            "scikit-learn benchmarks are supported."
        ),
        items=[
            {"template": "descriptive_statistics"},
            {
                "template": "statistical_test",
                "tests": [
                    "independent_t_test",
                    "paired_t_test",
                    "mann_whitney_u",
                    "chi_square",
                ],
            },
            {"template": "sklearn_benchmark", "tasks": ["classification", "regression"]},
        ],
    )


async def exports_stage(context: WorkflowContext) -> StageResult:
    draft = _latest_payload(context, "drafting")
    if not draft or "document" not in draft:
        raise ValueError("Run the Drafting stage before Exports")
    return StageResult(
        title="Validated exports available",
        summary="Use the Markdown, BibTeX, or DOCX export links for this project.",
        items=[
            {"format": format_name, "url": f"/api/projects/{context.project['id']}/export/{format_name}"}
            for format_name in ("markdown", "bibtex", "docx")
        ],
    )


HANDLERS = {
    "research": research_stage,
    "sources": sources_stage,
    "novelty": novelty_stage,
    "drafting": drafting_stage,
    "experiments": experiments_stage,
    "exports": exports_stage,
}

