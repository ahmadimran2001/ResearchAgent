"""Normalization, abstract reconstruction, and conservative paper deduplication."""

import html
import re
import unicodedata
from collections.abc import Iterable
from difflib import SequenceMatcher

from .models import Paper

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _DOI_PREFIX.sub("", value.strip()).strip().rstrip(".,;)")
    match = _DOI.search(cleaned)
    return match.group(0).lower() if match else None


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value or "")).casefold()
    return " ".join(_NON_WORD.sub(" ", value).split())


def reconstruct_openalex_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positions: list[tuple[int, str]] = []
    for token, offsets in index.items():
        positions.extend((offset, token) for offset in offsets)
    return " ".join(token for _, token in sorted(positions)) or None


def _merge(left: Paper, right: Paper) -> Paper:
    data = left.model_dump()
    for field in (
        "abstract", "year", "publication_date", "doi", "url", "venue",
        "citation_count",
    ):
        current, incoming = data.get(field), getattr(right, field)
        if incoming is not None and (
            current is None
            or (field == "abstract" and len(incoming) > len(current))
            or (field == "citation_count" and incoming > current)
        ):
            data[field] = incoming
    data["authors"] = list(dict.fromkeys(left.authors + right.authors))
    data["concepts"] = list(dict.fromkeys(left.concepts + right.concepts))
    data["provenance"] = left.provenance + right.provenance
    return Paper(**data)


def deduplicate_papers(
    papers: Iterable[Paper], title_threshold: float = 0.94
) -> list[Paper]:
    """Merge exact DOI matches and very close normalized-title matches."""
    output: list[Paper] = []
    doi_positions: dict[str, int] = {}
    for paper in papers:
        paper.doi = normalize_doi(paper.doi)
        title = normalize_title(paper.title)
        duplicate: int | None = doi_positions.get(paper.doi) if paper.doi else None
        if duplicate is None and title:
            for index, existing in enumerate(output):
                existing_title = normalize_title(existing.title)
                same_year = (
                    paper.year is None
                    or existing.year is None
                    or abs(paper.year - existing.year) <= 1
                )
                if same_year and SequenceMatcher(None, title, existing_title).ratio() >= title_threshold:
                    duplicate = index
                    break
        if duplicate is None:
            output.append(paper)
            if paper.doi:
                doi_positions[paper.doi] = len(output) - 1
        else:
            output[duplicate] = _merge(output[duplicate], paper)
            if paper.doi:
                doi_positions[paper.doi] = duplicate
    return output

