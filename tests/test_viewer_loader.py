"""Tests for parse viewer loader."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.parse.layout_schema import PageRecord
from store_brief.viewer.loader import (
    ParseViewerLoader,
    _parse_text_pages,
    enrich_pages,
    pair_excel,
)


def test_parse_text_pages_legacy_pptx():
    text = "### 슬라이드 1\nhello\n\n### 슬라이드 2\nworld"
    images = [{"source_ref": "att#s1", "path": "images/a.png"}]
    pages = _parse_text_pages(text, images, "att", "pptx")
    assert len(pages) == 2
    assert pages[0].text == "hello"
    assert pages[0].image_path == "images/a.png"
    assert pages[1].text == "world"


def test_pair_excel_matches_sheet():
    images = [{"source_ref": "att#모델별", "path": "images/x.png"}]
    tables = [{"sheet": "모델별", "columns": ["a"], "rows": [["1"]]}]
    layout = [{"sheet": "모델별", "confidence": 0.9, "needs_review": False, "regions": []}]
    sheets = pair_excel("post1", "att", images, tables, layout, raw_sheets=[])
    assert len(sheets) == 1
    assert sheets[0].sheet == "모델별"
    assert sheets[0].image_url == "/media/parsed/post1/images/x.png"
    assert sheets[0].image_urls == ["/media/parsed/post1/images/x.png"]
    assert sheets[0].layout["confidence"] == 0.9


def test_enrich_pages_vlm():
    pages = [PageRecord(index=1, ref="att#s1", text="t")]
    vlm = {"att#s1": __import__("store_brief.viewer.loader", fromlist=["VlmNote"]).VlmNote(
        "att#s1", "표", "desc")}
    views = enrich_pages("p1", pages, vlm)
    assert views[0].vlm.description == "desc"


def test_loader_list_and_detail():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        parsed = root / "parsed"
        raw = root / "raw"
        post_id = "abc123"
        pdir = parsed / post_id
        (pdir / "images").mkdir(parents=True)
        (raw / "2026-06-04").mkdir(parents=True)
        (raw / "2026-06-04" / "posts.json").write_text(json.dumps([{
            "id": post_id,
            "title": "테스트 공지",
            "body": "본문 내용",
            "posted_date": "2026-06-04",
            "attachments": [],
        }]), encoding="utf-8")
        (pdir / "meta.json").write_text(json.dumps({
            "post_id": post_id,
            "title": "테스트 공지",
            "posted_date": "2026-06-04",
            "attachment_count": 1,
            "parsed_at": "2026-06-19T00:00:00+00:00",
            "records": ["attkey01"],
            "record_index": {
                "attkey01": {"kind": "excel", "needs_review": False},
            },
        }), encoding="utf-8")
        (pdir / "attkey01.json").write_text(json.dumps({
            "attachment_id": f"{post_id}_f.xlsx",
            "filename": "f.xlsx",
            "kind": "excel",
            "source_path": "x",
            "source_fingerprint": "a",
            "parsed_at": "2026-06-19T00:00:00+00:00",
            "text": "",
            "images": [],
            "tables": [{"sheet": "S1", "columns": ["c"], "rows": [["v"]]}],
            "raw_sheets": [],
            "layout": [],
            "pages": [],
            "parse_mode": "heuristic",
            "error": None,
        }), encoding="utf-8")

        loader = ParseViewerLoader(root)
        real_load_record = loader.store.load_record

        def _fail_load_record(*_args, **_kwargs):
            raise AssertionError("list_posts must not load full parse records")

        loader.store.load_record = _fail_load_record  # type: ignore[method-assign]
        posts = loader.list_posts(query="테스트")
        assert len(posts) == 1
        assert posts[0].kinds == ["excel"]
        loader.store.load_record = real_load_record  # type: ignore[method-assign]
        detail = loader.load_post_detail(post_id)
        assert detail.body == "본문 내용"
        assert detail.attachments[0].view_type == "excel"
        assert detail.attachments[0].sheets[0].tables[0]["columns"] == ["c"]
