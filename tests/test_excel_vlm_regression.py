"""Regression patterns for Excel VLM layout pipeline (no COM / no vLLM)."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.parse.apply_layout import apply_layouts
from store_brief.parse.excel_tables import extract_tables_from_sheet
from store_brief.parse.layout_schema import RawSheet, TableLayoutSheet, TableRegionSpec
import pandas as pd


def test_simple_list_heuristic_still_works():
    df = pd.DataFrame([["No.", "지사", "지점"], ["1", "강남", "잠실"]])
    tables = extract_tables_from_sheet("진열점", df)
    assert tables and tables[0].columns[0] == "No."


def test_complex_sheet_via_layout_apply():
    """음식물처리기-style multi-header via explicit layout."""
    raw_rows = [
        ["", "▣ 음식물처리기 소진", "", ""],
        ["", "", "", ""],
        ["구분", "지사", "지점", "소진율"],
        ["", "", "", ""],
        ["합계", "회사 계", "", "0.35"],
        ["강북", "", "강북", "0.38"],
    ]
    raw = RawSheet("현황", raw_rows)
    layout = TableLayoutSheet(
        sheet="현황",
        regions=[
            TableRegionSpec(
                sheet="현황",
                title="▣ 음식물처리기 소진",
                header_rows=[2],
                data_start_row=4,
                columns=["구분", "지사", "지점", "소진율"],
                col_indices=[0, 1, 2, 3],
            )
        ],
        confidence=0.85,
    )
    tables = apply_layouts([raw], [layout])
    assert len(tables) == 1
    assert tables[0].rows[0][0] == "합계"
    assert tables[0].rows[1][2] == "강북"


def test_tv_award_layout_apply():
    raw = RawSheet(
        "6월 지사 시상 안내",
        [
            ["구분", "실적", "목표", "달성율"],
            ["강북지사", "104", "125", "0.83"],
        ],
    )
    layout = TableLayoutSheet(
        sheet="6월 지사 시상 안내",
        regions=[
            TableRegionSpec(
                sheet="6월 지사 시상 안내",
                header_rows=[0],
                data_start_row=1,
                columns=["구분", "실적", "목표", "달성율"],
                col_indices=[0, 1, 2, 3],
            )
        ],
        confidence=0.9,
    )
    tables = apply_layouts([raw], [layout])
    assert tables[0].rows[0][0] == "강북지사"


if __name__ == "__main__":
    test_simple_list_heuristic_still_works()
    test_complex_sheet_via_layout_apply()
    test_tv_award_layout_apply()
    print("ok")
