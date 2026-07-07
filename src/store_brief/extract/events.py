"""Extract typed Events from a post and its parsed attachments.

Flow per post:
  1. Run the VLM over every extracted image -> ImageNotes / ExtractedTables (llm.vision).
  2. Assemble a text bundle (post body + parsed attachment text + image descriptions).
  3. Ask the LLM for structured events, constrained to the seed category vocab.
  4. Materialize Event objects; attach tables/images; compute a stable id.

This is the only place that turns free text into structured records; everything
downstream is deterministic.
"""

from __future__ import annotations

import hashlib
from datetime import date

from store_brief.extract.provenance import match_refs_for_draft, sanitize_post_events, _ref_matches
from store_brief.extract.schema import (
    Event,
    EventExtractionResult,
    EventType,
    ExtractedEventDraft,
    ExtractedTable,
)
from store_brief.llm import prompts, vision
from store_brief.llm.client import pydantic_json_schema

MAX_BODY_CHARS = 6_000
MAX_ATTACH_BLOB_CHARS = 10_000
MAX_VLM_IMAGES_PER_POST = 6

_CAT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("대형가전", ["대형가전", "냉장고", "세탁기", "건조기", "에어컨", "TV", "원바디"]),
    ("주방", ["주방", "커피머신", "정수기", "음식물", "취사", "레인지"]),
    ("모바일·IT", ["IT", "PC", "노트북", "키보드", "태블릿", "스마트"]),
    ("계절가전", ["선풍기", "에어컨", "겨울", "여름", "계절"]),
    ("생활가전", ["생활", "청소기", "공기청정", "생활주방"]),
    ("Hobby", ["Hobby", "취미", "드론", "RC"]),
    ("KBB", ["KBB", "비데", "욕실"]),
    ("스마트홈", ["ISP", "POG", "연출", "하이라이트"]),
]


def _infer_categories(text: str, vocab: list[str]) -> list[str]:
    found = [cat for cat, kws in _CAT_KEYWORDS if cat in vocab and any(k in text for k in kws)]
    return found or (["기타"] if "기타" in vocab else [vocab[0]] if vocab else ["기타"])


def _normalize_draft(raw: ExtractedEventDraft, post, vocab: list[str]) -> ExtractedEventDraft:
    blob = f"{raw.title}\n{raw.summary}\n{post.title}\n{post.body[:500]}"
    if not raw.branches:
        raw.branches = ["전점"]
    if not raw.categories:
        raw.categories = _infer_categories(blob, vocab + ["기타"])
    return raw


def _truncate(text: str, limit: int, label: str = "") -> str:
    if len(text) <= limit:
        return text
    note = f"\n…({label} {len(text) - limit}자 생략)" if label else "\n…(생략)"
    return text[:limit] + note


def _event_id(source_post_id: str, title: str) -> str:
    return hashlib.sha1(f"{source_post_id}|{title}".encode()).hexdigest()[:16]


def _parse_date(val: str | None) -> date | None:
    if not val or val == "null":
        return None
    try:
        return date.fromisoformat(val[:10])
    except ValueError:
        return None


def _materialize_draft(
    raw: ExtractedEventDraft,
    post,
    parsed_attachments,
    tables,
    notes,
) -> Event:
    title = raw.title.strip() or post.title
    evt_type = raw.type
    try:
        et = EventType(evt_type)
    except ValueError:
        et = EventType.other

    matched_refs = match_refs_for_draft(
        raw, parsed_attachments, notes, tables, post_id=post.id,
    )

    def belongs(ref: str) -> bool:
        return _ref_matches(ref, matched_refs)

    scoped_notes = [n for n in notes if belongs(n.source_ref)]
    scoped_tables = [t for t in tables if belongs(t.source_ref)]
    scoped_refs = sorted(
        matched_refs
        | {n.source_ref for n in scoped_notes}
        | {t.source_ref for t in scoped_tables}
    )

    branches = raw.branches or ["전점"]
    return Event(
        id=_event_id(post.id, title),
        type=et,
        title=title,
        summary=raw.summary,
        categories=raw.categories,
        branches=branches,
        valid_from=_parse_date(raw.valid_from),
        valid_to=_parse_date(raw.valid_to),
        effective_date=_parse_date(raw.effective_date),
        source_post_id=post.id,
        attachment_refs=scoped_refs,
        tables=scoped_tables,
        images=scoped_notes,
        raw_excerpt=post.body[:500],
    )


def _tables_from_parsed(parsed_attachments) -> list[ExtractedTable]:
    out: list[ExtractedTable] = []
    for pa in parsed_attachments:
        for i, st in enumerate(getattr(pa, "tables", None) or []):
            out.append(ExtractedTable(
                source_ref=f"{pa.attachment_id}#table{i}",
                title=st.title,
                columns=list(st.columns),
                rows=[list(row) for row in st.rows],
            ))
    return out


def _skip_excel_sheet_vlm(pa, ref: str) -> bool:
    if not getattr(pa, "parse_mode", "").startswith("vlm"):
        return False
    if not getattr(pa, "tables", None):
        return False
    return ref.startswith(f"{pa.attachment_id}#")


def extract_events(post, parsed_attachments, categories: list[str], llm) -> list[Event]:
    notes: list = []
    tables = _tables_from_parsed(parsed_attachments)
    vlm_count = 0
    for pa in parsed_attachments:
        for img_path, ref in pa.image_paths:
            if _skip_excel_sheet_vlm(pa, ref):
                continue
            if vlm_count >= MAX_VLM_IMAGES_PER_POST:
                break
            note, table = vision.describe(img_path, ref, llm)
            vlm_count += 1
            notes.append(note)
            if table:
                tables.append(table)

    att_text = "\n\n".join(pa.text for pa in parsed_attachments if pa.text)
    img_text = "\n".join(f"- ({n.kind}) {n.description}" for n in notes)
    attachments_blob = "\n".join(filter(None, [att_text, img_text])) or "(없음)"
    attachments_blob = _truncate(attachments_blob, MAX_ATTACH_BLOB_CHARS, "첨부")

    body = _truncate(post.body, MAX_BODY_CHARS, "본문")

    system = prompts.EXTRACT_EVENTS_SYSTEM.format(categories=", ".join(categories))
    user = prompts.EXTRACT_EVENTS_USER.format(
        title=post.title, posted_date=post.posted_date,
        body=body, attachments=attachments_blob,
    )

    schema = pydantic_json_schema(EventExtractionResult)
    data = llm.complete_structured(
        user, system=system, json_schema=schema, schema_name="event_extraction",
    )
    result = EventExtractionResult.model_validate(data)
    drafts = [_normalize_draft(d, post, categories) for d in result.events]
    if not drafts:
        drafts = [ExtractedEventDraft(
            type="공지", title=post.title, summary=post.body[:200] or post.title,
            categories=["기타"], branches=["전점"],
        )]

    events = [
        _materialize_draft(raw, post, parsed_attachments, tables, notes)
        for raw in drafts
    ]
    cleaned, _ = sanitize_post_events(events, post, parsed_attachments)
    return cleaned
