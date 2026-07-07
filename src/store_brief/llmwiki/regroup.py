"""Re-group llmwiki by product-derived 분류담당 (reusable pipeline)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from store_brief.extract.schema import Event
from store_brief.hisis.batch_lookup import lookup_damdang_map
from store_brief.llmwiki.export import export_llmwiki
from store_brief.llmwiki.load import events_from_llmwiki_json
from store_brief.llmwiki.product_routing import (
    EnrichStats,
    enrich_events_with_product_damdang,
    extract_routing_product_codes,
)


def collect_all_product_codes(events: list[Event]) -> list[str]:
    codes: list[str] = []
    for event in events:
        codes.extend(extract_routing_product_codes(event))
    return list(dict.fromkeys(codes))


def regroup_llmwiki(
    events: list[Event],
    out_dir: str | Path,
    as_of: date,
    *,
    rnr_map_path: str = "config/rnr_category_map.yaml",
    cat_path: str | Path | None = None,
    sql_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    dry_run_lookup: bool = False,
    cache_only: bool = False,
    refresh_cache: bool = False,
) -> tuple[dict[str, Path], EnrichStats]:
    """Enrich events with product routing and re-export llmwiki artifacts."""
    all_codes = collect_all_product_codes(events)
    lookup = lookup_damdang_map(
        all_codes,
        cat_path=cat_path,
        sql_path=sql_path,
        cache_path=cache_path,
        dry_run=dry_run_lookup,
        cache_only=cache_only,
        refresh=refresh_cache,
    )
    stats = enrich_events_with_product_damdang(events, lookup)
    paths = export_llmwiki(
        events,
        out_dir,
        as_of,
        rnr_map_path=rnr_map_path,
        grouping="by_damdang_products",
        routing_stats=stats,
    )
    return paths, stats


def regroup_llmwiki_from_json(
    json_path: str | Path,
    out_dir: str | Path,
    as_of: date | None = None,
    **kwargs,
) -> tuple[dict[str, Path], EnrichStats]:
    path = Path(json_path)
    if as_of is None:
        data = json.loads(path.read_text(encoding="utf-8"))
        as_of = date.fromisoformat(data["as_of"])
    events = events_from_llmwiki_json(path)
    return regroup_llmwiki(events, out_dir, as_of, **kwargs)
