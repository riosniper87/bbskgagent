#!/usr/bin/env python3
"""Verify prepared data and R&R without calling vLLM."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief import config  # noqa: E402
from store_brief.ingest import board  # noqa: E402


def main():
    root = Path(__file__).resolve().parents[1]
    raw = root / "data" / "raw"
    rnr = root / "data" / "rnr.txt"

    report: dict = {"ok": True, "checks": []}

    def check(name: str, ok: bool, detail: str = ""):
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            report["ok"] = False
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))

    # raw date folders
    day_dirs = sorted(p for p in raw.iterdir() if p.is_dir() and (p / "posts.json").exists())
    check("raw_day_dirs", len(day_dirs) >= 10, f"{len(day_dirs)} date folders")

    total_posts = 0
    total_atts = 0
    missing_atts = 0
    for d in day_dirs:
        posts = json.loads((d / "posts.json").read_text(encoding="utf-8"))
        total_posts += len(posts)
        for p in posts:
            for a in p.get("attachments", []):
                total_atts += 1
                if not (d / "attachments" / a).exists():
                    missing_atts += 1
    check("posts_total", total_posts >= 50, str(total_posts))
    check("attachments_on_disk", missing_atts == 0, f"missing={missing_atts}/{total_atts}")

  # rnr
    employees = config.load_roster_rnr_txt(str(rnr))
    check("rnr_employees", len(employees) > 2000, str(len(employees)))
    mgr = sum(1 for e in employees if e.is_store_manager)
    check("rnr_managers", mgr > 100, str(mgr))

    branches = Counter((e.branch_code, e.branch) for e in employees)
    top_code, top_name = branches.most_common(1)[0][0]
    branch_emps = config.load_roster(str(rnr), branch=top_code)
    check("branch_filter", len(branch_emps) > 5, f"{top_code} {top_name}: {len(branch_emps)}")

    backfill = board.load_posts_backfill(str(raw), date(2026, 6, 17))
    check("backfill_posts", len(backfill) >= 50, str(len(backfill)))

    out = root / "data" / "verify_report.json"
    report["summary"] = {
        "date_folders": len(day_dirs),
        "total_posts": total_posts,
        "attachments": total_atts,
        "rnr_employees": len(employees),
        "sample_branch": {"code": top_code, "name": top_name, "count": len(branch_emps)},
        "backfill_posts": len(backfill),
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {out}")
    if not report["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
