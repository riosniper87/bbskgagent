"""Unified normalized record schema for ingestion (design §4)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ExtractionKind = Literal["profile", "deterministic", "fallback", "llm", "ocr"]


class Provenance(BaseModel):
    source_ref: str
    locator: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)
    extraction: ExtractionKind = "deterministic"


class NormalizedRecord(BaseModel):
    post_id: str
    source_type: str
    title: str = ""
    body: str
    provenance: Provenance
    attachment_name: str = ""
    damdang: str | None = None
    damdangs: list[str] = Field(default_factory=list)
    category_value: str | None = None
    product_codes: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    temporal: dict[str, Any] = Field(default_factory=dict)
    review_flag: str | None = None
