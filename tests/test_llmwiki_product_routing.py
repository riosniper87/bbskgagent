"""Tests for PRD code extraction and product-based wiki routing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.extract.schema import Event, EventType
from store_brief.hisis.prd_codes import extract_prd_codes
from store_brief.llmwiki.grouping import damdang_for_event
from store_brief.llmwiki.product_routing import (
    damdang_tags_from_codes,
    enrich_events_with_product_damdang,
    extract_routing_product_codes,
)


def test_extract_prd_codes_from_text():
    text = "신규 PLX-MCK02PDB 및 CBT-LFF32W, 대체 BD-N310P"
    assert extract_prd_codes(text) == ["PLX-MCK02PDB", "CBT-LFF32W", "BD-N310P"]


def test_ignore_file_extension_false_positive():
    assert extract_prd_codes("image AC-12R20FNW.PNG attached") == ["AC-12R20FNW"]


def test_routing_prefers_title_over_summary():
    event = Event(
        id="e1",
        type=EventType.notice,
        title="PLX-KB108MCWH 출시",
        summary="함께 안내 EP-0820 커피머신",
        source_post_id="p1",
        tables=[],
    )
    assert extract_routing_product_codes(event) == ["PLX-KB108MCWH"]


def test_routing_ignores_attachment_tables():
    from store_brief.extract.schema import ExtractedTable

    event = Event(
        id="e2",
        type=EventType.notice,
        title="일반 공지",
        summary="주간 가이드",
        source_post_id="p2",
        tables=[
            ExtractedTable(
                source_ref="t1",
                columns=["모델"],
                rows=[["CBT-LFF32W"], ["PLX-MCK02PDB"]],
            ),
        ],
        attachment_refs=["weekly_CBT-LFF32W.xlsx"],
    )
    assert extract_routing_product_codes(event) == []


def test_damdang_tags_merge_large_appliance():
    lookup = {
        "PLX-TV75MLBK": ("대형가전2",),
        "PLX-WM03STBG": ("대형가전1",),
    }
    tags = damdang_tags_from_codes(["PLX-TV75MLBK", "PLX-WM03STBG"], lookup)
    assert tags == ["대형가전"]


def test_too_many_damdangs_falls_back_to_category():
    lookup = {f"C{i:03d}-AAA": (f"담당{i}",) for i in range(6)}
    assert damdang_tags_from_codes(list(lookup), lookup) is None


def test_enrich_sets_damdang_tags():
    event = Event(
        id="e3",
        type=EventType.notice,
        title="멀티쿠커 PLX-MCK02PDB",
        summary="",
        categories=["모바일·IT"],
        source_post_id="p3",
    )
    lookup = {"PLX-MCK02PDB": ("생활주방", "주방")}
    stats = enrich_events_with_product_damdang([event], lookup)
    assert stats.events_product_routed == 1
    assert event.damdang_tags == ["생활주방", "주방"]
    assert event.routing_basis == "product"
    dm = {"점장": [], "IT": ["모바일·IT"], "생활주방": [], "주방": ["주방"]}
    assert damdang_for_event(event, dm) == ["생활주방", "주방"]


def test_fallback_when_no_product_match():
    event = Event(
        id="e4",
        type=EventType.notice,
        title="ZZZ-XYZ123 안내",
        summary="",
        categories=["주방"],
        source_post_id="p4",
    )
    enrich_events_with_product_damdang([event], {"ZZZ-XYZ123": ()})
    assert event.routing_basis == "category"
    dm = {"점장": [], "주방": ["주방"]}
    assert damdang_for_event(event, dm) == ["주방"]
