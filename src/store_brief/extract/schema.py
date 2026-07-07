"""Core data model.

The typed temporal *Event* is the heart of the system. Posts and attachments are
normalized into Events, which are persisted in the store. All date-based reporting
(expiring today, new this week, policy diffs) runs deterministically over Event fields,
so the LLM only ever produces/edits structured records — it never does date math.

Note: the deterministic logic in `temporal/` and `relevance/` reads Event attributes by
name only (duck typing), so it does not import this module. That keeps the date/matching
core testable without pydantic installed.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

# Sentinel meaning "applies to every branch" — see relevance/mapping.py
ALL_BRANCHES = "전점"


class EventType(str, Enum):
    promotion = "판촉"      # sale / discount with a validity window
    event = "이벤트"        # in-store event, demo, fair
    policy = "정책"         # operational policy; versioned via version_of
    notice = "공지"         # general announcement
    price_stock = "가격_재고"  # price change / stock alert
    other = "기타"


class ImageNote(BaseModel):
    """VLM output for a single image (standalone file, or embedded in pptx/pdf)."""
    source_ref: str                 # e.g. "att_12#img3"
    kind: str                       # 사진 | 표 | 차트 | 포스터 | 도식 | 기타
    description: str                # concise Korean description


class ExtractedTable(BaseModel):
    """A table recovered from an attachment (xlsx cells, or VLM/OCR over a table image).

    For the prototype we trust auto-extraction; `confidence` and `needs_review` are the
    hooks where a later OCR<->VLM cross-check loop will write its verdict.
    """
    source_ref: str
    title: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    confidence: float | None = None     # reserved for future verification loop
    needs_review: bool = False          # reserved for future verification loop


class Event(BaseModel):
    id: str                              # stable hash of (source_post_id + title) or uuid
    type: EventType
    title: str
    summary: str                         # 1-3 sentence Korean summary
    theme: str | None = None             # free-form discovered theme label

    # Targeting — drives relevance. Categories constrained to the seed vocab + "기타".
    categories: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=lambda: [ALL_BRANCHES])

    # Temporal fields — drive all date-based reporting.
    valid_from: date | None = None       # 판촉/이벤트 시작
    valid_to: date | None = None         # 판촉/이벤트 종료 ("오늘 종료" 판정용)
    effective_date: date | None = None   # 정책 시행일

    # Versioning — a policy update points to the record it replaces.
    version_of: str | None = None        # prior Event.id in the chain

    # Provenance + payload.
    source_post_id: str
    attachment_refs: list[str] = Field(default_factory=list)
    tables: list[ExtractedTable] = Field(default_factory=list)
    images: list[ImageNote] = Field(default_factory=list)
    raw_excerpt: str | None = None

    # Store bookkeeping — set by the store, not the extractor.
    first_seen: date | None = None       # 저장소 최초 관측일 ("이번주 신규" 판정용)
    last_updated: date | None = None

    # Wiki routing — set by regroup pipeline (product code → HISIS → cat.txt).
    product_codes: list[str] = Field(default_factory=list)
    damdang_tags: list[str] = Field(default_factory=list)
    routing_basis: str | None = None       # "product" | "category"


class Attachment(BaseModel):
    id: str
    filename: str
    path: str
    kind: str                            # excel | pptx | pdf | image | unknown


class Post(BaseModel):
    id: str
    title: str
    body: str
    posted_date: date
    attachments: list[Attachment] = Field(default_factory=list)


class Employee(BaseModel):
    """R&R record. A category owner has categories=[...]; a 점장 has is_store_manager=True.

    Relevance rule (see relevance/mapping.py):
      - 점장: every event touching their branch.
      - category owner: events touching their branch AND one of their categories.
    """
    id: str
    name: str
    branch: str                          # 지점 명칭
    branch_code: str | None = None       # 지점 코드 (rnr.txt)
    is_store_manager: bool = False       # 점장 여부
    categories: list[str] = Field(default_factory=list)  # 담당 카테고리


class ReportSections(BaseModel):
    expiring_today: list[Event] = Field(default_factory=list)
    new_this_week: list[Event] = Field(default_factory=list)
    policy_changes: list[dict] = Field(default_factory=list)  # {old: Event, new: Event, diff: str}
    current_relevant: list[Event] = Field(default_factory=list)


class ReportContext(BaseModel):
    employee: Employee
    as_of: date
    sections: ReportSections
    generated_prose: dict[str, str] = Field(default_factory=dict)  # section_key -> HTML-ready prose


# --- LLM structured-output drafts (dates as str; converted after validation) ---------

class ExtractedEventDraft(BaseModel):
    type: str = Field(description="판촉|이벤트|정책|공지|가격_재고|기타")
    title: str
    summary: str = Field(description="1~3문장 한국어 요약")
    categories: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None
    effective_date: str | None = None
    is_policy_update: bool = False


class EventExtractionResult(BaseModel):
    events: list[ExtractedEventDraft] = Field(default_factory=list)


class VisionTableDraft(BaseModel):
    title: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class VisionDescribeResult(BaseModel):
    kind: str = Field(description="사진|표|차트|포스터|도식|기타")
    description: str
    table: VisionTableDraft | None = None


class TableRegionDraft(BaseModel):
    title: str | None = None
    header_rows: list[int] = Field(default_factory=list, description="0-based header row indices")
    data_start_row: int = Field(description="0-based first data row")
    columns: list[str] = Field(default_factory=list)
    col_indices: list[int] = Field(default_factory=list, description="raw grid column index per column")
    data_end_row: int | None = None
    region: int = 0


class TableLayoutDraft(BaseModel):
    sheet: str
    regions: list[TableRegionDraft] = Field(default_factory=list)
    confidence: float = 0.8
    needs_review: bool = False
