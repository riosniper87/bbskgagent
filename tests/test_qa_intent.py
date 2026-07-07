"""Tests for intent parsing and damdang hint heuristics."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.qa.tools.intent import _SYSTEM, normalize_intent_dict
from store_brief.qa.tools.routing import infer_damdang_confidence, resolve_damdang_scope

_ROSTER = [
    "대형가전1", "대형가전2", "생활주방", "생활리빙", "IT", "케어서비스", "지원",
]


def test_system_prompt_no_default_damdang_example():
    assert '"damdang_hints": []' in _SYSTEM
    assert '"damdang_hints": ["대형가전1"]' not in _SYSTEM


def test_marketing_question_strips_product_damdang_hints():
    q = "6월 1일부터 광고 컨텐츠 개인 계정을 회사 계정으로 전환하는 건가요?"
    raw = {"keywords": ["광고", "계정", "전환"], "damdang_hints": ["대형가전1"]}
    intent = normalize_intent_dict(raw, question=q)
    assert "대형가전1" not in intent["damdang_hints"]


def test_marketing_low_confidence_uses_full_roster():
    q = "6월 1일부터 광고 컨텐츠 개인 계정을 회사 계정으로 전환하는 건가요?"
    conf = infer_damdang_confidence(
        question=q,
        damdang_hints=["대형가전1"],
        product_codes=[],
        roster=_ROSTER,
    )
    assert conf == "low"
    scope = resolve_damdang_scope(
        damdang_hints=["대형가전1"],
        roster=_ROSTER,
        confidence=conf,
        question=q,
    )
    assert scope == _ROSTER


def test_explicit_damdang_in_question_high_confidence():
    q = "대형가전1 냉장고 6월 판촉 알려줘"
    conf = infer_damdang_confidence(
        question=q,
        damdang_hints=["대형가전1"],
        product_codes=[],
        roster=_ROSTER,
    )
    assert conf == "high"
    scope = resolve_damdang_scope(
        damdang_hints=["대형가전1"],
        roster=_ROSTER,
        confidence=conf,
        question=q,
    )
    assert scope == ["대형가전1"]


def test_notebook_inventory_question_routes_pc_and_skips_notice_filter():
    q = "지사지점재고확인 시트에 있는 노트북 진열소진현황은 어떻게 확인하나요?"
    intent = normalize_intent_dict(
        {"keywords": ["노트북", "진열소진현황", "재고확인"], "notice_kinds": ["공지"]},
        question=q,
    )
    assert "PC솔루션" in intent["damdang_hints"]
    assert intent["notice_kinds"] == []


def test_notebook_question_high_confidence_for_pc_scope():
    q = "지사지점재고확인 시트에 있는 노트북 진열소진현황은 어떻게 확인하나요?"
    hints = normalize_intent_dict({}, question=q)["damdang_hints"]
    conf = infer_damdang_confidence(
        question=q,
        damdang_hints=hints,
        product_codes=[],
        roster=_ROSTER + ["PC솔루션"],
    )
    assert conf == "high"
