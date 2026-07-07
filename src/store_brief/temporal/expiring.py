"""Deterministic date-based queries over events.

These functions are the reason we extract typed temporal events instead of doing RAG
over raw text: 'what ends today' and 'what is new this week' become exact field
comparisons, not an LLM guess. Functions read attributes by name only (duck typing),
so they work on the pydantic Event or any stand-in object — and are testable without
pydantic installed.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def expiring_on(events: Iterable, as_of: date) -> list:
    """Promotions/events whose validity ends exactly on `as_of` (오늘로 끝나는 판촉/이벤트)."""
    return [e for e in events if getattr(e, "valid_to", None) == as_of]


def active_on(events: Iterable, as_of: date) -> list:
    """Events currently in effect on `as_of` (valid_from <= as_of <= valid_to)."""
    out = []
    for e in events:
        start = getattr(e, "valid_from", None)
        end = getattr(e, "valid_to", None)
        if start and start > as_of:
            continue
        if end and end < as_of:
            continue
        out.append(e)
    return out


def new_since(events: Iterable, as_of: date, days: int = 7) -> list:
    """Events first observed within the trailing window (이번주 신규).

    Uses `first_seen` (set by the store on initial insert), not the post date, so a post
    re-ingested days later does not falsely count as new.
    """
    window_start = as_of - timedelta(days=days)
    out = []
    for e in events:
        seen = getattr(e, "first_seen", None)
        if seen is not None and window_start <= seen <= as_of:
            out.append(e)
    return out
