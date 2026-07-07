"""Tests for parse viewer FastAPI routes."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytest = __import__("pytest")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from store_brief.viewer.app import create_app


def test_api_posts_and_media():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        parsed = root / "parsed"
        post_id = "post99"
        pdir = parsed / post_id
        img_dir = pdir / "images"
        img_dir.mkdir(parents=True)
        img = img_dir / "a.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        (pdir / "meta.json").write_text(json.dumps({
            "post_id": post_id,
            "title": "API Test",
            "posted_date": "2026-06-01",
            "attachment_count": 1,
            "parsed_at": "2026-06-19T00:00:00+00:00",
            "records": ["key1"],
        }), encoding="utf-8")
        (pdir / "key1.json").write_text(json.dumps({
            "attachment_id": f"{post_id}_f.pdf",
            "filename": "f.pdf",
            "kind": "pdf",
            "source_path": "x",
            "source_fingerprint": "b",
            "parsed_at": "2026-06-19T00:00:00+00:00",
            "text": "### p1\npage text",
            "images": [{"source_ref": f"{post_id}_f.pdf#p1", "path": "images/a.png"}],
            "tables": [],
            "raw_sheets": [],
            "layout": [],
            "pages": [{"index": 1, "ref": f"{post_id}_f.pdf#p1", "text": "page text", "image_path": "images/a.png"}],
            "parse_mode": "",
            "error": None,
        }), encoding="utf-8")

        client = TestClient(create_app(root))
        r = client.get("/api/posts")
        assert r.status_code == 200
        assert len(r.json()) == 1

        r2 = client.get(f"/api/posts/{post_id}")
        assert r2.status_code == 200
        assert r2.json()["title"] == "API Test"
        assert r2.json()["attachments"][0]["view_type"] == "slides"

        r3 = client.get(f"/media/parsed/{post_id}/images/a.png")
        assert r3.status_code == 200

        r4 = client.get("/media/parsed/post99/../secret")
        assert r4.status_code == 404
