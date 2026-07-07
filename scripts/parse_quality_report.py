"""CLI: parse-quality report (review_flag / extraction distribution).

Usage:
    python scripts/parse_quality_report.py [--data-dir data] [--out PATH]

Writes JSON to ``<data-dir>/parsed/_quality/report.json`` by default and
prints a short summary. Run before/after parser changes to compare the
flagged-record ratio.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.ingestion.quality import build_quality_report


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse-quality report")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default=None, help="output JSON path")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    report = build_quality_report(data_dir)

    out = Path(args.out) if args.out else data_dir / "parsed" / "_quality" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"attachments scanned : {report['attachments_scanned']}")
    print(f"records total       : {report['records_total']}")
    print(f"flagged             : {report['flagged_total']} ({report['flagged_ratio']:.1%})")
    if report["flags"]:
        print("flags:")
        for flag, count in report["flags"].items():
            print(f"  {flag}: {count}")
    if report["extractions"]:
        print("extraction:")
        for kind, count in report["extractions"].items():
            print(f"  {kind}: {count}")
    print(f"report → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
