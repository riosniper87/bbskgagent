"""Tests for applying VLM table layout to raw grids."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.parse.apply_layout import apply_layouts, apply_region
from store_brief.parse.layout_schema import RawSheet, TableLayoutSheet, TableRegionSpec


def test_simple_list_layout():
    raw_rows = [
        ["No.", "지사", "지점", "비고"],
        ["1", "강남", "잠실HM", "진열완료"],
        ["2", "강북", "상계HM", "진열완료"],
    ]
    region = TableRegionSpec(
        sheet="진열점",
        header_rows=[0],
        data_start_row=1,
        columns=["No.", "지사", "지점", "비고"],
        col_indices=[0, 1, 2, 3],
    )
    table = apply_region(raw_rows, region)
    assert table is not None
    assert table.columns == ["No.", "지사", "지점", "비고"]
    assert len(table.rows) == 2
    assert table.rows[0][1] == "강남"


def test_multi_header_layout():
    raw_rows = [
        ["▣ 지사별 소진 현황", "", "", ""],
        ["", "", "", ""],
        ["구분", "기초", "", "소진율"],
        ["", "3월말", "5월말", ""],
        ["합계", "100", "80", "0.2"],
        ["강북", "10", "8", "0.2"],
    ]
    region = TableRegionSpec(
        sheet="현황",
        title="▣ 지사별 소진 현황",
        header_rows=[2, 3],
        data_start_row=4,
        columns=["구분", "기초 / 3월말", "기초 / 5월말", "소진율"],
        col_indices=[0, 1, 2, 3],
    )
    table = apply_region(raw_rows, region)
    assert table is not None
    assert table.rows[0][0] == "합계"
    assert table.rows[1][0] == "강북"


def test_apply_layouts_workbook():
    raw = RawSheet(
        sheet="총판수량",
        rows=[
            ["지사", "실적", "목표", "달성율"],
            ["강북지사", "104", "125", "0.83"],
        ],
    )
    layout = TableLayoutSheet(
        sheet="총판수량",
        regions=[
            TableRegionSpec(
                sheet="총판수량",
                header_rows=[0],
                data_start_row=1,
                columns=["지사", "실적", "목표", "달성율"],
                col_indices=[0, 1, 2, 3],
            )
        ],
        confidence=0.9,
    )
    tables = apply_layouts([raw], [layout])
    assert len(tables) == 1
    assert tables[0].rows[0][0] == "강북지사"


if __name__ == "__main__":
    test_simple_list_layout()
    test_multi_header_layout()
    test_apply_layouts_workbook()
    print("ok")
