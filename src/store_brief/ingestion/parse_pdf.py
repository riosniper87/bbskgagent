"""Page-level PDF normalization (native text + OCR fallback)."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from store_brief.ingestion.ocr import ocr_pixmap, tesseract_available
from store_brief.ingestion.schema import NormalizedRecord, Provenance
from store_brief.parse.store import StoredParseRecord

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40
MAX_PAGES = 50


def _is_scanned(text: str) -> bool:
    return len((text or "").strip()) < MIN_TEXT_CHARS


def _flatten_table(table: list[list]) -> str:
    if not table:
        return ""
    header = table[0] if table else []
    lines: list[str] = []
    if header:
        lines.append(" | ".join(str(c).strip() for c in header if c is not None))
    for row in table[1:]:
        cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _page_body(native_text: str, tables: list[str]) -> str:
    parts = [native_text.strip()] if native_text.strip() else []
    parts.extend(t for t in tables if t)
    return "\n".join(parts).strip()


def parse_pdf_path(path: str, post_id: str, attachment_id: str, filename: str) -> list[NormalizedRecord]:
    """Parse PDF file into page-level NormalizedRecords."""
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    records: list[NormalizedRecord] = []
    for i, page in enumerate(doc):
        if i >= MAX_PAGES:
            break
        idx = i + 1
        source_ref = f"{attachment_id}#p{idx}"
        native = page.get_text().strip()
        table_texts: list[str] = []
        try:
            for tbl in page.find_tables().tables:
                data = tbl.extract()
                flat = _flatten_table(data)
                if flat:
                    table_texts.append(flat)
        except Exception:
            pass

        extraction = "deterministic"
        review_flag = None
        body = _page_body(native, table_texts)

        if _is_scanned(body):
            if tesseract_available():
                try:
                    pix = page.get_pixmap(dpi=150)
                    ocr_text = ocr_pixmap(pix)
                    if ocr_text:
                        body = ocr_text
                        extraction = "ocr"
                    else:
                        review_flag = "ocr_empty"
                        extraction = "ocr"
                except Exception as exc:
                    log.warning("OCR failed page %s of %s: %s", idx, filename, exc)
                    review_flag = "ocr_failed"
                    extraction = "ocr"
            else:
                review_flag = "ocr_unavailable"
                extraction = "fallback"

        if not body.strip():
            continue

        title_match = re.search(r"^(.{4,80})$", body.split("\n", 1)[0].strip())
        title = title_match.group(1)[:120] if title_match else f"p.{idx}"

        records.append(NormalizedRecord(
            post_id=post_id,
            source_type="pdf_page",
            title=title,
            body=body,
            attachment_name=filename,
            provenance=Provenance(
                source_ref=source_ref,
                locator=f"p.{idx}",
                raw={"page": idx},
                extraction=extraction,  # type: ignore[arg-type]
            ),
            review_flag=review_flag,
        ))
    return records


def parse_pdf_from_record(record: StoredParseRecord, post_id: str) -> list[NormalizedRecord]:
    """Parse stored PDF record using file path or embedded page text."""
    path = record.source_path
    if path and Path(path).is_file():
        try:
            return parse_pdf_path(path, post_id, record.attachment_id, record.filename)
        except Exception as exc:
            log.warning("pdf parse failed for %s: %s", record.filename, exc)

    if record.pages:
        records: list[NormalizedRecord] = []
        for page in record.pages:
            ref = page.get("ref") if isinstance(page, dict) else page.ref
            text = (page.get("text") if isinstance(page, dict) else page.text) or ""
            m = re.search(r"#p(\d+)$", ref or "")
            idx = int(m.group(1)) if m else len(records) + 1
            if not text.strip():
                continue
            records.append(NormalizedRecord(
                post_id=post_id,
                source_type="pdf_page",
                title=f"p.{idx}",
                body=text.strip(),
                attachment_name=record.filename,
                provenance=Provenance(
                    source_ref=ref or f"{record.attachment_id}#p{idx}",
                    locator=f"p.{idx}",
                    raw={"page": idx},
                    extraction="deterministic",
                ),
            ))
        return records

    blocks = re.split(r"(?=###\s*p\d+)", record.text or "")
    out: list[NormalizedRecord] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        m = re.search(r"###\s*p(\d+)", block)
        if not m:
            continue
        idx = int(m.group(1))
        body = re.sub(r"###\s*p\d+\s*", "", block).strip()
        if not body:
            continue
        out.append(NormalizedRecord(
            post_id=post_id,
            source_type="pdf_page",
            title=f"p.{idx}",
            body=body,
            attachment_name=record.filename,
            provenance=Provenance(
                source_ref=f"{record.attachment_id}#p{idx}",
                locator=f"p.{idx}",
                raw={"page": idx},
                extraction="deterministic",
            ),
        ))
    return out
