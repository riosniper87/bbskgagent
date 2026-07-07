"""Tests for BM25 helper."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.qa.bm25 import BM25Index


def test_bm25_ranks_relevant_higher():
    docs = [
        "선풍기 조립 서비스 INS-FAN 코드 안내",
        "조립PC 오피스 패키지 판매",
        "냉장고 판촉 행사",
    ]
    idx = BM25Index(docs)
    scores = idx.score_all("선풍기 조립 서비스")
    assert scores[0] > scores[1]
