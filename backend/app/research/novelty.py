"""Lightweight, explainable novelty screening against retrieved literature."""

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timezone
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from ..sources.models import Paper
from ..sources.normalize import normalize_title

_TOKEN = re.compile(r"[a-z0-9][a-z0-9-]+")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "using", "via",
    "we", "with",
}


class CandidateResearchIdea(BaseModel):
    title: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    feasibility: float = Field(0.5, ge=0.0, le=1.0)


class NearestWork(BaseModel):
    paper: Paper
    similarity: float
    overlapping_terms: list[str] = Field(default_factory=list)


class RankedResearchIdea(BaseModel):
    idea: CandidateResearchIdea
    rank: int
    score: float
    novelty_score: float
    relevance_score: float
    nearest_works: list[NearestWork] = Field(default_factory=list)


class NoveltyReport(BaseModel):
    query: str
    as_of: date
    ranked_ideas: list[RankedResearchIdea]
    disclaimer: str


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.casefold()) if token not in _STOP]


def _weighted_jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = Counter(left), Counter(right)
    terms = set(a) | set(b)
    if not terms:
        return 0.0
    intersection = sum(min(a[t], b[t]) for t in terms)
    union = sum(max(a[t], b[t]) for t in terms)
    return intersection / union


def _paper_text(paper: Paper) -> str:
    return " ".join(
        part for part in (
            paper.title,
            paper.abstract or "",
            " ".join(paper.concepts),
        ) if part
    )


def nearest_works(
    idea: CandidateResearchIdea,
    papers: Sequence[Paper],
    *,
    limit: int = 5,
) -> list[NearestWork]:
    """Rank lexical neighbors without embeddings or heavyweight ML libraries."""
    idea_text = f"{idea.title} {idea.description} {' '.join(idea.keywords)}"
    idea_tokens = _tokens(idea_text)
    idea_set: set[str] = set(idea_tokens)
    output: list[NearestWork] = []
    for paper in papers:
        paper_tokens = _tokens(_paper_text(paper))
        lexical = _weighted_jaccard(idea_tokens, paper_tokens)
        title_similarity = SequenceMatcher(
            None, normalize_title(idea.title), normalize_title(paper.title)
        ).ratio()
        # Token overlap carries meaning; title similarity catches close paraphrases.
        similarity = min(1.0, 0.75 * lexical + 0.25 * title_similarity)
        output.append(NearestWork(
            paper=paper,
            similarity=round(similarity, 4),
            overlapping_terms=sorted(idea_set.intersection(paper_tokens))[:20],
        ))
    output.sort(
        key=lambda match: (
            match.similarity,
            match.paper.citation_count or 0,
            match.paper.year or 0,
        ),
        reverse=True,
    )
    return output[:max(0, limit)]


def rank_research_ideas(
    query: str,
    ideas: Sequence[CandidateResearchIdea],
    papers: Sequence[Paper],
    *,
    nearest_limit: int = 5,
    as_of: date | None = None,
) -> NoveltyReport:
    """Screen and rank ideas; scores are triage signals, not novelty proof."""
    if not query.strip():
        raise ValueError("query must not be empty")
    query_tokens = _tokens(query)
    ranked: list[RankedResearchIdea] = []
    for idea in ideas:
        neighbors = nearest_works(idea, papers, limit=nearest_limit)
        nearest_similarity = neighbors[0].similarity if neighbors else 0.0
        novelty = max(0.0, 1.0 - nearest_similarity)
        idea_tokens = _tokens(f"{idea.title} {idea.description} {' '.join(idea.keywords)}")
        relevance = _weighted_jaccard(query_tokens, idea_tokens)
        # Saturate small query overlaps so concise queries are not overly penalized.
        relevance = min(1.0, math.sqrt(relevance))
        score = 0.55 * novelty + 0.30 * relevance + 0.15 * idea.feasibility
        ranked.append(RankedResearchIdea(
            idea=idea, rank=0, score=round(score, 4),
            novelty_score=round(novelty, 4),
            relevance_score=round(relevance, 4),
            nearest_works=neighbors,
        ))
    ranked.sort(
        key=lambda item: (item.score, item.novelty_score, item.idea.title.casefold()),
        reverse=True,
    )
    for index, item in enumerate(ranked, 1):
        item.rank = index
    report_date = as_of or datetime.now(timezone.utc).date()
    disclaimer = (
        f"As of {report_date.isoformat()}, this automated literature search and "
        "lexical comparison does not guarantee that any idea is novel, patentable, "
        "publishable, or absent from unindexed, unpublished, non-English, or later "
        "work. Verify claims with expert review and current database searches."
    )
    return NoveltyReport(
        query=query, as_of=report_date, ranked_ideas=ranked, disclaimer=disclaimer
    )

