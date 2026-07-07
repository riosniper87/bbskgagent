"""Timeline construction and 'latest state' resolution.

build_timeline orders events chronologically. resolve_current collapses each policy
version chain to its newest record, so a report shows the up-to-date policy rather than
every superseded revision (timeline을 보고 최신화).
"""

from __future__ import annotations

from datetime import date
from typing import Iterable


def _sort_key(e):
    return (
        getattr(e, "effective_date", None)
        or getattr(e, "valid_from", None)
        or getattr(e, "first_seen", None)
        or date.min
    )


def build_timeline(events: Iterable) -> list:
    """Chronological order, oldest first."""
    return sorted(events, key=_sort_key)


def resolve_current(events: Iterable) -> list:
    """Drop any event that has been superseded by a newer version in the same chain."""
    events = list(events)
    superseded = {getattr(e, "version_of", None) for e in events if getattr(e, "version_of", None)}
    return [e for e in events if getattr(e, "id", None) not in superseded]
