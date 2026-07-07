"""Tests for retrieval guards: product-filter relax, temporal relax, weak signal."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.llmwiki.card import WikiCard
from store_brief.qa.corpus import QACorpus
from store_brief.qa.schemas import RetrievalHit, TemporalScope, TimeMode
from store_brief.qa.tools.retrieve import is_weak_retrieval, retrieve_wiki_cards
from store_brief.temporal.meta import NoticeKind, TemporalMeta


def _card(post_id, damdang, body, posted, *, products=None, valid=None, headline="냉장고 판촉"):
    tm = TemporalMeta()
    tm.posted_date = posted
    if valid:
        tm.valid_from, tm.valid_to = valid
        tm.notice_kind = NoticeKind.promotion
    return WikiCard(
        damdang=damdang,
        post_id=post_id,
        post_title=f"공지 {post_id}",
        posted_date=posted,
        source_ref=f"{post_id}#s1",
        attachment_name="promo.xlsx",
        product_codes=products or [],
        headline=headline,
        body=body,
        temporal=tm,
    )


@pytest.fixture
def corpus():
    cards = [
        _card(
            "a", "대형가전1", "LG 냉장고 판촉 행사", date(2026, 6, 5),
            products=["X324GB5.AKOR"],
            valid=(date(2026, 6, 5), date(2026, 6, 8)),
        ),
        _card(
            "b", "IT", "노트북 거치대 안내", date(2026, 6, 10),
            headline="노트북 안내",
            valid=(date(2026, 6, 10), date(2026, 6, 12)),
        ),
    ]
    return QACorpus(as_of="2026-06-17", cards=cards, provenance_by_card={})


def test_wrong_product_code_does_not_zero_retrieval(corpus):
    diag: dict = {}
    hits = retrieve_wiki_cards(
        corpus,
        keywords=["냉장고", "판촉"],
        damdangs=["대형가전1"],
        product_codes=["ZZZZ9.AKOR"],  # hallucinated code — matches nothing
        diagnostics_out=diag,
    )
    assert hits, "product filter must relax instead of returning zero hits"
    assert hits[0].post_id == "a"
    assert diag.get("product_filter_relaxed") is True


def test_valid_product_code_still_filters(corpus):
    diag: dict = {}
    hits = retrieve_wiki_cards(
        corpus,
        keywords=["냉장고"],
        damdangs=["대형가전1"],
        product_codes=["X324GB5.AKOR"],
        diagnostics_out=diag,
    )
    assert hits
    assert all(h.post_id == "a" for h in hits)
    assert "product_filter_relaxed" not in diag


def test_temporal_active_on_relaxes_when_pool_empties(corpus):
    diag: dict = {}
    scope = TemporalScope(
        time_mode=TimeMode.active_on,
        query_date=date(2026, 7, 15),  # after every validity window
    )
    hits = retrieve_wiki_cards(
        corpus,
        keywords=["냉장고", "판촉"],
        damdangs=["대형가전1"],
        temporal_scope=scope,
        diagnostics_out=diag,
    )
    assert hits, "temporal filter must relax instead of emptying the pool"
    assert str(diag.get("temporal_relaxed", "")).startswith("active_on->")
    assert diag["pool_after_temporal"] == 2


def test_temporal_filter_kept_when_pool_survives(corpus):
    diag: dict = {}
    scope = TemporalScope(
        time_mode=TimeMode.active_on,
        query_date=date(2026, 6, 6),  # inside card a's window
    )
    hits = retrieve_wiki_cards(
        corpus,
        keywords=["냉장고", "판촉"],
        damdangs=["대형가전1"],
        temporal_scope=scope,
        diagnostics_out=diag,
    )
    assert hits and hits[0].post_id == "a"
    assert "temporal_relaxed" not in diag


def test_no_anchor_zero_score_cards_skipped(corpus):
    # No damdang boost applies ("생활리빙" not in corpus) and keywords match
    # nothing → all scores <= 0 → no junk hits.
    hits = retrieve_wiki_cards(
        corpus,
        keywords=["존재하지않는키워드"],
        damdangs=["생활리빙"],
    )
    assert hits == []


def test_diagnostics_pool_sizes(corpus):
    diag: dict = {}
    retrieve_wiki_cards(
        corpus,
        keywords=["냉장고"],
        damdangs=["대형가전1"],
        diagnostics_out=diag,
    )
    assert diag["pool_total"] == 2
    assert diag["hit_count"] >= 1
    assert diag["top_score"] > 0


def _hit(text: str, score: float) -> RetrievalHit:
    return RetrievalHit(
        card_id="c1",
        damdang="IT",
        headline=text,
        post_id="p1",
        post_title="",
        posted_date="2026-06-10",
        attachment_name="a.xlsx",
        source_ref="p1#s1",
        score=score,
        body_excerpt="",
    )


def test_weak_retrieval_zero_keyword_coverage():
    hits = [_hit("완전히 다른 주제의 카드", 50.0), _hit("또다른 카드", 30.0)]
    assert is_weak_retrieval(hits, ["냉장고", "판촉"]) is True
    # Without keywords, high score is trusted (backwards compatible).
    assert is_weak_retrieval(hits) is False


def test_weak_retrieval_variant_coverage_counts():
    hits = [_hit("냉장고 판촉 안내", 12.0), _hit("세탁기", 5.0)]
    # "냉장고는" matches via josa-stripped variant → not weak.
    assert is_weak_retrieval(hits, ["냉장고는"]) is False


def test_weak_retrieval_empty_hits():
    assert is_weak_retrieval([], ["냉장고"]) is True
    assert is_weak_retrieval([]) is True
