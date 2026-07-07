"""Tests for ingestion/parse_pptx slide-level normalization."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.ingestion.parse_pptx import parse_pptx_from_record
from store_brief.parse.store import ParsedAttachmentStore

DATA = Path(__file__).resolve().parents[1] / "data"
STORE = ParsedAttachmentStore(DATA / "parsed")
POST_ID = "6148b200b185"


def _load_pptx_record():
    meta_path = DATA / "parsed" / POST_ID / "meta.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in meta.get("records", []):
        rec = STORE.load_record(POST_ID, key)
        if rec and rec.kind == "pptx":
            return rec
    return None


def test_pptx_slide_records():
    record = _load_pptx_record()
    if record is None:
        pytest.skip("광고 PPTX parsed record not available")
    records = parse_pptx_from_record(record, POST_ID)
    assert len(records) > 0
    assert any(r.provenance.source_ref.endswith("#s1") for r in records)
    assert all(r.source_type == "pptx_slide" for r in records)
    assert all(r.provenance.extraction in ("deterministic", "fallback") for r in records)


def test_pptx_skips_boilerplate_slides():
    record = _load_pptx_record()
    if record is None:
        pytest.skip("광고 PPTX parsed record not available")
    records = parse_pptx_from_record(record, POST_ID)
    bodies = "\n".join(r.body for r in records).lower()
    assert "감사합니다" not in bodies or len(records) > 1
