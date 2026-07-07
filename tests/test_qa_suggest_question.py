"""Tests for sample question generation."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.llmwiki.card import WikiCard
from store_brief.qa.corpus import QACorpus
from store_brief.qa.tools.suggest_question import (
    ContentSnippet,
    card_to_snippet,
    collect_card_snippets,
    collect_snippets,
    generate_question_from_snippet,
    sample_snippet_from_corpus,
)
from store_brief.viewer.loader import AttachmentView, PageView, PostDetail


class MockLLM:
    def complete(self, prompt, system=None):
        return "6월 삼성 냉장고 판촉 기간이 언제까지인가요?"


def _card(**kwargs) -> WikiCard:
    defaults = dict(
        damdang="생활리빙",
        post_id="p1",
        post_title="6월 판촉",
        posted_date=date(2026, 6, 1),
        source_ref="p1#body",
        attachment_name="(게시글 본문)",
        body="6월 1일부터 6월 30일까지 냉장고 판촉 진행 " * 5,
    )
    defaults.update(kwargs)
    return WikiCard(**defaults)


def test_collect_snippets_from_body_and_slide():
    post = PostDetail(
        post_id="abc",
        title="테스트 공지",
        body="내용\n" + "판촉 안내 " * 30,
        posted_date="2026-06-10",
        parsed_at="",
        attachments=[
            AttachmentView(
                att_key="k1",
                filename="a.pptx",
                kind="pptx",
                parse_mode="",
                error=None,
                view_type="slides",
                pages=[
                    PageView(
                        index=1,
                        ref="abc#s1",
                        text="LG 냉장고 6월 행사 " * 20,
                        image_url=None,
                        vlm=None,
                    ),
                ],
            ),
        ],
    )
    snippets = collect_snippets(post)
    types = {s.source_type for s in snippets}
    assert "body" in types
    assert "slide" in types


def test_generate_question_mock_llm():
    snip = ContentSnippet(
        post_id="x",
        post_title="6월 판촉",
        posted_date="2026-06-01",
        source_type="body",
        source_label="본문",
        source_ref="x#body",
        text="6월 1일부터 6월 30일까지 냉장고 판촉 진행",
    )
    q = generate_question_from_snippet(MockLLM(), snip)
    assert "판촉" in q or "6월" in q


def test_card_to_snippet_skips_short_or_boilerplate():
    assert card_to_snippet(_card(body="짧음")) is None
    assert card_to_snippet(_card(body="프롬프트 안내 " * 20)) is None


def test_sample_snippet_from_corpus():
    corpus = QACorpus(
        as_of="2026-06-17",
        cards=[
            _card(post_id="in_corpus", source_ref="in_corpus#body"),
            _card(
                post_id="future",
                posted_date=date(2026, 7, 1),
                source_ref="future#body",
            ),
        ],
    )
    import random

    snip = sample_snippet_from_corpus(corpus, as_of="2026-06-17", rng=random.Random(0))
    assert snip.post_id == "in_corpus"
    assert snip.source_ref == "in_corpus#body"


def test_collect_card_snippets_maps_fields():
    snippets = collect_card_snippets([
        _card(
            attachment_name="체크리스트.xlsx",
            source_ref="p1_file.xlsx#table0",
            headline="체크리스트 (영역 2)",
        ),
    ])
    assert len(snippets) == 1
    assert snippets[0].source_type == "sheet"
    assert "체크리스트" in snippets[0].source_label
