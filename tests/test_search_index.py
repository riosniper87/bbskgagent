"""Tests for persistent search index build/load/score."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.index.build import build_search_index, card_search_text
from store_brief.index.search import CardSearchIndex
from store_brief.llmwiki.card import WikiCard
from store_brief.temporal.meta import TemporalMeta


def _card(card_id_suffix: str, body: str) -> WikiCard:
    c = WikiCard(
        damdang="대형가전1",
        post_id=f"p{card_id_suffix}",
        post_title="테스트 공지",
        posted_date=date(2026, 6, 10),
        source_ref=f"p{card_id_suffix}#s1",
        attachment_name="test.xlsx",
        headline="냉장고 판촉",
        body=body,
        temporal=TemporalMeta(),
        keywords=["냉장고", "판촉"],
    )
    return c


def test_card_search_text_includes_keywords():
    card = _card("1", "본문")
    text = card_search_text(card)
    assert "냉장고" in text
    assert "test.xlsx" in text


def test_build_load_score_roundtrip(tmp_path):
    cards = [
        _card("a", "LG 냉장고 판촉 행사"),
        _card("b", "세탁기 할인 안내"),
    ]
    meta = build_search_index(cards, tmp_path, as_of="2026-06-17")
    assert meta.card_count == 2
    pkl = tmp_path / "search_index.pkl"
    assert pkl.is_file()

    loaded = CardSearchIndex.load(pkl)
    assert loaded.card_count == 2
    assert loaded.card_ids == [c.id for c in cards]

    scores = loaded.score_all("냉장고 판촉")
    assert scores[cards[0].id] > scores[cards[1].id]


def test_score_all_card_id_keys(tmp_path):
    cards = [_card("x", "오클린 V8100 추가 행사")]
    build_search_index(cards, tmp_path, as_of="2026-06-17")
    loaded = CardSearchIndex.load(tmp_path / "search_index.pkl")
    by_id = loaded.score_all("오클린 V8100")
    assert set(by_id.keys()) == {cards[0].id}
    assert by_id[cards[0].id] > 0


def test_load_rejects_old_index_version(tmp_path):
    import pickle

    cards = [_card("v", "냉장고 판촉")]
    build_search_index(cards, tmp_path, as_of="2026-06-17")
    pkl = tmp_path / "search_index.pkl"
    payload = pickle.loads(pkl.read_bytes())
    payload["version"] = 1  # pre-josa-variant tokenization
    pkl.write_bytes(pickle.dumps(payload))

    with pytest.raises(ValueError, match="search index version"):
        CardSearchIndex.load(pkl)


def test_index_query_matches_josa_form(tmp_path):
    # Query "냉장고는" must match a doc containing "냉장고" via dual-emit.
    cards = [_card("j", "LG 냉장고 판촉 행사"), _card("k", "세탁기 할인")]
    build_search_index(cards, tmp_path, as_of="2026-06-17")
    loaded = CardSearchIndex.load(tmp_path / "search_index.pkl")
    scores = loaded.score_all("냉장고는 판촉")
    assert scores[cards[0].id] > scores[cards[1].id]
