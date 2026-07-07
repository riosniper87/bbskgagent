"""Q&A request/response schemas."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TimeMode(str, Enum):
    active_on = "active_on"
    posted_between = "posted_between"
    observable_on = "observable_on"
    version_diff = "version_diff"
    none = "none"


class QuestionIntent(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    damdang_hints: list[str] = Field(default_factory=list)
    product_codes: list[str] = Field(default_factory=list)
    notice_kinds: list[str] = Field(default_factory=list)
    time_mode: TimeMode = TimeMode.none
    query_date: date | None = None
    date_from: date | None = None
    date_to: date | None = None
    refine_query: str | None = None


class TemporalScope(BaseModel):
    time_mode: TimeMode
    query_date: date | None = None
    date_from: date | None = None
    date_to: date | None = None
    description: str = ""


class RetrievalHit(BaseModel):
    card_id: str
    damdang: str
    headline: str
    post_id: str
    post_title: str
    posted_date: str
    attachment_name: str
    source_ref: str
    product_codes: list[str] = Field(default_factory=list)
    score: float = 0.0
    temporal: dict[str, Any] = Field(default_factory=dict)
    body_excerpt: str = ""
    tables_summary: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    post_url: str | None = None


class AttachmentRef(BaseModel):
    attachment_id: str
    attachment_name: str
    post_id: str
    post_title: str
    kind: str | None = None
    path: str | None = None
    post_url: str


class Citation(BaseModel):
    card_id: str
    headline: str
    post_title: str
    attachment_name: str


class ToolTrace(BaseModel):
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    ms: int = 0


class QAResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    hits: list[RetrievalHit] = Field(default_factory=list)
    damdangs: list[str] = Field(default_factory=list)
    temporal_scope: TemporalScope | None = None
    traces: list[ToolTrace] = Field(default_factory=list)


class QAAskRequest(BaseModel):
    question: str
    as_of: str | None = None
    damdang: str | None = None
    query_date: date | None = None
    anchor_post_id: str | None = None
    anchor_source_ref: str | None = None


class QAAskBody(BaseModel):
    """HTTP JSON body for POST /api/qa/ask (dates as ISO strings)."""
    question: str
    as_of: str | None = None
    damdang: str | None = None
    query_date: str | None = None
    anchor_post_id: str | None = None
    anchor_source_ref: str | None = None


class SuggestQuestionBody(BaseModel):
    """Optional body for POST /api/qa/suggest-question."""
    seed: int | None = None


class SuggestQuestionResponse(BaseModel):
    question: str
    post_id: str
    post_title: str
    posted_date: str
    source_type: str
    source_label: str
    source_ref: str
    excerpt_preview: str
    excerpt_full: str
    seed: int | None = None
    post_url: str


class QASearchBody(BaseModel):
    """HTTP JSON body for POST /api/qa/search (no LLM)."""
    question: str
    as_of: str | None = None
    damdang: str | None = None
    query_date: str | None = None
    keywords: list[str] | None = None
    limit: int = 10


class QASearchResponse(BaseModel):
    hits: list[RetrievalHit] = Field(default_factory=list)
    damdangs_used: list[str] = Field(default_factory=list)
    index_loaded: bool = False
    traces: list[ToolTrace] = Field(default_factory=list)
