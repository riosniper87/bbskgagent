#!/usr/bin/env python3

"""Parse raw attachments only (no LLM) and save for human review.



  python scripts/parse_attachments.py --as-of 2026-06-17 --backfill

  python scripts/parse_attachments.py --as-of 2026-06-17 --limit-posts 5 --force

  python scripts/parse_attachments.py --as-of 2026-06-17 --backfill --force --kinds excel --with-llm-tables

Excel sheet PNGs (COM) are generated only with --with-llm-tables. Otherwise openpyxl tables only.

  data/parsed/{post_id}/meta.json, {att_key}.json, images/

  data/parsed/_review/index.md, {post_id}.md

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

from store_brief.ingest import attachments, board

from store_brief.llm.client import LLMClient

from store_brief.parse.store import ParsedAttachmentStore, export_review_markdown



log = logging.getLogger(__name__)





def main():

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    ap = argparse.ArgumentParser(description="Parse attachments and save for review")

    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")

    ap.add_argument("--settings", default="config/settings.yaml")

    ap.add_argument("--backfill", action="store_true")

    ap.add_argument("--limit-posts", type=int, default=None)
    ap.add_argument(
        "--skip-posts",
        type=int,
        default=0,
        help="Skip first N posts (resume a interrupted backfill)",
    )

    ap.add_argument("--force", action="store_true", help="Re-parse even if cache is fresh")

    ap.add_argument(

        "--kinds",

        default=None,

        help="Comma-separated attachment kinds to parse (e.g. excel). Others are skipped.",

    )

    ap.add_argument(

        "--with-llm-tables",

        action="store_true",

        help="Use VLM to infer Excel table layout (requires vLLM; also enables Excel COM sheet PNGs)",

    )

    args = ap.parse_args()



    kind_filter = None

    if args.kinds:

        kind_filter = {k.strip() for k in args.kinds.split(",") if k.strip()}



    settings = config.load_settings(args.settings)

    as_of = date.fromisoformat(args.as_of)

    raw_base = settings.data_dir + "/raw"

    parsed_root = Path(settings.data_dir) / "parsed"

    store = ParsedAttachmentStore(parsed_root)



    llm = None

    if args.with_llm_tables:

        llm = LLMClient(base_url=settings.vllm_base_url, model=settings.model)



    if args.backfill:

        posts = board.load_posts_backfill(raw_base, as_of)

    else:

        posts = board.load_posts(raw_base, as_of)

    if args.skip_posts:

        posts = posts[args.skip_posts :]

    if args.limit_posts is not None:

        posts = posts[: args.limit_posts]

    if not posts:

        raise SystemExit(f"No posts under {raw_base} for as_of={as_of}")



    stats = {"posts": 0, "attachments": 0, "images": 0, "errors": 0}



    try:

        with tempfile.TemporaryDirectory() as workdir:

            total = len(posts) + args.skip_posts
            for i, post in enumerate(posts, args.skip_posts + 1):

                log.info("[%d/%d] %s", i, total, post.title[:50])

                parsed = attachments.parse_and_store_post(

                    post,

                    workdir,

                    store,

                    force=args.force,

                    kinds=kind_filter,

                    llm=llm,

                    with_llm_tables=args.with_llm_tables,

                )

                stats["posts"] += 1

                stats["attachments"] += len(parsed)

                stats["images"] += sum(len(p.image_paths) for p in parsed)

                import json

                from store_brief.parse.store import _att_key

                for att in post.attachments:

                    if kind_filter is not None and att.kind not in kind_filter:

                        continue

                    rp = store.record_path(post.id, _att_key(att.id))

                    if rp.exists():

                        rec = json.loads(rp.read_text(encoding="utf-8"))

                        if rec.get("error"):

                            stats["errors"] += 1

    finally:

        from store_brief.parse.excel_com import cleanup_excel_app

        from store_brief.parse.pptx import cleanup_ppt_app

        cleanup_excel_app()

        cleanup_ppt_app()



    review_index = export_review_markdown(store, parsed_root / "_review")



    print(f"\nParsed {stats['posts']} post(s)")

    print(f"  attachments OK: {stats['attachments']}")

    print(f"  images extracted: {stats['images']}")

    print(f"  parse errors:     {stats['errors']}")

    print(f"  stored under:     {parsed_root.resolve()}")

    print(f"  review index:     {review_index.resolve()}")





if __name__ == "__main__":

    main()


