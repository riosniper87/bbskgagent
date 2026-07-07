"""Row-level Excel normalization using profiles + existing parse utilities."""
from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from store_brief.ingestion.schema import NormalizedRecord, Provenance
from store_brief.parse.excel_read import read_workbook, workbook_to_raw_sheets
from store_brief.parse.excel_tables import (
    SheetTable,
    extract_tables_from_raw_sheets,
    extract_tables_from_workbook,
    merge_header_rows,
)
from store_brief.parse.layout_schema import RawSheet
from store_brief.parse.store import StoredParseRecord

log = logging.getLogger(__name__)

_PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
_MIN_ROW_BODY_LEN = 8
_MAX_ROW_BODY = 800
_MAX_ROWS_PER_TABLE = 250
_CATEGORY_ALIASES = ("구분", "구   분", "category")
_BRAND_MARKETING_RE = re.compile(r"브랜드\s*마케팅|브랜드커뮤니케이션", re.I)
_NUMERIC_CELL_RE = re.compile(r"^[\d.,\s%\-:]+$")


@dataclass
class XlsxProfile:
    name: str
    match: str
    category_col: str | None = None
    sheet_include: list[str] | None = None
    header_rows: list[int] | None = None
    data_start_row: int | None = None
    merge_fill_cols: list[str] | None = None
    damdang_from: str | None = None
    priority: int = 0


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", "", (h or "").strip())


def _load_profiles() -> list[XlsxProfile]:
    profiles: list[XlsxProfile] = []
    if not _PROFILES_DIR.is_dir():
        return profiles
    for path in sorted(_PROFILES_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles.append(XlsxProfile(
            name=str(raw.get("name") or path.stem),
            match=str(raw.get("match") or "*"),
            category_col=raw.get("category_col"),
            sheet_include=raw.get("sheet_include"),
            header_rows=raw.get("header_rows"),
            data_start_row=raw.get("data_start_row"),
            merge_fill_cols=raw.get("merge_fill_cols"),
            damdang_from=raw.get("damdang_from"),
            priority=int(raw.get("priority") or 0),
        ))
    profiles.sort(key=lambda p: (-p.priority, -len(p.match)))
    return profiles


def match_profile(filename: str, profiles: list[XlsxProfile] | None = None) -> XlsxProfile | None:
    profiles = profiles or _load_profiles()
    name = Path(filename).name
    best: XlsxProfile | None = None
    for p in profiles:
        if fnmatch.fnmatch(name, p.match) or fnmatch.fnmatch(name.lower(), p.match.lower()):
            if best is None or (p.priority, len(p.match)) > (best.priority, len(best.match)):
                best = p
    return best


def _find_category_col(columns: list[str], profile: XlsxProfile | None) -> int | None:
    targets = {_norm_header(profile.category_col)} if profile and profile.category_col else set()
    targets.update(_norm_header(a) for a in _CATEGORY_ALIASES)
    for i, col in enumerate(columns):
        if _norm_header(col) in targets:
            return i
    return None


def _row_body(
    columns: list[str],
    row: list[str],
    *,
    max_parts: int = 16,
    meaningful_headers: bool = False,
) -> str:
    parts: list[str] = []
    mostly_col = (
        not meaningful_headers
        and sum(1 for c in columns if (c or "").startswith("col_")) > len(columns) // 2
    )
    for col, val in zip(columns, row):
        val = (val or "").strip()
        if not val:
            continue
        col = (col or "").strip()
        if mostly_col and col.startswith("col_"):
            if _NUMERIC_CELL_RE.match(val) or len(val) <= 2:
                continue
        if col.startswith("col_") and not val:
            continue
        if col:
            parts.append(f"{col}: {val}")
        else:
            parts.append(val)
        if len(parts) >= max_parts:
            break
    body = " | ".join(parts)
    if len(body) > _MAX_ROW_BODY:
        body = body[:_MAX_ROW_BODY] + "…"
    return body


def _headline_from_row(columns: list[str], row: list[str], sheet: str) -> str:
    for col, val in zip(columns, row):
        val = (val or "").strip()
        if not val or len(val) < 4:
            continue
        ncol = _norm_header(col)
        if ncol in ("세부내용", "세부 내용", "내용", "제목", "품목", "모델명", "상품"):
            return val[:120]
        if "내용" in (col or ""):
            return val[:120]
    body = _row_body(columns, row)
    if body:
        return body[:120]
    return sheet[:120]


def _raw_sheets_from_record(record: StoredParseRecord) -> list[RawSheet]:
    if not record.raw_sheets:
        return []
    out: list[RawSheet] = []
    for s in record.raw_sheets:
        if isinstance(s, RawSheet):
            out.append(s)
        else:
            out.append(RawSheet(sheet=s.get("sheet", ""), rows=s.get("rows") or []))
    return out


def _normalize_row_width(row: list[str], width: int) -> list[str]:
    row = [str(c) if c is not None else "" for c in row]
    if len(row) < width:
        return row + [""] * (width - len(row))
    return row[:width]


def _is_summary_row(row: list[str]) -> bool:
    cells = [c.strip() for c in row if c and str(c).strip()]
    if not cells:
        return True
    if cells[0] in ("합계", "소계", "총계"):
        return True
    if len(cells) >= 2 and cells[1] == "합계":
        return True
    return False


def _find_merge_fill_indices(columns: list[str], fill_names: list[str]) -> list[int]:
    targets = {_norm_header(n) for n in fill_names}
    indices: list[int] = []
    for i, col in enumerate(columns):
        ncol = _norm_header(col)
        if ncol in targets or any(t in ncol for t in targets):
            indices.append(i)
    return indices


def _apply_merge_fill_cols(
    columns: list[str],
    rows: list[list[str]],
    fill_names: list[str],
) -> list[list[str]]:
    indices = _find_merge_fill_indices(columns, fill_names)
    if not indices:
        return rows
    out = [list(r) for r in rows]
    for col_idx in indices:
        last = ""
        for row in out:
            if col_idx >= len(row):
                continue
            val = row[col_idx].strip()
            if val:
                last = val
            elif last:
                row[col_idx] = last
    return out


def _columns_are_meaningful(columns: list[str]) -> bool:
    if not columns:
        return False
    named = sum(1 for c in columns if c and not str(c).startswith("col_"))
    return named > len(columns) // 2


def _extract_profile_tables(
    raw_sheets: list[RawSheet],
    profile: XlsxProfile,
) -> list[SheetTable]:
    """Build SheetTables using profile header_rows / data_start_row / merge_fill_cols."""
    if not profile.header_rows:
        return []

    tables: list[SheetTable] = []
    for raw in raw_sheets:
        if not _sheet_allowed(raw.sheet, profile):
            continue
        rows = raw.rows
        if not rows:
            continue

        header_indices = [i for i in profile.header_rows if 0 <= i < len(rows)]
        if not header_indices:
            continue

        columns = merge_header_rows([rows[i] for i in header_indices])
        if not columns:
            continue

        if profile.data_start_row is not None:
            data_start = profile.data_start_row
        else:
            data_start = max(header_indices) + 1

        data_rows: list[list[str]] = []
        for row in rows[data_start:]:
            norm = _normalize_row_width(row, len(columns))
            if not any(c.strip() for c in norm):
                continue
            if _is_summary_row(norm):
                continue
            data_rows.append(norm)

        if profile.merge_fill_cols:
            data_rows = _apply_merge_fill_cols(columns, data_rows, profile.merge_fill_cols)

        if not data_rows:
            continue

        total = len(data_rows)
        truncated = total > _MAX_ROWS_PER_TABLE
        if truncated:
            data_rows = data_rows[:_MAX_ROWS_PER_TABLE]

        tables.append(
            SheetTable(
                sheet=raw.sheet,
                title=rows[header_indices[0]][0].strip() if rows[header_indices[0]] else None,
                columns=columns,
                rows=data_rows,
                total_rows=total,
                truncated=truncated,
                region=0,
            ),
        )
    return tables


def _tables_from_record(
    record: StoredParseRecord,
    profile: XlsxProfile | None,
    *,
    data_dir: str | Path | None = None,
) -> list[SheetTable]:
    if profile and profile.header_rows:
        raw = _raw_sheets_from_record(record)
        if raw:
            profile_tables = _extract_profile_tables(raw, profile)
            if profile_tables:
                return profile_tables

    if record.tables:
        out: list[SheetTable] = []
        for idx, tbl in enumerate(record.tables):
            if not isinstance(tbl, dict):
                continue
            cols = list(tbl.get("columns") or [])
            rows = [list(r) for r in tbl.get("rows") or []]
            if not cols or not rows:
                continue
            out.append(SheetTable(
                sheet=str(tbl.get("sheet") or "Sheet1"),
                title=tbl.get("title"),
                columns=cols,
                rows=rows,
                total_rows=len(rows),
                truncated=bool(tbl.get("truncated")),
                region=int(tbl.get("region") or 0),
            ))
        if out:
            return out

    src = Path(record.source_path)
    if not src.is_file() and data_dir:
        src = Path(data_dir) / record.source_path
    if not src.is_file():
        return []

    try:
        sheets = read_workbook(src)
        if record.raw_sheets:
            raw = [
                RawSheet(sheet=s.get("sheet", ""), rows=s.get("rows") or [])
                for s in record.raw_sheets
            ]
            return extract_tables_from_raw_sheets(raw)
        return extract_tables_from_workbook(sheets)
    except Exception as exc:
        log.warning("parse_xlsx read failed %s: %s", record.filename, exc)
        return []


def _sheet_allowed(sheet: str, profile: XlsxProfile | None) -> bool:
    if not profile or not profile.sheet_include:
        return True
    return any(s in sheet for s in profile.sheet_include)


def _tables_to_records(
    tables: list[SheetTable],
    *,
    record: StoredParseRecord,
    post_id: str,
    profile: XlsxProfile | None,
    extraction: str,
    review_flag: str | None,
) -> list[NormalizedRecord]:
    out: list[NormalizedRecord] = []
    for table_idx, table in enumerate(tables):
        if not _sheet_allowed(table.sheet, profile):
            continue
        cat_idx = _find_category_col(table.columns, profile)
        row_limit = _MAX_ROWS_PER_TABLE if profile and profile.header_rows else len(table.rows)
        meaningful = _columns_are_meaningful(table.columns)
        for row_idx, row in enumerate(table.rows[:row_limit]):
            row = [str(c) if c is not None else "" for c in row]
            if not any(c.strip() for c in row):
                continue
            body = _row_body(table.columns, row, meaningful_headers=meaningful)
            if len(body.strip()) < _MIN_ROW_BODY_LEN:
                continue
            if profile and profile.header_rows:
                body = f"시트: {table.sheet} | {body}"
            category_value = None
            if cat_idx is not None and cat_idx < len(row):
                category_value = row[cat_idx].strip() or None
            row_key = row[0].strip() if row and row[0].strip().isdigit() else str(row_idx + 1)
            source_ref = f"{record.attachment_id}#row:{table.sheet}:{row_key}"
            locator = f"시트:{table.sheet} / 행:{row_key}"
            title = _headline_from_row(table.columns, row, table.sheet)
            raw_meta: dict[str, Any] = {
                "sheet": table.sheet,
                "row": row_key,
                "table_idx": table_idx,
            }
            if profile and profile.damdang_from:
                raw_meta["damdang_from"] = profile.damdang_from
            out.append(NormalizedRecord(
                post_id=post_id,
                source_type="excel_row",
                title=title,
                body=body,
                attachment_name=record.filename,
                category_value=category_value,
                provenance=Provenance(
                    source_ref=source_ref,
                    locator=locator,
                    raw=raw_meta,
                    extraction=extraction,  # type: ignore[arg-type]
                ),
                review_flag=review_flag,
            ))
    return out


def _fallback_records(
    record: StoredParseRecord,
    post_id: str,
) -> list[NormalizedRecord]:
    """Preserve legacy sheet/table blob cards when profile row parse yields nothing."""
    out: list[NormalizedRecord] = []
    for sheet in record.raw_sheets or []:
        name = sheet.get("sheet") if isinstance(sheet, dict) else sheet.sheet
        rows = sheet.get("rows") if isinstance(sheet, dict) else sheet.rows
        lines = ["\t".join(str(c) for c in row) for row in (rows or [])[:40]]
        text = f"시트: {name}\n" + "\n".join(lines)
        ref = f"{record.attachment_id}#sheet:{name}"
        out.append(NormalizedRecord(
            post_id=post_id,
            source_type="excel_fallback",
            title=str(name),
            body=text,
            attachment_name=record.filename,
            provenance=Provenance(
                source_ref=ref,
                locator=f"시트:{name}",
                raw={"sheet": name, "fallback": True},
                extraction="fallback",
            ),
            review_flag="xlsx_fallback",
        ))
    for idx, tbl in enumerate(record.tables or []):
        if isinstance(tbl, dict):
            title = tbl.get("title") or f"table{idx}"
            cols = tbl.get("columns") or []
            rows = tbl.get("rows") or []
        else:
            title = getattr(tbl, "title", None) or f"table{idx}"
            cols = getattr(tbl, "columns", [])
            rows = getattr(tbl, "rows", [])
        lines = [" | ".join(str(c) for c in cols)] + [
            " | ".join(str(c) for c in r) for r in rows[:20]
        ]
        ref = f"{record.attachment_id}#table{idx}"
        out.append(NormalizedRecord(
            post_id=post_id,
            source_type="excel_fallback",
            title=str(title),
            body=f"{title}\n" + "\n".join(lines),
            attachment_name=record.filename,
            provenance=Provenance(
                source_ref=ref,
                locator=f"table:{idx}",
                raw={"table_idx": idx, "fallback": True},
                extraction="fallback",
            ),
            review_flag="xlsx_fallback",
        ))
    if not out and record.text:
        out.append(NormalizedRecord(
            post_id=post_id,
            source_type="excel_fallback",
            title=record.filename,
            body=record.text[:1200],
            attachment_name=record.filename,
            provenance=Provenance(
                source_ref=record.attachment_id,
                locator="attachment",
                raw={"fallback": True},
                extraction="fallback",
            ),
            review_flag="xlsx_fallback",
        ))
    return out


def parse_xlsx_from_record(
    record: StoredParseRecord,
    post_id: str,
    *,
    data_dir: str | Path | None = None,
    profile: XlsxProfile | None = None,
) -> list[NormalizedRecord]:
    """Parse excel attachment into row-level NormalizedRecords."""
    profile = profile or match_profile(record.filename)
    if profile:
        tables = _tables_from_record(record, profile, data_dir=data_dir)
        records = _tables_to_records(
            tables,
            record=record,
            post_id=post_id,
            profile=profile,
            extraction="profile",
            review_flag=None,
        )
        if records:
            return records
        log.info(
            "profile %s matched %s but no rows; falling back",
            profile.name,
            record.filename,
        )

    fallback = _fallback_records(record, post_id)
    if fallback:
        return fallback
    return []


# infer_damdang_from_record moved to store_brief.llmwiki.enrichment
