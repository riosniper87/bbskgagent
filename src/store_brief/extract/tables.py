"""Collect ExtractedTables from a set of events (theme-keyed grouping for the DB view).

The prototype keeps tables inline on each Event. This helper groups them by theme/category
so a later step can persist 'theme별 데이터 테이블'. Verification (confidence/needs_review)
is left to a future OCR<->VLM reconciliation pass.
"""
from __future__ import annotations

from collections import defaultdict


def group_tables_by_category(events) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for e in events:
        for t in getattr(e, "tables", []) or []:
            for cat in (getattr(e, "categories", []) or ["기타"]):
                out[cat].append(t)
    return dict(out)
