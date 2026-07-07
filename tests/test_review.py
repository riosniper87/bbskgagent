"""Tests for fixed-layer review (no pydantic / LLM required)."""

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.review.fixed_layer import (  # noqa: E402
    ReviewAction,
    diff_fixed,
    review_events,
)

AS_OF = date(2026, 6, 17)
VOCAB = ["대형가전", "주방", "기타"]


def ev(**kw):
    base = dict(
        id="e1", type="공지", title="테스트", source_post_id="p1",
        categories=["대형가전"], branches=["전점"],
        valid_from=None, valid_to=None, effective_date=None, version_of=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_diff_fixed_detects_category_change():
    old = ev(categories=["대형가전"])
    new = ev(categories=["주방"])
    changes = diff_fixed(old, new)
    assert len(changes) == 1 and changes[0].field == "categories"


def test_review_new_event():
    report = review_events([ev(id="new1")], {}, VOCAB, as_of=AS_OF)
    assert len(report.items) == 1
    assert report.items[0].action == ReviewAction.new_event
    assert report.items[0].upsert_allowed is True


def test_review_fixed_change_blocked():
    old = ev(id="e1", valid_to=date(2026, 6, 10))
    new = ev(id="e1", valid_to=date(2026, 6, 20))
    report = review_events(
        [new], {"e1": old}, VOCAB, as_of=AS_OF, block_on_fixed_change=True,
    )
    assert report.items[0].action == ReviewAction.fixed_changed
    assert report.items[0].upsert_allowed is False


def test_review_unknown_category_flag():
    report = review_events(
        [ev(categories=["신규카테고리"])], {}, VOCAB, as_of=AS_OF,
    )
    assert "미등록_카테고리" in report.items[0].flags
    assert report.vocab_expansion_proposals == ["신규카테고리"]


def test_review_date_inconsistent():
    report = review_events(
        [ev(valid_from=date(2026, 6, 20), valid_to=date(2026, 6, 10))],
        {}, VOCAB, as_of=AS_OF,
    )
    assert "날짜_불일치" in report.items[0].flags


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_"):
            globals()[name]()
            print(f"ok {name}")
