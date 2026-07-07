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


def test_assemble_body_merges_all_sources():
    from store_brief.ingestion.parse_pdf import _assemble_body

    body = _assemble_body("본문 텍스트", ["표1 | 값"], ["이미지 속 문구"])
    assert "본문 텍스트" in body
    assert "표1 | 값" in body
    assert "[이미지 OCR] 이미지 속 문구" in body
    # OCR must not replace native/table content
    assert body.index("본문 텍스트") < body.index("[이미지 OCR]")


def test_assemble_body_keeps_tables_without_ocr():
    from store_brief.ingestion.parse_pdf import _assemble_body

    assert _assemble_body("", ["표만 있음"], []) == "표만 있음"
    assert _assemble_body("", [], []) == ""


def _png_bytes(width: int = 200, height: int = 200) -> bytes:
    import fitz

    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height))
    pix.clear_with(90)
    return pix.tobytes("png")


@patch("store_brief.ingestion.parse_pdf.tesseract_available", return_value=True)
@patch("store_brief.ingestion.parse_pdf.ocr_pixmap", return_value="이미지 안 공지 문구")
def test_hybrid_page_merges_region_ocr(mock_ocr, mock_tess):
    import fitz

    from store_brief.ingestion.parse_pdf import parse_pdf_path

    doc = fitz.open()
    page = doc.new_page()  # 612 x 792
    native = "Store notice: fan display updated for June week two."
    assert 40 < len(native) < 200
    page.insert_text((72, 40), native)
    # image covering well over 30% of the page area
    page.insert_image(fitz.Rect(36, 100, 576, 700), stream=_png_bytes())
    path = Path(__file__).parent / "_tmp_hybrid.pdf"
    try:
        doc.save(str(path))
        doc.close()
        records = parse_pdf_path(str(path), "p1", "att#h", "hybrid.pdf")
        assert len(records) == 1
        rec = records[0]
        assert native in rec.body
        assert "[이미지 OCR] 이미지 안 공지 문구" in rec.body
        assert rec.provenance.extraction == "ocr"
        assert rec.provenance.raw.get("hybrid") is True
        assert rec.review_flag is None
    finally:
        if path.is_file():
            path.unlink()


@patch("store_brief.ingestion.parse_pdf.tesseract_available", return_value=True)
@patch("store_brief.ingestion.parse_pdf.ocr_pixmap", return_value="")
def test_text_page_with_small_image_stays_deterministic(mock_ocr, mock_tess):
    import fitz

    from store_brief.ingestion.parse_pdf import parse_pdf_path

    doc = fitz.open()
    page = doc.new_page()
    native = "Regular text page with a small logo image in the corner only."
    page.insert_text((72, 40), native)
    # tiny logo: < 10% page area → no hybrid OCR
    page.insert_image(fitz.Rect(560, 20, 600, 60), stream=_png_bytes(40, 40))
    path = Path(__file__).parent / "_tmp_logo.pdf"
    try:
        doc.save(str(path))
        doc.close()
        records = parse_pdf_path(str(path), "p1", "att#l", "logo.pdf")
        assert len(records) == 1
        assert records[0].provenance.extraction == "deterministic"
        assert "hybrid" not in records[0].provenance.raw
    finally:
        if path.is_file():
            path.unlink()


@patch("store_brief.ingestion.parse_pdf.tesseract_available", return_value=False)
def test_scanned_page_without_ocr_kept_with_flag(mock_tess):
    import fitz

    from store_brief.ingestion.parse_pdf import parse_pdf_path

    doc = fitz.open()
    doc.new_page()
    path = Path(__file__).parent / "_tmp_noocr.pdf"
    try:
        doc.save(str(path))
        doc.close()
        records = parse_pdf_path(str(path), "p1", "att#n", "scan.pdf")
        assert len(records) == 1
        assert records[0].review_flag == "ocr_unavailable"
        assert records[0].provenance.extraction == "fallback"
        assert records[0].body == ""
    finally:
        if path.is_file():
            path.unlink()
