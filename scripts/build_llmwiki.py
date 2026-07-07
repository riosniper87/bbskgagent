#!/usr/bin/env python3
"""Parse attachments, extract typed events via vLLM, store + export llmwiki.

  python scripts/build_llmwiki.py --as-of 2026-06-17 --limit-posts 3 --backfill
  python scripts/build_llmwiki.py --as-of 2026-06-17 --export-only

Output:
  data/store.sqlite                    — canonical event store
  data/llmwiki/{as_of}/llmwiki.md      — 담당(분류담당)별 정리
  data/llmwiki/{as_of}/by_damdang/     — 담당별 개별 파일
  data/llmwiki/{as_of}/adoption_log.json — proposal 자동 반영 기록
"""
from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief import config
from store_brief.extract import events as extract_events
from store_brief.ingest import attachments, board
from store_brief.llm.client import LLMClient
from store_brief.llmwiki.export import export_llmwiki
from store_brief.review.fixed_layer import export_review_report, upsert_with_review
from store_brief.store import versioning
from store_brief.store.db import EventStore
from store_brief.theme import classify

log = logging.getLogger(__name__)


def build(
    as_of: date,
    settings_path: str = "config/settings.yaml",
    *,
    backfill: bool = False,
    limit_posts: int | None = None,
) -> tuple[list, object | None]:
    settings = config.load_settings(settings_path)
    categories = config.load_categories("config/categories.yaml")
    llm = LLMClient(base_url=settings.vllm_base_url, model=settings.model)
    store = EventStore(settings.store_path)
    existing = store.load_recent(as_of, settings.retention_weeks)

    raw_base = settings.data_dir + "/raw"
    if backfill:
        posts = board.load_posts_backfill(raw_base, as_of, limit=limit_posts)
    else:
        posts = board.load_posts(raw_base, as_of, limit=limit_posts)

    if not posts:
        raise SystemExit(f"No posts under {raw_base} for as_of={as_of}")

    parsed_root = Path(settings.data_dir) / "parsed"
    new_events = []
    try:
        with tempfile.TemporaryDirectory() as workdir:
            for i, post in enumerate(posts, 1):
                log.info("[%d/%d] %s", i, len(posts), post.title[:50])
                try:
                    parsed = attachments.resolve_parsed_attachments(
                        post, workdir, parsed_root=parsed_root,
                    )
                    log.info("  parsed %d attachment(s), %d image(s)",
                             len(parsed), sum(len(p.image_paths) for p in parsed))
                    evs = extract_events.extract_events(post, parsed, categories, llm)
                    for e in evs:
                        e.theme = classify.assign_theme(e, categories, llm)
                    new_events.extend(evs)
                    log.info("  -> %d event(s)", len(evs))
                except Exception as exc:
                    log.warning("  skip: %s", exc)
    finally:
        from store_brief.parse.excel_com import cleanup_excel_app
        from store_brief.parse.pptx import cleanup_ppt_app
        cleanup_excel_app()
        cleanup_ppt_app()

    versioning.link_versions(new_events, existing)
    review_report = None
    if settings.review_fixed_layer:
        review_report = upsert_with_review(
            store, new_events, existing, categories, as_of,
            auto_adopt=settings.auto_adopt_proposals,
            categories_path="config/categories.yaml",
        )
    else:
        for e in new_events:
            store.upsert(e, as_of)
    store.prune(as_of, settings.retention_weeks)

    return store.load_recent(as_of, settings.retention_weeks), review_report


def export_only(as_of: date, settings_path: str = "config/settings.yaml") -> list:
    settings = config.load_settings(settings_path)
    store = EventStore(settings.store_path)
    return store.load_recent(as_of, settings.retention_weeks)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Build llmwiki from raw posts + attachments")
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--settings", default="config/settings.yaml")
    ap.add_argument("--backfill", action="store_true",
                    help="Include all posts with posted_date <= as_of")
    ap.add_argument("--limit-posts", type=int, default=None)
    ap.add_argument("--export-only", action="store_true",
                    help="Re-export llmwiki from store (no LLM)")
    args = ap.parse_args()

    as_of = date.fromisoformat(args.as_of)
    if args.export_only:
        events = export_only(as_of, args.settings)
        review_report = None
    else:
        events, review_report = build(
            as_of, args.settings, backfill=args.backfill, limit_posts=args.limit_posts,
        )

    settings = config.load_settings(args.settings)
    out_dir = Path(settings.data_dir) / "llmwiki"
    paths = export_llmwiki(events, out_dir, as_of)

    print(f"\nllmwiki built: {len(events)} event(s)")
    print(f"  JSON:       {paths['json']}")
    print(f"  Markdown:   {paths['markdown']}")
    print(f"  By 담당:    {paths['by_damdang_dir']}/")
    if review_report is not None:
        review_path = export_review_report(
            review_report, out_dir / as_of.isoformat() / "adoption_log.json",
        )
        s = review_report.to_dict()["summary"]
        print(f"  Adoption:   {review_path}")
        print(f"              반영 {s['upserted']}건 (proposal 자동 차용)")
        if review_report.vocab_adopted:
            print(f"              카테고리 추가: {review_report.vocab_adopted}")


if __name__ == "__main__":
    main()
