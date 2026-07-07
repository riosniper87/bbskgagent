#!/usr/bin/env python3
"""Normalize sv게시판.zip + ingest.zip into data/raw/{date}/ layout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.ingest.sv_board import prepare_raw  # noqa: E402


def main():
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description="Prepare raw board data from zip exports")
    ap.add_argument("--sv-zip", default=str(root / "data" / "sv게시판.zip"))
    ap.add_argument("--ingest-zip", default=str(root / "data" / "ingest.zip"))
    ap.add_argument("--out", default=str(root / "data" / "raw"))
    ap.add_argument("--staging", default=None, help="Staging dir (default: data/staging)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stats = prepare_raw(
        args.sv_zip, args.ingest_zip, args.out,
        staging_dir=args.staging, dry_run=args.dry_run,
    )

    report = {
        "posts": stats.posts,
        "attachments_total": stats.attachments_total,
        "attachments_from_ingest": stats.attachments_from_ingest,
        "attachments_from_sv": stats.attachments_from_sv,
        "attachments_missing": stats.attachments_missing,
        "match_rate": (
            round((stats.attachments_from_ingest + stats.attachments_from_sv) / stats.attachments_total, 3)
            if stats.attachments_total else 1.0
        ),
        "dates": stats.dates,
        "errors": stats.errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if stats.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
