"""Excel/CSV -> sheet images + raw grids + optional VLM table layout."""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from store_brief.parse.apply_layout import apply_layouts
from store_brief.parse.excel_com import rasterize_or_empty
from store_brief.parse.excel_read import grid_snippet, read_workbook, workbook_to_raw_sheets
from store_brief.parse.excel_tables import (
    extract_tables_from_raw_sheets,
    extract_tables_from_workbook,
    tables_to_text,
)
from store_brief.parse.layout_schema import RawSheet, TableLayoutSheet
from store_brief.parse.router import ParsedAttachment

log = logging.getLogger(__name__)


def _is_drm(path: Path) -> bool:
    head = path.read_bytes()[:8]
    return len(head) >= 7 and head[0] == 0x9B and head[1:7] == b"DRMONE"


def _sheet_name_from_ref(ref: str, att_id: str) -> str:
    prefix = f"{att_id}#"
    if not ref.startswith(prefix):
        return ref
    tail = ref[len(prefix) :]
    if "_t" in tail:
        base, suffix = tail.rsplit("_t", 1)
        if suffix.isdigit():
            return base
    return tail


def _images_by_sheet(image_paths: list[tuple[str, str]], att_id: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for path, ref in image_paths:
        sheet = _sheet_name_from_ref(ref, att_id)
        if sheet not in out:
            out[sheet] = path
    return out


def _infer_layouts(
    raw_sheets: list[RawSheet],
    image_paths: list[tuple[str, str]],
    attachment,
    llm,
) -> list[TableLayoutSheet]:
    from store_brief.llm import table_layout

    by_sheet = _images_by_sheet(image_paths, attachment.id)
    layouts: list[TableLayoutSheet] = []
    for raw in raw_sheets:
        img = by_sheet.get(raw.sheet)
        if not img:
            continue
        layout = table_layout.infer_layout(
            img,
            sheet_name=raw.sheet,
            filename=attachment.filename,
            grid_snippet=grid_snippet(raw.rows),
            llm=llm,
        )
        if layout is not None:
            layouts.append(layout)
    return layouts


def parse(
    attachment,
    workdir: str,
    *,
    llm=None,
    with_llm_tables: bool = False,
) -> ParsedAttachment:
    path = Path(attachment.path)
    if _is_drm(path):
        raise ValueError(
            f"첨부가 DRM 암호화 상태입니다 ({attachment.filename}). "
            "ingest.zip에서 복호화본으로 remap 후 다시 파싱하세요."
        )
    if not zipfile.is_zipfile(path) and path.suffix.lower() in (".xlsx", ".xlsm", ".pptx"):
        raise ValueError(
            f"손상되었거나 암호화된 Office 파일입니다 ({attachment.filename}). ingest 재매핑 필요."
        )

    sheets = read_workbook(path)
    raw_sheets = workbook_to_raw_sheets(sheets)

    parse_mode = "heuristic"
    layouts: list[TableLayoutSheet] = []
    tables = extract_tables_from_workbook(sheets)

    if not tables and raw_sheets:
        tables = extract_tables_from_raw_sheets(raw_sheets)

    image_paths: list[tuple[str, str]] = []
    if with_llm_tables and llm is not None:
        image_paths = rasterize_or_empty(str(path), workdir, attachment.id)

    if with_llm_tables and llm is not None and raw_sheets and image_paths:
        layouts = _infer_layouts(raw_sheets, image_paths, attachment, llm)
        if layouts:
            tables = apply_layouts(raw_sheets, layouts)
            parse_mode = "vlm_layout"
        elif tables:
            parse_mode = "vlm_layout_fallback"
    elif tables:
        parse_mode = "heuristic"

    text = tables_to_text(tables) if tables else ""

    return ParsedAttachment(
        attachment_id=attachment.id,
        text=text,
        image_paths=image_paths,
        tables=tables,
        raw_sheets=raw_sheets,
        layouts=layouts,
        parse_mode=parse_mode,
    )
