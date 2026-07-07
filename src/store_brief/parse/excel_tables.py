"""Extract searchable structured tables from Excel/CSV sheets."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

import pandas as pd

MAX_ROWS_PER_TABLE = 200
MAX_SHEETS = 8
MAX_HEADER_ROWS = 8
REGION_EMPTY_GAP = 2
TITLE_RE = re.compile(r"[▣●◆■]")
NARRATIVE_RE = re.compile(r"^\s*\d+[\).]\s")


@dataclass
class SheetTable:
    sheet: str
    title: str | None
    columns: list[str]
    rows: list[list[str]]
    total_rows: int
    truncated: bool
    region: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _cell_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _row_fill_ratio(cells: list[str]) -> float:
    if not cells:
        return 0.0
    return sum(1 for c in cells if c) / len(cells)


def _looks_numeric(text: str) -> bool:
    if not text:
        return False
    t = text.replace(",", "").replace("%", "").strip()
    if not t:
        return False
    try:
        float(t)
        return True
    except ValueError:
        return False


def _numeric_ratio(cells: list[str]) -> float:
    filled = [c for c in cells if c]
    if not filled:
        return 0.0
    return sum(1 for c in filled if _looks_numeric(c)) / len(filled)


def _unique_columns(raw: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, name in enumerate(raw):
        base = name.strip() or f"col_{i}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}_{n + 1}")
    return out


def _ffill_row(cells: list[str]) -> list[str]:
    out: list[str] = []
    last = ""
    for cell in cells:
        if cell:
            last = cell
        out.append(cell or last)
    return out


def _is_title_row(cells: list[str]) -> bool:
    filled = [c for c in cells if c]
    if not filled:
        return False
    if len(filled) == 1:
        return True
    # Multi-column header rows (e.g. 상품코드 | 상품명 | …) are not titles.
    if len(filled) >= 3:
        return False
    joined = " ".join(filled)
    return bool(TITLE_RE.search(joined)) or len(joined) > 28


def _is_narrative_row(cells: list[str]) -> bool:
    filled = [c for c in cells if c]
    if len(filled) != 1:
        return False
    text = filled[0]
    return bool(NARRATIVE_RE.match(text)) or text.startswith("▶") or text.startswith("-")


def _is_header_like(cells: list[str]) -> bool:
    filled = [c for c in cells if c]
    if not filled:
        return False
    if _is_title_row(cells) or _is_narrative_row(cells):
        return True
    if len(filled) < 2:
        return True
    return _numeric_ratio(cells) < 0.45


def _is_data_like(cells: list[str]) -> bool:
    filled = [c for c in cells if c]
    if len(filled) < 2:
        return False
    numeric = sum(1 for c in filled if _looks_numeric(c))
    if numeric >= 2:
        return True
    if numeric >= 1 and len(filled) >= 3:
        return True
    if _numeric_ratio(cells) >= 0.25 and _row_fill_ratio(cells) >= 0.12:
        return True
    return False


def _find_title(rows: list[list[str]], header_start: int) -> str | None:
    for row in rows[:header_start]:
        filled = [c for c in row if c]
        if not filled:
            continue
        if len(filled) == 1:
            return filled[0]
        joined = " ".join(filled)
        if TITLE_RE.search(joined) or len(joined) > 20:
            return joined
    return None


def _split_regions(rows: list[list[str]]) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    start: int | None = None
    empty_streak = 0

    for idx, row in enumerate(rows):
        if _row_fill_ratio(row) < 0.05:
            empty_streak += 1
            if start is not None and empty_streak >= REGION_EMPTY_GAP:
                regions.append((start, idx - empty_streak))
                start = None
            continue
        if start is None:
            start = idx
        empty_streak = 0

    if start is not None:
        regions.append((start, len(rows) - 1))
    return regions


def _find_header_and_data(rows: list[list[str]]) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0

    cursor = 0
    while cursor < len(rows) and (_is_title_row(rows[cursor]) or _row_fill_ratio(rows[cursor]) < 0.05):
        cursor += 1

    header_start = cursor
    header_end = cursor
    scan_limit = min(len(rows), header_start + MAX_HEADER_ROWS + 5)

    while header_end < scan_limit:
        row = rows[header_end]
        if _is_data_like(row):
            break
        if _is_header_like(row) or _row_fill_ratio(row) < 0.55:
            header_end += 1
            continue
        break

    data_start = header_end
    while data_start < len(rows) and not _is_data_like(rows[data_start]):
        if _is_narrative_row(rows[data_start]):
            data_start += 1
            header_end = data_start
            continue
        data_start += 1

    if data_start >= len(rows):
        return header_start, header_end, len(rows)

    return header_start, header_end, data_start


def merge_header_rows(header_rows: list[list[str]]) -> list[str]:
    return _merge_header_rows(header_rows)


def _merge_header_rows(header_rows: list[list[str]]) -> list[str]:
    if not header_rows:
        return []
    width = max(len(row) for row in header_rows)
    padded = [row + [""] * (width - len(row)) for row in header_rows]
    ffilled = [_ffill_row(row) for row in padded]
    columns: list[str] = []
    for col_idx in range(width):
        parts: list[str] = []
        seen: set[str] = set()
        for row in ffilled:
            value = row[col_idx].strip()
            if value and value not in seen:
                parts.append(value)
                seen.add(value)
        columns.append(" / ".join(parts) if parts else f"col_{col_idx}")
    return _unique_columns(columns)


def _trim_data_rows(rows: list[list[str]], *, max_empty_streak: int = 3) -> list[list[str]]:
    out: list[list[str]] = []
    empty_streak = 0
    for row in rows:
        if _row_fill_ratio(row) < 0.05:
            empty_streak += 1
            if empty_streak >= max_empty_streak:
                break
            continue
        if _is_title_row(row) and out:
            break
        empty_streak = 0
        out.append(row)
    return out


def _infer_leading_index_column(columns: list[str], rows: list[list[str]]) -> list[str]:
    if not columns or not rows:
        return columns
    if not (columns[0].startswith("col_") or columns[0] == ""):
        return columns
    sample = [row[0].strip() for row in rows[: min(10, len(rows))] if row and row[0].strip()]
    if sample and all(v.isdigit() for v in sample):
        columns = list(columns)
        columns[0] = "No."
    return columns


def _drop_empty_columns(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    keep_cols = [
        col_idx
        for col_idx in range(width)
        if any(row[col_idx] for row in padded)
    ]
    if not keep_cols:
        return []
    return [[row[col_idx] for col_idx in keep_cols] for row in padded]


def _dataframe_to_rows(df: pd.DataFrame) -> list[list[str]]:
    if df.empty:
        return []
    rows = df.map(_cell_str).values.tolist()
    return _drop_empty_columns(rows)


def _normalize_rows(rows: list[list[str]], width: int) -> list[list[str]]:
    return [
        row + [""] * (width - len(row)) if len(row) < width else row[:width]
        for row in rows
    ]


def extract_table_from_region(
    sheet_name: str,
    rows: list[list[str]],
    *,
    region_index: int = 0,
) -> SheetTable | None:
    if not rows:
        return None

    header_start, header_end, data_start = _find_header_and_data(rows)
    title = _find_title(rows[:header_start], header_start)
    header_rows = rows[header_start:header_end]
    columns = _merge_header_rows(header_rows) if header_rows else []
    data_rows = _trim_data_rows(rows[data_start:])
    if not data_rows:
        return None

    if not columns:
        width = max(len(row) for row in data_rows)
        columns = [f"col_{i}" for i in range(width)]

    width = len(columns)
    normalized = _normalize_rows(data_rows, width)
    total = len(normalized)
    truncated = total > MAX_ROWS_PER_TABLE
    if truncated:
        normalized = normalized[:MAX_ROWS_PER_TABLE]

    if len(normalized) < 1:
        return None

    meaningful_cols = sum(1 for c in columns if not c.startswith("col_"))
    if meaningful_cols == 0 and _numeric_ratio(normalized[0]) < 0.1:
        return None

    columns = _infer_leading_index_column(columns, normalized)

    return SheetTable(
        sheet=sheet_name,
        title=title,
        columns=columns,
        rows=normalized,
        total_rows=total,
        truncated=truncated,
        region=region_index,
    )


def extract_tables_from_sheet(sheet_name: str, df: pd.DataFrame) -> list[SheetTable]:
    rows = _dataframe_to_rows(df)
    if not rows:
        return []

    tables: list[SheetTable] = []
    regions = _split_regions(rows)
    if not regions:
        return []

    for region_index, (start, end) in enumerate(regions):
        region_rows = [
            row for row in rows[start : end + 1]
            if _row_fill_ratio(row) > 0
        ]
        table = extract_table_from_region(sheet_name, region_rows, region_index=region_index)
        if table is not None:
            tables.append(table)
    return tables


def tables_to_text(tables: list[SheetTable]) -> str:
    chunks: list[str] = []
    for table in tables:
        label = table.sheet if table.region == 0 else f"{table.sheet} (영역 {table.region + 1})"
        header = f"### 시트: {label}"
        if table.title:
            header += f"\n{table.title}"
        lines = [
            header,
            "| " + " | ".join(table.columns) + " |",
            "| " + " | ".join("---" for _ in table.columns) + " |",
        ]
        for row in table.rows:
            lines.append("| " + " | ".join(row) + " |")
        if table.truncated:
            lines.append(f"(상위 {MAX_ROWS_PER_TABLE}행만 표시, 전체 {table.total_rows}행)")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


def extract_tables_from_raw_sheets(raw_sheets) -> list[SheetTable]:
    """Extract tables from merged cell grids (openpyxl read path)."""
    tables: list[SheetTable] = []
    for raw in raw_sheets:
        trimmed = _drop_empty_columns(raw.rows)
        if not trimmed:
            continue
        table = extract_table_from_region(raw.sheet, trimmed)
        if table is not None:
            tables.append(table)
    return tables


def extract_tables_from_workbook(sheets: dict[str, pd.DataFrame]) -> list[SheetTable]:
    tables: list[SheetTable] = []
    for sheet_index, (name, df) in enumerate(sheets.items()):
        if sheet_index >= MAX_SHEETS:
            break
        tables.extend(extract_tables_from_sheet(str(name), df))
    return tables
