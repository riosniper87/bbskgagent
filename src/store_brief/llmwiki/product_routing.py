"""Route llmwiki events to 분류담당 via product codes + HISIS/cat.txt."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from store_brief.extract.schema import Event
from store_brief.hisis.prd_codes import MAX_ROUTING_DAMDANGS, extract_prd_codes
from store_brief.llmwiki.grouping import normalize_wiki_damdang

RoutingBasis = Literal["product", "category"]


def extract_routing_product_codes(event: Event) -> list[str]:
    """Prefer codes from title, then summary, then excerpt (skip tables/attachments)."""
    title_codes = extract_prd_codes(event.title)
    if title_codes:
        return title_codes
    summary_codes = extract_prd_codes(event.summary)
    if summary_codes:
        return summary_codes
    return extract_prd_codes(event.raw_excerpt or "")


def damdang_tags_from_codes(
    codes: list[str],
    lookup: dict[str, tuple[str, ...]],
) -> list[str] | None:
    """Union of 분류담당 for resolved codes; None if nothing matched."""
    tags: list[str] = []
    for code in codes:
        for tag in lookup.get(code, ()):
            norm = normalize_wiki_damdang(tag)
            if norm not in tags:
                tags.append(norm)
    if not tags:
        return None
    if len(tags) > MAX_ROUTING_DAMDANGS:
        return None
    return tags


@dataclass
class EnrichStats:
    events_total: int = 0
    events_with_codes: int = 0
    events_product_routed: int = 0
    events_category_routed: int = 0
    unique_codes: int = 0
    codes_resolved: int = 0


def enrich_events_with_product_damdang(
    events: list[Event],
    lookup: dict[str, tuple[str, ...]],
) -> EnrichStats:
    """Set event.product_codes / damdang_tags / routing_basis."""
    stats = EnrichStats(events_total=len(events))
    all_codes: list[str] = []

    for event in events:
        codes = extract_routing_product_codes(event)
        event.product_codes = codes
        if codes:
            stats.events_with_codes += 1
            all_codes.extend(codes)

    stats.unique_codes = len(set(all_codes))
    stats.codes_resolved = sum(1 for c in set(all_codes) if lookup.get(c))

    for event in events:
        tags = damdang_tags_from_codes(event.product_codes, lookup)
        if tags:
            event.damdang_tags = tags
            event.routing_basis = "product"
            stats.events_product_routed += 1
        else:
            event.damdang_tags = []
            event.routing_basis = "category"
            stats.events_category_routed += 1

    return stats


LookupFn = Callable[[list[str]], dict[str, tuple[str, ...]]]
