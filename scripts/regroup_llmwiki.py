#!/usr/bin/env python3
"""Re-group llmwiki by_damdang using product codes → HISIS → cat.txt 분류담당.

Reusable content-organization pipeline (not one-off):

  python scripts/regroup_llmwiki.py --as-of 2026-06-17
  python scripts/regroup_llmwiki.py --as-of 2026-06-17 --source store
  python scripts/regroup_llmwiki.py --as-of 2026-06-17 --cache-only
  python scripts/regroup_llmwiki.py --as-of 2026-06-17 --refresh-cache

Reads events from existing llmwiki.json (default) or EventStore, enriches with
product-derived 분류담당, and rewrites:
  data/llmwiki/{as_of}/llmwiki.json
  data/llmwiki/{as_of}/llmwiki.md
  data/llmwiki/{as_of}/by_damdang/*.md

HISIS results are cached at data/cache/hisis_prd_damdang.json for offline re-runs.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief import config
from store_brief.llmwiki.load import events_from_llmwiki_json
from store_brief.llmwiki.regroup import regroup_llmwiki
from store_brief.store.db import EventStore

log = logging.getLogger(__name__)


def load_events(
    as_of: date,
    *,
    source: str,
    settings_path: str,
    data_dir: Path,
) -> list:
    if source == "store":
        settings = config.load_settings(settings_path)
        store = EventStore(settings.store_path)
        return store.load_recent(as_of, settings.retention_weeks)

    json_path = data_dir / "llmwiki" / as_of.isoformat() / "llmwiki.json"
    if not json_path.is_file():
        raise SystemExit(f"llmwiki.json not found: {json_path}")
    return events_from_llmwiki_json(json_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(
        description="Re-group llmwiki by product-derived 분류담당",
    )
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--settings", default="config/settings.yaml")
    ap.add_argument(
        "--source",
        choices=("json", "store"),
        default="store",
        help="Load events from EventStore (default) or llmwiki.json",
    )
    ap.add_argument("--cat", default="config/cat.txt", help="cat.txt path")
    ap.add_argument("--sql", default="config/extract_info.sql", help="HISIS SQL template")
    ap.add_argument(
        "--cache",
        default="data/cache/hisis_prd_damdang.json",
        help="PRD_CD lookup cache file",
    )
    ap.add_argument(
        "--cache-only",
        action="store_true",
        help="Use cache only (no Oracle); unresolved codes fall back to categories",
    )
    ap.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Re-query HISIS for all product codes found in events",
    )
    ap.add_argument(
        "--dry-run-lookup",
        action="store_true",
        help="Print SQL only; do not export",
    )
    args = ap.parse_args()

    as_of = date.fromisoformat(args.as_of)
    settings = config.load_settings(args.settings)
    data_dir = Path(settings.data_dir)

    events = load_events(
        as_of,
        source=args.source,
        settings_path=args.settings,
        data_dir=data_dir,
    )
    if not events:
        raise SystemExit(f"No events for as_of={as_of}")

    log.info("Loaded %d event(s) from %s", len(events), args.source)

    if args.dry_run_lookup:
        from store_brief.hisis.lookup import render_extract_sql
        from store_brief.llmwiki.regroup import collect_all_product_codes

        codes = collect_all_product_codes(events)
        log.info("Found %d unique product code(s)", len(codes))
        if codes:
            print(render_extract_sql(codes[:80], sql_path=args.sql))
        return

    paths, stats = regroup_llmwiki(
        events,
        data_dir / "llmwiki",
        as_of,
        cat_path=args.cat,
        sql_path=args.sql,
        cache_path=args.cache,
        cache_only=args.cache_only,
        refresh_cache=args.refresh_cache,
    )

    print(f"\nllmwiki regrouped: {len(events)} event(s)")
    print(f"  상품코드 추출: {stats.events_with_codes}건 / {stats.unique_codes}코드")
    print(f"  상품 기반 담당: {stats.events_product_routed}건 (HISIS 매칭 {stats.codes_resolved}코드)")
    print(f"  카테고리 fallback: {stats.events_category_routed}건")
    print(f"  JSON:       {paths['json']}")
    print(f"  Markdown:   {paths['markdown']}")
    print(f"  By 담당:    {paths['by_damdang_dir']}/")


if __name__ == "__main__":
    main()
