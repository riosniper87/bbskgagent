#!/usr/bin/env python3
"""HISIS product lookup — model code (PRD_CD) → 품목코드 → cat.txt 분류담당.

Requires SSH tunnel to KRHIP (default 127.0.0.1:15211) and infra/.env credentials.

  python scripts/hisis_connect.py ABC123.AKOR
  python scripts/hisis_connect.py --dry-run ABC123.AKOR
  python scripts/hisis_connect.py --ping
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from store_brief.hisis.lookup import lookup_damdang_by_prd_codes


def _ping_oracle() -> int:
    from store_brief.hisis.oracle_env import configure_oracle_env

    configure_oracle_env(project_root=_ROOT)
    from as_analysis.io.oracle_extract import connect_oracle

    conn = connect_oracle()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM DUAL")
        row = cur.fetchone()
        print("Oracle OK:", row)
        return 0
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="HISIS PRD_CD → 분류담당 lookup")
    ap.add_argument("prd_codes", nargs="*", help="상품/모델 코드 (SC011M.PRD_CD)")
    ap.add_argument("--dry-run", action="store_true", help="Print SQL only, no DB")
    ap.add_argument("--ping", action="store_true", help="Test Oracle connection only")
    ap.add_argument("--cat", default=str(_ROOT / "config" / "cat.txt"))
    ap.add_argument("--sql", default=str(_ROOT / "config" / "extract_info.sql"))
    args = ap.parse_args()

    if args.ping:
        try:
            return _ping_oracle()
        except Exception as exc:
            print(f"Oracle connection failed: {exc}", file=sys.stderr)
            return 1

    if not args.prd_codes:
        ap.error("Provide at least one PRD_CD, or use --ping")

    try:
        results = lookup_damdang_by_prd_codes(
            list(args.prd_codes),
            cat_path=args.cat,
            sql_path=args.sql,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Lookup failed: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        return 0

    for i, res in enumerate(results):
        if i:
            print()
        for line in res.format_lines():
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
