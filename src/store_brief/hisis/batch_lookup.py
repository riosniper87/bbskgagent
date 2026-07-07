"""Batch PRD_CD → 분류담당 lookup with on-disk cache."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from store_brief.hisis.lookup import DamdangLookupResult, lookup_damdang_by_prd_codes


def _default_cache_path(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[3]
    return root / "data" / "cache" / "hisis_prd_damdang.json"


def load_lookup_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_lookup_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _entry_from_result(result: DamdangLookupResult) -> dict[str, Any]:
    return {
        "prd_nm": result.prd_nm,
        "item_cd": result.item_cd,
        "damdang": list(result.damdang),
        "matched": result.matched,
    }


def lookup_damdang_map(
    prd_codes: list[str],
    *,
    cat_path: str | Path | None = None,
    sql_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    dry_run: bool = False,
    cache_only: bool = False,
    refresh: bool = False,
    chunk_size: int = 80,
) -> dict[str, tuple[str, ...]]:
    """Resolve many PRD_CD values; persist hits in JSON cache for offline re-runs."""
    root = Path(__file__).resolve().parents[3]
    cache_file = Path(cache_path) if cache_path else _default_cache_path(root)
    cache = load_lookup_cache(cache_file)

    unique = list(dict.fromkeys(c.strip().upper() for c in prd_codes if c and c.strip()))
    if refresh:
        for code in unique:
            cache.pop(code, None)

    missing = [c for c in unique if c not in cache]
    if missing and not cache_only:
        for i in range(0, len(missing), chunk_size):
            chunk = missing[i : i + chunk_size]
            results = lookup_damdang_by_prd_codes(
                chunk,
                cat_path=cat_path,
                sql_path=sql_path,
                dry_run=dry_run,
            )
            if dry_run:
                return {code: () for code in unique}
            for result in results:
                cache[result.prd_cd] = _entry_from_result(result)
        save_lookup_cache(cache_file, cache)

    out: dict[str, tuple[str, ...]] = {}
    for code in unique:
        entry = cache.get(code, {})
        out[code] = tuple(entry.get("damdang") or ())
    return out
