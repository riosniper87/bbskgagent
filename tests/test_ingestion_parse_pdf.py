"""Tests for ingestion/parse_pdf page-level normalization."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.ingestion.parse_pdf import (
    MIN_TEXT_CHARS,
    _is_scanned,
    parse_pdf_from_record,
)
from store_brief.ingestion.schema import NormalizedRecord, Provenance
from store_brief.parse.store import ParsedAttachmentStore

DATA = Path(__file__).resolve().parents[1] / "data"
STORE = ParsedAttachmentStore(DATA / "parsed")


def test_is_scanned_heuristic():
    assert _is_scanned("")
    assert _is_scanned("short")
    assert not _is_scanned("x" * (MIN_TEXT_CHARS + 1))


def test_parse_pdf_from_pages_fallback():
    record = MagicMock()
    record.source_path = ""
    record.attachment_id = "att_pdf#1"
    record.filename = "test.pdf"
    record.pages = [
        {"ref": "att_pdf#1#p1", "text": "정책 변경 안내\n6월 1일부터 시행됩니다." * 3},
        {"ref": "att_pdf#1#p2", "text": ""},
    ]
    record.text = ""
    records = parse_pdf_from_record(record, "post1")
    assert len(records) == 1
    assert records[0].source_type == "pdf_page"
    assert records[0].provenance.extraction == "deterministic"


def test_parse_pdf_from_text_blocks():
    record = MagicMock()
    record.source_path = ""
    record.attachment_id = "att2"
    record.filename = "doc.pdf"
    record.pages = []
    record.text = "### p1\n첫 페이지 본문입니다.\n\n### p2\n두 번째 페이지 내용입니다."
    records = parse_pdf_from_record(record, "post2")
    assert len(records) == 2
    assert all(r.provenance.locator.startswith("p.") for r in records)


def test_parse_real_pdf_if_available():
    """Use first pdf parsed record in corpus when present."""
    parsed_root = DATA / "parsed"
    if not parsed_root.is_dir():
        pytest.skip("parsed data not available")
    for meta_path in parsed_root.glob("*/meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        post_id = meta_path.parent.name
        for key in meta.get("records", []):
            rec = STORE.load_record(post_id, key)
            if rec and rec.kind == "pdf":
                records = parse_pdf_from_record(rec, post_id)
                assert isinstance(records, list)
                if records:
                    assert records[0].source_type == "pdf_page"
                return
    pytest.skip("no pdf parsed record in corpus")


@patch("store_brief.ingestion.parse_pdf.tesseract_available", return_value=True)
@patch("store_brief.ingestion.parse_pdf.ocr_pixmap", return_value="OCR 추출 텍스트입니다." * 5)
def test_scanned_page_uses_ocr(mock_ocr, mock_tess):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    path = Path(__file__).parent / "_tmp_scanned.pdf"
    try:
        doc.save(str(path))
        doc.close()
        from store_brief.ingestion.parse_pdf import parse_pdf_path

        records = parse_pdf_path(str(path), "p1", "att#1", "scan.pdf")
        assert records
        assert records[0].provenance.extraction == "ocr"
    finally:
        if path.is_file():
            path.unlink()
