#!/usr/bin/env python3
"""Scan parsed excel attachments: group by filename pattern and sheet layout."""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from store_brief.parse.excel_tables import merge_header_rows


def _pattern(fn: str) -> str:
    fn_l = fn.lower()
    if "진열소진" in fn or "소진현황" in fn:
        return "진열소진"
    if "체크리스트" in fn:
        return "체크리스트"
    if "소진" in fn and "리스트" in fn:
        return "소진리스트"
    if "지사지점" in fn or "점별" in fn:
        return "지사지점현황"
    if "isp" in fn_l:
        return "ISP"
    if "행사" in fn or "판촉" in fn:
        return "행사판촉"
    if "재고" in fn:
        return "재고"
    return "기타"


def _sheet_signature(rows: list[list], sheet_name: str) -> dict:
    """Fingerprint layout: header row indices, col count, sample headers."""
    if not rows:
        return {"sheet": sheet_name, "empty": True}
    # find first non-empty row
    first_data = 0
    for i, row in enumerate(rows[:20]):
        if sum(1 for c in row if str(c).strip()) >= 2:
            first_data = i
            break
    # try dual-header at rows 5,6 (진열소진) and 3,4 (체크리스트)
    candidates = [(5, 6), (3, 4), (0,), (first_data,)]
    best_hdr = None
    best_cols: list[str] = []
    for hdr_rows in candidates:
        idx = [i for i in hdr_rows if i < len(rows)]
        if not idx:
            continue
        cols = merge_header_rows([rows[i] for i in idx])
        named = sum(1 for c in cols if c and not str(c).startswith("col_"))
        if named > len(best_cols) or (named == len(best_cols) and named > 3):
            best_hdr = idx
            best_cols = cols
    col_preview = [c.replace("\n", " ")[:40] for c in best_cols[:6]]
    width = max((len(r) for r in rows), default=0)
    return {
        "sheet": sheet_name,
        "rows": len(rows),
        "width": width,
        "header_rows": best_hdr,
        "col_count": len(best_cols),
        "col_preview": col_preview,
        "row5_preview": [str(c)[:20] for c in (rows[5] if len(rows) > 5 else [])[:6]],
    }


@dataclass
class FileInfo:
    filename: str
    post_id: str
    sheets: list[dict] = field(default_factory=list)


def main() -> None:
    parsed_root = _ROOT / "data" / "parsed"
    by_pattern: dict[str, list[FileInfo]] = defaultdict(list)
    seen_names: set[str] = set()

    for meta_path in sorted(parsed_root.glob("*/meta.json")):
        post_id = meta_path.parent.name
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for key in meta.get("records", []):
            rec_path = meta_path.parent / f"{key}.json"
            if not rec_path.is_file():
                continue
            try:
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if rec.get("kind") != "excel":
                continue
            fn = rec.get("filename", "")
            if fn in seen_names:
                continue
            seen_names.add(fn)
            pat = _pattern(fn)
            info = FileInfo(filename=fn, post_id=post_id)
            for s in rec.get("raw_sheets") or []:
                name = s.get("sheet", "")
                rows = s.get("rows") or []
                if pat == "진열소진" and "지사지점" not in str(name):
                    continue
                if pat == "체크리스트" and "체크" not in str(name):
                    continue
                info.sheets.append(_sheet_signature(rows, name))
            by_pattern[pat].append(info)

    print("=" * 70)
    print("EXCEL PROFILE CANDIDATE ANALYSIS")
    print("=" * 70)
    for pat in sorted(by_pattern.keys(), key=lambda p: -len(by_pattern[p])):
        items = by_pattern[pat]
        print(f"\n## {pat} ({len(items)} unique files)")
        # cluster by header signature
        clusters: dict[str, list[FileInfo]] = defaultdict(list)
        for it in items:
            if not it.sheets:
                key = "no_sheets"
            else:
                sig = it.sheets[0]
                key = f"hdr{sig.get('header_rows')}_cols{sig.get('col_count')}"
            clusters[key].append(it)
        for ckey, cluster in sorted(clusters.items(), key=lambda x: -len(x[1])):
            print(f"\n  Cluster [{ckey}] x{len(cluster)}")
            sample = cluster[0]
            if sample.sheets:
                s0 = sample.sheets[0]
                print(f"    header_rows: {s0.get('header_rows')}")
                print(f"    col_preview: {s0.get('col_preview')}")
            for it in cluster[:8]:
                print(f"    - {it.filename}")
            if len(cluster) > 8:
                print(f"    ... +{len(cluster) - 8} more")

    print("\n" + "=" * 70)
    print("PROFILE YAML FILES")
    print("=" * 70)
    prof_dir = _ROOT / "src" / "store_brief" / "ingestion" / "profiles"
    for yf in sorted(prof_dir.glob("*.yaml")):
        print(f"  {yf.name}")
    print("\nSee docs/excel-profiles.md for catalog.")


if __name__ == "__main__":
    main()
