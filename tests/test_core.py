"""Tests for the deterministic core (temporal + relevance).

Uses SimpleNamespace stand-ins so the date/matching logic is verifiable without pydantic
or a running model. Run: python -m pytest tests/  (or `python tests/test_core.py`).
"""

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.temporal import expiring, diff, timeline  # noqa: E402
from store_brief.relevance import mapping  # noqa: E402

AS_OF = date(2026, 6, 17)


def ev(**kw):
    base = dict(
        id=None, type="공지", title="", summary="", categories=[], branches=["전점"],
        valid_from=None, valid_to=None, effective_date=None, version_of=None,
        first_seen=None, last_updated=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_expiring_on():
    events = [
        ev(id="a", valid_to=date(2026, 6, 17)),   # ends today
        ev(id="b", valid_to=date(2026, 6, 18)),   # ends tomorrow
        ev(id="c", valid_to=None),                # no end
    ]
    got = {e.id for e in expiring.expiring_on(events, AS_OF)}
    assert got == {"a"}, got


def test_new_since():
    events = [
        ev(id="a", first_seen=date(2026, 6, 12)),  # within 7d
        ev(id="b", first_seen=date(2026, 6, 1)),   # too old
        ev(id="c", first_seen=date(2026, 6, 17)),  # today
    ]
    got = {e.id for e in expiring.new_since(events, AS_OF, days=7)}
    assert got == {"a", "c"}, got


def test_policy_change_pairs_and_resolve_current():
    old = ev(id="p1", type="정책", title="반품 정책 v1", first_seen=date(2026, 5, 1))
    new = ev(id="p2", type="정책", title="반품 정책 v2", version_of="p1",
             last_updated=date(2026, 6, 16), first_seen=date(2026, 6, 16))
    events = [old, new]
    pairs = diff.policy_change_pairs(events, AS_OF, days=7)
    assert len(pairs) == 1 and pairs[0]["new"].id == "p2" and pairs[0]["old"].id == "p1"
    current = {e.id for e in timeline.resolve_current(events)}
    assert current == {"p2"}, current  # superseded v1 dropped


def test_relevance_store_manager_vs_owner():
    sujin = ev()  # not an employee; build employees explicitly
    manager = SimpleNamespace(id="e1", name="점장", branch="강남", is_store_manager=True, categories=[])
    owner = SimpleNamespace(id="e2", name="대형가전담당", branch="강남",
                            is_store_manager=False, categories=["대형가전"])
    events = [
        ev(id="x", branches=["강남"], categories=["주방"]),       # 강남, 주방
        ev(id="y", branches=["강남"], categories=["대형가전"]),   # 강남, 대형가전
        ev(id="z", branches=["분당"], categories=["대형가전"]),   # 다른 지점
        ev(id="w", branches=["전점"], categories=["대형가전"]),   # 전점
    ]
    mgr = {e.id for e in mapping.relevant_events_for(manager, events)}
    own = {e.id for e in mapping.relevant_events_for(owner, events)}
    assert mgr == {"x", "y", "w"}, mgr      # 점장: 강남/전점 전부 (분당 제외)
    assert own == {"y", "w"}, own           # 담당: 강남/전점 ∩ 대형가전


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
