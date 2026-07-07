"""Extract promotion/event date windows from structured Excel tables."""
from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

from store_brief.temporal.parse import parse_all_validity_ranges

if TYPE_CHECKING:
    from store_brief.extract.schema import ExtractedTable
    from store_brief.temporal.meta import NoticeKind, TemporalMeta

_DATE_COL_HINTS = (
    "행사날짜",
    "행사기간",
    "적용기간",
    "판촉기간",
    "이벤트기간",
    "프로모션기간",
    "기간",
)


def _norm_col(name: str) -> str:
    return re.sub(r"\s+", "", str(name or ""))


def date_column_index(columns: list[str]) -> int | None:
    for i, col in enumerate(columns):
        c = _norm_col(col)
        if any(h in c for h in _DATE_COL_HINTS):
            return i
    return None


def windows_from_table(table: ExtractedTable, *, year: int) -> list[tuple[date, date | None]]:
    cols = list(table.columns or [])
    rows = table.rows or []
    if not cols or not rows:
        return []

    idx = date_column_index(cols)
    if idx is None:
        return []

    seen: set[tuple[date, date | None]] = set()
    out: list[tuple[date, date | None]] = []
    for row in rows:
        if idx >= len(row):
            continue
        cell = str(row[idx]).strip()
        if not cell or cell in ("-", "—", "N/A"):
            continue
        for vf, vt in parse_all_validity_ranges(cell, year=year):
            key = (vf, vt)
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def windows_from_tables(tables: list[ExtractedTable], *, year: int) -> list[tuple[date, date | None]]:
    seen: set[tuple[date, date | None]] = set()
    out: list[tuple[date, date | None]] = []
    for tbl in tables:
        for w in windows_from_table(tbl, year=year):
            if w not in seen:
                seen.add(w)
                out.append(w)
    return sorted(out, key=lambda x: x[0])


def apply_table_windows(meta: TemporalMeta, windows: list[tuple[date, date | None]]) -> TemporalMeta:
    """Merge table-derived windows into card-level temporal metadata."""
    if not windows:
        return meta

    from store_brief.temporal.meta import NoticeKind

    meta.event_windows = list(windows)
    starts = [w[0] for w in windows]
    ends = [w[1] for w in windows if w[1] is not None]

    span_from = min(starts)
    span_to = max(ends) if ends else None

    if meta.valid_from is None:
        meta.valid_from = span_from
    else:
        meta.valid_from = min(meta.valid_from, span_from)

    if span_to:
        if meta.valid_to is None:
            meta.valid_to = span_to
        else:
            meta.valid_to = max(meta.valid_to, span_to)

    if meta.notice_kind == NoticeKind.unknown:
        meta.notice_kind = NoticeKind.promotion

    return meta
