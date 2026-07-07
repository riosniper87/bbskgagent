"""Regression tests promoted from QA eval failures."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.qa.corpus import load_corpus
from store_brief.qa.eval.checks import (
    check_attachment,
    check_corpus_metadata,
    check_retrieval,
    corpus_has_source,
)
from store_brief.qa.eval.promote import load_regression_cases
from store_brief.qa.eval.schema import EvalCase
from store_brief.qa.tools.retrieve import keyword_overlap_count, retrieve_wiki_cards


DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def regression_cases() -> list[EvalCase]:
    cases = load_regression_cases(DATA)
    if not cases:
        fixture = DATA / "eval" / "regression_cases.json"
        if fixture.is_file():
            raw = json.loads(fixture.read_text(encoding="utf-8"))
            cases = [EvalCase.model_validate(c) for c in raw.get("cases", [])]
    return cases


@pytest.fixture
def corpus():
    path = DATA / "llmwiki" / "2026-06-17" / "llmwiki.json"
    if not path.is_file():
        pytest.skip("llmwiki corpus not built")
    return load_corpus(DATA, "2026-06-17")


def test_regression_cases_indexed(corpus, regression_cases):
    if not regression_cases:
        pytest.skip("no regression cases")
    for case in regression_cases:
        if not case.expect_corpus:
            continue
        assert corpus_has_source(corpus.cards, case), (
            f"corpus_gap: {case.post_id} / {case.source_label}"
        )
        _, meta_ok = check_corpus_metadata(corpus.cards, case)
        assert meta_ok, (
            f"corpus_metadata: {case.post_id} expect_damdang={case.expect_damdang}"
        )


def test_regression_cases_retrieval(corpus, regression_cases):
    if not regression_cases:
        pytest.skip("no regression cases")
    for case in regression_cases:
        if not case.expect_corpus:
            continue
        hits = retrieve_wiki_cards(
            corpus,
            keywords=case.question.split()[:6],
            damdangs=["생활리빙", "생활주방", "대형가전1", "대형가전2"],
            anchor_post_id=case.post_id,
            anchor_source_ref=case.source_ref,
        )
        hit1, hit3, _ = check_retrieval(hits, case)
        assert hit1 or hit3, (
            f"retrieval_miss: {case.question[:50]} top={hits[0].post_id if hits else None}"
        )
        assert check_attachment(hits, [], case), (
            f"attachment_mismatch: {case.source_label}"
        )


def test_ad_account_retrieval_keyword_overlap(corpus):
    """Marketing/account question should hit checklist post via keywords."""
    path = DATA / "llmwiki" / "2026-06-17" / "llmwiki.json"
    if not path.is_file():
        pytest.skip("llmwiki corpus not built")

    keywords = ["광고", "계정", "전환", "콘텐츠"]
    hits = retrieve_wiki_cards(
        corpus,
        keywords=keywords,
        damdangs=[
            "공통",
            "대형가전1", "대형가전2", "생활리빙", "생활주방", "IT",
            "케어서비스", "지원", "KBB", "주방", "스마트가전", "PC솔루션",
        ],
    )
    assert hits
    top_ids = {h.post_id for h in hits[:3]}
    assert "bbea9fa24f9f" in top_ids, f"top hits: {[(h.post_id, h.headline[:40]) for h in hits[:3]]}"
    top_card = next(c for c in corpus.cards if c.id == hits[0].card_id)
    assert keyword_overlap_count(top_card, keywords) >= 2
