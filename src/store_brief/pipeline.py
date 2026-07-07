"""Daily batch orchestration.

  python -m store_brief.pipeline --as-of 2026-06-17

Steps:
  1. ingest posts (+ attachments) for the day
  2. parse attachments (deterministic, NPU box)
  3. extract typed events (LLM/VLM on Spark)
  4. assign theme labels
  5. link policy version chains, then upsert into the store (sets first_seen/last_updated)
  6. prune events older than retention_weeks
  7. for each employee: relevance -> temporal sections -> compose -> write HTML

Steps 3-4 and report prose are the only model-dependent parts; 1-2, 5-6 and all
date/relevance filtering are deterministic.
"""

from __future__ import annotations

import argparse
import logging
import tempfile
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

from store_brief import config
from store_brief.extract import events as extract_events
from store_brief.ingest import attachments, board
from store_brief.llm.client import LLMClient
from store_brief.report import compose
from store_brief.review.fixed_layer import export_review_report, upsert_with_review
from store_brief.store import index as index_mod
from store_brief.store import versioning
from store_brief.store.db import EventStore
from store_brief.theme import classify


def run(
    as_of: date,
    settings_path: str = "config/settings.yaml",
    *,
    rnr_path: str = "config/rnr.csv",
    branch: str | None = None,
    backfill: bool = False,
    limit_posts: int | None = None,
    limit_employees: int | None = None,
) -> list[str]:
    settings = config.load_settings(settings_path)
    categories = config.load_categories("config/categories.yaml")
    roster = config.load_roster(rnr_path, branch=branch)
    if not roster:
        raise SystemExit(f"No employees found for branch={branch!r} in {rnr_path}")

    llm = LLMClient(base_url=settings.vllm_base_url, model=settings.model)
    store = EventStore(settings.store_path)

    existing = store.load_recent(as_of, settings.retention_weeks)

    raw_base = settings.data_dir + "/raw"
    if backfill:
        posts = board.load_posts_backfill(raw_base, as_of, limit=limit_posts)
    else:
        posts = board.load_posts(raw_base, as_of, limit=limit_posts)

    if not posts:
        raise SystemExit(f"No posts found under {raw_base} for as_of={as_of}")

    parsed_root = Path(settings.data_dir) / "parsed"
    # 1-4: ingest -> parse -> extract -> theme
    new_events = []
    try:
        with tempfile.TemporaryDirectory() as workdir:
            for post in posts:
                try:
                    parsed = attachments.resolve_parsed_attachments(
                        post, workdir, parsed_root=parsed_root,
                    )
                    evs = extract_events.extract_events(post, parsed, categories, llm)
                    for e in evs:
                        e.theme = classify.assign_theme(e, categories, llm)
                    new_events.extend(evs)
                except Exception as exc:
                    log.warning("skip post %s (%s): %s", post.id, post.title[:40], exc)
    finally:
        from store_brief.parse.excel_com import cleanup_excel_app
        from store_brief.parse.pptx import cleanup_ppt_app
        cleanup_excel_app()
        cleanup_ppt_app()

    # 5-6: version-link, review fixed layer, persist, prune
    versioning.link_versions(new_events, existing)
    if settings.review_fixed_layer:
        review_report = upsert_with_review(
            store, new_events, existing, categories, as_of,
            auto_adopt=settings.auto_adopt_proposals,
            categories_path="config/categories.yaml",
        )
        review_path = Path(settings.data_dir) / "llmwiki" / as_of.isoformat() / "adoption_log.json"
        export_review_report(review_report, review_path)
    else:
        for e in new_events:
            store.upsert(e, as_of)
    store.prune(as_of, settings.retention_weeks)

    # 7: build per-employee reports over the full recent window
    events = store.load_recent(as_of, settings.retention_weeks)
    idx = index_mod.VectorIndex(settings.embed_model)
    for e in events:
        idx.add(e)

    written = []
    roster_slice = roster[:limit_employees] if limit_employees else roster
    for emp in roster_slice:
        ctx = compose.build_context(emp, events, as_of, llm, index=idx,
                                    use_rerank=settings.use_rerank)
        written.append(compose.render(ctx, settings.reports_dir))
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--settings", default="config/settings.yaml")
    ap.add_argument("--rnr", default="config/rnr.csv", help="R&R file (csv or txt)")
    ap.add_argument("--branch", default=None, help="Branch code or name filter")
    ap.add_argument("--backfill", action="store_true",
                    help="Ingest all posts with posted_date <= as_of")
    ap.add_argument("--limit-posts", type=int, default=None, help="Cap posts processed")
    ap.add_argument("--limit-employees", type=int, default=None, help="Cap reports generated")
    args = ap.parse_args()
    out = run(
        date.fromisoformat(args.as_of),
        args.settings,
        rnr_path=args.rnr,
        branch=args.branch,
        backfill=args.backfill,
        limit_posts=args.limit_posts,
        limit_employees=args.limit_employees,
    )
    print(f"{len(out)} report(s) written:")
    for p in out:
        print(" ", p)


if __name__ == "__main__":
    main()
