"""Tests for pptx/pdf PageRecord extraction."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.parse import pdf, pptx
from store_brief.parse.layout_schema import PageRecord


def test_pptx_fallback_builds_pages(monkeypatch):
    monkeypatch.setattr(pptx, "_rasterize_slides", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no com")))

    def fake_texts(path):
        return ["title slide", "body slide"]

    monkeypatch.setattr(pptx, "_extract_slide_texts", fake_texts)

    att = SimpleNamespace(id="p1_f.pptx", path="dummy.pptx", filename="f.pptx")
    pa = pptx.parse(att, tempfile.mkdtemp())
    assert len(pa.pages) == 2
    assert pa.pages[0] == PageRecord(index=1, ref="p1_f.pptx#s1", text="title slide")
    assert pa.pages[1].text == "body slide"
    assert "슬라이드 1" in pa.text


def test_pdf_builds_pages_per_page():
    try:
        import fitz
    except ImportError:
        return

    td = tempfile.mkdtemp()
    path = Path(td) / "t.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello PDF page one with enough text for extraction.")
    doc.save(str(path))
    doc.close()

    att = SimpleNamespace(id="p1_t.pdf", path=str(path), filename="t.pdf")
    pa = pdf.parse(att, td)
    assert len(pa.pages) == 1
    assert pa.pages[0].index == 1
    assert "Hello PDF" in pa.pages[0].text
