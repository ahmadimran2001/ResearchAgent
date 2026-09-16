"""Literature retrieval public API."""

from .adapters import (
    ArxivSource,
    CrossrefSource,
    LiteratureSource,
    OpenAlexSource,
    SemanticScholarSource,
)
from .models import Paper, Provenance, SearchResponse
from .normalize import (
    deduplicate_papers,
    normalize_doi,
    normalize_title,
    reconstruct_openalex_abstract,
)
from .retrieval import LiteratureRetriever, QueryExpansionLLM, expand_query

__all__ = [
    "ArxivSource",
    "CrossrefSource",
    "LiteratureRetriever",
    "LiteratureSource",
    "OpenAlexSource",
    "Paper",
    "Provenance",
    "QueryExpansionLLM",
    "SearchResponse",
    "SemanticScholarSource",
    "deduplicate_papers",
    "expand_query",
    "normalize_doi",
    "normalize_title",
    "reconstruct_openalex_abstract",
]

