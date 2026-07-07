"""Tests for temporal metadata and time-based card queries."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.extract.schema import ExtractedTable
from store_brief.llmwiki.card import WikiCard
from store_brief.temporal.meta import (
    NoticeKind,
    extract_temporal_meta,
    link_card_versions,
)
from store_brief.temporal.parse import parse_all_validity_ranges, parse_validity_range
from store_brief.temporal.query import (
    active_on,
    observable_on,
    posted_between,
    version_pairs,
)
from store_brief.temporal.tables import windows_from_tables


def test_parse_iso_validity_range():
    vf, vt = parse_validity_range("행사 2026.06.01~2026.06.30", year=2026)
    assert vf == date(2026, 6, 1)
    assert vt == date(2026, 6, 30)


def test_extract_promotion_window():
    tm = extract_temporal_meta(
        text="[전기밥솥] 6월 중점 행사\n행사 기간 : 6/5~8, 6/12~15",
        posted_date=date(2026, 6, 3),
        title="6월 판촉",
        filename="promo.xlsx",
        damdang="생활주방",
    )
    assert tm.notice_kind == NoticeKind.promotion
    assert tm.valid_from == date(2026, 6, 5)
    assert tm.valid_to == date(2026, 6, 8)
    assert tm.topic_key


def test_active_on_filters_by_validity():
    cards = [
        WikiCard(
            damdang="대형가전1",
            post_id="a",
            post_title="t",
            posted_date=date(2026, 6, 1),
            source_ref="x",
            attachment_name="f",
            temporal=extract_temporal_meta(
                text="6/1~6/15",
                posted_date=date(2026, 6, 1),
                damdang="대형가전1",
            ),
        ),
        WikiCard(
            damdang="대형가전1",
            post_id="b",
            post_title="t2",
            posted_date=date(2026, 5, 1),
            source_ref="y",
            attachment_name="g",
            temporal=extract_temporal_meta(
                text="5/1~5/10",
                posted_date=date(2026, 5, 1),
                damdang="대형가전1",
            ),
        ),
    ]
    mid_june = active_on(cards, date(2026, 6, 10))
    assert len(mid_june) == 1
    assert mid_june[0].post_id == "a"


def test_posted_between_two_month_window():
    cards = [
        WikiCard(
            damdang="IT",
            post_id="old",
            post_title="t",
            posted_date=date(2026, 4, 20),
            source_ref="x",
            attachment_name="f",
        ),
        WikiCard(
            damdang="IT",
            post_id="new",
            post_title="t",
            posted_date=date(2026, 6, 12),
            source_ref="x",
            attachment_name="f",
        ),
    ]
    window = posted_between(cards, date(2026, 5, 1), date(2026, 6, 17))
    assert [c.post_id for c in window] == ["new"]


def test_version_chain_links_same_topic():
    base = dict(
        damdang="대형가전1",
        post_title="설치 변경",
        posted_date=date(2026, 5, 1),
        source_ref="a#s1",
        attachment_name="CS마스터_설치변경.pptx",
        product_codes=["X"],
        headline="설치 변경 v1",
        body="내용 v1",
    )
    c1 = WikiCard(**base, post_id="p1", temporal=extract_temporal_meta(
        text="6월1일부 변경", posted_date=date(2026, 5, 1),
        filename=base["attachment_name"], damdang="대형가전1",
    ))
    c2 = WikiCard(
        damdang=base["damdang"],
        post_title=base["post_title"],
        source_ref=base["source_ref"],
        attachment_name=base["attachment_name"],
        product_codes=base["product_codes"],
        post_id="p2",
        posted_date=date(2026, 6, 5),
        headline="설치 변경 v2",
        body="내용 v2",
        temporal=extract_temporal_meta(
            text="6월15일부 변경", posted_date=date(2026, 6, 5),
            filename=base["attachment_name"], damdang="대형가전1",
        ),
    )
    link_card_versions([c1, c2])
    assert c2.temporal.version_of == c1.id
    pairs = version_pairs([c1, c2])
    assert len(pairs) == 1
    assert pairs[0]["old"].id == c1.id


def test_observable_on_excludes_future_posts():
    c = WikiCard(
        damdang="KBB",
        post_id="x",
        post_title="t",
        posted_date=date(2026, 6, 20),
        source_ref="r",
        attachment_name="f",
    )
    assert observable_on([c], date(2026, 6, 10)) == []


def test_parse_all_validity_ranges_comma_separated():
    wins = parse_all_validity_ranges("6/5~8, 6/12~15", year=2026)
    assert wins == [
        (date(2026, 6, 5), date(2026, 6, 8)),
        (date(2026, 6, 12), date(2026, 6, 15)),
    ]


def test_table_haengsa_date_column():
    tbl = ExtractedTable(
        source_ref="a#table0",
        columns=["행사날짜", "브랜드", "상품코드"],
        rows=[
            ["6/1~6/30", "쿠쿠", "CRG-AT5110MS"],
            ["6/5~8", "LG", "X324GB5.AKOR"],
            ["6/12~15", "삼성", "RM70F63"],
        ],
    )
    windows = windows_from_tables([tbl], year=2026)
    assert len(windows) == 3
    assert windows[0] == (date(2026, 6, 1), date(2026, 6, 30))
    assert windows[1] == (date(2026, 6, 5), date(2026, 6, 8))


def test_extract_temporal_meta_from_promo_table():
    tbl = ExtractedTable(
        source_ref="a#table0",
        columns=["행사날짜", "품목"],
        rows=[["6/12~6/15", "4도어 냉장고"]],
    )
    tm = extract_temporal_meta(
        text="",
        posted_date=date(2026, 6, 10),
        title="6월 판촉",
        filename="promo.xlsx",
        damdang="대형가전1",
        tables=[tbl],
    )
    assert tm.notice_kind == NoticeKind.promotion
    assert tm.valid_from == date(2026, 6, 12)
    assert tm.valid_to == date(2026, 6, 15)
    assert tm.event_windows == [(date(2026, 6, 12), date(2026, 6, 15))]


def test_active_on_uses_event_windows_not_envelope_only():
    tbl = ExtractedTable(
        source_ref="a#table0",
        columns=["행사날짜", "품목"],
        rows=[
            ["6/5~8", "A"],
            ["6/20~22", "B"],
        ],
    )
    tm = extract_temporal_meta(
        text="",
        posted_date=date(2026, 6, 1),
        damdang="대형가전1",
        tables=[tbl],
    )
    card = WikiCard(
        damdang="대형가전1",
        post_id="p",
        post_title="t",
        posted_date=date(2026, 6, 1),
        source_ref="r",
        attachment_name="f",
        temporal=tm,
    )
    assert active_on([card], date(2026, 6, 7))
    assert not active_on([card], date(2026, 6, 15))
