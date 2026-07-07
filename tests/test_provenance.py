"""Tests for event provenance repair."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.extract.provenance import (
    PostCorpus,
    TextSection,
    build_post_corpus,
    dedupe_events,
    fit_score,
    keyword_set,
    normalize_title,
    sanitize_post_events,
    title_anchor_fit,
)
from store_brief.extract.schema import Event, EventType, ImageNote
from store_brief.parse.layout_schema import PageRecord
from store_brief.parse.router import ParsedAttachment


def _weekly_guide_parsed() -> ParsedAttachment:
    return ParsedAttachment(
        attachment_id="cc04e61c6be0_guide.pptx",
        text="### 슬라이드 1\n6월 1주차 분류담당자 가이드–KBB\nKBB 매장 연출",
        pages=[
            PageRecord(index=1, ref="cc04e61c6be0_guide.pptx#s1", text="KBB 매장 연출"),
        ],
        image_paths=[
            ("x.png", "cc04e61c6be0_hero.jpg#img0"),
            ("y.png", "cc04e61c6be0_guide.pptx#s1"),
        ],
    )


def _ruler_parsed() -> ParsedAttachment:
    return ParsedAttachment(
        attachment_id="6f93886a5c63_ruler.pptx",
        text="### 슬라이드 1\n종이 줄자 운영안\nKBB 매장 대상 종이 줄자 POP",
        pages=[
            PageRecord(
                index=1,
                ref="6f93886a5c63_ruler.pptx#s1",
                text="종이 줄자 운영안\nKBB 매장 대상 종이 줄자 POP",
            ),
        ],
    )


class _Post:
    def __init__(self, pid: str, title: str, body: str = ""):
        self.id = pid
        self.title = title
        self.body = body


def test_keyword_set_includes_korean_product_terms():
    kw = keyword_set("[ISP] 종이 줄자 운영 가이드")
    assert "종이" in kw or "줄자" in kw


def test_fit_score_ruler_event_on_ruler_post():
    corpus = build_post_corpus(
        _Post("6f93886a5c63", "종이 줄자 운영안"),
        [_ruler_parsed()],
    )
    kw = keyword_set("종이 줄자 운영 가이드")
    assert fit_score(kw, corpus) > 0.4


def test_fit_score_ruler_event_not_on_weekly_guide():
    corpus = build_post_corpus(
        _Post("cc04e61c6be0", "6월 1주차 분류담당자 업무 가이드"),
        [_weekly_guide_parsed()],
    )
    kw = keyword_set("종이 줄자 운영 가이드")
    assert fit_score(kw, corpus) < 0.2


def test_sanitize_reassigns_wrong_post_and_scopes_images():
    weekly = _weekly_guide_parsed()
    ruler = _ruler_parsed()
    wrong = Event(
        id="deadbeef",
        type=EventType.event,
        title="[ISP] 종이 줄자 운영 가이드",
        summary="KBB 매장 대상 종이 줄자 POP 및 철제거치대 활용 연출 가이드",
        categories=["KBB"],
        source_post_id="cc04e61c6be0",
        attachment_refs=[
            "cc04e61c6be0_hero.jpg#img0",
            "cc04e61c6be0_guide.pptx#s1",
        ],
        images=[
            ImageNote(
                source_ref="cc04e61c6be0_hero.jpg#img0",
                kind="포스터",
                description="샥즈 오픈핏 에어 이어폰 프로모션",
            ),
            ImageNote(
                source_ref="cc04e61c6be0_guide.pptx#s1",
                kind="표",
                description="6월 1주차 분류담당자 가이드",
            ),
        ],
    )
    corpora = {
        "cc04e61c6be0": build_post_corpus(
            _Post("cc04e61c6be0", "분류담당자 가이드"), [weekly],
        ),
        "6f93886a5c63": build_post_corpus(
            _Post("6f93886a5c63", "종이 줄자 운영안"), [ruler],
        ),
    }
    parsed_by_post = {
        "cc04e61c6be0": [weekly],
        "6f93886a5c63": [ruler],
    }
    cleaned, stats = sanitize_post_events(
        [wrong],
        _Post("cc04e61c6be0", "분류담당자 가이드"),
        [weekly],
        all_corpora=corpora,
        parsed_by_post=parsed_by_post,
    )
    assert len(cleaned) == 1
    assert cleaned[0].source_post_id == "6f93886a5c63"
    assert stats.reassigned_count == 1
    assert all("cc04e61c6be0" not in img.source_ref for img in cleaned[0].images)
    assert all("샥즈" not in img.description for img in cleaned[0].images)


def test_dedupe_keeps_better_provenance():
    good = Event(
        id="a1",
        type=EventType.event,
        title="종이 줄자 운영 가이드 및 진열 안내",
        summary="종이 줄자 POP 운영",
        source_post_id="6f93886a5c63",
        attachment_refs=["6f93886a5c63_ruler.pptx#s1"],
    )
    bad = Event(
        id="a2",
        type=EventType.event,
        title="[ISP] 종이 줄자 운영 가이드",
        summary="종이 줄자 POP 운영",
        source_post_id="cc04e61c6be0",
        attachment_refs=[],
    )
    corpora = {
        "6f93886a5c63": PostCorpus(
            "6f93886a5c63",
            "종이 줄자",
            "",
            [TextSection("6f93886a5c63_ruler.pptx#s1", "종이 줄자 운영안")],
        ),
        "cc04e61c6be0": PostCorpus("cc04e61c6be0", "가이드", "", []),
    }
    kept, dropped = dedupe_events([good, bad], corpora)
    assert dropped == 1
    assert len(kept) == 1
    assert kept[0].source_post_id == "6f93886a5c63"


def test_dedupe_keeps_multiple_events_from_same_post():
    a = Event(
        id="b1",
        type=EventType.notice,
        title="KBB 매장 연출 가이드",
        summary="KBB POP 운영",
        source_post_id="cc04e61c6be0",
    )
    b = Event(
        id="b2",
        type=EventType.notice,
        title="KBB 재고 소진 안내",
        summary="KBB 비데 재고",
        source_post_id="cc04e61c6be0",
    )
    corpora = {"cc04e61c6be0": PostCorpus("cc04e61c6be0", "가이드", "", [])}
    kept, dropped = dedupe_events([a, b], corpora)
    assert dropped == 0
    assert len(kept) == 2


def test_title_anchor_fit_requires_words_in_corpus():
    weekly = PostCorpus("cc04e61c6be0", "가이드", "", [TextSection("s1", "KBB 매장 연출")])
    ruler = PostCorpus(
        "6f93886a5c63",
        "종이 줄자",
        "",
        [TextSection("s1", "종이 줄자 운영안 KBB POP")],
    )
    assert title_anchor_fit("[ISP] 종이 줄자 운영 가이드", weekly) == 0.0
    assert title_anchor_fit("[ISP] 종이 줄자 운영 가이드", ruler) == 1.0


def test_normalize_title_strips_brackets():
    assert "종이 줄자" in normalize_title("[ISP] 종이 줄자 운영 가이드")
