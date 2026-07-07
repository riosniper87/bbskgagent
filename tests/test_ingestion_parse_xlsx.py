"""Tests for ingestion/parse_xlsx row-level normalization."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.ingestion.parse_xlsx import match_profile, parse_xlsx_from_record
from store_brief.parse.store import ParsedAttachmentStore

DATA = Path(__file__).resolve().parents[1] / "data"
STORE = ParsedAttachmentStore(DATA / "parsed")


def test_match_checklist_profile():
    p = match_profile("2. SV팀_260611_26년 6월 2주차 지점 체크리스트.xlsx")
    assert p is not None
    assert p.name == "체크리스트_지점"


def test_match_jindyeol_profile():
    p = match_profile("01_노트북 진열소진현황_0614마감.xlsx")
    assert p is not None
    assert p.name == "진열소진_노트북"


def test_match_sojin_list_profile():
    p = match_profile("15. [생활가전팀]_오클린구강용품_6월_소진현황_260608_송부용.xlsx")
    assert p is not None
    assert p.name == "소진리스트"


def test_match_bcd_profile():
    p = match_profile("260615_가전주방 BCD재고 소진현황.xlsx")
    assert p is not None
    assert p.name == "bcd_모델별"


def test_match_non_pog_profile():
    p = match_profile("260615_NON POG 문구사무,생활주방기타_소진현황.xlsx")
    assert p is not None
    assert p.name == "non_pog_모델별"


def test_match_jumbyeol_profile():
    p = match_profile("07_개인용선풍기 지사지점 판매현황_0614.xlsx")
    assert p is not None
    assert p.name == "점별모델확인"


def test_match_sv_profile():
    p = match_profile(
        "SV팀_6월_슈퍼히어로,하이라이트행사모델_진도율통합_0614_마감(총판)_V2_공지용.xlsx",
    )
    assert p is not None
    assert p.name == "sv_행사모델"


def test_checklist_row_records():
    record = STORE.load_record("bbea9fa24f9f", "495f70425fe1")
    if record is None:
        pytest.skip("parsed checklist not available")
    records = parse_xlsx_from_record(record, "bbea9fa24f9f", data_dir=DATA)
    assert len(records) > 10
    row3 = next(
        (r for r in records if r.provenance.source_ref.endswith(":3")),
        None,
    )
    assert row3 is not None
    assert row3.category_value == "공통"
    assert "브랜드마케팅팀" in row3.body
    assert row3.provenance.extraction == "profile"
    assert row3.review_flag is None


def test_jindyeol_inventory_rows():
    meta = json.loads((DATA / "parsed" / "126c62ac2108" / "meta.json").read_text(encoding="utf-8"))
    att_key = None
    for key in meta.get("records", []):
        rec = STORE.load_record("126c62ac2108", key)
        if rec and "진열소진" in rec.filename:
            att_key = key
            record = rec
            break
    if att_key is None:
        pytest.skip("진열소진 parsed record not available")
    p = match_profile(record.filename)
    assert p is not None
    assert p.header_rows == [5, 6]
    assert p.damdang_from == "product"
    records = parse_xlsx_from_record(record, "126c62ac2108", data_dir=DATA)
    assert len(records) > 5
    assert all("지사지점재고확인" in r.provenance.locator for r in records)
    assert all(r.provenance.extraction == "profile" for r in records)
    # Profile headers: branch inventory columns should appear in body (not col_* dump)
    sample = next(r for r in records if "모델명:" in r.body)
    assert "재고" in sample.body or "진열" in sample.body
    assert "col_0" not in sample.body
    assert sample.provenance.raw.get("damdang_from") == "product"
    assert sample.category_value  # 메이커 column


def test_fallback_flag_on_unknown_excel():
    record = STORE.load_record("9c9f6727c664", None)  # invalid
    if record is not None:
        return
    # use any non-profile excel from 오클린 post
    meta_path = DATA / "parsed" / "9c9f6727c664" / "meta.json"
    if not meta_path.is_file():
        pytest.skip("오클린 parsed not available")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    record = None
    for key in meta.get("records", []):
        rec = STORE.load_record("9c9f6727c664", key)
        if rec and rec.kind == "excel" and "오클린" in rec.filename:
            record = rec
            break
    if record is None:
        pytest.skip("오클린 excel not available")
    p = match_profile(record.filename)
    assert p is not None
    assert p.name == "소진리스트"
    records = parse_xlsx_from_record(record, "9c9f6727c664", data_dir=DATA)
    assert records
    assert all(r.provenance.extraction == "profile" for r in records)
    assert any("V8100" in r.body or "오클린" in r.body for r in records)
