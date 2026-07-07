"""Deterministic R&R -> event matching.

This is the explainable core of relevance ('your role covers category X at branch Y, so
you get this event'). It uses no model. retrieve.py + rerank.py add fuzzy recall on top.
Reads attributes by name only, so it is testable without pydantic.
"""

from __future__ import annotations

from typing import Iterable

ALL_BRANCHES = "전점"


def _branch_matches(employee, event) -> bool:
    branches = getattr(event, "branches", []) or []
    return ALL_BRANCHES in branches or getattr(employee, "branch", None) in branches


def _category_matches(employee, event) -> bool:
    emp_cats = set(getattr(employee, "categories", []) or [])
    evt_cats = set(getattr(event, "categories", []) or [])
    return bool(emp_cats & evt_cats)


def relevant_events_for(employee, events: Iterable) -> list:
    """Events this employee should see, by R&R rule.

    - 점장 (is_store_manager): every event touching their branch (all categories).
    - category owner: events touching their branch AND at least one of their categories.
    """
    out = []
    for e in events:
        if not _branch_matches(employee, e):
            continue
        if getattr(employee, "is_store_manager", False):
            out.append(e)
        elif _category_matches(employee, e):
            out.append(e)
    return out


def explain(employee, event) -> str:
    """One-line human-readable reason an event was selected (for report transparency)."""
    if getattr(employee, "is_store_manager", False):
        return f"{employee.branch} 점장 — 지점 전체 사안"
    shared = set(getattr(employee, "categories", [])) & set(getattr(event, "categories", []))
    return f"{employee.branch} · 담당 카테고리({', '.join(sorted(shared))})"
