"""Fuzzy recall on top of deterministic mapping. Optional for the prototype."""
from __future__ import annotations

from store_brief.relevance import mapping


def candidate_events(employee, events, index=None, k: int = 10) -> list:
    """Deterministic matches, optionally unioned with vector-index neighbours."""
    base = mapping.relevant_events_for(employee, events)
    if index is None:
        return base
    query = f"{employee.branch} {' '.join(employee.categories)}"
    extra_ids = set(index.search(query, k=k))
    by_id = {e.id: e for e in events}
    merged = {e.id: e for e in base}
    for eid in extra_ids:
        if eid in by_id:
            merged.setdefault(eid, by_id[eid])
    return list(merged.values())
