"""Tests for cat.txt → 분류담당 resolution (no Oracle)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.hisis.cat_index import load_cat_index, resolve_cat_record
from store_brief.hisis.lookup import render_extract_sql


def test_load_and_resolve_exact_item_cd():
    root = Path(__file__).resolve().parents[1]
    index = load_cat_index(root / "config" / "cat.txt")
    rec = resolve_cat_record(item_cd="AEAAA", item_id=None, index=index)
    assert rec is not None
    assert rec.team_nm == "Hobby팀"
    assert "Hobby" in rec.damdang


def test_resolve_by_item_id():
    root = Path(__file__).resolve().parents[1]
    index = load_cat_index(root / "config" / "cat.txt")
    rec = resolve_cat_record(item_cd=None, item_id="00002874", index=index)
    assert rec is not None
    assert rec.item_cd == "AEAAA"


def test_render_extract_sql():
    sql = render_extract_sql(["ABC.AKOR", "O'Brien"])
    assert "'ABC.AKOR'" in sql
    assert "'O''Brien'" in sql
    assert "CS308S" not in sql
    assert "CM101C" not in sql
