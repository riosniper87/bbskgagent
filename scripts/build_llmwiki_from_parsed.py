#!/usr/bin/env python3
"""Build llmwiki from parsed/VLM slices + HISIS product-code routing (greenfield).

Does NOT read or fix the old Event-based llmwiki. Each card is one parsed
slide/sheet with product codes that resolve to cat.txt 분류담당 via HISIS.

  python scripts/build_llmwiki_from_parsed.py --as-of 2026-06-17
  python scripts/build_llmwiki_from_parsed.py --as-of 2026-06-17 --cache-only
  python scripts/build_llmwiki_from_parsed.py --as-of 2026-06-17 --no-vlm-index

Output:
  data/llmwiki/{as_of}/llmwiki.md
  data/llmwiki/{as_of}/llmwiki.json
  data/llmwiki/{as_of}/by_damdang/*.md
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief import config
from store_brief.llmwiki.from_parsed import build_llmwiki_from_parsed
from store_brief.llmwiki.vlm_index import load_vlm_index
from store_brief.store.db import EventStore

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Build llmwiki from parsed + product codes")
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--settings", default="config/settings.yaml")
    ap.add_argument("--cat", default="config/cat.txt")
    ap.add_argument("--sql", default="config/extract_info.sql")
    ap.add_argument("--cache", default="data/cache/hisis_prd_damdang.json")
    ap.add_argument("--cache-only", action="store_true")
    ap.add_argument("--refresh-cache", action="store_true")
    ap.add_argument(
        "--no-vlm-index",
        action="store_true",
        help="Skip VLM descriptions from store (use slide text only)",
    )
    args = ap.parse_args()

    as_of = date.fromisoformat(args.as_of)
    settings = config.load_settings(args.settings)

    vlm_index = None
    if not args.no_vlm_index:
        store = EventStore(settings.store_path)
        vlm_index = load_vlm_index(store, as_of, settings.retention_weeks)
        log.info("VLM index: %d source_ref(s) from store", len(vlm_index))

    paths, stats = build_llmwiki_from_parsed(
        as_of,
        data_dir=settings.data_dir,
        cat_path=args.cat,
        sql_path=args.sql,
        cache_path=args.cache,
        cache_only=args.cache_only,
        refresh_cache=args.refresh_cache,
        vlm_index=vlm_index,
    )

    print(f"\nllmwiki built from parsed: {stats.cards_written} card(s)")
    print(f"  게시물: {stats.posts_scanned} · 슬라이스: {stats.slices_scanned}")
    print(f"  상품코드 슬라이스: {stats.slices_with_codes} · 본문 카드: {stats.post_body_cards} · 코드: {stats.unique_codes} (HISIS {stats.codes_resolved})")
    print(f"  JSON:     {paths['json']}")
    print(f"  Markdown: {paths['markdown']}")
    print(f"  By 담당:  {paths['by_damdang_dir']}/")
    if "search_index" in paths:
        print(f"  Index:    {paths['search_index']}")


if __name__ == "__main__":
    main()
