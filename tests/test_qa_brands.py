"""Tests for Q&A brand hint helpers."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.qa.schemas import RetrievalHit
from store_brief.qa.tools.brands import (
    build_brand_context,
    detect_requested_brands,
    display_title,
    infer_card_brands,
)


def _hit(**kwargs) -> RetrievalHit:
    defaults = dict(
        card_id="x",
        damdang="대형가전1",
        headline="일반",
        post_id="p1",
        post_title="06/04 주요공지사항 종합",
        posted_date="2026-06-04",
        attachment_name="PLUX.pptx",
        source_ref="p1#s1",
        product_codes=["PLX-SBS604BK"],
        body_excerpt="롯데하이마트 PLUX 냉장고 PLX-SBS604BK",
    )
    defaults.update(kwargs)
    return RetrievalHit(**defaults)


def test_detect_samsung_and_plux():
    assert "삼성" in detect_requested_brands("삼성 대형가전1 6월 판촉")
    assert "PLUX" in detect_requested_brands("플럭스 냉장고 행사")
    assert detect_requested_brands("6월 냉장고 판촉") == []


def test_infer_plux_card():
    assert "PLUX" in infer_card_brands(_hit())


def test_infer_samsung_card():
    h = _hit(
        headline="LG/삼성 세트 및 단품 추천 모델",
        post_title="6월 1주차 분류담당자 가이드",
        attachment_name="guide.pptx",
        product_codes=["RM70F63.AKOR"],
        body_excerpt="삼성 키친핏 냉장고 행사 RM70F63",
    )
    tags = infer_card_brands(h)
    assert "삼성" in tags
    assert "PLUX" not in tags


def test_brand_guidance_excludes_plux_for_samsung_question():
    ctx = build_brand_context(
        "삼성 판촉 알려줘",
        [
            _hit(),
            _hit(
                headline="LG/삼성 세트",
                post_title="6월 가이드",
                attachment_name="g.pptx",
                product_codes=[],
                body_excerpt="삼성 감사페스티벌 20%",
            ),
        ],
    )
    assert "삼성" in ctx.requested
    assert "불일치" in ctx.guidance
    assert "사용 가능" in ctx.guidance


def test_display_title_prefers_post_title():
    h = _hit(headline="벽걸이", post_title="06/04 주요공지사항 종합")
    assert h.post_title in display_title(h)
    assert display_title(h) != "벽걸이"
