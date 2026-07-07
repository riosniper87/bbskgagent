"""Time-based retrieval over WikiCards (or any duck-typed temporal record).

Designed for questions like:
  - "6월 중순 대형가전 판촉은?"  → active_on(query_date)
  - "지난달 공지 중 설치 변경 안내" → posted_between + semantic rank
  - "이번 개정에서 뭐가 바뀌었어?" → version_pairs
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def _get(obj, name: str, default=None):
    v = getattr(obj, name, default)
    if v is not None and name not in ("notice_kind", "valid_from", "valid_to", "effective_date", "version_of", "topic_key"):
        return v
    temporal = getattr(obj, "temporal", None)
    if temporal is not None:
        tv = getattr(temporal, name, None)
        if tv is not None:
            if name == "notice_kind":
                return getattr(tv, "value", tv)
            return tv
    if isinstance(obj, dict):
        temporal = obj.get("temporal") or {}
        if name in temporal and temporal[name] is not None:
            return temporal[name]
        return obj.get(name, default)
    props = getattr(obj, "props", None) or {}
    temporal = props.get("temporal") or {}
    if name in temporal and temporal[name] is not None:
        return temporal[name]
    if v is not None:
        return v
    return props.get(name, default)


def _notice_kind(obj) -> str | None:
    k = _get(obj, "notice_kind")
    if k is None and hasattr(obj, "temporal"):
        k = getattr(obj.temporal, "notice_kind", None)
        if k is not None:
            k = getattr(k, "value", k)
    return k


def _event_windows(obj) -> list[tuple[date, date | None]]:
    temporal = getattr(obj, "temporal", None)
    if temporal is not None and getattr(temporal, "event_windows", None):
        return list(temporal.event_windows)
    if isinstance(obj, dict):
        raw = (obj.get("temporal") or {}).get("event_windows") or []
    else:
        props = getattr(obj, "props", None) or {}
        raw = (props.get("temporal") or {}).get("event_windows") or []
    out: list[tuple[date, date | None]] = []
    for w in raw:
        if not isinstance(w, dict) or not w.get("from"):
            continue
        a = w["from"]
        b = w.get("to")
        out.append((
            date.fromisoformat(a) if isinstance(a, str) else a,
            date.fromisoformat(b) if isinstance(b, str) and b else None,
        ))
    return out


def _in_any_window(on: date, windows: list[tuple[date, date | None]]) -> bool:
    for start, end in windows:
        if start > on:
            continue
        if end and end < on:
            continue
        return True
    return False


def _valid_on_date(item, on: date) -> bool:
    windows = _event_windows(item)
    if windows:
        return _in_any_window(on, windows)
    start = _get(item, "valid_from")
    end = _get(item, "valid_to")
    if start and start > on:
        return False
    if end and end < on:
        return False
    return True


def active_on(items: Iterable, on: date) -> list:
    """Valid on `on`: any event_window or valid_from~valid_to contains the date."""
    return [item for item in items if _valid_on_date(item, on)]


def effective_on(items: Iterable, on: date) -> list:
    """Policy-style: effective_date <= on (or posted_date fallback)."""
    out = []
    for item in items:
        eff = _get(item, "effective_date")
        if eff is None:
            eff = _get(item, "posted_date")
        if eff is not None and eff <= on:
            out.append(item)
    return out


def posted_between(items: Iterable, start: date, end: date) -> list:
    """Board publish window — '한두 달 전에 올라온 공지'."""
    out = []
    for item in items:
        posted = _get(item, "posted_date")
        if posted is not None and start <= posted <= end:
            out.append(item)
    return out


def observable_on(items: Iterable, on: date) -> list:
    """Cards plausibly relevant when asking about date `on`.

    Published by `on`, and either in validity window or no window set.
    """
    out = []
    for item in items:
        posted = _get(item, "posted_date")
        if posted and posted > on:
            continue
        eff = _get(item, "effective_date")
        if eff and eff > on:
            continue
        windows = _event_windows(item)
        start = _get(item, "valid_from")
        end = _get(item, "valid_to")
        if windows or start or end:
            if not _valid_on_date(item, on):
                continue
        out.append(item)
    return out


def window_around(items: Iterable, center: date, *, days: int = 45) -> list:
    """Trailing window from center — e.g. ~two months of notices."""
    return posted_between(items, center - timedelta(days=days), center)


def version_pairs(items: Iterable) -> list[dict]:
    """Pairs (old, new) where new.version_of points to old.id."""
    by_id = {}
    for item in items:
        cid = _get(item, "id") or _get(item, "card_id")
        if cid:
            by_id[cid] = item
    pairs = []
    for item in items:
        prev_id = _get(item, "version_of")
        if not prev_id:
            continue
        pairs.append({"old": by_id.get(prev_id), "new": item})
    return pairs


def filter_by_notice_kind(items: Iterable, *kinds: str) -> list:
    want = set(kinds)
    return [i for i in items if _notice_kind(i) in want]
