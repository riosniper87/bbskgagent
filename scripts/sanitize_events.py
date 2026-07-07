#!/usr/bin/env python3
"""Repair event provenance in the store and re-export llmwiki.

Fixes:
  - events that attach every image/table from the post to every event
  - wrong source_post_id (e.g. 종이 줄자 on weekly guide post)
  - near-duplicate events across posts

  python scripts/sanitize_events.py --as-of 2026-06-17
  python scripts/sanitize_events.py --as-of 2026-06-17 --no-export
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief import config
from store_brief.extract.corpus import load_corpora_for_window
from store_brief.extract.provenance import sanitize_all_events
from store_brief.llmwiki.regroup import regroup_llmwiki
from store_brief.store.db import EventStore

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Sanitize event provenance and re-export llmwiki")
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--settings", default="config/settings.yaml")
    ap.add_argument("--no-export", action="store_true", help="Only fix store, skip llmwiki regroup")
    args = ap.parse_args()

    as_of = date.fromisoformat(args.as_of)
    settings = config.load_settings(args.settings)
    store = EventStore(settings.store_path)
    events = store.load_recent(as_of, settings.retention_weeks)
    if not events:
        raise SystemExit(f"No events in store for as_of={as_of}")

    corpora, parsed_by_post = load_corpora_for_window(
        as_of, data_dir=settings.data_dir,
    )
    cleaned, stats = sanitize_all_events(events, corpora, parsed_by_post)

    old_ids = {e.id for e in events}
    new_ids = {e.id for e in cleaned}
    removed = sorted(old_ids - new_ids)

    for event in cleaned:
        store.upsert(event, as_of)
    if removed:
        store.delete_many(removed)

    print(f"\nSanitized {stats.input_count} event(s)")
    print(f"  kept:       {stats.kept_count}")
    print(f"  dropped:    {stats.dropped_count} (incl. dedupe {stats.deduped_count})")
    print(f"  reassigned: {stats.reassigned_count}")
    print(f"  rescoped:   {stats.rescoped_count}")
    if removed:
        print(f"  removed ids: {', '.join(removed[:8])}" + (" …" if len(removed) > 8 else ""))

    if args.no_export:
        return

    paths, route_stats = regroup_llmwiki(
        cleaned,
        Path(settings.data_dir) / "llmwiki",
        as_of,
    )
    print(f"\nllmwiki re-exported: {len(cleaned)} event(s)")
    print(f"  상품 기반 담당: {route_stats.events_product_routed}건")
    print(f"  JSON:     {paths['json']}")
    print(f"  By 담당:  {paths['by_damdang_dir']}/")


if __name__ == "__main__":
    main()
