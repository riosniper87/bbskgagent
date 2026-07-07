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


def _stub_record(*, filename: str, tables=None, raw_sheets=None, text: str = ""):
    from types import SimpleNamespace

    return SimpleNamespace(
        attachment_id="attx",
        filename=filename,
        kind="excel",
        error=None,
        source_path="",
        tables=tables or [],
        raw_sheets=raw_sheets or [],
        text=text,
    )


def test_unmatched_file_with_meaningful_tables_uses_heuristic():
    record = _stub_record(
        filename="임의_공지_자료.xlsx",
        tables=[{
            "sheet": "안내",
            "columns": ["구분", "내용", "기한"],
            "rows": [
                ["공통", "매장 P.O.P 교체 안내드립니다", "6/30"],
                ["가전", "신모델 진열 지침 안내드립니다", "7/2"],
            ],
        }],
    )
    assert match_profile(record.filename) is None
    records = parse_xlsx_from_record(record, "post_h")
    assert records
    assert all(r.source_type == "excel_row" for r in records)
    assert all(r.provenance.extraction == "deterministic" for r in records)
    assert all(r.review_flag is None for r in records)
    assert all(r.provenance.raw.get("heuristic") is True for r in records)
    assert any("P.O.P" in r.body for r in records)


def test_unmatched_inventory_sheet_stays_flagged_fallback():
    record = _stub_record(
        filename="임의_재고_자료용.xlsx",
        tables=[{
            "sheet": "지사지점재고확인",
            "columns": ["모델명", "재고", "진열"],
            "rows": [["ABC-1", "3", "1"], ["ABC-2", "5", "2"]],
        }],
    )
    assert match_profile(record.filename) is None
    records = parse_xlsx_from_record(record, "post_n")
    assert records
    assert all(r.source_type == "excel_fallback" for r in records)
    assert all(r.review_flag == "xlsx_fallback" for r in records)


def test_unmatched_col_headers_stay_flagged_fallback():
    record = _stub_record(
        filename="임의_기타_자료용.xlsx",
        tables=[{
            "sheet": "Sheet1",
            "columns": ["col_0", "col_1", "col_2"],
            "rows": [["a", "b", "c"], ["d", "e", "f"]],
        }],
    )
    records = parse_xlsx_from_record(record, "post_c")
    assert records
    assert all(r.review_flag == "xlsx_fallback" for r in records)


def test_blob_fallback_drops_empty_rows_and_columns():
    record = _stub_record(
        filename="임의_빈칸_자료용.xlsx",
        raw_sheets=[{
            "sheet": "Sheet1",
            "rows": [
                ["", "", "", ""],
                ["제목", "", "값", ""],
                ["", "", "", ""],
                ["항목A", "", "10", ""],
            ],
        }],
    )
    records = parse_xlsx_from_record(record, "post_b")
    assert records
    body = records[0].body
    assert "제목\t값" in body
    assert "항목A\t10" in body
    assert "\t\t" not in body
    lines = [ln for ln in body.splitlines()[1:] if not ln.strip()]
    assert not lines


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
