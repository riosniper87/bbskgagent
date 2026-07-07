"""Link policy updates into version chains so diff.py can compare old vs new.

Prototype heuristic: a new 정책 event supersedes the most recent existing 정책 event that
shares a category and branch scope. Replace with an explicit key (e.g. a 'policy_code' the
extractor pulls from the post) once the data supports it.
"""
from __future__ import annotations


def _scope(e):
    return (frozenset(getattr(e, "categories", []) or []),
            frozenset(getattr(e, "branches", []) or []))


def link_versions(new_events, existing_events) -> None:
    """Mutate new_events in place: set version_of when a prior matching policy exists."""
    prior = [e for e in existing_events if _enum(getattr(e, "type", "")) == "정책"]
    for e in new_events:
        if _enum(getattr(e, "type", "")) != "정책":
            continue
        e_cats, e_branches = _scope(e)
        for old in prior:
            o_cats, o_branches = _scope(old)
            # shares at least one category AND one branch scope
            if old.id != e.id and (o_cats & e_cats) and (o_branches & e_branches):
                e.version_of = old.id
                break


def _enum(v):
    return getattr(v, "value", v)
