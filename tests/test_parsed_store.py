"""Tests for parsed attachment store."""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.parse.excel_tables import SheetTable
from store_brief.parse.layout_schema import RawSheet, TableLayoutSheet
from store_brief.parse.router import ParsedAttachment
from store_brief.parse.store import ParsedAttachmentStore, _att_key, export_review_markdown


def test_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        store = ParsedAttachmentStore(td)
        post = SimpleNamespace(id="p1", title="테스트", posted_date=__import__("datetime").date(2026, 6, 1))
        att = SimpleNamespace(id="p1_a.xlsx", filename="a.xlsx", kind="excel", path="dummy")
        pa = ParsedAttachment(
            "p1_a.xlsx",
            text="hello sheet",
            image_paths=[],
            tables=[SheetTable("s1", "제목", ["a", "b"], [["1", "2"]], 1, False)],
            raw_sheets=[RawSheet("s1", [["a", "b"], ["1", "2"]])],
            layouts=[TableLayoutSheet("s1", [], 1.0, False)],
            parse_mode="heuristic",
        )

        # fake source file for fingerprint
        src = Path(td) / "a.xlsx"
        src.write_bytes(b"x")
        att.path = str(src)

        store.save(post, att, pa)
        loaded = store.load_parsed_attachment("p1", att.id)
        assert loaded is not None
        assert loaded.text == "hello sheet"
        assert len(loaded.tables) == 1
        assert loaded.tables[0].columns == ["a", "b"]
        assert len(loaded.raw_sheets) == 1
        assert loaded.parse_mode == "heuristic"
        assert store.is_fresh("p1", att.id, src)


def test_review_export():
    with tempfile.TemporaryDirectory() as td:
        store = ParsedAttachmentStore(td)
        post = SimpleNamespace(id="p1", title="T", posted_date=__import__("datetime").date(2026, 6, 1))
        att = SimpleNamespace(id="p1_f", filename="f.csv", kind="excel", path="")
        src = Path(td) / "f.csv"
        src.write_text("a,b\n1,2", encoding="utf-8")
        att.path = str(src)
        store.save(post, att, ParsedAttachment("p1_f", text="data", image_paths=[]))
        store.update_meta(post, [_att_key(att.id)])
        idx = export_review_markdown(store, Path(td) / "_review")
        assert idx.exists()
        assert "p1.md" in idx.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_save_load_roundtrip()
    test_review_export()
    print("ok")
