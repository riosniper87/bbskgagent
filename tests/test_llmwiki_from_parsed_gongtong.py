"""WikiCard build: 구분=공통 checklist rows → damdang=공통."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.ingestion.parse_xlsx import parse_xlsx_from_record
from store_brief.llmwiki.from_parsed import records_to_wiki_cards
from store_brief.llmwiki.grouping import FALLBACK_KEY, load_qa_damdang_roster
from store_brief.parse.store import ParsedAttachmentStore
from datetime import date

DATA = Path(__file__).resolve().parents[1] / "data"
STORE = ParsedAttachmentStore(DATA / "parsed")


def test_bbea9fa24f9f_gongtong_row_card():
    record = STORE.load_record("bbea9fa24f9f", "495f70425fe1")
    if record is None:
        pytest.skip("checklist parsed record missing")

    norm_records = parse_xlsx_from_record(record, "bbea9fa24f9f", data_dir=DATA)
    row3 = next(
        (r for r in norm_records if r.provenance.source_ref.endswith(":3")),
        None,
    )
    assert row3 is not None

    roster = set(load_qa_damdang_roster(str(DATA / "rnr.txt")))
    cards = records_to_wiki_cards(
        [row3],
        post_id="bbea9fa24f9f",
        post_title="체크리스트",
        posted_date=date(2026, 6, 11),
        record=record,
        lookup={},
        roster=roster,
    )
    assert cards
    assert any(c.damdang == FALLBACK_KEY for c in cards)
    ad_card = next(c for c in cards if "브랜드마케팅팀" in c.body)
    assert ad_card.damdang == "공통"
    assert "#row:체크리스트:3" in ad_card.source_ref
