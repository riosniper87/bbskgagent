"""Enrichment stage: product codes, damdang routing, keywords, temporal on NormalizedRecord."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Callable

from store_brief.extract.provenance import keyword_set, title_anchors
from store_brief.hisis.prd_codes import extract_model_skus, extract_prd_codes
from store_brief.ingestion.schema import NormalizedRecord
from store_brief.llmwiki.from_posts import infer_damdangs_from_text
from store_brief.llmwiki.grouping import (
    FALLBACK_KEY,
    MANAGER_KEY,
    product_damdang_for_codes,
)
from store_brief.temporal.meta import extract_temporal_meta

_BRAND_MARKETING_RE = re.compile(r"브랜드\s*마케팅|브랜드커뮤니케이션", re.I)
_CROSS_CUTTING_RE = re.compile(
    r"광고\s*콘텐츠|콘텐츠\s*운영|연출\s*가이드|브랜드\s*마케팅|"
    r"isp\s*연출|체크리스트|지점\s*체크",
    re.I,
)
_DAMDANG_HINT_RE = re.compile(
    r"(?:\[|\b|_)(대형가전1|대형가전2|생활리빙|생활주방|생활가전팀|스마트가전|스마트폰|모바일|"
    r"PC솔루션|IT|KBB|주방|Hobby|애플|케어서비스|지원)(?:\]|담당|_|\b)",
    re.I,
)
_PROMO_EXCEL_RE = re.compile(
    r"소진\s*리스트|추가행사가|기존소진가|출하가|클리어런스|행사가",
    re.I,
)
_MAX_CODES_PER_SLICE = 24
_MIN_BODY_FOR_VLM = 80
_MAX_KEYWORDS = 40
_TEAM_BRACKET_RE = re.compile(r"\[([^\]]{2,30})\]")


@dataclass
class PostMeta:
    post_id: str
    post_title: str
    posted_date: date
    filename: str
    record_kind: str = "excel"


def damdang_hints_from_filename(filename: str) -> set[str]:
    hints = {m.group(1) for m in _DAMDANG_HINT_RE.finditer(filename)}
    if re.search(r"생활가전팀", filename, re.I):
        hints.add("생활리빙")
        hints.add("생활주방")
    return hints


def _filter_damdangs(
    damdangs: list[str],
    *,
    roster: set[str],
    filename_hints: set[str],
) -> list[str]:
    out: list[str] = []
    for d in damdangs:
        if d not in roster or d == MANAGER_KEY:
            continue
        if filename_hints and d not in filename_hints and d != FALLBACK_KEY:
            continue
        if d not in out:
            out.append(d)
    return out


def is_promo_excel_slice(kind: str, filename: str, text: str) -> bool:
    if kind != "excel":
        return False
    blob = f"{filename}\n{text}"
    if _PROMO_EXCEL_RE.search(blob):
        return len((text or "").strip()) >= 60
    if re.search(r"구강용품|오클린|소진현황", filename, re.I):
        return len((text or "").strip()) >= 60
    return False


def infer_damdang_from_record(
    rec: NormalizedRecord,
    *,
    lookup: dict[str, tuple[str, ...]],
    roster: set[str],
    post_title: str = "",
    filename: str = "",
) -> list[str]:
    """Route a single record to 분류담당 tags (soft targets, not hard filters)."""
    if rec.damdang and rec.damdang in roster:
        return [rec.damdang]
    if rec.damdangs:
        return [d for d in rec.damdangs if d in roster and d != MANAGER_KEY]

    if filename and "진열소진" in filename and "노트북" in filename.lower():
        if "PC솔루션" in roster:
            return ["PC솔루션"]

    cat = re.sub(r"\s+", "", (rec.category_value or ""))
    if cat == "공통" or _BRAND_MARKETING_RE.search(rec.body):
        if FALLBACK_KEY in roster:
            return [FALLBACK_KEY]

    blob = f"{post_title}\n{filename}\n{rec.body}"
    if _CROSS_CUTTING_RE.search(blob) and FALLBACK_KEY in roster:
        return [FALLBACK_KEY]
    codes = rec.product_codes or extract_prd_codes(rec.body)
    if not codes:
        codes = extract_model_skus(rec.body)

    if codes:
        damdangs = product_damdang_for_codes(codes, lookup)
        damdangs = [d for d in damdangs if d in roster]
        if damdangs:
            return damdangs

    inferred = infer_damdangs_from_text(blob, roster)
    return [d for d in inferred if d in roster and d != MANAGER_KEY]


def _infer_category_from_body(body: str) -> str | None:
    m = _TEAM_BRACKET_RE.search(body or "")
    if m:
        return m.group(1).strip()
    return None


def _extract_record_keywords(rec: NormalizedRecord, *, post_title: str) -> list[str]:
    parts = [post_title, rec.attachment_name or "", rec.title, rec.body or ""]
    found: set[str] = set()
    for text in parts:
        found |= keyword_set(text)
        for anchor in title_anchors(text):
            found.add(anchor)
    found -= {"", "sheet", "table", "슬라이드", "페이지"}
    ordered = sorted(found, key=lambda x: (-len(x), x))
    return ordered[:_MAX_KEYWORDS]


def _review_flags(
    rec: NormalizedRecord,
    *,
    damdangs: list[str],
    effective_text: str,
) -> str | None:
    if rec.review_flag:
        return rec.review_flag
    ext = rec.provenance.extraction
    if ext in ("fallback", "ocr"):
        return f"{ext}_content"
    if not damdangs:
        return "no_damdang"
    if len((effective_text or "").strip()) < 20:
        return "short_body"
    return None


def enrich_record(
    rec: NormalizedRecord,
    *,
    lookup: dict[str, tuple[str, ...]],
    roster: set[str],
    post_meta: PostMeta,
    vlm_text: str = "",
    tables: list | None = None,
) -> NormalizedRecord | None:
    """Fill product_codes, damdangs, keywords, temporal on one NormalizedRecord."""
    filename = post_meta.filename or rec.attachment_name
    effective_text = (rec.body or "").strip() or vlm_text
    kind = post_meta.record_kind

    codes = list(rec.product_codes)
    if not codes:
        codes = extract_prd_codes(effective_text, vlm_text)
    if not codes:
        codes = extract_model_skus(effective_text)

    category = rec.category_value
    if not category and kind in ("pptx_slide", "pdf_page", "pdf_section"):
        category = _infer_category_from_body(effective_text)

    blob = f"{post_meta.post_title}\n{filename}\n{effective_text}"
    file_hints = damdang_hints_from_filename(filename)
    is_promo = is_promo_excel_slice(kind, filename, effective_text)

    damdangs = infer_damdang_from_record(
        rec.model_copy(update={"product_codes": codes, "category_value": category}),
        lookup=lookup,
        roster=roster,
        post_title=post_meta.post_title,
        filename=filename,
    )

    if file_hints:
        hinted = _filter_damdangs(list(file_hints), roster=roster, filename_hints=file_hints)
        if hinted and not damdangs:
            damdangs = hinted
        elif hinted and damdangs and FALLBACK_KEY not in damdangs:
            for h in hinted:
                if h not in damdangs:
                    damdangs.append(h)

    if codes and len(codes) <= _MAX_CODES_PER_SLICE:
        routed = _filter_damdangs(
            product_damdang_for_codes(codes, lookup),
            roster=roster,
            filename_hints=file_hints,
        )
        if routed:
            damdangs = routed
        elif not damdangs:
            damdangs = infer_damdangs_from_text(blob, roster)
            damdangs = [d for d in damdangs if d in roster and d != MANAGER_KEY]
    elif is_promo and not damdangs:
        damdangs = infer_damdangs_from_text(blob, roster)
        for d in file_hints:
            if d in roster and d not in damdangs:
                damdangs.append(d)
        damdangs = [d for d in damdangs if d in roster and d != MANAGER_KEY]
    elif not damdangs and kind in ("pptx_slide", "pdf_page", "pdf_section"):
        damdangs = infer_damdangs_from_text(blob, roster)
        damdangs = [d for d in damdangs if d in roster and d != MANAGER_KEY]
        if not damdangs and _CROSS_CUTTING_RE.search(blob) and FALLBACK_KEY in roster:
            damdangs = [FALLBACK_KEY]
    elif not damdangs and len(effective_text.strip()) >= _MIN_BODY_FOR_VLM and vlm_text:
        damdangs = infer_damdangs_from_text(blob, roster)
        damdangs = [d for d in damdangs if d in roster and d != MANAGER_KEY]

    if not damdangs:
        return None

    headline = rec.title or post_meta.post_title
    primary_damdang = damdangs[0]
    temporal = extract_temporal_meta(
        text=effective_text,
        posted_date=post_meta.posted_date,
        title=headline,
        filename=filename,
        damdang=primary_damdang,
        tables=tables,
    ).to_dict()

    keywords = rec.keywords or _extract_record_keywords(rec, post_title=post_meta.post_title)
    review_flag = _review_flags(rec, damdangs=damdangs, effective_text=effective_text)

    return rec.model_copy(update={
        "product_codes": codes,
        "category_value": category,
        "damdang": primary_damdang,
        "damdangs": damdangs,
        "keywords": keywords,
        "temporal": temporal,
        "review_flag": review_flag,
        "attachment_name": filename or rec.attachment_name,
    })


def enrich_records(
    records: list[NormalizedRecord],
    *,
    lookup: dict[str, tuple[str, ...]],
    roster: set[str],
    post_meta: PostMeta,
    vlm_index: dict | None = None,
    tables_for_ref: Callable | None = None,
    record=None,
) -> list[NormalizedRecord]:
    """Enrich a batch of parsed NormalizedRecords."""
    vlm_index = vlm_index or {}
    out: list[NormalizedRecord] = []
    for rec in records:
        source_ref = rec.provenance.source_ref
        vlm = vlm_index.get(source_ref)
        vlm_text = vlm.description if vlm else ""
        tables = tables_for_ref(record, source_ref) if tables_for_ref and record else None
        enriched = enrich_record(
            rec,
            lookup=lookup,
            roster=roster,
            post_meta=post_meta,
            vlm_text=vlm_text,
            tables=tables,
        )
        if enriched is not None:
            out.append(enriched)
    return out
