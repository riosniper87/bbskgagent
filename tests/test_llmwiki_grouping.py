"""Tests for llmwiki 담당 grouping."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.llmwiki.grouping import (  # noqa: E402
    MANAGER_KEY,
    damdang_for_event,
    group_by_damdang,
)


def ev(**kw):
    base = dict(id="e1", categories=["주방"], theme="테스트")
    base.update(kw)
    return SimpleNamespace(**base)


DM = {
    MANAGER_KEY: [],
    "주방": ["주방"],
    "IT": ["모바일·IT"],
    "대형가전": ["대형가전"],
}


def test_large_appliance_merged():
    from store_brief.llmwiki.grouping import load_damdang_map

    dm = load_damdang_map()
    assert "대형가전1" not in dm and "대형가전2" not in dm
    assert "대형가전" in dm


def test_damdang_for_kitchen_event():
    assert damdang_for_event(ev(categories=["주방"]), DM) == ["주방"]


def test_damdang_fallback():
    assert damdang_for_event(ev(categories=["기타"]), DM) == ["공통"]


def test_manager_gets_all():
    buckets = group_by_damdang([ev(id="a"), ev(id="b", categories=["모바일·IT"])], DM)
    assert len(buckets[MANAGER_KEY]) == 2
    assert len(buckets["IT"]) == 1


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_"):
            globals()[name]()
            print(f"ok {name}")
