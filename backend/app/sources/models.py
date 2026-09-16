"""Canonical literature models shared by all source adapters."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    source: str
    source_id: str | None = None
    url: str | None = None
    retrieved_at: datetime
    raw: dict[str, Any] = Field(default_factory=dict)


class Paper(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    publication_date: date | None = None
    doi: str | None = None
    url: str | None = None
    venue: str | None = None
    citation_count: int | None = None
    concepts: list[str] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)

class SearchResponse(BaseModel):
    query: str
    papers: list[Paper] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)

