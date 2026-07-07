"""Tests for retrieval v2: soft damdang boost, recency, topic_key dedup."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.index.search import CardSearchIndex
from store_brief.llmwiki.card import WikiCard
from store_brief.qa.corpus import QACorpus
from store_brief.qa.schemas import TemporalScope, TimeMode
from store_brief.qa.tools.retrieve import (
    _dedup_by_topic_key,
    retrieve_wiki_cards,
)
from store_brief.temporal.meta import NoticeKind, TemporalMeta


def _card(
    post_id: str,
    damdang: str,
    body: str,
    posted: date,
    *,
    topic_key: str | None = None,
    source_suffix: str = "s1",
) -> WikiCard:
    tm = TemporalMeta(notice_kind=NoticeKind.promotion, topic_key=topic_key)
    return WikiCard(
        damdang=damdang,
        post_id=post_id,
        post_title=f"공지 {post_id}",
        posted_date=posted,
        source_ref=f"{post_id}#{source_suffix}",
        attachment_name="promo.xlsx",
        headline=body[:30],
        body=body,
        temporal=tm,
        keywords=body.split()[:3],
    )


def test_soft_boost_finds_other_damdang():
    cards = [
        _card("a", "대형가전1", "냉장고 판촉", date(2026, 6, 5)),
        _card("b", "IT", "냉장고 특가 노트북", date(2026, 6, 8)),
    ]
    corpus = QACorpus(as_of="2026-06-17", cards=cards)
    hits = retrieve_wiki_cards(
        corpus,
        keywords=["냉장고", "판촉"],
        damdangs=["대형가전1"],
        query_date=date(2026, 6, 17),
    )
    assert hits
    assert hits[0].card_id == cards[0].id


def test_recency_boost_prefers_newer_same_topic():
    tk = "topic-promo-1"
    older = _card("old", "대형가전1", "냉장고 판촉 5월", date(2026, 5, 1), topic_key=tk)
    newer = _card("new", "대형가전1", "냉장고 판촉 6월", date(2026, 6, 10), topic_key=tk)
    corpus = QACorpus(as_of="2026-06-17", cards=[older, newer])
    hits = retrieve_wiki_cards(
        corpus,
        keywords=["냉장고", "판촉"],
        damdangs=["대형가전1"],
        query_date=date(2026, 6, 17),
    )
    topic_hits = [h for h in hits if h.card_id in {older.id, newer.id}]
    assert len(topic_hits) == 1
    assert topic_hits[0].card_id == newer.id


def test_dedup_by_topic_key_keeps_newest():
    tk = "dup-topic"
    c1 = _card("p1", "대형가전1", "행사 A", date(2026, 5, 1), topic_key=tk)
    c2 = _card("p2", "대형가전1", "행사 B", date(2026, 6, 15), topic_key=tk)
    cards_by_id = {c1.id: c1, c2.id: c2}
    from store_brief.qa.schemas import RetrievalHit

    hits = [
        RetrievalHit(
            card_id=c1.id,
            damdang=c1.damdang,
            headline=c1.headline,
            post_id=c1.post_id,
            post_title=c1.post_title,
            posted_date=c1.posted_date.isoformat(),
            attachment_name=c1.attachment_name,
            source_ref=c1.source_ref,
            score=10.0,
        ),
        RetrievalHit(
            card_id=c2.id,
            damdang=c2.damdang,
            headline=c2.headline,
            post_id=c2.post_id,
            post_title=c2.post_title,
            posted_date=c2.posted_date.isoformat(),
            attachment_name=c2.attachment_name,
            source_ref=c2.source_ref,
            score=8.0,
        ),
    ]
    deduped = _dedup_by_topic_key(hits, cards_by_id)
    assert len(deduped) == 1
    assert deduped[0].card_id == c2.id


def test_persistent_index_used_when_present():
    cards = [
        _card("a", "대형가전1", "오클린 V8100 추가 행사", date(2026, 6, 5)),
        _card("b", "IT", "노트북 재고", date(2026, 6, 5)),
    ]
    docs = [f"{c.post_title} {c.body}" for c in cards]
    index = CardSearchIndex.from_documents([c.id for c in cards], docs, as_of="2026-06-17")
    corpus = QACorpus(as_of="2026-06-17", cards=cards, search_index=index)
    hits = retrieve_wiki_cards(
        corpus,
        keywords=["오클린", "V8100"],
        damdangs=["대형가전1"],
    )
    assert hits[0].card_id == cards[0].id


def test_version_diff_skips_dedup():
    tk = "ver-topic"
    c1 = _card("p1", "대형가전1", "v1", date(2026, 5, 1), topic_key=tk)
    c2 = _card("p2", "대형가전1", "v2", date(2026, 6, 1), topic_key=tk, source_suffix="s2")
    corpus = QACorpus(as_of="2026-06-17", cards=[c1, c2])
    scope = TemporalScope(time_mode=TimeMode.version_diff, query_date=date(2026, 6, 17))
    hits = retrieve_wiki_cards(
        corpus,
        keywords=["v1", "v2"],
        damdangs=["대형가전1"],
        temporal_scope=scope,
    )
    ids = {h.card_id for h in hits}
    assert c1.id in ids or c2.id in ids
