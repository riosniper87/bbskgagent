"""Tests for greenfield llmwiki from parsed slices."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.llmwiki.card import WikiCard
from store_brief.llmwiki.from_parsed import (
    _filter_damdangs,
    _headline,
    _is_promo_excel_slice,
    _skip_noisy_slice,
    group_cards,
)
from store_brief.llmwiki.grouping import product_codes_for_damdang, product_damdang_for_codes


def test_product_damdang_keeps_large_appliance_teams_separate():
    lookup = {
        "PLX-TV75MLBK": ("대형가전2", "스마트가전"),
        "PLX-WM03STBG": ("대형가전1",),
    }
    tags = product_damdang_for_codes(["PLX-TV75MLBK", "PLX-WM03STBG"], lookup)
    assert tags == ["대형가전2", "스마트가전", "대형가전1"]


def test_product_codes_for_damdang_filters_union():
    lookup = {
        "CBT-LFF32W": ("KBB", "주방"),
        "PLX-KB108MCWH": ("IT", "PC솔루션"),
    }
    assert product_codes_for_damdang(["CBT-LFF32W", "PLX-KB108MCWH"], "KBB", lookup) == [
        "CBT-LFF32W",
    ]
    assert product_codes_for_damdang(["CBT-LFF32W", "PLX-KB108MCWH"], "IT", lookup) == [
        "PLX-KB108MCWH",
    ]


def test_filter_damdangs_uses_filename_hints():
    roster = {"생활주방", "주방", "KBB"}
    assert _filter_damdangs(
        ["생활주방", "주방"],
        roster=roster,
        filename_hints={"생활주방"},
    ) == ["생활주방"]


def test_skip_inventory_excel_slice():
    text = "### 시트: 지사지점재고확인\n| col_0 | col_1 |"
    assert _skip_noisy_slice(text, "att#sheet:지사지점재고확인", "재고.xlsx")


def test_promo_excel_with_sojinyul_not_skipped():
    filename = "15. [생활가전팀]_오클린구강용품_6월_소진현황_260608_송부용.xlsx"
    text = (
        "시트: 소진 리스트\n"
        "NO | 품목 | 메이커 | 추가행사가 | 소진율\n"
        "1 | 전동칫솔 | 오클린 | 69900 | 0.58\n"
        "V8100_BK | 168000 | 99900"
    )
    assert _is_promo_excel_slice("excel", filename, text)
    assert _skip_noisy_slice(text, "att#sheet:소진 리스트", filename)
    assert not (
        _skip_noisy_slice(text, "att#sheet:소진 리스트", filename)
        and not _is_promo_excel_slice("excel", filename, text)
    )


def test_headline_prefers_bullet_over_col_header():
    text = "### 시트: 6월1주차\n● 생활주방 6월 할인모델\n| col_0 | col_1 |"
    assert _headline(text, "fallback") == "생활주방 6월 할인모델"


def test_group_cards_by_damdang():
    cards = [
        WikiCard(
            damdang="주방",
            post_id="p1",
            post_title="테스트",
            posted_date=date(2026, 6, 1),
            source_ref="p1_a#s1",
            attachment_name="a.pptx",
            product_codes=["PLX-MCK02PDB"],
        ),
        WikiCard(
            damdang="생활주방",
            post_id="p1",
            post_title="테스트",
            posted_date=date(2026, 6, 1),
            source_ref="p1_a#s1",
            attachment_name="a.pptx",
            product_codes=["PLX-MCK02PDB"],
        ),
    ]
    grouped = group_cards(cards, rnr_path="data/rnr.txt")
    assert len(grouped["주방"]) == 1
    assert len(grouped["생활주방"]) == 1
    assert len(grouped["점장"]) == 2
