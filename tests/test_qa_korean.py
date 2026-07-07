"""Tests for deterministic Korean query normalization (josa/stopwords)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.qa.korean import (
    expand_keywords,
    extract_question_keywords,
    is_question_stopword,
    keyword_variants,
    strip_josa,
)


def test_strip_josa_basic():
    assert strip_josa("냉장고는") == "냉장고"
    assert strip_josa("판촉을") == "판촉"
    assert strip_josa("세탁기에서는") == "세탁기"
    assert strip_josa("행사부터") == "행사"


def test_strip_josa_keeps_short_stems():
    # Stripping would leave <2 chars → unchanged.
    assert strip_josa("이") == "이"
    assert strip_josa("가는") == "가는"


def test_strip_josa_non_hangul_unchanged():
    assert strip_josa("V8100") == "V8100"
    assert strip_josa("INS-FAN") == "INS-FAN"
    assert strip_josa("") == ""


def test_keyword_variants_dual_emit():
    assert keyword_variants("냉장고는") == ["냉장고는", "냉장고"]
    assert keyword_variants("냉장고") == ["냉장고"]
    assert keyword_variants("  ") == []


def test_expand_keywords_order_and_dedup():
    out = expand_keywords(["냉장고는", "냉장고", "판촉을"])
    assert out == ["냉장고는", "냉장고", "판촉을", "판촉"]


def test_question_stopwords():
    assert is_question_stopword("알려줘")
    assert is_question_stopword("언제까지")
    assert not is_question_stopword("냉장고")


def test_extract_question_keywords():
    kws = extract_question_keywords("오클린 전동칫솔 V8100 행사가 언제까지인지 알려줘")
    assert "오클린" in kws
    assert "전동칫솔" in kws
    assert "V8100" in kws
    assert "알려줘" not in kws
    # 행사가 → josa stripped
    assert "행사" in kws


def test_extract_question_keywords_limit_and_empty():
    assert extract_question_keywords("") == []
    kws = extract_question_keywords("a1 b2 c3 d4 e5 f6 g7 h8 i9 j10", limit=3)
    assert len(kws) == 3
