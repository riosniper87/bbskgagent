"""Detect additions/changes to the fixed layer and gate store upserts.

Fixed layer (deterministic reporting fields):
  type, categories, branches, valid_from, valid_to, effective_date, version_of

Flexible layer (wiki prose — not gated here):
  theme, summary, tables, images, title

Review items are exported for human inspection; upsert policy is configurable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class ReviewAction(str, Enum):
    new_event = "신규"
    fixed_changed = "고정층_변경"
    unknown_category = "미등록_카테고리"
    date_inconsistent = "날짜_불일치"


FIXED_FIELDS = (
    "type", "categories", "branches",
    "valid_from", "valid_to", "effective_date", "version_of",
)


@dataclass
class FieldChange:
    field: str
    old: Any
    new: Any


@dataclass
class ReviewItem:
    event_id: str
    title: str
    source_post_id: str
    action: ReviewAction
    changes: list[FieldChange] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    upsert_allowed: bool = True
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "source_post_id": self.source_post_id,
            "action": self.action.value,
            "changes": [{"field": c.field, "old": _ser(c.old), "new": _ser(c.new)} for c in self.changes],
            "flags": self.flags,
            "upsert_allowed": self.upsert_allowed,
            "status": self.status,
        }


@dataclass
class ReviewReport:
    as_of: date
    items: list[ReviewItem] = field(default_factory=list)
    vocab_expansion_proposals: list[str] = field(default_factory=list)
    vocab_adopted: list[str] = field(default_factory=list)
    upserted_ids: list[str] = field(default_factory=list)
    held_ids: list[str] = field(default_factory=list)

    @property
    def needs_attention(self) -> list[ReviewItem]:
        return [i for i in self.items if i.flags or i.action != ReviewAction.new_event or i.changes]

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "summary": {
                "total": len(self.items),
                "new": sum(1 for i in self.items if i.action == ReviewAction.new_event),
                "fixed_changed": sum(1 for i in self.items if i.action == ReviewAction.fixed_changed),
                "upserted": len(self.upserted_ids),
                "held": len(self.held_ids),
            },
            "vocab_expansion_proposals": self.vocab_expansion_proposals,
            "vocab_adopted": self.vocab_adopted,
            "items": [i.to_dict() for i in self.items],
            "upserted_ids": self.upserted_ids,
            "held_ids": self.held_ids,
        }


def _enum(v: Any) -> str:
    return getattr(v, "value", v) if v is not None else None


def _ser(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return sorted(str(x) for x in v)
    return _enum(v) if hasattr(v, "value") else v


def _snapshot(e: Any) -> dict[str, Any]:
    return {f: _ser(getattr(e, f, None)) for f in FIXED_FIELDS}


def diff_fixed(old: Any, new: Any) -> list[FieldChange]:
    changes = []
    for f in FIXED_FIELDS:
        o, n = _ser(getattr(old, f, None)), _ser(getattr(new, f, None))
        if o != n:
            changes.append(FieldChange(field=f, old=o, new=n))
    return changes


def _date_inconsistent(e: Any) -> bool:
    vf, vt = getattr(e, "valid_from", None), getattr(e, "valid_to", None)
    return vf is not None and vt is not None and vf > vt


def review_events(
    new_events: Iterable[Any],
    existing_by_id: dict[str, Any],
    category_vocab: list[str],
    *,
    as_of: date,
    auto_approve_new: bool = True,
    block_on_fixed_change: bool = False,
) -> ReviewReport:
    """Compare extracted events against the store and build a review report."""
    vocab = set(category_vocab)
    report = ReviewReport(as_of=as_of)
    proposals: set[str] = set()

    for e in new_events:
        eid = getattr(e, "id", None)
        old = existing_by_id.get(eid)
        changes = diff_fixed(old, e) if old else []
        flags: list[str] = []

        for cat in getattr(e, "categories", []) or []:
            if cat not in vocab:
                proposals.add(cat)
                if ReviewAction.unknown_category.value not in flags:
                    flags.append(ReviewAction.unknown_category.value)

        if _date_inconsistent(e):
            flags.append(ReviewAction.date_inconsistent.value)

        if old is None:
            action = ReviewAction.new_event
            upsert = auto_approve_new
        elif changes:
            action = ReviewAction.fixed_changed
            upsert = not block_on_fixed_change
        else:
            action = ReviewAction.new_event  # re-extract, no fixed diff
            upsert = True

        item = ReviewItem(
            event_id=eid,
            title=getattr(e, "title", ""),
            source_post_id=getattr(e, "source_post_id", ""),
            action=action,
            changes=changes,
            flags=flags,
            upsert_allowed=upsert,
        )
        report.items.append(item)

    report.vocab_expansion_proposals = sorted(proposals)
    return report


def adopt_and_upsert(
    store,
    new_events: list[Any],
    existing: list[Any],
    category_vocab: list[str],
    as_of: date,
    *,
    categories_path: str = "config/categories.yaml",
) -> ReviewReport:
    """Record review deltas, adopt all proposals, upsert every new event."""
    from store_brief.config import apply_vocab_proposals

    by_id = {getattr(e, "id", None): e for e in existing}
    report = review_events(
        new_events, by_id, category_vocab, as_of=as_of,
        auto_approve_new=True, block_on_fixed_change=False,
    )
    for item in report.items:
        item.upsert_allowed = True
        item.status = "adopted"

    report.vocab_adopted = apply_vocab_proposals(categories_path, report.vocab_expansion_proposals)

    for e in new_events:
        store.upsert(e, as_of)
        report.upserted_ids.append(e.id)
    return report


def upsert_with_review(
    store,
    new_events: list[Any],
    existing: list[Any],
    category_vocab: list[str],
    as_of: date,
    *,
    auto_approve_new: bool = True,
    block_on_fixed_change: bool = False,
    auto_adopt: bool = False,
    categories_path: str = "config/categories.yaml",
) -> ReviewReport:
    """Review fixed-layer deltas; upsert per policy (or adopt all when auto_adopt)."""
    if auto_adopt:
        return adopt_and_upsert(
            store, new_events, existing, category_vocab, as_of,
            categories_path=categories_path,
        )
    by_id = {getattr(e, "id", None): e for e in existing}
    report = review_events(
        new_events, by_id, category_vocab, as_of=as_of,
        auto_approve_new=auto_approve_new,
        block_on_fixed_change=block_on_fixed_change,
    )
    allowed = {i.event_id for i in report.items if i.upsert_allowed}
    for e in new_events:
        if e.id in allowed:
            store.upsert(e, as_of)
            report.upserted_ids.append(e.id)
            for item in report.items:
                if item.event_id == e.id:
                    item.status = "adopted"
        else:
            report.held_ids.append(e.id)
    return report


def export_review_report(report: ReviewReport, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return out
