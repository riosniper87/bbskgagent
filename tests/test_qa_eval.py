"""Unit tests for QA eval checks (no OpenAI)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.qa.eval.checks import (
    check_attachment,
    check_corpus_metadata,
    check_retrieval,
    compute_pass,
    corpus_has_source,
)
from store_brief.qa.eval.schema import EvalCase, LayerScores
from store_brief.llmwiki.card import WikiCard
from store_brief.qa.schemas import Citation, RetrievalHit
from datetime import date


def _case(**kw) -> EvalCase:
    defaults = dict(
        question="오클린 전동칫솔 추가 행사가?",
        post_id="9c9f6727c664",
        post_title="6월 9일 주요공지사항(종합)",
        posted_date="2026-06-09",
        source_type="sheet",
        source_label="15. [생활가전팀]_오클린구강용품_6월_소진현황_260608_송부용.xlsx · 시트 소진 리스트",
        source_ref="9c9f6727c664_15. [생활가전팀]_오클린구강용품_6월_소진현황_260608_송부용.xlsx#table0",
        excerpt_full="V8100_BK 추가행사가 69900",
    )
    defaults.update(kw)
    return EvalCase(**defaults)


def _hit(post_id, attachment, source_ref, score=10.0):
    return RetrievalHit(
        card_id="c1",
        damdang="생활리빙",
        headline="소진 리스트",
        post_id=post_id,
        post_title="공지",
        posted_date="2026-06-09",
        attachment_name=attachment,
        source_ref=source_ref,
        score=score,
    )


def test_check_retrieval_hit_at_1():
    case = _case()
    hits = [_hit("9c9f6727c664", "오클린.xlsx", "ref1")]
    hit1, hit3, weak = check_retrieval(hits, case)
    assert hit1
    assert hit3
    assert not weak


def test_check_attachment_by_filename():
    case = _case()
    hits = [_hit("9c9f6727c664", "15. [생활가전팀]_오클린구강용품_6월_소진현황_260608_송부용.xlsx", "other#ref")]
    assert check_attachment(hits, [], case)


def test_corpus_has_source():
    case = _case()
    card = WikiCard(
        damdang="생활리빙",
        post_id=case.post_id,
        post_title=case.post_title,
        posted_date=date(2026, 6, 9),
        source_ref=case.source_ref,
        attachment_name="15. [생활가전팀]_오클린구강용품_6월_소진현황_260608_송부용.xlsx",
        product_codes=["V8100_BK"],
    )
    assert corpus_has_source([card], case)


def test_compute_pass_requires_all_layers():
    layers = LayerScores(
        retrieval_hit_at_1=True,
        attachment_match=True,
        judge_verdict="pass",
        judge_inferred_ratio=1.0,
    )
    assert compute_pass(layers)

    layers.judge_verdict = "partial"
    layers.judge_inferred_ratio = 0.5
    assert not compute_pass(layers, min_judge_ratio=0.7)


def test_compute_pass_skips_judge_when_skipped():
    layers = LayerScores(
        retrieval_hit_at_1=True,
        attachment_match=True,
        judge_verdict="skipped",
    )
    assert compute_pass(layers)


def test_check_corpus_metadata_damdang():
    case = _case(
        expect_damdang="공통",
        expect_source_contains="브랜드마케팅팀",
        source_ref="bbea9fa24f9f_checklist.xlsx#row:체크리스트:3",
    )
    card_ok = WikiCard(
        damdang="공통",
        post_id=case.post_id,
        post_title=case.post_title,
        posted_date=date(2026, 6, 11),
        source_ref="bbea9fa24f9f_checklist.xlsx#row:체크리스트:3",
        attachment_name="2. SV팀_260611_26년 6월 2주차 지점 체크리스트.xlsx",
        product_codes=[],
        headline="광고 콘텐츠",
        body="[브랜드마케팅팀] 광고 콘텐츠 운영 개선",
    )
    card_bad = WikiCard(
        damdang="생활리빙",
        post_id=case.post_id,
        post_title=case.post_title,
        posted_date=date(2026, 6, 11),
        source_ref="bbea9fa24f9f_checklist.xlsx#row:체크리스트:3",
        attachment_name="2. SV팀_260611_26년 6월 2주차 지점 체크리스트.xlsx",
        product_codes=[],
        headline="광고",
        body="[브랜드마케팅팀] 광고 콘텐츠 운영 개선",
    )
    indexed, meta_ok = check_corpus_metadata([card_ok], case)
    assert indexed and meta_ok
    indexed, meta_ok = check_corpus_metadata([card_bad], case)
    assert indexed and not meta_ok


def test_corpus_gap_allowed_when_expect_corpus_false():
    case = _case(
        post_id="6148b200b185",
        expect_corpus=False,
        source_ref="6148b200b185_pptx#s1",
    )
    assert corpus_has_source([], case)
    indexed, meta_ok = check_corpus_metadata([], case)
    assert indexed and meta_ok


def test_refs_match_row_level():
    from store_brief.qa.eval.checks import _refs_match

    assert _refs_match(
        "bbea9fa24f9f_checklist.xlsx#row:체크리스트:3",
        "bbea9fa24f9f_checklist.xlsx#row:체크리스트:3",
    )
    assert _refs_match(
        "bbea9fa24f9f_checklist.xlsx",
        "bbea9fa24f9f_checklist.xlsx#row:체크리스트:3",
    )
