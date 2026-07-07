"""Group events by 분류담당 (R&R role) for llmwiki export."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

MANAGER_KEY = "점장"
FALLBACK_KEY = "공통"

# llmwiki export: collapse these 분류담당 keys into one section (roster map unchanged)
WIKI_DAMDANG_MERGE: dict[str, list[str]] = {
    "대형가전": ["대형가전1", "대형가전2"],
}


def normalize_wiki_damdang(tag: str) -> str:
    """Collapse roster keys (e.g. 대형가전1) into wiki section names."""
    for merged_name, sources in WIKI_DAMDANG_MERGE.items():
        if tag in sources:
            return merged_name
    return tag


def normalize_product_damdang(tag: str) -> str:
    """Map cat.txt 분류담당 → rnr.txt 업무 담당 (no 대형가전1/2 merge)."""
    return tag.strip()


def load_rnr_damdang_roster(path: str = "data/rnr.txt") -> list[str]:
    """Unique 분류담당 values from rnr.txt (점장 first)."""
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return []
    seen: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines()[2:]:
        cols = line.split("\t")
        if len(cols) < 8:
            continue
        tag = cols[7].strip()
        if tag and tag not in seen:
            seen.append(tag)
    if MANAGER_KEY in seen:
        return [MANAGER_KEY] + [k for k in seen if k != MANAGER_KEY]
    return seen


def load_qa_damdang_roster(path: str = "data/rnr.txt") -> list[str]:
    """QA roster: HR rnr.txt plus synthetic cross-cutting 담당 (공통)."""
    roster = [d for d in load_rnr_damdang_roster(path) if d != MANAGER_KEY]
    if FALLBACK_KEY not in roster:
        roster.append(FALLBACK_KEY)
    return roster


def product_damdang_for_codes(
    codes: list[str],
    lookup: dict[str, tuple[str, ...]],
) -> list[str]:
    """Union of rnr 분류담당 for resolved product codes."""
    tags: list[str] = []
    for code in codes:
        for raw in lookup.get(code, ()):
            norm = normalize_product_damdang(raw)
            if norm and norm not in tags:
                tags.append(norm)
    return tags


def product_codes_for_damdang(
    codes: list[str],
    damdang: str,
    lookup: dict[str, tuple[str, ...]],
) -> list[str]:
    """Codes on this slice that belong to the given 분류담당."""
    matched: list[str] = []
    for code in codes:
        tags = [normalize_product_damdang(t) for t in lookup.get(code, ())]
        if damdang in tags and code not in matched:
            matched.append(code)
    return matched


def load_damdang_map(map_path: str = "config/rnr_category_map.yaml") -> dict[str, list[str]]:
    """Return {분류담당: [event categories]}. 점장 maps to all categories (wildcard)."""
    from store_brief.config import load_rnr_category_map

    raw = load_rnr_category_map(map_path)
    result: dict[str, list[str]] = {}
    for key in raw.get("managers", []):
        result[key] = []  # empty = all events
    for damdang, entry in raw.get("mappings", {}).items():
        result[damdang] = list(entry.get("categories", []))

    for merged_name, sources in WIKI_DAMDANG_MERGE.items():
        cats: list[str] = []
        for src in sources:
            if src in result:
                cats = result[src]
                break
        for src in sources:
            result.pop(src, None)
        if cats:
            result[merged_name] = cats

    return result


def damdang_order(damdang_map: dict[str, list[str]]) -> list[str]:
    """Stable section order: 점장 first, then mapping keys."""
    keys = list(damdang_map.keys())
    if MANAGER_KEY in keys:
        rest = sorted(k for k in keys if k != MANAGER_KEY)
        return [MANAGER_KEY] + rest
    return sorted(keys)


def damdang_for_event(
    event: Any,
    damdang_map: dict[str, list[str]],
    *,
    product_only: bool = False,
) -> list[str]:
    """Which 분류담당 sections should include this event."""
    product_tags = getattr(event, "damdang_tags", None) or []
    if product_tags:
        normalized: list[str] = []
        for tag in product_tags:
            name = normalize_wiki_damdang(tag)
            if name not in normalized:
                normalized.append(name)
        return normalized or ([FALLBACK_KEY] if not product_only else [])

    if product_only:
        return []

    evt_cats = set(getattr(event, "categories", []) or [])
    matched: list[str] = []
    for damdang, cats in damdang_map.items():
        if damdang == MANAGER_KEY:
            continue
        if evt_cats & set(cats):
            matched.append(damdang)
    if not matched:
        matched.append(FALLBACK_KEY)
    return matched


def group_by_damdang(
    events: Iterable[Any],
    damdang_map: dict[str, list[str]] | None = None,
    *,
    product_only: bool = False,
) -> dict[str, list[Any]]:
    """Assign events to 분류담당 buckets (event may appear in multiple)."""
    dm = damdang_map or load_damdang_map()
    buckets: dict[str, list[Any]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)

    for e in events:
        eid = getattr(e, "id", id(e))
        targets = damdang_for_event(e, dm, product_only=product_only)
        if not targets:
            continue
        for damdang in targets:
            if eid not in seen[damdang]:
                buckets[damdang].append(e)
                seen[damdang].add(eid)
        if MANAGER_KEY in dm and eid not in seen[MANAGER_KEY]:
            buckets[MANAGER_KEY].append(e)
            seen[MANAGER_KEY].add(eid)

    if FALLBACK_KEY not in buckets:
        buckets[FALLBACK_KEY] = []

    order = damdang_order(dm)
    extras = sorted(k for k in buckets if k not in order and k != FALLBACK_KEY)
    order = order + extras
    if FALLBACK_KEY not in order:
        order = order + [FALLBACK_KEY]
    return {k: buckets.get(k, []) for k in order if k in buckets or k == FALLBACK_KEY}


def group_by_theme(events: Iterable[Any]) -> dict[str, list[Any]]:
    buckets: dict[str, list[Any]] = defaultdict(list)
    for e in events:
        theme = (getattr(e, "theme", None) or "미분류").strip() or "미분류"
        buckets[theme].append(e)
    return dict(sorted(buckets.items()))
