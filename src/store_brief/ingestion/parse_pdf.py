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
# Hybrid pages: native text exists but images cover a large area — likely
# text + embedded scans/screenshots whose content the native layer misses.
HYBRID_TEXT_CHARS = 200
_MIN_IMAGE_AREA_RATIO = 0.10  # ignore small logos / decorations
_HYBRID_IMAGE_AREA_RATIO = 0.30  # total image coverage to trigger region OCR
_OCR_DPI = 150


def _is_scanned(text: str) -> bool:
    return len((text or "").strip()) < MIN_TEXT_CHARS


def _large_image_bboxes(page) -> list:
    """Bounding boxes of images big enough to plausibly hold content."""
    import fitz

    page_area = abs(page.rect) or 1.0
    boxes = []
    try:
        infos = page.get_image_info()
    except Exception:
        return []
    for info in infos:
        bbox = fitz.Rect(info.get("bbox", (0, 0, 0, 0)))
        if abs(bbox) / page_area >= _MIN_IMAGE_AREA_RATIO:
            boxes.append(bbox)
    return boxes


def _image_area_ratio(page, boxes) -> float:
    page_area = abs(page.rect) or 1.0
    return min(1.0, sum(abs(b) for b in boxes) / page_area)


def _ocr_image_regions(page, boxes) -> list[str]:
    """OCR only the image regions (no whole-page OCR → no text duplication)."""
    texts: list[str] = []
    for bbox in boxes:
        try:
            pix = page.get_pixmap(dpi=_OCR_DPI, clip=bbox)
            text = ocr_pixmap(pix)
        except Exception as exc:
            log.warning("region OCR failed on %s: %s", bbox, exc)
            continue
        if text:
            texts.append(text)
    return texts


def _assemble_body(native: str, tables: list[str], ocr_texts: list[str]) -> str:
    """Merge native text, extracted tables, and OCR text without losing any."""
    parts = [native.strip()] if native.strip() else []
    parts.extend(t for t in tables if t)
    parts.extend(f"[이미지 OCR] {t}" for t in ocr_texts if t)
    return "\n".join(parts).strip()


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
        except Exception as exc:
            log.warning("table extraction failed page %s of %s: %s", idx, filename, exc)

        extraction = "deterministic"
        review_flag = None
        hybrid = False
        ocr_texts: list[str] = []

        if _is_scanned(_page_body(native, table_texts)):
            # Whole page is a scan: OCR the full page, keep any extracted tables.
            if tesseract_available():
                try:
                    pix = page.get_pixmap(dpi=_OCR_DPI)
                    ocr_text = ocr_pixmap(pix)
                    if ocr_text:
                        ocr_texts = [ocr_text]
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
        elif len(native) < HYBRID_TEXT_CHARS and tesseract_available():
            # Hybrid page: thin native text + large image area → OCR image
            # regions only (avoids duplicating the native text layer).
            boxes = _large_image_bboxes(page)
            if boxes and _image_area_ratio(page, boxes) >= _HYBRID_IMAGE_AREA_RATIO:
                ocr_texts = _ocr_image_regions(page, boxes)
                if ocr_texts:
                    extraction = "ocr"
                    hybrid = True

        body = _assemble_body(native, table_texts, ocr_texts)

        if not body.strip() and review_flag is None:
            continue

        title_match = re.search(r"^(.{4,80})$", body.split("\n", 1)[0].strip())
        title = title_match.group(1)[:120] if title_match else f"p.{idx}"

        raw: dict = {"page": idx}
        if hybrid:
            raw["hybrid"] = True
        records.append(NormalizedRecord(
            post_id=post_id,
            source_type="pdf_page",
            title=title,
            body=body,
            attachment_name=filename,
            provenance=Provenance(
                source_ref=source_ref,
                locator=f"p.{idx}",
                raw=raw,
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
