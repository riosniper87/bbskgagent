"""Apply VLM-inferred table layout to raw cell grids."""
from __future__ import annotations

from store_brief.parse.excel_tables import (
    MAX_ROWS_PER_TABLE,
    SheetTable,
    _cell_str,
    _row_fill_ratio,
    _trim_data_rows,
    merge_header_rows,
)
from store_brief.parse.layout_schema import RawSheet, TableLayoutSheet, TableRegionSpec


def _pick_columns(region: TableRegionSpec, raw_rows: list[list[str]]) -> tuple[list[str], list[int]]:
    if region.columns and region.col_indices and len(region.columns) == len(region.col_indices):
        return region.columns, region.col_indices
    if region.header_rows:
        header_rows = [raw_rows[i] for i in region.header_rows if i < len(raw_rows)]
        cols = merge_header_rows(header_rows)
        if region.columns and len(region.columns) == len(cols):
            return region.columns, list(range(len(cols)))
        return cols, list(range(len(cols)))
    if region.columns:
        idx = region.col_indices or list(range(len(region.columns)))
        return region.columns, idx
    return [], []


def apply_region(raw_rows: list[list[str]], region: TableRegionSpec) -> SheetTable | None:
    columns, col_indices = _pick_columns(region, raw_rows)
    if not columns:
        return None

    data_end = region.data_end_row if region.data_end_row is not None else len(raw_rows)
    data_end = min(data_end, len(raw_rows))
    data_start = min(max(region.data_start_row, 0), data_end)
    data_rows = _trim_data_rows(raw_rows[data_start:data_end])
    if not data_rows:
        return None

    normalized: list[list[str]] = []
    for row in data_rows:
        if _row_fill_ratio(row) < 0.05:
            continue
        normalized.append([
            _cell_str(row[i]) if i < len(row) else ""
            for i in col_indices
        ])

    if not normalized:
        return None

    total = len(normalized)
    truncated = total > MAX_ROWS_PER_TABLE
    if truncated:
        normalized = normalized[:MAX_ROWS_PER_TABLE]

    return SheetTable(
        sheet=region.sheet,
        title=region.title,
        columns=columns,
        rows=normalized,
        total_rows=total,
        truncated=truncated,
        region=region.region,
    )


def apply_layout_sheet(raw: RawSheet, layout: TableLayoutSheet) -> list[SheetTable]:
    tables: list[SheetTable] = []
    for region in layout.regions:
        region.sheet = layout.sheet
        table = apply_region(raw.rows, region)
        if table is not None:
            tables.append(table)
    return tables


def apply_layouts(raw_sheets: list[RawSheet], layouts: list[TableLayoutSheet]) -> list[SheetTable]:
    by_name = {r.sheet: r for r in raw_sheets}
    tables: list[SheetTable] = []
    for layout in layouts:
        raw = by_name.get(layout.sheet)
        if raw is None:
            continue
        tables.extend(apply_layout_sheet(raw, layout))
    return tables
