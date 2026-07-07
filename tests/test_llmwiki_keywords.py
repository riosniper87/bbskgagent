"""Tests for card keyword extraction."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.llmwiki.card import WikiCard
from store_brief.llmwiki.keywords import extract_card_keywords
from store_brief.qa.tools.retrieve import keyword_overlap_count


def _ad_card() -> WikiCard:
    body = (
        "[브랜드마케팅팀] 광고 콘텐츠 운영 개선 기준 및 가이드\n"
        "1. 점별 공용 계정(단체/비즈니스) 신규 생성 운영"
    )
    return WikiCard(
        damdang="생활리빙",
        post_id="bbea9fa24f9f",
        post_title="26년 6월 2주차 분류담당자 업무 가이드",
        posted_date=date(2026, 6, 11),
        source_ref="bbea9fa24f9f_checklist.xlsx#table0",
        attachment_name="2. SV팀_260611_26년 6월 2주차 지점 체크리스트.xlsx",
        headline="체크리스트 (영역 2)",
        body=body,
    )


def test_extract_card_keywords_ad_content():
    kws = extract_card_keywords(_ad_card())
    assert "광고" in kws or "콘텐츠" in kws
    assert "계정" in kws or "공용" in kws


def test_keyword_overlap_count():
    card = _ad_card()
    card.keywords = extract_card_keywords(card)
    n = keyword_overlap_count(card, ["광고", "계정", "전환"])
    assert n >= 2
