"""Enrich product nodes from HISIS cache and damdang roster."""
from __future__ import annotations

import json
from pathlib import Path

from store_brief.llmwiki.grouping import FALLBACK_KEY, load_qa_damdang_roster, normalize_product_damdang


def load_hisis_cache(cache_path: str | Path) -> dict[str, dict]:
    p = Path(cache_path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def product_props(prd_cd: str, cache: dict[str, dict]) -> dict:
    entry = cache.get(prd_cd.strip().upper(), {})
    damdang = [normalize_product_damdang(d) for d in entry.get("damdang") or []]
    return {
        "prd_cd": prd_cd.strip().upper(),
        "prd_nm": entry.get("prd_nm"),
        "item_cd": entry.get("item_cd"),
        "damdang": damdang,
        "matched": bool(entry.get("matched") or damdang),
    }


def roster_damdangs(rnr_path: str = "data/rnr.txt") -> list[str]:
    return load_qa_damdang_roster(rnr_path)
