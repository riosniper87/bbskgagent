"""Tests for llmwiki/enrichment.py (Phase 2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.ingestion.parse_xlsx import parse_xlsx_from_record
from store_brief.llmwiki.enrichment import (
    PostMeta,
    enrich_records,
    infer_damdang_from_record,
)
from store_brief.ingestion.schema import NormalizedRecord, Provenance
from store_brief.parse.store import ParsedAttachmentStore

DATA = Path(__file__).resolve().parents[1] / "data"
STORE = ParsedAttachmentStore(DATA / "parsed")


def test_infer_damdang_gongtong_from_category():
    rec = NormalizedRecord(
        post_id="x",
        source_type="excel_row",
        body="[브랜드마케팅팀] 광고 콘텐츠",
        category_value="공통",
        provenance=Provenance(source_ref="x#row:체크리스트:3"),
    )
    roster = {"공통", "생활리빙", "PC솔루션"}
    assert infer_damdang_from_record(rec, lookup={}, roster=roster) == ["공통"]


def test_enrich_checklist_row3():
    record = STORE.load_record("bbea9fa24f9f", "495f70425fe1")
    if record is None:
        pytest.skip("parsed checklist not available")
    raw = parse_xlsx_from_record(record, "bbea9fa24f9f", data_dir=DATA)
    row3 = next((r for r in raw if r.provenance.source_ref.endswith(":3")), None)
    assert row3 is not None
    roster = {"공통", "생활리빙", "PC솔루션", "점장"}
    enriched = enrich_records(
        [row3],
        lookup={},
        roster=roster,
        post_meta=PostMeta(
            post_id="bbea9fa24f9f",
            post_title="체크리스트",
            posted_date=__import__("datetime").date(2026, 6, 11),
            filename=record.filename,
            record_kind="excel",
        ),
    )
    assert enriched
    assert enriched[0].damdangs == ["공통"]
    assert enriched[0].temporal.get("notice_kind")

def test_enrich_pptx_cross_cutting():
    from store_brief.ingestion.schema import NormalizedRecord, Provenance

    rec = NormalizedRecord(
        post_id="6148b200b185",
        source_type="pptx_slide",
        title="슬라이드 1",
        body="2026. 6. 1.\n광고 콘텐츠 운영 개선 설명회",
        provenance=Provenance(source_ref="x#s1", extraction="deterministic"),
    )
    roster = {"공통", "생활리빙", "점장"}
    enriched = enrich_records(
        [rec],
        lookup={},
        roster=roster,
        post_meta=PostMeta(
            post_id="6148b200b185",
            post_title="6월 광고 연출 가이드",
            posted_date=__import__("datetime").date(2026, 6, 5),
            filename="260529_광고 콘텐츠 운영 개선_기준 및 가이드_vf.pptx",
            record_kind="pptx",
        ),
    )
    assert enriched
    assert enriched[0].damdangs == ["공통"]


def test_enrich_jindyeol_pc_solution():
    meta = json.loads((DATA / "parsed" / "126c62ac2108" / "meta.json").read_text(encoding="utf-8"))
    record = None
    for key in meta.get("records", []):
        rec = STORE.load_record("126c62ac2108", key)
        if rec and "진열소진" in rec.filename:
            record = rec
            break
    if record is None:
        pytest.skip("진열소진 parsed record not available")
    raw = parse_xlsx_from_record(record, "126c62ac2108", data_dir=DATA)
    assert raw
    roster = {"PC솔루션", "공통", "점장"}
    enriched = enrich_records(
        raw[:3],
        lookup={},
        roster=roster,
        post_meta=PostMeta(
            post_id="126c62ac2108",
            post_title="노트북 진열소진",
            posted_date=__import__("datetime").date(2026, 6, 15),
            filename=record.filename,
            record_kind="excel",
        ),
    )
    assert enriched
    assert all("PC솔루션" in r.damdangs for r in enriched)
