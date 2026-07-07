#!/usr/bin/env python3
"""Generate sample HTML briefings from posts.json only (no vLLM).

Heuristically converts posts -> Events, then runs the same relevance/temporal/report
pipeline with a mock LLM that writes prose from the structured items.

Usage:
  python scripts/mock_daily.py --as-of 2026-06-17 --branch A6060E --rnr data/rnr.txt
  python scripts/mock_daily.py --as-of 2026-06-17 --branch A6060E --limit-employees 3
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief import config  # noqa: E402
from store_brief.ingest import board  # noqa: E402
from store_brief.mock.llm import MockLLM  # noqa: E402
from store_brief.mock.posts_to_events import posts_to_events  # noqa: E402
from store_brief.report import compose  # noqa: E402
from store_brief.theme import classify  # noqa: E402


def run(
    as_of: date,
    *,
    rnr_path: str = "data/rnr.txt",
    branch: str | None = None,
    limit_employees: int | None = None,
    reports_dir: str = "data/reports-mock",
    settings_path: str = "config/settings.yaml",
) -> list[str]:
    settings = config.load_settings(settings_path)
    categories = config.load_categories("config/categories.yaml")
    roster = config.load_roster(rnr_path, branch=branch)
    if not roster:
        raise SystemExit(f"No employees for branch={branch!r}")

    if limit_employees:
        roster = roster[:limit_employees]

    posts = board.load_posts_backfill(settings.data_dir + "/raw", as_of)
    if not posts:
        raise SystemExit(f"No posts in data/raw with posted_date <= {as_of}")

    events = posts_to_events(posts, as_of=as_of)
    llm = MockLLM()
    for e in events:
        e.theme = classify.assign_theme(e, categories, llm)

    written = []
    for emp in roster:
        # index=None: VectorIndex stub returns first-k events and pollutes relevance
        ctx = compose.build_context(emp, events, as_of, llm, index=None, use_rerank=False)
        written.append(compose.render(ctx, reports_dir))
    return written


def main():
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description="Mock daily briefing from posts.json only")
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--rnr", default=str(root / "data" / "rnr.txt"))
    ap.add_argument("--branch", default=None, help="Branch code or name")
    ap.add_argument("--limit-employees", type=int, default=5,
                    help="Max reports to generate (default 5)")
    ap.add_argument("--reports-dir", default=str(root / "data" / "reports-mock"))
    args = ap.parse_args()

    out = run(
        date.fromisoformat(args.as_of),
        rnr_path=args.rnr,
        branch=args.branch,
        limit_employees=args.limit_employees,
        reports_dir=args.reports_dir,
    )
    print(f"{len(out)} mock report(s) written:")
    for p in out:
        print(" ", p)


if __name__ == "__main__":
    main()
